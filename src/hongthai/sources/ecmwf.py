"""ECMWF 開放資料（CC BY 4.0）：HRES 控制報的 10 米陣風與系集的陣風超過門檻機率。

實測（2026-10-18，data.ecmwf.int 的 index 檔）：
- 系集機率產品 `stream="enfo"`、`type="ep"` 的參數是 `10fgg10`、`10fgg15`、`10fgg25`
  （10 米陣風 ≥ 10／15／25 m/s 的機率，單位 %），步長是 **24 小時窗**、每 12 小時一個
  （`"0-24"`、`"12-36"`…`"216-240"`），**只有 00／12Z** 有。所以不用自己拿系集成員算比例。
- HRES `stream="oper"`、`type="fc"` 的陣風參數依步長換名字：0–90 小時叫 `10fg`（每 3 小時一筆，
  但值是「前 1 小時」的最大陣風，因為 0–90 小時每小時後處理）；93–144 小時叫 `10fg3`（前 3 小時）；
  150 小時以後又叫 `10fg`（前 6 小時）。06／18Z 也有 oper，只到 144 小時。
- 出爐時間（UTC，HRES 全部步長）：00Z ≈ 07:35、06Z ≈ 12:30、12Z ≈ 19:35、18Z ≈ 00:30；
  系集機率 00Z ≈ 08:00、12Z ≈ 20:00。

所以 HRES 用最新一報（四個時次都可以），系集機率用最新的 00／12Z，`runs` 分開記。

側風（第二階段）：HRES 多抓 10 米風 `10u`／`10v`（瞬時值，和陣風同一組步長），每個陣風區間配上
區間結束那個步長的風向（真北）。全球檔每個參數每個步長約 0.5–1 MB，所以 HRES 下載量約變三倍。

入口與鏡像（H7，2026-10-18 build #4 從頭到尾 429 之後）：
- `ecmwf-opendata` 底下的 `multiurl` 預設遇到 429／5xx 每 120 秒重試、最多 500 次，而且照伺服器
  的 Retry-After 等，一次 build 就被這裡卡死。所以 Client 一律 `maximum_retries=3`、
  `retry_after=10`、`use_server_retry_after=False`（`ecmwf-opendata` 0.3.34 起才有這三個參數）；
  `latest()` 遇到重試用盡的 429／5xx 直接丟 `EcmwfError`（`http_<狀態碼>`），不要默默往前一天找、
  拿到舊的一報
- ECMWF 入口限 500 個同時連線，資料同步鏡像在 AWS、Google Cloud、Azure。找最新一報（只有幾個
  HEAD）用 `LATEST_SOURCES` 的順序：先問 `ecmwf`（最新），它失敗才問 `aws`；下載用
  `DOWNLOAD_SOURCES` 的順序：先 `aws`，那一報還沒同步到（404／空檔）或失敗就回 `ecmwf`，
  再失敗試 `google`。鏡像落後幾分鐘時因此不會拿到舊的一報而不自知
- 從 AWS 下載不重試（`DOWNLOAD_RETRY`）：S3 不接受一次多段 range，一報要發一百多個 range 請求；
  2026-10-18 實測約三成回 `503 Slow Down`，每次等 10 秒重試，148 秒後才失敗、預算就沒了。
  所以 AWS 第一個 503 就換下一個 source
- 實際從哪裡下載記在 `EcmwfData.mirror`（`sources.ecmwf.mirror`）；系集照同一套，記在 `ens_mirror`
"""

from __future__ import annotations

import contextlib
import functools
import io
import logging
import tempfile
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ..budget import add_bytes, check_cancelled, note
from ..config import Airport
from ..grib import read_points, wind_dir_from_uv
from ..timeutil import hours_between
from . import SourceError

log = logging.getLogger("hongthai")


class EcmwfError(SourceError):
    pass


@dataclass
class GustInterval:
    """某段時間（start, end] 內的最大陣風。"""

    start: datetime
    end: datetime
    gust_ms: float | None
    wdir: float | None = None  # 區間結束時的 10 米風向（度，真北）；沒有 10u／10v 時 None


@dataclass
class ProbWindow:
    """系集機率的 24 小時窗（start, end]，機率 0–1。"""

    start: datetime
    end: datetime
    p10: float | None
    p15: float | None
    p25: float | None


@dataclass
class EcmwfPoint:
    hres: list[GustInterval] = field(default_factory=list)
    ens: list[ProbWindow] = field(default_factory=list)


@dataclass
class EcmwfData:
    run: datetime
    ens_run: datetime | None
    ens_error: str | None
    points: dict[str, EcmwfPoint]
    bytes_downloaded: int = 0
    mirror: str | None = None  # HRES 實際從哪個 source 下載
    ens_mirror: str | None = None


HRES_GUST_PARAMS = ("10fg", "10fg3")
HRES_WIND_PARAMS = ("10u", "10v")
ENS_PARAMS = ("10fgg10", "10fgg15", "10fgg25")
ENS_WINDOW_H = 24
ENS_STRIDE_H = 12
ENS_MAX_END_H = 240

LATEST_SOURCES = ("ecmwf", "aws")
DOWNLOAD_SOURCES = ("aws", "ecmwf", "google")
CLIENT_RETRY = {"maximum_retries": 3, "retry_after": 10, "use_server_retry_after": False}
DOWNLOAD_RETRY: dict[str, dict] = {"aws": {"maximum_retries": 1}}
RETRIABLE_GIVE_UP = (429, 500, 502, 503, 504)


def hres_interval_hours(short_name: str, step: float) -> float:
    """HRES 陣風參數在該步長代表「前幾小時」的最大值。"""
    if short_name == "10fg3":
        return 3
    if short_name == "10fg6":
        return 6
    return 1 if step <= 90 else 6


def hres_steps(rel0: float, max_step: int, span_h: int = 120) -> list[int]:
    """每 3 小時一個步長，涵蓋 (rel0, rel0+span_h]；144 小時以後只有每 6 小時。"""
    first = int(rel0) + 3
    return [
        s
        for s in range(first, int(rel0) + span_h + 1, 3)
        if s <= max_step and (s <= 144 or s % 6 == 0)
    ]


def ens_windows(rel0: float, span_h: int = 120, slot_h: int = 6) -> list[str]:
    """完整包住任一 6 小時格的 24 小時窗（`"s-e"` 字串）。"""
    needed: set[int] = set()
    for k in range(span_h // slot_h):
        a, b = rel0 + k * slot_h, rel0 + (k + 1) * slot_h
        for s in range(0, ENS_MAX_END_H - ENS_WINDOW_H + 1, ENS_STRIDE_H):
            if s <= a and s + ENS_WINDOW_H >= b:
                needed.add(s)
    return [f"{s}-{s + ENS_WINDOW_H}" for s in sorted(needed)]


def parse_hres(path: str | Path, airports: list[Airport]) -> tuple[datetime, dict[str, list]]:
    pts = read_points(path, {a.icao: (a.lat, a.lon) for a in airports})
    run = None
    out: dict[str, list[GustInterval]] = {}
    for icao, series in pts.items():
        uv: dict[str, dict[float, float | None]] = {
            k: dict(zip(series[k].steps, series[k].values, strict=True))
            for k in HRES_WIND_PARAMS
            if k in series
        }
        intervals = []
        for short, s in series.items():
            if short not in HRES_GUST_PARAMS:
                continue
            run = s.run
            for step, v in zip(s.steps, s.values, strict=True):
                end = s.run + timedelta(hours=step)
                start = end - timedelta(hours=hres_interval_hours(short, step))
                wdir = wind_dir_from_uv(uv.get("10u", {}).get(step), uv.get("10v", {}).get(step))
                intervals.append(GustInterval(start, end, v, wdir))
        out[icao] = sorted(intervals, key=lambda g: g.end)
    if run is None:
        raise EcmwfError("HRES GRIB 裡沒有陣風資料", "empty")
    return run, out


def parse_ens(path: str | Path, airports: list[Airport]) -> tuple[datetime, dict[str, list]]:
    pts = read_points(path, {a.icao: (a.lat, a.lon) for a in airports})
    run = None
    out: dict[str, list[ProbWindow]] = {}
    for icao, series in pts.items():
        by_end: dict[float, dict[str, float | None]] = {}
        for short, s in series.items():
            run = s.run
            for step, v in zip(s.steps, s.values, strict=True):
                by_end.setdefault(step, {})[short] = None if v is None else v / 100
        windows = []
        for end_step, vals in sorted(by_end.items()):
            end = run + timedelta(hours=end_step)
            windows.append(
                ProbWindow(
                    end - timedelta(hours=ENS_WINDOW_H),
                    end,
                    vals.get("10fgg10"),
                    vals.get("10fgg15"),
                    vals.get("10fgg25"),
                )
            )
        out[icao] = windows
    if run is None:
        raise EcmwfError("系集機率 GRIB 裡沒有資料", "empty")
    return run, out


@functools.cache
def _client_class():
    from ecmwf.opendata import Client

    class BoundedClient(Client):
        """`latest()` 與 index 請求重試用盡後還是 429／5xx 時丟例外，不要當成「這一報不存在」。"""

        def _robust(self, call):
            inner = super()._robust(call)

            def wrapped(url, *args, **kwargs):
                r = inner(url, *args, **kwargs)
                if r.status_code in RETRIABLE_GIVE_UP:
                    raise EcmwfError(f"{url}: HTTP {r.status_code}", f"http_{r.status_code}")
                return r

            return wrapped

    return BoundedClient


def _client(source: str, **retry):
    return _client_class()(source=source, **{**CLIENT_RETRY, **retry})


def _code(e: BaseException) -> str:
    code = getattr(e, "code", None)
    if isinstance(code, str) and code:
        return code
    status = getattr(getattr(e, "response", None), "status_code", None)
    if status is not None:
        return f"http_{status}"
    return e.__class__.__name__


def _latest(clients, **request) -> datetime:
    """依 `LATEST_SOURCES` 找最新一報。

    全部失敗丟 `no_run`；最後一個是 429／5xx 用盡時丟它的代碼（例如 `http_429`）。
    """
    last: BaseException | None = None
    for src in LATEST_SOURCES:
        check_cancelled()
        t0 = time.monotonic()
        try:
            run = clients(src).latest(**request)
        except Exception as e:  # ecmwf-opendata 找不到時丟一般例外
            log.warning(
                "ECMWF latest %s（%s）失敗，%.1f 秒：%s",
                request.get("stream"),
                src,
                time.monotonic() - t0,
                e,
            )
            last = e
            continue
        log.info(
            "ECMWF latest %s（%s）：%s，%.1f 秒",
            request.get("stream"),
            src,
            run,
            time.monotonic() - t0,
        )
        return run.replace(tzinfo=UTC)
    code = _code(last) if isinstance(last, EcmwfError) else "no_run"
    raise EcmwfError(f"找不到最新 {request.get('stream')}：{last}", code) from last


def _retrieve(client, target: Path, **request) -> int:
    t0 = time.monotonic()
    target.unlink(missing_ok=True)  # multiurl 看到舊檔會接著續傳，換鏡像時不能留上一個的殘檔
    # multiurl 的 tqdm 進度條寫死 disable=False，會在 Actions log 洗版；大小與耗時由下面的 log 印
    with contextlib.redirect_stderr(io.StringIO()):
        client.retrieve(target=str(target), **request)
    size = target.stat().st_size if target.exists() else 0
    add_bytes(size)
    log.info(
        "ECMWF %s %s：%d bytes，%.1f 秒",
        request.get("stream"),
        request.get("type"),
        size,
        time.monotonic() - t0,
    )
    if size == 0:
        raise EcmwfError(f"ECMWF {request.get('stream')} 下載是空的", "empty")
    return size


def _download(clients, target: Path, **request) -> tuple[int, str]:
    """依 `DOWNLOAD_SOURCES` 下載；回傳（大小, 實際的 source）。全部失敗丟最後一個錯誤的代碼。"""
    last: BaseException | None = None
    for src in DOWNLOAD_SOURCES:
        check_cancelled()
        note(mirror=src)
        t0 = time.monotonic()
        try:
            client = clients(src, **DOWNLOAD_RETRY.get(src, {}))
            return _retrieve(client, target, **request), src
        except Exception as e:  # 404（鏡像還沒同步到）、429、空檔……換下一個
            log.warning(
                "ECMWF %s 從 %s 下載失敗，%.1f 秒：%s",
                request.get("stream"),
                src,
                time.monotonic() - t0,
                e,
            )
            last = e
    assert last is not None
    raise EcmwfError(f"ECMWF {request.get('stream')} 每個 source 都下載失敗：{last}", _code(last))


def fetch(airports: list[Airport], slot0: datetime, workdir: str | Path | None = None) -> EcmwfData:
    """抓最新 HRES 與最新 00／12Z 系集機率，涵蓋 slot0 起 120 小時。"""
    clients = functools.cache(_client)
    tmp = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="hongthai-ecmwf-"))
    tmp.mkdir(parents=True, exist_ok=True)

    # 用 144 小時的 10fg3 判斷「這一報 0–144 都出齊了」
    run = _latest(clients, stream="oper", type="fc", param="10fg3", step=144)
    max_step = 240 if run.hour in (0, 12) else 144
    steps = hres_steps(hours_between(run, slot0), max_step)
    size, mirror = _download(
        clients,
        tmp / "hres.grib2",
        date=run.strftime("%Y%m%d"),
        time=run.hour,
        stream="oper",
        type="fc",
        param=[*HRES_GUST_PARAMS, *HRES_WIND_PARAMS],
        step=steps,
    )
    hres_run, hres = parse_hres(tmp / "hres.grib2", airports)

    ens_run = None
    ens: dict[str, list[ProbWindow]] = {}
    ens_error = None
    ens_mirror = None
    try:
        er = _latest(clients, stream="enfo", type="ep", param="10fgg25", step="96-120")
        windows = ens_windows(hours_between(er, slot0))
        ens_size, ens_mirror = _download(
            clients,
            tmp / "ens.grib2",
            date=er.strftime("%Y%m%d"),
            time=er.hour,
            stream="enfo",
            type="ep",
            param=list(ENS_PARAMS),
            step=windows,
        )
        size += ens_size
        ens_run, ens = parse_ens(tmp / "ens.grib2", airports)
    except Exception as e:  # 系集失敗不影響 HRES
        log.warning("ECMWF 系集機率失敗：%s", e)
        ens_error = getattr(e, "code", None) or e.__class__.__name__
        ens_mirror = None

    points = {
        a.icao: EcmwfPoint(hres=hres.get(a.icao, []), ens=ens.get(a.icao, [])) for a in airports
    }
    return EcmwfData(hres_run, ens_run, ens_error, points, size, mirror, ens_mirror)
