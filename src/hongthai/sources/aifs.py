"""ECMWF AIFS Single（AI 模式，ECMWF 開放資料，CC BY 4.0）：10 米風、6 小時雨量與降雪量（HD14）。

實測（2026-10-20，`20261019/18z` 那一報）：
- `ecmwf-opendata` 的 `Client(model="aifs-single")`，`stream="oper"`、`type="fc"`、
  `resol="0p25"`（預設）。網址
  `<入口>/<YYYYMMDD>/<HH>z/aifs-single/0p25/oper/<YYYYMMDDHH>0000-<步長>h-oper-fc.grib2`，
  旁邊有 `.index`；AWS 鏡像 `ecmwf-forecasts` 有同一個路徑，所以鏡像順序和 HRES 一樣（找最新一報
  `ecmwf` → `aws`，下載 `aws` → `ecmwf` → `google`），重試、`Cancelled`、預算全部沿用 `ecmwf.py` 的
  `_latest`／`_download`
- 一天 4 報（00／06／12／18Z），每報都到 360 小時、**每 6 小時一個步長**；18Z 那報全部步長在起報後
  約 5.5 小時（23:31–23:34Z）出齊，同一報的 HRES 到 00:27Z
- 參數（地面）：`10u`、`10v`（m/s，瞬時）、`2t`（K）、`tp`、`sf`（總降水、降雪，**從起報累積**）。
  **`tp`／`sf` 的單位是 kg m⁻²（＝mm），不是 HRES 的 m**（cfgrib 的 `GRIB_units` 實測；
  新千歲 108 小時 `tp` 20.1）。沒有陣風（`10fg`）、沒有降水型態（`ptype`）、沒有能見度
- 每個步長五個參數約 3.0 MB（`10u` 0.73、`10v` 0.74、`tp` 0.67、`2t` 0.56、`sf` 0.29），21 個步長
  加第一格的開始步長約 66 MB；從 `ecmwf` 入口下載 21 個步長實測 66,172,049 bytes、49 秒（雲端
  開發機，不是 Actions）。AWS 那時回 `503 Slow Down`（連 `.index` 都是），所以多半會落到 `ecmwf`
- 6 小時雨量（降雪）＝`tp(t) − tp(t−6)`（`sf` 同），所以和 HRES 一樣多抓第一格的開始步長
  （`steps`，開始步長是 0 時 `tp(0)` 當 0）
- 陣風不在這裡估：`AifsStep.wind_kt` 是平均風，`assess` 乘 `config.GUST_FACTOR`
- 降水型態（`AifsStep.ptype`）：6 小時降雪 ≥ 6 小時總降水的一半 → `snow`，否則 `rain`；6 小時總降水
  < `NO_PRECIP_MM`（0.1 mm，GRIB 打包的雜訊約 0.01 mm）→ `none`。不用 2 米溫度猜型態
"""

from __future__ import annotations

import functools
import logging
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import hypot
from pathlib import Path

from ..config import Airport
from ..grib import read_points, wind_dir_from_uv
from ..timeutil import hours_between
from ..units import ms_to_kt
from . import ecmwf

log = logging.getLogger("hongthai")

MODEL = "aifs-single"
PARAMS = ("10u", "10v", "tp", "sf", "2t")
STEP_H = 6
SPAN_H = 120
NO_PRECIP_MM = 0.1
# 用這個步長的 `tp` 判斷「這一報出齊了」（AIFS 一報幾分鐘內全部出完，120 小時內的格都在 144 以內）
LATEST_STEP = 144


@dataclass
class AifsStep:
    """一個 6 小時整的時間點：10 米平均風（節）、風向、前 6 小時的雨量與降雪（mm）、
    2 米溫度（°C）。"""

    valid: datetime
    wind_kt: float | None
    wdir: float | None
    rain6h_mm: float | None
    snow6h_mm: float | None
    temp2m_c: float | None = None

    @property
    def ptype(self) -> str | None:
        if self.rain6h_mm is None:
            return None
        if self.rain6h_mm < NO_PRECIP_MM:
            return "none"
        if self.snow6h_mm is not None and self.snow6h_mm * 2 >= self.rain6h_mm:
            return "snow"
        return "rain"


@dataclass
class AifsData:
    run: datetime
    points: dict[str, list[AifsStep]]
    bytes_downloaded: int = 0
    mirror: str | None = None


def steps(rel0: float) -> list[int]:
    """涵蓋 slot0 起 120 小時的 6 小時整步長，加第一格的開始步長（算 6 小時雨量；0 不抓）。"""
    start = int(rel0)
    return [s for s in range(start, start + SPAN_H + 1, STEP_H) if s > 0]


def _table(series: dict, key: str) -> dict[float, float | None]:
    s = series.get(key)
    return dict(zip(s.steps, s.values, strict=True)) if s is not None else {}


def _diff6(table: dict[float, float | None], step: float) -> float | None:
    cur = table.get(step)
    prev = 0.0 if step - STEP_H == 0 else table.get(step - STEP_H)
    return None if cur is None or prev is None else max(0.0, cur - prev)


def parse(path: str | Path, airports: list[Airport]) -> tuple[datetime, dict[str, list[AifsStep]]]:
    """一個 GRIB 檔（全部步長）→ 各機場每個步長一筆。第一格的開始步長沒有前一個步長，雨量是 None
    （它的風照用：一格取頭尾兩個時間點）。"""
    pts = read_points(path, {a.icao: (a.lat, a.lon) for a in airports})
    run = None
    out: dict[str, list[AifsStep]] = {}
    for icao, series in pts.items():
        if not series:
            continue
        run = next(iter(series.values())).run
        u, v, tp, sf, t2 = (_table(series, k) for k in PARAMS)
        rows = []
        for step in sorted(set(u) | set(tp)):
            uu, vv, temp = u.get(step), v.get(step), t2.get(step)
            rows.append(
                AifsStep(
                    run + timedelta(hours=step),
                    None if uu is None or vv is None else ms_to_kt(hypot(uu, vv)),
                    wind_dir_from_uv(uu, vv),
                    _diff6(tp, step),
                    _diff6(sf, step),
                    None if temp is None else temp - 273.15,
                )
            )
        out[icao] = rows
    if run is None:
        raise ecmwf.EcmwfError("AIFS GRIB 裡沒有資料", "empty")
    return run, out


def fetch(airports: list[Airport], slot0: datetime, workdir: str | Path | None = None) -> AifsData:
    """抓最新一報 AIFS Single，涵蓋 slot0 起 120 小時。"""
    t0 = time.monotonic()
    clients = functools.cache(functools.partial(ecmwf._client, model=MODEL))
    tmp = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="hongthai-aifs-"))
    tmp.mkdir(parents=True, exist_ok=True)
    run = ecmwf._latest(clients, "AIFS", stream="oper", type="fc", param="tp", step=LATEST_STEP)
    size, mirror = ecmwf._download(
        clients,
        tmp / "aifs.grib2",
        label="AIFS",
        date=run.strftime("%Y%m%d"),
        time=run.hour,
        stream="oper",
        type="fc",
        param=list(PARAMS),
        step=steps(hours_between(run, slot0)),
    )
    run, points = parse(tmp / "aifs.grib2", airports)
    log.info("AIFS %s：%d bytes（%s），%.1f 秒", run, size, mirror, time.monotonic() - t0)
    return AifsData(run, {a.icao: points.get(a.icao, []) for a in airports}, size, mirror)
