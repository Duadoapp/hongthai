"""`latest.json` 格式（和網頁的契約）與失敗處理。"""

from __future__ import annotations

import json
import re
import threading
import time

import pytest
from conftest import FIXTURES, ROOT, load_json, utc

from hongthai import budget, build, grib
from hongthai.config import ConfirmedPeriod, Thresholds, load_airports
from hongthai.sources import cwa, ecmwf, gfs, hko, smg, taf
from hongthai.sources.gfs import GfsData, GustPoint

ICAOS = ["RCTP", "RCSS", "RCKH", "VHHH", "VMMC"]
ISO_Z = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
LANGS = {"zh-TW", "zh-HK", "zh-CN", "en"}
NOW = utc(2026, 10, 18, 8, 10)


def is_num_or_none(v):
    return v is None or (isinstance(v, int | float) and not isinstance(v, bool))


def sample_inputs(airports):
    hres_run, hres = ecmwf.parse_hres(FIXTURES / "ecmwf_oper_subregion.grib2", airports)
    ens_run, ens = ecmwf.parse_ens(FIXTURES / "ecmwf_ep_subregion.grib2", airports)
    ec = ecmwf.EcmwfData(
        hres_run,
        ens_run,
        None,
        {a.icao: ecmwf.EcmwfPoint(hres[a.icao], ens[a.icao]) for a in airports},
    )
    gf = GfsData(
        utc(2026, 10, 18, 0),
        {a.icao: [GustPoint(utc(2026, 10, 18, 6), 40.0, 120.0)] for a in airports},  # 節
    )
    tf = taf.TafData(
        taf.parse_tafs(load_json("taf.json")), taf.parse_metars(load_json("metar.json")), {}
    )
    hk = hko.HkoData(
        hko.parse_signal(
            {lang: load_json(f"hko_warnsum_tc8ne_{lang}.json") for lang in ("tc", "en", "sc")}
        ),
        {},
    )
    cw = cwa.CwaData(
        cwa.parse_bulletins(load_json("cwa_w-c0034-001_land.json"), utc(2026, 8, 27, 5)), {}
    )
    sm = smg.SmgData(
        smg.parse_signal({"c": (FIXTURES / "smg_c_typhoon_sig3.xml").read_text("utf-8")}), {}
    )
    return ec, gf, tf, hk, cw, sm


@pytest.fixture
def latest(airports):
    ec, gf, tf, hk, cw, sm = sample_inputs(airports)
    status = {n: {"ok": True} for n in build.SOURCE_NAMES}
    status["cwa"] = {"ok": False, "error": "timeout"}
    confirmed = [
        ConfirmedPeriod("VHHH", utc(2026, 10, 19, 0), utc(2026, 10, 19, 6), {"en": "closed"})
    ]
    out = build.assemble(
        now=NOW,
        airports=airports,
        confirmed=confirmed,
        status=status,
        ec=ec,
        gf=gf,
        tf=tf,
        hk=hk,
        cw=cw,
        sm=sm,
    )
    # 確認可以序列化成 JSON，並用序列化後的結果檢查
    return json.loads(json.dumps(out))


def test_top_level(latest):
    assert latest["schema"] == 1
    assert ISO_Z.match(latest["generatedAt"])
    assert set(latest["runs"]) >= {"ecmwf", "gfs"}
    for v in latest["runs"].values():
        assert v is None or ISO_Z.match(v)
    assert set(latest["sources"]) >= {"ecmwf", "gfs", "taf", "hko", "cwa", "smg"}
    for s in latest["sources"].values():
        assert isinstance(s["ok"], bool)
        if not s["ok"]:
            assert isinstance(s["error"], str)
    assert latest["sources"]["cwa"] == {"ok": False, "error": "timeout"}


def test_airport_shape(latest):
    assert [a["icao"] for a in latest["airports"]] == ICAOS
    for a in latest["airports"]:
        assert isinstance(a["iata"], str) and isinstance(a["tz"], str)
        assert set(a["name"]) == LANGS
        for w in a["warnings"]:
            assert w["source"] in ("hko", "cwa", "smg")
            assert isinstance(w["kind"], str)
            assert w["level"] in ("low", "medium", "high")
            assert set(w["text"]) == LANGS
            assert w["issuedAt"] is None or ISO_Z.match(w["issuedAt"])
        m = a["metar"]
        assert ISO_Z.match(m["observedAt"])
        assert all(is_num_or_none(m[k]) for k in ("windDirDeg", "windKt", "gustKt"))
        assert isinstance(m["raw"], str)
        t = a["taf"]
        assert all(ISO_Z.match(t[k]) for k in ("issuedAt", "validFrom", "validTo"))
        assert isinstance(t["raw"], str)
        for c in a["confirmed"]:
            assert ISO_Z.match(c["from"]) and ISO_Z.match(c["to"])
            assert isinstance(c["note"], dict)


def test_slot_shape(latest):
    for a in latest["airports"]:
        assert len(a["slots"]) == 20
        assert a["slots"][0]["from"] == "2026-10-18T06:00:00Z"
        assert a["slots"][-1]["to"] == "2026-10-23T06:00:00Z"
        for s in a["slots"]:
            assert ISO_Z.match(s["from"]) and ISO_Z.match(s["to"])
            assert s["level"] in ("low", "medium", "high", "confirmed", "unknown")
            assert s["basis"] in ("official", "model", "confirmed", "none")
            assert isinstance(s["gap"], bool)
            o = s["official"]
            if o is not None:
                assert is_num_or_none(o["windKt"]) and is_num_or_none(o["gustKt"])
                assert o["kind"] in ("main", "tempo", "prob30", "prob40", "warning")
                assert o["level"] in ("low", "medium", "high")
                assert is_num_or_none(o["crosswindKt"])
            m = s["model"]
            assert set(m["ec"]) == {
                "p10",
                "p15",
                "p25",
                "p29Kt",
                "p37Kt",
                "p49Kt",
                "hresGustMs",
                "hresGustKt",
                "crosswindKt",
            }
            assert all(is_num_or_none(v) for v in m["ec"].values())
            # 節的欄位（HD2）：系集機率的節欄位就是 m/s 門檻的那兩個，37 節沒有來源
            assert m["ec"]["p29Kt"] == m["ec"]["p15"] and m["ec"]["p49Kt"] == m["ec"]["p25"]
            assert m["ec"]["p37Kt"] is None
            assert set(m["gfs"]) == {"gustMs", "gustKt", "crosswindKt"}
            assert all(is_num_or_none(v) for v in m["gfs"].values())
            assert m["level"] in ("low", "medium", "high", None)
            assert m["agreement"] in ("agree", "disagree", None)


def test_content_from_samples(latest):
    by = {a["icao"]: a for a in latest["airports"]}
    rctp, vhhh, vmmc = by["RCTP"], by["VHHH"], by["VMMC"]
    # 氣象署警報只給台灣三個機場、天文台信號只給香港、SMG 信號只給澳門
    for icao in ("RCTP", "RCSS", "RCKH"):
        assert [w["kind"] for w in by[icao]["warnings"]] == ["typhoon_land"]
    assert "松山在警戒區" in by["RCSS"]["warnings"][0]["text"]["zh-TW"]
    assert [(w["kind"], w["code"]) for w in vhhh["warnings"]] == [("tc_signal", "TC8NE")]
    assert [(w["source"], w["code"], w["level"]) for w in vmmc["warnings"]] == [
        ("smg", "TC3", "medium")
    ]
    assert vmmc["slots"][0]["official"]["warnings"] == ["tc_signal"]
    assert vmmc["slots"][0]["level"] == "medium"
    # 側風：GFS 40 節、120° → 對香港 070.9° 的跑道差 49°
    xw = vhhh["slots"][0]["model"]["gfs"]["crosswindKt"]
    assert xw == pytest.approx(40 * 0.755, abs=0.2)
    for a in latest["airports"]:
        assert all(isinstance(s["model"]["ec"]["crosswindKt"], float) for s in a["slots"][12:14])
    s0 = vhhh["slots"][0]
    assert (s0["level"], s0["basis"]) == ("high", "official")
    assert s0["official"]["warnings"] == ["tc_signal"]
    assert s0["model"]["gfs"]["gustKt"] == 40.0
    assert s0["model"]["gfs"]["gustMs"] == 20.6  # 契約的舊欄位照出 m/s
    assert s0["model"]["level"] == "medium"  # 40 節 ≥ 37
    assert s0["gap"] is True
    assert vhhh["slots"][3]["level"] == "confirmed"
    assert len(vhhh["confirmed"]) == 1 and rctp["confirmed"] == []


def test_airports_thresholds_in_knots(airports, tmp_path):
    # 五個機場目前都用預設門檻（節）
    assert all(a.thresholds == Thresholds() for a in airports)
    raw = json.loads((ROOT / "airports.json").read_text("utf-8"))
    raw[0]["thresholds"] = {"crosswindMediumKt": 20, "ecP49High": 0.5}
    p = tmp_path / "airports.json"
    p.write_text(json.dumps(raw), "utf-8")
    th = load_airports(p)[0].thresholds
    assert (th.crosswind_medium_kt, th.ec_p49_high, th.model_high_gust_kt) == (20, 0.5, 48)
    # HD2 以前的 m/s 鍵不再接受
    raw[0]["thresholds"] = {"modelHighGustMs": 25}
    p.write_text(json.dumps(raw), "utf-8")
    with pytest.raises(ValueError, match="modelHighGustMs"):
        load_airports(p)


# ---- 執行與失敗處理 ----


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "airports.json").write_text((ROOT / "airports.json").read_text("utf-8"), "utf-8")
    (tmp_path / "confirmed.json").write_text("[]", "utf-8")
    monkeypatch.setattr(build.flights, "fetch", lambda now: build.flights.FlightsData({}, {}))

    def no_network(*a, **k):  # 模式失敗時會去 Pages 抓上一份；測試不連網
        raise build.requests.ConnectionError("測試不連網")

    monkeypatch.setattr(build.requests, "get", no_network)
    return tmp_path


def _boom(*a, **k):
    raise build.ecmwf.EcmwfError("down", "timeout")


def test_all_sources_fail_still_outputs(workspace, monkeypatch):
    for mod in (build.ecmwf, build.gfs, build.taf, build.hko, build.smg):
        monkeypatch.setattr(mod, "fetch", _boom)
    monkeypatch.delenv("CWA_API_KEY", raising=False)
    assert build.main([]) == 0
    out = json.loads((workspace / "public" / "latest.json").read_text("utf-8"))
    assert {k: v["ok"] for k, v in out["sources"].items() if k != "flights"} == dict.fromkeys(
        build.SOURCE_NAMES, False
    )
    assert out["sources"]["cwa"]["error"] == "no_api_key"
    assert out["runs"] == {"ecmwf": None, "ecmwfEns": None, "gfs": None}
    assert all(s["level"] == "unknown" for a in out["airports"] for s in a["slots"])
    # data/ 裡有 latest 與歷史，public/history 也有
    assert (workspace / "data" / "latest.json").exists()
    assert len(list((workspace / "public" / "history").glob("*.json"))) == 1


def test_full_build_from_fixtures(workspace, monkeypatch, airports):
    """整個 `build.main` 用 fixtures 跑一次：五個機場都有 20 格，原始快照都寫了。"""
    ec, gf, tf, hk, cw, sm = sample_inputs(airports)
    gs = gfs.groups(airports)
    pts = {}
    for name, members in zip(("hkmo", "tw"), gs, strict=True):
        pts.update(gfs.parse_file(FIXTURES / f"gfs_{name}_f006.grb2", members))
    gf = GfsData(utc(2026, 10, 18, 0), pts)
    tf.raw.update(taf=load_json("taf.json"), metar=load_json("metar.json"))
    hk.raw.update(tc={})
    sm.raw.update(c=(FIXTURES / "smg_c_typhoon_sig3.xml").read_text("utf-8"))
    monkeypatch.setattr(build.ecmwf, "fetch", lambda *a, **k: ec)
    monkeypatch.setattr(build.gfs, "fetch", lambda *a, **k: gf)
    monkeypatch.setattr(build.taf, "fetch", lambda *a, **k: tf)
    monkeypatch.setattr(build.hko, "fetch", lambda: hk)
    monkeypatch.setattr(build.cwa, "fetch", lambda *a: cw)
    monkeypatch.setattr(build.smg, "fetch", lambda: sm)
    monkeypatch.setattr(build, "utcnow", lambda: NOW)
    assert build.main([]) == 0
    out = json.loads((workspace / "public" / "latest.json").read_text("utf-8"))
    assert all(s["ok"] for k, s in out["sources"].items())
    assert [a["icao"] for a in out["airports"]] == ICAOS
    assert all(len(a["slots"]) == 20 for a in out["airports"])
    assert all(a["metar"] and a["taf"] for a in out["airports"])
    raw = workspace / "data" / "history" / "raw" / "2026-10-18"
    assert sorted(p.name for p in raw.iterdir()) == [
        f"0810Z-{n}.json" for n in ("cwa", "hko", "metar", "smg", "taf")
    ]


def test_pipeline_crash_republishes_previous(workspace, monkeypatch):
    prev = {"schema": 1, "generatedAt": "2026-10-18T01:00:00Z", "airports": []}
    (workspace / "data").mkdir()
    (workspace / "data" / "latest.json").write_text(json.dumps(prev), "utf-8")

    def crash(**kw):
        raise RuntimeError("bug")

    monkeypatch.setattr(build, "run", crash)
    assert build.main([]) == 1
    assert json.loads((workspace / "public" / "latest.json").read_text("utf-8")) == prev


def test_pipeline_crash_without_previous(workspace, monkeypatch):
    monkeypatch.setattr(build, "run", lambda **kw: (_ for _ in ()).throw(RuntimeError("bug")))
    monkeypatch.setattr(build, "previous_latest", lambda archive, url: None)
    assert build.main([]) == 2
    assert not (workspace / "public" / "latest.json").exists()


def _flights_from_fixtures():
    from hongthai.sources import flights

    return flights.FlightsData(
        {
            "VHHH": {"arrival": load_json("hkg_arrival.json"), "departure": []},
            "RCTP": {"rows": flights.parse_tpe((FIXTURES / "tpe_flights_big5.txt").read_bytes())},
            "RCSS": {"intlDeparture": load_json("tsa_intl_departure.json")},
            "RCKH": {"intlDeparture": load_json("khh_intdep.json")},
            "VMMC": {"departure": "壞掉的格式"},  # 統計失敗不影響其他機場與整個 build
        },
        {},
    )


def test_flight_stats_written_to_archive_only(workspace, monkeypatch):
    for mod in (build.ecmwf, build.gfs, build.taf, build.hko, build.smg):
        monkeypatch.setattr(mod, "fetch", _boom)
    monkeypatch.setattr(build.flights, "fetch", lambda now: _flights_from_fixtures())
    monkeypatch.setattr(build, "utcnow", lambda: NOW)
    assert build.main([]) == 0
    out = json.loads((workspace / "public" / "latest.json").read_text("utf-8"))
    fl = out["sources"]["flights"]
    assert fl["ok"] is True and fl["statsError"].startswith("VMMC:")
    day = workspace / "data" / "history" / "cancellations" / "2026-10-18.json"
    rows = json.loads(day.read_text("utf-8"))
    assert {r["airport"] for r in rows} == {"VHHH", "RCTP", "RCSS", "RCKH"}
    assert not list((workspace / "public").rglob("*cancellations*"))
    assert not list((workspace / "public").rglob("unknown-statuses.json"))
    assert not (workspace / "data" / "history" / "flights").exists()
    # 看不懂的狀態：fixture 都看得懂，檔案照樣建出來（`{}` 或只有機場→狀態→次數）
    unknown = workspace / "data" / "history" / "cancellations" / "unknown-statuses.json"
    assert isinstance(json.loads(unknown.read_text("utf-8")), dict)


def test_flight_fetch_error_reported(workspace, monkeypatch):
    for mod in (build.ecmwf, build.gfs, build.taf, build.hko, build.smg):
        monkeypatch.setattr(mod, "fetch", _boom)
    fl = _flights_from_fixtures()
    del fl.snapshots["VMMC"]
    fl.errors["VMMC"] = "timeout"
    monkeypatch.setattr(build.flights, "fetch", lambda now: fl)
    assert build.main([]) == 0
    out = json.loads((workspace / "public" / "latest.json").read_text("utf-8"))
    fl = out["sources"]["flights"]
    assert isinstance(fl.pop("seconds"), float)
    assert fl == {"ok": False, "error": "VMMC:timeout"}


# ---- 時間預算、模式沿用、耗時紀錄 ----


def _fail_all_but(monkeypatch, **fetches):
    for name in ("ecmwf", "gfs", "taf", "hko", "smg"):
        monkeypatch.setattr(getattr(build, name), "fetch", fetches.get(name, _boom))
    monkeypatch.delenv("CWA_API_KEY", raising=False)
    monkeypatch.setattr(build, "utcnow", lambda: NOW)


def _timing_lines(workspace):
    path = workspace / "data" / "history" / "timing" / "2026-10.jsonl"
    return [json.loads(line) for line in path.read_text("utf-8").splitlines()]


def test_budget_timeout_recorded_and_next_sources_run(workspace, monkeypatch, airports):
    _, gf, *_ = sample_inputs(airports)

    def slow(*a, **k):
        time.sleep(2)
        raise AssertionError("不該等到這裡")

    _fail_all_but(monkeypatch, ecmwf=slow, gfs=lambda *a, **k: gf)
    monkeypatch.setitem(build.BUDGET_S, "ecmwf", 0.2)
    t0 = time.monotonic()
    assert build.main([]) == 0
    assert time.monotonic() - t0 < 1.5  # 沒有等 slow 跑完
    out = json.loads((workspace / "public" / "latest.json").read_text("utf-8"))
    assert out["sources"]["ecmwf"] == {"ok": False, "error": "timeout", "seconds": 0.2}
    assert out["sources"]["gfs"]["ok"] is True
    assert out["sources"]["taf"]["error"] == "timeout"  # _boom 的代碼，表示有跑到
    assert out["sources"]["cwa"]["error"] == "no_api_key"
    assert out["sources"]["flights"]["ok"] is True
    assert out["runs"]["gfs"] == "2026-10-18T00:00:00Z"


def test_abandoned_thread_stops_before_parsing():
    """超時被放棄的執行緒下載完要解析前看到 cancelled 旗標就結束，不碰 eccodes。"""
    done = threading.Event()
    seen = []

    def fn():
        time.sleep(0.3)
        try:
            grib.read_points(FIXTURES / "gfs_hkmo_f006.grb2", {"VHHH": (22.3, 113.9)})
            seen.append("parsed")
        except budget.Cancelled:
            seen.append("cancelled")
        finally:
            done.set()

    out = budget.run("test", fn, 0.05)
    assert out.timed_out and out.context.cancelled.is_set()
    assert done.wait(5) and seen == ["cancelled"]
    # 主執行緒（沒有預算 context）照常解析
    assert grib.read_points(FIXTURES / "gfs_hkmo_f006.grb2", {"VHHH": (22.3, 113.9)})["VHHH"]


def _prev(generated_at, runs, ec=None, gfs_v=None, slot_from="2026-10-18T06:00:00Z"):
    model = {"level": "low", "agreement": None}
    model["ec"] = ec or dict.fromkeys(("p10", "p15", "p25", "hresGustMs", "crosswindKt"))
    model["gfs"] = gfs_v or {"gustMs": None, "crosswindKt": None}
    return {
        "schema": 1,
        "generatedAt": generated_at,
        "runs": runs,
        "sources": {},
        "airports": [
            {"icao": "VHHH", "slots": [{"from": slot_from, "model": model}]},
            # 對不到的格（上一份比較早的格）不影響
            {"icao": "RCTP", "slots": [{"from": "2026-10-18T00:00:00Z", "model": model}]},
        ],
    }


def _write_prev(workspace, prev):
    (workspace / "data").mkdir(exist_ok=True)
    (workspace / "data" / "latest.json").write_text(json.dumps(prev), "utf-8")


def test_ecmwf_failure_reuses_previous_model(workspace, monkeypatch):
    ec = {"p10": 0.9, "p15": 0.6, "p25": 0.1, "hresGustMs": 26.0, "crosswindKt": 12.5}
    prev = _prev(
        "2026-10-18T02:10:00Z",
        # HRES 8 小時前（沿用）；系集 32 小時前（超過 24 小時，不沿用）
        {"ecmwf": "2026-10-18T00:00:00Z", "ecmwfEns": "2026-10-17T00:00:00Z", "gfs": None},
        ec=ec,
        gfs_v={"gustMs": 30.0, "crosswindKt": 40.0},
    )
    _write_prev(workspace, prev)
    _fail_all_but(monkeypatch)
    assert build.main([]) == 0
    out = json.loads((workspace / "public" / "latest.json").read_text("utf-8"))
    src = out["sources"]["ecmwf"]
    assert src["ok"] is False and src["error"] == "timeout"
    assert src["reusedFrom"] == "2026-10-18T02:10:00Z"
    assert out["runs"] == {"ecmwf": "2026-10-18T00:00:00Z", "ecmwfEns": None, "gfs": None}
    # gfs 也失敗了，但上一份的 runs.gfs 是 null → 不沿用
    assert "reusedFrom" not in out["sources"]["gfs"]
    by = {a["icao"]: a for a in out["airports"]}
    s0 = by["VHHH"]["slots"][0]
    # 上一份是 HD2 以前的格式（只有 m/s 欄位）→ 節的欄位由 m/s 補
    assert s0["model"]["ec"] == {
        "p10": None,
        "p15": None,
        "p25": None,
        "p29Kt": None,
        "p37Kt": None,
        "p49Kt": None,
        "hresGustMs": 26.0,
        "hresGustKt": 50.5,
        "crosswindKt": 12.5,
    }
    assert s0["model"]["gfs"] == {"gustMs": None, "gustKt": None, "crosswindKt": None}
    # 等級照常用抄來的值算：HRES 26 m/s ≈ 50.5 節 → 高
    assert (s0["level"], s0["basis"], s0["model"]["level"]) == ("high", "model", "high")
    assert s0["model"]["agreement"] is None
    assert by["VHHH"]["slots"][1]["level"] == "unknown"
    assert all(s["level"] == "unknown" for s in by["RCTP"]["slots"])
    # data/latest.json 換成這次的
    assert json.loads((workspace / "data" / "latest.json").read_text("utf-8")) == out


def test_reuse_expires_after_24h(workspace, monkeypatch):
    ec = {"p10": 0.9, "p15": 0.6, "p25": 0.1, "hresGustMs": 26.0, "crosswindKt": 12.5}
    prev = _prev(
        "2026-10-17T13:10:00Z",
        {"ecmwf": "2026-10-17T06:00:00Z", "ecmwfEns": "2026-10-17T00:00:00Z", "gfs": None},
        ec=ec,
    )
    _write_prev(workspace, prev)
    _fail_all_but(monkeypatch)
    assert build.main([]) == 0
    out = json.loads((workspace / "public" / "latest.json").read_text("utf-8"))
    src = out["sources"]["ecmwf"]
    assert (src["ok"], src["error"]) == (False, "timeout") and "reusedFrom" not in src
    assert out["runs"] == {"ecmwf": None, "ecmwfEns": None, "gfs": None}
    s0 = out["airports"][3]["slots"][0]
    assert s0["model"]["ec"]["hresGustMs"] is None
    assert (s0["level"], s0["model"]["level"]) == ("unknown", None)


def test_gfs_failure_reuses_previous_gfs(workspace, monkeypatch, airports):
    ec, *_ = sample_inputs(airports)
    prev = _prev(
        "2026-10-18T02:10:00Z",
        {"ecmwf": None, "ecmwfEns": None, "gfs": "2026-10-17T18:00:00Z"},
        gfs_v={"gustMs": 20.6, "gustKt": 40.0, "crosswindKt": 20.0},  # HD2 以後的格式
        slot_from="2026-10-21T06:00:00Z",  # fixture 的 HRES 有涵蓋的格
    )
    _write_prev(workspace, prev)
    _fail_all_but(monkeypatch, ecmwf=lambda *a, **k: ec)
    assert build.main([]) == 0
    out = json.loads((workspace / "public" / "latest.json").read_text("utf-8"))
    assert out["sources"]["gfs"]["reusedFrom"] == "2026-10-18T02:10:00Z"
    assert out["sources"]["gfs"]["ok"] is False
    assert "reusedFrom" not in out["sources"]["ecmwf"]
    assert out["runs"]["gfs"] == "2026-10-17T18:00:00Z"
    slots = out["airports"][3]["slots"]
    s12 = slots[12]
    assert s12["from"] == "2026-10-21T06:00:00Z"
    assert s12["model"]["gfs"] == {"gustMs": 20.6, "gustKt": 40.0, "crosswindKt": 20.0}
    assert isinstance(s12["model"]["ec"]["hresGustKt"], float)
    # 兩個模式都有了，一致性照常算
    assert s12["model"]["agreement"] in ("agree", "disagree")
    assert s12["model"]["level"] in ("medium", "high")  # GFS 40 節 ≥ 37 → 至少中
    assert all(s["model"]["gfs"]["gustMs"] is None for s in slots if s is not s12)
    assert all(s["model"]["gfs"]["gustKt"] is None for s in slots if s is not s12)


def _write_hist(workspace, doc, ok=None):
    """寫一份 `history/<時間>.json`；`ok` 是 `{來源: ok}`。"""
    doc = {**doc, "sources": {n: {"ok": v} for n, v in (ok or {}).items()}}
    stamp = doc["generatedAt"].replace("-", "").replace(":", "")[:13] + "Z"
    path = workspace / "data" / "history" / f"{stamp}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), "utf-8")
    return doc


def test_reuse_searches_back_to_last_good_run(workspace, monkeypatch, airports):
    """上一份 gfs 也失敗（runs.gfs 是 null）、再上一份有 → 從再上一份沿用。"""
    ec, *_ = sample_inputs(airports)
    good = _write_hist(
        workspace,
        _prev(
            "2026-10-17T20:10:00Z",
            {"ecmwf": None, "ecmwfEns": None, "gfs": "2026-10-17T12:00:00Z"},  # 20 小時前
            gfs_v={"gustMs": 16.0, "crosswindKt": 20.0},
            slot_from="2026-10-21T06:00:00Z",
        ),
        ok={"gfs": True},
    )
    # 兩份之間有一份「自己也在沿用」的（ok false，runs 是舊的）：不能從它抄
    _write_hist(
        workspace,
        _prev(
            "2026-10-18T00:10:00Z",
            {"ecmwf": None, "ecmwfEns": None, "gfs": "2026-10-17T12:00:00Z"},
            gfs_v={"gustMs": 99.0, "crosswindKt": 99.0},
            slot_from="2026-10-21T06:00:00Z",
        ),
        ok={"gfs": False},
    )
    last = _write_hist(
        workspace,
        _prev("2026-10-18T02:10:00Z", {"ecmwf": None, "ecmwfEns": None, "gfs": None}),
        ok={"gfs": False},
    )
    _write_prev(workspace, last)
    _fail_all_but(monkeypatch, ecmwf=lambda *a, **k: ec)
    assert (
        build.find_reuse_source(workspace / "data", "gfs", NOW)["generatedAt"]
        == (good["generatedAt"])
    )
    assert build.main([]) == 0
    out = json.loads((workspace / "public" / "latest.json").read_text("utf-8"))
    src = out["sources"]["gfs"]
    assert (src["ok"], src["reusedFrom"]) == (False, "2026-10-17T20:10:00Z")
    assert out["runs"]["gfs"] == "2026-10-17T12:00:00Z"
    s12 = out["airports"][3]["slots"][12]
    assert s12["from"] == "2026-10-21T06:00:00Z"
    # HD2 以前的格式：gustKt 由 gustMs 補（16 m/s ≈ 31.1 節）
    assert s12["model"]["gfs"] == {"gustMs": 16.0, "gustKt": 31.1, "crosswindKt": 20.0}


def test_reuse_search_all_older_than_24h(workspace, monkeypatch, airports):
    """archive 裡有資料的那份超過 24 小時、上一份也沒資料 → 不沿用。"""
    ec, *_ = sample_inputs(airports)
    _write_hist(
        workspace,
        _prev(
            "2026-10-17T05:10:00Z",
            {"ecmwf": None, "ecmwfEns": None, "gfs": "2026-10-17T00:00:00Z"},  # 32 小時前
            gfs_v={"gustMs": 16.0, "crosswindKt": 20.0},
            slot_from="2026-10-21T06:00:00Z",
        ),
        ok={"gfs": True},
    )
    last = _write_hist(
        workspace,
        _prev("2026-10-18T02:10:00Z", {"ecmwf": None, "ecmwfEns": None, "gfs": None}),
        ok={"gfs": False},
    )
    _write_prev(workspace, last)
    _fail_all_but(monkeypatch, ecmwf=lambda *a, **k: ec)
    assert build.find_reuse_source(workspace / "data", "gfs", NOW) is None
    assert build.main([]) == 0
    out = json.loads((workspace / "public" / "latest.json").read_text("utf-8"))
    assert "reusedFrom" not in out["sources"]["gfs"]
    assert out["runs"]["gfs"] is None
    assert all(s["model"]["gfs"]["gustMs"] is None for s in out["airports"][3]["slots"])


def test_timing_written_per_source_as_it_goes(workspace, monkeypatch, airports):
    _, gf, *_ = sample_inputs(airports)
    seen_during_gfs = []

    def gfs_fetch(*a, **k):
        seen_during_gfs.extend(_timing_lines(workspace))
        return gf

    _fail_all_but(monkeypatch, gfs=gfs_fetch)
    monkeypatch.setenv("GITHUB_SHA", "0123456789abcdef")
    assert build.main([]) == 0
    # gfs 跑的時候，start 與 ecmwf 那兩行已經寫進去了
    assert [r["source"] for r in seen_during_gfs] == ["start", "ecmwf"]
    lines = _timing_lines(workspace)
    assert [r["source"] for r in lines] == [
        "start",
        "ecmwf",
        "gfs",
        "taf",
        "hko",
        "cwa",
        "smg",
        "flights",
        "done",
    ]
    assert {r["run"] for r in lines} == {"2026-10-18T08:10:00Z"}
    assert lines[0] == {
        "run": "2026-10-18T08:10:00Z",
        "source": "start",
        "ok": True,
        "seconds": 0,
        "commit": "0123456",
    }
    ec_line = lines[1]
    assert set(ec_line) == {"run", "source", "ok", "error", "seconds", "bytes", "mirror"}
    assert (ec_line["ok"], ec_line["error"], ec_line["mirror"]) == (False, "timeout", None)
    gfs_line = lines[2]
    assert set(gfs_line) == {"run", "source", "ok", "error", "seconds", "bytes", "mirror"}
    assert (gfs_line["ok"], gfs_line["error"], gfs_line["bytes"]) == (True, None, 0)
    assert gfs_line["mirror"] is None  # 假的 fetch 沒有記 mirror
    assert lines[5]["error"] == "no_api_key"
    assert lines[-1]["ok"] is True and isinstance(lines[-1]["seconds"], float)


def test_timing_done_false_when_pipeline_crashes(workspace, monkeypatch):
    monkeypatch.setattr(build, "run", lambda **kw: (_ for _ in ()).throw(RuntimeError("bug")))
    monkeypatch.setattr(build, "previous_latest", lambda archive, url: None)
    monkeypatch.setattr(build, "utcnow", lambda: NOW)
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    assert build.main([]) == 2
    lines = _timing_lines(workspace)
    assert [(r["source"], r["ok"]) for r in lines] == [("start", True), ("done", False)]
    assert lines[0]["commit"] is None
