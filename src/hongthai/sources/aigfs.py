"""NOAA AIGFS（AI 模式，公有領域）：10 米風、6 小時雨量、2 米溫度（HD14）。

實測（2026-10-20，`aws s3 ls` 等同的 S3 ListObjectsV2 查 `noaa-nws-graphcastgfs-pds`）：
- 正式 AIGFS 在 `aigfs.<YYYYMMDD>/<HH>/model/atmos/grib2/`（最早的目錄是 `aigfs.20260416/`；
  舊的實驗版 `graphcastgfs.<YYYYMMDD>/` 到 2026-05-05），每個步長兩個檔：
  `aigfs.t<HH>z.pres.f<FFF>.grib2`（氣壓層，約 70 MB）與 **`aigfs.t<HH>z.sfc.f<FFF>.grib2`**
  （地面，約 8 MB，用這個），旁邊都有 `.idx`
- 一天 4 報（00／06／12／18Z），每 6 小時一個步長到 384 小時；出齊約在起報後 7.5 小時
  （2026-10-19 00Z 07:32Z、06Z 13:34Z、12Z 19:42Z）
- 地面檔的 `.idx`（12Z f012）：`UGRD`／`VGRD:10 m above ground`、`DPT`／`TMP:2 m above ground`、
  `ACPCP:surface`、`PRMSL`、`TMP:surface`、`PRES:surface`、`APCP:surface` 兩筆（`6-12 hour acc fcst`
  與 `0-12 hour acc fcst`）；f006 兩筆都是 `0-6 hour acc fcst`；f120 的累積那筆寫成
  `0-5 day acc fcst`；f000 沒有 `APCP`。沒有陣風、能見度、降水型態
- 抓 `UGRD`、`VGRD`（必要）、`TMP:2 m`、`APCP`（可少）：每個步長約 2.5 MB（`UGRD`＋`VGRD` 相鄰
  約 1.7 MB、`TMP` 0.48、`APCP` 0.3），21 個步長約 52 MB
- `APCP` 用哪一筆看 `.idx` 的字樣（`apcp_kind`）：有「前 6 小時」那桶（`acc6`）就用它；沒有就用
  「從起報累積」那筆（`acc0`），6 小時雨量＝和前一個步長的差（`rain6h`）。同一個檔只抓一筆
  （cfgrib 讀到兩筆同步長的 `APCP` 只留第一筆）
- 下載照 `gfs.py` 的 AWS 寫法（`.idx` → byte 範圍 → 一段一個 `Range` 請求，`gfs.download_ranges`）
- NOMADS 備援：`https://nomads.ncep.noaa.gov/pub/data/nccf/com/aigfs/prod/` 有同樣的目錄與檔名，
  但**沒有 `filter_aigfs` 這種裁區 CGI**（`/cgi-bin/filter_aigfs.pl`、`filter_aigfs_0p25.pl` 都
  404），所以不做備援：AWS 失敗就整個失敗、交給沿用（`build.REUSE_FIELDS`）
- 陣風不在這裡估：`AigfsStep.wind_kt` 是平均風，`assess` 乘 `config.GUST_FACTOR`
"""

from __future__ import annotations

import logging
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import hypot
from pathlib import Path

from .. import grib
from ..budget import note
from ..config import Airport
from ..grib import read_points, wind_dir_from_uv
from ..timeutil import hours_between
from ..units import ms_to_kt
from . import SourceError, gfs, http_get

log = logging.getLogger("hongthai")

S3_URL = "https://noaa-nws-graphcastgfs-pds.s3.amazonaws.com"
MIRROR = "aws"
IDX_FIELDS: tuple[tuple[str, ...], ...] = (
    ("UGRD", "10 m above ground"),
    ("VGRD", "10 m above ground"),
)
IDX_OPTIONAL: tuple[tuple[str, ...], ...] = (("TMP", "2 m above ground"),)
APCP_KINDS = ("acc6", "acc0")  # 前面的優先
SPAN_H = gfs.SPAN_H
STEP_H = gfs.STEP_H


class AigfsError(SourceError):
    pass


@dataclass
class AigfsStep:
    """一個 6 小時整的時間點：10 米平均風（節）、風向、前 6 小時雨量（mm）、2 米溫度（°C）。"""

    valid: datetime
    wind_kt: float | None
    wdir: float | None
    rain6h_mm: float | None
    temp2m_c: float | None = None
    ptype = None  # 沒有降水型態：不投雪的票（`assess`）


@dataclass
class AigfsData:
    run: datetime
    points: dict[str, list[AigfsStep]]
    bytes_downloaded: int = 0
    mirror: str | None = None


def file_name(run: datetime, fh: int) -> str:
    return f"aigfs.t{run:%H}z.sfc.f{fh:03d}.grib2"


def run_dir(run: datetime) -> str:
    return f"/aigfs.{run:%Y%m%d}/{run:%H}/model/atmos/grib2"


def apcp_kind(idx_text: str, fh: int) -> str | None:
    """這個步長的 `APCP` 用哪一種累積（`APCP_KINDS` 的順序）；都沒有回 None（f000）。"""
    return next((k for k in APCP_KINDS if grib.idx_has(idx_text, ("APCP", "surface", k), fh)), None)


def rain6h(apcp: dict[int, tuple[str, float | None]]) -> dict[int, float | None]:
    """`{步長: (累積方式, 值)}` → `{步長: 前 6 小時雨量}`。`acc6` 直接用；`acc0` 和前一個步長的
    累積量相減。累積量：`acc0` 就是它；`acc6` 是前一個步長的累積量加上它（起報那一刻是 0，所以
    f006 的 `0-6 hour acc fcst` 兩種都算得出）。前一個步長的累積量算不出來時是 None。"""
    cum: dict[int, float] = {0: 0.0}
    out: dict[int, float | None] = {}
    for fh in sorted(apcp):
        kind, v = apcp[fh]
        prev = cum.get(fh - STEP_H)
        if v is None:
            out[fh] = None
            continue
        if kind == "acc0":
            cum[fh] = v
            out[fh] = None if prev is None else max(0.0, v - prev)
        else:
            if prev is not None:
                cum[fh] = prev + v
            out[fh] = v
    return out


def _parse_step(path: Path, airports: list[Airport]) -> dict[str, tuple]:
    """一個步長的檔 → `{icao: (valid, u, v, 2 米溫度 K, APCP)}`。"""
    out = {}
    for icao, series in read_points(path, {a.icao: (a.lat, a.lon) for a in airports}).items():
        u = series.get("10u")
        if u is None:
            continue
        vals = [series[k].values[0] if k in series else None for k in ("10u", "10v", "2t", "tp")]
        out[icao] = (u.run + timedelta(hours=u.steps[0]), *vals)
    return out


def _fetch_step(
    run: datetime, fh: int, airports: list[Airport], tmp: Path
) -> tuple[dict[str, tuple], str | None, int]:
    url = f"{S3_URL}{run_dir(run)}/{file_name(run, fh)}"
    idx = http_get(f"{url}.idx", error=AigfsError).text
    kind = apcp_kind(idx, fh)
    optional = IDX_OPTIONAL + ((("APCP", "surface", kind),) if kind else ())
    ranges = grib.byte_ranges(idx, IDX_FIELDS, fh, optional, error=AigfsError, label="AIGFS")
    path = tmp / f"aigfs-f{fh:03d}.grib2"
    size = gfs.download_ranges(url, ranges, path, AigfsError)
    return _parse_step(path, airports), kind, size


def fetch(
    airports: list[Airport], now: datetime, slot0: datetime, workdir: str | Path | None = None
) -> AigfsData:
    t0 = time.monotonic()
    note(mirror=MIRROR)

    def idx_url(run: datetime, fh: int) -> str:
        return f"{S3_URL}{run_dir(run)}/{file_name(run, fh)}.idx"

    run = gfs.latest_run(idx_url, now, slot0, 4, AigfsError)
    rel0 = int(hours_between(run, slot0))
    tmp = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="hongthai-aigfs-"))
    tmp.mkdir(parents=True, exist_ok=True)
    raw: dict[str, dict[int, tuple]] = {a.icao: {} for a in airports}
    kinds: dict[int, str | None] = {}
    total = 0
    for fh in range(rel0, rel0 + SPAN_H + 1, STEP_H):
        got, kinds[fh], size = _fetch_step(run, fh, airports, tmp)
        total += size
        for icao, row in got.items():
            raw[icao][fh] = row
    points: dict[str, list[AigfsStep]] = {}
    for icao, rows in raw.items():
        rain = rain6h({fh: (kinds[fh], r[4]) for fh, r in rows.items() if kinds[fh]})
        points[icao] = [
            AigfsStep(
                valid,
                None if u is None or v is None else ms_to_kt(hypot(u, v)),
                wind_dir_from_uv(u, v),
                rain.get(fh),
                None if t2 is None else t2 - 273.15,
            )
            for fh, (valid, u, v, t2, _) in sorted(rows.items())
        ]
    log.info(
        "AIGFS %s：%d 個步長，%d bytes，%.1f 秒",
        run,
        len(kinds),
        total,
        time.monotonic() - t0,
    )
    return AigfsData(run, points, total, MIRROR)
