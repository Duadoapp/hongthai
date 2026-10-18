"""資料來源。每個模組的 `fetch()` 回一個 dataclass，失敗丟該模組自己的例外（都繼承 `SourceError`），
由 `build.py` 接住並記成 `sources.<名稱>.ok=false`。"""

from __future__ import annotations

import logging
import ssl
import time

import requests
from requests.adapters import HTTPAdapter

log = logging.getLogger("hongthai")

USER_AGENT = "hongthai/0.1 (+https://github.com/Duadoapp/hongthai)"
TIMEOUT = 30


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
) -> requests.Response:
    """GET，失敗重試；把大小與耗時印在 log。`ok_404=True` 時 404 直接回傳不重試。"""
    hdrs = {"User-Agent": USER_AGENT, **(headers or {})}
    last: Exception | None = None
    for attempt in range(1, retries + 1):
        t0 = time.monotonic()
        try:
            r = (session or requests).get(url, params=params, headers=hdrs, timeout=TIMEOUT)
            if r.status_code == 404 and ok_404:
                return r
            r.raise_for_status()
            log.info(
                "GET %s → %d，%d bytes，%.1f 秒",
                r.url if len(r.url) < 200 else r.url[:200] + "…",
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
