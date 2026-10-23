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

只在有變化時寫：同一個 `airport`＋`dir`＋`flight`＋`schedUtc`，`status`、`class`、`estUtc`、
`actUtc` 任一個和檔裡最後一行不同才寫（`changed`），第一次看到也寫。
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime

from . import cancellations
from .timeutil import iso

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


def rows_of(airport: str, payload: dict, tz: str, fetched: datetime) -> list[dict]:
    """一個機場 `fetch_*` 的回傳 → 每班一行，依表定時間、方向、班號排序。看不出方向或表定時間的
    筆數由 `cancellations.flights_of` 記 log。"""
    rows = []
    for f in cancellations.flights_of(airport, payload, tz, fetched):
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
                "source": SOURCES.get(airport),
            }
        )
    return sorted(rows, key=lambda r: (r["schedUtc"], r["dir"], r["flight"]))


def day_of(row: dict) -> str:
    """歸檔的日期：表定時間的 UTC 日期。"""
    return row["schedUtc"][:10]


def flight_key(row: dict) -> tuple:
    return (row["airport"], row["dir"], row["flight"], row["schedUtc"])


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
