"""HD33a：Open-Meteo Previous Runs 回補 UKMO、GEM、ARPEGE、CMA（`sources/openmeteo_backfill.py`）與
`events backfill-openmeteo`。回應是手造的 fixture（`openmeteo_previous_runs_2*.json`）。"""

from __future__ import annotations

import json

import pytest
from conftest import load_json, utc

from hongthai import events
from hongthai.config import Event
from hongthai.sources import openmeteo_backfill as ob
from hongthai.sources.openmeteo import OpenMeteoError

ICAOS = ["RCTP", "VHHH"]
START = utc(2026, 10, 21, 0)
END = utc(2026, 10, 21, 12)
FETCHED = utc(2026, 10, 24, 17)


def _parse(name="openmeteo_previous_runs_2.json", start=START, end=END):
    return ob.parse(load_json(name), ICAOS, start, end, FETCHED)


def test_models_and_params():
    assert ob.MODELS == {
        "ukmo": "ukmo_global_deterministic_10km",
        "gem": "gem_global",
        "arpege": "meteofrance_arpege_world",
        "cma": "cma_grapes_global",
    }
    p = ob.params("cma", [(25.08, 121.23), (22.31, 113.92)], utc(2026, 10, 18, 12), END)
    assert p["models"] == "cma_grapes_global"
    assert p["latitude"] == "25.08,22.31" and p["longitude"] == "121.23,113.92"
    hourly = p["hourly"].split(",")
    assert len(hourly) == 24
    assert "wind_gusts_10m_previous_day0" in hourly and "precipitation_previous_day5" in hourly
    assert (p["start_date"], p["end_date"]) == ("2026-10-18", "2026-10-21")
    assert (p["wind_speed_unit"], p["timezone"]) == ("kn", "UTC")


def test_weighted_calls_under_limits():
    # 29W：10/18 12Z～10/26 16Z（9 個 UTC 日期）、26 個機場 → 一個模式 62.4、四個 249.6
    one = ob.calls(26, utc(2026, 10, 18, 12), utc(2026, 10, 26, 16))
    assert one == 62.4
    assert one * len(ob.MODELS) < 600


def test_parse_fields():
    rows, estimated, empty = _parse()
    assert estimated is False
    first = rows[0]
    assert first == {
        "t": "2026-10-24T17:00:00Z",
        "icao": "RCTP",
        "validAt": "2026-10-21T00:00:00Z",
        "previousDay": 0,
        "windKt": 20.0,
        "windDir": 60.0,
        "gustKt": 30.0,
        "gustEstimated": False,
        "precipMm": 0.0,
    }
    by = {(r["icao"], r["validAt"], r["previousDay"]): r for r in rows}
    r = by[("VHHH", "2026-10-21T05:00:00Z", 3)]
    assert (r["windKt"], r["gustKt"], r["windDir"], r["precipMm"]) == (16.5, 24.8, 110.0, 2.0)
    # 照 validAt、previousDay、機場（座標順序）排
    keys = [(r["validAt"], r["previousDay"], ICAOS.index(r["icao"])) for r in rows]
    assert keys == sorted(keys)


def test_parse_skips_rows_without_values():
    rows, _, empty = _parse()
    keys = {(r["icao"], r["validAt"], r["previousDay"]) for r in rows}
    # 桃園 day0 03Z 只有風向 → 不寫；day5 最後 3 個小時兩個地點都沒有 → 不寫
    assert ("RCTP", "2026-10-21T03:00:00Z", 0) not in keys
    assert ("RCTP", "2026-10-21T10:00:00Z", 5) not in keys
    assert ("VHHH", "2026-10-21T09:00:00Z", 5) in keys
    assert empty == 1 + 3 * 2
    assert len(rows) == 2 * 13 * 6 - empty


def test_parse_day0_key_with_or_without_suffix():
    """實際回應的 day0 不帶後綴（`wind_speed_10m`）；萬一帶 `_previous_day0` 也照讀。"""
    doc = load_json("openmeteo_previous_runs_2.json")
    assert "wind_speed_10m" in doc[0]["hourly"]
    assert "wind_speed_10m_previous_day0" not in doc[0]["hourly"]
    for loc in doc:
        for sec in ("hourly", "hourly_units"):
            loc[sec] = {
                (f"{k}_previous_day0" if k in ob.VARS else k): v for k, v in loc[sec].items()
            }
    assert ob.parse(doc, ICAOS, START, END, FETCHED) == _parse()


def test_parse_clips_to_window():
    rows, _, _ = _parse(start=utc(2026, 10, 21, 6), end=utc(2026, 10, 21, 7))
    assert {r["validAt"] for r in rows} == {"2026-10-21T06:00:00Z", "2026-10-21T07:00:00Z"}


def test_parse_gust_all_null_is_estimated():
    rows, estimated, _ = _parse("openmeteo_previous_runs_2_nogust.json")
    assert estimated is True
    assert all(r["gustEstimated"] is True and r["gustKt"] is None for r in rows)
    assert all(r["windKt"] is not None for r in rows)


def test_parse_bad_units_and_locations():
    doc = load_json("openmeteo_previous_runs_2.json")
    doc[0]["hourly_units"]["wind_speed_10m_previous_day2"] = "km/h"
    with pytest.raises(OpenMeteoError, match="kn"):
        ob.parse(doc, ICAOS, START, END, FETCHED)
    with pytest.raises(OpenMeteoError):
        ob.parse(load_json("openmeteo_previous_runs_2.json"), ["RCTP"], START, END, FETCHED)
    with pytest.raises(OpenMeteoError):
        ob.parse({"error": True, "reason": "No data"}, ICAOS, START, END, FETCHED)


def test_append_only_no_duplicates(tmp_path):
    rows, _, _ = _parse()
    path = ob.path_for(tmp_path, "ukmo")
    assert path == tmp_path / "backfill" / "openmeteo-ukmo.jsonl"
    assert ob.append(path, rows[:10]) == 10
    before = path.read_text(encoding="utf-8")
    # 重跑：已經有的跳過、新的接在後面，舊的行不動
    assert ob.append(path, rows) == len(rows) - 10
    after = path.read_text(encoding="utf-8")
    assert after.startswith(before)
    assert ob.append(path, rows) == 0
    lines = [json.loads(x) for x in after.splitlines()]
    assert len(lines) == len(rows)
    # 同一鍵、值不一樣（例如之後 Open-Meteo 改了）也不覆蓋
    changed = {**rows[0], "windKt": 99.0}
    assert ob.append(path, [changed]) == 0


def test_append_tolerates_broken_lines(tmp_path):
    path = tmp_path / "x.jsonl"
    path.write_text("not json\n", encoding="utf-8")
    rows, _, _ = _parse()
    assert ob.append(path, rows[:2]) == 2


class _Resp:
    def __init__(self, doc):
        self.content = json.dumps(doc).encode()
        self._doc = doc

    def json(self):
        return self._doc


def _airports(airports):
    by = {a.icao: a for a in airports}
    return [by[i] for i in ICAOS]


def test_backfill_one_model_fails_others_written(tmp_path, airports, monkeypatch):
    asked = []

    def get(url, *, params, **kw):
        asked.append(params["models"])
        assert url == ob.PREVIOUS_RUNS_URL
        if params["models"] == "gem_global":
            raise OpenMeteoError("HTTP 400", "http_400")
        name = "openmeteo_previous_runs_2"
        return _Resp(
            load_json(f"{name}_nogust.json" if "cma" in params["models"] else f"{name}.json")
        )

    monkeypatch.setattr(ob, "http_get", get)
    pauses = []
    out = ob.backfill(tmp_path, _airports(airports), START, END, FETCHED, pause=pauses.append)
    assert asked == list(ob.MODELS.values())  # 一個模式一個請求
    assert pauses == [ob.PAUSE_S] * 3
    assert out["gem"][0].error and out["gem"][1] == 0
    assert not (tmp_path / "backfill" / "openmeteo-gem.jsonl").exists()
    ukmo, written = out["ukmo"]
    assert ukmo.error is None and written == len(ukmo.rows) > 0 and ukmo.gust_estimated is False
    assert out["cma"][0].gust_estimated is True
    assert ukmo.calls == ob.calls(2, START, END) and ukmo.bytes > 0
    # 重跑只補沒有的
    again = ob.backfill(tmp_path, _airports(airports), START, END, FETCHED, pause=pauses.append)
    assert again["ukmo"][1] == 0 and again["cma"][1] == 0


def test_backfill_error_reason_from_response(airports, monkeypatch):
    import requests

    class _Err:
        status_code = 400

        def json(self):
            return {"error": True, "reason": "Cannot initialize gem_global"}

    def get(url, **kw):
        e = OpenMeteoError("x: HTTP 400", "http_400")
        e.__cause__ = requests.HTTPError(response=_Err())
        raise e

    monkeypatch.setattr(ob, "http_get", get)
    res = ob.fetch_model("gem", _airports(airports), START, END, FETCHED)
    assert res.error is not None and "Cannot initialize gem_global" in res.error


# ---- events backfill-openmeteo ----


def _event(**kw):
    from datetime import date

    base = {
        "id": "29W",
        "name": "CHAMPI",
        "start": date(2026, 10, 19),
        "end": date(2026, 10, 26),
        "airports": ("RCTP", "VHHH", "XXXX"),
    }
    return Event(**{**base, **kw})


def test_backfill_openmeteo_window(tmp_path, airports, monkeypatch):
    got = []

    def fake(d, aps, start, end, fetched, pause=None):
        got.append((d, [a.icao for a in aps], start, end, fetched))
        return {}

    monkeypatch.setattr(ob, "backfill", fake)
    now = utc(2026, 10, 24, 16, 41, 30)
    other = _event(id="X1")
    out = events.backfill_openmeteo(tmp_path, [_event(), other], airports, now, "29W")
    assert list(out) == ["29W"]
    d, icaos, start, end, fetched = got[0]
    assert d == tmp_path / "events" / "29W"
    assert icaos == ["RCTP", "VHHH"]  # airports.json 沒有的跳過
    assert start == utc(2026, 10, 18, 12)  # 台灣 10/19 00:00＝10/18 16Z 所在的格
    assert end == utc(2026, 10, 24, 16)  # 現在取整點（比事件結束早）
    assert fetched == now
    # 事件結束以後：到 to 隔天台灣 00:00
    got.clear()
    events.backfill_openmeteo(tmp_path, [_event()], airports, utc(2026, 11, 1), None)
    assert got[0][3] == utc(2026, 10, 26, 16)
    # 還沒開始的事件跳過
    got.clear()
    assert events.backfill_openmeteo(tmp_path, [_event()], airports, utc(2026, 10, 18, 12)) == {}
    assert got == []


def test_main_backfill_openmeteo(tmp_path, monkeypatch, capsys):
    res = ob.ModelResult("ukmo", rows=[{}] * 3, gust_estimated=False, bytes=1234, seconds=1.5)
    bad = ob.ModelResult("gem", error="HTTP 400（No data）")
    monkeypatch.setattr(
        events,
        "backfill_openmeteo",
        lambda history, evs, aps, now, eid: {"29W": {"ukmo": (res, 2), "gem": (bad, 0)}},
    )
    args = ["backfill-openmeteo", "--archive", str(tmp_path), "--event", "29W"]
    assert events.main(args) == 0
    out = capsys.readouterr().out
    assert "29W ukmo（ukmo_global_deterministic_10km）：3 行、寫了 2" in out
    assert "29W gem（gem_global）：失敗 HTTP 400（No data）" in out
    assert events.main(["backfill-openmeteo", "--archive", str(tmp_path), "--event", "NOPE"]) == 1


def test_workflow_has_backfill_openmeteo():
    from conftest import ROOT

    text = (ROOT / ".github" / "workflows" / "events.yml").read_text(encoding="utf-8")
    assert "backfill-openmeteo:" in text
    assert 'backfill-openmeteo --archive data --event "$EVENT_ID"' in text
