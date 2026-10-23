"""事件保存（HD20）：期間判斷、每報快照、backfill、METAR／JMA／JTWC 的行與去重。"""

from __future__ import annotations

import json
from datetime import date

import pytest
from conftest import FIXTURES, ROOT, load_json, utc

from hongthai import build, events
from hongthai.config import Event, EventSeed, load_events
from hongthai.sources import SourceError, cwa, flights

FETCHED = utc(2026, 10, 20, 6, 7)
EV = Event(
    "29W",
    "CHAMPI",
    date(2026, 10, 19),
    date(2026, 10, 28),
    ("RCTP", "RJFF", "ROMY", "VHHH", "ZSPD", "RCBS", "RCFG"),
    "TC2636",
    "wp2926",
)


# ---- 設定與期間 ----


def test_events_json(airports):
    (e,) = load_events(ROOT / "events.json")
    assert (e.id, e.start, e.end, e.jma_tc_id, e.jtwc_id) == (
        "29W",
        date(2026, 10, 19),
        date(2026, 10, 28),
        "TC2636",
        "wp2926",
    )
    assert len(e.airports) == len(set(e.airports)) == 26
    assert set(e.airports) <= {a.icao for a in airports}
    # 金門、馬祖要有局屬站才拿得到觀測
    by = {a.icao: a for a in airports}
    assert by["RCBS"].cwa_station and by["RCFG"].cwa_station


@pytest.mark.parametrize(
    ("t", "on"),
    [
        (utc(2026, 10, 18, 15, 59), False),  # 台灣 10/18 23:59
        (utc(2026, 10, 18, 16, 0), True),  # 台灣 10/19 00:00
        (utc(2026, 10, 28, 15, 59), True),  # 台灣 10/28 23:59
        (utc(2026, 10, 28, 16, 0), False),  # 台灣 10/29 00:00
    ],
)
def test_active_taiwan_dates(t, on):
    assert events.active([EV], t) == ([EV] if on else [])


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"id": "../x"}, "只能有英數"),
        ({"to": "2026-10-18"}, "早於"),
        ({"airports": ["rctp"]}, "不是 ICAO"),
        ({"seed": [16, 135]}, "seed 要是物件"),
        ({"seed": {"lat": 16, "lon": 135, "at": ""}}, "seed 沒有 at"),
    ],
)
def test_events_json_rejected(tmp_path, change, message):
    e = {"id": "29W", "from": "2026-10-19", "to": "2026-10-28", "airports": ["RCTP"], **change}
    p = tmp_path / "events.json"
    p.write_text(json.dumps({"events": [e]}), "utf-8")
    with pytest.raises(ValueError, match=message):
        load_events(p)


def test_events_json_seed(tmp_path):
    """HD21：找颱風中心的備用起點（可以沒有）。"""
    e = {"id": "29W", "from": "2026-10-19", "to": "2026-10-28"}
    seed = {"lat": 16.0, "lon": 135.6, "at": "2026-10-20T00:00Z"}
    p = tmp_path / "events.json"
    p.write_text(json.dumps({"events": [{**e, "seed": seed}]}), "utf-8")
    (ev,) = load_events(p)
    assert ev.seed == EventSeed(16.0, 135.6, utc(2026, 10, 20))
    assert load_events(ROOT / "events.json")[0].seed is None


def test_events_json_missing_or_duplicate(tmp_path):
    assert load_events(tmp_path / "none.json") == []
    e = {"id": "29W", "from": "2026-10-19", "to": "2026-10-28"}
    p = tmp_path / "events.json"
    p.write_text(json.dumps({"events": [e, e]}), "utf-8")
    with pytest.raises(ValueError, match="重複"):
        load_events(p)


# ---- 每報快照與 backfill ----


def test_snapshot_path_and_content(tmp_path):
    history = tmp_path / "history"
    src = history / "20261020T0555Z.json"
    src.parent.mkdir(parents=True)
    src.write_text('{"generatedAt":"2026-10-20T05:55:00Z"}\n', "utf-8")
    (p,) = events.snapshot(history, [EV], utc(2026, 10, 20, 5, 55), src)
    assert p == history / "events" / "29W" / "20261020T0555Z.json"
    assert p.read_bytes() == src.read_bytes()
    # 期間外不存
    assert events.snapshot(history, [EV], utc(2026, 10, 18, 8), src) == []


def test_build_event_snapshots(tmp_path, caplog):
    history = tmp_path / "history"
    src = history / "20261021T0100Z.json"
    src.parent.mkdir(parents=True)
    src.write_text("{}\n", "utf-8")
    (tmp_path / "events.json").write_text((ROOT / "events.json").read_text("utf-8"), "utf-8")
    build.event_snapshots(tmp_path / "events.json", history, utc(2026, 10, 21, 1), src)
    assert (history / "events" / "29W" / src.name).exists()
    # events.json 壞了只 log，不讓 build 失敗
    (tmp_path / "bad.json").write_text("{", "utf-8")
    build.event_snapshots(tmp_path / "bad.json", history, utc(2026, 10, 21, 1), src)
    assert "事件快照失敗" in caplog.text


def test_backfill_skips_existing_and_out_of_period(tmp_path):
    history = tmp_path / "history"
    history.mkdir()
    for name in (
        "20261018T1433Z",  # 台灣 10/18 22:33，期間前
        "20261018T1615Z",  # 台灣 10/19 00:15
        "20261019T0357Z",
        "20261020T0555Z",
        "latest",  # 不是時間檔名
    ):
        (history / f"{name}.json").write_text(f'"{name}"\n', "utf-8")
    d = history / "events" / "29W"
    d.mkdir(parents=True)
    (d / "20261019T0357Z.json").write_text('"已存在"\n', "utf-8")
    assert events.backfill(history, [EV]) == {"29W": 2}
    assert sorted(p.name for p in d.glob("*.json")) == [
        "20261018T1615Z.json",
        "20261019T0357Z.json",
        "20261020T0555Z.json",
    ]
    assert (d / "20261019T0357Z.json").read_text("utf-8") == '"已存在"\n'
    assert events.backfill(history, [EV]) == {"29W": 0}


# ---- METAR ----


def test_metar_rows_and_dedupe(tmp_path):
    aw = load_json("events_metar_hours2.json")
    obs = cwa.parse_obs(load_json("cwa_o-a0003-001_obs.json"), ("467110",))
    rows = events.metar_rows(aw, {"RCBS": obs["467110"]}, EV.airports, FETCHED)
    # 半小時一報的站兩筆都留（不像 taf.parse_metars 只留最新的）
    assert sorted({r["icao"] for r in rows}) == ["RCBS", "RCTP", "RJFF", "ROMY", "VHHH", "ZSPD"]
    assert len(rows) == len(aw) + 1
    rjff = next(r for r in rows if r["icao"] == "RJFF" and r["gustKt"])
    assert rjff == {
        "t": "2026-10-20T06:07:00Z",
        "icao": "RJFF",
        "observedAt": "2026-10-20T05:00:00Z",
        "windDirDeg": 210,
        "windKt": 12,
        "gustKt": 22,
        "visibilityM": 9999,
        "wx": [],
        "raw": "METAR RJFF 200500Z 21012G22KT 170V240 9999 FEW020 BKN050 31/20 Q1014 NOSIG",
        "source": "aviationweather",
        "type": "METAR",
    }
    rcbs = next(r for r in rows if r["icao"] == "RCBS")
    assert (rcbs["source"], rcbs["type"], rcbs["observedAt"]) == (
        "cwa",
        None,
        "2026-10-18T08:00:00Z",
    )
    assert (rcbs["windKt"], rcbs["gustKt"], rcbs["wx"]) == (2.9, 6.2, ["FG"])

    d = tmp_path / "events" / "29W"
    assert events.store_metars(d, rows, FETCHED) == len(rows)
    # 再抓一次（一小時後、hours=3 會重複拿到）同樣的觀測不重複寫
    assert events.store_metars(d, rows, utc(2026, 10, 20, 7, 7)) == 0
    files = sorted(p.name for p in (d / "metar").iterdir())
    assert files == ["2026-10-18.jsonl", "2026-10-20.jsonl"]  # 觀測時間的 UTC 日期
    lines = (d / "metar" / "2026-10-20.jsonl").read_text("utf-8").splitlines()
    assert len(lines) == len(aw)
    assert json.loads(lines[0])["icao"] == aw[0]["icaoId"]


def test_metar_rows_only_event_airports():
    aw = load_json("events_metar_hours2.json")
    rows = events.metar_rows(aw, {}, ("RCTP",), FETCHED)
    assert {r["icao"] for r in rows} == {"RCTP"}


# ---- 颱風現報 ----


def test_parse_jma():
    rows = events.parse_jma(load_json("jma_tc2636_specifications.json"), FETCHED)
    assert [(r["kind"], r["leadHours"]) for r in rows] == [
        ("analysis", 0),
        ("forecast", 12),
        ("forecast", 24),
    ]
    a = rows[0]
    assert {k: v for k, v in a.items() if k != "raw"} == {
        "t": "2026-10-20T06:07:00Z",
        "issuedAt": "2026-10-20T03:45:00Z",
        "kind": "analysis",
        "leadHours": 0,
        "validAt": "2026-10-20T03:00:00Z",
        "lat": 16.2,
        "lon": 134.9,
        "pressureHpa": 945.0,
        "windKt": 100.0,
        "gustKt": 140.0,
        "source": "jma",
    }
    assert a["raw"]["location"] == "フィリピンの東"


def test_jma_target_lists_tc():
    (t,) = load_json("jma_targettc.json")
    assert (t["tropicalCyclone"], t["typhoonNumber"]) == ("TC2636", "2630")


def test_parse_jtwc():
    text = (FIXTURES / "jtwc_wp2926.tcw").read_bytes().decode("utf-8")
    rows = events.parse_jtwc(text, FETCHED)
    assert [r["leadHours"] for r in rows] == [0, 12, 24, 36, 48, 60, 72, 96, 120]
    assert {k: v for k, v in rows[0].items() if k != "raw"} == {
        "t": "2026-10-20T06:07:00Z",
        "issuedAt": "2026-10-20T03:00:00Z",
        "kind": "analysis",
        "leadHours": 0,
        "validAt": "2026-10-20T00:00:00Z",
        "lat": 15.9,
        "lon": 135.6,
        "pressureHpa": 929.0,
        "windKt": 130.0,
        "gustKt": 160.0,
        "source": "jtwc",
        "warning": 23,
    }
    assert rows[0]["raw"].startswith("T000 159N 1356E 130")
    last = rows[-1]
    assert (last["validAt"], last["lat"], last["lon"], last["windKt"], last["gustKt"]) == (
        "2026-10-25T00:00:00Z",
        30.0,
        125.9,
        40.0,
        50.0,
    )
    assert all(r["pressureHpa"] is None for r in rows[1:])
    assert events.parse_jtwc("<html>blocked</html>", FETCHED) == []


def test_ddhhmm_month_rollover():
    assert events._ddhhmm("01", "03", "00", utc(2026, 10, 31, 18)) == utc(2026, 11, 1, 3)
    assert events._ddhhmm("31", "21", "00", utc(2026, 11, 1, 0)) == utc(2026, 10, 31, 21)


class _Resp:
    def __init__(self, content: bytes):
        self.content = content
        self.status_code = 200

    def json(self):
        return json.loads(self.content)


def test_fetch_jtwc_raw_only_when_new(tmp_path, monkeypatch):
    body = (FIXTURES / "jtwc_wp2926.tcw").read_bytes()
    monkeypatch.setattr(events, "http_get", lambda url, **k: _Resp(body))
    d = tmp_path / "events" / "29W"
    assert events.fetch_jtwc(EV, d, FETCHED) == 9
    assert events.fetch_jtwc(EV, d, utc(2026, 10, 20, 7, 7)) == 0  # 同一報
    raws = sorted(p.name for p in (d / "position" / "raw").iterdir())
    assert raws == ["jtwc-20261020T0607Z.txt"]
    assert (d / "position" / "raw" / raws[0]).read_bytes() == body
    assert len((d / "position" / "jtwc-2026-10-20.jsonl").read_text("utf-8").splitlines()) == 9


def test_jma_positions_dedupe(tmp_path, monkeypatch):
    spec = (FIXTURES / "jma_tc2636_specifications.json").read_bytes()
    target = (FIXTURES / "jma_targettc.json").read_bytes()
    monkeypatch.setattr(
        events, "http_get", lambda url, **k: _Resp(target if "targetTc" in url else spec)
    )
    d = tmp_path / "events" / "29W"
    assert events.store_positions(d, "jma", events.fetch_jma(EV, FETCHED), FETCHED) == 3
    assert events.store_positions(d, "jma", events.fetch_jma(EV, FETCHED), FETCHED) == 0
    other = Event("30W", "", EV.start, EV.end, (), "TC9999", None)
    assert events.fetch_jma(other, FETCHED) == []  # JMA 目前沒有這顆


# ---- 每小時 ----


def test_hourly_failures_only_logged(tmp_path, monkeypatch, airports):
    def down(url, **k):
        raise SourceError(f"{url}: down", "network")

    monkeypatch.setattr(events, "http_get", down)
    monkeypatch.setattr(flights, "http_get", down)
    history = tmp_path / "history"
    res = events.hourly(history, [EV], airports, None, FETCHED)
    # METAR 兩邊各自接住（沒有金鑰也只 log）→ 0 行；JMA、JTWC 失敗是 None；
    # 航班每個機場各自接住（`flights.fetch`）→ 0 行
    assert res == {"29W": {"metar": 0, "jma": None, "jtwc": None, "flights": 0}}
    assert events.hourly(history, [EV], airports, None, utc(2026, 10, 29)) == {}


def _fake_flights(now):
    tpe = {"rows": flights.parse_tpe((FIXTURES / "tpe_flights_big5.txt").read_bytes())}
    hkg = {"departure": [], "arrival": load_json("hkg_arrival.json")}
    return flights.FlightsData({"RCTP": tpe, "VHHH": hkg, "VMMC": {}}, {"RCSS": "network"})


def test_hourly_writes_all_four(tmp_path, monkeypatch, airports):
    bodies = {
        "metar": (FIXTURES / "events_metar_hours2.json").read_bytes(),
        "targetTc": (FIXTURES / "jma_targettc.json").read_bytes(),
        "specifications": (FIXTURES / "jma_tc2636_specifications.json").read_bytes(),
        "wp2926": (FIXTURES / "jtwc_wp2926.tcw").read_bytes(),
    }
    monkeypatch.setattr(
        events, "http_get", lambda url, **k: _Resp(next(v for n, v in bodies.items() if n in url))
    )
    obs_asked = []
    monkeypatch.setattr(
        cwa,
        "fetch_obs",
        lambda key, st: obs_asked.append(st) or load_json("cwa_o-a0003-001_obs.json"),
    )
    monkeypatch.setattr(flights, "fetch", _fake_flights)
    history = tmp_path / "history"
    res = events.hourly(history, [EV], airports, "key", FETCHED)
    # 10 筆 AW＋金門、馬祖；航班只寫事件有的機場（EV 有 RCTP、VHHH）：桃園 9 班＋香港 6 班
    assert res == {"29W": {"metar": 12, "jma": 3, "jtwc": 9, "flights": 15}}
    assert obs_asked == [("467110", "467990")]
    d = history / "events" / "29W"
    assert sorted(p.name for p in (d / "position").glob("*.jsonl")) == [
        "jma-2026-10-20.jsonl",
        "jtwc-2026-10-20.jsonl",
    ]
    assert len(list((d / "flights").glob("*.jsonl"))) == 4  # 表定時間 UTC 10/16～10/19
    # 下一小時同樣的資料：航班不重寫
    later = utc(2026, 10, 20, 7, 7)
    assert events.hourly(history, [EV], airports, "key", later)["29W"]["flights"] == 0


def test_hourly_flights_failure_does_not_block_others(tmp_path, monkeypatch, airports):
    """第四件事（航班）整個失敗只記 log，前三件照寫。"""
    bodies = {
        "metar": (FIXTURES / "events_metar_hours2.json").read_bytes(),
        "targetTc": (FIXTURES / "jma_targettc.json").read_bytes(),
        "specifications": (FIXTURES / "jma_tc2636_specifications.json").read_bytes(),
        "wp2926": (FIXTURES / "jtwc_wp2926.tcw").read_bytes(),
    }
    monkeypatch.setattr(
        events, "http_get", lambda url, **k: _Resp(next(v for n, v in bodies.items() if n in url))
    )

    def boom(now):
        raise RuntimeError("壞了")

    monkeypatch.setattr(flights, "fetch", boom)
    history = tmp_path / "history"
    res = events.hourly(history, [EV], airports, None, FETCHED)
    assert res == {"29W": {"metar": 10, "jma": 3, "jtwc": 9, "flights": None}}
    assert not (history / "events" / "29W" / "flights").exists()


def test_hourly_flights_one_airport_bad(tmp_path, monkeypatch, airports):
    """一個機場的格式壞掉（解析例外）不擋另一個機場。"""

    def fake(now):
        data = _fake_flights(now)
        data.snapshots["VHHH"] = {"arrival": ["不是物件"]}
        return data

    monkeypatch.setattr(flights, "fetch", fake)
    d = tmp_path / "events" / "29W"
    assert events.fetch_flights(EV, airports, FETCHED, d) == {"RCTP": 9, "VHHH": None}


def test_hourly_out_of_period_no_flights(tmp_path, monkeypatch, airports):
    asked = []
    monkeypatch.setattr(flights, "fetch", lambda now: asked.append(now) or _fake_flights(now))
    history = tmp_path / "history"
    assert events.hourly(history, [EV], airports, None, utc(2026, 10, 18, 15, 59)) == {}
    assert asked == []
    assert not (history / "events").exists()


# ---- 補香港航班（HD31） ----


def test_backfill_flights(tmp_path, monkeypatch, airports):
    hkg = load_json("hkg_arrival.json")  # 香港 10/17、10/18 的組
    asked = []

    def get(url, params=None, **k):
        asked.append(params)
        body = hkg if params["arrival"] == "true" else []
        return _Resp(json.dumps(body).encode())

    monkeypatch.setattr(flights, "http_get", get)
    history = tmp_path / "history"
    d = history / "events" / "29W"
    # 每小時已經寫過的同一班同狀態不重寫
    have = [
        r
        for r in events.flights_log.rows_of(
            "VHHH", {"arrival": hkg, "departure": []}, "Asia/Hong_Kong", FETCHED
        )
        if r["flight"] == "HX613"
    ]
    assert events.store_flights(d, have) == 1
    pauses = []
    now = utc(2026, 10, 20, 20)  # 香港 10/21 04:00
    res = events.backfill_flights(history, [EV], airports, date(2026, 10, 19), now, pauses.append)
    # 10/19、10/20、10/21 三天；每天回同樣的 6 班，合併後 6 班，寫 5 行（HX613 已經有）
    days = dict.fromkeys(("2026-10-19", "2026-10-20", "2026-10-21"), 6)
    assert res == {"29W": {"days": days, "flights": 6, "written": 5}}
    assert [(p["date"], p["arrival"]) for p in asked] == [
        (day, a) for day in ("2026-10-19", "2026-10-20", "2026-10-21") for a in ("false", "true")
    ]
    assert len(pauses) == len(asked) - 1
    lines = [
        json.loads(x)
        for p in sorted((d / "flights").glob("*.jsonl"))
        for x in p.read_text().splitlines()
    ]
    assert len(lines) == 6
    assert [r.get("backfill") for r in lines if r["flight"] == "HX613"] == [None]
    assert all(r["backfill"] is True for r in lines if r["flight"] != "HX613")
    assert {r["t"] for r in lines if r.get("backfill")} == {"2026-10-20T20:00:00Z"}


def test_backfill_flights_keeps_fresher_copy(tmp_path, monkeypatch, airports):
    """同一班在 10/19 的回應（較新）和 10/20 的回應（帶前一天的尾巴、較舊）各一份：
    只寫較新的那份。"""
    item = {"time": "23:15", "flight": [{"no": "CX 271"}], "destination": ["NRT"]}

    def group(day, updated, status):
        return {
            "date": day,
            "arrival": False,
            "cargo": False,
            "lastUpdatedTime": updated,
            "list": [{**item, "status": status}],
        }

    bodies = {
        "2026-10-19": [group("2026-10-19", "2026-10-20T00:37:13+08:00", "Dep 00:15 (20/10/2026)")],
        "2026-10-20": [group("2026-10-19", "2026-10-19T23:40:42+08:00", "Boarding")],
    }

    def get(url, params=None, **k):
        body = [] if params["arrival"] == "true" else bodies[params["date"]]
        return _Resp(json.dumps(body).encode())

    monkeypatch.setattr(flights, "http_get", get)
    history = tmp_path / "history"
    now = utc(2026, 10, 19, 20)  # 香港 10/20
    res = events.backfill_flights(history, [EV], airports, date(2026, 10, 19), now, lambda s: None)
    assert res == {"29W": {"days": {"2026-10-19": 1, "2026-10-20": 1}, "flights": 1, "written": 1}}
    (line,) = (history / "events" / "29W" / "flights" / "2026-10-19.jsonl").read_text().splitlines()
    assert json.loads(line)["status"] == "Dep 00:15 (20/10/2026)"


def test_backfill_flights_failure_and_out_of_period(tmp_path, monkeypatch, airports):
    def down(url, **k):
        raise SourceError(f"{url}: down", "network")

    monkeypatch.setattr(flights, "http_get", down)
    history = tmp_path / "history"
    now = utc(2026, 10, 19, 20)  # 香港 10/20
    res = events.backfill_flights(history, [EV], airports, date(2026, 10, 19), now, lambda s: None)
    assert res == {
        "29W": {"days": {"2026-10-19": None, "2026-10-20": None}, "flights": 0, "written": 0}
    }
    # 事件期間（10-19～10-28）外、或事件沒有香港：不抓
    late = utc(2026, 10, 30)
    assert events.backfill_flights(history, [EV], airports, date(2026, 10, 29), late) == {}
    no_hkg = Event("30W", "", EV.start, EV.end, ("RCTP",), None, None)
    assert events.backfill_flights(history, [no_hkg], airports, date(2026, 10, 19), now) == {}


# ---- 補 METAR 缺口（HD25） ----


def test_metar_hours_six():
    assert events.METAR_HOURS == 6


def test_backfill_metar(tmp_path, monkeypatch, airports):
    """一站一站、每次最多 72 小時往回抓；期間外的不收、已有的不覆蓋、補進來的多 `backfill`；
    金門、馬祖（氣象署觀測）不抓。"""
    aw = load_json("events_metar_hours2.json")  # 2026-10-20 05:00～06:00Z
    asked = []

    def get(url, params=None, **k):
        asked.append(params)
        return _Resp(json.dumps(aw).encode())

    monkeypatch.setattr(events, "http_get", get)
    history = tmp_path / "history"
    d = history / "events" / "29W"
    # 已經有的那筆（每小時抓的）不覆蓋
    have = events.metar_rows(aw, {}, ("RCTP",), FETCHED)
    events.store_metars(d, [r for r in have if r["observedAt"] == "2026-10-20T06:00:00Z"], FETCHED)
    pauses = []
    since, now = utc(2026, 10, 20, 5, 15), utc(2026, 10, 23, 7, 0)  # 3 天 1 小時 45 分 → 兩段
    res = events.backfill_metar(history, [EV], airports, since, now, pauses.append)
    assert res == {"29W": {"RCTP": 1, "RJFF": 2, "ROMY": 1, "VHHH": 2, "ZSPD": 2}}
    stations = [p["ids"] for p in asked]
    assert stations == [s for s in ("RCTP", "RJFF", "ROMY", "VHHH", "ZSPD") for _ in (1, 2)]
    assert asked[:2] == [
        {"ids": "RCTP", "date": "2026-10-23T07:00:00Z", "hours": 72, "format": "json"},
        {"ids": "RCTP", "date": "2026-10-20T07:00:00Z", "hours": 2, "format": "json"},
    ]
    assert len(pauses) == len(asked) - 1
    lines = [json.loads(x) for x in (d / "metar" / "2026-10-20.jsonl").read_text().splitlines()]
    rctp = [r for r in lines if r["icao"] == "RCTP"]
    assert [(r["observedAt"], r.get("backfill")) for r in rctp] == [
        ("2026-10-20T06:00:00Z", None),  # 原本的
        ("2026-10-20T05:30:00Z", "aviationweather"),
    ]
    # RJFF 05:00 在 since 之前，不收
    assert {r["observedAt"] for r in lines if r["icao"] == "RJFF"} == {
        "2026-10-20T06:00:00Z",
        "2026-10-20T05:30:00Z",
    }
    assert events.metar_coverage(d)["RCTP"] == {"2026-10-20": 2}
    # 再跑一次全部已經有
    assert events.backfill_metar(history, [EV], airports, since, now, pauses.append) == {
        "29W": dict.fromkeys(("RCTP", "RJFF", "ROMY", "VHHH", "ZSPD"), 0)
    }


def test_backfill_metar_failure_and_out_of_period(tmp_path, monkeypatch, airports):
    def down(url, **k):
        raise SourceError(f"{url}: down", "network")

    monkeypatch.setattr(events, "http_get", down)
    history = tmp_path / "history"
    res = events.backfill_metar(
        history, [EV], airports, utc(2026, 10, 20), utc(2026, 10, 21), lambda s: None
    )
    assert res == {"29W": dict.fromkeys(("RCTP", "RJFF", "ROMY", "VHHH", "ZSPD"))}
    # 事件期間（台灣 10-19～10-28）外不抓
    assert (
        events.backfill_metar(
            history, [EV], airports, utc(2026, 10, 29), utc(2026, 10, 30), lambda s: None
        )
        == {}
    )
