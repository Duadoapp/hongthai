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
"""

from __future__ import annotations

import contextlib
import io
import logging
import tempfile
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ..config import Airport
from ..grib import read_points
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


ENS_PARAMS = ("10fgg10", "10fgg15", "10fgg25")
ENS_WINDOW_H = 24
ENS_STRIDE_H = 12
ENS_MAX_END_H = 240


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
        intervals = []
        for short, s in series.items():
            run = s.run
            for step, v in zip(s.steps, s.values, strict=True):
                end = s.run + timedelta(hours=step)
                start = end - timedelta(hours=hres_interval_hours(short, step))
                intervals.append(GustInterval(start, end, v))
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


def _retrieve(client, target: Path, **request) -> int:
    t0 = time.monotonic()
    # multiurl 的 tqdm 進度條寫死 disable=False，會在 Actions log 洗版；大小與耗時由下面的 log 印
    with contextlib.redirect_stderr(io.StringIO()):
        client.retrieve(target=str(target), **request)
    size = target.stat().st_size if target.exists() else 0
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


def fetch(airports: list[Airport], slot0: datetime, workdir: str | Path | None = None) -> EcmwfData:
    """抓最新 HRES 與最新 00／12Z 系集機率，涵蓋 slot0 起 120 小時。"""
    from ecmwf.opendata import Client

    client = Client(source="ecmwf")
    tmp = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="hongthai-ecmwf-"))
    tmp.mkdir(parents=True, exist_ok=True)

    try:
        # 用 144 小時的 10fg3 判斷「這一報 0–144 都出齊了」
        run = client.latest(stream="oper", type="fc", param="10fg3", step=144)
    except Exception as e:  # ecmwf-opendata 找不到時丟一般例外
        raise EcmwfError(f"找不到最新 HRES：{e}", "no_run") from e
    run = run.replace(tzinfo=UTC)
    max_step = 240 if run.hour in (0, 12) else 144
    steps = hres_steps(hours_between(run, slot0), max_step)
    size = _retrieve(
        client,
        tmp / "hres.grib2",
        date=run.strftime("%Y%m%d"),
        time=run.hour,
        stream="oper",
        type="fc",
        param=["10fg", "10fg3"],
        step=steps,
    )
    hres_run, hres = parse_hres(tmp / "hres.grib2", airports)

    ens_run = None
    ens: dict[str, list[ProbWindow]] = {}
    ens_error = None
    try:
        er = client.latest(stream="enfo", type="ep", param="10fgg25", step="96-120")
        er = er.replace(tzinfo=UTC)
        windows = ens_windows(hours_between(er, slot0))
        size += _retrieve(
            client,
            tmp / "ens.grib2",
            date=er.strftime("%Y%m%d"),
            time=er.hour,
            stream="enfo",
            type="ep",
            param=list(ENS_PARAMS),
            step=windows,
        )
        ens_run, ens = parse_ens(tmp / "ens.grib2", airports)
    except Exception as e:  # 系集失敗不影響 HRES
        log.warning("ECMWF 系集機率失敗：%s", e)
        ens_error = getattr(e, "code", None) or e.__class__.__name__

    points = {
        a.icao: EcmwfPoint(hres=hres.get(a.icao, []), ens=ens.get(a.icao, [])) for a in airports
    }
    return EcmwfData(hres_run, ens_run, ens_error, points, size)
