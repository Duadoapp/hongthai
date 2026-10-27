"""NOAA GEFS（美國系集，HD42 遠期關注）：31 個成員（控制 `gec00`＋擾動 `gep01`…`gep30`）的地面陣風。

只給 `longrange.py` 用（第 6–15 天），不進 `latest.json`、不投票。

來源（2026-10-27 查 AWS 開放資料 `noaa-gefs-pds`，美國政府公有領域）：
- 網址：`https://noaa-gefs-pds.s3.amazonaws.com/gefs.<YYYYMMDD>/<HH>/atmos/pgrb2bp5/`
  `<成員>.t<HH>z.pgrb2b.0p50.f<FFF>`，旁邊有 `.idx`（格式同 GFS，`grib.byte_ranges`）
- **0.5° 全球**；每個時次都到 384 小時（00Z 那報延長到 840 小時），240 小時以前每 3 小時、
  以後每 6 小時一個檔
- **陣風 `GUST:surface` 在 `pgrb2bp5`（b 檔，第 30 筆，約 175 KB）**，`pgrb2ap5`（a 檔）只有
  10 米風 `UGRD`／`VGRD:10 m above ground`；0.25° 的 `pgrb2sp25` 有陣風但只到 240 小時，
  第 11–15 天沒有，所以不用
- 2026-10-27 00Z：`gep30` 的 f360 在 06:18Z、f384 在 06:28Z 上 S3（b 檔比 a 檔晚幾十秒）
- `GUST` 是瞬時值（同 GFS）：每個成員每個窗取窗內（含頭尾）6 小時整時間點的最大值。
  240 小時以前雖然有每 3 小時的檔，為了第 6–10 天和第 11–15 天取樣一致、也和 WN2 系集
  （6 小時一點）一致，一律只抓 6 小時整的

下載（每個成員、每個步長一個檔）：
- `.idx` 先只抓前 `IDX_HEAD_BYTES`（`Range: bytes=0-8191`，約 120 行；`GUST` 是第 30 筆）——
  整個 `.idx` 約 38 KB，1,271 個檔差約 43 MB。前段裡找不到 `GUST`、或 `GUST` 後面沒有下一筆
  （算不出結束位置）時才抓整個 `.idx`
- 再用一個 `Range` 請求只抓 `GUST` 那一筆；回應不是 206、或不是 `GRIB`…`7777` 當失敗
  （`gfs.download_ranges`）
- **b 檔沒有 `GUST` 時**（`.idx` 整個找不到）改抓 a 檔的 `UGRD`／`VGRD:10 m above ground`，
  10 米風 × 機場的估算陣風係數 G（同 AI 模式，`gustfactor.py`），那個檔記 `estimated`
- 一天一次、第 6–15 天（`longrange.py` 的 10 個窗，6 小時一點是 41 個步長）× 31 個成員
  ＝ 1,271 個檔、2,542 個請求（`.idx` 前段＋`GUST`），約 230 MB。`WORKERS` 條執行緒平行抓
  （各自一個 `requests.Session`）；全部抓完後每個成員的步長接成一個檔再解析
- 單一檔失敗（重試 3 次後）只記 `missing`，那個成員那個時間點沒有值；失敗超過
  `MAX_MISSING_FRACTION` 就整套失敗（`GefsError("partial")`）

找哪一報（`find_run`）：從 `latest`（`longrange.py` 的基準日 00Z）往回每 6 小時找，最多
`tries` 報；`gec00` 與 `gep30` 的最後所需步長的 `.idx` 都在，才算出齊。
"""

from __future__ import annotations

import logging
import tempfile
import threading
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import requests

from .. import budget, grib
from ..config import Airport
from ..grib import read_points, wind_speed_kt
from ..timeutil import hours_between
from ..units import ms_to_kt
from . import SourceError, http_get
from .gfs import download_ranges

log = logging.getLogger("hongthai")

S3_URL = "https://noaa-gefs-pds.s3.amazonaws.com"
MEMBERS = ("gec00", *(f"gep{i:02d}" for i in range(1, 31)))
STEP_H = 6
MAX_STEP_H = 384  # 每個時次都有；00Z 更長，但用不到
GUST_FIELD = ("GUST", "surface")
WIND_FIELDS = (("UGRD", "10 m above ground"), ("VGRD", "10 m above ground"))
IDX_HEAD_BYTES = 8192
WORKERS = 16
MAX_MISSING_FRACTION = 0.1


class GefsError(SourceError):
    pass


@dataclass
class MemberPoint:
    """一個成員在一個時間點的陣風（節）；`estimated` 是 10 米風 × G 估算的。"""

    valid: datetime
    gust_kt: float | None
    estimated: bool = False


@dataclass
class GefsData:
    run: datetime
    # icao → 成員（`MEMBERS` 的順序）→ 時間點
    points: dict[str, list[list[MemberPoint]]]
    bytes_downloaded: int = 0
    files: int = 0
    missing: int = 0
    estimated: bool = False  # 有任何一個檔是估算的
    steps: list[int] = field(default_factory=list)


def file_url(run: datetime, member: str, fh: int, kind: str = "b") -> str:
    """`kind` 是 `b`（`pgrb2bp5`，有陣風）或 `a`（`pgrb2ap5`，10 米風）。"""
    return (
        f"{S3_URL}/gefs.{run:%Y%m%d}/{run:%H}/atmos/pgrb2{kind}p5/"
        f"{member}.t{run:%H}z.pgrb2{kind}.0p50.f{fh:03d}"
    )


def steps_for(run: datetime, windows: Sequence[tuple[datetime, datetime]]) -> list[int]:
    """這些窗（含頭尾）要抓的步長：6 小時整、0–`MAX_STEP_H` 小時。"""
    out: set[int] = set()
    for start, end in windows:
        a, b = hours_between(run, start), hours_between(run, end)
        for fh in range(max(0, int(-(-a // STEP_H)) * STEP_H), int(b) + 1, STEP_H):
            if fh <= MAX_STEP_H:
                out.add(fh)
    return sorted(out)


def find_run(latest: datetime, last_fh: int, tries: int = 5) -> datetime:
    """從 `latest` 往回每 6 小時找，`gec00` 與 `gep30` 在 `last_fh`（不超過 `MAX_STEP_H`）的
    `.idx` 都在的第一報。起報往前移時所需步長變大，每一報各自算（`last_fh` 是 `latest` 的）。"""
    run = latest
    for i in range(tries):
        fh = min(MAX_STEP_H, last_fh + i * STEP_H)
        ok = all(
            http_get(
                f"{file_url(run, m, fh)}.idx", ok_404=True, retries=2, error=GefsError
            ).status_code
            == 200
            for m in (MEMBERS[0], MEMBERS[-1])
        )
        if ok:
            return run
        log.info("GEFS %s 還沒出到 f%03d", run, fh)
        run -= timedelta(hours=STEP_H)
    raise GefsError(f"GEFS 從 {latest} 往回 {tries} 報都還沒出齊", "no_run")


def _records_after(idx_text: str, field: tuple[str, ...]) -> bool:
    """`.idx` 文字裡有 `field`，而且它後面還有下一筆（才算得出結束位置）。"""
    recs = sorted(grib.idx_records(idx_text))
    for i, (_, var, lev, _) in enumerate(recs):
        if (var, lev) == field:
            return i + 1 < len(recs)
    return False


def _head(text: str) -> str:
    """`.idx` 前段的最後一行可能被切掉一半，丟掉。"""
    return text if text.endswith("\n") else text[: text.rfind("\n") + 1]


def gust_ranges(url: str, session: requests.Session | None = None) -> list[tuple[int, int | None]]:
    """b 檔 `.idx` → `GUST` 那一筆的 byte 範圍；先抓前段，不夠才抓整個。沒有 `GUST` 丟
    `bad_idx`。"""
    r = http_get(
        f"{url}.idx",
        session=session,
        headers={"Range": f"bytes=0-{IDX_HEAD_BYTES - 1}"},
        error=GefsError,
    )
    text = r.text if r.status_code == 200 else _head(r.text)  # 200：伺服器不理 Range、給了整個
    if r.status_code != 200 and not _records_after(text, GUST_FIELD):
        text = http_get(f"{url}.idx", session=session, error=GefsError).text
    return grib.byte_ranges(text, (GUST_FIELD,), error=GefsError, label="GEFS")


def parse_member(
    path: Path, airports: Sequence[Airport], g: dict[str, float] | None = None
) -> dict[str, list[MemberPoint]]:
    """一個成員的檔（各步長接在一起）→ `{icao: 時間點}`。`GUST` 直接換算成節；只有 10 米風的步長
    （b 檔沒有陣風時）× `g[icao]` 估算（沒有 G 的機場是 None）。"""
    out: dict[str, list[MemberPoint]] = {}
    for icao, series in read_points(path, {a.icao: (a.lat, a.lon) for a in airports}).items():
        pts: dict[float, MemberPoint] = {}
        gust, u, v = series.get("gust"), series.get("10u"), series.get("10v")
        if u is not None and v is not None:
            factor = (g or {}).get(icao)
            for step, a, b in zip(u.steps, u.values, v.values, strict=True):
                wind = wind_speed_kt(a, b)
                pts[step] = MemberPoint(
                    u.run + timedelta(hours=step),
                    None if wind is None or factor is None else wind * factor,
                    estimated=True,
                )
        if gust is not None:  # 同一步長兩個都有時用陣風
            for step, val in zip(gust.steps, gust.values, strict=True):
                pts[step] = MemberPoint(gust.run + timedelta(hours=step), ms_to_kt(val))
        out[icao] = [pts[s] for s in sorted(pts)]
    return out


def _fetch_one(
    run: datetime, member: str, fh: int, tmp: Path, session: requests.Session
) -> tuple[Path, int, bool]:
    """一個成員一個步長：b 檔的 `GUST`；b 檔的 `.idx` 沒有 `GUST` 才改抓 a 檔的 10 米風（估算）。
    回傳（檔案, 大小, 是不是估算）。"""
    url = file_url(run, member, fh)
    path = tmp / f"{member}-f{fh:03d}.grib2"
    estimated = False
    try:
        ranges = gust_ranges(url, session)
    except GefsError as e:
        if e.code != "bad_idx":
            raise
        log.warning("GEFS %s f%03d 的 b 檔沒有 GUST，改用 10 米風估算", member, fh)
        url = file_url(run, member, fh, "a")
        idx = http_get(f"{url}.idx", session=session, error=GefsError).text
        ranges = grib.byte_ranges(idx, WIND_FIELDS, error=GefsError, label="GEFS")
        estimated = True
    return path, download_ranges(url, ranges, path, GefsError), estimated


def fetch(
    airports: Sequence[Airport],
    latest: datetime,
    windows: Sequence[tuple[datetime, datetime]],
    workdir: str | Path | None = None,
    gust_factors: dict[str, float] | None = None,
    workers: int = WORKERS,
) -> GefsData:
    """抓 `windows` 要的步長、31 個成員；`latest` 是最新該有的一報（往回找出齊的，`find_run`）。
    `gust_factors`（icao → G）只在 b 檔沒有陣風、改用 10 米風時用。"""
    t0 = time.monotonic()
    last = max(end for _, end in windows)
    run = find_run(latest, int(-(-hours_between(latest, last) // STEP_H)) * STEP_H)
    steps = steps_for(run, windows)
    tmp = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="hongthai-gefs-"))
    tmp.mkdir(parents=True, exist_ok=True)
    jobs = [(m, fh) for m in MEMBERS for fh in steps]
    ctx = budget.context()
    local = threading.local()

    def work(job: tuple[str, int]):
        budget.attach(ctx)  # 超過預算時這條執行緒也停（`check_cancelled`）、下載量算進來源
        if not hasattr(local, "session"):
            local.session = requests.Session()
        member, fh = job
        try:
            return job, _fetch_one(run, member, fh, tmp, local.session)
        except SourceError as e:
            log.warning("GEFS %s f%03d 抓不到：%s", member, fh, e)
            return job, None

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="gefs") as pool:
        results = dict(pool.map(work, jobs))
    missing = sum(r is None for r in results.values())
    if missing > len(jobs) * MAX_MISSING_FRACTION:
        raise GefsError(f"GEFS {run} 有 {missing}／{len(jobs)} 個檔抓不到", "partial")
    total = sum(r[1] for r in results.values() if r is not None)
    estimated = any(r[2] for r in results.values() if r is not None)
    # 每個成員的步長接成一個檔再解析：cfgrib 開一次檔的開銷比解碼一個場大（1,271 次 → 31 次）
    points: dict[str, list[list[MemberPoint]]] = {a.icao: [] for a in airports}
    for m in MEMBERS:
        path = tmp / f"{m}.grib2"
        with path.open("wb") as f:
            for fh in steps:
                r = results.get((m, fh))
                if r is not None:
                    f.write(r[0].read_bytes())
        parsed = parse_member(path, airports, gust_factors) if path.stat().st_size else {}
        for a in airports:
            points[a.icao].append(parsed.get(a.icao, []))
    log.info(
        "GEFS %s：%d 個成員 × %d 個步長，%d 個檔抓不到，%d bytes，%.1f 秒%s",
        run,
        len(MEMBERS),
        len(steps),
        missing,
        total,
        time.monotonic() - t0,
        "（有估算陣風）" if estimated else "",
    )
    return GefsData(run, points, total, len(jobs) - missing, missing, estimated, steps)
