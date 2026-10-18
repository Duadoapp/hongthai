"""航班 → 每 6 小時格的取消／延誤統計：歸格、分類、去重、合併。"""

from __future__ import annotations

import json
import logging

import pytest
from conftest import FIXTURES, load_json, utc

from hongthai import cancellations
from hongthai.sources import flights

NOW = utc(2026, 10, 18, 8, 55)
TPE_TZ = "Asia/Taipei"


def counts(total=0, cancelled=0, delayed=0, other=0):
    return {"total": total, "cancelled": cancelled, "delayed": delayed, "other": other}


def by_slot(stats):
    return {r["from"]: (r["dep"], r["arr"]) for r in stats}


def tpe_payload():
    return {"rows": flights.parse_tpe((FIXTURES / "tpe_flights_big5.txt").read_bytes())}


# ---- 各機場 ----


def test_tpe_slots_codeshare_and_cross_date():
    stats = cancellations.airport_stats("RCTP", tpe_payload(), TPE_TZ, NOW)
    assert all(r["airport"] == "RCTP" and r["asOf"] == "2026-10-18T08:55:00Z" for r in stats)
    assert [(r["from"], r["to"]) for r in stats] == [
        ("2026-10-16T12:00:00Z", "2026-10-16T18:00:00Z"),
        ("2026-10-17T00:00:00Z", "2026-10-17T06:00:00Z"),
        ("2026-10-18T06:00:00Z", "2026-10-18T12:00:00Z"),
        ("2026-10-19T00:00:00Z", "2026-10-19T06:00:00Z"),
    ]
    s = by_slot(stats)
    # 當地 10/17 00:10–00:20 抵達 → UTC 10/16 16 點多；LJ733／KE5759 共掛只算一班
    assert s["2026-10-16T12:00:00Z"] == (counts(), counts(4))
    # UA166 取消（掛名列沒有，只有一列）
    assert s["2026-10-17T00:00:00Z"] == (counts(1, cancelled=1), counts())
    # 出發：CI162 晚 55 分（不算延誤），KE／DL 共掛不算；抵達：MU5005 狀態延遲、UA871 晚 90 分
    assert s["2026-10-18T06:00:00Z"] == (counts(1), counts(2, delayed=2))
    # CI279／JL5121 共掛取消算一班
    assert s["2026-10-19T00:00:00Z"] == (counts(), counts(1, cancelled=1))


def test_tpe_same_flight_in_two_terminals_counted_once():
    payload = tpe_payload()
    ci162 = next(r for r in payload["rows"] if r["flightNo"] == "162")
    payload["rows"].append({**ci162, "terminal": "2"})
    # 掛名列也重複一次（機型空白），一樣不算
    kl = next(r for r in payload["rows"] if r["flightNo"] == "5694")
    payload["rows"].append({**kl, "terminal": "2"})
    s = by_slot(cancellations.airport_stats("RCTP", payload, TPE_TZ, NOW))
    assert s["2026-10-18T06:00:00Z"][0] == counts(1)


def test_tpe_marketing_row_without_operator_still_counts():
    payload = tpe_payload()
    payload["rows"] = [r for r in payload["rows"] if r["flightNo"] != "733"]  # 拿掉營運列
    s = by_slot(cancellations.airport_stats("RCTP", payload, TPE_TZ, NOW))
    assert s["2026-10-16T12:00:00Z"][1] == counts(4)  # 剩下的 KE5759 自己算一班


def test_hkg_codeshare_dates_and_dedupe():
    hk = load_json("hkg_arrival.json")
    # 昨天、今天兩次查詢會重疊：同一份接兩次也只算一次
    payload = {"departure": [], "arrival": hk + hk}
    s = by_slot(cancellations.airport_stats("VHHH", payload, "Asia/Hong_Kong", NOW))
    # 10/17 23:50 HX613（三個班號）At gate 00:55 (18/10) 晚 65 分；
    # 10/18 00:00–00:10 的三班也在 UTC 10/17
    assert s["2026-10-17T12:00:00Z"] == (counts(), counts(4, delayed=1))
    assert s["2026-10-18T06:00:00Z"] == (counts(), counts(1, cancelled=1))  # CX774 Cancelled
    # 21:50 HB851 Est at 00:30 (19/10)：晚 160 分
    assert s["2026-10-18T12:00:00Z"] == (counts(), counts(1, delayed=1))
    assert len(s) == 3


def test_hkg_skips_cargo_groups():
    hk = load_json("hkg_arrival.json")
    payload = {"arrival": [{**g, "cargo": True} for g in hk]}
    assert cancellations.airport_stats("VHHH", payload, "Asia/Hong_Kong", NOW) == []


def test_tsa_master_codeshare_and_delay():
    payload = {"intlDeparture": load_json("tsa_intl_departure.json")}
    s = by_slot(cancellations.airport_stats("RCSS", payload, TPE_TZ, NOW))
    # Master 2、3 的掛名班號（MU8628、BR2178、FM3002、CI8005）不算
    assert s == {
        "2026-10-18T00:00:00Z": (counts(2), counts()),
        "2026-10-18T06:00:00Z": (counts(2, delayed=1), counts()),  # MU5098 延誤Delayed
    }


def test_tsa_cargo_skipped_and_year_wrap():
    row = load_json("tsa_intl_departure.json")[0]
    cargo = {**row, "AirDrType": "CGO", "AirLineNum": "999"}
    jan = {**row, "AirFlyDate": "0101", "ExpectDepartureTime": "0100", "RealDepartureTime": ""}
    payload = {"intlDeparture": [cargo, jan]}
    stats = cancellations.airport_stats("RCSS", payload, TPE_TZ, utc(2026, 12, 31, 20))
    assert [(r["from"], r["dep"]["total"]) for r in stats] == [("2026-12-31T12:00:00Z", 1)]


def test_khh_status_and_time_delay():
    payload = {"intlDeparture": load_json("khh_intdep.json")}
    s = by_slot(cancellations.airport_stats("RCKH", payload, TPE_TZ, NOW))
    assert s["2026-10-17T18:00:00Z"] == (counts(5), counts())  # 當地 07:00–07:15
    # TW672、Z2133 延遲；IT670 狀態「登機」但晚 61 分
    assert s["2026-10-18T06:00:00Z"] == (counts(3, delayed=3), counts())


def test_khh_list_before_rollover_is_yesterday():
    payload = {"intlDeparture": load_json("khh_intdep.json")}
    early = utc(2026, 10, 18, 20, 25)  # 當地 10/19 04:25，清單還是 10/18 的（07:00 已離站）
    tz = cancellations.ZoneInfo(TPE_TZ)
    assert str(cancellations.khh_list_date(payload, early.astimezone(tz))) == "2026-10-18"
    assert str(cancellations.khh_list_date(payload, NOW.astimezone(tz))) == "2026-10-18"
    s = by_slot(cancellations.airport_stats("RCKH", payload, TPE_TZ, early))
    assert s["2026-10-17T18:00:00Z"][0]["total"] == 5


def test_mfm_statuses():
    payload = {"departure": load_json("mfm_departure_en.json"), "arrival": []}
    s = by_slot(cancellations.airport_stats("VMMC", payload, "Asia/Macau", NOW))
    assert s == {
        "2026-10-17T18:00:00Z": (counts(3), counts()),
        "2026-10-18T00:00:00Z": (counts(3, cancelled=1), counts()),  # KR502 CANCELLED
        # AK187、NX992 DELAY UNTIL；Z2093 的 OPEN AT 16:55 是開櫃時間，不算
        "2026-10-18T06:00:00Z": (counts(3, delayed=2), counts()),
        "2026-10-18T12:00:00Z": (counts(2), counts()),  # RESCHEDULE 提早、"0" 還沒有狀態
    }


def _mfm_arrival(status, at="18-10 16:20"):
    row = {"time": at, "flightNo": "NX001", "origin": "Taipei", "status": status}
    return {"departure": [], "arrival": [{**row, "date": "18-10-2026"}]}


def test_mfm_chinese_landed_is_normal_arrival():
    """英文端點回中文狀態：`航班著陸 16:23` 是已降落、正常（不是取消、延誤、other）。"""
    stats = cancellations.airport_stats("VMMC", _mfm_arrival("航班著陸 16:23"), "Asia/Macau", NOW)
    assert by_slot(stats) == {"2026-10-18T06:00:00Z": (counts(), counts(1))}
    flights_ = cancellations.flights_of("VMMC", _mfm_arrival("航班著陸 16:23"), "Asia/Macau", NOW)
    assert cancellations.unknown_statuses(flights_) == {}


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("航班著陸 17:30", counts(1, delayed=1)),  # 時間拿來算延誤：晚 70 分
        ("航班起飛 16:25", counts(1)),
        ("著陸", counts(1)),
        ("已著陸", counts(1)),
        ("起飛", counts(1)),
        ("已起飛", counts(1)),
        ("航班取消", counts(1, cancelled=1)),
        ("延遲起飛", counts(1, delayed=1)),  # 不能因為有「起飛」就當正常
        ("航班改降", counts(1, other=1)),
    ],
)
def test_mfm_chinese_keywords(status, expected):
    stats = cancellations.airport_stats("VMMC", _mfm_arrival(status), "Asia/Macau", NOW)
    assert stats[0]["arr"] == expected


def test_unknown_statuses_merged_into_file(tmp_path):
    rows = load_json("khh_intdep.json")[:3]
    rows[0] = {**rows[0], "airFlyStatus": "改降"}
    rows[1] = {**rows[1], "airFlyStatus": " 改降 "}
    parsed = cancellations.flights_of("RCKH", {"intlDeparture": rows}, TPE_TZ, NOW)
    first = {"RCKH": cancellations.unknown_statuses(parsed), "VHHH": {}}
    path = cancellations.store_unknown(tmp_path, first, NOW)
    assert path == tmp_path / "cancellations" / "unknown-statuses.json"
    t1 = "2026-10-18T08:55:00Z"
    assert json.loads(path.read_text("utf-8")) == {
        "RCKH": {"改降": {"count": 2, "firstSeen": t1, "lastSeen": t1}},
        "VHHH": {},
    }
    later = utc(2026, 10, 18, 14, 33)
    cancellations.store_unknown(tmp_path, {"RCKH": {"改降": 1}, "VMMC": {"SOME STATUS": 3}}, later)
    t2 = "2026-10-18T14:33:00Z"
    data = json.loads(path.read_text("utf-8"))
    assert data == {
        "RCKH": {"改降": {"count": 3, "firstSeen": t1, "lastSeen": t2}},
        "VHHH": {},
        "VMMC": {"SOME STATUS": {"count": 3, "firstSeen": t2, "lastSeen": t2}},
    }
    # 只有狀態字串與次數，沒有班號、時間、航點
    assert "NX" not in path.read_text("utf-8") and "flight" not in path.read_text("utf-8")


def test_unknown_status_goes_to_other_and_logs_once(caplog):
    rows = load_json("khh_intdep.json")[:3]
    rows[0] = {**rows[0], "airFlyStatus": "改降"}
    rows[1] = {**rows[1], "airFlyStatus": "改降"}
    rows[2] = {**rows[2], "airFlyStatus": "取消（天候）"}  # 開頭是「取消」也認得
    with caplog.at_level(logging.WARNING, logger="hongthai"):
        stats = cancellations.airport_stats("RCKH", {"intlDeparture": rows}, TPE_TZ, NOW)
    assert stats[0]["dep"] == counts(3, cancelled=1, other=2)
    msgs = [r.getMessage() for r in caplog.records if "看不懂" in r.getMessage()]
    assert len(msgs) == 1 and "改降" in msgs[0]


def test_unknown_airport_raises():
    with pytest.raises(KeyError):
        cancellations.airport_stats("XXXX", {}, TPE_TZ, NOW)


def test_snapshot_wrapper_fields_ignored():
    """以前 gz 快照多包了 airport、fetchedAt，也能直接算。"""
    payload = {"airport": "VMMC", "fetchedAt": "2026-10-18T08:55:00Z"}
    payload["departure"] = load_json("mfm_departure_en.json")
    assert len(cancellations.airport_stats("VMMC", payload, "Asia/Macau", NOW)) == 4


# ---- 合併與存檔 ----


def row(frm, dep_total, arr_total=0, as_of="2026-10-18T01:05:00Z", airport="VHHH", cancelled=0):
    return {
        "airport": airport,
        "from": frm,
        "to": frm[:11] + f"{int(frm[11:13]) + 6:02d}" + frm[13:],
        "asOf": as_of,
        "dep": counts(dep_total, cancelled=cancelled),
        "arr": counts(arr_total),
    }


def test_merge_newer_wins_unless_total_shrinks():
    a = "2026-10-18T00:00:00Z"
    b = "2026-10-18T06:00:00Z"
    old = [row(a, 100, 100), row(b, 50, 50)]
    new = [
        row(a, 100, 100, as_of="2026-10-18T08:25:00Z", cancelled=3),  # 一樣多 → 新的
        row(b, 10, 0, as_of="2026-10-18T08:25:00Z"),  # 變少（來源換日）→ 留舊的
        row("2026-10-18T12:00:00Z", 5, as_of="2026-10-18T08:25:00Z"),  # 沒有的 → 加
    ]
    merged = cancellations.merge(old, new)
    assert [r["from"] for r in merged] == [a, b, "2026-10-18T12:00:00Z"]
    assert merged[0]["dep"]["cancelled"] == 3 and merged[0]["asOf"] == "2026-10-18T08:25:00Z"
    assert merged[1] == old[1]


def test_merge_sorted_by_airport_then_from():
    rows = [row("2026-10-18T06:00:00Z", 1, airport="VMMC"), row("2026-10-18T12:00:00Z", 1)]
    rows.append(row("2026-10-18T00:00:00Z", 1, airport="RCTP"))
    merged = cancellations.merge([], rows)
    assert [(r["airport"], r["from"][11:13]) for r in merged] == [
        ("RCTP", "00"),
        ("VHHH", "12"),
        ("VMMC", "06"),
    ]


def test_store_splits_by_utc_date_and_merges(tmp_path):
    stats = cancellations.airport_stats("RCTP", tpe_payload(), TPE_TZ, NOW)
    written = cancellations.store(tmp_path, stats)
    assert [p.name for p in written] == [
        "2026-10-16.json",
        "2026-10-17.json",
        "2026-10-18.json",
        "2026-10-19.json",
    ]
    path = tmp_path / "cancellations" / "2026-10-18.json"
    text = path.read_text("utf-8")
    assert text.startswith('[\n  {\n    "airport": "RCTP",')  # 兩個空白縮排
    assert json.loads(text)[0]["arr"] == counts(2, delayed=2)

    # 下一個跑次：桃園只剩 10/18 起的資料，10/16 那格消失不影響舊檔；10/18 那格被新的覆蓋
    later = utc(2026, 10, 18, 13, 5)
    payload = tpe_payload()
    payload["rows"] = [r for r in payload["rows"] if r["scheduledDate"] != "2026/10/17"]
    mfm = {"departure": load_json("mfm_departure_en.json")}
    stats2 = cancellations.airport_stats("RCTP", payload, TPE_TZ, later)
    stats2 += cancellations.airport_stats("VMMC", mfm, "Asia/Macau", later)
    cancellations.store(tmp_path, stats2)
    day16 = json.loads((tmp_path / "cancellations" / "2026-10-16.json").read_text("utf-8"))
    assert day16 == [r for r in stats if r["from"].startswith("2026-10-16")]
    day18 = json.loads(path.read_text("utf-8"))
    assert [(r["airport"], r["from"][11:13], r["asOf"][11:16]) for r in day18] == [
        ("RCTP", "06", "13:05"),
        ("VMMC", "00", "13:05"),
        ("VMMC", "06", "13:05"),
        ("VMMC", "12", "13:05"),
    ]
