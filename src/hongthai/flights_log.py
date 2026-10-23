"""每小時逐班航班紀錄（HD31，29W 對答案用；純函式，不連網、不寫檔）。

`sources/flights.py` 各機場 `fetch_*` 的回傳 → 一班一行（`events.py` 寫進
`history/events/<id>/flights/<表定時間的 UTC 日期>.jsonl`）：

    {"t": 抓的時間, "airport": ICAO, "dir": "dep"|"arr", "flight": 營運班號,
     "codeshares": [掛名班號…], "peer": 對方機場（IATA 或原文）, "schedUtc", "estUtc", "actUtc",
     "status": 原始狀態文字, "class": "cancelled"|"delayed"|"other"|"normal", "source"}

解析、共掛合成一班、去重、分類、沒有日期的時間、高雄換日全部用 `cancellations.flights_of`
（和取消統計同一套）。`estUtc`／`actUtc` 是 `cancellations` 算延誤用的那個時間：狀態表示已起飛／
已降落（桃園「出發」「已到」、松山「已飛」「已到」、高雄「離站」「抵達」、香港 `Dep`／`At gate`／
`Landed`、澳門 `TOOK OFF AT`／`LANDED AT`／「著陸」「起飛」）放 `actUtc`，其他放 `estUtc`。

只在有變化時寫：同一個 `source`＋`airport`＋`dir`＋`flight`＋`schedUtc`，`status`、`class`、
`estUtc`、`actUtc` 任一個和檔裡最後一行不同才寫（`changed`），第一次看到也寫。`source` 算在鍵裡
（HD32）：桃園、松山、高雄 TDX 和原本的來源都存，兩邊各自比、不合併、不去重。

香港（HD31 修正，2026-10-24 上線後看到）：`past?date=` 每一天的回應都帶前後一天還沒結束的幾班，
同一班會在兩個回應裡各出現一次，而兩個回應的更新時間（組的 `lastUpdatedTime`）不同，舊的那份狀態
落後（例如一份已經 `Dep 23:20`、另一份還是 `Gate Closed`）。不處理的話每小時挑到哪一份不一定，
同一班的狀態來回跳、每次都多寫一行。所以逐班紀錄先用 `hkg_freshest` 只留 `lastUpdatedTime` 最新
那組的那份（同一組裡重複的照舊交給 `cancellations`）；取消統計不變。

HD32：TDX 的 `/v2/Air/FIDS/Airport`（`sources/tdx.py`）一個機場那筆 → 同樣的一行（`tdx_rows`，
`source: "tdx"`）。TDX 每班有表定、預計、實際三個帶日期的時間（當地時間），所以不用猜日期：
`actUtc` 是實際時間（沒有實際、但狀態已起飛／已降落時放預計），其他放預計；延誤看實際，沒有實際
看預計。狀態用中文 `…Remark`（空的才用 `…RemarkEn`），照 `cancellations.py` 的台灣規則分類
（`TDX_STATUS`：台灣三個來源的對照表合起來，加 TDX 可能用的單一中文或英文；查不到時開頭「取消」→
取消、「延誤／延遲」→ 延誤），對照表沒列的記 log。貨機（`IsCargo`）不存；共掛：某一列的班號列在
同方向、同表定時間另一列的 `CodeShare` 裡，就是掛名列，不另成一班；同一班號＋表定時間重複時留
最嚴重的。
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from . import cancellations
from .cancellations import CANCELLED, DELAYED, OK, Flight
from .timeutil import iso

log = logging.getLogger("hongthai")

CLASS = {
    cancellations.OK: "normal",
    cancellations.OTHER: "other",
    cancellations.DELAYED: "delayed",
    cancellations.CANCELLED: "cancelled",
}
SOURCES = {
    "RCTP": "taoyuan-airport",
    "RCSS": "tsa",
    "RCKH": "kia",
    "VHHH": "hongkongairport",
    "VMMC": "aacm",
}
TDX = "tdx"
# TDX 的狀態（`_norm` 後）：台灣三個來源的對照表合起來（高雄的有單一中文「取消」「延遲」「準時」），
# 加上 TDX 可能用的其他單一中文或英文
# （＊：還沒實際看過，HD32 依民航局與各機場 FIDS 的用語預先列入）
TDX_STATUS = {
    **cancellations.TPE_STATUS,
    **cancellations.TSA_STATUS,
    **cancellations.KHH_STATUS,
    "CANCELLED": CANCELLED,  # ＊
    "CANCELED": CANCELLED,  # ＊
    "延誤": DELAYED,  # ＊
    "DELAYED": DELAYED,  # ＊
    "DELAY": DELAYED,  # ＊
    "ONTIME": OK,  # ＊
    "已飛": OK,  # ＊
    "出發": OK,  # ＊
    "DEPARTED": OK,  # ＊
    "已到": OK,  # ＊
    "到達": OK,  # ＊
    "ARRIVED": OK,  # ＊
    "報到": OK,  # ＊
    "CHECKIN": OK,  # ＊
    "BOARDING": OK,  # ＊
    "提早": OK,  # ＊
    "EARLY": OK,  # ＊
    "時間更改": OK,  # ＊
    "SCHEDULECHANGE": OK,  # ＊
}
# 已起飛／已降落（沒有實際時間時，預計時間當實際）
TDX_DONE = (
    cancellations.TPE_DONE
    | cancellations.TSA_DONE
    | cancellations.KHH_FINAL
    | {
        "已飛",
        "出發",
        "DEPARTED",
        "已到",
        "到達",
        "ARRIVED",
    }
)


def _updated(group: dict) -> datetime:
    try:
        t = datetime.fromisoformat(str(group.get("lastUpdatedTime") or ""))
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def hkg_freshest(payload: dict) -> dict:
    """香港：同一班（同方向、同日期的組、同表定時間、同第一個班號）出現在多個組時，只留
    `lastUpdatedTime` 最新那組的那份（見檔頭）；沒有 `lastUpdatedTime` 的組當最舊。"""
    out: dict = dict(payload)
    for feed in ("departure", "arrival"):
        groups = list(payload.get(feed) or [])
        dicts = [i for i, g in enumerate(groups) if isinstance(g, dict)]
        order = sorted(dicts, key=lambda i: _updated(groups[i]), reverse=True)
        seen: set[tuple] = set()
        kept: dict[int, list] = {}
        for i in order:
            g, items = groups[i], []
            for item in g.get("list") or []:
                nos = item.get("flight") if isinstance(item, dict) else None
                no = str((nos or [{}])[0].get("no", "")).replace(" ", "") if nos else ""
                key = (str(g.get("date")), item.get("time") if isinstance(item, dict) else None, no)
                if key in seen:
                    continue
                seen.add(key)
                items.append(item)
            kept[i] = items
        # 格式不對的（不是物件）原樣留著，照舊由 `cancellations` 報錯
        out[feed] = [{**g, "list": kept[i]} if i in kept else g for i, g in enumerate(groups)]
    return out


def rows_of(airport: str, payload: dict, tz: str, fetched: datetime) -> list[dict]:
    """一個機場 `fetch_*` 的回傳 → 每班一行，依表定時間、方向、班號排序。看不出方向或表定時間的
    筆數由 `cancellations.flights_of` 記 log。香港先用 `hkg_freshest` 去掉舊的那份。"""
    if airport == "VHHH":
        payload = hkg_freshest(payload)
    flights = cancellations.flights_of(airport, payload, tz, fetched)
    return _rows(airport, flights, fetched, SOURCES.get(airport))


def _rows(airport: str, flights: Iterable[Flight], fetched: datetime, source: str | None) -> list:
    rows = []
    for f in flights:
        when = iso(f.when)
        rows.append(
            {
                "t": iso(fetched),
                "airport": airport,
                "dir": f.direction,
                "flight": f.flight,
                "codeshares": list(f.codeshares),
                "peer": f.peer,
                "schedUtc": iso(f.scheduled),
                "estUtc": None if f.done else when,
                "actUtc": when if f.done else None,
                "status": f.status,
                "class": CLASS[f.category],
                "source": source,
            }
        )
    return sorted(rows, key=lambda r: (r["schedUtc"], r["dir"], r["flight"]))


# ---- TDX（HD32） ----


def _tdx_time(v: object, tz: ZoneInfo) -> datetime | None:
    """TDX 的時間是當地時間 `yyyy-MM-ddTHH:mm`（沒有時區就當機場時區；有就照它的）。"""
    s = str(v or "").strip()
    if not s:
        return None
    try:
        t = datetime.fromisoformat(s)
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=tz)


def _tdx_no(airline: object, number: object) -> str:
    """`AirlineID`＋`FlightNumber`（文件說班號不含航空公司代碼；已經含的不重複加）。"""
    a = re.sub(r"\s+", "", str(airline or "")).upper()
    n = re.sub(r"\s+", "", str(number or "")).upper()
    if not n:
        return ""
    if a and n.startswith(a) and n[len(a) :][:1].isdigit():
        return n
    return a + n


def _tdx_codeshares(v: object) -> list[str]:
    """`CodeShare`：字串（`,`／`;`／`/`／`、` 分隔）或 `[{AirlineID, FlightNumber}]`／字串陣列。"""
    if isinstance(v, list):
        out = []
        for x in v:
            if isinstance(x, dict):
                no = _tdx_no(x.get("AirlineID"), x.get("FlightNumber"))
            else:
                no = re.sub(r"\s+", "", str(x or "")).upper()
            if no:
                out.append(no)
        return out
    parts = re.split(r"[,;/、]+", str(v or ""))
    return [p for p in (re.sub(r"\s+", "", x).upper() for x in parts) if p]


def _tdx_status(zh: str, en: str) -> str:
    cat = cancellations._lookup(TDX_STATUS, zh) if zh.strip() else OK
    if zh.strip() and cat != cancellations.OTHER:
        return cat
    if en.strip():
        en_cat = cancellations._lookup(TDX_STATUS, en)
        if en_cat != cancellations.OTHER or not zh.strip():
            return en_cat
    return cat


def tdx_flights(airport_fids: dict, tz: str) -> list[Flight]:
    """TDX 一個機場那筆 → 解析、去重好的 `Flight`（分類、共掛、貨機規則見檔頭）。"""
    zone = ZoneInfo(tz)
    out: list[Flight] = []
    skipped = 0
    for feed, direction, field, peer_field in (
        ("FIDSDeparture", "dep", "Departure", "ArrivalAirportID"),
        ("FIDSArrival", "arr", "Arrival", "DepartureAirportID"),
    ):
        items = [r for r in airport_fids.get(feed) or [] if isinstance(r, dict)]
        items = [r for r in items if r.get("IsCargo") is not True]
        parsed = []
        for r in items:
            sched = _tdx_time(r.get(f"Schedule{field}Time"), zone)
            no = _tdx_no(r.get("AirlineID"), r.get("FlightNumber"))
            if sched is None or not no:
                skipped += 1
                continue
            parsed.append((r, sched, no, _tdx_codeshares(r.get("CodeShare"))))
        marketed = {(sched, c) for _, sched, no, cs in parsed for c in cs if c != no}
        for r, sched, no, cs in parsed:
            if (sched, no) in marketed:
                continue  # 共掛的掛名列
            zh = str(r.get(f"{field}Remark") or "").strip()
            en = str(r.get(f"{field}RemarkEn") or "").strip()
            actual = _tdx_time(r.get(f"Actual{field}Time"), zone)
            estimated = _tdx_time(r.get(f"Estimated{field}Time"), zone)
            when = actual or estimated
            done = actual is not None or cancellations._norm(zh or en) in TDX_DONE
            out.append(
                Flight(
                    direction,
                    (direction, no, sched),
                    sched,
                    cancellations._category(_tdx_status(zh, en), sched, when),
                    zh or en,
                    no,
                    tuple(c for c in dict.fromkeys(cs) if c != no),
                    cancellations._peer(r.get(peer_field)),
                    when,
                    done,
                )
            )
    sev = cancellations.SEVERITY
    seen: dict[tuple, Flight] = {}
    for f in out:
        if f.key not in seen or sev[f.category] > sev[seen[f.key].category]:
            seen[f.key] = f
    if skipped:
        log.warning(
            "TDX 航班 %s：%d 筆沒有表定時間或班號，跳過", airport_fids.get("AirportID"), skipped
        )
    return list(seen.values())


def tdx_rows(airport: str, airport_fids: dict, tz: str, fetched: datetime) -> list[dict]:
    """TDX 一個機場那筆 → 每班一行（`source: "tdx"`）；對照表沒列的狀態記 log。"""
    flights = tdx_flights(airport_fids, tz)
    for status, n in sorted(cancellations.unknown_statuses(flights).items()):
        log.warning("TDX 航班 %s 看不懂的狀態 %r（%d 班，class 是 other）", airport, status, n)
    return _rows(airport, flights, fetched, TDX)


def day_of(row: dict) -> str:
    """歸檔的日期：表定時間的 UTC 日期。"""
    return row["schedUtc"][:10]


def flight_key(row: dict) -> tuple:
    return (row.get("source"), row["airport"], row["dir"], row["flight"], row["schedUtc"])


def flight_state(row: dict) -> tuple:
    return (row["status"], row["class"], row["estUtc"], row["actUtc"])


def changed(existing: Iterable[str], rows: Iterable[dict]) -> list[dict]:
    """`existing` 是同一檔已有的行（文字）；回傳 `rows` 裡和同一班最後一行狀態不同（或第一次
    看到）的。壞掉的行跳過。"""
    last: dict[tuple, tuple] = {}
    for line in existing:
        try:
            r = json.loads(line)
            last[flight_key(r)] = flight_state(r)
        except (ValueError, KeyError, TypeError):
            continue
    out = []
    for r in rows:
        k, s = flight_key(r), flight_state(r)
        if last.get(k) != s:
            out.append(r)
            last[k] = s
    return out
