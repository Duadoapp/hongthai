"""颱風路徑抽取（HD21，Shawn 2026-10-20 定案第 6 點）：事件期間每個模式每一報抽出颱風路徑，存
`data` 分支 `history/events/<id>/tracks/<起報 YYYYMMDDTHHMM>Z-<模式>.json`；颱風過後對最佳路徑算每個
提前時間的距離誤差（HD22）。這支只抽、不評，也不改等級規則。

兩種來源：

- **IFS（`ifs`）、IFS 系集（`ifs-ens`）**：ECMWF 開放資料自帶的颱風路徑產品（`type="tf"`，BUFR），
  不自己找中心。2026-10-20 實測（`ecmwf-opendata` 0.3.x）：`stream="oper"`／`"enfo"`、`type="tf"`、
  `step` 是整段——00／12Z 是 `360`、06／18Z 是 `144`（`TF_STEP`；檔名
  `<YYYYMMDDHH>0000-360h-oper-tf.bufr` 這種，四個時次都有 oper 與 enfo）。00Z 那報 oper 42,726 bytes
  （15 個 storm）、enfo 1,252,262 bytes（56 個 storm）。鏡像順序同 `sources/ecmwf.py`（`_download`：
  `aws` → `ecmwf` → `google`）。一個 BUFR 訊息一個 storm：`stormIdentifier`（29W 在 ECMWF 叫 `36W`，
  所以比對主要靠名稱）、`longStormName`（`CHAMPI`，前面補空白）；系集是 51 個 subset（壓縮），
  `ensembleMemberNumber` 1–51、51 是控制報（`ensembleForecastType` 0）；HRES 一個 subset、成員
  編號也是 51，存成 `member: 0`。每個時間點：起報那一刻用分析位置 `#2#latitude`／
  `#2#longitude`（`#1#` 是發布中心的觀測位置，記在 `storm.observed`）、
  `#1#pressureReducedToMeanSeaLevel`、`#1#windSpeedAt10M`；
  第 k 個預報時間（`#k#timePeriod` 小時）是 `#(2k+2)#latitude`／`longitude`（中心）、
  `#(k+1)#pressureReducedToMeanSeaLevel`、`#(k+1)#windSpeedAt10M`（10 米最大風，m/s → 節）。缺值
  （-1e100）的點不寫。解析用 `eccodes`（已經是依賴，不加 `pdbufr`）
  - 只留事件那顆（`pick_storm`）：`stormIdentifier` 等於 `events.json` 的 JTWC 編號
    （`wp2926` → `29W`）、或名稱等於事件名稱的英文部分（`CHAMPI`）；都比不到就取離 JMA／JTWC
    現報位置（`position_near`）`MATCH_KM` 公里內最近的
  - 格式：`{"model": "ifs"|"ifs-ens", "run", "storm": {"id", "name", "matchedBy", "observed"},
    "members": [{"member", "points": [{"validAt", "lat", "lon", "pressureHpa", "windKt"}]}],
    "mean": [{"validAt", "lat", "lon", "n"}]}`；系集的 `mean` 是每個時間點有點的成員的**中位數位置**
    （經緯各取中位數，`n` 是成員數；少於 `MIN_ENS_MEMBERS` 個的時間點不寫），HRES 的 `mean` 是空的。
    產品裡沒有這顆時 `storm` 是 null、`members` 空的（照寫，表示那報找過了）

- **GFS、AIGFS、AIFS**：從海平面氣壓場找中心。三個來源事件期間多抓海平面氣壓（GFS、AIGFS `PRMSL`、
  AIFS `msl`，步長和原本一樣：起報後第一個 6 小時格起 120 小時、每 6 小時），`find_track`：
  1. 起點（`find_seed`）：起報時間前後 `SEED_WINDOW`（3 小時）內 JTWC、再 JMA 的 `analysis`
     （`position/*.jsonl`，離起報時間最近的、同樣近取發布較晚的）；都沒有就用 `events.json` 的
     `seed`（`at` 也要在 3 小時內）；再沒有就用同一報 ECMWF `tf` 產品裡那顆的觀測位置（`ecmwf-tf`；
     HD20 上線以前的報沒有現報，補過去的報靠這個）；都沒有就跳過這報、記 log（不寫檔）
  2. 第一個步長在起點 ±`SEED_BOX_DEG`（4°）的方框找最小值；之後每步在上一步中心
     ±`STEP_BOX_DEG`（3°）的方框找。格點 0.25°、不內插
  3. 停止（這步起不再追，`stop` 記原因）：最小值 > `MAX_CENTER_HPA`（1005 hPa，`weak`）、方框裡
     最小點在邊界上（`edge`）、中心跨出北緯 0–40°／東經 100–180°（`domain`）、步長不連續（`gap`）；
     追到最後一個步長是 `end`
  - 格式：`{"model": "gfs"|"aigfs"|"aifs", "run", "seed": {"lat", "lon", "at", "source"},
    "points": [{"validAt", "lat", "lon", "mslpHpa"}], "stop"}`

接進 build（`build_tracks`）：模式都抓完之後、只在有事件在期間內時跑（`BUDGET_S["tracks"]`）；
IFS／系集用這一報 HRES 的時次，GFS、AIGFS、AIFS 用各自這一報的時次與抓到的檔；已經有的
`tracks/<時次>-<模式>.json` 跳過（同一報不會抽兩次）。補過去的報（`backfill_tracks`）：讀
`history/events/<id>/<時間>.json` 的 `runs`，每個模式每個時次只抽一次，GFS、AIGFS 從 AWS 重抓
海平面氣壓（留 30 天）、IFS、AIFS 從 ECMWF 開放資料抓（約 4 天，拿不到記 log）。
"""

from __future__ import annotations

import functools
import json
import logging
import re
import statistics
import warnings
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from math import asin, cos, radians, sin, sqrt
from pathlib import Path

import numpy as np

from . import grib
from .budget import check_cancelled
from .config import Event
from .events import _stamp_time, event_dir
from .sources import SourceError, aifs, aigfs, ecmwf, gfs, http_get
from .timeutil import floor_6h, hours_between, iso, parse_time
from .units import ms_to_kt

log = logging.getLogger("hongthai")

TRACK_MODELS = ("ifs", "ifs-ens", "gfs", "aigfs", "aifs")
MSLP_MODELS = ("gfs", "aigfs", "aifs")
TF_STREAMS = {"ifs": "oper", "ifs-ens": "enfo"}
TF_STEP = {0: 360, 6: 144, 12: 360, 18: 144}
# 每個模式在快照 `runs` 裡的鍵（補過去的報用）；系集的路徑產品四個時次都有，和 HRES 一樣抽
RUN_KEYS = {
    "ifs": ("ecmwf", "ecmwfEns"),
    "ifs-ens": ("ecmwf", "ecmwfEns"),
    "gfs": ("gfs",),
    "aigfs": ("aigfs",),
    "aifs": ("aifs",),
}
MSLP_SHORT_NAMES = ("prmsl", "msl")  # GFS／AIGFS、AIFS 在 cfgrib 的名字

LAT_RANGE = (0.0, 40.0)
LON_RANGE = (100.0, 180.0)
CROP_MARGIN_DEG = 5.0  # 讀場時多留的邊（方框最大 ±4°）
SEED_BOX_DEG = 4.0
STEP_BOX_DEG = 3.0
MAX_CENTER_HPA = 1005.0
STEP_H = 6
SEED_WINDOW = timedelta(hours=3)
MATCH_KM = 300.0
MIN_ENS_MEMBERS = 10
_EPS = 1e-6


class TracksError(SourceError):
    pass


def track_path(d: Path, run: datetime, model: str) -> Path:
    return d / "tracks" / f"{run:%Y%m%dT%H%M}Z-{model}.json"


def write_doc(path: Path, doc: dict) -> None:
    """不縮排（系集 51 個成員約 150 KB）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(doc, ensure_ascii=False, separators=(",", ":"))
    path.write_text(text + "\n", encoding="utf-8")


def _is_num(v: object) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool)


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = radians(lat1), radians(lat2)
    a = sin((p2 - p1) / 2) ** 2 + cos(p1) * cos(p2) * sin(radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * asin(sqrt(min(1.0, a)))


# ---- 起點：JMA／JTWC 現報 ----


def read_positions(d: Path, source: str) -> list[dict]:
    rows = []
    for p in sorted((d / "position").glob(f"{source}-*.jsonl")):
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def position_near(d: Path, at: datetime, window: timedelta = SEED_WINDOW) -> dict | None:
    """`at` 前後 `window` 內的現報位置：JTWC 優先、再 JMA；`analysis` 裡 `validAt` 離 `at` 最近的
    （同樣近取發布較晚的）。回傳 `{"lat", "lon", "at", "source"}`。"""
    for source in ("jtwc", "jma"):
        best: tuple[tuple[float, float], dict] | None = None
        for r in read_positions(d, source):
            lat, lon = r.get("lat"), r.get("lon")
            if r.get("kind") != "analysis" or not (_is_num(lat) and _is_num(lon)):
                continue
            try:
                valid = parse_time(r.get("validAt"))
                issued = parse_time(r.get("issuedAt"))
            except (TypeError, ValueError):
                continue
            if valid is None or abs(valid - at) > window:
                continue
            key = (abs(valid - at).total_seconds(), -(issued or valid).timestamp())
            if best is None or key < best[0]:
                best = (key, {"lat": lat, "lon": lon, "at": iso(valid), "source": source})
        if best is not None:
            return best[1]
    return None


def event_seed(event: Event, run: datetime) -> dict | None:
    s = event.seed
    if s is None or abs(s.at - run) > SEED_WINDOW:
        return None
    return {"lat": s.lat, "lon": s.lon, "at": iso(s.at), "source": "events.json"}


def find_seed(
    d: Path, run: datetime, event: Event, observed: Callable[[], dict | None] | None = None
) -> dict | None:
    """JTWC → JMA → `events.json` 的 `seed` → `observed()`（ECMWF `tf` 的觀測位置）。"""
    seed = position_near(d, run) or event_seed(event, run)
    if seed is None and observed is not None:
        seed = observed()
    return seed


# ---- 海平面氣壓場 → 中心 ----


@dataclass
class Field:
    """裁到追蹤範圍（含邊）的海平面氣壓：緯度、經度（0–360）都由小到大，`hpa[緯, 經]`。"""

    lats: np.ndarray
    lons: np.ndarray
    hpa: np.ndarray


def _crop(lats: np.ndarray, lons: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    m = CROP_MARGIN_DEG
    lons = lons % 360
    li = np.nonzero((lats >= LAT_RANGE[0] - m) & (lats <= LAT_RANGE[1] + m))[0]
    lj = np.nonzero((lons >= LON_RANGE[0] - m) & (lons <= LON_RANGE[1] + m))[0]
    return li[np.argsort(lats[li])], lj[np.argsort(lons[lj])], lons


def read_mslp(paths: Iterable[Path]) -> dict[datetime, Field]:
    """GRIB 檔裡的海平面氣壓（`MSLP_SHORT_NAMES`，Pa）→ `{有效時間: Field}`（hPa）。"""
    import cfgrib  # 延後載入：沒有 eccodes 的環境也能跑其他測試

    out: dict[datetime, Field] = {}
    for path in paths:
        if not Path(path).exists():
            log.warning("海平面氣壓的檔 %s 不見了", path)
            continue
        check_cancelled()
        with grib.GRIB_LOCK:
            check_cancelled()
            # 不用 `filter_by_keys`：比不到任何訊息時 cfgrib 丟 KeyError。其他變數只建索引、不解碼
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", FutureWarning)
                datasets = cfgrib.open_datasets(str(path), backend_kwargs={"indexpath": ""})
            for ds in datasets:
                try:
                    _read_dataset(ds, out)
                finally:
                    ds.close()
    return out


def _read_dataset(ds, out: dict[datetime, Field]) -> None:
    names = [v for v in ds.data_vars if ds[v].attrs.get("GRIB_shortName") in MSLP_SHORT_NAMES]
    if not names:
        return
    run = grib._to_datetime(ds["time"].values)
    steps = np.atleast_1d(ds["step"].values) / np.timedelta64(1, "h")
    lats = np.asarray(ds["latitude"].values, dtype=float)
    li, lj, lons = _crop(lats, np.asarray(ds["longitude"].values, dtype=float))
    for var in names:
        da = ds[var]
        for k, step in enumerate(steps):
            one = da.isel(step=k) if "step" in da.dims else da
            vals = np.asarray(one.values, dtype=float)[np.ix_(li, lj)] / 100
            out[run + timedelta(hours=float(step))] = Field(lats[li], lons[lj], vals)


def box_min(
    f: Field, lat: float, lon: float, half: float
) -> tuple[float, float, float, bool] | None:
    """（lat, lon）± `half` 度方框裡的最小值 →（緯, 經, hPa, 在不在方框邊界上）；方框裡沒資料
    回 None。"""
    li = np.nonzero(np.abs(f.lats - lat) <= half + _EPS)[0]
    lj = np.nonzero(np.abs(f.lons - lon % 360) <= half + _EPS)[0]
    if not len(li) or not len(lj):
        return None
    sub = f.hpa[np.ix_(li, lj)]
    if np.all(np.isnan(sub)):
        return None
    i, j = divmod(int(np.nanargmin(sub)), sub.shape[1])
    edge = i in (0, len(li) - 1) or j in (0, len(lj) - 1)
    return float(f.lats[li[i]]), float(f.lons[lj[j]]), float(sub[i, j]), edge


def in_domain(lat: float, lon: float) -> bool:
    return LAT_RANGE[0] <= lat <= LAT_RANGE[1] and LON_RANGE[0] <= lon % 360 <= LON_RANGE[1]


def find_track(fields: dict[datetime, Field], lat: float, lon: float) -> tuple[list[dict], str]:
    """從起點逐步追中心（規則見模組說明）；回傳（各步的點, 停止原因）。"""
    points: list[dict] = []
    half = SEED_BOX_DEG
    prev: datetime | None = None
    for valid in sorted(fields):
        if prev is not None and valid - prev != timedelta(hours=STEP_H):
            return points, "gap"
        hit = box_min(fields[valid], lat, lon, half)
        if hit is None:
            return points, "edge"
        clat, clon, hpa, edge = hit
        if hpa > MAX_CENTER_HPA:
            return points, "weak"
        if edge:
            return points, "edge"
        if not in_domain(clat, clon):
            return points, "domain"
        points.append({"validAt": iso(valid), "lat": clat, "lon": clon, "mslpHpa": round(hpa, 1)})
        lat, lon, half, prev = clat, clon, STEP_BOX_DEG, valid
    return points, "end"


def mslp_doc(model: str, run: datetime, seed: dict, fields: dict[datetime, Field]) -> dict:
    points, stop = find_track(fields, seed["lat"], seed["lon"])
    return {"model": model, "run": iso(run), "seed": seed, "points": points, "stop": stop}


# ---- ECMWF 颱風路徑產品（BUFR）----


@dataclass
class TfMember:
    number: int
    control: bool
    points: list[dict]


@dataclass
class TfStorm:
    id: str
    name: str
    run: datetime
    observed: tuple[float, float] | None
    members: list[TfMember]

    def position(self) -> tuple[float, float] | None:
        if self.observed is not None:
            return self.observed
        first = next((m.points[0] for m in self.members if m.points), None)
        return None if first is None else (first["lat"], first["lon"])


def _missing(v: float) -> bool:
    return not np.isfinite(v) or abs(v) >= 1e99 or v == 2147483647


def parse_tf(path: str | Path) -> list[TfStorm]:
    """ECMWF `tf` BUFR → 每個 storm 一筆（格式見模組說明）。"""
    import eccodes  # 延後載入

    storms = []
    with grib.GRIB_LOCK, open(path, "rb") as f:
        while (h := eccodes.codes_bufr_new_from_file(f)) is not None:
            try:
                eccodes.codes_set(h, "unpack", 1)
                storms.append(_tf_storm(eccodes, h))
            finally:
                eccodes.codes_release(h)
    return storms


def _tf_storm(eccodes, h) -> TfStorm:
    n = int(eccodes.codes_get(h, "numberOfSubsets"))

    def values(key: str) -> list[float | None]:
        if not eccodes.codes_is_defined(h, key):
            return [None] * n
        arr = [float(v) for v in np.atleast_1d(eccodes.codes_get_array(h, key))]
        out = [None if _missing(v) else v for v in arr]
        return out * n if len(out) == 1 else out

    def first(key: str) -> float | None:
        return next((v for v in values(key) if v is not None), None)

    run = datetime(
        *(int(first(f"#1#{k}") or 0) for k in ("year", "month", "day", "hour", "minute")),
        tzinfo=UTC,
    )
    rep = first("#1#delayedDescriptorReplicationFactor")
    # （小時, 位置的序號, 氣壓與風的序號）；起報那一刻用分析位置 #2#
    times = [(0, 2, 1)] + [
        (int(first(f"#{k}#timePeriod") or 0), 2 * k + 2, k + 1) for k in range(1, int(rep or 0) + 1)
    ]
    cols = []
    for hours, pos, val in times:
        cols.append(
            (
                iso(run + timedelta(hours=hours)),
                values(f"#{pos}#latitude"),
                values(f"#{pos}#longitude"),
                values(f"#{val}#pressureReducedToMeanSeaLevel"),
                values(f"#{val}#windSpeedAt10M"),
            )
        )
    numbers = values("#1#ensembleMemberNumber")
    kinds = values("#1#ensembleForecastType")
    members = []
    for i in range(n):
        pts = []
        for valid, lat, lon, p, w in cols:
            if lat[i] is None or lon[i] is None:
                continue
            pts.append(
                {
                    "validAt": valid,
                    "lat": round(lat[i], 2),  # BUFR 是 0.1°，解碼後有浮點雜訊
                    "lon": round(lon[i], 2),
                    "pressureHpa": None if p[i] is None else round(p[i] / 100, 1),
                    "windKt": None if w[i] is None else round(ms_to_kt(w[i]), 1),
                }
            )
        members.append(TfMember(int(numbers[i] or 0), kinds[i] == 0, pts))
    obs_lat, obs_lon = first("#1#latitude"), first("#1#longitude")
    return TfStorm(
        str(eccodes.codes_get(h, "#1#stormIdentifier")).strip(),
        str(eccodes.codes_get(h, "#1#longStormName")).strip(),
        run,
        None if obs_lat is None or obs_lon is None else (round(obs_lat, 2), round(obs_lon, 2)),
        members,
    )


_JTWC_FILE = re.compile(r"^(wp|ep|cp)(\d{2})\d{2}$", re.IGNORECASE)
_BASIN = {"wp": "W", "ep": "E", "cp": "C"}
_NAME = re.compile(r"\s*([A-Za-z][A-Za-z' -]*[A-Za-z])")


def storm_ids(event: Event) -> set[str]:
    """`wp2926` → `29W`；事件 id 本身像 `29W` 的也算。"""
    ids = set()
    if event.jtwc_id and (m := _JTWC_FILE.match(event.jtwc_id)):
        ids.add(f"{m[2]}{_BASIN[m[1].lower()]}")
    if re.fullmatch(r"\d{2}[A-Z]", event.id):
        ids.add(event.id)
    return ids


def storm_name(event: Event) -> str | None:
    """`CHAMPI（薔琵）` → `CHAMPI`。"""
    m = _NAME.match(event.name)
    return m[1].upper() if m else None


def pick_storm(storms: list[TfStorm], event: Event, ref: dict | None) -> tuple[TfStorm, str] | None:
    """事件那顆：編號 → 名稱 → 離 `ref`（現報位置）`MATCH_KM` 內最近的；回傳
    （storm, 怎麼比到的）。"""
    ids, name = storm_ids(event), storm_name(event)
    for s in storms:
        if s.id.upper() in ids:
            return s, "id"
    for s in storms:
        if name and s.name.upper() == name:
            return s, "name"
    if ref is None:
        return None
    near = []
    for s in storms:
        pos = s.position()
        if pos is not None:
            km = distance_km(ref["lat"], ref["lon"], *pos)
            if km <= MATCH_KM:
                near.append((km, s))
    return (min(near, key=lambda x: x[0])[1], "distance") if near else None


def ens_mean(members: list[dict]) -> list[dict]:
    """每個時間點有點的成員的中位數位置（經緯各取中位數）；成員少於 `MIN_ENS_MEMBERS` 的
    時間點不寫。"""
    by_time: dict[str, list[tuple[float, float]]] = {}
    for m in members:
        for p in m["points"]:
            by_time.setdefault(p["validAt"], []).append((p["lat"], p["lon"]))
    return [
        {
            "validAt": t,
            "lat": round(statistics.median(a for a, _ in pos), 2),
            "lon": round(statistics.median(b for _, b in pos), 2),
            "n": len(pos),
        }
        for t, pos in sorted(by_time.items())
        if len(pos) >= MIN_ENS_MEMBERS
    ]


def tf_doc(
    model: str, run: datetime, storms: list[TfStorm], event: Event, ref: dict | None
) -> dict:
    hit = pick_storm(storms, event, ref)
    if hit is None:
        log.warning("%s %s 的路徑產品裡沒有 %s", model, iso(run), event.id)
        return {"model": model, "run": iso(run), "storm": None, "members": [], "mean": []}
    storm, how = hit
    members = [
        {"member": 0 if model == "ifs" else m.number, "points": m.points}
        for m in storm.members
        if m.points
    ]
    if model == "ifs":
        members = members[:1]
    obs = storm.observed
    return {
        "model": model,
        "run": iso(run),
        "storm": {
            "id": storm.id,
            "name": storm.name,
            "matchedBy": how,
            "observed": None if obs is None else {"lat": obs[0], "lon": obs[1]},
        },
        "members": members,
        "mean": ens_mean(members) if model == "ifs-ens" else [],
    }


# ---- 下載 ----


class Downloads:
    """一次 build 或補報的下載：同一個（stream, 時次）的 `tf` 只抓一次；`bytes` 是總下載量。"""

    def __init__(self, workdir: Path):
        self.workdir = workdir
        self.bytes = 0
        self._tf: dict[tuple[str, datetime], list[TfStorm] | None] = {}
        self._ec = functools.cache(ecmwf._client)
        self._aifs = functools.cache(functools.partial(ecmwf._client, model=aifs.MODEL))

    def tf(self, stream: str, run: datetime) -> list[TfStorm]:
        key = (stream, run)
        if key not in self._tf:
            self._tf[key] = None  # 失敗也記著，同一次不重抓
            self.workdir.mkdir(parents=True, exist_ok=True)
            path = self.workdir / f"tf-{stream}-{run:%Y%m%d%H}.bufr"
            size, mirror = ecmwf._download(
                self._ec,
                path,
                label="ECMWF tf",
                date=run.strftime("%Y%m%d"),
                time=run.hour,
                stream=stream,
                type="tf",
                step=TF_STEP[run.hour],
            )
            self.bytes += size
            log.info("ECMWF tf %s %s：%d bytes（%s）", stream, iso(run), size, mirror)
            self._tf[key] = parse_tf(path)
        storms = self._tf[key]
        if storms is None:
            raise TracksError(f"ECMWF tf {stream} {iso(run)} 剛才抓失敗了", "tf_failed")
        return storms

    def mslp(self, model: str, run: datetime, steps: list[int]) -> list[Path]:
        """補過去的報：重抓那一報的海平面氣壓（GFS、AIGFS 從 AWS，AIFS 從 ECMWF 開放資料）。"""
        self.workdir.mkdir(parents=True, exist_ok=True)
        if model == "aifs":
            path = self.workdir / f"aifs-msl-{run:%Y%m%d%H}.grib2"
            size, _ = ecmwf._download(
                self._aifs,
                path,
                label="AIFS msl",
                date=run.strftime("%Y%m%d"),
                time=run.hour,
                stream="oper",
                type="fc",
                param=[aifs.MSLP_PARAM],
                step=steps,
            )
            self.bytes += size
            return [path]
        mod = gfs if model == "gfs" else aigfs
        paths = []
        for fh in steps:
            url = f"{mod.S3_URL}{mod.run_dir(run)}/{mod.file_name(run, fh)}"
            idx = http_get(f"{url}.idx", error=TracksError).text
            ranges = grib.byte_ranges(
                idx, (mod.MSLP_FIELD,), fh, error=TracksError, label=model.upper()
            )
            path = self.workdir / f"{model}-msl-{run:%Y%m%d%H}-f{fh:03d}.grib2"
            self.bytes += gfs.download_ranges(url, ranges, path, TracksError)
            paths.append(path)
        return paths


def mslp_steps(model: str, run: datetime, slot0: datetime) -> list[int]:
    """和那一報 build 時抓的步長一樣：`slot0` 起 120 小時、每 6 小時（AIFS 不抓第 0 步）。"""
    rel0 = int(hours_between(run, slot0))
    if model == "aifs":
        return aifs.steps(rel0)
    return list(range(rel0, rel0 + gfs.SPAN_H + 1, gfs.STEP_H))


# ---- 抽一報 ----


@dataclass
class TracksResult:
    written: list[Path] = field(default_factory=list)
    skipped: int = 0  # 已經有的
    no_seed: int = 0  # 找不到起點、跳過的
    failed: list[str] = field(default_factory=list)  # `<模式>@<時次>`
    bytes: int = 0


def observed_seed(dl: Downloads, event: Event, run: datetime) -> dict | None:
    """同一報 ECMWF `tf`（HRES）裡事件那顆的觀測位置（發布中心的現報）。"""
    try:
        hit = pick_storm(dl.tf("oper", run), event, None)
    except Exception as e:  # 抓不到就沒有這個備案
        log.warning("事件 %s：%s 的 ECMWF tf 拿不到，不能當起點：%s", event.id, iso(run), e)
        return None
    if hit is None or hit[0].observed is None:
        return None
    lat, lon = hit[0].observed
    return {"lat": lat, "lon": lon, "at": iso(run), "source": "ecmwf-tf"}


def extract(
    d: Path,
    event: Event,
    model: str,
    run: datetime,
    dl: Downloads,
    fields: Callable[[], dict[datetime, Field]],
) -> Path | None:
    """抽一個模式的一報並寫檔；找不到起點回 None（不寫）。下載或解析失敗丟例外。"""
    if model in TF_STREAMS:
        ref = position_near(d, run) or event_seed(event, run)
        doc = tf_doc(model, run, dl.tf(TF_STREAMS[model], run), event, ref)
    else:
        seed = find_seed(d, run, event, lambda: observed_seed(dl, event, run))
        if seed is None:
            log.warning("事件 %s：%s %s 找不到起點（沒有現報），跳過", event.id, model, iso(run))
            return None
        doc = mslp_doc(model, run, seed, fields())
    path = track_path(d, run, model)
    write_doc(path, doc)
    return path


def _job(
    res: TracksResult,
    d: Path,
    event: Event,
    model: str,
    run: datetime,
    dl: Downloads,
    fields: Callable[[], dict[datetime, Field]],
) -> None:
    if track_path(d, run, model).exists():
        res.skipped += 1
        return
    try:
        path = extract(d, event, model, run, dl, fields)
    except Exception as e:  # 一個模式失敗不擋其他的
        log.warning("事件 %s：%s %s 的路徑抽不出來：%s", event.id, model, iso(run), e)
        res.failed.append(f"{model}@{iso(run)}")
        return
    if path is None:
        res.no_seed += 1
        return
    res.written.append(path)
    log.info("事件 %s：路徑 → %s", event.id, path)


def build_tracks(
    history: Path,
    events: list[Event],
    ifs_run: datetime | None,
    mslp: dict[str, tuple[datetime, list[Path]]],
    workdir: Path,
) -> TracksResult:
    """build 裡用：IFS／系集用 `ifs_run`（這一報 HRES 的時次），`mslp` 是各模式（`MSLP_MODELS`）
    這一報的時次與有海平面氣壓的檔。沒抓到的模式（來源失敗）不在 `mslp` 裡，只 log。"""
    dl = Downloads(workdir)
    res = TracksResult()
    cache: dict[str, dict[datetime, Field]] = {}

    def fields_of(model: str) -> dict[datetime, Field]:
        if model not in cache:
            files = mslp[model][1]
            if not files:
                raise TracksError(f"{model} 這一報沒有抓到海平面氣壓", "no_mslp")
            cache[model] = read_mslp(files)
        return cache[model]

    jobs: list[tuple[str, datetime]] = []
    if ifs_run is not None:
        jobs += [("ifs", ifs_run), ("ifs-ens", ifs_run)]
    for model in MSLP_MODELS:
        if model in mslp:
            jobs.append((model, mslp[model][0]))
        else:
            log.warning("%s 這一報沒抓到，不抽路徑", model)
    if ifs_run is None:
        log.warning("ECMWF 這一報沒抓到，IFS／系集不抽路徑")
    for e in events:
        d = event_dir(history, e)
        for model, run in jobs:
            _job(res, d, e, model, run, dl, functools.partial(fields_of, model))
    res.bytes = dl.bytes
    return res


def runs_wanted(d: Path, since: datetime) -> dict[tuple[str, datetime], datetime]:
    """`d/<時間>.json`（時間 ≥ `since`）的 `runs` → `{(模式, 時次): 最早那份的 slot0}`。"""
    wanted: dict[tuple[str, datetime], datetime] = {}
    for p in sorted(d.glob("*.json")):
        t = _stamp_time(p.stem)
        if t is None or t < since:
            continue
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            log.warning("快照 %s 讀不了，跳過", p)
            continue
        runs = doc.get("runs") if isinstance(doc, dict) else None
        if not isinstance(runs, dict):
            continue
        for model, keys in RUN_KEYS.items():
            for key in keys:
                try:
                    run = parse_time(runs.get(key))
                except (TypeError, ValueError):
                    run = None
                if run is not None:
                    wanted.setdefault((model, run), floor_6h(t))
    return wanted


def backfill_tracks(
    history: Path, events: list[Event], since: datetime, workdir: Path
) -> dict[str, TracksResult]:
    """補過去的報（`python -m hongthai.events backfill-tracks`）；已經有的跳過。"""
    out = {}
    for e in events:
        d = event_dir(history, e)
        dl = Downloads(workdir)
        res = TracksResult()
        wanted = runs_wanted(d, since)
        for (model, run), slot0 in sorted(
            wanted.items(), key=lambda kv: (kv[0][1], TRACK_MODELS.index(kv[0][0]))
        ):

            def fields(model=model, run=run, slot0=slot0, dl=dl) -> dict[datetime, Field]:
                return read_mslp(dl.mslp(model, run, mslp_steps(model, run, slot0)))

            _job(res, d, e, model, run, dl, fields)
            for p in workdir.glob("*.grib2"):  # 一報抽完就刪，不佔磁碟
                p.unlink(missing_ok=True)
        res.bytes = dl.bytes
        out[e.id] = res
    return out
