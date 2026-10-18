"""`latest.json` 格式（和網頁的契約）與失敗處理。"""

from __future__ import annotations

import json
import re

import pytest
from conftest import FIXTURES, ROOT, load_json, utc

from hongthai import build
from hongthai.config import ConfirmedPeriod
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
        {a.icao: [GustPoint(utc(2026, 10, 18, 6), 16.0, 120.0)] for a in airports},
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
            assert set(m["ec"]) == {"p10", "p15", "p25", "hresGustMs", "crosswindKt"}
            assert all(is_num_or_none(v) for v in m["ec"].values())
            assert set(m["gfs"]) == {"gustMs", "crosswindKt"}
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
    # 側風：GFS 16 m/s、120° → 對香港 070.9° 的跑道差 49°
    xw = vhhh["slots"][0]["model"]["gfs"]["crosswindKt"]
    assert xw == pytest.approx(16 * 3600 / 1852 * 0.755, abs=0.2)
    for a in latest["airports"]:
        assert all(isinstance(s["model"]["ec"]["crosswindKt"], float) for s in a["slots"][12:14])
    s0 = vhhh["slots"][0]
    assert (s0["level"], s0["basis"]) == ("high", "official")
    assert s0["official"]["warnings"] == ["tc_signal"]
    assert s0["model"]["gfs"]["gustMs"] == 16.0
    assert s0["model"]["level"] == "medium"
    assert s0["gap"] is True
    assert vhhh["slots"][3]["level"] == "confirmed"
    assert len(vhhh["confirmed"]) == 1 and rctp["confirmed"] == []


# ---- 執行與失敗處理 ----


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "airports.json").write_text((ROOT / "airports.json").read_text("utf-8"), "utf-8")
    (tmp_path / "confirmed.json").write_text("[]", "utf-8")
    monkeypatch.setattr(build.flights, "fetch", lambda now: build.flights.FlightsData({}, {}))
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
    assert not (workspace / "data" / "history" / "flights").exists()


def test_flight_fetch_error_reported(workspace, monkeypatch):
    for mod in (build.ecmwf, build.gfs, build.taf, build.hko, build.smg):
        monkeypatch.setattr(mod, "fetch", _boom)
    fl = _flights_from_fixtures()
    del fl.snapshots["VMMC"]
    fl.errors["VMMC"] = "timeout"
    monkeypatch.setattr(build.flights, "fetch", lambda now: fl)
    assert build.main([]) == 0
    out = json.loads((workspace / "public" / "latest.json").read_text("utf-8"))
    assert out["sources"]["flights"] == {"ok": False, "error": "VMMC:timeout"}
