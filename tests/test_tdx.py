"""HD32 TDX 航空即時航班：認證與請求（`sources/tdx.py`）、逐班轉換與分類（`flights_log.tdx_rows`）、
只在變化時寫、和原本來源各存各的、沒有 secret 跳過、token 失敗只記 log。"""

from __future__ import annotations

import json
import logging
from datetime import date

import pytest
import requests
from conftest import FIXTURES, load_json, utc

from hongthai import events, flights_log
from hongthai.config import Event
from hongthai.sources import flights, tdx

FETCHED = utc(2026, 10, 23, 6, 7)
TW = "Asia/Taipei"
ID, SECRET = "my-client-id", "s3cret-value-never-logged"
EV = Event(
    "29W",
    "CHAMPI",
    date(2026, 10, 19),
    date(2026, 10, 28),
    ("RCTP", "RCSS", "RCMQ", "RCBS", "VHHH"),
    "TC2636",
    "wp2926",
)


def fids(iata: str) -> dict:
    return next(a for a in load_json("tdx_fids_airport.json") if a["AirportID"] == iata)


def by_flight(rows):
    return {r["flight"]: r for r in rows}


class _Resp:
    def __init__(self, body: object, status: int = 200, headers: dict | None = None):
        self.content = json.dumps(body).encode()
        self.status_code = status
        self.headers = headers or {}

    def json(self):
        return json.loads(self.content)


# ---- 逐班轉換與分類 ----


def test_tdx_rows_taichung():
    rs = by_flight(flights_log.tdx_rows("RCMQ", fids("RMQ"), TW, FETCHED))
    # 貨機（IsCargo）不存
    assert set(rs) == {"B78701", "B78702", "B78703", "AE8501", "AE8504"}
    assert rs["B78701"] == {
        "t": "2026-10-23T06:07:00Z",
        "airport": "RCMQ",
        "dir": "dep",
        "flight": "B78701",
        "codeshares": [],
        "peer": "MZG",
        "schedUtc": "2026-10-22T23:30:00Z",  # 台灣 10/23 07:30 → UTC 前一天
        "estUtc": None,
        "actUtc": "2026-10-22T23:41:00Z",  # 有實際時間 → actUtc
        "status": "已飛",
        "class": "normal",
        "source": "tdx",
    }
    assert rs["B78703"]["class"] == "cancelled"  # 「取消」
    assert rs["B78702"]["class"] == "delayed"  # 「延誤」
    assert rs["B78702"]["estUtc"] == "2026-10-23T01:20:00Z"
    # 「準時」但預計比表定晚 75 分鐘 → 延誤（和 cancellations.py 同一條 60 分鐘規則）
    assert rs["AE8501"]["class"] == "delayed"
    assert rs["AE8501"]["status"] == "準時"
    # 空白狀態是正常；預計時間帶日期，跨 UTC 日也照實
    assert rs["AE8504"]["class"] == "normal"
    assert rs["AE8504"]["schedUtc"] == "2026-10-23T15:40:00Z"
    assert rs["AE8504"]["estUtc"] == "2026-10-23T16:20:00Z"


def test_tdx_rows_codeshares_unknown_and_skipped(caplog):
    with caplog.at_level(logging.WARNING, "hongthai"):
        rs = by_flight(flights_log.tdx_rows("RCBS", fids("KNH"), TW, FETCHED))
    # CI9271 列在 AE1271 的 CodeShare 裡、同一個表定時間 → 掛名列，不另成一班
    assert set(rs) == {"AE1271", "AE1273"}
    assert rs["AE1271"]["codeshares"] == ["CI9271"]
    assert rs["AE1271"]["class"] == "normal"  # 時間更改
    # 「加班機」HD32 時是對照表沒列的 other；HD38 起開頭「加班」→ 正常，不再記 log
    assert rs["AE1273"]["class"] == "normal"
    assert "看不懂的狀態" not in caplog.text
    # 沒有表定時間的那筆跳過、記 log
    assert "1 筆沒有表定時間或班號" in caplog.text


def test_tdx_rows_taoyuan_and_songshan():
    tpe = by_flight(flights_log.tdx_rows("RCTP", fids("TPE"), TW, FETCHED))
    # CodeShare 是物件陣列也接
    assert tpe["CI162"]["codeshares"] == ["KE5694", "DL7719"]
    assert tpe["CI162"]["schedUtc"] == "2026-10-23T23:30:00Z"
    # 班號已含航空公司代碼不重複加；時間帶 +08:00 照它的；中文狀態空白用英文
    assert tpe["BR198"]["schedUtc"] == "2026-10-23T05:05:00Z"
    assert tpe["BR198"]["actUtc"] == "2026-10-23T05:01:00Z"
    assert tpe["BR198"]["status"] == "ARRIVED"
    tsa = by_flight(flights_log.tdx_rows("RCSS", fids("TSA"), TW, FETCHED))
    # 「已到」沒有實際時間：預計時間當實際（同桃園「已到」）
    assert tsa["AE1272"]["actUtc"] == "2026-10-23T03:25:00Z"
    assert tsa["AE1272"]["estUtc"] is None


@pytest.mark.parametrize(
    ("zh", "en", "cls"),
    [
        ("取消", "CANCELLED", "cancelled"),
        ("取消CANCELLED", "", "cancelled"),
        ("取消(天候)", "", "cancelled"),  # 台灣規則：開頭「取消」
        ("延遲", "", "delayed"),
        ("延誤DELAYED", "", "delayed"),
        ("延誤至14:30", "", "delayed"),  # 台灣規則：開頭「延誤」
        ("已到", "ARRIVED", "normal"),
        ("離站", "", "normal"),
        ("", "CANCELLED", "cancelled"),  # 中文空白用英文
        ("", "", "normal"),
        # HD38（HD37 報告工具先補的三種，2026-10-22～24 TDX 實際看到）
        ("加班", "", "normal"),
        ("加班機", "EXTRA", "normal"),
        ("轉降", "", "diverted"),
        ("預計12:30離站", "", "normal"),  # 表定 12:00，晚 30 分
        ("預計13:00出發", "", "delayed"),  # 晚 60 分（狀態裡的時間當預計時間）
        ("檢查", "", "other"),  # 還是看不懂的
    ],
)
def test_tdx_status_rules(zh, en, cls):
    one = {
        "AirportID": "HUN",
        "FIDSDeparture": [
            {
                "AirlineID": "AE",
                "FlightNumber": "391",
                "ArrivalAirportID": "TSA",
                "ScheduleDepartureTime": "2026-10-23T12:00",
                "DepartureRemark": zh,
                "DepartureRemarkEn": en,
            }
        ],
    }
    (row,) = flights_log.tdx_rows("RCYU", one, TW, FETCHED)
    assert row["class"] == cls


def test_tdx_same_flight_twice_keeps_most_severe():
    base = {"AirlineID": "B7", "FlightNumber": "8611", "ScheduleArrivalTime": "2026-10-23T09:00"}
    one = {
        "AirportID": "TTT",
        "FIDSArrival": [{**base, "ArrivalRemark": "準時"}, {**base, "ArrivalRemark": "取消"}],
    }
    (row,) = flights_log.tdx_rows("RCFN", one, TW, FETCHED)
    assert row["class"] == "cancelled"


# ---- 只在變化時寫、和原本的來源各存各的 ----


def test_store_only_changes_and_kept_apart_from_original_source(tmp_path):
    d = tmp_path / "events" / "29W"
    rows = flights_log.tdx_rows("RCMQ", fids("RMQ"), TW, FETCHED)
    assert events.store_flights(d, rows) == 5
    # 下一小時同樣的資料：不重寫
    later = flights_log.tdx_rows("RCMQ", fids("RMQ"), TW, utc(2026, 10, 23, 7, 7))
    assert events.store_flights(d, later) == 0
    # 狀態變了才寫那一班
    changed = fids("RMQ")
    changed["FIDSArrival"][0]["ArrivalRemark"] = "取消"
    rows2 = flights_log.tdx_rows("RCMQ", changed, TW, utc(2026, 10, 23, 8, 7))
    assert events.store_flights(d, rows2) == 1
    # 原本的來源（桃園機場）同一班同狀態：source 不同，各自寫
    tdx_row = by_flight(flights_log.tdx_rows("RCTP", fids("TPE"), TW, FETCHED))["CI162"]
    original = {**tdx_row, "source": "taoyuan-airport"}
    assert events.store_flights(d, [tdx_row]) == 1
    assert events.store_flights(d, [original]) == 1
    assert events.store_flights(d, [tdx_row, original]) == 0
    lines = [json.loads(x) for x in (d / "flights" / "2026-10-23.jsonl").read_text().splitlines()]
    assert sorted(r["source"] for r in lines if r["flight"] == "CI162") == [
        "taoyuan-airport",
        "tdx",
    ]


def test_hd31_rows_unchanged_by_source_key(tmp_path):
    """HD31 的行（每個機場一個來源）照舊：同一班同狀態不重寫。"""
    tpe = {"rows": flights.parse_tpe((FIXTURES / "tpe_flights_big5.txt").read_bytes())}
    rows = flights_log.rows_of("RCTP", tpe, TW, FETCHED)
    assert events.store_flights(tmp_path, rows) == len(rows)
    assert events.store_flights(tmp_path, rows) == 0


# ---- 認證與請求 ----


def test_from_env_missing_secret_skips(caplog):
    with caplog.at_level(logging.INFO, "hongthai"):
        assert tdx.Client.from_env({}) is None
        assert tdx.Client.from_env({"TDX_CLIENT_ID": ID, "TDX_CLIENT_SECRET": " "}) is None
    assert "TDX 未設定" in caplog.text
    c = tdx.Client.from_env({"TDX_CLIENT_ID": ID, "TDX_CLIENT_SECRET": SECRET})
    assert c is not None and SECRET not in repr(c)


def test_fids_params():
    p = tdx.fids_params(["TSA", "TPE", "TSA"])
    assert p == {
        "$filter": "AirportID eq 'TPE' or AirportID eq 'TSA'",
        "$top": "2",
        "$format": "JSON",
    }


def _fake_tdx(monkeypatch, token_status=200):
    posts, gets = [], []

    def post(url, data=None, **k):
        posts.append((url, data))
        if token_status != 200:
            return _Resp({"error": "unauthorized_client"}, token_status)
        return _Resp({"access_token": "tok-123", "expires_in": 86400})

    def get(url, params=None, headers=None, **k):
        gets.append((url, params, headers))
        return _Resp(load_json("tdx_fids_airport.json"))

    monkeypatch.setattr(tdx.requests, "post", post)
    monkeypatch.setattr(tdx, "http_get", get)
    return posts, gets


def test_client_token_once_and_bearer(monkeypatch, caplog):
    posts, gets = _fake_tdx(monkeypatch)
    c = tdx.Client(ID, SECRET)
    with caplog.at_level(logging.WARNING, "hongthai"):
        got = c.fids(["RMQ", "KNH", "HUN"])
    assert set(got) == {"KNH", "RMQ"}
    assert "沒有回這幾個機場：HUN" in caplog.text
    assert posts == [
        (
            tdx.TOKEN_URL,
            {"grant_type": "client_credentials", "client_id": ID, "client_secret": SECRET},
        )
    ]
    url, params, headers = gets[0]
    assert url == tdx.FIDS_URL
    assert params["$filter"] == "AirportID eq 'HUN' or AirportID eq 'KNH' or AirportID eq 'RMQ'"
    assert headers["Authorization"] == "Bearer tok-123"
    assert headers["Accept-Encoding"] == "gzip"
    # 同一次執行：token 不重取、同樣的機場不重抓
    assert c.fids(["KNH", "RMQ", "HUN"]) is got
    c.fids(["TPE"])
    assert len(posts) == 1 and len(gets) == 2


def test_each_data_request_recorded_with_retry(monkeypatch, tmp_path):
    """HD38：每送一次資料請求記一行（重試的那次也記；token 不記），`bytes` 是壓縮後的
    `Content-Length`。"""
    _fake_tdx(monkeypatch)
    sent = []

    def flaky(url, params=None, headers=None, retries=3, **k):
        sent.append(retries)
        if len(sent) == 1:
            raise tdx.TdxError("TDX：HTTP 503", "http_503")
        return _Resp(load_json("tdx_fids_airport.json"), headers={"Content-Length": "104611"})

    monkeypatch.setattr(tdx, "http_get", flaky)
    monkeypatch.setattr(tdx.time, "sleep", lambda s: None)
    c = tdx.Client(ID, SECRET)
    c.log = tdx.CallLog(tmp_path, "events", clock=lambda: FETCHED)
    assert set(c.fids(["RMQ"])) == {"RMQ"}
    assert sent == [1, 1] and c.calls == 2  # 每次 http_get 只試一次，重試由 fids 自己做
    lines = (tmp_path / "tdx" / "calls-2026-10.jsonl").read_text("utf-8").splitlines()
    assert [json.loads(x) for x in lines] == [
        {"t": "2026-10-23T06:07:00Z", "caller": "events", "bytes": None},
        {"t": "2026-10-23T06:07:00Z", "caller": "events", "bytes": 104611},
    ]
    assert tdx.month_calls(tmp_path, FETCHED) == 2
    # 同樣的機場不重抓、不多記
    c.fids(["RMQ"])
    assert tdx.month_calls(tmp_path, FETCHED) == 2


def test_forbidden_not_retried_and_recorded(monkeypatch, tmp_path):
    _fake_tdx(monkeypatch)
    sent = []

    def forbidden(*a, **k):
        sent.append(1)
        raise tdx.TdxError("TDX：HTTP 403", "http_403")

    monkeypatch.setattr(tdx, "http_get", forbidden)
    c = tdx.Client(ID, SECRET, log=tdx.CallLog(tmp_path, "build", clock=lambda: FETCHED))
    with pytest.raises(tdx.TdxError):
        c.fids(["RMQ"])
    assert sent == [1] and tdx.month_calls(tmp_path, FETCHED) == 1


def test_token_failure_message_has_no_secret(monkeypatch):
    _fake_tdx(monkeypatch, token_status=401)
    with pytest.raises(tdx.TdxError) as ei:
        tdx.Client(ID, SECRET).token()
    assert "401" in str(ei.value) and "unauthorized_client" in str(ei.value)
    assert SECRET not in str(ei.value)

    def boom(*a, **k):
        raise requests.ConnectionError(f"cannot connect {SECRET}")

    monkeypatch.setattr(tdx.requests, "post", boom)
    with pytest.raises(tdx.TdxError) as ei:
        tdx.Client(ID, SECRET).token()
    assert SECRET not in str(ei.value) and ei.value.__cause__ is None


# ---- hourly ----


def _quiet_hd31(monkeypatch):
    """前三件與原本五個航班來源都不連網：METAR／JMA／JTWC 失敗、航班 0 行。"""

    def down(url, **k):
        raise events.SourceError(f"{url}: down", "network")

    monkeypatch.setattr(events, "http_get", down)
    monkeypatch.setattr(flights, "fetch", lambda now: flights.FlightsData({}, {}))


def test_hourly_tdx_writes(tmp_path, monkeypatch, airports):
    _quiet_hd31(monkeypatch)
    posts, gets = _fake_tdx(monkeypatch)
    history = tmp_path / "history"
    res = events.hourly(history, [EV], airports, None, FETCHED, tdx.Client(ID, SECRET))
    # 事件裡的台灣機場：桃園 2、松山 1、台中 5、金門 2（香港不是台灣、TDX 不查）
    assert res["29W"]["tdx"] == 10
    assert res["29W"]["flights"] == 0
    assert gets[0][1]["$filter"] == (
        "AirportID eq 'KNH' or AirportID eq 'RMQ' or AirportID eq 'TPE' or AirportID eq 'TSA'"
    )
    d = history / "events" / "29W" / "flights"
    lines = [json.loads(x) for p in sorted(d.glob("*.jsonl")) for x in p.read_text().splitlines()]
    assert {r["source"] for r in lines} == {"tdx"}
    assert {r["airport"] for r in lines} == {"RCTP", "RCSS", "RCMQ", "RCBS"}
    # 下一小時同樣的資料：不重寫
    later = utc(2026, 10, 23, 7, 7)
    assert events.hourly(history, [EV], airports, None, later, tdx.Client(ID, SECRET)) == {
        "29W": {"metar": 0, "jma": None, "jtwc": None, "flights": 0, "tdx": 0}
    }


@pytest.mark.parametrize(("used", "asked"), [(1999, 1), (2000, 0)])
def test_hourly_tdx_monthly_limit(tmp_path, monkeypatch, airports, caplog, used, asked):
    """HD38：事件期間的每小時存檔也看每月上限，到 2,000 次（build＋events）才停；每次請求記一行
    `caller: "events"`。"""
    _quiet_hd31(monkeypatch)
    _, gets = _fake_tdx(monkeypatch)
    history = tmp_path / "history"
    path = tdx.calls_path(history, FETCHED)
    path.parent.mkdir(parents=True)
    path.write_text('{"t": "2026-10-20T08:25:00Z", "caller": "build", "bytes": 1}\n' * used)
    c = tdx.Client(ID, SECRET, log=tdx.CallLog(history, "events", clock=lambda: FETCHED))
    with caplog.at_level(logging.WARNING, "hongthai"):
        res = events.hourly(history, [EV], airports, None, FETCHED, c)
    assert len(gets) == asked
    if asked:
        assert res["29W"]["tdx"] == 10
        last = json.loads(path.read_text("utf-8").splitlines()[-1])
        assert (last["caller"], last["t"]) == ("events", "2026-10-23T06:07:00Z")
        assert tdx.month_calls(history, FETCHED) == 2000
    else:
        assert res["29W"]["tdx"] is None
        assert "TDX 本月已用 2000 次（上限 2000），這小時跳過" in caplog.text
        assert tdx.month_calls(history, FETCHED) == 2000


def test_hourly_without_tdx_secret_skips(tmp_path, monkeypatch, airports):
    _quiet_hd31(monkeypatch)
    posts, gets = _fake_tdx(monkeypatch)
    res = events.hourly(tmp_path / "history", [EV], airports, None, FETCHED, None)
    assert res == {"29W": {"metar": 0, "jma": None, "jtwc": None, "flights": 0}}
    assert posts == [] and gets == []


def test_hourly_tdx_token_failure_only_logged(tmp_path, monkeypatch, airports, caplog):
    def down(url, **k):
        raise events.SourceError(f"{url}: down", "network")

    tpe = {"rows": flights.parse_tpe((FIXTURES / "tpe_flights_big5.txt").read_bytes())}
    monkeypatch.setattr(events, "http_get", down)
    monkeypatch.setattr(flights, "fetch", lambda now: flights.FlightsData({"RCTP": tpe}, {}))
    posts, gets = _fake_tdx(monkeypatch, token_status=401)
    with caplog.at_level(logging.WARNING, "hongthai"):
        res = events.hourly(
            tmp_path / "history", [EV], airports, None, FETCHED, tdx.Client(ID, SECRET)
        )
    # TDX 失敗只記 log，原本的航班照寫
    assert res["29W"]["tdx"] is None
    assert res["29W"]["flights"] == 9
    assert gets == []
    assert "TDX 航班失敗" in caplog.text
    assert SECRET not in caplog.text


def test_hourly_tdx_no_taiwan_airports(tmp_path, monkeypatch, airports):
    _quiet_hd31(monkeypatch)
    posts, gets = _fake_tdx(monkeypatch)
    hk_only = Event("X", "X", date(2026, 10, 19), date(2026, 10, 28), ("VHHH",), None, None)
    res = events.hourly(
        tmp_path / "history", [hk_only], airports, None, FETCHED, tdx.Client(ID, SECRET)
    )
    assert res["X"]["tdx"] == 0
    assert posts == [] and gets == []


def test_main_reads_tdx_env(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(events, "hourly", lambda *a: seen.append(a[-1]) or {})
    monkeypatch.setattr(events, "utcnow", lambda: FETCHED)
    monkeypatch.setenv("TDX_CLIENT_ID", ID)
    monkeypatch.setenv("TDX_CLIENT_SECRET", SECRET)
    assert events.main(["hourly", "--archive", str(tmp_path)]) == 0
    monkeypatch.delenv("TDX_CLIENT_SECRET")
    assert events.main(["hourly", "--archive", str(tmp_path)]) == 0
    assert isinstance(seen[0], tdx.Client) and seen[1] is None
