"""颱風 29W（CHAMPI）的驗證報告（HD22）：各系統依提前時間的陣風誤差、停飛命中、路徑誤差。

在 repo 根目錄跑（`data` 是 `data` 分支的 checkout，底下有 `history/`）：

    python -m tools.report_29w --archive data --event 29W \\
      [--jtwc bwp292026.dat] [--jma bst_all.txt] [--cutoff 2026-10-22T04:00Z] \\
      [--cancel-rate 0.3 --cancel-count 10] [--out report/29W.md] [--json report/29W.json]

純讀 `history/events/<id>/`（快照、`metar/`、`position/`、`tracks/`、`wn3/`）、
`history/cancellations/`、`history/ai/`，不改任何檔案（除了 `--out`／`--json`）。只用標準函式庫，
不用裝 numpy／eccodes。標準輸出印摘要；沒給 `--out` 時整份 Markdown 印在標準輸出。

定案（Shawn 2026-10-20，`docs/prompts/2026-10-20-HD22-29w-report.md`）：

- 提前時間分五段 0–24、24–48、48–72、72–96、96–120 小時（左閉右開，120 歸最後一段）。格的提前時間是
  `from − generatedAt`；這一報所在的那格（`from` 在 `generatedAt` 前、`to` 在後）算 0–24，已經
  結束的格不算。WN3 的事件檔沒有 `generatedAt`，用 `from − 起報`；路徑是 `validAt − 起報`
- 版本：`generatedAt` < `--cutoff`（預設 2026-10-22T04:00Z＝台北 10/22 12:00）是「定版前」
  （5 票與試跑中的 8 票），之後是「定版後」。只有規則燈分版本，各模式與 AI 不分
- (a) 陣風：每報每機場每格，預測是 `slot.model.models[]` 那筆的 `gustKt`（`gustEstimated` 的模式標
  `*`；WN3 用 `wn3/<起報>.json`）；實測是格內 METAR 的最大值（有陣風用陣風、沒有用平均風；格內沒有
  觀測就跳過）。分兩組印：全部、格內最大平均風 ≥ 10 節（和估算陣風係數的樣本一樣）。門檻 37／48 節
  的命中＝預測與實測都過門檻、漏報＝實測過預測沒過、誤報＝預測過實測沒過
- (b) 等級：只算 `events.json` 的機場裡有航班資料（`history/cancellations/` 有列）的。一格停飛＝
  （出發＋抵達）取消率 ≥ `--cancel-rate` 或取消 ≥ `--cancel-count` 班；格的 `to` 晚於航班資料最新
  的 `asOf` 時還沒有結果，不算；結束了但沒有那格的列（那格沒有航班）也不算。「判中或高」＝
  `medium`／`high`／`confirmed`，「判高」＝`high`／`confirmed`；`unknown` 不算。
  - **每格**：只有規則燈（AI 沒有每格的等級）
  - **每報每機場**：AI 兩燈是整個機場未來 5 天一個等級，所以和「這報 0–120 小時內任一格停飛」比；
    規則燈取同一範圍的最高等級一起比。窗裡最後一格還沒結束的不算。FP 沒有提前時間，所以提前段只印
    召回率（依窗裡第一個停飛格的提前時間）。AI 用快照的 `airports[].ai`，`status: ok` 才算；快照沒有
    `ai` 時用 `history/ai/<日期>.json` 同一報同機場那筆
- (c) 路徑：`tracks/<起報>-<模式>.json` 的每個點對真相內插到同一 `validAt`（線性；前後兩點相隔超過
  `MAX_GAP_H` 小時不內插）的大圓距離（公里）。IFS 用 HRES（`member: 0`）、系集用中位數位置
  （`mean`），系集另印成員誤差與離散（成員到中位數的平均距離）。真相：`--jtwc`（ATCF b-deck）、
  `--jma`（JMA `bst_all.txt` 或單一颱風的檔）給了哪份比哪份、兩份並列；都沒給時用 `position/`
  的現報（`analysis`）當暫時真相：JTWC 內插得到就用 JTWC，不然用 JMA
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from math import asin, cos, radians, sin, sqrt
from pathlib import Path
from statistics import mean, median
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from hongthai.config import Event, load_events  # noqa: E402
from hongthai.timeutil import iso, parse_time  # noqa: E402
from hongthai.units import KT_PER_MS  # noqa: E402

TAIPEI = ZoneInfo("Asia/Taipei")
BUCKETS = ((0, 24), (24, 48), (48, 72), (72, 96), (96, 120))
BUCKET_LABELS = tuple(f"{a}–{b}" for a, b in BUCKETS)
MAX_LEAD_H = 120
DEFAULT_CUTOFF = "2026-10-22T04:00Z"
BEFORE, AFTER = "定版前", "定版後"
# 8 票（HD16）；10/21 前只有前 5 個。WN3 只有 report-only 的事件檔
EXPECTED_MODELS = ("ifs", "gfs", "ifs-ens", "aifs", "aigfs", "icon", "jma", "wn2-ens")
MODEL_ORDER = (*EXPECTED_MODELS, "wn3")
TRACK_ORDER = ("ifs", "ifs-ens", "gfs", "aigfs", "aifs", "wn3")
AI_KEYS = ("claude", "gemini")
AI_NAMES = {"claude": "Claude", "gemini": "Gemini"}
RISKY = ("medium", "high", "confirmed")
HIGH = ("high", "confirmed")
LEVELS = ("low", *RISKY)
GUST_THRESHOLDS = (37, 48)
MIN_WIND_KT = 10
MAX_GAP_H = 12
_STAMP = "%Y%m%dT%H%MZ"
_TRACK_FILE = re.compile(r"^(\d{8}T\d{4}Z)-(.+)\.json$")
_NAME = re.compile(r"[A-Za-z][A-Za-z' -]*[A-Za-z]")


# ---- 小工具 ----


def _num(v: object) -> float | None:
    return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else None


def lead_hours(t: datetime, ref: datetime) -> float:
    return (t - ref).total_seconds() / 3600


def bucket(lead: float) -> int | None:
    """提前時間（小時）→ 第幾段；負的（這一報所在的那格）算 0–24，超過 120 回 None。"""
    if lead > MAX_LEAD_H:
        return None
    if lead < 0:
        return 0
    return min(int(lead // 24), len(BUCKETS) - 1)


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """大圓距離（同 `hongthai.tracks.distance_km`；那支要 numpy／eccodes，這裡不載入）。"""
    p1, p2 = radians(lat1), radians(lat2)
    a = sin((p2 - p1) / 2) ** 2 + cos(p1) * cos(p2) * sin(radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * asin(sqrt(min(1.0, a)))


def version_of(generated: datetime, cutoff: datetime) -> str:
    return BEFORE if generated < cutoff else AFTER


def storm_name(event: Event) -> str | None:
    """`CHAMPI（薔琵）` → `CHAMPI`。"""
    m = _NAME.search(event.name)
    return m.group(0).upper() if m else None


def _read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _jsonl(paths: Iterable[Path]) -> list[dict]:
    rows = []
    for p in paths:
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


# ---- 真相：METAR ----


@dataclass
class Obs:
    at: datetime
    value: float  # 有陣風用陣風、沒有用平均風
    wind: float


def load_metars(d: Path) -> dict[str, list[Obs]]:
    """`metar/*.jsonl` → 每站的觀測（依時間排序；同一站同一 `observedAt` 只留一筆）。"""
    seen: set[tuple[str, datetime]] = set()
    out: dict[str, list[Obs]] = defaultdict(list)
    for r in _jsonl(sorted((d / "metar").glob("*.jsonl"))):
        icao, at, wind = r.get("icao"), parse_time(r.get("observedAt")), _num(r.get("windKt"))
        if not isinstance(icao, str) or at is None or wind is None or (icao, at) in seen:
            continue
        seen.add((icao, at))
        gust = _num(r.get("gustKt"))
        out[icao].append(Obs(at, gust if gust is not None else wind, wind))
    for obs in out.values():
        obs.sort(key=lambda o: o.at)
    return dict(out)


def slot_obs(obs: list[Obs], start: datetime, end: datetime) -> tuple[float, float] | None:
    """格內（`start` ≤ 觀測 < `end`）的（最大陣風或平均風, 最大平均風）；沒有觀測回 None。"""
    inside = [o for o in obs if start <= o.at < end]
    if not inside:
        return None
    return max(o.value for o in inside), max(o.wind for o in inside)


# ---- 真相：停飛 ----


@dataclass
class Cancellations:
    rows: dict[tuple[str, datetime], dict]
    as_of: datetime | None
    airports: frozenset[str]

    def stopped(
        self, airport: str, start: datetime, end: datetime, rate: float, count: int
    ) -> bool | None:
        """那格停飛了沒；還沒結束或沒有那格的列回 None。"""
        if self.as_of is None or end > self.as_of:
            return None
        row = self.rows.get((airport, start))
        if row is None:
            return None
        return is_stopped(row, rate, count)


def is_stopped(row: dict, rate: float, count: int) -> bool | None:
    total = cancelled = 0
    for k in ("dep", "arr"):
        part = row.get(k) or {}
        total += int(part.get("total") or 0)
        cancelled += int(part.get("cancelled") or 0)
    if total <= 0:
        return None
    return cancelled >= count or cancelled / total >= rate


def load_cancellations(history: Path) -> Cancellations:
    rows: dict[tuple[str, datetime], dict] = {}
    as_of = None
    for p in sorted((history / "cancellations").glob("????-??-??.json")):
        doc = _read_json(p)
        for r in doc if isinstance(doc, list) else []:
            if not isinstance(r, dict):
                continue
            start, t = parse_time(r.get("from")), parse_time(r.get("asOf"))
            if not isinstance(r.get("airport"), str) or start is None:
                continue
            rows[(r["airport"], start)] = r
            if t is not None and (as_of is None or t > as_of):
                as_of = t
    return Cancellations(rows, as_of, frozenset(a for a, _ in rows))


# ---- 真相：颱風位置 ----


@dataclass
class Track:
    """一條真相路徑（依時間排序的點）；`at` 線性內插。"""

    name: str
    points: list[tuple[datetime, float, float]]

    def at(self, t: datetime) -> tuple[float, float] | None:
        pts = self.points
        for i, (t1, lat1, lon1) in enumerate(pts):
            if t1 == t:
                return lat1, lon1
            if t1 > t:
                if i == 0:
                    return None
                t0, lat0, lon0 = pts[i - 1]
                if lead_hours(t1, t0) > MAX_GAP_H:
                    return None
                f = (t - t0) / (t1 - t0)
                return lat0 + (lat1 - lat0) * f, lon0 + (lon1 - lon0) * f
        return None


@dataclass
class Truth:
    """一份真相（JTWC、JMA，或現報）：依序試每條路徑，第一條內插得到的算。"""

    label: str
    tracks: list[Track]
    provisional: bool = False
    used: Counter[str] = field(default_factory=Counter)

    def at(self, t: datetime) -> tuple[float, float] | None:
        for tr in self.tracks:
            p = tr.at(t)
            if p is not None:
                self.used[tr.name] += 1
                return p
        return None


def _dedupe(points: Iterable[tuple[datetime, float, float]]) -> list[tuple[datetime, float, float]]:
    """同一時間留第一個，依時間排序。"""
    out: dict[datetime, tuple[datetime, float, float]] = {}
    for p in points:
        out.setdefault(p[0], p)
    return [out[t] for t in sorted(out)]


def _latlon(s: str) -> float:
    """ATCF 的 `165N`、`1344E`（十分之一度）。"""
    v = int(s[:-1]) / 10
    return -v if s[-1] in "SW" else v


def parse_atcf(text: str) -> list[tuple[datetime, float, float]]:
    """JTWC ATCF b-deck（`bwp292026.dat`）→ 最佳路徑的點；同一時間多行（34／50／64 節風圈）
    只留一個。逗號分隔：盆地、編號、`YYYYMMDDHH`、序號、`BEST`、提前（0）、緯、經、最大風、氣壓…"""
    pts = []
    for line in text.splitlines():
        f = [x.strip() for x in line.split(",")]
        if len(f) < 8 or not re.fullmatch(r"\d{10}", f[2]):
            continue
        if not re.fullmatch(r"\d+[NS]", f[6]) or not re.fullmatch(r"\d+[EW]", f[7]):
            continue
        t = datetime.strptime(f[2], "%Y%m%d%H").replace(tzinfo=UTC)
        pts.append((t, _latlon(f[6]), _latlon(f[7])))
    return _dedupe(pts)


@dataclass
class BstStorm:
    number: str  # 國際編號 `YYNN`（例如 2630）
    name: str
    points: list[tuple[datetime, float, float]]


def parse_jma_bst(text: str) -> list[BstStorm]:
    """JMA（RSMC Tokyo）最佳路徑 `bst_all.txt`（或單一颱風的檔）→ 每個颱風。表頭行
    `66666 <國際編號> <行數> …`，名稱在第 31–50 欄；資料行
    `YYMMDDHH 002 <等級> <緯×10> <經×10> <氣壓> [<最大風>] …`。"""
    storms: list[BstStorm] = []
    for line in text.splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "66666" and len(parts) >= 2:
            storms.append(BstStorm(parts[1], line[30:50].strip().upper(), []))
            continue
        if not storms or len(parts) < 5 or not re.fullmatch(r"\d{8}", parts[0]):
            continue
        try:
            t = datetime.strptime(parts[0], "%y%m%d%H").replace(tzinfo=UTC)
            lat, lon = int(parts[3]) / 10, int(parts[4]) / 10
        except ValueError:
            continue
        storms[-1].points.append((t, lat, lon))
    for s in storms:
        s.points = _dedupe(s.points)
    return storms


def pick_bst(storms: list[BstStorm], number: str | None, name: str | None) -> BstStorm:
    """指定國際編號就用那個；不然比名稱；檔裡只有一個就用那個。"""
    for s in storms:
        if number and s.number == number:
            return s
    if not number:
        named = [s for s in storms if name and s.name == name]
        if len(named) == 1:
            return named[0]
        if len(storms) == 1:
            return storms[0]
    raise ValueError(
        f"JMA 最佳路徑找不到 {number or name}（檔裡有 "
        f"{'、'.join(f'{s.number} {s.name}' for s in storms) or '沒有颱風'}）；用 --jma-id 指定"
    )


def provisional_tracks(d: Path) -> list[Track]:
    """`position/` 的現報（`analysis`）：JTWC、JMA 各一條，同一 `validAt` 取發布較晚的。"""
    out = []
    for source in ("jtwc", "jma"):
        best: dict[datetime, tuple[datetime, float, float]] = {}
        for r in _jsonl(sorted((d / "position").glob(f"{source}-*.jsonl"))):
            t, issued = parse_time(r.get("validAt")), parse_time(r.get("issuedAt"))
            lat, lon = _num(r.get("lat")), _num(r.get("lon"))
            if r.get("kind") != "analysis" or t is None or lat is None or lon is None:
                continue
            key = issued or t
            if t not in best or key >= best[t][0]:
                best[t] = (key, lat, lon)
        out.append(Track(source, [(t, best[t][1], best[t][2]) for t in sorted(best)]))
    return out


# ---- 每報快照 ----


@dataclass
class ModelGust:
    model: str
    gust: float
    estimated: bool


@dataclass
class Slot:
    start: datetime
    end: datetime
    level: str | None
    gusts: list[ModelGust]


@dataclass
class AirportReport:
    icao: str
    slots: list[Slot]
    ai: dict[str, str | None]  # claude／gemini → `status: ok` 的等級，其他 None


@dataclass
class Report:
    generated: datetime
    path: str
    votes: int | None
    model_runs: dict[str, str]  # 有資料的模式 → 起報
    ai_ok: dict[str, int]
    airports: dict[str, AirportReport]


def load_ai_records(history: Path) -> dict[tuple[str, str], dict]:
    """`history/ai/<日期>.json` → （`run`, 機場）→ 那筆戰績（快照沒有 `ai` 時用）。"""
    out = {}
    for p in sorted((history / "ai").glob("????-??-??.json")):
        doc = _read_json(p)
        for r in doc if isinstance(doc, list) else []:
            if isinstance(r, dict) and r.get("run") and r.get("airport"):
                out[(str(parse_time(r["run"])), r["airport"])] = r
    return out


def _ai_level(light: object) -> str | None:
    if not isinstance(light, dict) or light.get("status") != "ok":
        return None
    lv = light.get("level")
    return lv if lv in LEVELS else None


def model_entries(model: dict, runs: object) -> list[dict]:
    """`slot.model.models[]`（HD14 起）；更早的快照沒有，從 `ec`／`gfs` 拼出 IFS、系集、GFS 三筆
    （`hresGustKt` 或 `hresGustMs`、`gustKt` 或 `gustMs`；起報用頂層 `runs`）。"""
    entries = model.get("models")
    if isinstance(entries, list):
        return [e for e in entries if isinstance(e, dict) and isinstance(e.get("id"), str)]
    runs = runs if isinstance(runs, dict) else {}
    ec = model.get("ec") if isinstance(model.get("ec"), dict) else None
    gfs = model.get("gfs") if isinstance(model.get("gfs"), dict) else None
    out = []  # `level` 只用來算「這報有這個模式」（舊快照沒有每個模式的等級）
    if ec is not None:
        g = _num(ec.get("hresGustKt"))
        if g is None and (ms := _num(ec.get("hresGustMs"))) is not None:
            g = ms * KT_PER_MS
        if g is not None:
            out.append({"id": "ifs", "run": runs.get("ecmwf"), "gustKt": g, "level": "?"})
        if _num(ec.get("p10")) is not None:
            out.append({"id": "ifs-ens", "run": runs.get("ecmwfEns"), "gustKt": None, "level": "?"})
    if gfs is not None:
        g = _num(gfs.get("gustKt"))
        if g is None and (ms := _num(gfs.get("gustMs"))) is not None:
            g = ms * KT_PER_MS
        if g is not None:
            out.append({"id": "gfs", "run": runs.get("gfs"), "gustKt": g, "level": "?"})
    return out


def parse_report(
    doc: dict, path: str, airports: Iterable[str], ai_records: dict[tuple[str, str], dict]
) -> Report | None:
    """一份快照 → 報告要用的部分（只留 `airports` 的機場）；沒有 `generatedAt` 回 None。"""
    generated = parse_time(doc.get("generatedAt"))
    if generated is None:
        return None
    want = set(airports)
    votes: int | None = None
    runs: dict[str, str] = {}
    ai_ok = dict.fromkeys(AI_KEYS, 0)
    out: dict[str, AirportReport] = {}
    for a in doc.get("airports") or []:
        if not isinstance(a, dict):
            continue
        ai = a.get("ai") if isinstance(a.get("ai"), dict) else None
        if ai is None:
            ai = ai_records.get((str(generated), a.get("icao")))
        levels = {k: _ai_level((ai or {}).get(k)) for k in AI_KEYS}
        for k in AI_KEYS:
            ai_ok[k] += levels[k] is not None
        slots = []
        for s in a.get("slots") or []:
            start, end = parse_time(s.get("from")), parse_time(s.get("to"))
            if start is None or end is None:
                continue
            model = s.get("model") if isinstance(s.get("model"), dict) else {}
            total = _num((model.get("vote") or {}).get("total"))
            if total is not None:
                votes = max(votes or 0, int(total))
            gusts = []
            for e in model_entries(model, doc.get("runs")):
                if e.get("level") is not None and e.get("run"):
                    runs.setdefault(e["id"], e["run"])
                g = _num(e.get("gustKt"))
                if g is not None:
                    gusts.append(ModelGust(e["id"], g, bool(e.get("gustEstimated"))))
            lv = s.get("level")
            slots.append(Slot(start, end, lv if lv in LEVELS else None, gusts))
        if a.get("icao") in want:
            out[a["icao"]] = AirportReport(a["icao"], slots, levels)
    return Report(generated, path, votes, runs, ai_ok, out)


def report_files(d: Path) -> list[tuple[datetime, Path]]:
    files = []
    for p in d.glob("*.json"):
        try:
            files.append((datetime.strptime(p.stem, _STAMP).replace(tzinfo=UTC), p))
        except ValueError:
            continue
    return sorted(files)


def load_reports(d: Path, airports: Iterable[str], history: Path) -> list[Report]:
    ai_records = load_ai_records(history)
    airports = tuple(airports)
    out = []
    for _, p in report_files(d):
        doc = _read_json(p)
        if isinstance(doc, dict) and (r := parse_report(doc, p.name, airports, ai_records)):
            out.append(r)
    return sorted(out, key=lambda r: r.generated)


@dataclass
class Wn3Run:
    run: datetime
    airports: dict[str, list[Slot]]


def load_wn3(d: Path, airports: Iterable[str]) -> list[Wn3Run]:
    """`wn3/<起報>.json`（WN3 report-only 的事件檔）→ 每格的估算陣風。"""
    want = set(airports)
    out = []
    for p in sorted((d / "wn3").glob("*.json")):
        doc = _read_json(p)
        run = parse_time(doc.get("run")) if isinstance(doc, dict) else None
        if run is None:
            continue
        aps: dict[str, list[Slot]] = {}
        for icao, slots in (doc.get("airports") or {}).items():
            if icao not in want or not isinstance(slots, list):
                continue
            rows = []
            for s in slots:
                start, end = parse_time(s.get("from")), parse_time(s.get("to"))
                g = _num(s.get("gustKt"))
                if start is not None and end is not None:
                    gusts = [ModelGust("wn3", g, True)] if g is not None else []
                    rows.append(Slot(start, end, None, gusts))
            aps[icao] = rows
        out.append(Wn3Run(run, aps))
    return out


# ---- (a) 陣風 ----


@dataclass
class GustCell:
    pairs: list[tuple[float, float]] = field(default_factory=list)  # （預測, 實測）

    def summary(self) -> dict:
        n = len(self.pairs)
        out: dict = {
            "n": n,
            "mae": round(mean(abs(p - o) for p, o in self.pairs), 2) if n else None,
            "bias": round(mean(p - o for p, o in self.pairs), 2) if n else None,
        }
        for th in GUST_THRESHOLDS:
            hit = sum(p >= th and o >= th for p, o in self.pairs)
            miss = sum(p < th <= o for p, o in self.pairs)
            false = sum(o < th <= p for p, o in self.pairs)
            out[f"ge{th}"] = {
                "hit": hit,
                "miss": miss,
                "false": false,
                "pod": round(hit / (hit + miss), 3) if hit + miss else None,
            }
        return out


@dataclass
class GustResult:
    all: dict[str, list[GustCell]]
    windy: dict[str, list[GustCell]]
    estimated: set[str]
    no_metar: int = 0  # 格內沒有觀測，跳過的（機場 × 格，每報各算）


def _gust_slots(slots: list[Slot], ref: datetime, obs: list[Obs], res: GustResult) -> None:
    for s in slots:
        if s.end <= ref:
            continue
        b = bucket(lead_hours(s.start, ref))
        if b is None or not s.gusts:
            continue
        o = slot_obs(obs, s.start, s.end)
        if o is None:
            res.no_metar += 1
            continue
        value, wind = o
        for g in s.gusts:
            if g.estimated:
                res.estimated.add(g.model)
            res.all.setdefault(g.model, [GustCell() for _ in BUCKETS])[b].pairs.append(
                (g.gust, value)
            )
            if wind >= MIN_WIND_KT:
                res.windy.setdefault(g.model, [GustCell() for _ in BUCKETS])[b].pairs.append(
                    (g.gust, value)
                )


def gust_stats(
    reports: list[Report], wn3: list[Wn3Run], metars: dict[str, list[Obs]]
) -> GustResult:
    res = GustResult({}, {}, set())
    for r in reports:
        for a in r.airports.values():
            _gust_slots(a.slots, r.generated, metars.get(a.icao, []), res)
    for w in wn3:
        for icao, slots in w.airports.items():
            _gust_slots(slots, w.run, metars.get(icao, []), res)
    return res


# ---- (b) 等級 ----


@dataclass
class Confusion:
    tp: int = 0
    fp: int = 0
    fn: int = 0
    tn: int = 0

    def add(self, predicted: bool, actual: bool) -> None:
        if predicted and actual:
            self.tp += 1
        elif predicted:
            self.fp += 1
        elif actual:
            self.fn += 1
        else:
            self.tn += 1

    @property
    def precision(self) -> float | None:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else None

    @property
    def recall(self) -> float | None:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else None

    def summary(self) -> dict:
        p, r = self.precision, self.recall
        return {
            "tp": self.tp,
            "fp": self.fp,
            "fn": self.fn,
            "tn": self.tn,
            "precision": None if p is None else round(p, 3),
            "recall": None if r is None else round(r, 3),
        }


def _confusions() -> dict[str, list[Confusion]]:
    return {"risky": [Confusion() for _ in BUCKETS], "high": [Confusion() for _ in BUCKETS]}


@dataclass
class WindowStats:
    """每報每機場：整體一個 Confusion，另依第一個停飛格的提前段記召回（只有 TP／FN）。"""

    risky: Confusion = field(default_factory=Confusion)
    high: Confusion = field(default_factory=Confusion)
    recall_risky: list[Confusion] = field(default_factory=lambda: [Confusion() for _ in BUCKETS])
    recall_high: list[Confusion] = field(default_factory=lambda: [Confusion() for _ in BUCKETS])

    def add(self, level: str, actual: bool, first: int | None) -> None:
        self.risky.add(level in RISKY, actual)
        self.high.add(level in HIGH, actual)
        if actual and first is not None:
            self.recall_risky[first].add(level in RISKY, True)
            self.recall_high[first].add(level in HIGH, True)

    def summary(self) -> dict:
        return {
            "risky": self.risky.summary(),
            "high": self.high.summary(),
            "recallByFirstStop": {
                "risky": [c.recall for c in self.recall_risky],
                "high": [c.recall for c in self.recall_high],
            },
        }


@dataclass
class LevelResult:
    airports: list[str]
    slot: dict[str, dict[str, list[Confusion]]]  # 版本 → risky／high → 每段
    window: dict[str, WindowStats]  # 「規則燈（定版前）」等 → 統計
    counts: Counter[str] = field(default_factory=Counter)


def rule_key(version: str) -> str:
    return f"rule:{version}"


def level_stats(
    reports: list[Report],
    canc: Cancellations,
    airports: Iterable[str],
    cutoff: datetime,
    rate: float,
    count: int,
) -> LevelResult:
    scope = sorted(set(airports) & canc.airports)
    res = LevelResult(
        scope,
        {BEFORE: _confusions(), AFTER: _confusions()},
        {k: WindowStats() for k in (rule_key(BEFORE), rule_key(AFTER), *AI_KEYS)},
    )
    for r in reports:
        ver = version_of(r.generated, cutoff)
        for icao in scope:
            a = r.airports.get(icao)
            if a is None:
                continue
            window: list[tuple[int, bool | None]] = []
            best: str | None = None
            last_end: datetime | None = None
            for s in a.slots:
                if s.end <= r.generated:
                    continue
                b = bucket(lead_hours(s.start, r.generated))
                if b is None:
                    continue
                actual = canc.stopped(icao, s.start, s.end, rate, count)
                window.append((b, actual))
                last_end = s.end
                if s.level is not None and (
                    best is None or LEVELS.index(s.level) > LEVELS.index(best)
                ):
                    best = s.level
                if actual is None:
                    res.counts["slotNoTruth"] += 1
                    continue
                if s.level is None:
                    res.counts["slotNoLevel"] += 1
                    continue
                res.slot[ver]["risky"][b].add(s.level in RISKY, actual)
                res.slot[ver]["high"][b].add(s.level in HIGH, actual)
            if last_end is None or canc.as_of is None or last_end > canc.as_of:
                res.counts["windowOpen"] += 1
                continue
            actual_any = any(x for _, x in window)
            first = next((b for b, x in window if x), None)
            if best is not None:
                res.window[rule_key(ver)].add(best, actual_any, first)
            for k in AI_KEYS:
                if a.ai[k] is not None:
                    res.window[k].add(a.ai[k], actual_any, first)
                else:
                    res.counts[f"{k}NotOk"] += 1
    return res


# ---- (c) 路徑 ----


@dataclass
class ModelTrack:
    model: str
    run: datetime
    points: list[tuple[datetime, float, float]]  # HRES／找中心的點，系集是中位數位置
    members: list[list[tuple[datetime, float, float]]]  # 系集成員（其他模式空的）
    steps: int
    stop: str | None


def _pts(rows: object) -> list[tuple[datetime, float, float]]:
    out = []
    for p in rows if isinstance(rows, list) else []:
        t = parse_time(p.get("validAt")) if isinstance(p, dict) else None
        lat, lon = (_num(p.get("lat")), _num(p.get("lon"))) if isinstance(p, dict) else (None, None)
        if t is not None and lat is not None and lon is not None:
            out.append((t, lat, lon))
    return out


def parse_track(doc: dict, model: str, run: datetime) -> ModelTrack:
    """`tracks/` 的一份 → 主路徑與成員。ECMWF 路徑產品（有 `members`）：HRES 用 `member: 0`、
    系集用 `mean`；找中心的用 `points`。"""
    if "members" in doc:
        members = [m for m in doc.get("members") or [] if isinstance(m, dict)]
        hres = [m for m in members if m.get("member") == 0]
        if hres:
            pts = _pts(hres[0].get("points"))
            return ModelTrack(model, run, pts, [], len(pts), None if doc.get("storm") else "none")
        pts = _pts(doc.get("mean"))
        ens = [_pts(m.get("points")) for m in members]
        stop = None if doc.get("storm") else "none"
        return ModelTrack(model, run, pts, ens, len(pts), stop)
    pts = _pts(doc.get("points"))
    return ModelTrack(model, run, pts, [], len(pts), doc.get("stop"))


def load_tracks(d: Path) -> list[ModelTrack]:
    out = []
    for p in sorted((d / "tracks").glob("*.json")):
        m = _TRACK_FILE.match(p.name)
        doc = _read_json(p)
        if not m or not isinstance(doc, dict):
            continue
        run = parse_time(doc.get("run")) or datetime.strptime(m.group(1), _STAMP).replace(
            tzinfo=UTC
        )
        out.append(parse_track(doc, str(doc.get("model") or m.group(2)), run))
    return out


@dataclass
class TrackCell:
    errors: list[float] = field(default_factory=list)

    def summary(self) -> dict:
        n = len(self.errors)
        return {
            "n": n,
            "mean": round(mean(self.errors), 1) if n else None,
            "median": round(median(self.errors), 1) if n else None,
        }


@dataclass
class TrackResult:
    label: str
    provisional: bool
    models: dict[str, list[TrackCell]]
    members: dict[str, list[TrackCell]]  # 系集：成員對真相的誤差
    spread: dict[str, list[TrackCell]]  # 系集：成員到中位數的距離
    no_truth: int = 0
    used: dict[str, int] = field(default_factory=dict)


def _cells() -> list[TrackCell]:
    return [TrackCell() for _ in BUCKETS]


def track_stats(tracks: list[ModelTrack], truth: Truth) -> TrackResult:
    res = TrackResult(truth.label, truth.provisional, {}, {}, {})
    for tr in tracks:
        cells = res.models.setdefault(tr.model, _cells())
        for t, lat, lon in tr.points:
            lead = lead_hours(t, tr.run)
            b = bucket(lead) if lead >= 0 else None
            if b is None:
                continue
            p = truth.at(t)
            if p is None:
                res.no_truth += 1
                continue
            cells[b].errors.append(distance_km(lat, lon, *p))
        if not tr.members:
            continue
        center = {t: (lat, lon) for t, lat, lon in tr.points}
        errs = res.members.setdefault(tr.model, _cells())
        spread = res.spread.setdefault(tr.model, _cells())
        for m in tr.members:
            for t, lat, lon in m:
                lead = lead_hours(t, tr.run)
                b = bucket(lead) if lead >= 0 else None
                if b is None:
                    continue
                if t in center:
                    spread[b].errors.append(distance_km(lat, lon, *center[t]))
                p = truth.at(t)
                if p is not None:
                    errs[b].errors.append(distance_km(lat, lon, *p))
    res.used = dict(truth.used)
    return res


def truths(
    d: Path, event: Event, jtwc: Path | None, jma: Path | None, jma_id: str | None
) -> list[Truth]:
    out = []
    if jtwc is not None:
        pts = parse_atcf(jtwc.read_text(encoding="utf-8", errors="replace"))
        out.append(Truth(f"JTWC 最佳路徑（{jtwc.name}）", [Track("jtwc-best", pts)]))
    if jma is not None:
        storms = parse_jma_bst(jma.read_text(encoding="utf-8", errors="replace"))
        s = pick_bst(storms, jma_id, storm_name(event))
        out.append(
            Truth(f"JMA 最佳路徑（{jma.name}，{s.number} {s.name}）", [Track("jma-best", s.points)])
        )
    if not out:
        out.append(
            Truth("暫時真相：現報（JTWC 優先、再 JMA）", provisional_tracks(d), provisional=True)
        )
    return out


# ---- 資料完整度 ----


def metar_hours(
    metars: dict[str, list[Obs]], airports: Iterable[str]
) -> tuple[int, dict[str, int]]:
    """（METAR 期間的總小時數, 每站有觀測的小時數）。"""
    hours = {
        icao: {o.at.replace(minute=0, second=0) for o in metars.get(icao, [])} for icao in airports
    }
    every = set().union(*hours.values()) if hours else set()
    span = int(lead_hours(max(every), min(every))) + 1 if every else 0
    return span, {icao: len(h) for icao, h in hours.items()}


def models_present(r: Report) -> list[str]:
    return [m for m in EXPECTED_MODELS if m in r.model_runs]


# ---- 輸出 ----


def _f(v: float | None, digits: int = 1) -> str:
    return "-" if v is None else f"{v:.{digits}f}"


def md_table(headers: list[str], rows: list[list[str]]) -> list[str]:
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return out


def _ordered(keys: Iterable[str], order: tuple[str, ...]) -> list[str]:
    keys = set(keys)
    return [k for k in order if k in keys] + sorted(keys - set(order))


def _tw(t: datetime) -> str:
    return f"{t.astimezone(TAIPEI):%m/%d %H:%M}"


def _short_run(run: str) -> str:
    t = parse_time(run)
    return f"{t:%d/%H}Z" if t else "?"


@dataclass
class Result:
    event: Event
    reports: list[Report]
    cutoff: datetime
    rate: float
    count: int
    gust: GustResult
    levels: LevelResult
    tracks: list[TrackResult]
    track_runs: list[ModelTrack]
    metar_span: int
    metar_hours: dict[str, int]
    cancel_as_of: datetime | None


def render(res: Result) -> str:
    e, reps = res.event, res.reports
    L: list[str] = [f"# 颱風 {e.id} {e.name} 驗證報告", ""]
    L += summary_lines(res)
    L += ["", "## (a) 陣風：預測 − METAR 實測（節）", ""]
    L += [
        "每格 `平均絕對誤差／偏差（n）`，偏差＝預測 − 實測；實測＝格內 METAR 最大（有陣風用陣風、"
        "沒有用平均風）。標 * 的是估算陣風（平均風 × 係數）；系集沒有陣風不列。",
        "",
    ]
    for title, data in (
        (f"格內最大平均風 ≥ {MIN_WIND_KT} 節", res.gust.windy),
        ("全部的格", res.gust.all),
    ):
        L += [f"### {title}", ""]
        rows = []
        for m in _ordered(data, MODEL_ORDER):
            star = "*" if m in res.gust.estimated else ""
            cells = [c.summary() for c in data[m]]
            rows.append(
                [f"{m}{star}"]
                + [f"{_f(c['mae'])}／{_f(c['bias'])}（{c['n']}）" if c["n"] else "-" for c in cells]
            )
        L += (
            md_table(["模式", *[f"{b} h" for b in BUCKET_LABELS]], rows)
            if rows
            else ["（沒有資料）"]
        )
        L.append("")
    L += [
        "### 門檻命中（全部的格）",
        "",
        "每格 `≥37：命中/實測過門檻（誤報）、≥48：…`；命中＝預測與實測都過門檻。",
        "",
    ]
    rows = []
    for m in _ordered(res.gust.all, MODEL_ORDER):
        cells = []
        for c in res.gust.all[m]:
            s = c.summary()
            parts = [
                f"≥{th}：{s[f'ge{th}']['hit']}/{s[f'ge{th}']['hit'] + s[f'ge{th}']['miss']}"
                f"（{s[f'ge{th}']['false']}）"
                for th in GUST_THRESHOLDS
            ]
            cells.append("、".join(parts) if s["n"] else "-")
        rows.append([f"{m}{'*' if m in res.gust.estimated else ''}", *cells])
    L += md_table(["模式", *[f"{b} h" for b in BUCKET_LABELS]], rows) if rows else ["（沒有資料）"]
    L += ["", "## (b) 等級：判中或高 vs 實際停飛", ""]
    lv = res.levels
    L += [
        f"停飛定義：一格（UTC 6 小時，出發＋抵達）取消率 ≥ {res.rate:.0%} 或取消 ≥ {res.count} 班。"
        f"機場：{'、'.join(lv.airports) or '（沒有航班資料）'}。航班資料到 "
        f"{iso(res.cancel_as_of) or '-'}，之後結束的格還沒有結果。",
        "",
        "### 每格（規則燈）",
        "",
        "每格 `精確率／召回率（TP/FP/FN/TN）`。",
        "",
    ]
    rows = []
    for kind, name in (("risky", "判中或高"), ("high", "判高")):
        for ver in (BEFORE, AFTER):
            cs = lv.slot[ver][kind]
            rows.append(
                [f"規則燈（{ver}）{name}"]
                + [
                    f"{_f(c.precision, 2)}／{_f(c.recall, 2)}（{c.tp}/{c.fp}/{c.fn}/{c.tn}）"
                    if c.tp + c.fp + c.fn + c.tn
                    else "-"
                    for c in cs
                ]
            )
    L += md_table(["系統", *[f"{b} h" for b in BUCKET_LABELS]], rows)
    L += [
        "",
        "### 每報每機場（0–120 小時內任一格停飛；AI 的燈是整個機場 5 天一個等級）",
        "",
        "規則燈取這報 0–120 小時的最高等級。提前段的欄是召回率，依窗裡第一個停飛格的提前時間分。",
        "",
    ]
    rows = []
    for kind, name in (("risky", "判中或高"), ("high", "判高")):
        for key in (rule_key(BEFORE), rule_key(AFTER), *AI_KEYS):
            w = lv.window[key]
            c = w.risky if kind == "risky" else w.high
            by = w.recall_risky if kind == "risky" else w.recall_high
            label = AI_NAMES.get(key) or f"規則燈（{key.split(':')[1]}）"
            rows.append(
                [
                    f"{label}{name}",
                    str(c.tp),
                    str(c.fp),
                    str(c.fn),
                    str(c.tn),
                    _f(c.precision, 2),
                    _f(c.recall, 2),
                    *[_f(x.recall, 2) for x in by],
                ]
            )
    L += md_table(
        ["系統", "TP", "FP", "FN", "TN", "精確率", "召回率", *[f"{b} h" for b in BUCKET_LABELS]],
        rows,
    )
    L += ["", "## (c) 路徑：距離誤差（公里）", ""]
    L += ["每格 `平均／中位數（n）`；提前時間＝`validAt` − 起報。系集是中位數位置。", ""]
    for tr in res.tracks:
        L += [f"### 對 {tr.label}", ""]
        rows = []
        for m in _ordered(tr.models, TRACK_ORDER):
            name = f"{m}（中位數）" if m in tr.members else m
            cells = [c.summary() for c in tr.models[m]]
            rows.append(
                [name]
                + [
                    f"{_f(c['mean'], 0)}／{_f(c['median'], 0)}（{c['n']}）" if c["n"] else "-"
                    for c in cells
                ]
            )
        L += (
            md_table(["模式", *[f"{b} h" for b in BUCKET_LABELS]], rows)
            if rows
            else ["（沒有路徑）"]
        )
        if tr.members:
            L += ["", "系集成員：每格 `成員誤差平均／成員到中位數平均（成員點數）`。", ""]
            rows = []
            for m in _ordered(tr.members, TRACK_ORDER):
                cells = []
                for c, s in zip(tr.members[m], tr.spread[m], strict=True):
                    cs, ss = c.summary(), s.summary()
                    cells.append(
                        f"{_f(cs['mean'], 0)}／{_f(ss['mean'], 0)}（{cs['n']}）"
                        if cs["n"] or ss["n"]
                        else "-"
                    )
                rows.append([m, *cells])
            L += md_table(["系集", *[f"{b} h" for b in BUCKET_LABELS]], rows)
        used = "、".join(f"{k} {v}" for k, v in sorted(tr.used.items())) or "沒有"
        L += [
            "",
            f"真相內插的次數（依來源）：{used}；內插不到（範圍外或缺口 > {MAX_GAP_H} 小時）"
            f"{tr.no_truth} 點。",
            "",
        ]
    L += completeness_lines(res)
    L += ["", "## 附錄：每報", ""]
    rows = []
    for r in reps:
        present = models_present(r)
        runs = "、".join(
            f"{m} {_short_run(r.model_runs[m])}" for m in _ordered(r.model_runs, MODEL_ORDER)
        )
        rows.append(
            [
                iso(r.generated) or "",
                version_of(r.generated, res.cutoff),
                str(r.votes or "-"),
                f"{len(present)}/{len(EXPECTED_MODELS)}",
                runs or "-",
                f"{r.ai_ok['claude']}／{r.ai_ok['gemini']}",
            ]
        )
    L += md_table(
        ["generatedAt", "版本", "票數", "模式", "各模式起報", "AI 評了（Claude／Gemini）"], rows
    )
    return "\n".join(L) + "\n"


def summary_lines(res: Result) -> list[str]:
    e, reps = res.event, res.reports
    span = f"{iso(reps[0].generated)} – {iso(reps[-1].generated)}" if reps else "沒有快照"
    versions = Counter(version_of(r.generated, res.cutoff) for r in reps)
    truth = "；".join(t.label for t in res.tracks)
    return [
        "## 摘要",
        "",
        f"- 事件：{e.id} {e.name}，期間（台灣日期）{e.start}～{e.end}，{len(e.airports)} 個機場",
        f"- 快照：{len(reps)} 報（{span}）",
        f"- 版本切點：{iso(res.cutoff)}（台北 {_tw(res.cutoff)}）；定版前 {versions[BEFORE]} 報、"
        f"定版後 {versions[AFTER]} 報",
        f"- 路徑真相：{truth}",
        f"- 停飛定義：取消率 ≥ {res.rate:.0%} 或取消 ≥ {res.count} 班",
    ]


def completeness_lines(res: Result) -> list[str]:
    L = ["## 資料完整度", ""]
    by_day: dict[date, list[Report]] = defaultdict(list)
    for r in res.reports:
        by_day[r.generated.astimezone(TAIPEI).date()].append(r)
    rows = []
    for d, rs in sorted(by_day.items()):
        counts = [len(models_present(r)) for r in rs]
        rows.append([str(d), str(len(rs)), f"{min(counts)}–{max(counts)}", f"{mean(counts):.1f}"])
    L += ["### 每天幾報（台灣日期）、每報有資料的模式（共 8 個）", ""]
    L += md_table(["日期", "報數", "模式數範圍", "平均"], rows) if rows else ["（沒有快照）"]
    per_model = Counter(m for r in res.reports for m in models_present(r))
    L += ["", "各模式出現在幾報：" + "、".join(f"{m} {per_model[m]}" for m in EXPECTED_MODELS), ""]
    L += [f"### METAR 每站有觀測的小時數（METAR 期間共 {res.metar_span} 小時）", ""]
    items = sorted(res.metar_hours.items())
    L += ["、".join(f"{k} {v}" for k, v in items) or "（沒有 METAR）", ""]
    c = res.levels.counts
    L += [
        "### 跳過的",
        "",
        f"- (a) 格內沒有 METAR 觀測：{res.gust.no_metar} 格（機場 × 格，每報各算）",
        f"- (b) 每格：還沒結束或沒有航班 {c['slotNoTruth']} 格、"
        f"規則燈 unknown {c['slotNoLevel']} 格；"
        f"每報每機場：窗還沒結束 {c['windowOpen']} 筆；AI 不是 ok（skipped／error／沒有）："
        f"Claude {c['claudeNotOk']}、Gemini {c['geminiNotOk']} 筆",
        "",
        "### 路徑每報每模式追到幾步",
        "",
        "`步數`（停止原因；`none`＝路徑產品裡沒有這顆）。",
        "",
    ]
    by_run: dict[datetime, dict[str, ModelTrack]] = defaultdict(dict)
    for t in res.track_runs:
        by_run[t.run][t.model] = t
    models = _ordered({t.model for t in res.track_runs}, TRACK_ORDER)
    rows = []
    for run in sorted(by_run):
        cells = []
        for m in models:
            t = by_run[run].get(m)
            cells.append("-" if t is None else f"{t.steps}" + (f"（{t.stop}）" if t.stop else ""))
        rows.append([iso(run) or "", *cells])
    L += md_table(["起報", *models], rows) if rows else ["（沒有路徑檔）"]
    return L


def to_json(res: Result) -> dict:
    def gust(data: dict[str, list[GustCell]]) -> dict:
        return {m: [c.summary() for c in cells] for m, cells in data.items()}

    lv = res.levels
    return {
        "event": {"id": res.event.id, "name": res.event.name, "airports": list(res.event.airports)},
        "buckets": list(BUCKET_LABELS),
        "cutoff": iso(res.cutoff),
        "stopDefinition": {"rate": res.rate, "count": res.count},
        "gust": {
            "estimated": sorted(res.gust.estimated),
            "all": gust(res.gust.all),
            f"windGe{MIN_WIND_KT}": gust(res.gust.windy),
            "noMetar": res.gust.no_metar,
        },
        "levels": {
            "airports": lv.airports,
            "cancellationsAsOf": iso(res.cancel_as_of),
            "slot": {
                ver: {k: [c.summary() for c in cs] for k, cs in v.items()}
                for ver, v in lv.slot.items()
            },
            "window": {k: w.summary() for k, w in lv.window.items()},
            "skipped": dict(lv.counts),
        },
        "tracks": [
            {
                "truth": t.label,
                "provisional": t.provisional,
                "models": {m: [c.summary() for c in cs] for m, cs in t.models.items()},
                "members": {m: [c.summary() for c in cs] for m, cs in t.members.items()},
                "spread": {m: [c.summary() for c in cs] for m, cs in t.spread.items()},
                "noTruth": t.no_truth,
                "truthPointsUsed": t.used,
            }
            for t in res.tracks
        ],
        "trackRuns": [
            {"run": iso(t.run), "model": t.model, "steps": t.steps, "stop": t.stop}
            for t in sorted(res.track_runs, key=lambda t: (t.run, t.model))
        ],
        "metar": {"spanHours": res.metar_span, "hours": res.metar_hours},
        "reports": [
            {
                "generatedAt": iso(r.generated),
                "version": version_of(r.generated, res.cutoff),
                "votes": r.votes,
                "models": r.model_runs,
                "aiOk": r.ai_ok,
            }
            for r in res.reports
        ],
    }


def build_result(
    archive: Path,
    event: Event,
    cutoff: datetime,
    rate: float,
    count: int,
    jtwc: Path | None = None,
    jma: Path | None = None,
    jma_id: str | None = None,
) -> Result:
    history = archive / "history"
    d = history / "events" / event.id
    reports = load_reports(d, event.airports, history)
    metars = load_metars(d)
    canc = load_cancellations(history)
    track_runs = load_tracks(d)
    span, hours = metar_hours(metars, event.airports)
    return Result(
        event=event,
        reports=reports,
        cutoff=cutoff,
        rate=rate,
        count=count,
        gust=gust_stats(reports, load_wn3(d, event.airports), metars),
        levels=level_stats(reports, canc, event.airports, cutoff, rate, count),
        tracks=[track_stats(track_runs, t) for t in truths(d, event, jtwc, jma, jma_id)],
        track_runs=track_runs,
        metar_span=span,
        metar_hours=hours,
        cancel_as_of=canc.as_of,
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m tools.report_29w", description=__doc__.splitlines()[0]
    )
    ap.add_argument("--archive", type=Path, default=Path("data"), help="data 分支的 checkout")
    ap.add_argument("--event", default="29W")
    ap.add_argument("--events", type=Path, default=ROOT / "events.json")
    ap.add_argument("--jtwc", type=Path, help="JTWC 最佳路徑（ATCF b-deck，bwp292026.dat）")
    ap.add_argument("--jma", type=Path, help="JMA 最佳路徑（bst_all.txt 或單一颱風的檔）")
    ap.add_argument("--jma-id", help="JMA 國際編號（例如 2630）；不給就比颱風名稱")
    ap.add_argument("--cutoff", default=DEFAULT_CUTOFF, help="定版時間（UTC）")
    ap.add_argument("--cancel-rate", type=float, default=0.3)
    ap.add_argument("--cancel-count", type=int, default=10)
    ap.add_argument("--out", type=Path, help="Markdown 報告；不給就印在標準輸出")
    ap.add_argument("--json", type=Path, help="JSON（給之後畫圖）")
    args = ap.parse_args(argv)
    t0 = time.monotonic()
    event = next((e for e in load_events(args.events) if e.id == args.event), None)
    if event is None:
        print(f"{args.events} 沒有事件 {args.event}", file=sys.stderr)
        return 1
    cutoff = parse_time(args.cutoff)
    if cutoff is None:
        print(f"看不懂的 --cutoff {args.cutoff}", file=sys.stderr)
        return 1
    try:
        res = build_result(
            args.archive,
            event,
            cutoff,
            args.cancel_rate,
            args.cancel_count,
            args.jtwc,
            args.jma,
            args.jma_id,
        )
    except ValueError as ex:
        print(ex, file=sys.stderr)
        return 1
    md = render(res)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(md, encoding="utf-8")
        print("\n".join(summary_lines(res)))
        print(f"\nMarkdown：{args.out}")
    else:
        print(md)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        body = json.dumps(to_json(res), ensure_ascii=False, indent=1)
        args.json.write_text(body + "\n", encoding="utf-8")
        print(f"JSON：{args.json}")
    print(f"（{time.monotonic() - t0:.1f} 秒）", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
