"""颱風 29W（CHAMPI）的驗證報告（HD22）：各系統依提前時間的陣風誤差、停飛命中、路徑誤差。

在 repo 根目錄跑（`data` 是 `data` 分支的 checkout，底下有 `history/`）：

    python -m tools.report_29w --archive data --event 29W \\
      [--jtwc bwp292026.dat] [--jma bst_all.txt] [--cutoff 2026-10-22T04:00Z] \\
      [--until 2026-10-25T14:00+08:00] [--truth-until 2026-10-26T24:00+08:00] \\
      [--cancel-rate 0.3 --cancel-count 10] [--out report/29W.md] [--json report/29W.json]

29W 實際用法（HD36）：

    python -m tools.report_29w --archive data --event 29W --jtwc bwp292026.dat \\
      --until 2026-10-25T14:00+08:00 --truth-until 2026-10-26T24:00+08:00 \\
      --out report/29W.md --json report/29W.json

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

兩個截止（HD36，Shawn 2026-10-24 定案，`docs/prompts/2026-10-24-HD36-report-until.md`）：

- `--until`：預報算到「這個時間之後的第一報」——`generatedAt` ≤ 時間的報全部算，
  再加上之後的第一報（還沒出就只算到時間以前的）；WN3 事件檔用起報、同一個規則；模式路徑
  只收留下的報用過的起報（WN3 路徑照 WN3 的規則）。不給＝全部的報。時間要寫時區
  （`Z`、`+08:00`），`T24:00` 當隔天 `T00:00`
- `--truth-until`（`T`）：實測只用到這個時間；不給＝`events.json` 那筆 `to` 的台灣日期
  隔天 00:00。實測的最後時間取 `min(T, 該資料本身最新的時間)`（航班是 `asOf`）。超過的
  不算命中也不算誤報，另計「超過實測截止」：(a) 格的 `to` 晚於 `T`（METAR 也只用 ≤ `T`
  的）；(b) 每格：格的 `to` 晚於實測最後時間；(b) 每報每機場：窗裡超過的格丟掉（計
  「截短」），一格不剩計「沒有實測」，其他照原規則比（`first` 照截短後的窗）；規則燈的
  預測仍取整個 0–120 小時的最高等級（和 AI 的 5 天燈同一範圍）。另算一份「只算完整窗」
  （沒有格被丟掉的）當對照；(c) 真相只用 `validAt` ≤ `T` 的點，模式路徑 `validAt` > `T`
  的點不算

停飛實測加讀逐班航班（HD37，Shawn 2026-10-25 定案，
`docs/prompts/2026-10-25-HD37-report-flights-truth.md`）：

- 來源依機場選：`history/cancellations/` 有的機場照舊用它；沒有的機場用 `events/<id>/flights/`
  的逐班紀錄（`source: tdx`）。同一班（`airport`、`dir`、`flight`、`schedUtc`、`source`）取 `t`
  最新的一行，表定時間落在格內的算進那格，停飛規則和 `cancellations/` 完全一樣；那格沒有航班不算
- 實測的最後時間每個機場各一個：資料最新的時間（`cancellations/` 是那個機場的 `asOf`；逐班是
  整批最新的 `t`，所有 `source: tdx` 的行裡最大的）和 `--truth-until` 早的那個。
  `levels.truthLast` 是各機場裡最晚的
- 班次少：那格表定（出發＋抵達）少於 `FEW_FLIGHTS`（4）班，`cancellations/` 的機場也照同一個
  標準（用那格的 `total`）。規則照判，只是另外列：每格是「其中班次少」的子集；每報每機場是結果
  靠班次少的格決定的窗（有停飛時停飛的格全是班次少、沒停飛時有實測的格全是班次少；`few_window`）
- 窗裡的格都沒有航班列（逐班紀錄開始之前的報）不當成「沒停飛」，計 `windowNoFlights`
- 狀態重新分類（只在報告裡，不改存檔；`reclassify`）：`class: other` 的 `加班` → 正常、`轉降` →
  轉降（不算取消，另外計數）、`預計HH:MM到站／離站／出發`（可帶 `MM/DD` 或 `YYYY/MM/DD`）→ 預計
  比表定晚 60 分鐘以上算延誤、否則正常（沒寫日期照 `cancellations.py` 放在表定前 6 小時到後
  18 小時之間）；其他照舊 `other`，列出前 10 種

旁觀・回補（HD33a，`docs/prompts/2026-10-25-HD33a-new-models-backfill.md`）：事件目錄有
`backfill/openmeteo-<模式>.jsonl`（`python -m hongthai.events backfill-openmeteo`，UKMO、GEM、
ARPEGE、CMA GRAPES 經 Open-Meteo Previous Runs API）時多算這四個模式；沒有這個目錄時報告與 JSON
和以前一樣。

- 提前時間：Open-Meteo 的 `previousDay` N＝提前 24N 起、不到 24(N+1) 小時的那一報（文件：day1 是
  valid time 前 24 小時的預報）。照提示詞把「起報」當成**格開始時間減 N 天那一天的 00Z**（一格裡的
  小時都用同一個起報），提前時間＝格的 `from` − 起報＝24N＋0／6／12／18，照 HD22 的切法落在第 N 段：
  N＝0 → 0–24、1 → 24–48 … 4 → 96–120；N＝5 是 120 小時以後，不算（檔裡照存）。同一個起報的格合成
  一報（`BackfillRun`），像 WN3 事件檔一樣算。格內 (from, to] 6 個小時都有才算（資料頭尾的半格不算）
- 一格的預測照 `assess.hourly_for_slot`（ICON／JMA 那套）：有陣風的模式取 (from, to] 小時裡前一小時
  最大陣風的最大，側風每小時用陣風與風向算再取大；陣風全是 null 的模式（`gustEstimated`）取
  [from, to] 小時裡最大的平均風 × 機場的係數 G，側風用每小時的平均風 × G。G 用快照裡同一機場
  估算陣風那幾筆的 `gustFactor`（起報當時或之前最近的一報；之前沒有就用最早有的那報），都沒有用 1.4
- 模式等級：單一模式的陣風（≥ 37 中、≥ 48 高）與側風（≥ 27 中、≥ 33 高）取較高，門檻照
  `airports.json`（同 `assess.gust_level`／`crosswind_level`；`assess` 要 numpy，這裡照抄不載入）
- `--until`：起報 ≤ 留下的最後一報的 `generatedAt`（沒有快照時用 `--until` 本身）的才算；
  `--truth-until` 和 (a)、(b) 每格同一套
- (a) 陣風：四列接在各表最後，標「（旁觀・回補）」；(b) 多一張「每格各模式的風等級」對停飛實測：快照
  8 個模式各自的 `levels.wind` 與回補四個並列（之後決定投票或加權用）
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from math import asin, cos, radians, sin, sqrt
from pathlib import Path
from statistics import mean, median
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from hongthai import cancellations  # noqa: E402
from hongthai.config import (  # noqa: E402
    GUST_FACTOR_DEFAULT,
    Airport,
    Event,
    Runway,
    Thresholds,
    load_airports,
    load_events,
)
from hongthai.timeutil import floor_6h, iso, parse_time  # noqa: E402
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
# 停飛實測的來源（HD37）
CANCELLATIONS, FLIGHTS = "cancellations", "flights"
FLIGHT_SOURCE = "tdx"
FLIGHT_CLASSES = ("normal", "cancelled", "delayed", "diverted", "other")
FLIGHT_CLASS_NAMES = {
    "normal": "正常",
    "cancelled": "取消",
    "delayed": "延誤",
    "diverted": "轉降",
    "other": "other",
}
FEW_FLIGHTS = 4  # 一格表定（出發＋抵達）少於這麼多班標「班次少」（Shawn 2026-10-25）
_STAMP = "%Y%m%dT%H%MZ"
_TRACK_FILE = re.compile(r"^(\d{8}T\d{4}Z)-(.+)\.json$")
_NAME = re.compile(r"[A-Za-z][A-Za-z' -]*[A-Za-z]")
# HD33a：Open-Meteo Previous Runs 回補的旁觀模式（只在報告裡比）
BACKFILL_ORDER = ("ukmo", "gem", "arpege", "cma")
BACKFILL_LABEL = "（旁觀・回補）"
BACKFILL_MAX_DAY = 4  # previousDay 5 是提前 120 小時以後
_BACKFILL_FILE = re.compile(r"^openmeteo-(.+)\.jsonl$")
WIND_LEVELS = ("low", "medium", "high")


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


_HOUR24 = re.compile(r"^(\d{4}-\d{2}-\d{2})T24(:00){1,2}(\.0+)?(Z|[+-]\d{2}:?\d{2})$")


def parse_cli_time(s: str) -> datetime:
    """`--until`／`--truth-until`：ISO 8601，要有時區（`Z` 或 `+08:00`）；`T24:00` 當隔天 `T00:00`。
    看不懂丟 ValueError。"""
    m = _HOUR24.match(s.strip())
    text = f"{m.group(1)}T00:00{m.group(4)}" if m else s.strip()
    try:
        t = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"看不懂的時間 {s}（ISO 8601，例如 2026-10-26T24:00+08:00）") from None
    if t.tzinfo is None:
        raise ValueError(f"時間 {s} 要寫時區（Z 或 +08:00）")
    return (t + timedelta(days=1) if m else t).astimezone(UTC)


def default_truth_until(event: Event) -> datetime:
    """`events.json` 的 `to`（台灣日期）隔天 00:00（台灣）：`to: 2026-10-26` → 10/26 16:00Z。"""
    nxt = event.end + timedelta(days=1)
    return datetime(nxt.year, nxt.month, nxt.day, tzinfo=TAIPEI).astimezone(UTC)


def select_until[T](
    items: list[T], at: Callable[[T], datetime], until: datetime | None
) -> tuple[list[T], bool]:
    """`at` ≤ `until` 的全部，再加上之後的第一個（依 `at` 排序）；回傳
    （留下的, 有沒有之後的那一個）。`until` 是 None 時全部留下。"""
    items = sorted(items, key=at)
    if until is None:
        return items, False
    kept = [x for x in items if at(x) <= until]
    later = [x for x in items if at(x) > until]
    return kept + later[:1], bool(later)


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


def load_metars(d: Path, until: datetime | None = None) -> dict[str, list[Obs]]:
    """`metar/*.jsonl` → 每站的觀測（依時間排序；同一站同一 `observedAt` 只留一筆；
    只留 ≤ `until` 的）。"""
    seen: set[tuple[str, datetime]] = set()
    out: dict[str, list[Obs]] = defaultdict(list)
    for r in _jsonl(sorted((d / "metar").glob("*.jsonl"))):
        icao, at, wind = r.get("icao"), parse_time(r.get("observedAt")), _num(r.get("windKt"))
        if not isinstance(icao, str) or at is None or wind is None or (icao, at) in seen:
            continue
        if until is not None and at > until:
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
class AirportTruth:
    """一個機場的停飛實測：每個 UTC 6 小時格一列（`cancellations/` 的列，或逐班彙整成同樣的形狀
    `{"dep": {"total", "cancelled", "delayed", "diverted", "other"}, "arr": {…}}`）。"""

    source: str  # CANCELLATIONS／FLIGHTS
    rows: dict[datetime, dict]  # 格的 `from` → 列
    last: (
        datetime | None
    )  # 資料最新的時間（`cancellations/` 是這個機場的 `asOf`、逐班是整批的 `t`）


@dataclass
class Cancellations:
    """停飛實測（HD37）：`cancellations/` 有的機場用它，其他機場用逐班紀錄。"""

    by_airport: dict[str, AirportTruth]
    # 逐班重新分類（只算實測算到之前結束的格）：類別 → 班數、規則 → 班數、看不懂的狀態 → 班數
    classes: Counter[str] = field(default_factory=Counter)
    reclassified: Counter[str] = field(default_factory=Counter)
    unknown: Counter[str] = field(default_factory=Counter)

    @property
    def airports(self) -> frozenset[str]:
        return frozenset(self.by_airport)

    @property
    def as_of(self) -> datetime | None:
        """`cancellations/` 最新的 `asOf`（定版以來的「航班資料到」）。"""
        ts = [a.last for a in self.by_airport.values() if a.source == CANCELLATIONS and a.last]
        return max(ts, default=None)

    def last(self, airport: str, until: datetime | None) -> datetime | None:
        """這個機場實測的最後時間＝min(`until`, 資料最新的時間)。"""
        a = self.by_airport.get(airport)
        if a is None or a.last is None:
            return None
        return a.last if until is None else min(until, a.last)

    def stopped(
        self, airport: str, start: datetime, end: datetime, rate: float, count: int
    ) -> tuple[bool | None, bool]:
        """（那格停飛了沒, 班次少）；還沒結束或沒有那格的列回 （None, False）。"""
        a = self.by_airport.get(airport)
        if a is None or a.last is None or end > a.last:
            return None, False
        row = a.rows.get(start)
        if row is None:
            return None, False
        actual = is_stopped(row, rate, count)
        return actual, actual is not None and row_total(row) < FEW_FLIGHTS


def row_total(row: dict) -> int:
    return sum(int((row.get(k) or {}).get("total") or 0) for k in ("dep", "arr"))


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
    by_airport: dict[str, AirportTruth] = {}
    for p in sorted((history / "cancellations").glob("????-??-??.json")):
        doc = _read_json(p)
        for r in doc if isinstance(doc, list) else []:
            if not isinstance(r, dict):
                continue
            start, t = parse_time(r.get("from")), parse_time(r.get("asOf"))
            if not isinstance(r.get("airport"), str) or start is None:
                continue
            a = by_airport.setdefault(r["airport"], AirportTruth(CANCELLATIONS, {}, None))
            a.rows[start] = r
            if t is not None and (a.last is None or t > a.last):
                a.last = t
    return Cancellations(by_airport)


# ---- 真相：逐班航班（HD37） ----

_EST = re.compile(
    r"預計\s*(?:(?:(\d{4})[/-])?(\d{1,2})[/-](\d{1,2})\s*)?(\d{1,2}:\d{2})\s*(?:到站|離站|出發|抵達|起飛)?"
)


def reclassify(row: dict, tz: ZoneInfo) -> tuple[str, str | None]:
    """逐班一行的 `class` → 報告用的類別（`normal`／`cancelled`／`delayed`／`diverted`／`other`）與
    套到的規則（沒套到回 None）。只動 `class: other` 的：`加班` → 正常；`轉降` → 轉降；
    `預計HH:MM到站／離站`（可帶 `MM/DD` 或 `YYYY/MM/DD`）→ 預計時間比表定晚 60 分鐘以上算延誤，
    否則正常（沒寫日期照 `cancellations.py` 放在表定前 6 小時到後 18 小時之間）。"""
    cls = row.get("class")
    if cls in ("normal", "cancelled", "delayed"):
        return str(cls), None
    status = str(row.get("status") or "").strip()
    compact = re.sub(r"\s+", "", status)
    if compact.startswith("加班"):
        return "normal", "extra"
    if compact.startswith("轉降"):
        return "diverted", "diverted"
    m = _EST.fullmatch(status)
    sched = parse_time(row.get("schedUtc"))
    clock = cancellations._clock(m[4]) if m else None
    if m and sched is not None and clock is not None:
        local = sched.astimezone(tz)
        if m[2]:
            try:
                day = (
                    date(int(m[1]), int(m[2]), int(m[3]))
                    if m[1]
                    else cancellations._nearest_year(int(m[2]), int(m[3]), local.date())
                )
            except ValueError:
                return "other", None
            est = datetime.combine(day, clock, tzinfo=tz)
        else:
            est = cancellations._near(local, clock)
        if est is not None:
            late = est - local >= timedelta(minutes=cancellations.DELAY_MINUTES)
            return ("delayed", "estDelayed") if late else ("normal", "estOnTime")
    return "other", None


def _zero_counts() -> dict[str, int]:
    return {"total": 0, **dict.fromkeys(FLIGHT_CLASSES[1:], 0)}


def load_flights(
    d: Path,
    truth: Cancellations,
    airports: Iterable[str],
    tz: dict[str, str],
    until: datetime | None = None,
) -> None:
    """`flights/*.jsonl`（`source: tdx`）→ 補進 `truth`：只補 `airports` 裡 `cancellations/` 沒有的
    機場。同一班（`airport`、`dir`、`flight`、`schedUtc`、`source`）取 `t` 最新的一行（同 `t` 取檔裡
    後面的），依表定時間歸格。逐班機場的 `last` 是整批最新的 `t`（所有 `source: tdx` 的行，
    十個機場是同一個請求抓的；逐班只在有變化時寫，班次少的機場自己最新的 `t` 會停在很早）。
    重新分類的次數只算實測的最後時間（min(`until`, `last`)）之前結束的格。"""
    want = set(airports) - truth.airports
    latest: dict[tuple, tuple[datetime, dict]] = {}
    last: datetime | None = None
    for r in _jsonl(sorted((d / "flights").glob("*.jsonl"))):
        airport, t = r.get("airport"), parse_time(r.get("t"))
        if r.get("source") != FLIGHT_SOURCE or t is None:
            continue
        last = t if last is None else max(last, t)
        if airport not in want:
            continue
        key = (airport, r.get("dir"), r.get("flight"), r.get("schedUtc"), r.get("source"))
        if key not in latest or t >= latest[key][0]:
            latest[key] = (t, r)
    step = timedelta(hours=6)
    for (airport, direction, *_), (_, r) in latest.items():
        sched = parse_time(r.get("schedUtc"))
        if direction not in ("dep", "arr") or sched is None:
            continue
        zone = ZoneInfo(tz.get(airport, "Asia/Taipei"))
        cls, rule = reclassify(r, zone)
        a = truth.by_airport.setdefault(airport, AirportTruth(FLIGHTS, {}, last))
        start = floor_6h(sched)
        row = a.rows.setdefault(start, {"dep": _zero_counts(), "arr": _zero_counts()})
        row[direction]["total"] += 1
        if cls != "normal":
            row[direction][cls] += 1
        end_ok = (lt := truth.last(airport, until)) is not None and start + step <= lt
        if end_ok:
            truth.classes[cls] += 1
            if rule:
                truth.reclassified[rule] += 1
            if cls == "other":
                truth.unknown[str(r.get("status") or "").strip()] += 1


def airport_tz(path: Path) -> dict[str, str]:
    doc = _read_json(path)
    rows = doc.get("airports") if isinstance(doc, dict) else None
    return {
        a["icao"]: a["tz"]
        for a in rows or []
        if isinstance(a, dict) and isinstance(a.get("icao"), str) and isinstance(a.get("tz"), str)
    }


@dataclass
class TruthSource:
    """報告「停飛實測」表的一列。"""

    source: str
    last: datetime | None  # 資料最新的時間
    used: datetime | None  # 實測的最後時間＝min(實測截止, last)
    slots: int  # 實測的最後時間之前結束、有航班的格
    few: int  # 其中班次少的
    flights: int
    cancelled: int
    delayed: int
    diverted: int | None  # `cancellations/` 沒有這一類

    def summary(self) -> dict:
        return {
            "source": self.source,
            "last": iso(self.last),
            "truthLast": iso(self.used),
            "slots": self.slots,
            "fewSlots": self.few,
            "flights": self.flights,
            "cancelled": self.cancelled,
            "delayed": self.delayed,
            "diverted": self.diverted,
        }


def truth_sources(
    truth: Cancellations, airports: Iterable[str], until: datetime | None
) -> dict[str, TruthSource]:
    out = {}
    for icao in airports:
        a = truth.by_airport.get(icao)
        if a is None:
            continue
        used = truth.last(icao, until)
        rows = [
            r
            for start, r in a.rows.items()
            if used is not None and start + timedelta(hours=6) <= used and row_total(r) > 0
        ]

        def total(k: str, rows: list[dict] = rows) -> int:
            return sum(int((r.get(d) or {}).get(k) or 0) for r in rows for d in ("dep", "arr"))

        out[icao] = TruthSource(
            a.source,
            a.last,
            used,
            len(rows),
            sum(row_total(r) < FEW_FLIGHTS for r in rows),
            total("total"),
            total("cancelled"),
            total("delayed"),
            total("diverted") if a.source == FLIGHTS else None,
        )
    return out


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
    winds: dict[str, str] = field(default_factory=dict)  # 模式 → 自己的風等級（`levels.wind`）


@dataclass
class AirportReport:
    icao: str
    slots: list[Slot]
    ai: dict[str, str | None]  # claude／gemini → `status: ok` 的等級，其他 None
    gust_factor: float | None = None  # 估算陣風那幾筆的 `gustFactor`（HD33a 回補估算用）


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
        factor: float | None = None
        for s in a.get("slots") or []:
            start, end = parse_time(s.get("from")), parse_time(s.get("to"))
            if start is None or end is None:
                continue
            model = s.get("model") if isinstance(s.get("model"), dict) else {}
            total = _num((model.get("vote") or {}).get("total"))
            if total is not None:
                votes = max(votes or 0, int(total))
            gusts = []
            winds: dict[str, str] = {}
            for e in model_entries(model, doc.get("runs")):
                if e.get("level") is not None and e.get("run"):
                    runs.setdefault(e["id"], e["run"])
                g = _num(e.get("gustKt"))
                if g is not None:
                    gusts.append(ModelGust(e["id"], g, bool(e.get("gustEstimated"))))
                wind = (e.get("levels") or {}).get("wind")
                if wind in WIND_LEVELS:
                    winds[e["id"]] = wind
                if factor is None and e.get("gustEstimated"):
                    factor = _num(e.get("gustFactor"))
            lv = s.get("level")
            slots.append(Slot(start, end, lv if lv in LEVELS else None, gusts, winds))
        if a.get("icao") in want:
            out[a["icao"]] = AirportReport(a["icao"], slots, levels, factor)
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


# ---- 旁觀・回補（HD33a） ----


@dataclass
class BfHour:
    valid: datetime
    wind: float | None
    wdir: float | None
    gust: float | None


@dataclass
class BackfillData:
    """`backfill/openmeteo-<模式>.jsonl`：模式 →（機場, previousDay）→ 有效時間 → 那個小時。"""

    hours: dict[str, dict[tuple[str, int], dict[datetime, BfHour]]]
    estimated: dict[str, bool]  # 模式 → 陣風是不是估算（任一行 `gustEstimated`）
    rows: dict[str, int]  # 模式 → 行數（去重後）


@dataclass
class BackfillRun:
    """同一個（模式, 起報）的格（起報＝格開始時間減 previousDay 天那一天的 00Z）。"""

    model: str
    run: datetime
    airports: dict[str, list[Slot]]


def load_backfill(d: Path, airports: Iterable[str]) -> BackfillData | None:
    """`backfill/openmeteo-*.jsonl` → 回補資料；沒有這個目錄或檔回 None。同一個（機場、`validAt`、
    `previousDay`）只留第一行。"""
    files = sorted(
        p for p in (d / "backfill").glob("openmeteo-*.jsonl") if _BACKFILL_FILE.match(p.name)
    )
    if not files:
        return None
    want = set(airports)
    out = BackfillData({}, {}, {})
    for p in files:
        m = _BACKFILL_FILE.match(p.name)
        assert m
        model = m.group(1)
        hours = out.hours.setdefault(model, {})
        out.estimated.setdefault(model, False)
        out.rows.setdefault(model, 0)
        for r in _jsonl([p]):
            icao, t, day = r.get("icao"), parse_time(r.get("validAt")), r.get("previousDay")
            if icao not in want or t is None or not isinstance(day, int) or isinstance(day, bool):
                continue
            by_t = hours.setdefault((icao, day), {})
            if t in by_t:
                continue
            by_t[t] = BfHour(
                t, _num(r.get("windKt")), _num(r.get("windDir")), _num(r.get("gustKt"))
            )
            out.rows[model] += 1
            if r.get("gustEstimated") is True:
                out.estimated[model] = True
    return out


def _round1(v: float | None) -> float | None:
    return None if v is None else round(v, 1)


def crosswind_kt(
    speed: float | None, wdir: float | None, runways: Iterable[Runway]
) -> float | None:
    """同 `assess.crosswind_kt`：所有跑道（每條兩個方向）裡最小的側風分量；沒有風向時＝風速。"""
    runways = tuple(runways)
    if speed is None or not runways:
        return None
    if wdir is None:
        return float(speed)
    return min(speed * abs(sin(radians(wdir - h))) for r in runways for h in r.headings)


def wind_level(gust: float | None, crosswind: float | None, th: Thresholds) -> str | None:
    """同 `assess._wind_level`：陣風（≥ 中／高門檻）與側風取較高；兩個都沒有回 None。"""
    levels = []
    if gust is not None:
        levels.append(
            2 if gust >= th.model_high_gust_kt else 1 if gust >= th.model_medium_gust_kt else 0
        )
    if crosswind is not None:
        levels.append(
            2
            if crosswind >= th.crosswind_high_kt
            else 1
            if crosswind >= th.crosswind_medium_kt
            else 0
        )
    return WIND_LEVELS[max(levels)] if levels else None


def backfill_slot(
    hours: dict[datetime, BfHour],
    start: datetime,
    end: datetime,
    estimated: bool,
    runways: Iterable[Runway],
    g: float,
) -> tuple[float | None, float | None]:
    """一格的（陣風, 側風），同 `assess.hourly_for_slot`（見開頭「旁觀・回補」）。"""
    runways = tuple(runways)
    step = timedelta(hours=1)
    n = int(lead_hours(end, start))
    if estimated:
        inst = [hours[t] for t in (start + i * step for i in range(n + 1)) if t in hours]
        winds = [(h.wind, h.wdir) for h in inst if h.wind is not None]
        if not winds:
            return None, None
        wind = round(max(w for w, _ in winds), 1)
        xw = [crosswind_kt(w * g, wd, runways) for w, wd in winds]
        return round(wind * g, 1), _round1(max((x for x in xw if x is not None), default=None))
    prev = [hours[t] for t in (start + i * step for i in range(1, n + 1)) if t in hours]
    hits = [h for h in prev if h.gust is not None]
    if not hits:
        return None, None
    top = max(h.gust for h in hits if h.gust is not None)
    xw = [crosswind_kt(h.gust, h.wdir, runways) for h in hits]
    return round(top, 1), _round1(max((x for x in xw if x is not None), default=None))


def gust_factor_at(reports: list[Report], icao: str, t: datetime) -> float:
    """`t` 當時或之前最近一報那個機場的 G；之前沒有用最早有的那報；都沒有 1.4。"""
    have = [
        (r.generated, f) for r in reports if (a := r.airports.get(icao)) and (f := a.gust_factor)
    ]
    if not have:
        return GUST_FACTOR_DEFAULT
    before = [f for at, f in have if at <= t]
    return before[-1] if before else have[0][1]


def backfill_runs(
    data: BackfillData, sites: dict[str, Airport], reports: list[Report]
) -> list[BackfillRun]:
    """回補資料 → 每個（模式, 起報）一報、每個機場每格一個 `Slot`（`gusts` 一筆、`winds` 一筆）。
    `previousDay` 0–4 才算；格見 `full_slots`。"""
    runs: dict[tuple[str, datetime], dict[str, list[Slot]]] = {}
    for model, by_key in data.hours.items():
        est = data.estimated.get(model, False)
        for (icao, day), hours in by_key.items():
            if not 0 <= day <= BACKFILL_MAX_DAY or icao not in sites:
                continue
            site = sites[icao]
            for start in full_slots(hours):
                end = start + timedelta(hours=6)
                run = datetime.combine(
                    (start - timedelta(days=day)).date(), datetime.min.time(), UTC
                )
                g = gust_factor_at(reports, icao, run) if est else 1.0
                gust, xw = backfill_slot(hours, start, end, est, site.runways, g)
                lv = wind_level(gust, xw, site.thresholds)
                if gust is None and lv is None:
                    continue
                slot = Slot(
                    start,
                    end,
                    None,
                    [ModelGust(model, gust, est)] if gust is not None else [],
                    {model: lv} if lv is not None else {},
                )
                runs.setdefault((model, run), {}).setdefault(icao, []).append(slot)
    return [
        BackfillRun(m, run, {k: sorted(v, key=lambda s: s.start) for k, v in aps.items()})
        for (m, run), aps in sorted(runs.items(), key=lambda x: (x[0][1], x[0][0]))
    ]


def full_slots(hours: dict[datetime, BfHour]) -> list[datetime]:
    """(from, to] 6 個小時都有的 6 小時格（UTC 00／06／12／18 起）的開始時間；資料頭尾只有幾個小時
    的格不算（不然最大值偏低）。"""
    step = timedelta(hours=1)
    starts = set()
    for t in hours:
        u = t - step
        starts.add(u.replace(hour=u.hour - u.hour % 6, minute=0, second=0, microsecond=0))
    return sorted(s for s in starts if all(s + i * step in hours for i in range(1, 7)))


def backfill_until(
    runs: list[BackfillRun], reports: list[Report], until: datetime | None
) -> list[BackfillRun]:
    """`--until`：起報 ≤ 留下的最後一報的 `generatedAt`（沒有快照用 `until`）。"""
    if until is None:
        return runs
    last = reports[-1].generated if reports else until
    return [r for r in runs if r.run <= last]


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
    past_truth: int = 0  # 格的 `to` 晚於實測截止（同上的算法）


def _gust_slots(
    slots: list[Slot], ref: datetime, obs: list[Obs], res: GustResult, until: datetime | None
) -> None:
    for s in slots:
        if s.end <= ref:
            continue
        b = bucket(lead_hours(s.start, ref))
        if b is None or not s.gusts:
            continue
        if until is not None and s.end > until:
            res.past_truth += 1
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
    reports: list[Report],
    wn3: list[Wn3Run],
    metars: dict[str, list[Obs]],
    until: datetime | None = None,
) -> GustResult:
    res = GustResult({}, {}, set())
    for r in reports:
        for a in r.airports.values():
            _gust_slots(a.slots, r.generated, metars.get(a.icao, []), res, until)
    for w in wn3:
        for icao, slots in w.airports.items():
            _gust_slots(slots, w.run, metars.get(icao, []), res, until)
    return res


def backfill_gust_stats(
    runs: list[BackfillRun], metars: dict[str, list[Obs]], until: datetime | None = None
) -> GustResult:
    """回補四個模式的 (a)：同 `gust_stats`，參考時間是起報（同 WN3 事件檔）。"""
    res = GustResult({}, {}, set())
    for r in runs:
        for icao, slots in r.airports.items():
            _gust_slots(slots, r.run, metars.get(icao, []), res, until)
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
    window: dict[str, WindowStats]  # 「規則燈（定版前）」等 → 統計（窗截到實測截止）
    window_full: dict[str, WindowStats]  # 同上，只算完整窗（沒有格超過實測截止的）
    truth_last: datetime | None = None  # 實測的最後時間＝min(實測截止, 各機場資料最新的時間)
    counts: Counter[str] = field(default_factory=Counter)
    # HD37：班次少的格與窗（上面的子集，另外列）、每個機場的實測來源
    slot_few: dict[str, dict[str, list[Confusion]]] = field(default_factory=dict)
    window_few: dict[str, WindowStats] = field(default_factory=dict)
    window_full_few: dict[str, WindowStats] = field(default_factory=dict)
    sources: dict[str, TruthSource] = field(default_factory=dict)
    classes: Counter[str] = field(default_factory=Counter)  # 逐班重新分類後各類班數
    reclassified: Counter[str] = field(default_factory=Counter)  # 套到各規則的班數
    unknown: Counter[str] = field(default_factory=Counter)  # 看不懂、照舊 other 的狀態


def rule_key(version: str) -> str:
    return f"rule:{version}"


def few_window(window: list[tuple[int, bool | None, bool]]) -> bool:
    """窗的結果是不是靠班次少的格決定：有停飛時停飛的格全是班次少；沒停飛時有實測的格全是班次少
    （拿掉班次少的格，結果會變或沒有實測）。"""
    stopped = [few for _, x, few in window if x]
    judged = [few for _, x, few in window if x is not None]
    return all(stopped) if stopped else bool(judged) and all(judged)


def level_stats(
    reports: list[Report],
    canc: Cancellations,
    airports: Iterable[str],
    cutoff: datetime,
    rate: float,
    count: int,
    until: datetime | None = None,
) -> LevelResult:
    """`until` 是實測截止；每個機場實測的最後時間取它和那個機場資料最新的時間（`cancellations/`
    的 `asOf`、逐班的 `t`）早的那個，晚於它結束的格不算（每格計 `slotPastTruth`；每報每機場的窗
    丟掉那些格，計 `windowTruncated`，一格不剩再計 `windowNoTruth`）。班次少的格與窗另外再記一份
    （`slot_few`、`window_few`）。"""
    scope = sorted(set(airports) & canc.airports)
    keys = (rule_key(BEFORE), rule_key(AFTER), *AI_KEYS)
    lasts = {icao: canc.last(icao, until) for icao in scope}
    known = [t for t in lasts.values() if t is not None]
    res = LevelResult(
        scope,
        {BEFORE: _confusions(), AFTER: _confusions()},
        {k: WindowStats() for k in keys},
        {k: WindowStats() for k in keys},
        max(known) if known else None,
        slot_few={BEFORE: _confusions(), AFTER: _confusions()},
        window_few={k: WindowStats() for k in keys},
        window_full_few={k: WindowStats() for k in keys},
        sources=truth_sources(canc, scope, until),
        classes=canc.classes,
        reclassified=canc.reclassified,
        unknown=canc.unknown,
    )
    for r in reports:
        ver = version_of(r.generated, cutoff)
        for icao in scope:
            a = r.airports.get(icao)
            if a is None:
                continue
            last = lasts[icao]
            window: list[tuple[int, bool | None, bool]] = []
            dropped = 0
            best: str | None = None
            for s in a.slots:
                if s.end <= r.generated:
                    continue
                b = bucket(lead_hours(s.start, r.generated))
                if b is None:
                    continue
                if s.level is not None and (
                    best is None or LEVELS.index(s.level) > LEVELS.index(best)
                ):
                    best = s.level
                if last is None or s.end > last:
                    dropped += 1
                    res.counts["slotPastTruth"] += 1
                    continue
                actual, few = canc.stopped(icao, s.start, s.end, rate, count)
                window.append((b, actual, few))
                if actual is None:
                    res.counts["slotNoTruth"] += 1
                    continue
                if s.level is None:
                    res.counts["slotNoLevel"] += 1
                    continue
                slots = [res.slot, res.slot_few] if few else [res.slot]
                for stats in slots:
                    stats[ver]["risky"][b].add(s.level in RISKY, actual)
                    stats[ver]["high"][b].add(s.level in HIGH, actual)
            if dropped:
                res.counts["windowTruncated"] += 1
            if not window:
                res.counts["windowNoTruth"] += 1
                continue
            if all(x is None for _, x, _ in window):
                # 窗裡的格都沒有航班列（例如逐班紀錄開始之前的報）：不當成「沒停飛」
                res.counts["windowNoFlights"] += 1
                continue
            actual_any = any(x for _, x, _ in window)
            first = next((b for b, x, _ in window if x), None)
            targets = [res.window] if dropped else [res.window, res.window_full]
            if few_window(window):
                targets += [res.window_few] if dropped else [res.window_few, res.window_full_few]
            for stats in targets:
                if best is not None:
                    stats[rule_key(ver)].add(best, actual_any, first)
                for k in AI_KEYS:
                    if a.ai[k] is not None:
                        stats[k].add(a.ai[k], actual_any, first)
            for k in AI_KEYS:
                if a.ai[k] is None:
                    res.counts[f"{k}NotOk"] += 1
    return res


@dataclass
class ModelLevelResult:
    """每格各模式自己的風等級對停飛（HD33a）：模式 → risky／high → 每段。"""

    models: dict[str, dict[str, list[Confusion]]]
    counts: Counter[str] = field(default_factory=Counter)


def model_level_stats(
    reports: list[Report],
    runs: list[BackfillRun],
    canc: Cancellations,
    airports: Iterable[str],
    rate: float,
    count: int,
    until: datetime | None = None,
) -> ModelLevelResult:
    """快照每格 `models[].levels.wind`（8 個模式）與回補四個模式的等級，對同一套停飛實測（每格，
    同 `level_stats` 的每格：每個機場實測的最後時間＝min(`until`, 那個機場資料最新的時間)，晚於它
    結束的格不算；HD37 的逐班實測與班次少照用，班次少的格另計 `slotFew`）。"""
    scope = sorted(set(airports) & canc.airports)
    lasts = {icao: canc.last(icao, until) for icao in scope}
    res = ModelLevelResult({})
    sources: list[tuple[datetime, str, list[Slot]]] = [
        (r.generated, icao, r.airports[icao].slots)
        for r in reports
        for icao in scope
        if icao in r.airports
    ]
    sources += [
        (r.run, icao, r.airports[icao]) for r in runs for icao in scope if icao in r.airports
    ]
    for ref, icao, slots in sources:
        for s in slots:
            if s.end <= ref or not s.winds:
                continue
            b = bucket(lead_hours(s.start, ref))
            if b is None:
                continue
            last = lasts[icao]
            if last is None or s.end > last:
                res.counts["slotPastTruth"] += 1
                continue
            actual, few = canc.stopped(icao, s.start, s.end, rate, count)
            if actual is None:
                res.counts["slotNoTruth"] += 1
                continue
            res.counts["slotFew"] += few
            for m, lv in s.winds.items():
                cs = res.models.setdefault(m, _confusions())
                cs["risky"][b].add(lv in RISKY, actual)
                cs["high"][b].add(lv in HIGH, actual)
    return res


@dataclass
class BackfillResult:
    """HD33a 回補的部分；`Result.backfill` 是 None（沒有回補檔）時報告和以前一樣。"""

    rows: dict[str, int]
    estimated: dict[str, bool]
    runs: list[BackfillRun]
    gust: GustResult
    levels: ModelLevelResult
    excluded_runs: int = 0  # `--until` 排除的（模式, 起報）


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
    past_truth: int = 0  # 模式路徑 `validAt` 晚於實測截止的點
    used: dict[str, int] = field(default_factory=dict)


def _cells() -> list[TrackCell]:
    return [TrackCell() for _ in BUCKETS]


def track_stats(
    tracks: list[ModelTrack], truth: Truth, until: datetime | None = None
) -> TrackResult:
    """`until`：實測截止，`validAt` 晚於它的點不算（主路徑計 `past_truth`；系集成員的誤差也不算，
    離散不用真相，照算）。真相本身在 `truths` 就截好了。"""
    res = TrackResult(truth.label, truth.provisional, {}, {}, {})
    for tr in tracks:
        cells = res.models.setdefault(tr.model, _cells())
        for t, lat, lon in tr.points:
            lead = lead_hours(t, tr.run)
            b = bucket(lead) if lead >= 0 else None
            if b is None:
                continue
            if until is not None and t > until:
                res.past_truth += 1
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
                if until is not None and t > until:
                    continue
                p = truth.at(t)
                if p is not None:
                    errs[b].errors.append(distance_km(lat, lon, *p))
    res.used = dict(truth.used)
    return res


def _clip(track: Track, until: datetime | None) -> Track:
    """真相只用 `validAt` ≤ `until` 的點。"""
    if until is None:
        return track
    return Track(track.name, [p for p in track.points if p[0] <= until])


def truths(
    d: Path,
    event: Event,
    jtwc: Path | None,
    jma: Path | None,
    jma_id: str | None,
    until: datetime | None = None,
) -> list[Truth]:
    out = []
    if jtwc is not None:
        pts = parse_atcf(jtwc.read_text(encoding="utf-8", errors="replace"))
        out.append(Truth(f"JTWC 最佳路徑（{jtwc.name}）", [_clip(Track("jtwc-best", pts), until)]))
    if jma is not None:
        storms = parse_jma_bst(jma.read_text(encoding="utf-8", errors="replace"))
        s = pick_bst(storms, jma_id, storm_name(event))
        out.append(
            Truth(
                f"JMA 最佳路徑（{jma.name}，{s.number} {s.name}）",
                [_clip(Track("jma-best", s.points), until)],
            )
        )
    if not out:
        out.append(
            Truth(
                "暫時真相：現報（JTWC 優先、再 JMA）",
                [_clip(t, until) for t in provisional_tracks(d)],
                provisional=True,
            )
        )
    return out


def tracks_until(
    tracks: list[ModelTrack], reports: list[Report], until: datetime | None
) -> list[ModelTrack]:
    """`--until`：模式路徑只收留下的報用過的起報（同模式取最晚的那個，以前的都收）；WN3 路徑照 WN3
    事件檔的規則（起報 ≤ 時間，再加之後的第一個起報）。"""
    if until is None:
        return tracks
    latest: dict[str, datetime] = {}
    for r in reports:
        for m, run in r.model_runs.items():
            t = parse_time(run)
            if t is not None and (m not in latest or t > latest[m]):
                latest[m] = t
    wn3, _ = select_until(sorted({t.run for t in tracks if t.model == "wn3"}), lambda t: t, until)
    keep = set(wn3)
    return [
        t
        for t in tracks
        if (t.run in keep if t.model == "wn3" else t.model in latest and t.run <= latest[t.model])
    ]


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
    truth_until: datetime
    truth_until_default: bool = True  # 沒給 `--truth-until`，用 events.json 的 `to`
    until: str | None = None  # `--until` 原值
    until_has_next: bool = False  # `--until` 之後有沒有報（有的話已經多算了那一報）
    excluded: dict[str, int] = field(default_factory=dict)  # `--until` 排除的：報、WN3、路徑
    backfill: BackfillResult | None = None  # HD33a 回補（沒有回補檔時 None）


def _gust_rows(
    res: Result, data: dict[str, list[GustCell]], backfill: dict[str, list[GustCell]]
) -> list[tuple[str, list[GustCell], str]]:
    """(a) 各表的列：快照與 WN3 的模式，再接回補的（標「（旁觀・回補）」）；估算陣風標 *。"""
    out = [
        (m, data[m], f"{m}{'*' if m in res.gust.estimated else ''}")
        for m in _ordered(data, MODEL_ORDER)
    ]
    if res.backfill is not None:
        est = res.backfill.gust.estimated
        out += [
            (m, backfill[m], f"{m}{'*' if m in est else ''}{BACKFILL_LABEL}")
            for m in _ordered(backfill, BACKFILL_ORDER)
        ]
    return out


def model_level_lines(res: Result) -> list[str]:
    """(b) 每格各模式的風等級（HD33a，有回補檔才印）。"""
    bf = res.backfill
    assert bf is not None
    c = bf.levels.counts
    L = [
        "",
        "### 每格各模式的風等級（陣風與側風）vs 實際停飛",
        "",
        "每個模式自己的風等級（單一模式的陣風 ≥ 37／48 節、側風 ≥ 27／33 節取較高；"
        "系集只有高或低），"
        "快照 8 個模式用 `models[].levels.wind`、回補的照同一套門檻算；不分版本。每格 "
        "`精確率／召回率（TP/FP/FN/TN）`。晚於實測的最後時間結束的格不算"
        f"（{c['slotPastTruth']} 格次）、結束了但沒有航班的不算（{c['slotNoTruth']} 格次）；"
        f"實測同上（含逐班），算進來的格次裡班次少（< {FEW_FLIGHTS} 班）的 {c['slotFew']} 個。",
        "",
    ]
    rows = []
    models = bf.levels.models
    order = [m for m in _ordered(models, (*MODEL_ORDER, *BACKFILL_ORDER))]
    for kind, name in (("risky", "判中或高"), ("high", "判高")):
        for m in order:
            label = f"{m}{BACKFILL_LABEL}" if m in bf.rows else m
            rows.append(
                [f"{label}{name}"]
                + [
                    f"{_f(x.precision, 2)}／{_f(x.recall, 2)}（{x.tp}/{x.fp}/{x.fn}/{x.tn}）"
                    if x.tp + x.fp + x.fn + x.tn
                    else "-"
                    for x in models[m][kind]
                ]
            )
    L += md_table(["模式", *[f"{b} h" for b in BUCKET_LABELS]], rows) if rows else ["（沒有資料）"]
    return L


def backfill_lines(res: Result) -> list[str]:
    """摘要裡回補的那一行（HD33a，有回補檔才印）。"""
    bf = res.backfill
    assert bf is not None
    parts = [
        f"{m}{'（估算陣風）' if bf.estimated.get(m) else ''} {bf.rows[m]} 行"
        for m in _ordered(bf.rows, BACKFILL_ORDER)
    ]
    runs = sorted({r.run for r in bf.runs})
    span = f"{iso(runs[0])} – {iso(runs[-1])}" if runs else "沒有"
    return [
        f"- 旁觀・回補（Open-Meteo Previous Runs）：{'、'.join(parts)}；起報（格開始時間減 "
        f"`previousDay` 天的 00Z）{span}，`--until` 排除了 {bf.excluded_runs} 個（模式, 起報）"
    ]


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
    bf = res.backfill
    if bf is not None:
        L += [
            "標「（旁觀・回補）」的是 Open-Meteo Previous Runs 回補的模式（HD33a）："
            "起報當成格開始時間減 `previousDay` 天那一天的 00Z，提前時間＝格的 `from` − 起報"
            "（`previousDay` 0–4 → 0–24…96–120）。",
            "",
        ]
    for title, data, bdata in (
        (f"格內最大平均風 ≥ {MIN_WIND_KT} 節", res.gust.windy, bf.gust.windy if bf else {}),
        ("全部的格", res.gust.all, bf.gust.all if bf else {}),
    ):
        L += [f"### {title}", ""]
        rows = []
        for _, cells_, label in _gust_rows(res, data, bdata):
            cells = [c.summary() for c in cells_]
            rows.append(
                [label]
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
    for _, cells_, label in _gust_rows(res, res.gust.all, bf.gust.all if bf else {}):
        cells = []
        for c in cells_:
            s = c.summary()
            parts = [
                f"≥{th}：{s[f'ge{th}']['hit']}/{s[f'ge{th}']['hit'] + s[f'ge{th}']['miss']}"
                f"（{s[f'ge{th}']['false']}）"
                for th in GUST_THRESHOLDS
            ]
            cells.append("、".join(parts) if s["n"] else "-")
        rows.append([label, *cells])
    L += md_table(["模式", *[f"{b} h" for b in BUCKET_LABELS]], rows) if rows else ["（沒有資料）"]
    L += ["", "## (b) 等級：判中或高 vs 實際停飛", ""]
    lv = res.levels
    L += [
        f"停飛定義：一格（UTC 6 小時，出發＋抵達）取消率 ≥ {res.rate:.0%} 或取消 ≥ {res.count} 班。"
        f"機場：{'、'.join(lv.airports) or '（沒有航班資料）'}。航班資料到 "
        f"{iso(res.cancel_as_of) or '-'}，之後結束的格還沒有結果。",
        "",
    ]
    L += truth_source_lines(lv)
    L += [
        "",
        "### 每格（規則燈）",
        "",
        "每格 `精確率／召回率（TP/FP/FN/TN）`。「其中班次少」是同一列裡那格表定（出發＋抵達）"
        f"少於 {FEW_FLIGHTS} 班的子集（規則照判，只是另外列）。",
        "",
    ]
    rows = []
    for kind, name in (("risky", "判中或高"), ("high", "判高")):
        for ver in (BEFORE, AFTER):
            for data, suffix in ((lv.slot, ""), (lv.slot_few, "（其中班次少）")):
                rows.append(
                    [f"規則燈（{ver}）{name}{suffix}"]
                    + [
                        f"{_f(c.precision, 2)}／{_f(c.recall, 2)}（{c.tp}/{c.fp}/{c.fn}/{c.tn}）"
                        if c.tp + c.fp + c.fn + c.tn
                        else "-"
                        for c in data[ver][kind]
                    ]
                )
    L += md_table(["系統", *[f"{b} h" for b in BUCKET_LABELS]], rows)
    c = lv.counts
    per_airport = (
        "；每個機場各自算，見「停飛實測」"
        if any(v.source == FLIGHTS for v in lv.sources.values())
        else ""
    )
    L += [
        "",
        "### 每報每機場（0–120 小時內任一格停飛；AI 的燈是整個機場 5 天一個等級；窗截到實測截止）",
        "",
        "規則燈取這報 0–120 小時的最高等級。提前段的欄是召回率，依窗裡第一個停飛格的提前時間分。"
        f"窗裡結束時間晚於實測的最後時間（{iso(lv.truth_last) or '-'}，實測截止與航班資料"
        f"早的那個{per_airport}）的格丟掉，截短 {c['windowTruncated']} 個窗（其中一格不剩、不算的 "
        f"{c['windowNoTruth']} 個）；"
        "截短後任一格停飛＝有停飛。",
        "",
    ]
    L += window_table(lv.window, lv.window_few)
    L += [
        "",
        "#### 對照：只算完整窗（窗裡沒有任何格超過實測截止）",
        "",
    ]
    L += window_table(lv.window_full, lv.window_full_few)
    if bf is not None:
        L += model_level_lines(res)
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


def window_table(
    stats: dict[str, WindowStats], few: dict[str, WindowStats] | None = None
) -> list[str]:
    """`few` 給了就在每列下面加一列「其中班次少」（結果靠班次少的格決定的窗，見 `few_window`）。"""
    rows = []
    for kind, name in (("risky", "判中或高"), ("high", "判高")):
        for key in (rule_key(BEFORE), rule_key(AFTER), *AI_KEYS):
            label = AI_NAMES.get(key) or f"規則燈（{key.split(':')[1]}）"
            for data, suffix in ((stats, ""), (few, "（其中班次少）")):
                if data is not None:
                    rows.append(_window_row(data[key], kind, f"{label}{name}{suffix}"))
    return md_table(
        ["系統", "TP", "FP", "FN", "TN", "精確率", "召回率", *[f"{b} h" for b in BUCKET_LABELS]],
        rows,
    )


def _window_row(w: WindowStats, kind: str, label: str) -> list[str]:
    c = w.risky if kind == "risky" else w.high
    by = w.recall_risky if kind == "risky" else w.recall_high
    return [
        label,
        str(c.tp),
        str(c.fp),
        str(c.fn),
        str(c.tn),
        _f(c.precision, 2),
        _f(c.recall, 2),
        *[_f(x.recall, 2) for x in by],
    ]


def truth_source_lines(lv: LevelResult) -> list[str]:
    """(b) 的「停飛實測」：每個機場用哪個來源、算到哪裡、格數與各類班數；逐班的重新分類。"""
    flights = [k for k, v in lv.sources.items() if v.source == FLIGHTS]
    L = [
        "### 停飛實測",
        "",
        "`cancellations/` 有的機場用它（每 6 小時的取消統計，和定版以來一致）；沒有的機場用逐班紀錄"
        f"`flights/`（`source: {FLIGHT_SOURCE}`，同一班取最新一行、依表定時間歸格，停飛規則一樣）。"
        "每個機場實測的最後時間是資料最新的時間（統計是那個機場的 `asOf`、"
        "逐班是整批 TDX 最新的 `t`）和實測截止早的那個。"
        f"格數、班數只算那之前結束的格；班次少＝表定（出發＋抵達）少於 {FEW_FLIGHTS} 班。",
        "",
    ]
    rows = []
    for icao, v in lv.sources.items():
        name = "取消統計" if v.source == CANCELLATIONS else f"逐班（{FLIGHT_SOURCE}）"
        rows.append(
            [
                icao,
                name,
                iso(v.last) or "-",
                iso(v.used) or "-",
                str(v.slots),
                str(v.few),
                str(v.flights),
                str(v.cancelled),
                str(v.delayed),
                "-" if v.diverted is None else str(v.diverted),
            ]
        )
    L += md_table(
        ["機場", "來源", "資料最新", "實測算到", "格數", "班次少", "班數", "取消", "延誤", "轉降"],
        rows,
    )
    if not flights:
        return L
    rc, cl = lv.reclassified, lv.classes
    L += [
        "",
        f"逐班重新分類（只在報告裡，不改存檔；{'、'.join(flights)}）：原本 `class: other` 的"
        f"`加班` → 正常 {rc['extra']} 班、`轉降` → 轉降 {rc['diverted']} 班（不算取消）、"
        f"`預計HH:MM到站／離站` → 延誤 {rc['estDelayed']}／正常 {rc['estOnTime']} 班（預計比表定晚 "
        f"{cancellations.DELAY_MINUTES} 分鐘以上算延誤）。各類："
        + "、".join(f"{FLIGHT_CLASS_NAMES[k]} {cl[k]}" for k in FLIGHT_CLASSES)
        + " 班。",
    ]
    if lv.unknown:
        top = "、".join(f"`{k or '（空白）'}` {n}" for k, n in lv.unknown.most_common(10))
        L += ["", f"看不懂、照舊 other 的狀態（前 10 種）：{top}。"]
    return L


def cutoff_lines(res: Result) -> list[str]:
    """摘要最上面：兩個截止（HD36）與各自排除了多少。"""
    reps, ex, c = res.reports, res.excluded, res.levels.counts
    last = reps[-1].generated if reps else None
    if res.until is None:
        note = "沒給 `--until`，全部的報"
    elif res.until_has_next:
        note = f"`--until` {res.until} 之後的第一報"
    else:
        note = f"`--until` {res.until}；時間之後還沒有報"
    t = res.truth_until
    how = "預設＝events.json 的 to 隔天 00:00" if res.truth_until_default else "`--truth-until`"
    past_track = res.tracks[0].past_truth if res.tracks else 0
    return [
        f"- 預報算到：{iso(last) or '沒有快照'}（台北 {_tw(last) if last else '-'}；{note}）；"
        f"`--until` 排除了 {ex.get('reports', 0)} 報、WN3 {ex.get('wn3', 0)} 報、"
        f"路徑 {ex.get('tracks', 0)} 份",
        f"- 實測到：{iso(t)}（台北 {_tw(t)}；{how}）；航班資料到 {iso(res.cancel_as_of) or '-'}，"
        f"(b) 實際算到 {iso(res.levels.truth_last) or '-'}"
        + (
            "（每個機場各自算到哪裡見 (b)「停飛實測」）"
            if any(v.source == FLIGHTS for v in res.levels.sources.values())
            else ""
        ),
        f"- 超過實測截止、仍然沒有實測的（不算命中也不算誤報）：(a) 陣風 {res.gust.past_truth} 格、"
        f"(b) 每格 {c['slotPastTruth']} 格、每報每機場截短 {c['windowTruncated']} 個窗"
        f"（截短後沒有實測 {c['windowNoTruth']} 筆）、(c) 路徑 {past_track} 點",
    ]


def summary_lines(res: Result) -> list[str]:
    e, reps = res.event, res.reports
    span = f"{iso(reps[0].generated)} – {iso(reps[-1].generated)}" if reps else "沒有快照"
    versions = Counter(version_of(r.generated, res.cutoff) for r in reps)
    truth = "；".join(t.label for t in res.tracks)
    return [
        "## 摘要",
        "",
        *cutoff_lines(res),
        f"- 事件：{e.id} {e.name}，期間（台灣日期）{e.start}～{e.end}，{len(e.airports)} 個機場",
        f"- 快照：{len(reps)} 報（{span}）",
        f"- 版本切點：{iso(res.cutoff)}（台北 {_tw(res.cutoff)}）；定版前 {versions[BEFORE]} 報、"
        f"定版後 {versions[AFTER]} 報",
        f"- 路徑真相：{truth}",
        f"- 停飛定義：取消率 ≥ {res.rate:.0%} 或取消 ≥ {res.count} 班",
        scope_line(res.levels),
        *(backfill_lines(res) if res.backfill is not None else []),
    ]


def scope_line(lv: LevelResult) -> str:
    """(b) 的範圍：哪些機場、各用哪個來源（HD37 起沒有取消統計的機場用逐班紀錄）。"""
    by: dict[str, list[str]] = defaultdict(list)
    for icao, v in lv.sources.items():
        by[v.source].append(icao)
    parts = [f"取消統計 {'、'.join(by[CANCELLATIONS]) or '沒有'}"]
    if by[FLIGHTS]:
        parts.append(f"逐班（{FLIGHT_SOURCE}）{'、'.join(by[FLIGHTS])}")
    return (
        f"- (b) 停飛實測的範圍：{len(lv.airports)} 個機場（{'；'.join(parts)}）；"
        f"表定少於 {FEW_FLIGHTS} 班的格標「班次少」另外列"
    )


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
        "格是機場 × 格、每報各算；超過實測截止的不算命中也不算誤報。",
        "",
    ]
    rows = [
        [
            "(a) 陣風",
            f"格內沒有 METAR 觀測 {res.gust.no_metar} 格",
            f"{res.gust.past_truth} 格",
            "-",
            "-",
        ],
        [
            "(b) 每格",
            f"結束了但沒有航班 {c['slotNoTruth']} 格、規則燈 unknown {c['slotNoLevel']} 格",
            f"{c['slotPastTruth']} 格",
            "-",
            "-",
        ],
        [
            "(b) 每報每機場",
            f"AI 不是 ok（skipped／error／沒有）：Claude {c['claudeNotOk']}、"
            f"Gemini {c['geminiNotOk']} 筆"
            + (
                f"；窗裡的格都沒有航班列（逐班紀錄開始之前的報）{c['windowNoFlights']} 個"
                if c["windowNoFlights"]
                else ""
            ),
            "（見截短）",
            f"{c['windowTruncated']} 個",
            f"{c['windowNoTruth']} 筆",
        ],
    ]
    for tr in res.tracks:
        rows.append(
            [
                f"(c) 路徑（對 {tr.label}）",
                f"真相內插不到 {tr.no_truth} 點",
                f"{tr.past_truth} 點",
                "-",
                "-",
            ]
        )
    L += md_table(["類別", "跳過", "超過實測截止", "截短的窗", "截短後沒有實測"], rows)
    L += [
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
    out = {
        "event": {"id": res.event.id, "name": res.event.name, "airports": list(res.event.airports)},
        "buckets": list(BUCKET_LABELS),
        "cutoff": iso(res.cutoff),
        "until": res.until,
        "untilHasNext": res.until_has_next,
        "lastReport": iso(res.reports[-1].generated) if res.reports else None,
        "excludedByUntil": res.excluded,
        "truthUntil": iso(res.truth_until),
        "truthUntilDefault": res.truth_until_default,
        "stopDefinition": {"rate": res.rate, "count": res.count},
        "gust": {
            "estimated": sorted(res.gust.estimated),
            "all": gust(res.gust.all),
            f"windGe{MIN_WIND_KT}": gust(res.gust.windy),
            "noMetar": res.gust.no_metar,
            "pastTruth": res.gust.past_truth,
        },
        "levels": {
            "airports": lv.airports,
            "cancellationsAsOf": iso(res.cancel_as_of),
            "slot": {
                ver: {k: [c.summary() for c in cs] for k, cs in v.items()}
                for ver, v in lv.slot.items()
            },
            "truthLast": iso(lv.truth_last),
            "window": {k: w.summary() for k, w in lv.window.items()},
            "windowComplete": {k: w.summary() for k, w in lv.window_full.items()},
            "skipped": {"slotPastTruth": 0, "windowTruncated": 0, "windowNoTruth": 0}
            | dict(lv.counts),
            "fewFlights": FEW_FLIGHTS,
            "slotFew": {
                ver: {k: [c.summary() for c in cs] for k, cs in v.items()}
                for ver, v in lv.slot_few.items()
            },
            "windowFew": {k: w.summary() for k, w in lv.window_few.items()},
            "windowCompleteFew": {k: w.summary() for k, w in lv.window_full_few.items()},
            "truthSources": {k: v.summary() for k, v in lv.sources.items()},
            "flightClasses": {k: lv.classes[k] for k in FLIGHT_CLASSES},
            "reclassified": {
                k: lv.reclassified[k] for k in ("extra", "diverted", "estDelayed", "estOnTime")
            },
            "unknownStatuses": [[k, n] for k, n in lv.unknown.most_common()],
        },
        "tracks": [
            {
                "truth": t.label,
                "provisional": t.provisional,
                "models": {m: [c.summary() for c in cs] for m, cs in t.models.items()},
                "members": {m: [c.summary() for c in cs] for m, cs in t.members.items()},
                "spread": {m: [c.summary() for c in cs] for m, cs in t.spread.items()},
                "noTruth": t.no_truth,
                "pastTruth": t.past_truth,
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
    if (bf := res.backfill) is not None:
        out["backfill"] = {
            "source": "open-meteo-previous-runs",
            "rows": bf.rows,
            "gustEstimated": bf.estimated,
            "runs": sorted({iso(r.run) for r in bf.runs}),
            "excludedRunsByUntil": bf.excluded_runs,
            "gust": {
                "estimated": sorted(bf.gust.estimated),
                "all": gust(bf.gust.all),
                f"windGe{MIN_WIND_KT}": gust(bf.gust.windy),
                "noMetar": bf.gust.no_metar,
                "pastTruth": bf.gust.past_truth,
            },
            "modelLevels": {
                m: {k: [c.summary() for c in cs] for k, cs in v.items()}
                for m, v in bf.levels.models.items()
            },
            "modelLevelsSkipped": dict(bf.levels.counts),
        }
    return out


def build_result(
    archive: Path,
    event: Event,
    cutoff: datetime,
    rate: float,
    count: int,
    jtwc: Path | None = None,
    jma: Path | None = None,
    jma_id: str | None = None,
    until: str | None = None,
    truth_until: datetime | None = None,
    airports_path: Path = ROOT / "airports.json",
) -> Result:
    """`until` 是 `--until` 原值（`parse_cli_time` 看得懂的）；`truth_until` 不給＝`events.json` 的
    `to` 隔天 00:00（台灣）。`airports_path` 只在有回補檔時讀（門檻與跑道，HD33a）。"""
    history = archive / "history"
    d = history / "events" / event.id
    until_at = parse_cli_time(until) if until is not None else None
    t_until = truth_until or default_truth_until(event)
    all_reports = load_reports(d, event.airports, history)
    reports, has_next = select_until(all_reports, lambda r: r.generated, until_at)
    all_wn3 = load_wn3(d, event.airports)
    wn3, _ = select_until(all_wn3, lambda w: w.run, until_at)
    metars = load_metars(d, t_until)
    canc = load_cancellations(history)
    load_flights(d, canc, event.airports, airport_tz(ROOT / "airports.json"), t_until)
    all_tracks = load_tracks(d)
    track_runs = tracks_until(all_tracks, reports, until_at)
    span, hours = metar_hours(metars, event.airports)
    truth_list = truths(d, event, jtwc, jma, jma_id, t_until)
    backfill = None
    if (bf_data := load_backfill(d, event.airports)) is not None:
        sites = {a.icao: a for a in load_airports(airports_path)}
        all_runs = backfill_runs(bf_data, sites, all_reports)
        bf_runs = backfill_until(all_runs, reports, until_at)
        backfill = BackfillResult(
            rows=bf_data.rows,
            estimated=bf_data.estimated,
            runs=bf_runs,
            gust=backfill_gust_stats(bf_runs, metars, t_until),
            levels=model_level_stats(reports, bf_runs, canc, event.airports, rate, count, t_until),
            excluded_runs=len({(r.model, r.run) for r in all_runs})
            - len({(r.model, r.run) for r in bf_runs}),
        )
    return Result(
        event=event,
        reports=reports,
        cutoff=cutoff,
        rate=rate,
        count=count,
        gust=gust_stats(reports, wn3, metars, t_until),
        levels=level_stats(reports, canc, event.airports, cutoff, rate, count, t_until),
        tracks=[track_stats(track_runs, t, t_until) for t in truth_list],
        track_runs=track_runs,
        metar_span=span,
        metar_hours=hours,
        cancel_as_of=canc.as_of,
        truth_until=t_until,
        truth_until_default=truth_until is None,
        until=until,
        until_has_next=has_next,
        excluded={
            "reports": len(all_reports) - len(reports),
            "wn3": len(all_wn3) - len(wn3),
            "tracks": len(all_tracks) - len(track_runs),
        },
        backfill=backfill,
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
    ap.add_argument(
        "--until",
        help="預報算到這個時間之後的第一報（例如 2026-10-25T14:00+08:00）；不給＝全部的報",
    )
    ap.add_argument(
        "--truth-until",
        help="實測只用到這個時間（例如 2026-10-26T24:00+08:00）；"
        "不給＝events.json 的 to 隔天 00:00（台灣）",
    )
    ap.add_argument(
        "--airports",
        type=Path,
        default=ROOT / "airports.json",
        help="門檻與跑道（只在有回補檔 backfill/openmeteo-*.jsonl 時用，HD33a）",
    )
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
    truth_until = None
    for flag, value in (("--until", args.until), ("--truth-until", args.truth_until)):
        try:
            t = parse_cli_time(value) if value is not None else None
        except ValueError as ex:
            print(f"{flag}：{ex}", file=sys.stderr)
            return 1
        if flag == "--truth-until":
            truth_until = t
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
            args.until,
            truth_until,
            args.airports,
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
