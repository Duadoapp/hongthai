"""`latest.json` 格式（和網頁的契約）與失敗處理。"""

from __future__ import annotations

import json
import re

import pytest
from conftest import FIXTURES, ROOT, load_json, utc

from hongthai import build
from hongthai.config import ConfirmedPeriod
from hongthai.sources import cwa, ecmwf, hko, taf
from hongthai.sources.gfs import GfsData, GustPoint

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
        {a.icao: [GustPoint(utc(2026, 10, 18, 6), 16.0)] for a in airports},
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
        cwa.parse_warnings(load_json("cwa_w-c0034-001_land.json"), utc(2026, 8, 27, 5)), {}
    )
    return ec, gf, tf, hk, cw


@pytest.fixture
def latest(airports):
    ec, gf, tf, hk, cw = sample_inputs(airports)
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
    )
    # 確認可以序列化成 JSON，並用序列化後的結果檢查
    return json.loads(json.dumps(out))


def test_top_level(latest):
    assert latest["schema"] == 1
    assert ISO_Z.match(latest["generatedAt"])
    assert set(latest["runs"]) >= {"ecmwf", "gfs"}
    for v in latest["runs"].values():
        assert v is None or ISO_Z.match(v)
    assert set(latest["sources"]) >= {"ecmwf", "gfs", "taf", "hko", "cwa"}
    for s in latest["sources"].values():
        assert isinstance(s["ok"], bool)
        if not s["ok"]:
            assert isinstance(s["error"], str)
    assert latest["sources"]["cwa"] == {"ok": False, "error": "timeout"}


def test_airport_shape(latest):
    assert [a["icao"] for a in latest["airports"]] == ["RCTP", "VHHH"]
    for a in latest["airports"]:
        assert isinstance(a["iata"], str) and isinstance(a["tz"], str)
        assert set(a["name"]) == LANGS
        for w in a["warnings"]:
            assert w["source"] in ("hko", "cwa")
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
            m = s["model"]
            assert set(m["ec"]) == {"p10", "p15", "p25", "hresGustMs"}
            assert all(is_num_or_none(v) for v in m["ec"].values())
            assert set(m["gfs"]) == {"gustMs"} and is_num_or_none(m["gfs"]["gustMs"])
            assert m["level"] in ("low", "medium", "high", None)
            assert m["agreement"] in ("agree", "disagree", None)


def test_content_from_samples(latest):
    rctp, vhhh = latest["airports"]
    # 氣象署警報只給桃園、天文台信號只給香港
    assert [w["kind"] for w in rctp["warnings"]] == ["typhoon_land"]
    assert [(w["kind"], w["code"]) for w in vhhh["warnings"]] == [("tc_signal", "TC8NE")]
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
    monkeypatch.setattr(build.flights, "fetch_and_store", lambda d, now: {"VHHH": None})
    return tmp_path


def _boom(*a, **k):
    raise build.ecmwf.EcmwfError("down", "timeout")


def test_all_sources_fail_still_outputs(workspace, monkeypatch):
    for mod in (build.ecmwf, build.gfs, build.taf, build.hko):
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
