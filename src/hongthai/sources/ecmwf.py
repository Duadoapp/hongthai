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

側風（第二階段）：HRES 多抓 10 米風 `10u`／`10v`（瞬時值），每個陣風區間配上一個風向（真北）。
HD18 起同一個時間點的風速（√(u²+v²)，節）也留下來（`GustInterval.wind_kt`），算估算陣風的係數用；
不多抓參數。

單位（HD2，2026-10-19）：GRIB 的陣風是 m/s，解析完就換算成節（`GustInterval.gust_kt`）；
系集機率的門檻仍是 ECMWF 定的 10／15／25 m/s（≈ 19.4／29.2／48.6 節），開放資料沒有其他門檻。

下載量（H10，2026-10-18 06Z 那一報的 index 實測，全球 0.25°，每個步長）：
- 陣風每個步長**只有一個**參數：0–90 小時只有 `10fg`（約 1.29–1.42 MB），93–144 小時只有 `10fg3`
  （約 1.28–1.41 MB），150 小時以後只有 `10fg`；同一步長不會兩個都有，所以請求裡寫兩個參數不會
  多抓。0–90 小時沒有 `10fg3`，不能「改抓 `10fg3`、不抓 `10fg`」，那樣 0–90 小時就沒有陣風了
- `10u`、`10v` 各約 0.73–0.87 MB
- H7 的做法（四個參數 × 全部步長）：06Z 那一報 rel0=6、40 個步長，陣風 52.4 MB＋風 59.3 MB＝
  111,671,090 bytes（就是 2026-10-18 14:33Z 那次逾時時的下載量）
- 所以 `10u`／`10v` 改成只抓 6 小時整的步長（`wind_steps`，00／06／12／18Z 的時間點），另外一個請求
  下載：同一報陣風 52.4 MB＋風 29.6 MB＝82,041,279 bytes（少 27%）。3 小時那個陣風區間配**結束時間
  往後最近**的那個 6 小時步長的風向（`wind_step`）

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

降水（HD8，第五階段天氣種類；2026-10-19 查 18Z oper 與 12Z enfo ep 的 index）：
- HRES 有 `tp`（總降水，**從起報累積**，單位 m）、`ptype`（降水型態，瞬時）、`2t`（2 米溫度，K），
  每個步長各約 0.88–1.05、0.94–0.95、0.66 MB；**沒有能見度**（index 裡沒有 `vis`），所以 EC
  不算霧（備案）
- 三個都和 `10u`／`10v` 放同一個請求、只抓 6 小時整的步長（`precip_steps`＝`wind_steps` 再加第一格的
  開始步長，6 小時雨量要 `tp(格結束) − tp(格開始)`；開始步長是 0 時 `tp(0)` 當 0）。m → mm、K → °C
- `ptype` 的代碼（ECMWF 參數 260015，<https://codes.ecmwf.int/grib/param-db/260015>）：
  0 無、1 雨、3 凍雨、5 雪、6 濕雪、7 雨雪混合、8 冰粒、12 凍毛毛雨；其他代碼記 `other`
  （`PTYPE_NAMES`）
- 系集機率多 `tpg25`、`tpg50`（24 小時總降水 ≥ 25／50 mm 的機率，%；窗和 `10fgg*` 一樣、每個約
  0.07–0.15 MB），和陣風機率同一個請求

遠期關注（HD42，`fetch_longrange`，給 `longrange.py`，不進 `latest.json`）：2026-10-27 查
00Z 的 `…-360h-enfo-ep.index`：系集機率**到 360 小時**、每 12 小時一個 24 小時窗——0–240 小時
的窗在 `…-240h-enfo-ep.grib2`（`"0-24"`…`"216-240"`），之後在 `…-360h-enfo-ep.grib2`
（`"228-252"`…`"336-360"`），`ecmwf-opendata` 依窗的結束步長自己挑檔。360h 檔 08:01Z 上入口
（同 240h 檔）。只抓 `10fgg15`、`10fgg25`（每個窗約 0.66＋0.25 MB，10 個窗約 9 MB）
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
from ..grib import read_points, wind_dir_from_uv, wind_speed_kt
from ..timeutil import hours_between
from ..units import ms_to_kt
from . import SourceError

log = logging.getLogger("hongthai")


class EcmwfError(SourceError):
    pass


@dataclass
class GustInterval:
    """某段時間（start, end] 內的最大陣風（節）。"""

    start: datetime
    end: datetime
    gust_kt: float | None
    wdir: float | None = None  # 區間結束時的 10 米風向（度，真北）；沒有 10u／10v 時 None
    # 同一個時間點（`wind_step`）的 10 米平均風速（節，HD18）；沒有 10u／10v 時 None
    wind_kt: float | None = None


@dataclass
class PrecipStep:
    """HRES 一個 6 小時整的時間點（HD8）：前 6 小時雨量（mm）、那時的降水型態與 2 米溫度（°C）。"""

    valid: datetime
    rain6h_mm: float | None
    ptype: str | None  # `PTYPE_NAMES` 的值
    temp2m_c: float | None = None


@dataclass
class ProbWindow:
    """系集機率的 24 小時窗（start, end]，機率 0–1；`p10`／`p15`／`p25` 是陣風 ≥ 10／15／25 m/s，
    `tp25`／`tp50` 是 24 小時總降水 ≥ 25／50 mm（HD8）。"""

    start: datetime
    end: datetime
    p10: float | None
    p15: float | None
    p25: float | None
    tp25: float | None = None
    tp50: float | None = None


@dataclass
class EcmwfPoint:
    hres: list[GustInterval] = field(default_factory=list)
    ens: list[ProbWindow] = field(default_factory=list)
    precip: list[PrecipStep] = field(default_factory=list)


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
HRES_WIND_STRIDE_H = 6
# HD8：和 10u／10v 同一個請求、同樣只抓 6 小時整的步長
HRES_PRECIP_PARAMS = ("tp", "ptype", "2t")
PTYPE_NAMES = {
    0: "none",
    1: "rain",
    3: "freezing_rain",
    5: "snow",
    6: "wet_snow",
    7: "rain_snow",
    8: "ice_pellets",
    12: "freezing_drizzle",
}
ENS_PARAMS = ("10fgg10", "10fgg15", "10fgg25", "tpg25", "tpg50")
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


def wind_step(step: float) -> int:
    """陣風區間（結束於 `step`）配哪個步長的 10 米風：結束時間往後最近的 6 小時整步長。

    時次都是 00／06／12／18Z，所以步長是 6 的倍數＝時間點是 00／06／12／18Z。
    """
    return -(-int(step) // HRES_WIND_STRIDE_H) * HRES_WIND_STRIDE_H


def wind_steps(steps: list[int]) -> list[int]:
    """這些陣風步長要配的 10 米風步長（排序、不重複）。"""
    return sorted({wind_step(s) for s in steps})


def precip_steps(steps: list[int], rel0: float) -> list[int]:
    """10 米風與降水要抓的步長：`wind_steps` 再加第一格的開始步長（算第一格的 6 小時雨量）。"""
    base = {int(rel0)} if rel0 > 0 else set()
    return sorted(set(wind_steps(steps)) | base)


def ptype_name(code: float | None) -> str | None:
    if code is None:
        return None
    return PTYPE_NAMES.get(round(code), "other")


def parse_precip(series: dict, run: datetime) -> list[PrecipStep]:
    """一個點的 `tp`／`ptype`／`2t` → 每個步長一筆（6 小時雨量＝和前 6 小時的 `tp` 差）。"""

    def table(key: str) -> dict[float, float | None]:
        s = series.get(key)
        return dict(zip(s.steps, s.values, strict=True)) if s is not None else {}

    tp, ptype, t2 = table("tp"), table("ptype"), table("2t")
    out = []
    for step in sorted(set(tp) | set(ptype)):
        cur = tp.get(step)
        prev = 0.0 if step - HRES_WIND_STRIDE_H == 0 else tp.get(step - HRES_WIND_STRIDE_H)
        rain = None if cur is None or prev is None else max(0.0, (cur - prev) * 1000)
        temp = t2.get(step)
        out.append(
            PrecipStep(
                run + timedelta(hours=step),
                rain,
                ptype_name(ptype.get(step)),
                None if temp is None else temp - 273.15,
            )
        )
    return out


def ens_windows(rel0: float, span_h: int = 120, slot_h: int = 6) -> list[str]:
    """完整包住任一 6 小時格的 24 小時窗（`"s-e"` 字串）。"""
    needed: set[int] = set()
    for k in range(span_h // slot_h):
        a, b = rel0 + k * slot_h, rel0 + (k + 1) * slot_h
        for s in range(0, ENS_MAX_END_H - ENS_WINDOW_H + 1, ENS_STRIDE_H):
            if s <= a and s + ENS_WINDOW_H >= b:
                needed.add(s)
    return [f"{s}-{s + ENS_WINDOW_H}" for s in sorted(needed)]


def parse_hres(
    path: str | Path,
    airports: list[Airport],
    wind_path: str | Path | None = None,
    precip: dict[str, list[PrecipStep]] | None = None,
) -> tuple[datetime, dict[str, list]]:
    """陣風（`path`）配 10 米風（`wind_path`；沒給就在 `path` 裡找）。

    風向與平均風速（HD18）取 `wind_step` 那個步長的 `10u`／`10v`；陣風換算成節。給了 `precip`
    時順便把 `wind_path` 裡的 `tp`／`ptype`／`2t` 解析進去（HD8，`parse_precip`）。
    """
    where = {a.icao: (a.lat, a.lon) for a in airports}
    pts = read_points(path, where)
    winds = read_points(wind_path, where) if wind_path is not None else pts
    run = None
    out: dict[str, list[GustInterval]] = {}
    for icao, series in pts.items():
        w = winds.get(icao, {})
        uv: dict[str, dict[float, float | None]] = {
            k: dict(zip(w[k].steps, w[k].values, strict=True)) for k in HRES_WIND_PARAMS if k in w
        }
        intervals = []
        for short, s in series.items():
            if short not in HRES_GUST_PARAMS:
                continue
            run = s.run
            for step, v in zip(s.steps, s.values, strict=True):
                end = s.run + timedelta(hours=step)
                start = end - timedelta(hours=hres_interval_hours(short, step))
                ws = wind_step(step)
                u, v10 = uv.get("10u", {}).get(ws), uv.get("10v", {}).get(ws)
                intervals.append(
                    GustInterval(
                        start, end, ms_to_kt(v), wind_dir_from_uv(u, v10), wind_speed_kt(u, v10)
                    )
                )
        out[icao] = sorted(intervals, key=lambda g: g.end)
        if precip is not None and run is not None:
            precip[icao] = parse_precip(w, run)
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
                    vals.get("tpg25"),
                    vals.get("tpg50"),
                )
            )
        out[icao] = windows
    if run is None:
        raise EcmwfError("系集機率 GRIB 裡沒有資料", "empty")
    return run, out


# HD42：遠期關注只要 ≥ 15／25 m/s 兩個機率；窗到 360 小時
LONGRANGE_PARAMS = ("10fgg15", "10fgg25")
LONGRANGE_MAX_END_H = 360


@dataclass
class LongRangeData:
    """HD42：最新系集機率在 `windows` 那幾個窗的值（icao → 有資料的窗）。"""

    run: datetime
    points: dict[str, list[ProbWindow]]
    bytes_downloaded: int = 0
    mirror: str | None = None


def window_steps(run: datetime, windows: list[tuple[datetime, datetime]]) -> list[str]:
    """`windows`（UTC 的 24 小時窗）對這一報的步長字串（`"120-144"`）；不在系集機率產品裡的窗
    （開始不是 12 小時的倍數、超過 360 小時、在起報之前）跳過。"""
    out = []
    for start, end in windows:
        a, b = hours_between(run, start), hours_between(run, end)
        if (
            a >= 0
            and a == int(a)
            and int(a) % ENS_STRIDE_H == 0
            and b - a == ENS_WINDOW_H
            and b <= LONGRANGE_MAX_END_H
        ):
            out.append(f"{int(a)}-{int(b)}")
    return out


def fetch_longrange(
    airports: list[Airport],
    windows: list[tuple[datetime, datetime]],
    workdir: str | Path | None = None,
) -> LongRangeData:
    """HD42：最新出到 360 小時的系集機率（00／12Z），只抓 `windows` 的窗的 `10fgg15`／`10fgg25`。"""
    clients = functools.cache(_client)
    tmp = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="hongthai-ecmwf-lr-"))
    tmp.mkdir(parents=True, exist_ok=True)
    last = f"{LONGRANGE_MAX_END_H - ENS_WINDOW_H}-{LONGRANGE_MAX_END_H}"
    run = _latest(clients, "ECMWF 遠期", stream="enfo", type="ep", param="10fgg25", step=last)
    steps = window_steps(run, windows)
    if not steps:
        raise EcmwfError(f"ECMWF 系集 {run} 沒有涵蓋任何一個遠期的窗", "no_window")
    size, mirror = _download(
        clients,
        tmp / "ens-longrange.grib2",
        label="ECMWF 遠期",
        date=run.strftime("%Y%m%d"),
        time=run.hour,
        stream="enfo",
        type="ep",
        param=list(LONGRANGE_PARAMS),
        step=steps,
    )
    parsed_run, points = parse_ens(tmp / "ens-longrange.grib2", airports)
    return LongRangeData(parsed_run, points, size, mirror)


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


def _client(source: str, model: str = "ifs", **retry):
    """`model` 是 `ecmwf-opendata` 的模式（HD14 的 AIFS 用 `"aifs-single"`）。"""
    return _client_class()(source=source, model=model, **{**CLIENT_RETRY, **retry})


def _code(e: BaseException) -> str:
    code = getattr(e, "code", None)
    if isinstance(code, str) and code:
        return code
    status = getattr(getattr(e, "response", None), "status_code", None)
    if status is not None:
        return f"http_{status}"
    return e.__class__.__name__


def _latest(clients, label: str = "ECMWF", **request) -> datetime:
    """依 `LATEST_SOURCES` 找最新一報。

    全部失敗丟 `no_run`；最後一個是 429／5xx 用盡時丟它的代碼（例如 `http_429`）。`label` 只用在
    log（AIFS 共用這一套，HD14）。
    """
    last: BaseException | None = None
    for src in LATEST_SOURCES:
        check_cancelled()
        t0 = time.monotonic()
        try:
            run = clients(src).latest(**request)
        except Exception as e:  # ecmwf-opendata 找不到時丟一般例外
            log.warning(
                "%s latest %s（%s）失敗，%.1f 秒：%s",
                label,
                request.get("stream"),
                src,
                time.monotonic() - t0,
                e,
            )
            last = e
            continue
        log.info(
            "%s latest %s（%s）：%s，%.1f 秒",
            label,
            request.get("stream"),
            src,
            run,
            time.monotonic() - t0,
        )
        return run.replace(tzinfo=UTC)
    code = _code(last) if isinstance(last, EcmwfError) else "no_run"
    raise EcmwfError(f"{label} 找不到最新 {request.get('stream')}：{last}", code) from last


def _retrieve(client, target: Path, label: str = "ECMWF", **request) -> int:
    t0 = time.monotonic()
    target.unlink(missing_ok=True)  # multiurl 看到舊檔會接著續傳，換鏡像時不能留上一個的殘檔
    # multiurl 的 tqdm 進度條寫死 disable=False，會在 Actions log 洗版；大小與耗時由下面的 log 印
    with contextlib.redirect_stderr(io.StringIO()):
        client.retrieve(target=str(target), **request)
    size = target.stat().st_size if target.exists() else 0
    add_bytes(size)
    log.info(
        "%s %s %s：%d bytes，%.1f 秒",
        label,
        request.get("stream"),
        request.get("type"),
        size,
        time.monotonic() - t0,
    )
    if size == 0:
        raise EcmwfError(f"{label} {request.get('stream')} 下載是空的", "empty")
    return size


def _download(
    clients,
    target: Path,
    sources: tuple[str, ...] = DOWNLOAD_SOURCES,
    label: str = "ECMWF",
    **request,
) -> tuple[int, str]:
    """依 `sources` 的順序下載；回傳（大小, 實際的 source）。全部失敗丟最後一個錯誤的代碼。"""
    last: BaseException | None = None
    for src in sources:
        check_cancelled()
        note(mirror=src)
        t0 = time.monotonic()
        try:
            client = clients(src, **DOWNLOAD_RETRY.get(src, {}))
            return _retrieve(client, target, label, **request), src
        except Exception as e:  # 404（鏡像還沒同步到）、429、空檔……換下一個
            log.warning(
                "%s %s 從 %s 下載失敗，%.1f 秒：%s",
                label,
                request.get("stream"),
                src,
                time.monotonic() - t0,
                e,
            )
            last = e
    assert last is not None
    raise EcmwfError(f"{label} {request.get('stream')} 每個 source 都下載失敗：{last}", _code(last))


def fetch(airports: list[Airport], slot0: datetime, workdir: str | Path | None = None) -> EcmwfData:
    """抓最新 HRES 與最新 00／12Z 系集機率，涵蓋 slot0 起 120 小時。"""
    clients = functools.cache(_client)
    tmp = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="hongthai-ecmwf-"))
    tmp.mkdir(parents=True, exist_ok=True)

    # 用 144 小時的 10fg3 判斷「這一報 0–144 都出齊了」
    run = _latest(clients, stream="oper", type="fc", param="10fg3", step=144)
    max_step = 240 if run.hour in (0, 12) else 144
    steps = hres_steps(hours_between(run, slot0), max_step)
    oper = {"date": run.strftime("%Y%m%d"), "time": run.hour, "stream": "oper", "type": "fc"}
    size, mirror = _download(
        clients, tmp / "hres.grib2", param=list(HRES_GUST_PARAMS), step=steps, **oper
    )
    # 風（＋降水，HD8）先試陣風成功的那個 source
    wind_sources = (mirror, *(s for s in DOWNLOAD_SOURCES if s != mirror))
    wind_size, wind_mirror = _download(
        clients,
        tmp / "hres-wind.grib2",
        wind_sources,
        param=[*HRES_WIND_PARAMS, *HRES_PRECIP_PARAMS],
        step=precip_steps(steps, hours_between(run, slot0)),
        **oper,
    )
    size += wind_size
    if wind_mirror != mirror:
        log.info("ECMWF HRES 陣風從 %s、10 米風從 %s 下載", mirror, wind_mirror)
    precip: dict[str, list[PrecipStep]] = {}
    hres_run, hres = parse_hres(tmp / "hres.grib2", airports, tmp / "hres-wind.grib2", precip)

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
        a.icao: EcmwfPoint(
            hres=hres.get(a.icao, []), ens=ens.get(a.icao, []), precip=precip.get(a.icao, [])
        )
        for a in airports
    }
    return EcmwfData(hres_run, ens_run, ens_error, points, size, mirror, ens_mirror)
