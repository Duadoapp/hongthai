"""HD31 每小時逐班航班紀錄：逐班轉換、共掛合併、分類和 `cancellations.py` 一致、只在變化時寫、
表定時間的 UTC 日期歸檔、高雄換日。"""

from __future__ import annotations

import json

import pytest
from conftest import FIXTURES, load_json, utc

from hongthai import cancellations, events, flights_log
from hongthai.sources import flights

NOW = utc(2026, 10, 18, 8, 55)
TW = "Asia/Taipei"
HK = "Asia/Hong_Kong"
MO = "Asia/Macau"


def tpe():
    return {"rows": flights.parse_tpe((FIXTURES / "tpe_flights_big5.txt").read_bytes())}


SOURCES = {
    "RCTP": (tpe, TW),
    "RCSS": (lambda: {"intlDeparture": load_json("tsa_intl_departure.json")}, TW),
    "RCKH": (lambda: {"intlDeparture": load_json("khh_intdep.json")}, TW),
    "VHHH": (lambda: {"departure": [], "arrival": load_json("hkg_arrival.json")}, HK),
    "VMMC": (lambda: {"departure": load_json("mfm_departure_en.json"), "arrival": []}, MO),
}


def rows(airport, payload=None, now=NOW):
    make, tz = SOURCES[airport]
    return flights_log.rows_of(airport, payload if payload is not None else make(), tz, now)


def by_flight(rs):
    return {r["flight"]: r for r in rs}


# ---- 各來源逐班轉換 ----


def test_tpe_rows_and_codeshares():
    rs = by_flight(rows("RCTP"))
    # 掛名列（機型空白）併進前面的營運列，不另成一班
    assert set(rs) == {
        "LJ733", "LJ763", "ZE987", "ZE983", "UA166", "CI162", "MU5005", "UA871", "CI279",
    }  # fmt: skip
    assert rs["LJ733"] == {
        "t": "2026-10-18T08:55:00Z",
        "airport": "RCTP",
        "dir": "arr",
        "flight": "LJ733",
        "codeshares": ["KE5759"],
        "peer": "ICN",
        "schedUtc": "2026-10-16T16:10:00Z",  # 台灣 10/17 00:10 → UTC 前一天
        "estUtc": None,
        "actUtc": "2026-10-16T16:29:00Z",  # 已到：實際時間
        "status": "已到ARRIVED",
        "class": "normal",
        "source": "taoyuan-airport",
    }
    assert rs["CI162"]["codeshares"] == ["KE5694", "DL7719"]
    assert (rs["CI162"]["estUtc"], rs["CI162"]["actUtc"]) == ("2026-10-18T08:25:00Z", None)
    assert rs["CI162"]["class"] == "normal"  # 晚 55 分不算延誤
    assert (rs["UA871"]["class"], rs["MU5005"]["class"]) == ("delayed", "delayed")
    assert (rs["CI279"]["class"], rs["CI279"]["codeshares"]) == ("cancelled", ["JL5121"])


def test_tpe_codeshare_goes_to_preceding_operator():
    """同組（同方向、同表定時間、同航點）有兩班營運時，掛名列歸前面最近的那班。"""
    base = {
        "kind": "A",
        "scheduledDate": "2026/10/22",
        "scheduledTime": "15:05:00",
        "airportCode": "KIX",
        "status": "已到ARRIVED",
    }
    payload = {
        "rows": [
            {**base, "airlineCode": "CI", "flightNo": "157", "aircraft": "B777-300"},
            {**base, "airlineCode": "JL", "flightNo": "5103", "aircraft": ""},
            {**base, "airlineCode": "BR", "flightNo": "131", "aircraft": "B777-300"},
            {**base, "airlineCode": "NZ", "flightNo": "4917", "aircraft": ""},
            {**base, "airlineCode": "NH", "flightNo": "5811", "aircraft": ""},
        ]
    }
    rs = by_flight(rows("RCTP", payload))
    assert {k: r["codeshares"] for k, r in rs.items()} == {
        "CI157": ["JL5103"],
        "BR131": ["NZ4917", "NH5811"],
    }


def test_tsa_rows_and_codeshares():
    rs = by_flight(rows("RCSS"))
    # Master 2、3 是掛名：MU5098 的 FM3002、CI8005；MU8628、BR2178 沒有同組的營運列，不算
    assert set(rs) == {"B7502", "JL096", "JL098", "MU5098"}
    r = rs["MU5098"]
    assert (r["codeshares"], r["peer"], r["class"], r["status"]) == (
        ["FM3002", "CI8005"],
        "SHA",
        "delayed",
        "延誤Delayed",
    )
    assert (r["schedUtc"], r["estUtc"], r["actUtc"]) == (
        "2026-10-18T09:15:00Z",
        "2026-10-18T09:52:00Z",
        None,
    )
    assert (rs["B7502"]["estUtc"], rs["B7502"]["actUtc"]) == (None, "2026-10-17T23:50:00Z")
    assert rs["B7502"]["schedUtc"] == "2026-10-18T00:00:00Z"
    assert rs["B7502"]["source"] == "tsa"


def test_tsa_arrival_peer():
    row = {
        "AirFlyDate": "1018",
        "AirLineIATA": "MU",
        "AirLineNum": "5007",
        "UpAirportCode": "SHA",
        "GoalAirportCode": "TSA",
        "ExpectArrivalTime": "1615",
        "RealArrivalTime": "1615",
        "AirFlyStatus": "取消Cancelled",
        "Master": "1",
    }
    (r,) = rows("RCSS", {"intlArrival": [row]})
    assert (r["dir"], r["peer"], r["class"]) == ("arr", "SHA", "cancelled")


def test_khh_rows():
    rs = by_flight(rows("RCKH"))
    assert (rs["IT284"]["peer"], rs["IT284"]["actUtc"], rs["IT284"]["estUtc"]) == (
        "KIX",
        "2026-10-17T23:20:00Z",
        None,
    )
    # 「登機」但預計晚 61 分 → 延誤（cancellations 同一套）；時間是預計
    assert (rs["IT670"]["class"], rs["IT670"]["estUtc"], rs["IT670"]["actUtc"]) == (
        "delayed",
        "2026-10-18T09:16:00Z",
        None,
    )
    assert rs["IT670"]["codeshares"] == []
    arr = {"expectTime": "07:05", "realTime": "", "airLineNum": "FD234", "upAirportCode": "DMK"}
    (r,) = rows("RCKH", {"intlArrival": [{**arr, "airFlyStatus": "準時"}]})
    assert (r["dir"], r["peer"], r["estUtc"], r["actUtc"]) == ("arr", "DMK", None, None)


def test_khh_list_date_rollover():
    """高雄清單沒有日期：現在台灣 10/18 00:30，表定 23:00 的已經離站 → 清單是 10/17 的。"""
    early = utc(2026, 10, 17, 16, 30)
    late = {"expectTime": "23:00", "realTime": "23:05", "airLineNum": "CI1", "airFlyStatus": "離站"}
    morning = {"expectTime": "07:00", "realTime": "", "airLineNum": "CI2", "airFlyStatus": "準時"}
    payload = {"intlDeparture": [late, morning]}
    rs = by_flight(rows("RCKH", payload, early))
    assert rs["CI1"]["schedUtc"] == "2026-10-17T15:00:00Z"  # 台灣 10/17 23:00
    assert rs["CI2"]["schedUtc"] == "2026-10-16T23:00:00Z"  # 台灣 10/17 07:00
    assert {flights_log.day_of(r) for r in rs.values()} == {"2026-10-17", "2026-10-16"}


def test_hkg_rows_and_codeshares():
    rs = by_flight(rows("VHHH"))
    r = rs["HX613"]
    assert (r["codeshares"], r["peer"], r["dir"], r["source"]) == (
        ["EY6812", "TK9201"],
        "KIX",
        "arr",
        "hongkongairport",
    )
    # 表定香港 10/17 23:50、到閘 10/18 00:55 → 晚 65 分
    assert (r["schedUtc"], r["actUtc"], r["estUtc"], r["class"]) == (
        "2026-10-17T15:50:00Z",
        "2026-10-17T16:55:00Z",
        None,
        "delayed",
    )
    assert rs["CX774"]["class"] == "cancelled"
    assert len(rs["CX774"]["codeshares"]) == 5
    # Est at 是預計
    assert (rs["HB851"]["estUtc"], rs["HB851"]["actUtc"]) == ("2026-10-18T16:30:00Z", None)
    # 香港 10/18 00:00 的班機是 UTC 10/17 → 歸 10/17 的檔
    assert flights_log.day_of(rs["UO671"]) == "2026-10-17"


def test_hkg_departure_peer_list():
    group = {
        "date": "2026-10-22",
        "cargo": False,
        "list": [
            {
                "time": "20:45",
                "flight": [{"no": "PX 019D"}, {"no": "CX 6899"}],
                "status": "Dep 20:03 (22/10/2026)",
                "destination": ["POM", "HGU"],
            }
        ],
    }
    (r,) = rows("VHHH", {"departure": [group], "arrival": []})
    assert (r["flight"], r["codeshares"], r["peer"], r["actUtc"]) == (
        "PX019D",
        ["CX6899"],
        "POM/HGU",
        "2026-10-22T12:03:00Z",
    )


def test_mfm_rows():
    rs = by_flight(rows("VMMC"))
    # 澳門 10/18 02:15 → UTC 10/17 18:15
    assert (rs["TW650"]["schedUtc"], rs["TW650"]["actUtc"], rs["TW650"]["peer"]) == (
        "2026-10-17T18:15:00Z",
        "2026-10-17T18:24:00Z",
        "Jeju",
    )
    assert flights_log.day_of(rs["TW650"]) == "2026-10-17"
    ak = rs["AK187"]
    assert (ak["class"], ak["estUtc"], ak["actUtc"]) == ("delayed", "2026-10-18T09:45:00Z", None)
    assert ak["status"].startswith("DELAY UNTIL 17:45   ")  # 原始文字
    assert (rs["KR502"]["class"], rs["KR502"]["estUtc"]) == ("cancelled", None)
    # 開櫃時間不算班機時間
    assert (rs["Z2093"]["estUtc"], rs["Z2093"]["actUtc"]) == (None, None)
    assert rs["VZ3733"]["estUtc"] == "2026-10-18T12:25:00Z"
    assert rs["TW650"]["source"] == "aacm"


@pytest.mark.parametrize(
    ("status", "act"),
    [("航班著陸 16:23", True), ("Landed at 16:23", True), ("Expected at 16:23", False)],
)
def test_mfm_arrival_actual_or_expected(status, act):
    row = {"time": "18-10 16:20", "flightNo": "NX001", "origin": "Taipei", "status": status}
    (r,) = rows("VMMC", {"departure": [], "arrival": [{**row, "date": "18-10-2026"}]})
    t = "2026-10-18T08:23:00Z"
    assert (r["actUtc"], r["estUtc"]) == ((t, None) if act else (None, t))
    assert r["peer"] == "Taipei"


@pytest.mark.parametrize("airport", sorted(SOURCES))
def test_class_matches_cancellations(airport):
    """分類和 `cancellations.py` 一模一樣：逐班的 class 加起來等於取消統計的格。"""
    make, tz = SOURCES[airport]
    rs = rows(airport)
    parsed = cancellations.flights_of(airport, make(), tz, NOW)
    assert len(rs) == len(parsed)
    assert sorted(r["class"] for r in rs) == sorted(flights_log.CLASS[f.category] for f in parsed)
    stats = cancellations.airport_stats(airport, make(), tz, NOW)
    for kind in ("cancelled", "delayed", "other"):
        assert sum(s["dep"][kind] + s["arr"][kind] for s in stats) == sum(
            r["class"] == kind for r in rs
        )
    assert sum(s["dep"]["total"] + s["arr"]["total"] for s in stats) == len(rs)


# ---- 只在變化時寫 ----


def test_changed_only_on_change():
    first = rows("VMMC")
    lines = [json.dumps(r) for r in first]
    assert flights_log.changed([], first) == first  # 第一次看到全寫
    later = utc(2026, 10, 18, 9, 55)
    again = rows("VMMC", now=later)
    assert flights_log.changed(lines, again) == []  # `t` 不同不算變化
    payload = SOURCES["VMMC"][0]()
    payload["departure"][6]["status"] = "DELAY UNTIL 18:30"  # AK187 預計時間改了
    payload["departure"][9]["status"] = "CANCELLED"  # JX206 取消
    new = flights_log.changed(lines + ["壞掉的行", "{}"], rows("VMMC", payload, later))
    assert [(r["flight"], r["class"], r["estUtc"]) for r in new] == [
        ("AK187", "delayed", "2026-10-18T10:30:00Z"),
        ("JX206", "cancelled", None),
    ]


def test_changed_compares_with_last_line():
    r = rows("VMMC")[0]
    a, b = {**r, "status": "A"}, {**r, "status": "B"}
    # 狀態 A → B → 又回到 A：和最後一行（B）比，要寫
    assert flights_log.changed([json.dumps(a), json.dumps(b)], [a]) == [a]
    assert flights_log.changed([json.dumps(a), json.dumps(b)], [b]) == []


def test_store_flights_files_by_sched_utc_date(tmp_path):
    d = tmp_path / "events" / "29W"
    rs = rows("VHHH") + rows("RCTP")
    assert events.store_flights(d, rs) == len(rs)
    assert events.store_flights(d, rs) == 0
    files = sorted(p.name for p in (d / "flights").iterdir())
    assert files == [
        "2026-10-16.jsonl",
        "2026-10-17.jsonl",
        "2026-10-18.jsonl",
        "2026-10-19.jsonl",
    ]
    day17 = [json.loads(x) for x in (d / "flights" / "2026-10-17.jsonl").read_text().splitlines()]
    assert {r["flight"] for r in day17} >= {"HX613", "UO671", "UA166"}
    assert all(r["schedUtc"].startswith("2026-10-17") for r in day17)
    # 狀態變了只多一行，寫在同一班的檔
    hb = [r for r in rs if r["flight"] == "HB851"]
    cancelled = [{**r, "status": "Cancelled", "class": "cancelled"} for r in hb]
    assert events.store_flights(d, cancelled) == 1
    day18 = (d / "flights" / "2026-10-18.jsonl").read_text().splitlines()
    assert json.loads(day18[-1])["class"] == "cancelled"
