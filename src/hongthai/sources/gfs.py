"""NOAA GFS 0.25°：NOMADS GRIB filter 只抓機場附近的地面陣風（`GUST`，m/s）與 10 米風
（`UGRD`／`VGRD`，算側風用的風向）。

- 網址：`https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl`，參數 `dir`、`file`、
  `var_GUST=on`、`var_UGRD=on`、`var_VGRD=on`、`lev_surface=on`、`lev_10_m_above_ground=on`、
  `subregion=` 與 `toplat`／`bottomlat`／`leftlon`／`rightlon`
- 範圍：機場依經度分群（相鄰機場經度差超過 `GROUP_GAP_DEG` 就分開），每群一個各自 ±1° 的外接框；
  五個機場分成台灣（桃園、松山、高雄）與港澳兩個框，每檔 1–2 KB
- 出爐時間（UTC）：各報約 3.5–4 小時後到 f120（00Z ≈ 03:40、06Z ≈ 09:40、12Z ≈ 15:40、18Z ≈ 21:40）
- NOMADS 有速率限制：請求之間 `sleep(1)`，失敗重試 3 次
- GUST 是瞬時值（每 6 小時一筆），判讀時一格取頭尾兩個時間點的最大值
"""

from __future__ import annotations

import logging
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from ..config import Airport
from ..grib import read_points, wind_dir_from_uv
from ..timeutil import floor_6h, hours_between
from . import SourceError, http_get

log = logging.getLogger("hongthai")

FILTER_URL = "https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl"
PROD_URL = "https://nomads.ncep.noaa.gov/pub/data/nccf/com/gfs/prod"
SPAN_H = 120
STEP_H = 6
PAD_DEG = 1.0
GROUP_GAP_DEG = 3.0


class GfsError(SourceError):
    pass


@dataclass
class GustPoint:
    valid: datetime
    gust_ms: float | None
    wdir: float | None = None  # 同一時間的 10 米風向（度，真北）


@dataclass
class GfsData:
    run: datetime
    points: dict[str, list[GustPoint]]
    bytes_downloaded: int = 0


def groups(airports: list[Airport]) -> list[list[Airport]]:
    """依經度排序，相鄰兩個機場經度差超過 `GROUP_GAP_DEG` 就分成不同的框。"""
    out: list[list[Airport]] = []
    for a in sorted(airports, key=lambda a: a.lon):
        if out and a.lon - out[-1][-1].lon <= GROUP_GAP_DEG:
            out[-1].append(a)
        else:
            out.append([a])
    return out


def subregion(airports: list[Airport]) -> dict[str, str]:
    return {
        "subregion": "",
        "toplat": f"{max(a.lat for a in airports) + PAD_DEG:.2f}",
        "bottomlat": f"{min(a.lat for a in airports) - PAD_DEG:.2f}",
        "leftlon": f"{min(a.lon for a in airports) - PAD_DEG:.2f}",
        "rightlon": f"{max(a.lon for a in airports) + PAD_DEG:.2f}",
    }


PARAMS = {
    "var_GUST": "on",
    "var_UGRD": "on",
    "var_VGRD": "on",
    "lev_surface": "on",
    "lev_10_m_above_ground": "on",
}


def parse_file(path: str | Path, airports: list[Airport]) -> dict[str, list[GustPoint]]:
    """一個 GRIB 檔（一個步長）→ 各機場的陣風點（配上同一步長的 10 米風向）。"""
    out: dict[str, list[GustPoint]] = {}
    for icao, series in read_points(path, {a.icao: (a.lat, a.lon) for a in airports}).items():
        u, v = series.get("10u"), series.get("10v")
        uv = {}
        if u is not None and v is not None:
            uv = {s: (a, b) for s, a, b in zip(u.steps, u.values, v.values, strict=True)}
        gust = series.get("gust")
        pts = []
        if gust is not None:
            for step, val in zip(gust.steps, gust.values, strict=True):
                wdir = wind_dir_from_uv(*uv.get(step, (None, None)))
                pts.append(GustPoint(gust.run + timedelta(hours=step), val, wdir))
        out[icao] = pts
    return out


def file_name(run: datetime, fh: int) -> str:
    return f"gfs.t{run:%H}z.pgrb2.0p25.f{fh:03d}"


def run_dir(run: datetime) -> str:
    return f"/gfs.{run:%Y%m%d}/{run:%H}/atmos"


def find_latest_run(now: datetime, slot0: datetime, tries: int = 4) -> datetime:
    """從最近的時次往回找，第一個已經出到所需最後步長（看 `.idx`）的就是最新可用的一報。"""
    run = floor_6h(now)
    for _ in range(tries):
        last_fh = int(hours_between(run, slot0)) + SPAN_H
        url = f"{PROD_URL}{run_dir(run)}/{file_name(run, last_fh)}.idx"
        r = http_get(url, ok_404=True, retries=2, error=GfsError)
        if r.status_code == 200:
            return run
        run -= timedelta(hours=6)
        time.sleep(1)
    raise GfsError("NOMADS 上找不到最近 24 小時內出齊的 GFS", "no_run")


def fetch(
    airports: list[Airport], now: datetime, slot0: datetime, workdir: str | Path | None = None
) -> GfsData:
    t0 = time.monotonic()
    run = find_latest_run(now, slot0)
    rel0 = int(hours_between(run, slot0))
    tmp = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="hongthai-gfs-"))
    tmp.mkdir(parents=True, exist_ok=True)
    points: dict[str, list[GustPoint]] = {a.icao: [] for a in airports}
    total = 0
    n_files = 0
    for g, members in enumerate(groups(airports)):
        region = subregion(members)
        for fh in range(rel0, rel0 + SPAN_H + 1, STEP_H):
            time.sleep(1)
            params = {
                "dir": run_dir(run),
                "file": file_name(run, fh),
                **PARAMS,
                **region,
            }
            r = http_get(FILTER_URL, params=params, error=GfsError)
            path = tmp / f"gfs-g{g}-f{fh:03d}.grib2"
            path.write_bytes(r.content)
            total += len(r.content)
            n_files += 1
            for icao, pts in parse_file(path, members).items():
                points[icao].extend(pts)
    log.info("GFS %s：%d 檔，%d bytes，%.1f 秒", run, n_files, total, time.monotonic() - t0)
    return GfsData(run, points, total)
