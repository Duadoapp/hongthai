"""HD38：航班取消、延誤數進 `latest.json`（`slots[].flights`、`airports[].flightSources`、
`sources.tdx`）；平常每報抓 TDX 補台灣其他 7 個機場、每月呼叫上限；新分類（加班、轉降、預計時間）；
3 小時格的統計。"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from conftest import load_json, utc
from test_build import _boom, _flights_from_fixtures, workspace  # noqa: F401 pytest fixture

from hongthai import build, cancellations, flights_log
from hongthai.cancellations import Flight
from hongthai.sources import tdx

TW = "Asia/Taipei"
NOW = utc(2026, 10, 23, 6, 7)  # TDX fixture 的時間
NOW_ORIG = utc(2026, 10, 18, 8, 10)  # 原本五個來源 fixture 的時間（同 test_build.NOW）
ORIGINAL = {"RCTP", "RCSS", "RCKH", "VHHH", "VMMC"}
TDX_SEVEN = {"RCMQ", "RCNN", "RCYU", "RCFN", "RCQC", "RCBS", "RCFG"}


class FakeClient:
    """`tdx.Client` 的替身：`fids` 回 fixture（只有 RMQ、KNH、TPE、TSA 四個機場）。"""

    def __init__(self, fail: Exception | None = None):
        self.asked: list[tuple[str, ...]] = []
        self.calls = 0
        self.fail = fail

    def fids(self, iatas):
        want = tuple(sorted(set(iatas)))
        self.asked.append(want)
        self.calls += 1
        if self.fail is not None:
            raise self.fail
        body = load_json("tdx_fids_airport.json")
        return {a["AirportID"]: a for a in body if a["AirportID"] in want}


def _flight(direction, sched, category=cancellations.OK, no="X1"):
    return Flight(direction, (direction, no, sched), sched, category, "", no)


# ---- 新分類（cancellations.py 正式補上 HD37 報告工具的三種） ----


@pytest.mark.parametrize(
    ("status", "cat"),
    [
        ("加班", cancellations.OK),
        ("加班機", cancellations.OK),
        ("轉降", cancellations.DIVERTED),
        ("轉降高雄", cancellations.DIVERTED),
        ("預計15:40到站", cancellations.OK),
        ("預計19:00出發", cancellations.OK),
        ("預計07:05離站", cancellations.OK),
        ("預計10/25 01:30到站", cancellations.OK),
        ("檢查", cancellations.OTHER),
        ("回航", cancellations.OTHER),
        ("取消", cancellations.CANCELLED),
    ],
)
def test_tw_rules(status, cat):
    assert cancellations._lookup(cancellations.KHH_STATUS, status) == cat


def test_tw_expected_with_and_without_date():
    tz = cancellations.ZoneInfo(TW)
    sched = cancellations.datetime(2026, 10, 24, 23, 35, tzinfo=tz)
    # 沒寫日期：放在表定前 6 小時到後 18 小時之間（00:40 是隔天）
    assert cancellations.tw_expected("預計00:40到站", sched) == sched + timedelta(minutes=65)
    assert cancellations.tw_expected("預計23:20到站", sched) == sched - timedelta(minutes=15)
    # 寫了月日照它
    assert cancellations.tw_expected("預計10/25 01:00到站", sched) == sched + timedelta(
        hours=1, minutes=25
    )
    assert cancellations.tw_expected("預計10/26 01:00到站", sched) == sched + timedelta(
        hours=25, minutes=25
    )
    assert cancellations.tw_expected("準時", sched) is None


def test_tdx_expected_time_from_status_and_diverted():
    one = {
        "AirportID": "KHH",
        "FIDSArrival": [
            {  # 預計時間只在狀態裡：晚 70 分 → 延誤，時間寫進 estUtc
                "AirlineID": "IT",
                "FlightNumber": "773",
                "DepartureAirportID": "SDJ",
                "ScheduleArrivalTime": "2026-10-24T22:30",
                "ArrivalRemark": "預計23:40到站",
            },
            {  # 晚 30 分 → 正常
                "AirlineID": "IT",
                "FlightNumber": "775",
                "DepartureAirportID": "SDJ",
                "ScheduleArrivalTime": "2026-10-24T22:30",
                "ArrivalRemark": "預計23:00到站",
            },
            {
                "AirlineID": "CA",
                "FlightNumber": "197",
                "DepartureAirportID": "SHA",
                "ScheduleArrivalTime": "2026-10-24T14:15",
                "ActualArrivalTime": "2026-10-24T15:55",
                "ArrivalRemark": "轉降",
            },
        ],
    }
    rs = {r["flight"]: r for r in flights_log.tdx_rows("RCSS", one, TW, NOW)}
    assert (rs["IT773"]["class"], rs["IT773"]["estUtc"]) == ("delayed", "2026-10-24T15:40:00Z")
    assert rs["IT775"]["class"] == "normal"
    assert rs["CA197"]["class"] == "diverted"
    stats = cancellations.slot_stats("RCSS", flights_log.tdx_flights(one, TW), NOW)
    arr = {r["from"]: r["arr"] for r in stats}
    assert arr["2026-10-24T12:00:00Z"] == {
        "total": 2,
        "cancelled": 0,
        "delayed": 1,
        "diverted": 0,
        "other": 0,
    }
    assert arr["2026-10-24T06:00:00Z"]["diverted"] == 1


def test_original_tw_sources_use_expected_time_from_status():
    # 高雄：表定 10:00、`realTime` 空白、狀態「預計11:30到站」→ 延誤
    payload = {
        "intlArrival": [
            {"expectTime": "10:00", "realTime": "", "airFlyStatus": "預計11:30到站"},
            {"expectTime": "12:00", "realTime": "", "airFlyStatus": "轉降"},
        ]
    }
    got = cancellations.flights_of("RCKH", payload, TW, NOW_ORIG)
    assert sorted(f.category for f in got) == ["delayed", "diverted"]


# ---- few、slot_json ----


@pytest.mark.parametrize(("n", "few"), [(3, True), (4, False)])
def test_few_boundary(n, few):
    t0 = utc(2026, 10, 23, 6)
    flights = [_flight("dep", t0 + timedelta(minutes=i), no=f"X{i}") for i in range(n - 1)]
    flights.append(_flight("arr", t0, cancellations.CANCELLED, no="Y"))
    (row,) = cancellations.slot_stats("RCQC", flights, NOW)
    got = cancellations.slot_json(row, "tdx")
    assert got == {
        "total": n,
        "cancelled": 1,
        "delayed": 0,
        "diverted": 0,
        "few": few,
        "source": "tdx",
        "asOf": "2026-10-23T06:07:00Z",
        "dep": {"total": n - 1, "cancelled": 0, "delayed": 0, "diverted": 0},
        "arr": {"total": 1, "cancelled": 1, "delayed": 0, "diverted": 0},
    }
    assert cancellations.FEW_FLIGHTS == 4


def test_slot_json_old_row_without_diverted():
    old = {
        "airport": "RCTP",
        "from": "2026-10-18T06:00:00Z",
        "asOf": "2026-10-18T05:06:00Z",
        "dep": {"total": 3, "cancelled": 1, "delayed": 0, "other": 1},
        "arr": {"total": 2, "cancelled": 0, "delayed": 1, "other": 0},
    }
    got = cancellations.slot_json(old, "taoyuan-airport")
    assert (got["total"], got["diverted"], got["few"]) == (5, 0, False)
    assert "other" not in got and "other" not in got["dep"]


def test_three_hour_slots():
    t0 = utc(2026, 10, 23, 6)
    flights = [
        _flight("dep", t0, no="A"),
        _flight("dep", t0 + timedelta(hours=2, minutes=59), cancellations.CANCELLED, no="B"),
        _flight("arr", t0 + timedelta(hours=3), cancellations.DELAYED, no="C"),
    ]
    rows = cancellations.slot_stats("RCFN", flights, NOW, 3)
    assert [(r["from"], r["to"]) for r in rows] == [
        ("2026-10-23T06:00:00Z", "2026-10-23T09:00:00Z"),
        ("2026-10-23T09:00:00Z", "2026-10-23T12:00:00Z"),
    ]
    assert [cancellations.slot_json(r, "tdx")["cancelled"] for r in rows] == [1, 0]
    slots = [{"from": "2026-10-23T06:00:00Z"}, {"from": "2026-10-23T09:00:00Z"}, {"from": "x"}]
    build.slot_flights(slots, rows, "tdx")
    assert [s["flights"]["total"] for s in slots[:2]] == [2, 1]
    assert "flights" not in slots[2]  # 那格沒有航班不寫


# ---- TDX：哪些機場、失敗、每月上限 ----


def test_tdx_airports_ten_requested_seven_counted(airports):
    want, fill = build.tdx_airports(airports)
    assert len(want) == 10
    assert {a.icao for a in fill} == TDX_SEVEN
    assert not {a.icao for a in fill} & ORIGINAL


def test_tdx_stats_only_fills_seven(tmp_path, airports):
    client = FakeClient()
    fs = build.tdx_stats(client, airports, NOW, tmp_path)  # type: ignore[arg-type]
    assert client.asked == [tuple(sorted(a.iata for a in build.tdx_airports(airports)[0]))]
    # fixture 有台中、金門、桃園、松山：桃園、松山照舊用原本的來源，不重複
    assert set(fs.rows) == set(fs.source) == {"RCMQ", "RCBS"}
    assert set(fs.source.values()) == {"tdx"}
    assert fs.status["ok"] is True
    assert (fs.status["calls"], fs.status["monthCalls"]) == (1, 1)
    # fixture 沒有的五個機場記在 statsError
    missing = {k.split(":")[0] for k in fs.status["statsError"].split("; ")}
    assert missing == TDX_SEVEN - {"RCMQ", "RCBS"}
    # 3 小時格也算
    assert set(fs.rows3h) == {"RCMQ", "RCBS"}
    # 看不懂的狀態照樣合併進 unknown-statuses.json（fixture 都看得懂 → 每個機場是空的）
    unknown = tmp_path / "cancellations" / "unknown-statuses.json"
    assert json.loads(unknown.read_text("utf-8")) == {"RCBS": {}, "RCMQ": {}}


def test_tdx_stats_failure_and_not_configured(tmp_path, airports):
    fs = build.tdx_stats(None, airports, NOW, tmp_path)
    assert fs.status == {"ok": False, "error": "not_configured", "calls": 0} and not fs.rows
    client = FakeClient(fail=tdx.TdxError("TDX token：HTTP 401", "token_http"))
    fs = build.tdx_stats(client, airports, NOW, tmp_path)  # type: ignore[arg-type]
    assert fs.status == {"ok": False, "error": "token_http", "calls": 1, "monthCalls": 1}
    assert not fs.rows


def _timing(history, calls: list[object]):
    path = history / "timing" / "2026-10.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps({"run": "2026-10-20T08:25:00Z", "source": "tdx", "ok": True, "calls": c})
        for c in calls
    ]
    lines.append(json.dumps({"run": "x", "source": "openmeteo", "calls": 99}))  # 別的來源不算
    lines.append(json.dumps({"run": "y", "source": "tdx", "ok": False, "error": "timeout"}))
    path.write_text("\n".join(lines) + "\n", "utf-8")


def _event_rows(history, day: str, stamps: list[str], source="tdx"):
    path = history / "events" / "29W" / "flights" / f"{day}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for t in stamps:
            for no in ("A1", "A2"):  # 同一次請求寫好幾行，只算一次
                row = {"t": t, "airport": "RCMQ", "flight": no, "source": source}
                f.write(json.dumps(row, ensure_ascii=False) + "\n")


def test_month_calls_build_plus_events(tmp_path):
    _timing(tmp_path, [1, 1, 0])  # 2 次＋超過預算那次當 1 次
    _event_rows(tmp_path, "2026-10-22", ["2026-10-22T01:07:00Z", "2026-10-22T02:07:00Z"])
    _event_rows(tmp_path, "2026-10-23", ["2026-10-22T02:07:00Z"])  # 同一個 t 不重複算
    _event_rows(tmp_path, "2026-10-30", ["2026-09-30T23:07:00Z"])  # 上個月抓的不算
    _event_rows(tmp_path, "2026-10-24", ["2026-10-24T03:07:00Z"], source="kia")  # 原本的來源不算
    assert build.tdx_month_calls(tmp_path, NOW) == 3 + 2
    assert build.tdx_month_calls(tmp_path, utc(2026, 11, 1, 1, 5)) == 0


def test_monthly_limit_skips_tdx(tmp_path, airports, caplog):
    _timing(tmp_path, [1] * (tdx.MONTHLY_CALL_LIMIT - 1))  # ＋timeout 那行＝上限
    client = FakeClient()
    fs = build.tdx_stats(client, airports, NOW, tmp_path)  # type: ignore[arg-type]
    assert fs.status == {
        "ok": False,
        "error": "monthly_limit",
        "calls": 0,
        "monthCalls": tdx.MONTHLY_CALL_LIMIT,
    }
    assert client.asked == [] and not fs.rows
    assert "TDX 本月已用" in caplog.text
    assert tdx.MONTHLY_CALL_LIMIT == 600


# ---- 整報：latest.json 的新欄位 ----


@pytest.fixture
def no_models(monkeypatch):
    """整報的測試不連網：模式與官方來源都失敗（同 test_build 的航班測試）。"""
    for mod in (build.ecmwf, build.gfs, build.taf, build.hko, build.smg):
        monkeypatch.setattr(mod, "fetch", _boom)


def _slots_with_flights(out, icao):
    a = next(a for a in out["airports"] if a["icao"] == icao)
    return {s["from"]: s["flights"] for s in a["slots"] if "flights" in s}


def test_build_writes_tdx_flights_into_latest(workspace, monkeypatch, no_models):  # noqa: F811
    client = FakeClient()
    monkeypatch.setattr(build.tdx.Client, "from_env", classmethod(lambda cls: client))
    monkeypatch.setattr(build, "utcnow", lambda: NOW)
    assert build.main([]) == 0
    out = json.loads((workspace / "public" / "latest.json").read_text("utf-8"))
    st = out["sources"]["tdx"]
    assert (st["ok"], st["calls"], st["monthCalls"]) == (True, 1, 1)
    by = {a["icao"]: a for a in out["airports"]}
    assert by["RCMQ"]["flightSources"] == ["tdx"] and by["RCBS"]["flightSources"] == ["tdx"]
    # 沒有航班資料的機場：flightSources 是 []、每格都沒有 flights
    for icao in ("RCTP", "RCSS", "RJTT", "RCNN"):
        assert by[icao]["flightSources"] == []
        assert all("flights" not in s for s in by[icao]["slots"])
    rmq = _slots_with_flights(out, "RCMQ")
    # 台中 fixture 只有一班落在 slots 裡（10/23 台灣 23:40 抵達）：班次少
    assert rmq == {
        "2026-10-23T12:00:00Z": {
            "total": 1,
            "cancelled": 0,
            "delayed": 0,
            "diverted": 0,
            "few": True,
            "source": "tdx",
            "asOf": "2026-10-23T06:07:00Z",
            "dep": {"total": 0, "cancelled": 0, "delayed": 0, "diverted": 0},
            "arr": {"total": 1, "cancelled": 0, "delayed": 0, "diverted": 0},
        }
    }
    assert all(f["source"] == "tdx" for f in _slots_with_flights(out, "RCBS").values())
    # TDX 不寫 history/cancellations/ 的格統計（只有 unknown-statuses.json）
    cdir = workspace / "data" / "history" / "cancellations"
    assert [p.name for p in cdir.iterdir()] == ["unknown-statuses.json"]
    # 耗時紀錄記了 calls，下一報數得到
    assert build.tdx_month_calls(workspace / "data" / "history", NOW) == 1


def test_build_original_sources_into_latest(workspace, monkeypatch, no_models):  # noqa: F811
    monkeypatch.setattr(build.flights, "fetch", lambda now: _flights_from_fixtures())
    monkeypatch.setattr(build, "utcnow", lambda: NOW_ORIG)
    # history 裡已經有同一格、班數比較多的舊列 → 照存檔的合併規則留舊的
    cdir = workspace / "data" / "history" / "cancellations"
    cdir.mkdir(parents=True)
    old = {
        "airport": "RCTP",
        "from": "2026-10-19T00:00:00Z",
        "to": "2026-10-19T06:00:00Z",
        "asOf": "2026-10-18T05:06:00Z",
        "dep": {"total": 9, "cancelled": 0, "delayed": 0, "other": 0},
        "arr": {"total": 1, "cancelled": 1, "delayed": 0, "other": 0},
    }
    (cdir / "2026-10-19.json").write_text(json.dumps([old]), "utf-8")
    assert build.main([]) == 0
    out = json.loads((workspace / "public" / "latest.json").read_text("utf-8"))
    by = {a["icao"]: a for a in out["airports"]}
    assert by["RCTP"]["flightSources"] == ["taoyuan-airport"]
    assert by["VHHH"]["flightSources"] == ["hongkongairport"]
    assert by["RCSS"]["flightSources"] == ["tsa"] and by["RCKH"]["flightSources"] == ["kia"]
    assert by["VMMC"]["flightSources"] == []  # 這一報統計失敗
    tpe = _slots_with_flights(out, "RCTP")
    # 出發 CI162 正常；抵達 MU5005 狀態延遲、UA871 晚 90 分（同 test_cancellations）
    assert tpe["2026-10-18T06:00:00Z"] == {
        "total": 3,
        "cancelled": 0,
        "delayed": 2,
        "diverted": 0,
        "few": True,
        "source": "taoyuan-airport",
        "asOf": "2026-10-18T08:10:00Z",
        "dep": {"total": 1, "cancelled": 0, "delayed": 0, "diverted": 0},
        "arr": {"total": 2, "cancelled": 0, "delayed": 2, "diverted": 0},
    }
    assert tpe["2026-10-19T00:00:00Z"]["total"] == 10  # 舊列留著
    assert tpe["2026-10-19T00:00:00Z"]["asOf"] == "2026-10-18T05:06:00Z"
    # TDX 沒設金鑰：sources.tdx 記 not_configured，原本的照出
    assert out["sources"]["tdx"]["error"] == "not_configured"
    # TDX 七個機場沒資料
    assert all(by[i]["flightSources"] == [] for i in TDX_SEVEN)
