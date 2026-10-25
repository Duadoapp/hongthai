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
  - `diverted`：狀態表示轉降（HD38；以前算 `other`，舊檔沒有這個鍵，讀的時候當 0）
  - `delayed`：狀態表示延誤，**或**預計／實際時間比表定時間晚 60 分鐘以上（取消的不重複算）
  - `other`：對照表沒列的狀態（仍算進 `total`；每種字串在 log 印一次，並合併進
    `history/cancellations/unknown-statuses.json`，見 `store_unknown`）
  - 其他（狀態正常或還沒有狀態）不另外計
- 沒有日期的預計／實際時間（松山、高雄、澳門、香港沒帶日期的）：
  放在表定時間前 6 小時到後 18 小時之間
- 高雄的資料沒有日期：預設是當地今天；有表定時間在現在 2 小時以後、狀態已經是
  「離站」「抵達」的班機時，表示清單還沒換日，當成昨天

狀態對照表：從 `data` 分支 2026-10-18 05:06Z 的快照整理（`git fetch origin data` 後
`git show data:history/flights/2026-10-18/<機場>-0506.json.gz | gunzip`），
2026-10-18 08:5xZ 實際抓一次補上新看到的用語。比對前去掉空白、轉大寫。
標「＊」的是兩次都沒看到、依同一來源的用語預先列入的。台灣三個來源（和 TDX，`flights_log.py`）
另有通用規則：開頭是「取消」→ 取消，開頭是「延遲」「延誤」→ 延誤；HD38 補上 TDX 2026-10-22～24
實際看到、HD37 報告工具先補的三種（以前都是 `other`；新存的資料才套，舊檔不改寫）：
- 開頭是「加班」（加班機）→ 正常
- 開頭是「轉降」→ `diverted`（不算取消，另外計數）
- `預計HH:MM到站`／`預計HH:MM離站`／`預計HH:MM出發`（也接 `抵達`、`到達`、`起飛`、沒有結尾字的，
  和帶 `MM/DD` 或 `YYYY/MM/DD` 的，同 HD37 報告工具）→ 正常，狀態裡的時間當預計時間（來源本身
  沒有預計／實際時間時才用），晚 60 分鐘以上照上面的規則算延誤；沒寫日期的照「沒有日期的預計／
  實際時間」的規則放（`tw_expected`）

每格表定（出發＋抵達）少於 `FEW_FLIGHTS`（4）班的，`latest.json` 標 `few: true`（`slot_json`；
HD37 報告工具的「班次少」用同一個門檻）。

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
  - 英文端點也會回中文狀態（2026-10-18 看到 `航班著陸 16:23`）。去空白、轉大寫對中文沒用，所以
    上面的英文樣式都比不到時，再用「包含關鍵字」比對（`MFM_KEYWORDS`，依序、先比到的算），
    狀態裡有 `HH:MM` 就拿來算延誤：
    - 正常：包含「著陸」（`航班著陸 HH:MM`＝已降落，和 `LANDED AT` 同一類；＊`著陸`、＊`已著陸`）、
      包含「起飛」（＊`航班起飛 HH:MM`＝`TOOK OFF AT`；＊`起飛`、＊`已起飛`）
    - 為了「延遲起飛」這類不會被當成正常，先比：＊包含「取消」→ 取消，＊包含「延誤」「延遲」→ 延誤
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .timeutil import SLOT_HOURS, iso

log = logging.getLogger("hongthai")

OK, OTHER, DELAYED, DIVERTED, CANCELLED = "ok", "other", "delayed", "diverted", "cancelled"
SEVERITY = {OK: 0, OTHER: 1, DELAYED: 2, DIVERTED: 3, CANCELLED: 4}
DELAY_MINUTES = 60
FEW_FLIGHTS = 4  # 一格表定少於這個班數標「班次少」（HD37、HD38）
CARGO_TYPES = {"CGO", "CARGO", "FRT"}


@dataclass(frozen=True)
class Flight:
    direction: str  # "dep"／"arr"
    key: tuple  # 去重用
    scheduled: datetime  # 表定時間（帶時區）
    category: str  # OK／OTHER／DELAYED／CANCELLED
    status: str  # 原始狀態字串
    # 以下是 HD31 逐班紀錄（`flights_log.py`）用的，統計不看
    flight: str = ""  # 營運班號
    codeshares: tuple[str, ...] = ()  # 掛名班號（共掛合成一班時被略過的那些列）
    peer: str | None = None  # 對方機場（IATA 或來源的原文）
    when: datetime | None = None  # 預計或實際時間（算延誤用的那個）
    done: bool = False  # 已起飛／已降落：`when` 是實際時間，不是預計


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
TPE_DONE = {"出發DEPARTED", "已到ARRIVED"}  # 預計／實際時間是實際的（HD31）
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
TSA_DONE = {"已飛DEPARTED", "已到ARRIVED"}
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
HKG_DONE = r"(?:DEP|AT GATE|LANDED) "  # 狀態裡的時間是實際的（`EST AT` 是預計）
MFM_STATUS = [
    (r"0?", OK),
    (r"CANCELL?ED", CANCELLED),
    (rf"DELAY UNTIL {_T}", DELAYED),
    (r"DELAYED", DELAYED),
    (rf"(?:TOOK OFF AT|LANDED AT|EXPECTED AT|RESCHEDULE) {_T}", OK),
    (r"BOARDING|GATE CLOSED|CHECK-IN CLOSED|CHECK-IN \S+ OPEN(?: AT \d{1,2}:\d{2})?", OK),
]
# 澳門的中文狀態：（關鍵字, 分類），依序比「包含」，先比到的算
MFM_KEYWORDS = [
    ("取消", CANCELLED),
    ("延誤", DELAYED),
    ("延遲", DELAYED),
    ("著陸", OK),
    ("起飛", OK),
]
MFM_DONE = r"(?:TOOK OFF|LANDED) AT "


# `預計HH:MM到站` 之類（`_norm` 後），和 HD37 報告工具（`tools/report_29w.py` 的 `_EST`）同一套：
# 可帶 `MM/DD` 或 `YYYY/MM/DD`，結尾的「到站」之類可省。群組：年、月、日（都可省）、時間
TW_EXPECTED = re.compile(
    r"預計(?:(?:(\d{4})[/-])?(\d{1,2})[/-](\d{1,2}))?(\d{1,2}:\d{2})(?:到站|離站|出發|抵達|到達|起飛)?"
)


def _lookup(table: dict[str, str], status: object) -> str:
    """台灣三個來源（和 TDX）：先查表，查不到再看開頭的中文、`預計HH:MM到站` 這類。"""
    s = _norm(status)
    if s in table:
        return table[s]
    if s.startswith("取消"):
        return CANCELLED
    if s.startswith(("延遲", "延誤")):
        return DELAYED
    if s.startswith("轉降"):
        return DIVERTED
    if s.startswith("加班") or TW_EXPECTED.fullmatch(s):
        return OK
    return OTHER


def tw_expected(status: object, sched: datetime) -> datetime | None:
    """`預計HH:MM到站` 這類狀態裡的預計時間（帶表定時間的時區）；不是這類回 None。沒寫日期的
    放在表定時間前 6 小時到後 18 小時之間（`_near`），只寫月日的取最接近表定日期的那一年。"""
    m = TW_EXPECTED.fullmatch(_norm(status))
    if not m:
        return None
    clock = _clock(m[4])
    if not m[2]:
        return _near(sched, clock)
    try:
        if m[1]:
            day = date(int(m[1]), int(m[2]), int(m[3]))
        else:
            day = _nearest_year(int(m[2]), int(m[3]), sched.date())
    except ValueError:
        return None
    return _at(day, clock, sched.tzinfo)  # type: ignore[arg-type]


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


def _codeshares(groups: list[tuple], operated: list[bool], nos: list[str]) -> dict[int, list]:
    """共掛是分開的列時（桃園、松山），掛名列歸給同一組（同方向、同表定時間、同航點）裡
    **前面最近的**營運列（來源是營運列後面接它的掛名列；同組有兩班營運時才分得開），前面沒有就給
    同組第一個營運列。回傳 營運列索引 → 掛名班號。"""
    ops: dict[tuple, list[int]] = defaultdict(list)
    for i, (g, op) in enumerate(zip(groups, operated, strict=True)):
        if op:
            ops[g].append(i)
    out: dict[int, list] = defaultdict(list)
    for i, (g, op) in enumerate(zip(groups, operated, strict=True)):
        if op or g not in ops:
            continue
        before = [j for j in ops[g] if j < i]
        out[before[-1] if before else ops[g][0]].append(nos[i])
    return out


def _peer(v: object) -> str | None:
    """對方機場：字串或（香港）IATA 陣列，多個用 `/` 接；空的回 None。"""
    if isinstance(v, list):
        v = "/".join(str(x).strip() for x in v if str(x).strip())
    return str(v or "").strip() or None


# ---- 各來源 ----


def _tpe(payload: dict, tz: ZoneInfo, now: datetime) -> Iterator[Flight | None]:
    rows = payload.get("rows") or []

    def sched_of(r: dict) -> datetime | None:
        try:
            d = datetime.strptime(str(r.get("scheduledDate", "")).strip(), "%Y/%m/%d").date()
        except ValueError:
            return None
        return _at(d, _clock(r.get("scheduledTime")), tz)

    def no_of(r: dict) -> str:
        return f"{r.get('airlineCode', '')}{str(r.get('flightNo', '')).strip()}"

    has_aircraft = [bool(str(r.get("aircraft") or "").strip()) for r in rows]
    groups = [(r.get("kind"), sched_of(r), r.get("airportCode")) for r in rows]
    operated = {g for g, op in zip(groups, has_aircraft, strict=True) if op}
    shares = _codeshares(groups, has_aircraft, [no_of(r) for r in rows])
    for i, r in enumerate(rows):
        direction = {"D": "dep", "A": "arr"}.get(str(r.get("kind", "")).strip())
        sched = sched_of(r)
        if direction is None or sched is None:
            yield None
            continue
        if not has_aircraft[i] and groups[i] in operated:
            continue  # 共掛的掛名列
        actual = None
        try:
            est_day = datetime.strptime(str(r.get("estimatedDate", "")).strip(), "%Y/%m/%d").date()
            actual = _at(est_day, _clock(r.get("estimatedTime")), tz)
        except ValueError:
            pass
        status = str(r.get("status") or "")
        actual = actual or tw_expected(status, sched)
        cat = _category(_lookup(TPE_STATUS, status), sched, actual)
        flight_no = no_of(r)
        yield Flight(
            direction,
            (direction, flight_no, sched),
            sched,
            cat,
            status,
            flight_no,
            tuple(shares.get(i, ())),
            _peer(r.get("airportCode")),
            actual,
            _norm(status) in TPE_DONE,
        )


def _tsa(payload: dict, tz: ZoneInfo, now: datetime) -> Iterator[Flight | None]:
    today = now.astimezone(tz).date()
    for feed, rows in payload.items():
        if not isinstance(rows, list):
            continue
        direction = "dep" if feed.endswith("Departure") else "arr"
        field = "Departure" if direction == "dep" else "Arrival"
        kind_field = "AirDrType" if direction == "dep" else "AirArType"
        peer_field = "GoalAirportCode" if direction == "dep" else "UpAirportCode"
        rows = [r for r in rows if isinstance(r, dict)]

        def no_of(r: dict) -> str:
            return f"{r.get('AirLineIATA') or r.get('AirLineCode') or ''}{r.get('AirLineNum', '')}"

        master = [str(r.get("Master") or "1").strip() in ("", "1") for r in rows]
        groups = [
            (r.get("AirFlyDate"), r.get(f"Expect{field}Time"), r.get(peer_field)) for r in rows
        ]
        shares = _codeshares(groups, master, [no_of(r) for r in rows])
        for i, r in enumerate(rows):
            if not master[i]:
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
            status = str(r.get("AirFlyStatus") or "")
            actual = _near(sched, _clock(r.get(f"Real{field}Time"))) or tw_expected(status, sched)
            cat = _category(_lookup(TSA_STATUS, status), sched, actual)
            flight_no = no_of(r)
            yield Flight(
                direction,
                (direction, flight_no, sched),
                sched,
                cat,
                status,
                flight_no,
                tuple(shares.get(i, ())),
                _peer(r.get(peer_field)),
                actual,
                _norm(status) in TSA_DONE,
            )


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
        peer_field = "goalAirportCode" if direction == "dep" else "upAirportCode"
        for r in rows:
            sched = _at(day, _clock(r.get("expectTime")), tz)
            if sched is None:
                yield None
                continue
            status = str(r.get("airFlyStatus") or "")
            actual = _near(sched, _clock(r.get("realTime"))) or tw_expected(status, sched)
            cat = _category(_lookup(KHH_STATUS, status), sched, actual)
            flight_no = str(r.get("airLineNum") or "").strip()
            yield Flight(
                direction,
                (direction, r.get("airLineNum"), sched),
                sched,
                cat,
                status,
                flight_no,
                (),
                _peer(r.get(peer_field)),
                actual,
                _norm(status) in KHH_FINAL,
            )


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
                peer = item.get("destination" if direction == "dep" else "origin") or []
                yield Flight(
                    direction,
                    key,
                    sched,
                    _category(cat, sched, actual),
                    status,
                    nos[0] if nos else "",
                    tuple(nos[1:]),
                    _peer(peer),
                    actual,
                    bool(re.match(HKG_DONE, status.strip().upper())),
                )


def _mfm_part(part: str) -> tuple[str, str | None]:
    cat, hhmm, _ = _match(MFM_STATUS, part)
    if cat == OTHER:
        for keyword, kw_cat in MFM_KEYWORDS:
            if keyword in part:
                m = re.search(_T, part)
                return kw_cat, m[1] if m else None
    return cat, hhmm


def _mfm_parts(status: str) -> list[str]:
    return [p for p in re.split(r"\s{2,}", status.strip()) if p] or [""]


def _mfm_status(status: str) -> tuple[str, str | None]:
    results = [_mfm_part(p) for p in _mfm_parts(status)]
    cat = max((c for c, _ in results), key=SEVERITY.__getitem__)
    hhmm = next((t for _, t in results if t), None)
    return cat, hhmm


def _mfm_done(status: str) -> bool:
    """已起飛／已降落（`TOOK OFF AT`、`LANDED AT`、中文的「著陸」「起飛」且是正常的那類）。"""
    for p in _mfm_parts(status):
        if re.match(MFM_DONE, re.sub(r"\s+", " ", p).upper()):
            return True
        if ("著陸" in p or "起飛" in p) and _mfm_part(p)[0] == OK:
            return True
    return False


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
            peer = r.get("destination" if direction == "dep" else "origin")
            yield Flight(
                direction,
                key,
                sched,
                _category(cat, sched, actual),
                status,
                str(r.get("flightNo") or "").strip(),
                (),
                _peer(peer),
                actual,
                _mfm_done(status),
            )


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
    return {"total": 0, CANCELLED: 0, DELAYED: 0, DIVERTED: 0, OTHER: 0}


def unknown_statuses(flights: Iterable[Flight]) -> Counter[str]:
    """對照表沒列的狀態字串（去頭尾空白）→ 班數。"""
    return Counter(f.status.strip() for f in flights if f.category == OTHER)


def airport_stats(airport: str, payload: dict, tz: str, now: datetime) -> list[dict]:
    """一個機場的原始資料 → 每個有班機的 UTC 6 小時格一筆統計，依 `from` 排序。"""
    return slot_stats(airport, flights_of(airport, payload, tz, now), now)


def _floor(t: datetime, hours: int) -> datetime:
    """往前取整到 `hours` 小時一格（UTC 00Z 起算；6 就是 `timeutil.floor_6h`）。"""
    t = t.astimezone(UTC)
    return t.replace(hour=t.hour - t.hour % hours, minute=0, second=0, microsecond=0)


def slot_stats(
    airport: str,
    flights: list[Flight],
    now: datetime,
    hours: int = SLOT_HOURS,
    log_unknown: bool = True,
) -> list[dict]:
    """解析好的航班 → 每格一筆統計（`airport_stats` 的後半）。`hours` 是格長（HD38：3 小時格
    用 3，依表定歸格的規則一樣）；`log_unknown=False` 不再印看不懂的狀態（同一批算第二次時）。"""
    if log_unknown:
        for status, n in sorted(unknown_statuses(flights).items()):
            log.warning("航班 %s 看不懂的狀態 %r（%d 班，算進 other）", airport, status, n)
    slots: dict[datetime, dict[str, dict[str, int]]] = defaultdict(
        lambda: {"dep": _zero(), "arr": _zero()}
    )
    for f in flights:
        counts = slots[_floor(f.scheduled, hours)][f.direction]
        counts["total"] += 1
        if f.category != OK:
            counts[f.category] += 1
    step = timedelta(hours=hours)
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


COUNT_KEYS = ("total", CANCELLED, DELAYED, DIVERTED)


def slot_json(row: dict, source: str) -> dict:
    """一筆格的統計 → `latest.json` 的 `slots[].flights`（HD38）：出發＋抵達合計的
    `total`／`cancelled`／`delayed`／`diverted`、`few`（表定少於 `FEW_FLIGHTS` 班）、`source`、
    `asOf`，另附 `dep`／`arr` 各自的四個數。`other` 不另列（算在 `total` 裡）；HD38 以前存的列
    沒有 `diverted`，當 0。"""
    parts = {
        d: {k: int((row.get(d) or {}).get(k) or 0) for k in COUNT_KEYS} for d in ("dep", "arr")
    }
    total = {k: parts["dep"][k] + parts["arr"][k] for k in COUNT_KEYS}
    return {
        **total,
        "few": total["total"] < FEW_FLIGHTS,
        "source": source,
        "asOf": row.get("asOf"),
        **parts,
    }


def load(history: Path, days: Iterable[str]) -> list[dict]:
    """讀 `history/cancellations/<日期>.json`（這幾天的；沒有的檔跳過）。"""
    rows: list[dict] = []
    for day in sorted(set(days)):
        path = history / "cancellations" / f"{day}.json"
        if path.exists():
            body = json.loads(path.read_text(encoding="utf-8"))
            rows += [r for r in body if isinstance(r, dict)] if isinstance(body, list) else []
    return rows


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


UNKNOWN_FILE = "unknown-statuses.json"


def merge_unknown(existing: dict, airport_counts: dict[str, Counter[str]], now: datetime) -> dict:
    """`{機場: {狀態: {"count", "firstSeen", "lastSeen"}}}`：次數累加（每次 build 看到幾班就加幾，
    同一班在多次 build 都看到會重複算），`firstSeen` 留第一次、`lastSeen` 換成這次。"""
    out = {k: dict(v) for k, v in existing.items() if isinstance(v, dict)}
    for airport, counts in sorted(airport_counts.items()):
        rows = out.setdefault(airport, {})
        for status, n in sorted(counts.items()):
            old = rows.get(status) if isinstance(rows.get(status), dict) else {}
            rows[status] = {
                "count": int(old.get("count") or 0) + n,
                "firstSeen": old.get("firstSeen") or iso(now),
                "lastSeen": iso(now),
            }
    return {k: dict(sorted(v.items())) for k, v in sorted(out.items())}


def store_unknown(history: Path, airport_counts: dict[str, Counter[str]], now: datetime) -> Path:
    """合併進 `history/cancellations/unknown-statuses.json`（只存狀態字串與次數，不存班號、時間、
    航點）。這次沒有看不懂的狀態也會建出檔（`{}`），主對話看得到「有在記、只是都看得懂」。"""
    path = history / "cancellations" / UNKNOWN_FILE
    old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    merged = merge_unknown(old if isinstance(old, dict) else {}, airport_counts, now)
    if not path.exists() or merged != old:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
