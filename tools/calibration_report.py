"""回測校準報告（HD46）：燈號等級（低／中／高／已確認）對實際取消、延誤。

在 repo 根目錄跑（`data` 是 `data` 分支的 checkout，底下有 `history/`）：

    python -m tools.calibration_report --archive data --from 2026-10-18 --to 2026-11-10 \\
      [--min-flights 10] [--out report/calibration-2026-11.md] \\
      [--json report/calibration-2026-11.json]

純讀，只用標準函式庫；不改任何檔案（除了 `--out`／`--json`），**不改 `assess.py`、門檻、
每報的輸出**，也**不讀私人 bucket**（WN3 只看快照裡本來就有的 `model.level`）。標準輸出印摘要；
沒給 `--out` 時整份 Markdown 印在標準輸出。讀檔、停飛實測的寫法借 `tools/report_29w.py`
（import 進來用，不改它）。

讀什麼：

- 預報：`history/<YYYYMMDDTHHMM>Z.json`（每報的 `latest.json` 快照），`generatedAt` 落在
  `--from` 那天 00:00Z 到 `--to` 那天 24:00Z（UTC 日期，兩端都含；也可以給帶時區的時間）
- 實測：`history/cancellations/<日期>.json`（H6，桃園、松山、高雄、香港、澳門）；這五個以外的
  機場用 `history/events/<id>/flights/*.jsonl` 的 TDX 逐班紀錄（HD32，只有事件期間有），同 29W
  報告（HD37）：同一班取 `t` 最新那行、狀態照 `report_29w.reclassify` 重新分類、依表定時間歸格
- 期間分類：`events.json`（台灣日期，含兩端）

做法：

- 提前時間＝格的 `from` − `generatedAt`，分五段 0–24、24–48、48–72、72–96、96–120 小時
  （同 HD22：左閉右開，120 歸最後一段；這一報所在的那格算 0–24；已經結束的格不算）
- **去重**：同一個（機場、格、提前時間段）被很多報預報過，只取提前時間最靠近那段中間
  （12、36、60、84、108 小時）的那一報；一樣近取比較新的那報。所以同一格在每一段最多算一次、
  全部最多五次
- 一格的實測：那格（UTC 6 小時，依表定時間）出發＋抵達合計的 `total`、`cancelled`、`delayed`
  （狀態延誤或晚 60 分鐘以上，取消的不重複算）。格的 `to` 晚於那個機場資料最新的時間
  （`cancellations/` 是那個機場最大的 `asOf`、逐班是整批最新的 `t`）時還沒有結果，不算；
  沒有那格的列（沒有航班）不算
- 表定（出發＋抵達）少於 `--min-flights`（預設 10）班的格：主要的表全部排除，盤點另列格數；
  另算一份門檻 4 班（`cancellations.FEW_FLIGHTS`）的對照
- 事件（六種並列）：取消率 ≥ 10%／25%／50%；（取消＋延誤）÷ 表定 ≥ 10%／25%／50%
- 等級：快照每格的 `level`（`confirmed` 是「已確認」；`unknown` 不算）。官方層＝
  `official.level`（沒有官方層是 null，不算）、模式投票層＝`model.level`；原因＝`causes`
  （含這個原因就算，一格多個原因每個都算一次）
- AI 燈：每報每機場一個等級（`airports[].ai.<claude|gemini>`，快照沒有 `ai` 時用
  `history/ai/<日期>.json` 同一報同機場那筆），和「這報 0–120 小時任一格有事件」比；規則燈取
  同一報 20 格的最高等級一起比。每個機場每個 UTC 日只取當天第一報（窗仍然互相重疊）；窗裡
  最後一格還沒有結果的不算
- 區間：Wilson 95%（z＝1.96）。同一格在不同提前時間段會各算一次、相鄰的格與機場也不獨立，
  所以區間偏窄
- 「說了高」＝`high`／`confirmed`；「說中以上」＝`medium`／`high`／`confirmed`。
  命中＝說了而且有事件，誤報＝說了沒事件，漏報＝沒說但有事件
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from math import sqrt
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT / "src", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from hongthai.config import load_events  # noqa: E402
from hongthai.timeutil import iso, parse_time  # noqa: E402
from tools import report_29w as r29  # noqa: E402

TAIPEI = ZoneInfo("Asia/Taipei")
BUCKETS = r29.BUCKETS
BUCKET_LABELS = tuple(f"{a}–{b} h" for a, b in BUCKETS)
CENTERS = tuple((a + b) / 2 for a, b in BUCKETS)
SLOT = timedelta(hours=6)
LEVELS = ("low", "medium", "high", "confirmed")
LEVEL_NAMES = {"low": "低", "medium": "中", "high": "高", "confirmed": "已確認"}
LEVEL_ORDER = {"unknown": 0, "low": 1, "medium": 2, "high": 3, "confirmed": 4}
RISKY = ("medium", "high", "confirmed")
HIGH = ("high", "confirmed")
POSITIVE = {"risky": RISKY, "high": HIGH}
POSITIVE_NAMES = {"risky": "說中以上", "high": "說高"}
CAUSES = ("wind", "rain", "snow", "fog")
CAUSE_NAMES = {"wind": "風", "rain": "雨", "snow": "雪", "fog": "霧"}
AI_KEYS = r29.AI_KEYS
AI_NAMES = r29.AI_NAMES
DEFAULT_MIN_FLIGHTS = 10
FEW_FLIGHTS = r29.FEW_FLIGHTS  # 4：對照用
MIN_AIRPORT_SLOTS = 20  # 分機場：有效格（不重複）至少這麼多才單獨一列
Z = 1.96
_STAMP = re.compile(r"^(\d{8}T\d{4}Z)\.json$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
NON_TYPHOON = "非颱風期間"
SOURCE_LONG = {
    "cancellations": "取消統計（H6，`history/cancellations/`）",
    "tdx": "TDX 逐班紀錄（HD32，只有事件期間）",
}


@dataclass(frozen=True)
class EventDef:
    key: str
    label: str
    with_delay: bool
    rate: float


EVENTS = (
    EventDef("c10", "取消率 ≥ 10%", False, 0.10),
    EventDef("c25", "取消率 ≥ 25%", False, 0.25),
    EventDef("c50", "取消率 ≥ 50%", False, 0.50),
    EventDef("cd10", "取消＋延誤 ≥ 10%", True, 0.10),
    EventDef("cd25", "取消＋延誤 ≥ 25%", True, 0.25),
    EventDef("cd50", "取消＋延誤 ≥ 50%", True, 0.50),
)
EVENT_BY_KEY = {e.key: e for e in EVENTS}
# 分原因、分層、AI、分機場的表只放這四欄（JSON 六種都有）
COMPACT = ("c10", "c25", "c50", "cd25")
FLAG_EVENTS = ("c10", "c25", "cd25")  # 分機場「偏高／偏低」看這三種
SHORT = {"c10": "取消10", "c25": "取消25", "c50": "取消50", "cd10": "取延10", "cd25": "取延25"}
SHORT["cd50"] = "取延50"


# ---- 小工具 ----


def wilson(k: int, n: int) -> tuple[float, float] | None:
    """二項比例的 Wilson 95% 區間；n＝0 回 None。"""
    if n <= 0:
        return None
    p = k / n
    denom = 1 + Z * Z / n
    center = (p + Z * Z / (2 * n)) / denom
    half = Z * sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / denom
    return max(0.0, center - half), min(1.0, center + half)


def bucket_of(lead: float) -> int | None:
    return r29.bucket(lead)


def parse_day(s: str, end: bool) -> datetime:
    """`--from`／`--to`：`YYYY-MM-DD` 是 UTC 日期（`--to` 含那一整天）；其他照 `parse_cli_time`。"""
    s = s.strip()
    if _DATE.match(s):
        t = datetime.fromisoformat(s).replace(tzinfo=UTC)
        return t + timedelta(days=1) if end else t
    return r29.parse_cli_time(s)


def max_level(levels: Iterable[str]) -> str:
    return max(levels, key=lambda lv: LEVEL_ORDER.get(lv, 0), default="unknown")


def _pct(v: float | None, digits: int = 0) -> str:
    return "-" if v is None else f"{v * 100:.{digits}f}%"


def _tw(t: datetime | None) -> str:
    return "-" if t is None else t.astimezone(TAIPEI).strftime("%m/%d %H:%M")


# ---- 統計格 ----


@dataclass
class Cell:
    n: int = 0
    k: int = 0

    def add(self, hit: bool) -> None:
        self.n += 1
        self.k += int(hit)

    @property
    def rate(self) -> float | None:
        return self.k / self.n if self.n else None

    @property
    def ci(self) -> tuple[float, float] | None:
        return wilson(self.k, self.n)

    def summary(self) -> dict:
        ci = self.ci
        return {
            "n": self.n,
            "k": self.k,
            "rate": None if self.rate is None else round(self.rate, 4),
            "lo": None if ci is None else round(ci[0], 4),
            "hi": None if ci is None else round(ci[1], 4),
        }

    def text(self, ci: bool = True) -> str:
        if not self.n:
            return "-"
        s = f"{_pct(self.rate)}（{self.k}/{self.n}）"
        if ci and (c := self.ci):
            s += f" [{c[0] * 100:.0f}–{c[1] * 100:.0f}]"
        return s


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
        ci = wilson(self.tp, self.tp + self.fp)
        return {
            "hits": self.tp,
            "falseAlarms": self.fp,
            "misses": self.fn,
            "correctNegatives": self.tn,
            "precision": None if p is None else round(p, 4),
            "precisionLo": None if ci is None else round(ci[0], 4),
            "precisionHi": None if ci is None else round(ci[1], 4),
            "recall": None if r is None else round(r, 4),
        }


# ---- 讀快照 ----


@dataclass(frozen=True)
class Forecast:
    airport: str
    start: datetime
    run: datetime
    lead: float
    bucket: int
    level: str
    official: str | None  # 官方層等級（沒有官方層 None）
    model: str | None  # 模式投票層等級
    causes: tuple[str, ...]


@dataclass
class AiWindow:
    """每報每機場：AI 兩燈（狀態, 等級）與規則燈（20 格最高）、這報 0–120 小時的格。"""

    airport: str
    run: datetime
    lights: dict[str, tuple[str | None, str | None]]
    rule: str
    starts: tuple[datetime, ...]


@dataclass
class Archive:
    runs: list[datetime] = field(default_factory=list)
    forecasts: list[Forecast] = field(default_factory=list)
    windows: list[AiWindow] = field(default_factory=list)
    airports: dict[str, str] = field(default_factory=dict)  # ICAO → IATA
    counts: Counter[str] = field(default_factory=Counter)
    # TDX 機場只有快照 `slots[].flights` 的格（逐班紀錄沒有）：機場 → 格（只在盤點列出，不算）
    snapshot_only: dict[str, set[datetime]] = field(default_factory=lambda: defaultdict(set))


def snapshot_files(history: Path, start: datetime, end: datetime) -> list[tuple[datetime, Path]]:
    """`history/<YYYYMMDDTHHMM>Z.json` 裡檔名時間落在 [start, end) 的（依時間排序）。"""
    out = []
    for p in history.glob("*.json"):
        m = _STAMP.match(p.name)
        if not m:
            continue
        t = datetime.strptime(m.group(1), "%Y%m%dT%H%MZ").replace(tzinfo=UTC)
        if start <= t < end:
            out.append((t, p))
    return sorted(out)


def _layer(obj: object) -> str | None:
    if isinstance(obj, dict) and obj.get("level") in LEVEL_ORDER:
        return str(obj["level"])
    return None


def _light(obj: object) -> tuple[str | None, str | None]:
    if not isinstance(obj, dict):
        return None, None
    status = obj.get("status") if isinstance(obj.get("status"), str) else None
    lv = obj.get("level") if obj.get("level") in ("low", "medium", "high") else None
    return status, lv


def load_archive(history: Path, start: datetime, end: datetime) -> Archive:
    arc = Archive()
    ai_records: dict[tuple[str, str], dict] | None = None
    for stamp, path in snapshot_files(history, start, end):
        doc = r29._read_json(path)
        if not isinstance(doc, dict):
            arc.counts["badSnapshot"] += 1
            continue
        run = parse_time(doc.get("generatedAt")) or stamp
        if not start <= run < end:
            continue
        arc.runs.append(run)
        for a in doc.get("airports") or []:
            if not isinstance(a, dict) or not isinstance(a.get("icao"), str):
                continue
            icao = a["icao"]
            arc.airports.setdefault(icao, str(a.get("iata") or icao))
            levels, starts = [], []
            for s in a.get("slots") or []:
                f, t = parse_time(s.get("from")), parse_time(s.get("to"))
                if f is None or t is None:
                    continue
                fl = s.get("flights")
                if isinstance(fl, dict) and fl.get("source") == r29.FLIGHT_SOURCE:
                    arc.snapshot_only[icao].add(f)
                if t <= run:
                    arc.counts["endedSlots"] += 1
                    continue
                lead = (f - run).total_seconds() / 3600
                b = bucket_of(lead)
                if b is None:
                    arc.counts["beyond120"] += 1
                    continue
                level = s.get("level")
                starts.append(f)
                if level not in LEVELS:
                    arc.counts["unknownLevel"] += 1
                    continue
                levels.append(level)
                if level == "confirmed":
                    arc.counts["confirmed"] += 1
                causes = tuple(c for c in s.get("causes") or [] if c in CAUSES)
                model = s.get("model")
                arc.forecasts.append(
                    Forecast(
                        icao,
                        f,
                        run,
                        lead,
                        b,
                        level,
                        _layer(s.get("official")),
                        _layer(model),
                        causes,
                    )
                )
            ai = a.get("ai")
            if not isinstance(ai, dict):
                if ai_records is None:
                    ai_records = r29.load_ai_records(history)
                ai = ai_records.get((str(run), icao)) or {}
            arc.windows.append(
                AiWindow(
                    icao,
                    run,
                    {k: _light(ai.get(k)) for k in AI_KEYS},
                    max_level(levels),
                    tuple(starts),
                )
            )
    arc.runs.sort()
    return arc


def dedupe(forecasts: Iterable[Forecast]) -> list[Forecast]:
    """每個（機場、格、提前時間段）只留提前時間最靠近那段中間的一報；一樣近留比較新的。"""
    best: dict[tuple[str, datetime, int], Forecast] = {}
    for f in forecasts:
        key = (f.airport, f.start, f.bucket)
        cur = best.get(key)
        d = abs(f.lead - CENTERS[f.bucket])
        if cur is None:
            best[key] = f
            continue
        dc = abs(cur.lead - CENTERS[cur.bucket])
        if d < dc or (d == dc and f.run > cur.run):
            best[key] = f
    return sorted(best.values(), key=lambda f: (f.airport, f.start, f.bucket))


# ---- 實測 ----


@dataclass(frozen=True)
class SlotTruth:
    total: int
    cancelled: int
    delayed: int
    diverted: int
    source: str
    early: bool  # `cancellations/` 的列在格結束前算的（`asOf` < `to`），之後沒再更新

    def hit(self, ev: EventDef) -> bool:
        x = self.cancelled + (self.delayed if ev.with_delay else 0)
        return self.total > 0 and x / self.total >= ev.rate


@dataclass
class TruthSet:
    slots: dict[tuple[str, datetime], SlotTruth] = field(default_factory=dict)
    last: dict[str, datetime] = field(default_factory=dict)
    source: dict[str, str] = field(default_factory=dict)
    pending: Counter[str] = field(default_factory=Counter)  # 還沒有結果的格（機場 → 格數）

    def first(self, airport: str) -> datetime | None:
        return min((s for (a, s) in self.slots if a == airport), default=None)


def _part(row: dict, key: str) -> int:
    return sum(int((row.get(d) or {}).get(key) or 0) for d in ("dep", "arr"))


def load_truth(history: Path, tz: dict[str, str], airports: Iterable[str]) -> TruthSet:
    """`cancellations/` 的機場用它；其他機場用事件保存的 TDX 逐班紀錄（`report_29w` 的讀法）。"""
    raw = r29.load_cancellations(history)
    events_dir = history / "events"
    for d in sorted(events_dir.iterdir()) if events_dir.is_dir() else []:
        if (d / "flights").is_dir():
            r29.load_flights(d, raw, airports, tz)
    out = TruthSet()
    for icao, a in raw.by_airport.items():
        if a.last is None:
            continue
        out.last[icao] = a.last
        out.source[icao] = "tdx" if a.source == r29.FLIGHTS else "cancellations"
        for start, row in a.rows.items():
            total = _part(row, "total")
            if total <= 0:
                continue
            if start + SLOT > a.last:
                out.pending[icao] += 1
                continue
            as_of, end = parse_time(row.get("asOf")), parse_time(row.get("to"))
            early = as_of is not None and end is not None and as_of < end
            out.slots[(icao, start)] = SlotTruth(
                total,
                _part(row, "cancelled"),
                _part(row, "delayed"),
                _part(row, "diverted"),
                out.source[icao],
                early,
            )
    return out


# ---- 期間 ----


@dataclass(frozen=True)
class Period:
    id: str
    start: datetime
    end: datetime
    airports: frozenset[str]


def load_periods(path: Path) -> list[Period]:
    out = []
    for e in load_events(path):
        s = datetime(e.start.year, e.start.month, e.start.day, tzinfo=TAIPEI)
        n = e.end + timedelta(days=1)
        t = datetime(n.year, n.month, n.day, tzinfo=TAIPEI)
        out.append(Period(e.id, s.astimezone(UTC), t.astimezone(UTC), frozenset(e.airports)))
    return out


def period_of(periods: list[Period], airport: str, start: datetime) -> str:
    for p in periods:
        if airport in p.airports and p.start <= start < p.end:
            return p.id
    return NON_TYPHOON


# ---- 計算 ----


Pair = tuple[Forecast, SlotTruth]


def calibration(pairs: list[Pair], ev: EventDef) -> dict[str, list[Cell]]:
    """等級 → 每段（最後一個是全部）的 Cell。"""
    out = {lv: [Cell() for _ in range(len(BUCKETS) + 1)] for lv in LEVELS}
    for f, t in pairs:
        hit = t.hit(ev)
        out[f.level][f.bucket].add(hit)
        out[f.level][-1].add(hit)
    return out


def confusion(pairs: list[Pair], ev: EventDef, positive: tuple[str, ...]) -> list[Confusion]:
    out = [Confusion() for _ in range(len(BUCKETS) + 1)]
    for f, t in pairs:
        hit, said = t.hit(ev), f.level in positive
        out[f.bucket].add(said, hit)
        out[-1].add(said, hit)
    return out


def grouped(
    pairs: list[Pair], key: Callable[[Forecast], Iterable[str] | str | None]
) -> dict[str, dict[str, Cell]]:
    """分組（`key` 回一個或多個組名；None 不算）→ 事件 → Cell。"""
    out: dict[str, dict[str, Cell]] = defaultdict(lambda: {e.key: Cell() for e in EVENTS})
    for f, t in pairs:
        ks = key(f)
        if ks is None:
            continue
        for k in [ks] if isinstance(ks, str) else ks:
            for e in EVENTS:
                out[k][e.key].add(t.hit(e))
    return dict(out)


@dataclass
class AiResult:
    windows: int = 0
    skipped: Counter[str] = field(default_factory=Counter)
    rows: dict[str, dict[str, Cell]] = field(
        default_factory=dict
    )  # 「claude:ok:high」→ 事件 → Cell
    confusion: dict[str, dict[str, dict[str, Confusion]]] = field(default_factory=dict)


def ai_stats(windows: list[AiWindow], truth: TruthSet, min_flights: int) -> AiResult:
    res = AiResult()
    daily: dict[tuple[str, str], AiWindow] = {}
    for w in sorted(windows, key=lambda w: w.run):
        daily.setdefault((w.airport, w.run.date().isoformat()), w)
    rows: dict[str, dict[str, Cell]] = defaultdict(lambda: {e.key: Cell() for e in EVENTS})
    conf: dict[str, dict[str, dict[str, Confusion]]] = defaultdict(
        lambda: {e.key: {p: Confusion() for p in POSITIVE} for e in EVENTS}
    )
    for w in daily.values():
        last = truth.last.get(w.airport)
        if last is None or not w.starts:
            continue
        if max(w.starts) + SLOT > last:
            res.skipped["windowNotFinished"] += 1
            continue
        ts = [
            t
            for s in w.starts
            if (t := truth.slots.get((w.airport, s))) is not None and t.total >= min_flights
        ]
        if not ts:
            res.skipped["windowNoTruth"] += 1
            continue
        res.windows += 1
        hits = {e.key: any(t.hit(e) for t in ts) for e in EVENTS}
        said: dict[str, str] = {"rule": w.rule}
        for k in AI_KEYS:
            status, lv = w.lights.get(k, (None, None))
            if status == "ok" and lv:
                said[k] = lv
            elif status == "skipped" and lv:
                said[f"{k}:skipped"] = lv
            else:
                res.skipped[f"{k}:{status or 'none'}"] += 1
        for who, lv in said.items():
            for e in EVENTS:
                rows[f"{who}:{lv}"][e.key].add(hits[e.key])
                if ":" not in who:
                    for p, pos in POSITIVE.items():
                        conf[who][e.key][p].add(lv in pos, hits[e.key])
        # 兩個 AI 都有評（ok）的窗：規則燈與兩個 AI 在同一批窗上比
        if all(said.get(k) for k in AI_KEYS):
            for who in ("rule", *AI_KEYS):
                lv = said[who]
                for e in EVENTS:
                    if who == "rule":
                        rows[f"rule(ai-ok):{lv}"][e.key].add(hits[e.key])
                    for p, pos in POSITIVE.items():
                        conf[f"{who}(ai-ok)"][e.key][p].add(lv in pos, hits[e.key])
    res.rows = dict(rows)
    res.confusion = {k: dict(v) for k, v in conf.items()}
    return res


@dataclass
class AirportRow:
    icao: str
    iata: str
    source: str
    first: datetime | None
    last: datetime | None
    slots: int  # 有效格（不重複，≥ min_flights）
    few: int  # 班次少的格（不重複）
    early: int
    events: dict[str, int]  # 事件格（不重複）
    cells: dict[str, dict[str, Cell]]  # 事件 → 等級 → Cell（全部提前時間）
    flags: list[str]


def airport_rows(
    pairs: list[Pair],
    truth: TruthSet,
    names: dict[str, str],
    min_flights: int,
    pooled: dict[str, dict[str, Cell]],
) -> list[AirportRow]:
    by: dict[str, list[Pair]] = defaultdict(list)
    for f, t in pairs:
        by[f.airport].append((f, t))
    out = []
    for icao in sorted(truth.last):
        uniq = {s: t for (a, s), t in truth.slots.items() if a == icao}
        valid = {s: t for s, t in uniq.items() if t.total >= min_flights}
        cells: dict[str, dict[str, Cell]] = {e.key: {lv: Cell() for lv in LEVELS} for e in EVENTS}
        for f, t in by.get(icao, []):
            for e in EVENTS:
                cells[e.key][f.level].add(t.hit(e))
        flagged: dict[tuple[str, str], list[str]] = defaultdict(list)
        for lv in ("low", "medium", "high"):
            for ek in FLAG_EVENTS:
                c, ref = cells[ek][lv], pooled[ek][lv]
                ci, r = c.ci, ref.rate
                if c.n < 5 or ci is None or r is None:
                    continue
                if ci[0] > r:
                    flagged[(lv, "偏高")].append(SHORT[ek])
                elif ci[1] < r:
                    flagged[(lv, "偏低")].append(SHORT[ek])
        flags = [f"說{LEVEL_NAMES[lv]}{d}（{'、'.join(v)}）" for (lv, d), v in flagged.items()]
        out.append(
            AirportRow(
                icao,
                names.get(icao, icao),
                truth.source.get(icao, "?"),
                truth.first(icao),
                truth.last.get(icao),
                len(valid),
                len(uniq) - len(valid),
                sum(t.early for t in valid.values()),
                {e.key: sum(t.hit(e) for t in valid.values()) for e in EVENTS},
                cells,
                flags,
            )
        )
    return out


# ---- 結果 ----


@dataclass
class Result:
    args: dict
    data_commit: dict
    tool_commit: dict
    runs: list[datetime]
    archive_counts: Counter[str]
    airports_all: dict[str, str]
    truth: TruthSet
    snapshot_only: dict[str, int]  # TDX 機場：只有快照統計的格數（不算）
    min_flights: int
    forecasts: int
    deduped: int
    pairs: list[Pair]  # ≥ min_flights
    few_pairs: list[Pair]  # 班次少（另列）
    no_truth: int
    calib: dict[str, dict[str, list[Cell]]]
    calib_few4: dict[str, dict[str, list[Cell]]]  # 門檻 4 班的對照
    conf: dict[str, dict[str, list[Confusion]]]
    causes: dict[str, dict[str, Cell]]
    periods: dict[str, dict[str, Cell]]
    period_ids: list[str]
    layers: dict[str, dict[str, Cell]]
    ai: AiResult
    airports: list[AirportRow]
    misses: dict[str, list[Pair]]  # 事件 → 0–24 小時說低（沒到中）的事件格


def git_info(path: Path) -> dict:
    try:
        out = subprocess.run(
            ["git", "-C", str(path), "log", "-1", "--format=%H%x00%s%x00%cI"],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        ).stdout.strip()
        sha, subject, at = out.split("\x00")
        dirty = subprocess.run(
            ["git", "-C", str(path), "status", "--porcelain", "--untracked-files=no"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        ).stdout.strip()
        return {"commit": sha, "subject": subject, "committedAt": at, "dirty": bool(dirty)}
    except (OSError, subprocess.SubprocessError, ValueError):
        return {"commit": None, "subject": None, "committedAt": None, "dirty": None}


def compute(
    archive_dir: Path,
    start: datetime,
    end: datetime,
    min_flights: int = DEFAULT_MIN_FLIGHTS,
    airports_path: Path = ROOT / "airports.json",
    events_path: Path = ROOT / "events.json",
    args: dict | None = None,
    git: bool = True,
) -> Result:
    history = archive_dir / "history"
    arc = load_archive(history, start, end)
    tz = r29.airport_tz(airports_path)
    truth = load_truth(history, tz, set(arc.airports) | set(tz))
    periods = load_periods(events_path)
    deduped = dedupe(arc.forecasts)
    pairs, few_pairs, few4_pairs = [], [], []
    no_truth = 0
    for f in deduped:
        t = truth.slots.get((f.airport, f.start))
        if t is None:
            no_truth += 1
            continue
        if t.total >= FEW_FLIGHTS:
            few4_pairs.append((f, t))
        (pairs if t.total >= min_flights else few_pairs).append((f, t))
    calib = {e.key: calibration(pairs, e) for e in EVENTS}
    calib_few4 = {e.key: calibration(few4_pairs, e) for e in EVENTS}
    conf = {f"{e.key}:{p}": confusion(pairs, e, pos) for e in EVENTS for p, pos in POSITIVE.items()}
    causes = grouped(
        pairs,
        lambda f: [f"{c}:{f.level}" for c in f.causes] if f.level in RISKY else None,
    )
    periods_g = grouped(pairs, lambda f: f"{period_of(periods, f.airport, f.start)}:{f.level}")

    def layer_key(f: Forecast) -> list[str]:
        ks = []
        near = f.bucket <= 1
        if near and f.official is not None:
            ks += [f"official:{f.official}", f"model-same:{f.model}"]
        if f.model is not None:
            ks.append(f"model-{'near' if near else 'far'}:{f.model}")
        return ks

    layers = grouped(pairs, layer_key)
    pooled = {e.key: {lv: calib[e.key][lv][-1] for lv in LEVELS} for e in EVENTS}
    misses = {
        e.key: sorted(
            ((f, t) for f, t in pairs if f.bucket == 0 and t.hit(e) and f.level not in RISKY),
            key=lambda p: (p[0].start, p[0].airport),
        )
        for e in EVENTS
    }
    snapshot_only = {
        icao: sum(
            1
            for s in starts
            if (icao, s) not in truth.slots and s + SLOT <= (arc.runs[-1] if arc.runs else s)
        )
        for icao, starts in arc.snapshot_only.items()
    }
    snapshot_only = {k: v for k, v in sorted(snapshot_only.items()) if v}
    ai = ai_stats(arc.windows, truth, min_flights)
    res = Result(
        args=args or {},
        data_commit=git_info(archive_dir) if git else {},
        tool_commit=git_info(ROOT) if git else {},
        runs=arc.runs,
        archive_counts=arc.counts,
        airports_all=dict(sorted(arc.airports.items())),
        truth=truth,
        snapshot_only=snapshot_only,
        min_flights=min_flights,
        forecasts=len(arc.forecasts),
        deduped=len(deduped),
        pairs=pairs,
        few_pairs=few_pairs,
        no_truth=no_truth,
        calib=calib,
        calib_few4=calib_few4,
        conf=conf,
        causes=causes,
        periods=periods_g,
        period_ids=[p.id for p in periods],
        layers=layers,
        ai=ai,
        airports=airport_rows(pairs, truth, arc.airports, min_flights, pooled),
        misses=misses,
    )
    return res


# ---- Markdown ----


def md_table(headers: list[str], rows: list[list[str]]) -> list[str]:
    return r29.md_table(headers, rows)


def _cell(c: Cell | None, ci: bool = False) -> str:
    return "-" if c is None else c.text(ci)


def _unique_events(pairs: list[Pair], ev: EventDef) -> set[tuple[str, datetime]]:
    return {(f.airport, f.start) for f, t in pairs if t.hit(ev)}


def _unique_slots(pairs: list[Pair]) -> set[tuple[str, datetime]]:
    return {(f.airport, f.start) for f, _ in pairs}


def limit_lines(res: Result) -> list[str]:
    by_src: dict[str, list[str]] = defaultdict(list)
    for a, s in sorted(res.truth.source.items()):
        by_src[s].append(a)

    def span(icaos: list[str]) -> str:
        first = min((f for a in icaos if (f := res.truth.first(a)) is not None), default=None)
        last = max((res.truth.last[a] for a in icaos), default=None)
        return f"台北 {_tw(first)} – {_tw(last)}"

    early = sum(t.early for t in res.truth.slots.values() if t.total >= res.min_flights)
    days = (res.runs[-1] - res.runs[0]).total_seconds() / 86400 if res.runs else 0
    return [
        "## 限制（先讀這段）",
        "",
        f"- **期間只有 {days:.1f} 天、{len(res.runs)} 報**，而且只有一個颱風（"
        + "、".join(res.period_ids or ["無"])
        + "）。大量取消幾乎都集中在那幾天，非颱風期間的事件很少，下面的比例很多是個位數樣本",
        "- **取消不一定是天氣造成**：航班資料沒有取消原因，航空公司營運、機材調度、航權也會取消。"
        "取消率低門檻（10%）在平常日子也會碰到（見「分機場」）",
        "- **各機場航班資料的來源與起始日不同**："
        + "；".join(
            f"{SOURCE_LONG[s]} {len(v)} 個（{'、'.join(v)}，{span(v)}）" for s, v in by_src.items()
        )
        + "。HD38 起 TDX 七個機場每 6 小時的統計只進每報快照的 `slots[].flights`，"
        "而且只有那報所在的格、只到那報的時間（不完整），這裡不算，盤點另列",
        f"- **{early} 個有效格的取消統計是在格結束前算的**（`asOf` < `to`，之後來源不再列"
        "那些班、合併規則留了舊的列）：取消多半事前公告，影響不大；**延誤會少算**，"
        "所以「取消＋延誤」那幾種偏低",
        "- **樣本不獨立**：同一格在五個提前時間段各算一次，颱風期間相鄰的格、相鄰的機場一起出事。"
        "Wilson 區間假設獨立，實際的不確定性更大",
        "- 規則在期間內改過（10/22 定版 8 票、10/30 起 WN3 投票等），這裡全部混在一起算，"
        "只看每報當時寫出來的等級",
        "- 只有台灣、香港、澳門的機場有航班資料；日本、韓國、沖繩、華東、東南亞的等級"
        "完全沒有被檢驗",
        "",
    ]


def inventory_lines(res: Result) -> list[str]:
    a = res.args
    lines = ["## 1. 資料盤點", ""]
    lines.append(
        f"- 期間：`--from {a.get('from')}` `--to {a.get('to')}`（`generatedAt` 的 UTC 日期）；"
        f"{len(res.runs)} 報，{iso(res.runs[0]) if res.runs else '-'} – "
        f"{iso(res.runs[-1]) if res.runs else '-'}"
    )
    lines.append(
        f"- 快照裡的機場 {len(res.airports_all)} 個；有航班實測的 {len(res.truth.last)} 個"
        f"（下表）；沒有航班資料、**不算**的 {len(set(res.airports_all) - set(res.truth.last))} "
        "個：" + "、".join(sorted(set(res.airports_all) - set(res.truth.last)))
    )
    if res.snapshot_only:
        lines.append(
            "- TDX 機場只有快照裡不完整統計的格（逐班紀錄結束後；不算）："
            + "、".join(f"{k} {v} 格" for k, v in res.snapshot_only.items())
        )
    lines.append(
        "- `data` 分支的 `history/flights/` 只有 H6 之前 2026-10-18 那一天的快照、`history/tdx/`"
        " 只有 TDX "
        "呼叫次數，都沒有逐班資料；TDX 逐班只在事件保存 `history/events/<id>/flights/`"
    )
    c = res.archive_counts
    lines.append(
        f"- 預報格：{res.forecasts} 筆（每報每機場每格，不含已結束的 {c['endedSlots']} 筆、"
        f"`unknown` {c['unknownLevel']} 筆）→ 去重後 {res.deduped} 筆 → 有實測的 "
        f"{len(res.pairs) + len(res.few_pairs)} 筆（其中班次少於 {res.min_flights} 班的 "
        f"{len(res.few_pairs)} 筆另列、不進主要的表；沒有實測的 {res.no_truth} 筆）"
    )
    lines.append(
        f"- 已確認（`confirmed`）的格：{c['confirmed']} 筆（`confirmed.json` 期間內沒有時段時是 0"
        "，那一欄全是「-」）"
    )
    lines.append("")
    rows = []
    for r in res.airports:
        rows.append(
            [
                f"{r.icao}（{r.iata}）",
                "取消統計" if r.source == "cancellations" else "TDX 逐班",
                _tw(r.first),
                _tw(r.last),
                str(r.slots),
                str(r.few),
                str(r.early),
                str(res.truth.pending.get(r.icao, 0)),
            ]
        )
    lines += md_table(
        [
            "機場",
            "來源",
            "最早的格（台北）",
            "資料到（台北）",
            f"有效格（≥ {res.min_flights} 班）",
            "班次少的格",
            "格結束前算的",
            "還沒有結果",
        ],
        rows,
    )
    lines.append("")
    return lines


def definition_lines(res: Result) -> list[str]:
    return [
        "## 2. 事件定義與做法",
        "",
        "- 一格＝一個機場一個 UTC 6 小時格（00／06／12／18Z），航班依**表定**時間歸格，"
        "出發＋抵達合計；分母是那格的表定班數（不含貨機，共掛算一班）",
        "- 六種事件並列：**取消率 ≥ 10%／25%／50%**；**（取消＋延誤）÷ 表定 ≥ 10%／25%／50%**"
        "（延誤＝狀態延誤或預計／實際比表定晚 60 分鐘以上，取消的不重複算；五個取消統計機場"
        "與 TDX 逐班都有）。轉降不算",
        f"- **班次少的格**：表定少於 **{res.min_flights}** 班的格不進主要的表"
        "（10 班時一班取消＝10%，少於 10 班時一班就跨過最低的門檻）；"
        f"最後附一份 {FEW_FLIGHTS} 班（`FEW_FLIGHTS`）的對照",
        "- 提前時間＝格的 `from` − 那報的 `generatedAt`，分 0–24／24–48／48–72／72–96／96–120 小時"
        "（這一報所在的那格算 0–24、已經結束的格不算）",
        "- **去重**：同一個（機場、格、提前時間段）只取提前時間最靠近那段中間"
        "（12／36／60／84／108 小時）的一報（一樣近取比較新的），所以每格每段最多一筆；"
        "但同一格在五段各算一次",
        "- 等級：每格的 `level`（綜合，低／中／高；`confirmed`＝已確認另列）。「說中以上」＝中、"
        "高、已確認；"
        "「說高」＝高、已確認。命中＝說了而且有事件、誤報＝說了沒事件、漏報＝沒說但有事件",
        "- 區間：Wilson 95%，表裡寫成 `比例（事件/格數）[下限–上限]`（百分比）",
        "",
    ]


def calib_lines(res: Result) -> list[str]:
    lines = [
        "## 3. 校準表：等級 × 提前時間 → 有事件的比例",
        "",
        "每格 `比例（事件格/格數）[Wilson 95%]`。**重點是「高」那一欄**：說了高的格，實際上有多"
        "少比例真的出事。",
        "",
    ]
    for e in EVENTS:
        lines.append(f"### {e.label}")
        lines.append("")
        rows = []
        for i, label in enumerate((*BUCKET_LABELS, "全部")):
            rows.append([label, *(_cell(res.calib[e.key][lv][i], ci=True) for lv in LEVELS)])
        lines += md_table(["提前時間", *(LEVEL_NAMES[lv] for lv in LEVELS)], rows)
        lines.append("")
    lines += [
        "### 命中／誤報／漏報",
        "",
        "`命中/誤報/漏報`；「有事件比例」＝命中 ÷（命中＋誤報）、「抓到」＝命中 ÷（命中＋漏報）。",
        "",
    ]
    rows = []
    for e in EVENTS:
        for i, label in enumerate((*BUCKET_LABELS, "全部")):
            row = [e.label if i == 0 else "", label]
            for p in POSITIVE:
                c = res.conf[f"{e.key}:{p}"][i]
                row += [f"{c.tp}/{c.fp}/{c.fn}", _pct(c.precision), _pct(c.recall)]
            rows.append(row)
    lines += md_table(
        [
            "事件",
            "提前時間",
            "說中以上：命中/誤報/漏報",
            "有事件比例",
            "抓到",
            "說高：命中/誤報/漏報",
            "有事件比例",
            "抓到",
        ],
        rows,
    )
    lines.append("")
    return lines


def _compact_rows(
    groups: dict[str, dict[str, Cell]], order: list[tuple[str, str]]
) -> list[list[str]]:
    rows = []
    for key, label in order:
        g = groups.get(key)
        if g is None or not any(c.n for c in g.values()):
            continue
        rows.append([label, str(g[COMPACT[0]].n), *(_cell(g[k]) for k in COMPACT)])
    return rows


def _compact_headers(first: str, count: str = "格數") -> list[str]:
    return [first, count, *(EVENT_BY_KEY[k].label for k in COMPACT)]


def cause_lines(res: Result) -> list[str]:
    lines = [
        "## 4. 分原因、分期間",
        "",
        "全部提前時間合在一起（同一格最多算五次）。每格 `比例（事件/格數）`。",
        "",
        "### 原因（`causes`，只有中以上的格有；一格多個原因每個各算一次）",
        "",
    ]
    order = [(f"{c}:{lv}", f"{CAUSE_NAMES[c]}・{LEVEL_NAMES[lv]}") for c in CAUSES for lv in RISKY]
    rows = _compact_rows(res.causes, order)
    lines += md_table(_compact_headers("原因・等級"), rows) if rows else ["（沒有中以上的格）"]
    lines += ["", "### 29W 期間與非颱風期間", ""]
    periods = [*res.period_ids, NON_TYPHOON]
    order = [(f"{p}:{lv}", f"{p}・{LEVEL_NAMES[lv]}") for p in periods for lv in LEVELS]
    lines += md_table(_compact_headers("期間・等級"), _compact_rows(res.periods, order))
    lines += [
        "",
        "期間＝`events.json` 那筆的台灣日期（含兩端）而且是那筆列的機場；其他都算非颱風期間。",
        "",
    ]
    return lines


def layer_lines(res: Result) -> list[str]:
    lines = [
        "## 5. 分層：官方層對模式投票層、AI 燈",
        "",
        "### 官方層（TAF／警報）對模式投票層",
        "",
        "官方層只有 0–30 小時，所以官方層與「同一批格的模式層」只比 0–48 小時（前兩段）；另列模式層"
        "在 0–48 小時全部的格、48–120 小時。",
        "",
    ]
    groups = (
        ("official", "官方層（0–48 h）"),
        ("model-same", "模式層・同一批格（0–48 h）"),
        ("model-near", "模式層・全部（0–48 h）"),
        ("model-far", "模式層・全部（48–120 h）"),
    )
    order = [(f"{g}:{lv}", f"{name}・{LEVEL_NAMES[lv]}") for g, name in groups for lv in LEVELS]
    lines += md_table(_compact_headers("層・等級"), _compact_rows(res.layers, order))
    ai = res.ai
    lines += [
        "",
        "### AI 燈（Claude、Gemini）與規則燈，每報每機場",
        "",
        "每報每機場一個等級，和「這報 0–120 小時任一格有事件」比；規則燈＝同一報 20 格的最高等級。"
        "每個機場每個 UTC 日只取當天第一報；窗裡最後一格還沒有結果的不算。"
        f"共 {ai.windows} 個窗（不算的："
        + "、".join(f"{k} {v}" for k, v in sorted(ai.skipped.items()))
        + "）。"
        "`skipped`＝規則燈 5 天都低、沒有呼叫 AI，直接寫低。",
        "",
    ]
    whos = [
        ("rule", "規則燈（全部的窗）"),
        ("rule(ai-ok)", "規則燈（兩個 AI 都有評的窗）"),
        ("claude", "Claude（有評）"),
        ("gemini", "Gemini（有評）"),
        ("claude:skipped", "Claude（skipped）"),
        ("gemini:skipped", "Gemini（skipped）"),
    ]
    order = [(f"{w}:{lv}", f"{name}・{LEVEL_NAMES[lv]}") for w, name in whos for lv in LEVELS]
    lines += md_table(_compact_headers("燈・等級", "窗數"), _compact_rows(ai.rows, order))
    lines += [
        "",
        "說高的「有事件比例」（命中 ÷ 說高）與抓到率；後三列只用兩個 AI 都有評的窗：",
        "",
    ]
    rows = []
    same = [
        ("rule(ai-ok)", "規則燈（同一批窗）"),
        ("claude(ai-ok)", "Claude（同一批窗）"),
        ("gemini(ai-ok)", "Gemini（同一批窗）"),
    ]
    for w, name in [whos[0], *same]:
        c = ai.confusion.get(w)
        if not c:
            continue
        row = [name]
        for k in COMPACT:
            cf = c[k]["high"]
            row.append(f"{_pct(cf.precision)}／{_pct(cf.recall)}（{cf.tp}/{cf.fp}/{cf.fn}）")
        rows.append(row)
    lines += md_table(
        ["燈", *(f"{EVENT_BY_KEY[k].label}：有事件／抓到（命中/誤報/漏報）" for k in COMPACT)],
        rows,
    )
    lines.append("")
    return lines


def airport_lines(res: Result) -> list[str]:
    lines = [
        "## 6. 分機場",
        "",
        f"有效格（不重複、≥ {res.min_flights} 班）至少 {MIN_AIRPORT_SLOTS} 格的機場各一列。"
        "事件格是不重複的格數；後面是全部提前時間合起來的 `比例（事件/格數）`。"
        "「偏高／偏低」＝這個機場的 Wilson 區間整個在全部機場合計的比例之上／之下"
        "（格數 ≥ 5 才看；取消10＝取消率 ≥ 10%、取延25＝取消＋延誤 ≥ 25%）。",
        "",
    ]
    rows, small = [], []
    for r in res.airports:
        if r.slots < MIN_AIRPORT_SLOTS:
            small.append(f"{r.icao} {r.slots} 格")
            continue
        ev = "／".join(str(r.events[k]) for k in COMPACT)
        rows.append(
            [
                f"{r.icao}（{r.iata}）",
                str(r.slots),
                ev,
                _cell(r.cells["c10"]["low"]),
                _cell(r.cells["c25"]["low"]),
                _cell(r.cells["c25"]["medium"]),
                _cell(r.cells["c25"]["high"]),
                _cell(r.cells["cd25"]["high"]),
                "；".join(r.flags) or "-",
            ]
        )
    pooled_row = [
        "全部",
        str(len(_unique_slots(res.pairs))),
        "／".join(str(len(_unique_events(res.pairs, EVENT_BY_KEY[k]))) for k in COMPACT),
        _cell(res.calib["c10"]["low"][-1]),
        _cell(res.calib["c25"]["low"][-1]),
        _cell(res.calib["c25"]["medium"][-1]),
        _cell(res.calib["c25"]["high"][-1]),
        _cell(res.calib["cd25"]["high"][-1]),
        "",
    ]
    lines += md_table(
        [
            "機場",
            "有效格",
            "事件格 " + "／".join(EVENT_BY_KEY[k].label.replace(" ", "") for k in COMPACT),
            "說低→取消 ≥ 10%",
            "說低→取消 ≥ 25%",
            "說中→取消 ≥ 25%",
            "說高→取消 ≥ 25%",
            "說高→取消＋延誤 ≥ 25%",
            "明顯偏高／偏低",
        ],
        [*rows, pooled_row],
    )
    if small:
        lines += ["", "樣本不夠、不單獨列（仍算進全部）：" + "、".join(small)]
    lines.append("")
    return lines


def few_lines(res: Result) -> list[str]:
    lines = [
        f"## 7. 對照：班次少的門檻改成 {FEW_FLIGHTS} 班",
        "",
        f"主要的表排除表定少於 {res.min_flights} 班的格；改成只排除少於 {FEW_FLIGHTS} 班（HD37 的"
        "「班次少」）時，"
        "「全部提前時間」那一列變成：",
        "",
    ]
    rows = []
    for e in EVENTS:
        rows.append([e.label, *(_cell(res.calib_few4[e.key][lv][-1]) for lv in LEVELS)])
    lines += md_table(["事件", *(LEVEL_NAMES[lv] for lv in LEVELS)], rows)
    lines.append("")
    return lines


def _span_text(cells: list[Cell]) -> str:
    return "、".join(
        f"{label.replace(' h', '')} {_pct(c.rate)}（{c.k}/{c.n}）"
        for label, c in zip(BUCKET_LABELS, cells, strict=False)
        if c.n
    )


def _by_airport(rows: Iterable[Pair]) -> str:
    c = Counter(f.airport for f, _ in rows)
    return "、".join(f"{a} {n}" for a, n in sorted(c.items(), key=lambda x: (-x[1], x[0])))


def phenomena(res: Result) -> list[str]:
    """「值得 Shawn 看的現象」：固定的幾條，數字從結果來（不下該改門檻的結論）。"""
    out = []
    c25, cd25 = EVENT_BY_KEY["c25"], EVENT_BY_KEY["cd25"]
    for e in (c25, cd25):
        hi, lo = res.calib[e.key]["high"], res.calib[e.key]["low"]
        if hi[-1].n:
            out.append(
                f"說高的格，{e.label}的比例依提前時間：{_span_text(hi[:-1])}；"
                f"說低的格合計 {_pct(lo[-1].rate, 1)}（{lo[-1].k}/{lo[-1].n}）"
            )
    fa = sorted(
        (f.airport, f.start, t)
        for f, t in res.pairs
        if f.bucket == 0 and f.level in HIGH and not t.hit(c25)
    )
    if fa:
        out.append(
            f"0–24 小時說高、但取消率沒到 25% 的 {len(fa)} 格："
            + "、".join(
                f"{a} {_tw(s)}（取消 {t.cancelled}/{t.total}、延誤 {t.delayed}）"
                for a, s, t in fa[:8]
            )
            + ("…" if len(fa) > 8 else "")
        )
    med = res.calib["c25"]["medium"][-1]
    if med.n:
        parts = [f"說中的格{c25.label}合計 {med.text(False)}"]
        for p in [*res.period_ids, NON_TYPHOON]:
            c = res.periods.get(f"{p}:medium", {}).get("c25")
            if c is not None:
                parts.append(f"{p} {c.text(False)}")
        out.append("；".join(parts))
    uniq = _unique_events(res.pairs, c25)
    miss = res.misses["c25"]
    if uniq:
        low29 = [
            res.periods[f"{p}:low"]["c25"] for p in res.period_ids if f"{p}:low" in res.periods
        ]
        n_miss = len(miss)
        out.append(
            f"{c25.label}的事件格（不重複）共 {len(uniq)} 格；"
            f"0–24 小時那報說低（沒到中）的 {n_miss} 格"
            + (f"（{_by_airport(miss)}）" if miss else "")
            + (
                f"，其中 {over} 格是官方層說低、模式層說中以上（0–30 小時以官方為準）"
                if (over := sum(f.official == "low" and f.model in RISKY for f, _ in miss))
                else ""
            )
            + "".join(f"；颱風期間說低的格{c25.label} {c.text(False)}" for c in low29)
        )

    def nt(lv: str, ek: str) -> Cell:
        return res.periods.get(f"{NON_TYPHOON}:{lv}", {}).get(ek, Cell())

    c10 = EVENT_BY_KEY["c10"]
    out.append(
        f"非颱風期間：說高 {nt('high', 'c10').n} 筆、說中 {nt('medium', 'c10').n} 筆"
        f"（{c25.label} {nt('medium', 'c25').k} 筆）、說低 {nt('low', 'c10').n} 筆"
        f"（{c10.label} {nt('low', 'c10').text(False)}、{c25.label} "
        f"{nt('low', 'c25').text(False)}、{cd25.label} {nt('low', 'cd25').text(False)}）"
    )
    off = res.layers.get("official:high", {}).get("c25", Cell())
    mod = res.layers.get("model-same:high", {}).get("c25", Cell())
    if off.n or mod.n:
        out.append(
            f"0–48 小時有官方層的格，{c25.label}：官方層說高 {off.text(False)}；"
            f"同一批格模式層說高 {mod.text(False)}"
        )
    for r in res.airports:
        if r.slots < MIN_AIRPORT_SLOTS:
            continue
        notable = [x for x in r.flags if "偏高" in x or not x.startswith("說低")]
        if not notable:
            continue
        low10, m25 = r.cells["c10"]["low"], r.cells["c25"]["medium"]
        all10 = _pct(res.calib["c10"]["low"][-1].rate, 1)
        all25 = _pct(res.calib["c25"]["medium"][-1].rate)
        out.append(
            f"{r.icao}（{r.iata}）：{'；'.join(notable)}（說低時{c10.label} {low10.text(False)}，"
            f"全部機場 {all10}；說中時{c25.label} {m25.text(False)}，全部機場 {all25}）"
        )
    parts = []
    for w, name in (
        ("rule(ai-ok)", "規則燈"),
        ("claude(ai-ok)", "Claude"),
        ("gemini(ai-ok)", "Gemini"),
    ):
        c = res.ai.confusion.get(w, {}).get("c25", {}).get("high")
        if c is not None and c.tp + c.fp + c.fn:
            parts.append(
                f"{name} 說高 {c.tp + c.fp} 窗、有事件 {_pct(c.precision)}、抓到 {_pct(c.recall)}"
            )
    if parts:
        out.append(
            f"每報每機場（{res.ai.windows} 個窗；兩個 AI 都有評的窗、{c25.label}）："
            + "；".join(parts)
        )
    causes = [
        f"{CAUSE_NAMES[c]} {g['c25'].text(False)}"
        for c in CAUSES
        if (g := res.causes.get(f"{c}:high")) and g["c25"].n
    ]
    if causes:
        out.append(f"說高的格依原因（{c25.label}）：" + "、".join(causes))
    early = [t for t in res.truth.slots.values() if t.early and t.total >= res.min_flights]
    if early:
        hit = sum(t.hit(c25) for t in early)
        out.append(
            f"{len(early)} 個有效格的取消統計在格結束前就定了（`asOf` < `to`），"
            f"其中 {hit} 格是{c25.label}的事件；這些格的延誤數不可靠"
        )
    h10, h4 = res.calib["c25"]["high"][-1], res.calib_few4["c25"]["high"][-1]
    out.append(
        f"班次少的門檻 {res.min_flights} 班 → {FEW_FLIGHTS} 班："
        f"說高的格{c25.label} {h10.text(False)} → {h4.text(False)}"
    )
    return out


def render(res: Result) -> str:
    dc, tc = res.data_commit, res.tool_commit
    last_truth = max(res.truth.last.values(), default=None)
    last_run = res.runs[-1] if res.runs else None
    a = res.args
    head = [
        "# 回測校準報告：燈號等級對實際取消／延誤（HD46）",
        "",
        f"- 資料截止：預報 {iso(last_run)}（最後一報，台北 {_tw(last_run)}）；"
        f"航班實測到 {iso(last_truth)}（台北 {_tw(last_truth)}，各機場見盤點）",
        f"- `data` 分支 commit：`{dc.get('commit') or '?'}`（{dc.get('subject') or '-'}）",
        f"- 報告工具 commit：`{tc.get('commit') or '?'}`"
        + ("（工作目錄有未提交的修改）" if tc.get("dirty") else ""),
        "- 指令：`python -m tools.calibration_report --archive <data> "
        f"--from {a.get('from')} --to {a.get('to')} --min-flights {res.min_flights}`",
        "- 等級叫「風險」不叫「機率」；這份只回答「說高／中／低的時候，實際上各有多少比例"
        "真的大量取消或延誤」，**不下門檻該改成多少的結論**",
        "",
    ]
    body = [
        *head,
        *limit_lines(res),
        *inventory_lines(res),
        *definition_lines(res),
        *calib_lines(res),
        *cause_lines(res),
        *layer_lines(res),
        *airport_lines(res),
        *few_lines(res),
        "## 8. 值得 Shawn 看的現象",
        "",
        *(f"- {p}" for p in phenomena(res)),
        "",
    ]
    return "\n".join(body)


# ---- JSON ----


def _cells_json(cells: dict[str, Cell]) -> dict:
    return {k: c.summary() for k, c in cells.items()}


def to_json(res: Result) -> dict:
    labels = [*BUCKET_LABELS, "all"]
    return {
        "meta": {
            "args": res.args,
            "dataCommit": res.data_commit,
            "toolCommit": res.tool_commit,
            "firstRun": iso(res.runs[0]) if res.runs else None,
            "lastRun": iso(res.runs[-1]) if res.runs else None,
            "runs": len(res.runs),
            "minFlights": res.min_flights,
            "buckets": list(BUCKET_LABELS),
            "events": [
                {"key": e.key, "label": e.label, "withDelay": e.with_delay, "rate": e.rate}
                for e in EVENTS
            ],
            "dedupe": "per (airport, slot, lead bucket) keep the run whose lead is closest to "
            "the bucket centre (12/36/60/84/108 h); ties keep the newer run",
        },
        "inventory": {
            "airportsInSnapshots": len(res.airports_all),
            "airportsWithFlights": sorted(res.truth.last),
            "airportsWithoutFlights": sorted(set(res.airports_all) - set(res.truth.last)),
            "snapshotOnlySlots": res.snapshot_only,
            "forecasts": res.forecasts,
            "deduped": res.deduped,
            "pairs": len(res.pairs),
            "fewPairs": len(res.few_pairs),
            "noTruth": res.no_truth,
            "counts": dict(sorted(res.archive_counts.items())),
            "airports": [
                {
                    "icao": r.icao,
                    "source": r.source,
                    "firstSlot": iso(r.first),
                    "truthLast": iso(r.last),
                    "validSlots": r.slots,
                    "fewSlots": r.few,
                    "earlySlots": r.early,
                    "pendingSlots": res.truth.pending.get(r.icao, 0),
                }
                for r in res.airports
            ],
        },
        "calibration": {
            e.key: {
                lv: dict(zip(labels, (c.summary() for c in res.calib[e.key][lv]), strict=True))
                for lv in LEVELS
            }
            for e in EVENTS
        },
        "calibrationFew4": {
            e.key: {lv: res.calib_few4[e.key][lv][-1].summary() for lv in LEVELS} for e in EVENTS
        },
        "confusion": {
            k: dict(zip(labels, (c.summary() for c in v), strict=True)) for k, v in res.conf.items()
        },
        "causes": {k: _cells_json(v) for k, v in sorted(res.causes.items())},
        "periods": {k: _cells_json(v) for k, v in sorted(res.periods.items())},
        "layers": {k: _cells_json(v) for k, v in sorted(res.layers.items())},
        "ai": {
            "windows": res.ai.windows,
            "skipped": dict(sorted(res.ai.skipped.items())),
            "rows": {k: _cells_json(v) for k, v in sorted(res.ai.rows.items())},
            "confusion": {
                who: {ek: {p: c.summary() for p, c in v.items()} for ek, v in sorted(d.items())}
                for who, d in sorted(res.ai.confusion.items())
            },
        },
        "airports": [
            {
                "icao": r.icao,
                "validSlots": r.slots,
                "events": r.events,
                "levels": {ek: _cells_json(v) for ek, v in r.cells.items()},
                "flags": r.flags,
            }
            for r in res.airports
        ],
        "misses0to24": {
            k: [
                {
                    "airport": f.airport,
                    "from": iso(f.start),
                    "run": iso(f.run),
                    "level": f.level,
                    "official": f.official,
                    "model": f.model,
                    "total": t.total,
                    "cancelled": t.cancelled,
                    "delayed": t.delayed,
                }
                for f, t in v
            ]
            for k, v in res.misses.items()
        },
        "phenomena": phenomena(res),
    }


# ---- CLI ----


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="回測校準報告（HD46）：燈號等級對實際取消／延誤")
    ap.add_argument(
        "--archive", required=True, type=Path, help="data 分支的 checkout（底下有 history/）"
    )
    ap.add_argument("--from", dest="start", required=True, help="第一報的 UTC 日期（YYYY-MM-DD）")
    ap.add_argument("--to", dest="end", required=True, help="最後一報的 UTC 日期（含）")
    ap.add_argument("--min-flights", type=int, default=DEFAULT_MIN_FLIGHTS)
    ap.add_argument("--airports", type=Path, default=ROOT / "airports.json")
    ap.add_argument("--events", type=Path, default=ROOT / "events.json")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--json", type=Path)
    a = ap.parse_args(argv)
    if not (a.archive / "history").is_dir():
        ap.error(f"{a.archive} 底下沒有 history/")
    try:
        start, end = parse_day(a.start, end=False), parse_day(a.end, end=True)
    except ValueError as e:
        ap.error(str(e))
    if a.min_flights < 1:
        ap.error("--min-flights 至少 1")
    t0 = time.monotonic()
    res = compute(
        a.archive,
        start,
        end,
        a.min_flights,
        a.airports,
        a.events,
        args={"from": a.start, "to": a.end, "minFlights": a.min_flights},
    )
    md = render(res)
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(md, encoding="utf-8")
    else:
        print(md)
    if a.json:
        a.json.parent.mkdir(parents=True, exist_ok=True)
        a.json.write_text(
            json.dumps(to_json(res), ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )
    print(
        f"{len(res.runs)} 報、有實測的機場 {len(res.truth.last)} 個、"
        f"配對 {len(res.pairs)} 筆（班次少另列 {len(res.few_pairs)}）、"
        f"{time.monotonic() - t0:.1f} 秒",
        file=sys.stderr if not a.out else sys.stdout,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
