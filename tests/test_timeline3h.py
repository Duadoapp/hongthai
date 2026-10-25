"""機場頁的 3 小時時間軸（HD35）：`airports/<iata>.json`。"""

from __future__ import annotations

import copy
import json
from datetime import timedelta
from types import SimpleNamespace

import test_build
from conftest import utc
from test_build import (
    NOW,
    _boom,
    _fail_all_but,
    fake_ai,
    sample_ai_models,
    sample_inputs,
    sample_openmeteo,
)

from hongthai import assess, build
from hongthai.config import MODELS, Thresholds
from hongthai.sources import ecmwf, openmeteo
from hongthai.sources.aifs import AifsStep
from hongthai.sources.ecmwf import EcmwfPoint, GustInterval, PrecipStep, ProbWindow
from hongthai.sources.gfs import GustPoint
from hongthai.sources.taf import TafPeriod
from hongthai.timeutil import slot_bounds

workspace = test_build.workspace  # fixture
TH = Thresholds()
S0 = utc(2026, 10, 18, 6)  # NOW（08:10Z）所在的 6 小時格
ALL_NATIVE = frozenset(m.id for m in MODELS if m.three_hourly)
# Shawn 2026-10-25：每個機場檔約 127 KB（壓縮後約 5 KB）可以接受；fixtures 的檔比實際小，留餘裕
MAX_FILE_BYTES = 135_000


def h(n: float):
    return S0 + timedelta(hours=n)


def ec_point() -> EcmwfPoint:
    """HRES 陣風每 3 小時一筆（前 1 小時最大陣風，同 0–90 小時的 `10fg`）：結束在 09Z 的 50 節、
    12Z 的 20 節，之後 10 節；12Z 的 6 小時雨量 40 mm（中）。"""
    gusts = {3: 50.0, 6: 20.0}
    hres = [GustInterval(h(e - 1), h(e), gusts.get(e, 10.0)) for e in range(3, 121, 3)]
    ens = [ProbWindow(h(s), h(s + 24), 0.5, 0.1, 0.0) for s in range(-6, 120, 12)]
    precip = [PrecipStep(h(e), 40.0 if e == 6 else 0.0, "rain", 25.0) for e in range(6, 121, 6)]
    return EcmwfPoint(hres, ens, precip)


def icon_hours() -> list[openmeteo.OmHour]:
    """ICON 逐時：前 1 小時最大陣風 07–09Z 30 節、10–12Z 40 節（中）；06–12Z 每小時 6 mm
    （6 小時 36 mm＝中，3 小時只有 18 mm）。"""

    def gust(n: int) -> float:
        return 30.0 if n <= 3 else 40.0 if n <= 6 else 5.0

    return [
        openmeteo.OmHour(h(n), 10.0, 90.0, gust(n), 6.0 if 0 < n <= 6 else 0.0, 0.0, None, 61)
        for n in range(0, 121)
    ]


def aifs_steps() -> list[AifsStep]:
    """AIFS 每 6 小時一點：10 米風 31 節（× 1.4＝估算陣風 43.4 節，中）。"""
    return [AifsStep(h(n), 31.0, 90.0, 2.0, 0.0) for n in range(0, 121, 6)]


def inputs(**kw):
    args = dict(
        now=NOW,
        thresholds=TH,
        ec=ec_point(),
        gfs=[GustPoint(h(n), 10.0) for n in range(0, 121, 6)],
        taf_periods=None,
        warnings=[],
        confirmed=[],
        aifs=aifs_steps(),
        icon=icon_hours(),
        runs={m.id: "2026-10-18T00:00:00Z" for m in MODELS},
    )
    args.update(kw)
    return args


def doc_for(native=ALL_NATIVE, **kw):
    """`build.airport_doc` 走一次（6 小時格先用同一份輸入算，等同 `latest.json` 那個機場）。"""
    args = inputs(**kw)
    six = assess.assess_slots(slots=slot_bounds(NOW), **args)
    latest_airport = {"slots": six}
    before = copy.deepcopy(latest_airport)
    a = SimpleNamespace(icao="RCTP", iata="TPE", thresholds=TH)
    doc, diff = build.airport_doc(latest_airport, "2026-10-18T08:10:00Z", NOW, a, args, native)
    assert latest_airport == before  # 6 小時格（latest.json）不會被改
    return doc, six, diff


def entry(slot, mid):
    return next(e for e in slot["model"]["models"] if e["id"] == mid)


def test_three_hour_bounds():
    b = assess.three_hour_bounds(S0)
    assert len(b) == 24
    assert b[0] == (S0, h(3)) and b[-1] == (h(69), h(72))


def test_window_max_per_model():
    """陣風、平均風、側風照 3 小時窗取最大：IFS 一格一筆 `10fg`、ICON 取窗內的小時。"""
    doc, six, _ = doc_for()
    s3a, s3b = doc["slots3h"][:2]
    assert entry(six[0], "ifs")["gustKt"] == 50.0
    assert (entry(s3a, "ifs")["gustKt"], entry(s3b, "ifs")["gustKt"]) == (50.0, 20.0)
    assert s3a["model"]["ec"]["hresGustKt"] == 50.0 and s3b["model"]["ec"]["hresGustKt"] == 20.0
    assert entry(six[0], "icon")["gustKt"] == 40.0
    assert (entry(s3a, "icon")["gustKt"], entry(s3b, "icon")["gustKt"]) == (30.0, 40.0)
    assert entry(s3a, "ifs")["sixHourly"] is False and entry(s3a, "icon")["sixHourly"] is False


def test_six_hourly_models_fill_both_slots():
    """只有 6 小時資料的模式：同一個 6 小時的值放進兩個 3 小時格、標 `sixHourly`。"""
    doc, six, _ = doc_for()
    for mid in ("gfs", "ifs-ens", "aifs", "aigfs", "jma", "wn2-ens"):
        parent = entry(six[0], mid)
        for s in doc["slots3h"][:2]:
            e = entry(s, mid)
            assert e["sixHourly"] is True
            assert {k: v for k, v in e.items() if k != "sixHourly"} == parent
    assert entry(doc["slots3h"][0], "aifs")["gustKt"] == 43.4
    assert doc["slots3h"][0]["model"]["gfs"] == six[0]["model"]["gfs"]
    # 每一筆都有 `sixHourly`
    assert all(
        isinstance(e["sixHourly"], bool) for s in doc["slots3h"] for e in s["model"]["models"]
    )


def test_rain_uses_enclosing_six_hour_slot():
    """雨的門檻是 6 小時累積：兩個 3 小時格都用包住它的 6 小時格的雨量，`causes` 照算。"""
    doc, six, _ = doc_for()
    for s in doc["slots3h"][:2]:
        assert s["model"]["ec"]["rain6hMm"] == 40.0 and s["model"]["ec"]["rain"] == "medium"
        assert entry(s, "icon")["rain6hMm"] == 36.0
        assert entry(s, "icon")["levels"]["rain"] == "medium"
    assert entry(six[0], "icon")["rain6hMm"] == 36.0
    # 第二格：IFS 陣風只剩 20 節，ICON 40 節、AIFS 43.4 節（中）；雨 IFS、ICON 都中
    s3b = doc["slots3h"][1]
    assert s3b["basis"] == "model" and "rain" in s3b["causes"]


def test_vote_same_rules_as_six_hour():
    """投票與門檻照 6 小時的規則（同一套函式）：`vote`、`level` 就是 `model_vote` 的結果。"""
    doc, _, _ = doc_for()
    for s in doc["slots3h"]:
        cats, v = assess.model_vote(s["model"]["models"])
        assert s["model"]["vote"] == v and s["model"]["level"] == v["level"]
        if s["basis"] == "model":
            assert s["level"] == v["level"]
            assert s["causes"] == assess.causes_from(cats, assess.MODEL_CAUSE_ORDER)


def test_taf_sliced_into_three_hour_slots():
    """官方層：TAF 依時段切到 3 小時格；6 小時格是兩格的合。"""
    taf = [
        TafPeriod(S0, h(36), "main", 90, 10.0, None),
        TafPeriod(h(3), h(6), "tempo", 90, 30.0, 50.0),
    ]
    doc, six, _ = doc_for(taf_periods=taf)
    s3a, s3b = doc["slots3h"][:2]
    assert six[0]["official"]["level"] == "high"
    assert (s3a["basis"], s3a["official"]["level"], s3a["official"]["gustKt"]) == (
        "official",
        "low",
        None,
    )
    assert (s3b["official"]["level"], s3b["official"]["kind"]) == ("high", "tempo")
    assert s3b["level"] == "high"
    # 官方層只看 0–30 小時：開始時間早於 now＋30 小時（14:10Z 明天）的格才有
    starts = [s["from"] for s in doc["slots3h"] if s["official"] is not None]
    assert starts[-1] == "2026-10-19T12:00:00Z"


def test_seam_and_file_shape():
    doc, six, _ = doc_for()
    assert set(doc) == {"schema", "generatedAt", "icao", "iata", "slots3h", "slots6h"}
    assert (doc["schema"], doc["icao"], doc["iata"]) == (1, "RCTP", "TPE")
    assert len(doc["slots3h"]) == 24 and len(doc["slots6h"]) == 8
    assert doc["slots3h"][0]["from"] == "2026-10-18T06:00:00Z"
    # 0–72／72–120 的接縫：最後一個 3 小時格的結束＝第一個 6 小時格的開始
    assert doc["slots3h"][-1]["to"] == doc["slots6h"][0]["from"] == "2026-10-21T06:00:00Z"
    assert doc["slots6h"] == six[12:]
    assert doc["slots6h"][-1]["to"] == six[-1]["to"]
    # 每格的欄位和 `latest.json` 的 `slots[]` 同一套
    for s in doc["slots3h"]:
        assert set(s) == set(six[0])
        assert set(s["model"]) == set(six[0]["model"])
        assert [e["id"] for e in s["model"]["models"]] == [m.id for m in MODELS]
        for e in s["model"]["models"]:
            assert set(e) == set(entry(six[0], e["id"])) | {"sixHourly"}


def test_reused_model_falls_back_to_six_hour():
    """這一報沒抓到（沿用舊資料）的 3 小時模式也用 6 小時格的值、標 `sixHourly`。"""
    doc, six, _ = doc_for(native=frozenset({"icon"}))
    s3b = doc["slots3h"][1]
    assert entry(s3b, "ifs")["sixHourly"] is True and entry(s3b, "ifs")["gustKt"] == 50.0
    assert s3b["model"]["ec"] == six[0]["model"]["ec"]


def test_native_3h_from_sources():
    ok, bad = {"ok": True}, {"ok": False, "reusedFrom": "x"}
    om = {"icon", "gem", "arpege", "cma"}  # HD33b 的三個旁觀模式也有 3 小時資料
    assert build.native_3h({"ecmwf": ok, "openmeteo": ok}) == {"ifs", *om}
    assert build.native_3h({"ecmwf": bad, "openmeteo": ok}) == om
    assert build.native_3h({"ecmwf": ok, "openmeteo": bad}) == {"ifs"}
    assert build.native_3h({}) == frozenset()
    assert ALL_NATIVE == {"ifs", *om}


def test_level_mismatches_logged_not_changed():
    six = [{"from": "A0", "to": "A6", "level": "high"}, {"from": "A6", "to": "B0", "level": "low"}]
    three = [
        {"from": "A0", "level": "medium"},
        {"from": "A3", "level": "low"},
        {"from": "A6", "level": "low"},
        {"from": "A9", "level": "unknown"},
    ]
    assert assess.level_mismatches(three, six) == [
        {"from": "A0", "level6h": "high", "levels3h": ["medium", "low"]}
    ]
    confirmed = [{"from": "A0", "to": "A6", "level": "confirmed"}]
    pair = [{"from": "A0", "level": "high"}, {"from": "A3", "level": "confirmed"}]
    assert assess.level_mismatches(pair, confirmed) == []


# ---- 整個 build ----


def _full_fixtures(monkeypatch, airports):
    ec, gf, tf, hk, cw, sm, nw = sample_inputs(airports)
    tf.raw.update(taf={}, metar={})
    af, ag = sample_ai_models(airports)
    om = sample_openmeteo(airports)
    _fail_all_but(
        monkeypatch,
        ecmwf=lambda *a, **k: ec,
        gfs=lambda *a, **k: gf,
        aifs=lambda *a, **k: af,
        aigfs=lambda *a, **k: ag,
        openmeteo=lambda *a, **k: om,
        taf=lambda *a, **k: tf,
        hko=lambda: hk,
        smg=lambda: sm,
        nws=lambda zones: nw,
    )
    monkeypatch.setattr(build.cwa, "fetch", lambda *a: cw)
    monkeypatch.setattr(build.ai, "EVALUATORS", {"claude": fake_ai("high"), "gemini": fake_ai()})


def _files(workspace):
    return {p.stem: p for p in (workspace / "public" / "airports").glob("*.json")}


def test_build_publishes_airport_files(workspace, monkeypatch, airports):
    _full_fixtures(monkeypatch, airports)
    seen = {}
    real = build.airport_files

    def spy(latest, **kw):  # `latest.json` 完全不變：產生 3 小時格前後一模一樣
        before = copy.deepcopy(latest)
        out = real(latest, **kw)
        seen["same"] = latest == before
        return out

    monkeypatch.setattr(build, "airport_files", spy)
    assert build.main([]) == 0
    assert seen["same"] is True
    out = json.loads((workspace / "public" / "latest.json").read_text("utf-8"))
    files = _files(workspace)
    assert sorted(files) == sorted(a.iata.lower() for a in airports)
    by = {a["iata"]: a for a in out["airports"]}
    total = 0
    for code, p in files.items():
        text = p.read_text("utf-8")
        total += len(text.encode("utf-8"))
        assert "\n " not in text  # 不縮排
        assert len(text.encode("utf-8")) <= MAX_FILE_BYTES, code
        doc = json.loads(text)
        assert doc["generatedAt"] == out["generatedAt"]
        assert doc["iata"].lower() == code
        assert doc["slots6h"] == by[doc["iata"]]["slots"][12:]
        assert len(doc["slots3h"]) == 24
    # 只進 Pages：不進 data 分支、不進 history/
    assert not list((workspace / "data").rglob("airports"))
    assert not (workspace / "public" / "history" / "airports").exists()
    # latest.json 沒有多任何欄位
    assert "airports3h" not in out["sources"]
    assert set(out["airports"][0]) == {
        *("icao", "iata", "tz", "name", "region", "official", "warningSources", "warnings"),
        *("metar", "taf", "slots", "confirmed", "ai"),
        "flightSources",  # HD38
    }
    line = next(
        json.loads(x)
        for x in (workspace / "data" / "history" / "timing" / "2026-10.jsonl")
        .read_text("utf-8")
        .splitlines()
        if '"airports3h"' in x
    )
    assert (line["ok"], line["files"], line["bytes"]) == (True, len(files), total)


def test_airport_failure_skips_only_that_file(workspace, monkeypatch, airports):
    """某個機場算不出來只 log、不出那個檔；其他機場與 `latest.json` 照出，回傳 0。"""
    _full_fixtures(monkeypatch, airports)
    real = build.airport_doc

    def flaky(latest_airport, generated_at, now, a, inputs, native):
        if a.iata == "TPE":
            raise ValueError("壞掉")
        return real(latest_airport, generated_at, now, a, inputs, native)

    monkeypatch.setattr(build, "airport_doc", flaky)
    (workspace / "public" / "airports").mkdir(parents=True)
    (workspace / "public" / "airports" / "tpe.json").write_text("{}", "utf-8")  # 舊的要刪
    assert build.main([]) == 0
    files = _files(workspace)
    assert "tpe" not in files and len(files) == len(airports) - 1
    assert json.loads((workspace / "public" / "latest.json").read_text("utf-8"))["airports"]


def test_whole_step_failure_not_fatal(workspace, monkeypatch, airports):
    _full_fixtures(monkeypatch, airports)
    monkeypatch.setattr(build, "native_3h", _boom)
    assert build.main([]) == 0
    assert _files(workspace) == {}
    assert (workspace / "public" / "latest.json").exists()


def test_failed_sources_still_publish(workspace, monkeypatch):
    """模式全部失敗：檔照出，3 小時格是 `unknown`。"""
    _fail_all_but(monkeypatch)
    assert build.main([]) == 0
    doc = json.loads((workspace / "public" / "airports" / "tpe.json").read_text("utf-8"))
    assert all(s["level"] == "unknown" for s in doc["slots3h"])


def test_republish_previous_drops_airport_files(workspace, monkeypatch):
    """整個流程壞掉、改發布上一份時不發機場檔（網頁退回 6 小時）。"""
    (workspace / "public" / "airports").mkdir(parents=True)
    (workspace / "public" / "airports" / "tpe.json").write_text("{}", "utf-8")
    (workspace / "data").mkdir()
    (workspace / "data" / "latest.json").write_text(
        json.dumps({"generatedAt": "2026-10-18T02:10:00Z", "airports": []}), "utf-8"
    )
    monkeypatch.setattr(build, "run", lambda **kw: (_ for _ in ()).throw(RuntimeError("bug")))
    monkeypatch.setattr(build, "utcnow", lambda: NOW)
    assert build.main([]) == 1
    assert _files(workspace) == {}


def test_ecmwf_hres_steps_are_three_hourly_to_72h():
    """`ifs` 標 `three_hourly` 的依據：0–72 小時（起報晚 12 小時也一樣）HRES 每 3 小時一筆。"""
    steps = ecmwf.hres_steps(12, 144)
    assert [s for s in steps if s <= 12 + 72] == list(range(15, 85, 3))


def test_observer_models_three_hourly_but_not_voting():
    """HD33b 的旁觀模式（GEM、ARPEGE、CMA）有 3 小時資料：照 3 小時窗算、`sixHourly: false`；
    還是不投票（拿掉它們的 3 小時格和沒有它們時一樣）。"""
    doc, _, _ = doc_for(om_hourly={"gem": icon_hours(), "arpege": None, "cma": None})
    base, _, _ = doc_for()
    s3a, s3b = doc["slots3h"][:2]
    assert (entry(s3a, "gem")["gustKt"], entry(s3b, "gem")["gustKt"]) == (30.0, 40.0)
    assert entry(s3a, "gem")["sixHourly"] is False
    assert entry(s3a, "gem")["rain6hMm"] == 36.0  # 雨照樣用 6 小時格
    assert entry(s3a, "arpege")["gustKt"] is None and entry(s3a, "arpege")["sixHourly"] is False
    for s, b in zip(doc["slots3h"], base["slots3h"], strict=True):
        assert (s["level"], s["model"]["vote"], s["causes"]) == (
            b["level"],
            b["model"]["vote"],
            b["causes"],
        )
