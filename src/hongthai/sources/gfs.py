"""NOAA GFS 0.25°：地面陣風（`GUST`，m/s）與 10 米風（`UGRD`／`VGRD`，算側風用的風向）。

來源（H10）：以 AWS 開放資料鏡像為主、NOMADS 為備援。2026-10-18 12:42Z 起 NOMADS 對 GitHub Actions
回 403（請求是找最新一報的第一個 `.idx`，199 bytes），不能只靠它。

AWS（NOAA Open Data Dissemination，`noaa-gfs-bdp-pds`，公有領域）：
- 網址：`https://noaa-gfs-bdp-pds.s3.amazonaws.com/gfs.<YYYYMMDD>/<HH>/atmos/gfs.t<HH>z.pgrb2.0p25.f<FFF>`，
  旁邊有 `.idx`（一行一筆：`序號:byte 起點:d=<時次>:變數:層:時效:`）
- 不能裁區域，所以用 `.idx` 算出 `GUST:surface`、`UGRD:10 m above ground`、
  `VGRD:10 m above ground` 三筆的 byte 範圍（到下一筆的起點為止），相鄰的併成一段，用 HTTP `Range`
  只抓那幾段（S3 不接受一次多段 range，一段一個請求；`UGRD`／`VGRD` 相鄰，所以每個步長兩個請求）。
  全球 0.25°：`GUST` 約 0.6 MB、`UGRD`＋`VGRD` 約 1.9 MB，21 個步長共約 50 MB
- 回應不是 206、或內容不是 `GRIB`…`7777` 就當失敗
- 解析一樣用 `grib.read_points`（取機場最近格點，全球檔也能用）

順序：
- `find_latest_run`：先看 AWS 的 `.idx`（所需最後步長的 `.idx` 存在就表示那一報出齊了），AWS 失敗
  （連不上、403、24 小時內都找不到）再看 NOMADS；回傳那一報和在哪裡找到的
- 下載從找到那一報的地方開始；AWS 某個步長失敗就改 NOMADS（之後的步長都用 NOMADS，不再回 AWS）。
  最後用的是哪一個記在 `GfsData.mirror`（`sources.gfs.mirror`：`"aws"`／`"nomads"`）

NOMADS（備援，H10 以前唯一的來源）：
- 網址：`https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl`，參數 `dir`、`file`、
  `var_GUST=on`、`var_UGRD=on`、`var_VGRD=on`、`lev_surface=on`、`lev_10_m_above_ground=on`、
  `subregion=` 與 `toplat`／`bottomlat`／`leftlon`／`rightlon`
- 範圍（H9）：**一個框**涵蓋全部機場（外接框 ±1°；41 個機場約北緯 17.3–43.8°、東經 108.4–142.7°，
  NOMADS 對齊 0.25° 格點），每個步長一個請求。2026-10-18 實測一檔約 64 KB、21 個步長約 1.3 MB。
  不用依地區分六個框：NOMADS 有速率限制、每個請求前 `sleep(1)`，六個框是 126 個請求（光等就 126 秒，
  預算 180 秒），一個框是 21 個；框大一點只多幾十 KB。之後加機場（HD3）框會自動變大
- H9 以前依經度分群（經度差 3° 以上分開），五個機場兩個框、每檔 1–2 KB
- NOMADS 有速率限制：請求之間 `sleep(1)`，失敗重試 3 次

共同：
- 出爐時間（UTC）：各報約 3.5–4 小時後到 f120（00Z ≈ 03:40、06Z ≈ 09:40、12Z ≈ 15:40、18Z ≈ 21:40）
- GUST 是瞬時值（每 6 小時一筆），判讀時一格取頭尾兩個時間點的最大值
- GRIB 的陣風是 m/s，解析完就換算成節（`GustPoint.gust_kt`，HD2）
"""

from __future__ import annotations

import logging
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from ..budget import note
from ..config import Airport
from ..grib import read_points, wind_dir_from_uv
from ..timeutil import floor_6h, hours_between
from ..units import ms_to_kt
from . import SourceError, http_get

log = logging.getLogger("hongthai")

S3_URL = "https://noaa-gfs-bdp-pds.s3.amazonaws.com"
FILTER_URL = "https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl"
PROD_URL = "https://nomads.ncep.noaa.gov/pub/data/nccf/com/gfs/prod"
MIRRORS = ("aws", "nomads")
BASE_URL = {"aws": S3_URL, "nomads": PROD_URL}
# `.idx` 裡要抓的（變數, 層）
IDX_FIELDS = (("GUST", "surface"), ("UGRD", "10 m above ground"), ("VGRD", "10 m above ground"))
SPAN_H = 120
STEP_H = 6
PAD_DEG = 1.0


class GfsError(SourceError):
    pass


@dataclass
class GustPoint:
    valid: datetime
    gust_kt: float | None  # 節
    wdir: float | None = None  # 同一時間的 10 米風向（度，真北）


@dataclass
class GfsData:
    run: datetime
    points: dict[str, list[GustPoint]]
    bytes_downloaded: int = 0
    mirror: str | None = None  # 最後從哪裡下載：aws／nomads


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
    """一個 GRIB 檔（一個步長）→ 各機場的陣風點（節，配上同一步長的 10 米風向）。"""
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
                pts.append(GustPoint(gust.run + timedelta(hours=step), ms_to_kt(val), wdir))
        out[icao] = pts
    return out


def file_name(run: datetime, fh: int) -> str:
    return f"gfs.t{run:%H}z.pgrb2.0p25.f{fh:03d}"


def run_dir(run: datetime) -> str:
    return f"/gfs.{run:%Y%m%d}/{run:%H}/atmos"


def byte_ranges(idx_text: str, fields=IDX_FIELDS) -> list[tuple[int, int | None]]:
    """`.idx` 文字 → 要抓的 byte 範圍（頭尾都含；最後一筆到檔尾時尾是 None），相鄰的併成一段。

    一筆的範圍是它的起點到下一個（起點更大的）紀錄的起點前一個 byte。少了任何一筆就丟 `bad_idx`。
    """
    recs: list[tuple[int, str, str]] = []
    for line in idx_text.splitlines():
        parts = line.split(":")
        if len(parts) < 5 or not parts[1].strip().isdigit():
            continue
        recs.append((int(parts[1]), parts[3], parts[4]))
    starts = sorted({r[0] for r in recs})
    wanted = set(fields)
    found: set[tuple[str, str]] = set()
    out: list[tuple[int, int | None]] = []
    for start, var, lev in sorted(recs):
        if (var, lev) not in wanted or (var, lev) in found:
            continue
        found.add((var, lev))
        later = [s for s in starts if s > start]
        end = later[0] - 1 if later else None
        if out and out[-1][1] is not None and out[-1][1] + 1 == start:
            out[-1] = (out[-1][0], end)
        else:
            out.append((start, end))
    if found != wanted:
        missing = ", ".join(f"{v}:{lv}" for v, lv in fields if (v, lv) not in found)
        raise GfsError(f".idx 裡沒有 {missing}", "bad_idx")
    return out


def _find_run(mirror: str, now: datetime, slot0: datetime, tries: int) -> datetime:
    run = floor_6h(now)
    for _ in range(tries):
        last_fh = int(hours_between(run, slot0)) + SPAN_H
        url = f"{BASE_URL[mirror]}{run_dir(run)}/{file_name(run, last_fh)}.idx"
        r = http_get(url, ok_404=True, retries=2, error=GfsError)
        if r.status_code == 200:
            return run
        run -= timedelta(hours=6)
        if mirror == "nomads":
            time.sleep(1)
    raise GfsError(f"{mirror} 上找不到最近 24 小時內出齊的 GFS", "no_run")


def find_latest_run(now: datetime, slot0: datetime, tries: int = 4) -> tuple[datetime, str]:
    """從最近的時次往回找，第一個已經出到所需最後步長（看 `.idx`）的就是最新可用的一報。

    依 `MIRRORS` 的順序找（先 AWS，失敗再 NOMADS）；回傳（那一報, 在哪裡找到的）。
    """
    last: GfsError | None = None
    for mirror in MIRRORS:
        note(mirror=mirror)
        try:
            return _find_run(mirror, now, slot0, tries), mirror
        except GfsError as e:
            log.warning("GFS 在 %s 找最新一報失敗：%s", mirror, e)
            last = e
    assert last is not None
    raise last


def _fetch_aws(
    run: datetime, fh: int, airports: list[Airport], tmp: Path
) -> tuple[dict[str, list[GustPoint]], int]:
    """AWS：`.idx` → 三筆的 byte 範圍 → 一段一個 `Range` 請求，接成一個 GRIB 檔再解析。"""
    url = f"{S3_URL}{run_dir(run)}/{file_name(run, fh)}"
    ranges = byte_ranges(http_get(f"{url}.idx", error=GfsError).text)
    path = tmp / f"gfs-aws-f{fh:03d}.grib2"
    size = 0
    with path.open("wb") as f:
        for a, b in ranges:
            rng = f"bytes={a}-{'' if b is None else b}"
            r = http_get(url, headers={"Range": rng}, error=GfsError)
            body = r.content
            if r.status_code != 206 or not (body.startswith(b"GRIB") and body.endswith(b"7777")):
                raise GfsError(f"{url} {rng}：HTTP {r.status_code}，不是 GRIB", "not_grib")
            f.write(body)
            size += len(body)
    return parse_file(path, airports), size


def _fetch_nomads(
    run: datetime, fh: int, airports: list[Airport], tmp: Path
) -> tuple[dict[str, list[GustPoint]], int]:
    """NOMADS GRIB filter：一個涵蓋全部機場的框（`subregion`），裁好區域的小檔。"""
    time.sleep(1)
    params = {"dir": run_dir(run), "file": file_name(run, fh), **PARAMS, **subregion(airports)}
    r = http_get(FILTER_URL, params=params, error=GfsError)
    path = tmp / f"gfs-nomads-f{fh:03d}.grib2"
    path.write_bytes(r.content)
    return parse_file(path, airports), len(r.content)


def fetch(
    airports: list[Airport], now: datetime, slot0: datetime, workdir: str | Path | None = None
) -> GfsData:
    t0 = time.monotonic()
    run, mirror = find_latest_run(now, slot0)
    rel0 = int(hours_between(run, slot0))
    tmp = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="hongthai-gfs-"))
    tmp.mkdir(parents=True, exist_ok=True)
    points: dict[str, list[GustPoint]] = {a.icao: [] for a in airports}
    total = 0
    used: list[str] = []
    for fh in range(rel0, rel0 + SPAN_H + 1, STEP_H):
        got = None
        if mirror == "aws":
            note(mirror="aws")
            try:
                got = _fetch_aws(run, fh, airports, tmp)
            except GfsError as e:
                log.warning("GFS f%03d 從 AWS 抓失敗，之後改用 NOMADS：%s", fh, e)
                mirror = "nomads"
        if got is None:
            note(mirror="nomads")
            got = _fetch_nomads(run, fh, airports, tmp)
        used.append(mirror)
        pts, size = got
        total += size
        for icao, ps in pts.items():
            points[icao].extend(ps)
    log.info(
        "GFS %s：%d 個步長（%s），%d bytes，%.1f 秒",
        run,
        len(used),
        "、".join(f"{m} {used.count(m)}" for m in MIRRORS if m in used),
        total,
        time.monotonic() - t0,
    )
    return GfsData(run, points, total, mirror)
