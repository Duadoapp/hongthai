"""航班狀態 → 每機場、每個 UTC 6 小時格的取消／延誤統計（純函式，不連網；`store` 寫檔）。

輸入是 `sources/flights.py` 各機場 `fetch_*` 的回傳（以前存成 `history/flights/*.json.gz`
的那個結構，多出的 `airport`、`fetchedAt` 欄位不影響）＋機場時區＋現在時間。輸出每格一筆：

    {"airport": "RCTP", "from": "…T06:00:00Z", "to": "…T12:00:00Z", "asOf": "…",
     "dep": {"total": 118, "cancelled": 2, "delayed": 7, "other": 0}, "arr": {…}}

規則：
- 依**表定**時間歸格（和 `latest.json` 一樣對齊 00／06／12／18Z）；表定時間是當地時間，
  用 `airports.json` 的 `tz` 轉 UTC。看不出方向或表定時間的那筆無法歸格，跳過並印 log
- 出發（`dep`）、抵達（`arr`）分開算；不含貨機（香港 `cargo=true` 的組、松山
  `AirDrType`／`AirArType` 是 `CGO`／`CARGO`／`FRT` 的；桃園、高雄、澳門的資料沒有貨機）
- 一班只算一次：
  - 香港：`flight` 陣列多個班號（共掛）是一班；以第一個班號＋表定時間去重
    （昨天、今天兩次查詢會重疊）
  - 桃園：共掛班號是**分開的列**，只有實際營運那一列有機型（`aircraft` 是機型或 `-`），
    掛名的列機型空白。同方向、同表定時間、同航點的列裡，有營運列時掛名的列不算；
    另外以班號＋表定時間去重（同一筆出現在多個航廈時）
  - 松山：共掛是分開的列，`Master` 是 `1` 的是營運班號，`2`、`3` 是掛名的，不算
  - 高雄、澳門：沒看到共掛的列（同時同航點的兩筆是不同的飛機），以班號＋表定時間去重
  - 同一班出現兩次時留最嚴重的分類
- 分類（互斥，一班只進一類，`total` 包含全部）：
  - `cancelled`：狀態表示取消
  - `delayed`：狀態表示延誤，**或**預計／實際時間比表定時間晚 60 分鐘以上（取消的不重複算）
  - `other`：對照表沒列的狀態（仍算進 `total`；每種字串在 log 印一次）
  - 其他（狀態正常或還沒有狀態）不另外計
- 沒有日期的預計／實際時間（松山、高雄、澳門、香港沒帶日期的）：
  放在表定時間前 6 小時到後 18 小時之間
- 高雄的資料沒有日期：預設是當地今天；有表定時間在現在 2 小時以後、狀態已經是
  「離站」「抵達」的班機時，表示清單還沒換日，當成昨天

狀態對照表：從 `data` 分支 2026-10-18 05:06Z 的快照整理（`git fetch origin data` 後
`git show data:history/flights/2026-10-18/<機場>-0506.json.gz | gunzip`），
2026-10-18 08:5xZ 實際抓一次補上新看到的用語。比對前去掉空白、轉大寫。
標「＊」的是兩次都沒看到、依同一來源的用語預先列入的。台灣三個來源另有通用規則：
開頭是「取消」→ 取消，開頭是「延遲」「延誤」→ 延誤。

- 桃園 `status`
  - 取消：取消CANCELLED
  - 延誤：延遲DELAY
  - 正常：準時ON TIME、出發DEPARTED、已到ARRIVED、時間更改SCHEDULE CHANGE、空白
  - 時間：`estimatedDate`＋`estimatedTime`
- 松山 `AirFlyStatus`
  - 取消：＊取消Cancelled
  - 延誤：延誤Delayed
  - 正常：準時OnTime、已飛Departed、已到Arrived、報到CheckIn、登機Boarding、提早Early、空白
  - 時間：`RealDepartureTime`／`RealArrivalTime`（`HHMM` 或 `HH:MM`）
- 高雄 `airFlyStatus`
  - 取消：＊取消
  - 延誤：延遲
  - 正常：準時、離站、抵達、登機、空白
  - 時間：`realTime`
- 香港 `status`（時間從狀態解析）
  - 取消：Cancelled
  - 延誤：＊Delayed
  - 正常：空白（還沒有狀態）、`Dep`／`Est at`／`At gate`／`Landed HH:MM`（可帶
    `(dd/mm/yyyy)`）、Boarding Soon、Boarding、Final Call、Gate Closed
- 澳門 `status`（時間從狀態解析）
  - 取消：CANCELLED、Cancelled
  - 延誤：`DELAY UNTIL HH:MM`、＊DELAYED
  - 正常：`0`／空白（還沒有狀態）、`TOOK OFF AT`／`Landed at`／`Expected at`／
    `RESCHEDULE HH:MM`、BOARDING、GATE CLOSED、CHECK-IN CLOSED、`CHECK-IN <櫃台> OPEN`
    （可帶 `AT HH:MM`，那是開櫃時間，不算班機時間）
  - 狀態可能是兩段用多個空白接起來（`DELAY UNTIL 17:45␣␣␣…CHECK-IN D12-D14 OPEN`），
    每段各自比對，取最嚴重的一類
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .timeutil import SLOT_HOURS, floor_6h, iso

log = logging.getLogger("hongthai")

OK, OTHER, DELAYED, CANCELLED = "ok", "other", "delayed", "cancelled"
SEVERITY = {OK: 0, OTHER: 1, DELAYED: 2, CANCELLED: 3}
DELAY_MINUTES = 60
CARGO_TYPES = {"CGO", "CARGO", "FRT"}


@dataclass(frozen=True)
class Flight:
    direction: str  # "dep"／"arr"
    key: tuple  # 去重用
    scheduled: datetime  # 表定時間（帶時區）
    category: str  # OK／OTHER／DELAYED／CANCELLED
    status: str  # 原始狀態字串


# ---- 狀態對照表 ----


def _norm(s: object) -> str:
    return re.sub(r"\s+", "", str(s or "")).upper()


TPE_STATUS = {
    "取消CANCELLED": CANCELLED,
    "延遲DELAY": DELAYED,
    "準時ONTIME": OK,
    "出發DEPARTED": OK,
    "已到ARRIVED": OK,
    "時間更改SCHEDULECHANGE": OK,
    "": OK,
}
TSA_STATUS = {
    "取消CANCELLED": CANCELLED,
    "延誤DELAYED": DELAYED,
    "準時ONTIME": OK,
    "已飛DEPARTED": OK,
    "已到ARRIVED": OK,
    "報到CHECKIN": OK,
    "登機BOARDING": OK,
    "提早EARLY": OK,
    "": OK,
}
KHH_STATUS = {
    "取消": CANCELLED,
    "延遲": DELAYED,
    "準時": OK,
    "離站": OK,
    "抵達": OK,
    "登機": OK,
    "": OK,
}
KHH_FINAL = {"離站", "抵達"}

_T = r"(\d{1,2}:\d{2})"
_D = r"(?: \((\d{1,2}/\d{1,2}/\d{4})\))?"
# (樣式, 分類)；樣式裡第一個群組是時間、第二個（如果有）是 dd/mm/yyyy
HKG_STATUS = [
    (r"", OK),
    (r"CANCELLED", CANCELLED),
    (r"DELAYED", DELAYED),
    (rf"(?:DEP|EST AT|AT GATE|LANDED) {_T}{_D}", OK),
    (r"BOARDING SOON|BOARDING|FINAL CALL|GATE CLOSED", OK),
]
MFM_STATUS = [
    (r"0?", OK),
    (r"CANCELL?ED", CANCELLED),
    (rf"DELAY UNTIL {_T}", DELAYED),
    (r"DELAYED", DELAYED),
    (rf"(?:TOOK OFF AT|LANDED AT|EXPECTED AT|RESCHEDULE) {_T}", OK),
    (r"BOARDING|GATE CLOSED|CHECK-IN CLOSED|CHECK-IN \S+ OPEN(?: AT \d{1,2}:\d{2})?", OK),
]


def _lookup(table: dict[str, str], status: object) -> str:
    """台灣三個來源：先查表，查不到再看開頭的中文。"""
    s = _norm(status)
    if s in table:
        return table[s]
    if s.startswith("取消"):
        return CANCELLED
    if s.startswith(("延遲", "延誤")):
        return DELAYED
    return OTHER


def _match(rules: list, status: str) -> tuple[str, str | None, date | None]:
    """香港、澳門：回傳（分類, 狀態裡的 HH:MM, 狀態裡的日期）。"""
    s = re.sub(r"\s+", " ", status.strip()).upper()
    for pattern, cat in rules:
        m = re.fullmatch(pattern, s)
        if m:
            groups = m.groups()
            hhmm = groups[0] if groups else None
            on = groups[1] if len(groups) > 1 else None
            return cat, hhmm, datetime.strptime(on, "%d/%m/%Y").date() if on else None
    return OTHER, None, None


# ---- 時間 ----


def _clock(s: object) -> time | None:
    m = re.fullmatch(r"(\d{1,2}):?(\d{2})(?::\d{2})?", str(s or "").strip())
    if not m or int(m[1]) > 23 or int(m[2]) > 59:
        return None
    return time(int(m[1]), int(m[2]))


def _at(day: date, clock: time | None, tz: ZoneInfo) -> datetime | None:
    return datetime.combine(day, clock, tzinfo=tz) if clock else None


def _near(sched: datetime, clock: time | None) -> datetime | None:
    """沒有日期的預計／實際時間：放在表定時間前 6 小時到後 18 小時之間。"""
    t = _at(sched.date(), clock, sched.tzinfo)
    if t is None:
        return None
    if t < sched - timedelta(hours=6):
        t += timedelta(days=1)
    elif t >= sched + timedelta(hours=18):
        t -= timedelta(days=1)
    return t


def _nearest_year(month: int, day: int, ref: date) -> date:
    """只有月日：取最接近 `ref` 的那一年（跨年用）。"""
    cands = []
    for y in (ref.year - 1, ref.year, ref.year + 1):
        try:
            cands.append(date(y, month, day))
        except ValueError:  # 2 月 29 日
            continue
    return min(cands, key=lambda d: abs((d - ref).days))


def _category(status_cat: str, sched: datetime, actual: datetime | None) -> str:
    if status_cat == OK and actual is not None:
        if actual - sched >= timedelta(minutes=DELAY_MINUTES):
            return DELAYED
    return status_cat


# ---- 各來源 ----


def _tpe(payload: dict, tz: ZoneInfo, now: datetime) -> Iterator[Flight | None]:
    rows = payload.get("rows") or []

    def sched_of(r: dict) -> datetime | None:
        try:
            d = datetime.strptime(str(r.get("scheduledDate", "")).strip(), "%Y/%m/%d").date()
        except ValueError:
            return None
        return _at(d, _clock(r.get("scheduledTime")), tz)

    operated = {
        (r.get("kind"), sched_of(r), r.get("airportCode"))
        for r in rows
        if str(r.get("aircraft") or "").strip()
    }
    for r in rows:
        direction = {"D": "dep", "A": "arr"}.get(str(r.get("kind", "")).strip())
        sched = sched_of(r)
        if direction is None or sched is None:
            yield None
            continue
        if not str(r.get("aircraft") or "").strip() and (
            (r.get("kind"), sched, r.get("airportCode")) in operated
        ):
            continue  # 共掛的掛名列
        actual = None
        try:
            est_day = datetime.strptime(str(r.get("estimatedDate", "")).strip(), "%Y/%m/%d").date()
            actual = _at(est_day, _clock(r.get("estimatedTime")), tz)
        except ValueError:
            pass
        status = str(r.get("status") or "")
        cat = _category(_lookup(TPE_STATUS, status), sched, actual)
        flight_no = f"{r.get('airlineCode', '')}{str(r.get('flightNo', '')).strip()}"
        yield Flight(direction, (direction, flight_no, sched), sched, cat, status)


def _tsa(payload: dict, tz: ZoneInfo, now: datetime) -> Iterator[Flight | None]:
    today = now.astimezone(tz).date()
    for feed, rows in payload.items():
        if not isinstance(rows, list):
            continue
        direction = "dep" if feed.endswith("Departure") else "arr"
        field = "Departure" if direction == "dep" else "Arrival"
        kind_field = "AirDrType" if direction == "dep" else "AirArType"
        for r in rows:
            if str(r.get("Master") or "1").strip() not in ("", "1"):
                continue  # 共掛的掛名班號
            if str(r.get(kind_field) or "").strip().upper() in CARGO_TYPES:
                continue
            m = re.fullmatch(r"(\d{2})(\d{2})", str(r.get("AirFlyDate") or "").strip())
            if not m:
                yield None
                continue
            try:
                day = _nearest_year(int(m[1]), int(m[2]), today)
            except ValueError:
                yield None
                continue
            sched = _at(day, _clock(r.get(f"Expect{field}Time")), tz)
            if sched is None:
                yield None
                continue
            actual = _near(sched, _clock(r.get(f"Real{field}Time")))
            status = str(r.get("AirFlyStatus") or "")
            cat = _category(_lookup(TSA_STATUS, status), sched, actual)
            airline = r.get("AirLineIATA") or r.get("AirLineCode") or ""
            flight_no = f"{airline}{r.get('AirLineNum', '')}"
            yield Flight(direction, (direction, flight_no, sched), sched, cat, status)


def khh_list_date(payload: dict, now_local: datetime) -> date:
    """高雄清單是哪一天的：預設今天；有晚於現在 2 小時的班機已經離站／抵達，就是昨天的。"""
    today = now_local.date()
    later = now_local + timedelta(hours=2)
    for rows in payload.values():
        for r in rows if isinstance(rows, list) else ():
            sched = _at(today, _clock(r.get("expectTime")), now_local.tzinfo)
            if sched and sched > later and _norm(r.get("airFlyStatus")) in KHH_FINAL:
                return today - timedelta(days=1)
    return today


def _khh(payload: dict, tz: ZoneInfo, now: datetime) -> Iterator[Flight | None]:
    day = khh_list_date(payload, now.astimezone(tz))
    for feed, rows in payload.items():
        if not isinstance(rows, list):
            continue
        direction = "dep" if feed.endswith("Departure") else "arr"
        for r in rows:
            sched = _at(day, _clock(r.get("expectTime")), tz)
            if sched is None:
                yield None
                continue
            actual = _near(sched, _clock(r.get("realTime")))
            status = str(r.get("airFlyStatus") or "")
            cat = _category(_lookup(KHH_STATUS, status), sched, actual)
            yield Flight(direction, (direction, r.get("airLineNum"), sched), sched, cat, status)


def _hkg(payload: dict, tz: ZoneInfo, now: datetime) -> Iterator[Flight | None]:
    for feed, direction in (("departure", "dep"), ("arrival", "arr")):
        for group in payload.get(feed) or []:
            if group.get("cargo"):
                continue
            try:
                day = date.fromisoformat(str(group.get("date")))
            except ValueError:
                yield None
                continue
            for item in group.get("list") or []:
                sched = _at(day, _clock(item.get("time")), tz)
                if sched is None:
                    yield None
                    continue
                status = str(item.get("status") or "")
                cat, hhmm, on = _match(HKG_STATUS, status)
                clock = _clock(hhmm)
                actual = _at(on, clock, tz) if on else _near(sched, clock)
                nos = [str(f.get("no", "")).replace(" ", "") for f in item.get("flight") or []]
                key = (direction, nos[0] if nos else "", sched)
                yield Flight(direction, key, sched, _category(cat, sched, actual), status)


def _mfm_status(status: str) -> tuple[str, str | None]:
    parts = [p for p in re.split(r"\s{2,}", status.strip()) if p] or [""]
    results = [_match(MFM_STATUS, p) for p in parts]
    cat = max((c for c, _, _ in results), key=SEVERITY.__getitem__)
    hhmm = next((t for _, t, _ in results if t), None)
    return cat, hhmm


def _mfm(payload: dict, tz: ZoneInfo, now: datetime) -> Iterator[Flight | None]:
    today = now.astimezone(tz).date()
    for feed, direction in (("departure", "dep"), ("arrival", "arr")):
        for r in payload.get(feed) or []:
            ref = today
            try:
                ref = datetime.strptime(str(r.get("date", "")).strip(), "%d-%m-%Y").date()
            except ValueError:
                pass
            when = str(r.get("time", "")).strip()
            m = re.fullmatch(r"(?:(\d{1,2})-(\d{1,2}) )?(\d{1,2}:\d{2})", when)
            if not m:
                yield None
                continue
            try:
                day = _nearest_year(int(m[2]), int(m[1]), ref) if m[1] else ref
            except ValueError:
                yield None
                continue
            sched = _at(day, _clock(m[3]), tz)
            if sched is None:
                yield None
                continue
            status = str(r.get("status") or "")
            cat, hhmm = _mfm_status(status)
            actual = _near(sched, _clock(hhmm))
            key = (direction, r.get("flightNo"), sched)
            yield Flight(direction, key, sched, _category(cat, sched, actual), status)


PARSERS: dict[str, Callable[[dict, ZoneInfo, datetime], Iterable[Flight | None]]] = {
    "RCTP": _tpe,
    "RCSS": _tsa,
    "RCKH": _khh,
    "VHHH": _hkg,
    "VMMC": _mfm,
}


# ---- 統計 ----


def flights_of(airport: str, payload: dict, tz: str, now: datetime) -> list[Flight]:
    """解析＋去重（同一個 key 留最嚴重的分類）。"""
    parser = PARSERS.get(airport)
    if parser is None:
        raise KeyError(f"沒有 {airport} 的航班解析")
    seen: dict[tuple, Flight] = {}
    skipped = 0
    for f in parser(payload, ZoneInfo(tz), now):
        if f is None:
            skipped += 1
        elif f.key not in seen or SEVERITY[f.category] > SEVERITY[seen[f.key].category]:
            seen[f.key] = f
    if skipped:
        log.warning("航班 %s：%d 筆看不出方向或表定時間，跳過", airport, skipped)
    return list(seen.values())


def _zero() -> dict[str, int]:
    return {"total": 0, CANCELLED: 0, DELAYED: 0, OTHER: 0}


def airport_stats(airport: str, payload: dict, tz: str, now: datetime) -> list[dict]:
    """一個機場的原始資料 → 每個有班機的 UTC 6 小時格一筆統計，依 `from` 排序。"""
    flights = flights_of(airport, payload, tz, now)
    unknown = Counter(f.status for f in flights if f.category == OTHER)
    for status, n in sorted(unknown.items()):
        log.warning("航班 %s 看不懂的狀態 %r（%d 班，算進 other）", airport, status, n)
    slots: dict[datetime, dict[str, dict[str, int]]] = defaultdict(
        lambda: {"dep": _zero(), "arr": _zero()}
    )
    for f in flights:
        counts = slots[floor_6h(f.scheduled)][f.direction]
        counts["total"] += 1
        if f.category != OK:
            counts[f.category] += 1
    step = timedelta(hours=SLOT_HOURS)
    return [
        {
            "airport": airport,
            "from": iso(start),
            "to": iso(start + step),
            "asOf": iso(now),
            "dep": slots[start]["dep"],
            "arr": slots[start]["arr"],
        }
        for start in sorted(slots)
    ]


def _total(row: dict) -> int:
    return row["dep"]["total"] + row["arr"]["total"]


def merge(existing: list[dict], new: list[dict]) -> list[dict]:
    """同 `airport`＋`from`：新的覆蓋舊的，但新的 `dep.total + arr.total` 比舊的少就留舊的。"""
    rows = {(r["airport"], r["from"]): r for r in existing}
    for r in new:
        key = (r["airport"], r["from"])
        if key not in rows or _total(r) >= _total(rows[key]):
            rows[key] = r
    return sorted(rows.values(), key=lambda r: (r["airport"], r["from"]))


def store(history: Path, stats: list[dict]) -> list[Path]:
    """依格的 UTC 日期合併進 `history/cancellations/<YYYY-MM-DD>.json`；回傳寫了哪些檔。"""
    by_day: dict[str, list[dict]] = defaultdict(list)
    for r in stats:
        by_day[r["from"][:10]].append(r)
    written = []
    for day, rows in sorted(by_day.items()):
        path = history / "cancellations" / f"{day}.json"
        old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        path.parent.mkdir(parents=True, exist_ok=True)
        body = json.dumps(merge(old, rows), ensure_ascii=False, indent=2)
        path.write_text(body + "\n", encoding="utf-8")
        written.append(path)
    return written
