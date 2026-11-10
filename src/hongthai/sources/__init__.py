"""資料來源。每個模組的 `fetch()` 回一個 dataclass，失敗丟該模組自己的例外（都繼承 `SourceError`），
由 `build.py` 接住並記成 `sources.<名稱>.ok=false`。"""

from __future__ import annotations

import logging
import ssl
import time

import requests
from requests.adapters import HTTPAdapter

from ..budget import add_bytes, check_cancelled

log = logging.getLogger("hongthai")

USER_AGENT = "hongthai/0.1 (+https://github.com/Duadoapp/hongthai)"
TIMEOUT = 30
# `http_get` 單一回應（解壓縮後）的上限（HD44）。2026-11-10 實測各呼叫端最大的一般回應：
# TDX FIDS 約 1.8 MB（gzip 傳輸約 104 KB）、Open-Meteo forecast 約 1.34 MB、SWIC 清單約 0.98 MB，
# 其他都在 0.7 MB 以下；取 5 倍以上湊整數。GRIB 下載另外傳 `GRIB_MAX_BYTES`
# （GFS、AIGFS、GEFS 的 `Range`、NOMADS GRIB filter）
MAX_BYTES = 10_000_000
# GRIB：實測最大的一段 `Range` 約 1.9 MB（GFS 0.25° 含海平面氣壓）、NOMADS filter 約 0.25 MB；
# GRIB 壓縮率隨欄位與打包方式變，相鄰幾筆併成一段時也會變大，多留一點
GRIB_MAX_BYTES = 50_000_000
CHUNK_BYTES = 64 * 1024


class SourceError(Exception):
    """來源抓取或解析失敗。`code` 是寫進 JSON 的簡短原因。"""

    code = "error"

    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        if code:
            self.code = code


class NonStrictTLSAdapter(HTTPAdapter):
    """照常驗證憑證，但不開 Python 3.13 起預設的 `VERIFY_X509_STRICT`。

    中央氣象署的憑證缺 Subject Key Identifier，strict 模式下會被擋
    （`Missing Subject Key Identifier`）；憑證鏈與主機名稱還是照常檢查。
    """

    @staticmethod
    def _context() -> ssl.SSLContext:
        ctx = ssl.create_default_context()
        ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
        return ctx

    def init_poolmanager(self, *args, **kwargs):
        kwargs["ssl_context"] = self._context()
        return super().init_poolmanager(*args, **kwargs)

    def proxy_manager_for(self, proxy, **proxy_kwargs):
        # 有 HTTPS_PROXY 時 requests 走這裡，不走 init_poolmanager
        proxy_kwargs["ssl_context"] = self._context()
        return super().proxy_manager_for(proxy, **proxy_kwargs)


def _short(url: str) -> str:
    return url if len(url) < 200 else url[:200] + "…"


def _read_body(r: requests.Response, max_bytes: int) -> int | None:
    """分塊讀完 `r`（`stream=True` 的回應），讀到的內容放回 `r._content`，之後 `.content`、`.text`、
    `.json()` 照常用。超過 `max_bytes` 就關連線、回傳已讀的 bytes（`Content-Length` 已經超過的不讀，
    回 0）；沒超過回 None。

    算的是解壓縮後的大小（`requests` 會自動解 gzip），`Content-Length` 是壓縮後的，所以有
    `Content-Length` 而且沒超過時還是邊讀邊數。
    """
    try:
        declared = int(r.headers.get("Content-Length") or -1)
    except ValueError:
        declared = -1
    if declared > max_bytes:
        r.close()
        return 0
    buf = bytearray()
    for chunk in r.iter_content(CHUNK_BYTES):
        buf += chunk
        if len(buf) > max_bytes:
            r.close()
            return len(buf)
    r._content = bytes(buf)
    r._content_consumed = True
    return None


def http_get(
    url: str,
    *,
    session: requests.Session | None = None,
    params: dict | None = None,
    headers: dict | None = None,
    retries: int = 3,
    backoff: float = 2.0,
    error: type[SourceError] = SourceError,
    ok_404: bool = False,
    timeout: float = TIMEOUT,
    max_bytes: int = MAX_BYTES,
) -> requests.Response:
    """GET，失敗重試；把大小與耗時印在 log。`ok_404=True` 時 404 直接回傳不重試。

    回應（解壓縮後）超過 `max_bytes` 就關連線、丟 `error(..., "too_large")`，不重試（HD44）。
    來源超過時間預算被放棄後，下一次請求前就停（`budget.check_cancelled`）。
    """
    hdrs = {"User-Agent": USER_AGENT, **(headers or {})}
    last: Exception | None = None
    for attempt in range(1, retries + 1):
        check_cancelled()
        t0 = time.monotonic()
        try:
            r = (session or requests).get(
                url, params=params, headers=hdrs, timeout=timeout, stream=True
            )
            over = _read_body(r, max_bytes)
            if over is not None:
                add_bytes(over)
                shown = _short(r.url or url)
                log.warning(
                    "GET %s 超過上限 %d bytes（已讀 %d bytes），放棄", shown, max_bytes, over
                )
                raise error(f"{shown}: 回應超過 {max_bytes} bytes", "too_large")
            add_bytes(len(r.content))
            if r.status_code == 404 and ok_404:
                return r
            r.raise_for_status()
            log.info(
                "GET %s → %d，%d bytes，%.1f 秒",
                _short(r.url),
                r.status_code,
                len(r.content),
                time.monotonic() - t0,
            )
            return r
        except requests.Timeout as e:
            last = error(f"{url}: timeout", "timeout")
            last.__cause__ = e
        except requests.HTTPError as e:
            last = error(f"{url}: HTTP {e.response.status_code}", f"http_{e.response.status_code}")
            last.__cause__ = e
            if e.response.status_code in (401, 403):
                break
        except requests.RequestException as e:
            last = error(f"{url}: {e.__class__.__name__}", "network")
            last.__cause__ = e
        log.warning("GET %s 第 %d 次失敗：%s", url, attempt, last)
        if attempt < retries:
            time.sleep(backoff * attempt)
    assert last is not None
    raise last
