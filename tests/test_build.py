"""`latest.json` 格式（和網頁的契約）與失敗處理。"""

from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from conftest import FIXTURES, ROOT, load_json, utc

from hongthai import budget, build, grib
from hongthai.ai import config as ai_config
from hongthai.ai.parse import AiError
from hongthai.assess import DEFAULT_GUST_FACTOR
from hongthai.config import WN3_MODEL, ConfirmedPeriod, Thresholds, load_airports, load_regions
from hongthai.sources import (
    aifs,
    aigfs,
    cwa,
    ecmwf,
    gfs,
    hko,
    jma,
    nws,
    openmeteo,
    smg,
    swic,
    taf,
    wn3,
)
from hongthai.sources.gfs import GfsData, GustPoint

# 地區與機場的顯示順序（H9；HD3 加越南、菲律賓、關島・帛琉；Duado spec 第 16 節）
REGIONS = {
    "taiwan": ["RCTP", "RCSS", "RCKH", "RCMQ", "RCNN", "RCYU", "RCFN", "RCQC", "RCBS", "RCFG"],
    "east-china": ["ZSPD", "ZSSS", "ZSHC", "ZSNB", "ZSWZ", "ZSFZ", "ZSAM", "ZSQZ"],
    "south-china-hkmo": ["ZGOW", "ZGSZ", "ZGGG", "VHHH", "VMMC", "ZGSD", "ZJHK", "ZJSY"],
    "okinawa": ["ROAH", "ROIG", "ROMY"],
    "japan": ["RJFK", "RJFF", "RJBB", "RJGG", "RJTT", "RJAA", "RJCC", "RJSS"],
    "korea": ["RKPC", "RKPK", "RKSI", "RKSS"],
    "vietnam": ["VVNB", "VVTS", "VVDN", "VVCR", "VVPQ"],
    "philippines": ["RPLL", "RPVM", "RPLC"],
    "guam-palau": ["PGUM", "PTRO"],
}
ICAOS = [i for icaos in REGIONS.values() for i in icaos]
TAIWAN = REGIONS["taiwan"]
# fixtures 的 TAF／METAR 有的站（ROMY 只有 METAR）
TAF_ICAOS = {"RCTP", "RCSS", "RCKH", "VHHH", "VMMC", "ZSPD", "ROAH", "RJTT", "RKSI"}
METAR_ICAOS = TAF_ICAOS | {"ROMY"}
ISO_Z = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
LEVELS_OR_NONE = ("low", "medium", "high", None)
# HD8 加的模式欄位，沒有降水資料時都是 None
EC_HD8_NONE = dict.fromkeys(
    ("rain6hMm", "ptype", "p24hRain25", "p24hRain50", "temp2mC", "rain", "snow")
)
GFS_HD8_NONE = dict.fromkeys(("rain6hMm", "ptype", "visibilityM", "rain", "snow", "fog"))
PTYPES = (
    "none",
    "rain",
    "freezing_rain",
    "snow",
    "wet_snow",
    "rain_snow",
    "ice_pellets",
    "freezing_drizzle",
    "other",
)
LANGS = {"zh-TW", "zh-HK", "zh-CN", "en"}
MODEL_ENTRY_KEYS = {
    "id",
    "run",
    "windKt",  # HD18
    "gustKt",
    "gustEstimated",
    "gustFactor",  # HD18
    "gustFactorBasis",  # HD18
    "crosswindKt",
    "rain6hMm",
    "ptype",
    "visibilityM",
    "p49Kt",  # HD16
    "levels",
    "level",
}
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
    nw = nws.NwsData(nws.parse_alerts(load_json("nws_alerts_active_guz001_typhoon.json")), {})
    return ec, gf, tf, hk, cw, sm, nw


# JMA 看的 11 個機場（HD9）：日本 8 個＋沖繩 3 個
JMA_ICAOS = set(REGIONS["okinawa"]) | set(REGIONS["japan"])


def sample_jma(airports):
    """HD9：新千歲在手造的北海道（016000）那份裡有大雪警報＋暴風雪警報；其他 office 沒有回應的
    機場當作沒有警報。"""
    doc = load_json("jma_r8_016000_snow.json")
    return jma.JmaData(
        {
            a.jma_area.class20: jma.parse_area(doc, a.jma_area)
            if a.jma_area.office == "016000"
            else []
            for a in airports
            if a.jma_area
        },
        {"016000": doc},
    )


# HD29：經 WMO SWIC 的 21 個機場（中國大陸 14、韓國 4、菲律賓 3）
SWIC_ICAOS = (
    {i for i in REGIONS["east-china"] + REGIONS["south-china-hkmo"] if i[:2] in ("ZS", "ZG", "ZJ")}
    | set(REGIONS["korea"])
    | set(REGIONS["philippines"])
)
SWIC_SAMPLES = ROOT / "docs" / "surveys" / "samples" / "2026-10-22-cap" / "swic"


def sample_swic():
    """HD29：HD28 實抓的溫州市氣象台大風黃色預警（龍灣區，WNZ 會中）。"""
    xml = (SWIC_SAMPLES / "cap" / "cn-wenzhou-gale-yellow.xml").read_text("utf-8")
    alert = swic.parse_cap(xml, "cma", NOW, "wenzhou.xml")
    return swic.SwicData([alert], {"wmoAll": {"items": []}, "caps": {"wenzhou.xml": xml}}, 1)


def sample_ai_models(airports):
    """HD14 的 AIFS、AIGFS：每個機場整段一樣的 10 米平均風（節）。"""
    steps = range(0, 121, 6)
    t0 = utc(2026, 10, 18, 6)
    af = aifs.AifsData(
        utc(2026, 10, 18, 0),
        {
            a.icao: [aifs.AifsStep(t0 + timedelta(hours=h), 31.0, 90.0, 2.0, 0.0) for h in steps]
            for a in airports
        },
        66_000_000,
        "ecmwf",
    )
    ag = aigfs.AigfsData(
        utc(2026, 10, 17, 18),
        {
            a.icao: [aigfs.AigfsStep(t0 + timedelta(hours=h), 10.0, 90.0, 0.5) for h in steps]
            for a in airports
        },
        50_000_000,
        "aws",
    )
    return af, ag


def sample_openmeteo(airports, icon_gust=20.0, jma_wind=15.0, wn2_winds=(20.0, 40.0, 10.0, 36.0)):
    """HD16 的 ICON、JMA GSM、WeatherNext 2 系集：每個機場整段一樣（ICON 陣風、JMA 平均風、WN2 每個
    成員的 10 米風，節）。"""
    t0 = utc(2026, 10, 18, 0)
    hours = [t0 + timedelta(hours=h) for h in range(144)]
    return openmeteo.OpenMeteoData(
        runs={"icon": utc(2026, 10, 18, 0), "jma": utc(2026, 10, 17, 18), "wn2-ens": None},
        hourly={
            "icon": {
                a.icao: [
                    openmeteo.OmHour(t, 15.0, 90.0, icon_gust, 0.5, 0.0, None, 61) for t in hours
                ]
                for a in airports
            },
            "jma": {
                a.icao: [
                    openmeteo.OmHour(t, jma_wind, 90.0, None, 0.0, 0.0, None, 0) for t in hours
                ]
                for a in airports
            },
        },
        ensemble={
            a.icao: [openmeteo.EnsStep(t, tuple(wn2_winds)) for t in hours[::6]] for a in airports
        },
        raw={"forecast": [{"hourly": {}}], "ensemble": [{"hourly": {}}]},
        bytes_downloaded=2_300_000,
        calls=397.8,
        members=len(wn2_winds),
    )


AI_COMMENT = {"zh-TW": "高。", "zh-HK": "高。", "zh-CN": "高。", "en": "High."}


def fake_ai(level: str | None = "high", code: str | None = None, delay: float = 0.0):
    """假的 AI 模型（`ai.run.EVALUATORS` 的一個值）：`level` 給 None 時每次丟 `AiError(code)`。"""

    def evaluate(text, *, client=None, timeout=60):
        time.sleep(delay)
        if level is None:
            raise AiError(code or "bad_format")
        sentences = {lang: [{"text": c, "src": ["rule"]}] for lang, c in AI_COMMENT.items()}
        return {"level": level, "comment": dict(AI_COMMENT), "sentences": sentences}

    return SimpleNamespace(make_client=object, evaluate=evaluate)


@pytest.fixture
def latest(airports, tmp_path):
    ec, gf, tf, hk, cw, sm, nw = sample_inputs(airports)
    af, ag = sample_ai_models(airports)
    regions = load_regions(ROOT / "airports.json")
    status = {n: {"ok": True} for n in build.SOURCE_NAMES}
    status["cwa"] = {"ok": False, "error": "timeout"}
    confirmed = [
        ConfirmedPeriod("VHHH", utc(2026, 10, 19, 0), utc(2026, 10, 19, 6), {"en": "closed"})
    ]
    out = build.assemble(
        now=NOW,
        regions=regions,
        airports=airports,
        confirmed=confirmed,
        status=status,
        ec=ec,
        gf=gf,
        tf=tf,
        hk=hk,
        cw=cw,
        sm=sm,
        nw=nw,
        af=af,
        ag=ag,
        jm=sample_jma(airports),
        sw=sample_swic(),
    )
    # AI 對決（HD5）：Claude 成功、Gemini 格式不對
    evaluators = {"claude": fake_ai("high"), "gemini": fake_ai(None, "bad_format")}
    duel = build.ai.Duel(out, None, NOW, tmp_path, evaluators=evaluators)
    res = duel.run()
    build.ai.apply(out, res, {"ok": res["source"]["ok"], "seconds": 0.1, **res["source"]})
    # 確認可以序列化成 JSON，並用序列化後的結果檢查
    return json.loads(json.dumps(out))


def test_top_level(latest):
    assert latest["schema"] == 1
    assert ISO_Z.match(latest["generatedAt"])
    assert set(latest["runs"]) >= {"ecmwf", "gfs"}
    for v in latest["runs"].values():
        assert v is None or ISO_Z.match(v)
    assert set(latest["sources"]) >= {
        "ecmwf",
        "gfs",
        "taf",
        "hko",
        "cwa",
        "smg",
        "nws",
        "jma",
        "ai",
    }
    for s in latest["sources"].values():
        assert isinstance(s["ok"], bool)
        if not s["ok"]:
            assert isinstance(s["error"], str)
    assert latest["sources"]["cwa"] == {"ok": False, "error": "timeout"}
    # 地區（H9）：照顯示順序，四語名稱
    assert [r["id"] for r in latest["regions"]] == list(REGIONS)
    for r in latest["regions"]:
        assert set(r) == {"id", "name"} and set(r["name"]) == LANGS
    assert latest["regions"][0]["name"] == {
        "zh-TW": "台灣",
        "zh-HK": "台灣",
        "zh-CN": "台湾",
        "en": "Taiwan",
    }
    # 多模式投票（HD14）：頂層 models（id、四語名稱，照 config.MODELS 的順序）
    assert [m["id"] for m in latest["models"]] == [
        "ifs",
        "gfs",
        "ifs-ens",
        "aifs",
        "aigfs",
        "icon",
        "jma",
        "wn2-ens",
        "gem",  # HD33b：旁觀
        "arpege",
        "cma",
    ]
    for m in latest["models"]:
        assert set(m) == {"id", "name", "voting", "votesOnlyHigh"} and set(m["name"]) == LANGS
        # HD16：三票都投票；HD33b 的三個是旁觀
        assert m["voting"] is (m["id"] not in ("gem", "arpege", "cma"))
        # HD24：只投高或低的系集（判中時不算分母）
        assert m["votesOnlyHigh"] is (m["id"] in ("ifs-ens", "wn2-ens"))
    assert latest["models"][3]["name"] == {
        "zh-TW": "歐洲 AI 模式 AIFS",
        "zh-HK": "歐洲 AI 模式 AIFS",
        "zh-CN": "欧洲 AI 模式 AIFS",
        "en": "ECMWF AIFS",
    }
    assert latest["runs"]["aifs"] == "2026-10-18T00:00:00Z"
    assert latest["runs"]["aigfs"] == "2026-10-17T18:00:00Z"
    assert {"aifs", "aigfs"} <= set(latest["sources"])


def test_airport_shape(latest, airports):
    by_icao = {a.icao: a for a in airports}
    assert [a["icao"] for a in latest["airports"]] == ICAOS
    for a in latest["airports"]:
        assert isinstance(a["iata"], str) and isinstance(a["tz"], str)
        assert set(a["name"]) == LANGS
        assert a["icao"] in REGIONS[a["region"]]
        assert set(a["official"]) == {"warnings"} and isinstance(a["official"]["warnings"], bool)
        # HD29：接了哪些官方警報來源，照 airports.json
        assert a["warningSources"] == list(by_icao[a["icao"]].warning_sources)
        assert a["official"]["warnings"] is bool(a["warningSources"])
        assert "runwaySource" not in a
        for w in a["warnings"]:
            assert w["source"] in ("hko", "cwa", "smg", "nws", "jma", "cma", "kma", "pagasa")
            assert isinstance(w["kind"], str)
            assert w["level"] in ("low", "medium", "high")
            assert set(w["text"]) == LANGS
            assert w["issuedAt"] is None or ISO_Z.match(w["issuedAt"])
        m = a["metar"]
        assert (m is not None) == (a["icao"] in METAR_ICAOS)  # 沒有 METAR 的站是 null
        if m is not None:
            assert ISO_Z.match(m["observedAt"])
            assert all(is_num_or_none(m[k]) for k in ("windDirDeg", "windKt", "gustKt"))
            assert isinstance(m["raw"], str)
        t = a["taf"]
        assert (t is not None) == (a["icao"] in TAF_ICAOS)  # 沒有 TAF 的站是 null
        if t is not None:
            assert all(ISO_Z.match(t[k]) for k in ("issuedAt", "validFrom", "validTo"))
            assert isinstance(t["raw"], str)
        for d in (m, t):  # HD8：能見度（公尺）、天氣現象、雲幕（呎）
            if d is not None:
                assert d["visibilityM"] is None or isinstance(d["visibilityM"], int)
                assert d["ceilingFt"] is None or isinstance(d["ceilingFt"], int)
                assert isinstance(d["wx"], list) and all(isinstance(w, str) for w in d["wx"])
        for c in a["confirmed"]:
            assert ISO_Z.match(c["from"]) and ISO_Z.match(c["to"])
            assert isinstance(c["note"], dict)


def test_ai_shape(latest):
    """AI 對決（HD5，Duado spec 第 16 節）：頂層 `ai`、`airports[].ai`、`sources.ai`。"""
    assert latest["ai"] == {
        "disclaimer": {
            "zh-TW": "AI 評論僅供參考，以航空公司與機場公告為準",
            "zh-HK": "AI 評論僅供參考，以航空公司及機場公告為準",
            "zh-CN": "AI 评论仅供参考，以航空公司与机场公告为准",
            "en": "AI commentary is for reference only; follow airline and airport announcements.",
        },
        "models": {"claude": "claude-opus-5-5", "gemini": "gemini-4-argon"},
    }
    errors = {"no_api_key", "timeout", "bad_format", "network", "daily_cap", "run_cap", "refusal"}
    statuses = set()
    for a in latest["airports"]:
        ai = a["ai"]
        assert set(ai) == {"evaluatedAt", "claude", "gemini"}
        assert ai["evaluatedAt"] is None or ISO_Z.match(ai["evaluatedAt"])
        for key, model in (("claude", "claude-opus-5-5"), ("gemini", "gemini-4-argon")):
            light = ai[key]
            statuses.add(light["status"])
            assert light["model"] == model
            # HD40：三種燈都只多 `sentences`（`ok` 是逐句短評，其他是 null）
            if light["status"] == "ok":
                assert set(light) == {"status", "level", "comment", "model", "sentences"}
                assert light["level"] in ("low", "medium", "high")
                assert set(light["comment"]) == LANGS
                assert set(light["sentences"]) == LANGS
                for lang in LANGS:
                    texts = [x["text"] for x in light["sentences"][lang]]
                    assert light["comment"][lang] == (" " if lang == "en" else "").join(texts)
            elif light["status"] == "skipped":
                assert set(light) == {"status", "level", "comment", "model", "sentences"}
                assert light["sentences"] is None
                assert light["level"] == "low"
                assert light["comment"]["zh-TW"] == "沒看到明顯風險"
                assert set(light["comment"]) == LANGS
            else:
                assert light["status"] == "error"
                assert set(light) == {"status", "level", "comment", "model", "error", "sentences"}
                assert light["level"] is None and light["comment"] is None
                assert light["sentences"] is None
                assert light["error"] in errors or light["error"].startswith("http_")
        both_error = all(ai[k]["status"] == "error" for k in ("claude", "gemini"))
        assert (ai["evaluatedAt"] is None) == both_error
    # 樣本的 GFS 陣風每個機場都 40 節（中）→ 51 個都符合，前 20 個被評、其他 run_cap
    # （skipped 的結構在 test_ai.py 測）
    assert statuses == {"ok", "error"}
    errs = [a["ai"]["claude"].get("error") for a in latest["airports"]]
    assert errs.count(None) == 20 and errs.count("run_cap") == 31
    # 樣本：香港 8 號信號（高）→ 被評；Claude 成功、Gemini 格式不對
    vhhh = next(a for a in latest["airports"] if a["icao"] == "VHHH")["ai"]
    assert vhhh["evaluatedAt"] == "2026-10-18T08:10:00Z"
    assert vhhh["claude"]["status"] == "ok" and vhhh["gemini"]["error"] == "bad_format"
    src = latest["sources"]["ai"]
    assert src["ok"] is True and isinstance(src["seconds"], float)
    assert set(src["calls"]) == {"claude", "gemini"}
    assert all(isinstance(v, int) for v in src["calls"].values())
    assert src["errors"] == {"gemini": "bad_format"}


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
                assert o["kind"] in ("main", "tempo", "prob30", "prob40", "warning", "metar")
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
                # HD8
                "rain6hMm",
                "ptype",
                "p24hRain25",
                "p24hRain50",
                "temp2mC",
                "rain",
                "snow",
            }
            ec_ptype = m["ec"]["ptype"]
            assert ec_ptype is None or ec_ptype in PTYPES
            assert m["ec"]["rain"] in LEVELS_OR_NONE and m["ec"]["snow"] in LEVELS_OR_NONE
            assert all(
                is_num_or_none(v) for k, v in m["ec"].items() if k not in ("ptype", "rain", "snow")
            )
            # 節的欄位（HD2）：系集機率的節欄位就是 m/s 門檻的那兩個，37 節沒有來源
            assert m["ec"]["p29Kt"] == m["ec"]["p15"] and m["ec"]["p49Kt"] == m["ec"]["p25"]
            assert m["ec"]["p37Kt"] is None
            assert set(m["gfs"]) == {
                "gustMs",
                "gustKt",
                "crosswindKt",
                "rain6hMm",
                "ptype",
                "visibilityM",
                "rain",
                "snow",
                "fog",
            }
            assert m["gfs"]["ptype"] is None or m["gfs"]["ptype"] in PTYPES
            assert all(m["gfs"][k] in LEVELS_OR_NONE for k in ("rain", "snow", "fog"))
            assert all(
                is_num_or_none(v)
                for k, v in m["gfs"].items()
                if k not in ("ptype", "rain", "snow", "fog")
            )
            # HD8：causes 是主因在前的種類清單；官方層有 TAF 時 wx 是物件
            assert isinstance(s["causes"], list)
            assert set(s["causes"]) <= {"wind", "rain", "snow", "fog"}
            if o is not None:
                assert o["wx"] is None or set(o["wx"]) == {
                    "phenomena",
                    "visibilityM",
                    "ceilingFt",
                    "rain",
                    "snow",
                    "fog",
                }
                assert (o["wx"] is None) == (o["kind"] == "warning")
            assert m["level"] in ("low", "medium", "high", None)
            assert m["agreement"] in ("agree", "disagree", None)
            # HD14：每格 5 筆 models[]（照 config.MODELS）與 vote
            assert [e["id"] for e in m["models"]] == [
                "ifs",
                "gfs",
                "ifs-ens",
                "aifs",
                "aigfs",
                "icon",
                "jma",
                "wn2-ens",
                "gem",  # HD33b：旁觀
                "arpege",
                "cma",
            ]
            for e in m["models"]:
                assert set(e) == MODEL_ENTRY_KEYS
                assert e["run"] is None or ISO_Z.match(e["run"])
                assert all(is_num_or_none(e[k]) for k in ("gustKt", "crosswindKt", "rain6hMm"))
                assert e["visibilityM"] is None or is_num_or_none(e["visibilityM"])
                assert e["ptype"] is None or e["ptype"] in PTYPES
                assert e["gustEstimated"] in (True, False, None)
                assert set(e["levels"]) == {"wind", "rain", "snow", "fog"}
                assert all(v in LEVELS_OR_NONE for v in e["levels"].values())
                assert e["level"] in LEVELS_OR_NONE
            v = m["vote"]
            assert set(v) == {"total", "high", "medium", "mediumTotal", "low", "level", "thin"}
            assert v["medium"] <= v["mediumTotal"] <= v["total"]  # HD24
            assert v["level"] == m["level"] and isinstance(v["thin"], bool)
            assert 0 <= v["high"] <= v["total"] <= 8 and v["low"] <= v["total"]


def test_content_from_samples(latest):
    by = {a["icao"]: a for a in latest["airports"]}
    rctp, vhhh, vmmc = by["RCTP"], by["VHHH"], by["VMMC"]
    # 氣象署警報只給台灣十個機場、天文台信號只給香港、SMG 信號只給澳門
    for icao in TAIWAN:
        assert [w["kind"] for w in by[icao]["warnings"]] == ["typhoon_land"]
    assert "松山在警戒區" in by["RCSS"]["warnings"][0]["text"]["zh-TW"]
    # 沒有官方警報來源的機場：warnings 是空的、official.warnings 是 false（網頁顯示「尚未提供」）
    with_sources = set(TAIWAN) | {"VHHH", "VMMC", "PGUM"} | JMA_ICAOS | SWIC_ICAOS
    for a in latest["airports"]:
        assert a["official"]["warnings"] is (a["icao"] in with_sources)
        if a["icao"] not in with_sources:
            assert a["warnings"] == []
            assert all(not (s["official"] or {}).get("warnings") for s in a["slots"])
    assert [(w["kind"], w["code"]) for w in vhhh["warnings"]] == [("tc_signal", "TC8NE")]
    assert [(w["source"], w["code"], w["level"]) for w in vmmc["warnings"]] == [
        ("smg", "TC3", "medium")
    ]
    assert vmmc["slots"][0]["official"]["warnings"] == ["tc_signal"]
    assert vmmc["slots"][0]["level"] == "medium"
    # NWS（HD3）只給關島：颱風警報高、守視中，解除的那一則不算；帛琉沒接
    pgum = by["PGUM"]
    assert [(w["source"], w["kind"], w["level"], w["code"]) for w in pgum["warnings"]] == [
        ("nws", "typhoon_warning", "high", "Typhoon Warning"),
        ("nws", "typhoon_watch", "medium", "Typhoon Watch"),
    ]
    assert pgum["warnings"][0]["text"]["zh-TW"] == "颱風警報生效中（美國國家氣象局）"
    assert pgum["warnings"][0]["text"]["en"].startswith("Typhoon Warning issued October 18")
    assert pgum["warnings"][0]["detail"] == "TYPHOON WARNING REMAINS IN EFFECT"
    assert pgum["warnings"][0]["issuedAt"] == "2026-10-18T05:01:00Z"
    assert pgum["slots"][0]["official"]["warnings"] == ["typhoon_warning", "typhoon_watch"]
    assert (pgum["slots"][0]["level"], pgum["slots"][0]["basis"]) == ("high", "official")
    assert by["PTRO"]["official"]["warnings"] is False and by["PTRO"]["warnings"] == []
    # JMA（HD9）：日本與沖繩 11 個機場都接；新千歲有大雪警報（中）＋暴風雪警報（低，只列出）
    rjcc = by["RJCC"]
    assert [(w["source"], w["kind"], w["level"], w["code"]) for w in rjcc["warnings"]] == [
        ("jma", "jma_heavy_snow", "medium", "06"),
        ("jma", "jma_snowstorm", "low", "02"),
    ]
    assert rjcc["warnings"][0]["text"] == {
        "zh-TW": "日本氣象廳大雪警報（千歳市）",
        "zh-HK": "日本氣象廳大雪警報（千歳市）",
        "zh-CN": "日本气象厅大雪警报（千歳市）",
        "en": "JMA heavy snow warning (Chitose)",
    }
    assert rjcc["warnings"][0]["issuedAt"] == "2026-12-10T07:40:00Z"
    assert "detail" not in rjcc["warnings"][0]
    assert rjcc["slots"][0]["official"]["warnings"] == ["jma_heavy_snow", "jma_snowstorm"]
    assert "snow" in rjcc["slots"][0]["causes"]
    for icao in JMA_ICAOS - {"RJCC"}:
        assert by[icao]["official"]["warnings"] is True and by[icao]["warnings"] == []
    # 側風：GFS 40 節、120° → 對香港 070.9° 的跑道差 49°
    xw = vhhh["slots"][0]["model"]["gfs"]["crosswindKt"]
    assert xw == pytest.approx(40 * 0.755, abs=0.2)
    # 51 個機場都有跑道（石垣 HD3 補上），都算得出側風
    for a in latest["airports"]:
        xws = [s["model"]["ec"]["crosswindKt"] for s in a["slots"][12:14]]
        assert all(isinstance(x, float) for x in xws), a["icao"]
    # 石垣 04/22（035.7°）：GFS 40 節、120° → 差 84.3°
    roig = by["ROIG"]["slots"][0]["model"]["gfs"]["crosswindKt"]
    assert roig == pytest.approx(40 * 0.995, abs=0.1)
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
    # 51 個機場目前都用預設門檻（節），airports.json 不寫 thresholds
    assert all(a.thresholds == Thresholds() for a in airports)
    raw = json.loads((ROOT / "airports.json").read_text("utf-8"))
    assert not any("thresholds" in a for a in raw["airports"])
    raw["airports"][0]["thresholds"] = {"crosswindMediumKt": 20, "ecP49High": 0.5}
    p = tmp_path / "airports.json"
    p.write_text(json.dumps(raw), "utf-8")
    th = load_airports(p)[0].thresholds
    assert (th.crosswind_medium_kt, th.ec_p49_high, th.model_high_gust_kt) == (20, 0.5, 48)
    # HD2 以前的 m/s 鍵不再接受
    raw["airports"][0]["thresholds"] = {"modelHighGustMs": 25}
    p.write_text(json.dumps(raw), "utf-8")
    with pytest.raises(ValueError, match="modelHighGustMs"):
        load_airports(p)


def test_airports_json_structure():
    """`airports.json`（H9、HD3）：51 個機場、九個地區，順序和 Duado spec 第 16 節一致。"""
    raw = json.loads((ROOT / "airports.json").read_text("utf-8"))
    assert [r["id"] for r in raw["regions"]] == list(REGIONS)
    assert all(set(r["name"]) == LANGS for r in raw["regions"])
    aps = raw["airports"]
    assert len(raw["regions"]) == 9
    assert len(aps) == 51 and [a["icao"] for a in aps] == ICAOS
    assert len({a["icao"] for a in aps}) == 51 and len({a["iata"] for a in aps}) == 51
    for a in aps:
        assert a["icao"] in REGIONS[a["region"]]
        assert re.fullmatch(r"[A-Z]{4}", a["icao"]) and re.fullmatch(r"[A-Z]{3}", a["iata"])
        ZoneInfo(a["tz"])
        assert set(a["name"]) == LANGS and "機場" not in a["name"]["zh-TW"]
        assert -90 <= a["lat"] <= 90 and -180 <= a["lon"] <= 180
        assert a["runwaySource"] in ("aip", "ourairports", "computed")
        assert a["runways"], a["icao"]  # HD3 起每個機場都有跑道
        for r in a["runways"]:
            assert len(r["headings"]) == 2 and all(0 <= h <= 360 for h in r["headings"])
            assert abs((r["headings"][1] - r["headings"][0]) % 360 - 180) < 0.05
        # 官方警報：台灣看氣象署（每個機場一組警戒區關鍵字）、香港天文台、澳門 SMG、
        # 關島 NWS（HD3）、日本與沖繩 JMA（HD9）、中國大陸、韓國、菲律賓經 WMO SWIC（HD29），
        # 越南、帛琉還沒有
        want = (
            ["cwa"]
            if a["region"] == "taiwan"
            else ["jma"]
            if a["region"] in ("okinawa", "japan")
            else ["cma"]
            if a["icao"].startswith(("ZS", "ZG", "ZJ"))
            else ["kma"]
            if a["region"] == "korea"
            else ["pagasa"]
            if a["region"] == "philippines"
            else {"VHHH": ["hko"], "VMMC": ["smg"], "PGUM": ["nws"]}.get(a["icao"], [])
        )
        assert a["warningSources"] == want
        assert bool(a.get("cmaAreas")) == (want == ["cma"])
        assert bool(a.get("psgcAreas")) == (want == ["pagasa"])
        assert bool(a.get("cwaAreas")) == (a["region"] == "taiwan")
        assert a.get("nwsZone") == ("GUZ001" if a["icao"] == "PGUM" else None)
        assert bool(a.get("jmaArea")) == (a["icao"] in JMA_ICAOS)
    # JMA 的區域（2026-10-20 從 area.json 查的機場所在市町村；office 是它往上的都道府縣氣象台）
    areas = {a["icao"]: a["jmaArea"] for a in aps if a.get("jmaArea")}
    assert {k: (v["office"], v["class20"], v["name"]) for k, v in areas.items()} == {
        "ROAH": ("471000", "4720100", "那覇市"),
        "ROIG": ("474000", "4720700", "石垣市"),
        "ROMY": ("473000", "4721400", "宮古島市"),
        "RJFK": ("460100", "4621800", "霧島市"),
        "RJFF": ("400000", "4013000", "福岡市"),
        "RJBB": ("270000", "2721300", "泉佐野市"),
        "RJGG": ("230000", "2321600", "常滑市"),
        "RJTT": ("130000", "1311100", "大田区"),
        "RJAA": ("120000", "1221100", "成田市"),
        "RJCC": ("016000", "0122400", "千歳市"),
        "RJSS": ("040000", "0420700", "名取市"),
    }
    # HD29：中國氣象局預警對機場的縣級代碼、PAGASA 的 PSGC（調查報告第 2.3、2.5 節，待主對話核對）
    assert {a["icao"]: a["cmaAreas"] for a in aps if a.get("cmaAreas")} == {
        "ZSPD": ["310115"],
        "ZSSS": ["310105", "310112"],
        "ZSHC": ["330109"],
        "ZSNB": ["330203"],
        "ZSWZ": ["330303"],
        "ZSFZ": ["350112"],
        "ZSAM": ["350206"],
        "ZSQZ": ["350582"],
        "ZGOW": ["445203", "445202"],
        "ZGSZ": ["440306"],
        "ZGGG": ["440111", "440114"],
        "ZGSD": ["440404"],
        "ZJHK": ["460108"],
        "ZJSY": ["460204"],
    }
    assert {a["icao"]: a["psgcAreas"] for a in aps if a.get("psgcAreas")} == {
        "RPLL": ["137600000", "137604000", "137605000", "130000000"],
        "RPVM": ["072226000", "072200000", "070000000"],
        "RPLC": ["035409000", "035400000", "030000000"],
    }
    aip = [a["icao"] for a in aps if a["runwaySource"] == "aip"]
    assert sorted(aip) == ["RCKH", "RCSS", "RCTP", "VHHH", "VMMC"]
    assert [a["icao"] for a in aps if a["runwaySource"] == "computed"] == ["ROIG"]
    roig = next(a for a in aps if a["icao"] == "ROIG")
    assert roig["runways"] == [{"id": "04/22", "headings": [35.7, 215.7]}]


def _write_airports(tmp_path, raw):
    p = tmp_path / "airports.json"
    p.write_text(json.dumps(raw, ensure_ascii=False), "utf-8")
    return p


def _pgum(raw):
    return next(a for a in raw["airports"] if a["icao"] == "PGUM")


def _icao(raw, icao):
    return next(a for a in raw["airports"] if a["icao"] == icao)


def _rjcc(raw):
    return next(a for a in raw["airports"] if a["icao"] == "RJCC")


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda raw: raw["airports"].append(dict(raw["airports"][0])), "ICAO 重複"),
        (lambda raw: raw["airports"][0].update(region="mars"), "不在 regions"),
        (lambda raw: raw["airports"][0].update(tz="Asia/Taipeii"), "IANA"),
        (lambda raw: raw["airports"][0]["runways"][0].update(headings=[49, 400]), "0–360"),
        (lambda raw: raw["airports"].insert(0, raw["airports"].pop(-1)), "順序"),
        (lambda raw: raw["regions"].append(dict(raw["regions"][0])), "地區 id 重複"),
        (lambda raw: _pgum(raw).pop("nwsZone"), "nwsZone"),
        (lambda raw: _pgum(raw).update(nwsZone="Guam"), "nwsZone"),
        (lambda raw: _rjcc(raw).pop("jmaArea"), "jmaArea"),
        (lambda raw: _rjcc(raw)["jmaArea"].update(office="16000"), "jmaArea"),
        (lambda raw: _rjcc(raw)["jmaArea"].update(class20="122400"), "jmaArea"),
        (lambda raw: _rjcc(raw)["jmaArea"].pop("name"), "jmaArea"),
        # HD29
        (lambda raw: _icao(raw, "ZSWZ").pop("cmaAreas"), "cmaAreas"),
        (lambda raw: _icao(raw, "ZSWZ").update(cmaAreas=["3303"]), "cmaAreas"),
        (lambda raw: _icao(raw, "RPLL").pop("psgcAreas"), "psgcAreas"),
        (lambda raw: _icao(raw, "RPLL").update(psgcAreas=["1376"]), "psgcAreas"),
    ],
)
def test_airports_json_rejected(tmp_path, change, message):
    raw = json.loads((ROOT / "airports.json").read_text("utf-8"))
    change(raw)
    with pytest.raises(ValueError, match=message):
        load_airports(_write_airports(tmp_path, raw))


def test_regions_order_matches_airports(latest):
    seen = []
    for a in latest["airports"]:
        if not seen or seen[-1] != a["region"]:
            seen.append(a["region"])
    assert seen == [r["id"] for r in latest["regions"]]


def test_swic_warnings_in_output(latest):
    """HD29：經 SWIC 的警報只列出（low）；三國 21 個機場 `official.warnings` 是 true。"""
    by = {a["icao"]: a for a in latest["airports"]}
    for icao in SWIC_ICAOS:
        assert by[icao]["official"]["warnings"] is True
    want = {"ZS": ["cma"], "ZG": ["cma"], "ZJ": ["cma"], "RK": ["kma"], "RP": ["pagasa"]}
    assert all(by[i]["warningSources"] == want[i[:2]] for i in SWIC_ICAOS)
    assert all(by[i]["warningSources"] == [] for i in REGIONS["vietnam"] + ["PTRO"])
    wnz = by["ZSWZ"]
    assert wnz["warnings"] == [
        {
            "source": "cma",
            "kind": "cma_gale_yellow",
            "level": "low",
            "text": {
                "zh-TW": "溫州市氣象臺發布大風黃色預警[Ⅲ級/較重]（中國氣象局，經 WMO SWIC）",
                "zh-HK": "温州市氣象台發佈大風黃色預警[Ⅲ級/較重]（中國氣象局，經 WMO SWIC）",
                "zh-CN": "温州市气象台发布大风黄色预警[Ⅲ级/较重]（中国气象局，经 WMO SWIC）",
                "en": "Wenzhou Meteorological Observatory issues a yellow warning for strong "
                "winds [Level III/Severe] (CMA via WMO SWIC)",
            },
            "issuedAt": "2026-10-21T01:35:00Z",
            "code": "gale",
            "detail": "温州市气象台发布大风黄色预警[Ⅲ级/较重]",
        }
    ]
    # 低的警報撐不起官方層（WNZ 沒有 TAF）：每格照模式算
    assert all(s["official"] is None and s["basis"] != "official" for s in wnz["slots"])
    assert all(by[i]["warnings"] == [] for i in SWIC_ICAOS - {"ZSWZ"})


# ---- 執行與失敗處理 ----


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "airports.json").write_text((ROOT / "airports.json").read_text("utf-8"), "utf-8")
    names = (ROOT / "typhoon_names.json").read_text("utf-8")  # HD34c：airports.json 旁邊
    (tmp_path / "typhoon_names.json").write_text(names, "utf-8")
    (tmp_path / "confirmed.json").write_text("[]", "utf-8")
    monkeypatch.setattr(build.flights, "fetch", lambda now: build.flights.FlightsData({}, {}))
    monkeypatch.setattr(build.nws, "fetch", lambda zones: build.nws.NwsData([], {}))
    monkeypatch.setattr(build.jma, "fetch", lambda areas: build.jma.JmaData({}, {}))
    monkeypatch.setattr(build.swic, "fetch", lambda airports, now: build.swic.SwicData([], {}, 0))
    # HD34：颱風地圖的兩個來源預設沒有颱風（測試不連網）
    monkeypatch.setattr(build.typhoon, "fetch_cwa", lambda key: build.typhoon.TyphoonData([], {}))
    monkeypatch.setattr(build.typhoon, "fetch_jma", lambda: build.typhoon.TyphoonData([], {}))
    monkeypatch.setattr(build.tcnames, "fetch", _no_names)  # HD34d：名稱表自動更新不連網
    # HD14 的兩個模式、HD16 的 Open-Meteo、HD15 的 WeatherNext 3 預設失敗（測試不連網）
    for mod in (build.aifs, build.aigfs, build.openmeteo, build.wn3):
        monkeypatch.setattr(mod, "fetch", _boom)

    def no_network(*a, **k):  # 模式失敗時會去 Pages 抓上一份；測試不連網
        raise build.requests.ConnectionError("測試不連網")

    monkeypatch.setattr(build.requests, "get", no_network)
    monkeypatch.delenv("JOB_STARTED_AT", raising=False)  # HD25：build.yml 才有
    for k in (build.tdx.ENV_ID, build.tdx.ENV_SECRET):  # HD38：TDX 不連網
        monkeypatch.delenv(k, raising=False)
    for k in (k for keys in ai_config.ENV.values() for k in keys):  # AI 對決（HD5）不呼叫
        monkeypatch.delenv(k, raising=False)
    # 預覽圖（HD1）在 test_og.py 測；這裡不畫，build 的測試才不會每個多幾秒
    monkeypatch.setattr(
        build.og, "render_all", lambda latest, out_dir: {"ok": True, "count": 0, "bytes": 0}
    )
    return tmp_path


REAL_FETCH_CWA = build.typhoon.fetch_cwa  # workspace 換掉之前的（HD34）
REAL_FETCH_NAMES = build.tcnames.fetch  # HD34d


def sample_typhoons():
    """HD34 的手造氣象署回應與 JMA 實抓＋手造 TD（`tests/test_typhoons.py` 同一份）。"""
    t = build.typhoon
    raw = load_json("jma_typhoon.json")
    jma = [
        t.parse_jma(tc, raw[tc]["specifications"], raw[tc]["forecast"])
        for tc in raw
        if tc != "targetTc"
    ]
    cwa_raw = load_json("cwa_typhoon_track.json")
    return t.TyphoonData(t.parse_cwa(cwa_raw), cwa_raw), t.TyphoonData(jma, raw)


def test_typhoon_failures_do_not_touch_latest(workspace, monkeypatch, airports):
    """HD34：颱風來源失敗、或 typhoons.json 組不出來，latest.json 照出、只多 sources 兩筆。"""
    monkeypatch.setattr(build.typhoon, "fetch_jma", _boom)
    monkeypatch.setattr(build, "utcnow", lambda: NOW)
    assert build.main([]) == 0
    out = json.loads((workspace / "public" / "latest.json").read_text("utf-8"))
    assert out["sources"]["jmaTyphoon"] == {
        "ok": False,
        "error": "timeout",
        "seconds": out["sources"]["jmaTyphoon"]["seconds"],
    }
    assert out["sources"]["cwaTyphoon"]["ok"] is True
    assert "typhoons" not in out
    ty = json.loads((workspace / "public" / "typhoons.json").read_text("utf-8"))
    assert (ty["active"], ty["sources"]["jma"]["error"]) == (False, "timeout")

    def broken(*a, **k):
        raise KeyError("bug")

    monkeypatch.setattr(build.typhoons, "build", broken)
    monkeypatch.setattr(build, "utcnow", lambda: NOW + timedelta(hours=6))
    assert build.main([]) == 0
    out2 = json.loads((workspace / "public" / "latest.json").read_text("utf-8"))
    assert out2["generatedAt"] != out["generatedAt"]
    # 組不出來時 data 裡那份沒動，Pages 照舊發布上一份
    assert json.loads((workspace / "public" / "typhoons.json").read_text("utf-8")) == ty


def test_typhoon_names_table_next_to_airports(workspace, monkeypatch, caplog):
    """HD34c：`airports.json` 旁邊的 `typhoon_names.json` 有就照對照表（zh-CN 烟花），讀不了只 log、
    名稱照來源給的。"""
    raw = load_json("jma_typhoon_0826z.json")["TC2637"]
    infa = build.typhoon.parse_jma("TC2637", raw["specifications"], raw["forecast"])
    monkeypatch.setattr(build.typhoon, "fetch_jma", lambda: build.typhoon.TyphoonData([infa], {}))
    monkeypatch.setattr(build, "utcnow", lambda: NOW)
    names = workspace / "typhoon_names.json"  # workspace 已經放了一份
    assert build.main([]) == 0
    ty = json.loads((workspace / "public" / "typhoons.json").read_text("utf-8"))
    assert ty["storms"][0]["name"]["zh-CN"] == "烟花"
    names.unlink()
    monkeypatch.setattr(build, "utcnow", lambda: NOW + timedelta(hours=6))
    with caplog.at_level("ERROR", logger="hongthai"):
        assert build.main([]) == 0
    ty = json.loads((workspace / "public" / "typhoons.json").read_text("utf-8"))
    assert ty["storms"][0]["name"]["zh-CN"] == "In-fa"
    assert any("對照表" in r.getMessage() for r in caplog.records)


def _no_names(year):
    raise build.tcnames.NamesError("測試不連網", "network")


# 名稱表自動更新的測試用：要晚於 repo 那份的 `fetchedAt`（2026-10-26），不然 `read_names` 會改用
# repo 的
AT_1027 = utc(2026, 10, 27, 1, 5)


def _newname_storm(monkeypatch):
    """0826Z 日本氣象廳的烟花（範圍內）改名成名稱表沒有的 Newname。`AT_1027` 接近真的現在，
    模式與觀測來源一律直接失敗（不然會真的去抓那一報）。"""
    for mod in (build.ecmwf, build.gfs, build.taf, build.hko, build.smg):
        monkeypatch.setattr(mod, "fetch", _boom)
    raw = load_json("jma_typhoon_0826z.json")["TC2637"]
    infa = build.typhoon.parse_jma("TC2637", raw["specifications"], raw["forecast"])
    return replace(infa, name_en="Newname")


def test_typhoon_names_refresh_writes_data_branch(workspace, monkeypatch, caplog):
    """HD34d：名稱表查不到 → 當報抓三個官方頁（mock）→ 寫進 `data` 分支那份、這一報就用新名字；
    同一天第二報先讀 `data` 分支那份、不再抓。repo 的那份不動。"""
    from test_tcnames import NEW, _fake_http, _official

    storm = _newname_storm(monkeypatch)
    monkeypatch.setattr(build.typhoon, "fetch_jma", lambda: build.typhoon.TyphoonData([storm], {}))
    monkeypatch.setattr(build.tcnames, "fetch", REAL_FETCH_NAMES)
    calls: list[str] = []
    _fake_http(monkeypatch, _official(*NEW), calls)
    monkeypatch.setattr(build, "utcnow", lambda: AT_1027)
    repo_names = (workspace / "typhoon_names.json").read_text("utf-8")
    with caplog.at_level("WARNING", logger="hongthai"):
        assert build.main([]) == 0
    assert len(calls) == 4
    ty = json.loads((workspace / "public" / "typhoons.json").read_text("utf-8"))
    (s,) = ty["storms"]
    assert s["name"] == {"zh-TW": "新名甲", "zh-HK": "新名乙", "zh-CN": "新名丙", "en": "Newname"}
    data = json.loads((workspace / "data" / "typhoon_names.json").read_text("utf-8"))
    assert any(r["en"] == "Newname" for r in data["names"]) and len(data["names"]) == 140
    assert data["refreshTried"] == {"date": "2026-10-27", "names": ["NEWNAME"]}
    assert data["sources"]["zh-TW"]["fetchedAt"] == "2026-10-27T01:05Z"
    assert (workspace / "typhoon_names.json").read_text("utf-8") == repo_names
    assert any(r.getMessage() == "颱風名稱 Newname（2631）：refreshed" for r in caplog.records)
    # 同一天第二報：名字在 data 分支那份裡，不抓
    calls.clear()
    monkeypatch.setattr(build, "utcnow", lambda: AT_1027 + timedelta(hours=6))
    assert build.main([]) == 0
    assert calls == []
    ty = json.loads((workspace / "public" / "typhoons.json").read_text("utf-8"))
    assert ty["storms"][0]["name"]["zh-HK"] == "新名乙"


def test_typhoon_names_refresh_failed_falls_back(workspace, monkeypatch, caplog):
    """抓不到：名稱表不換、只記今天抓過（同一天不再抓），名稱退回氣象署的譯名 → 英文名。"""
    storm = _newname_storm(monkeypatch)
    monkeypatch.setattr(build.typhoon, "fetch_jma", lambda: build.typhoon.TyphoonData([storm], {}))
    calls = []
    monkeypatch.setattr(build.tcnames, "fetch", lambda year: calls.append(year) or _no_names(year))
    monkeypatch.setattr(build, "utcnow", lambda: AT_1027)
    with caplog.at_level("WARNING", logger="hongthai"):
        assert build.main([]) == 0
    assert calls == [2026]
    ty = json.loads((workspace / "public" / "typhoons.json").read_text("utf-8"))
    # 日本氣象廳那份、沒配到氣象署（沒有中文名可借）→ 三種中文都是英文名
    assert ty["storms"][0]["name"] == dict.fromkeys(("zh-TW", "zh-HK", "zh-CN", "en"), "Newname")
    data = json.loads((workspace / "data" / "typhoon_names.json").read_text("utf-8"))
    repo = json.loads((workspace / "typhoon_names.json").read_text("utf-8"))
    assert (data["names"], data["sources"]) == (repo["names"], repo["sources"])
    assert data["refreshTried"] == {"date": "2026-10-27", "names": ["NEWNAME"]}
    assert any(
        r.getMessage() == "颱風名稱 Newname（2631）：fetch_failed（network）"
        for r in caplog.records
    )
    # 配到氣象署那份（有中文名）：三種中文都借氣象署的
    cwa = build.typhoon.Storm(
        "cwa", "ty30", None, "新名", "NEWNAME", storm.issued_at, [], storm.now, []
    )
    monkeypatch.setattr(
        build.typhoon, "fetch_cwa", lambda key: build.typhoon.TyphoonData([cwa], {})
    )
    monkeypatch.setattr(build, "utcnow", lambda: AT_1027 + timedelta(hours=6))
    assert build.main([]) == 0
    assert calls == [2026]  # 同一天不再抓
    ty = json.loads((workspace / "public" / "typhoons.json").read_text("utf-8"))
    (s,) = ty["storms"]
    assert s["name"] == {"zh-TW": "新名", "zh-HK": "新名", "zh-CN": "新名", "en": "Newname"}
    # 名稱表更新本身出錯（程式錯誤）：只 log，這一報照舊表出
    monkeypatch.setattr(build.typhoons, "refresh_names", _boom)
    monkeypatch.setattr(build, "utcnow", lambda: AT_1027 + timedelta(hours=12))
    with caplog.at_level("ERROR", logger="hongthai"):
        assert build.main([]) == 0
    ty = json.loads((workspace / "public" / "typhoons.json").read_text("utf-8"))
    assert (
        ty["generatedAt"] == "2026-10-27T13:05:00Z" and ty["storms"][0]["name"]["zh-CN"] == "新名"
    )
    assert any("自動更新失敗" in r.getMessage() for r in caplog.records)


def test_pipeline_crash_republishes_previous_typhoons(workspace, monkeypatch):
    (workspace / "data").mkdir()
    (workspace / "data" / "latest.json").write_text('{"schema": 1, "airports": []}', "utf-8")
    (workspace / "data" / "typhoons.json").write_text('{"active": false}', "utf-8")
    monkeypatch.setattr(build, "run", lambda **kw: (_ for _ in ()).throw(RuntimeError("bug")))
    assert build.main([]) == 1
    assert (workspace / "public" / "typhoons.json").read_text("utf-8") == '{"active": false}'


def _airport(out, icao):
    return next(a for a in out["airports"] if a["icao"] == icao)


def _boom(*a, **k):
    raise build.ecmwf.EcmwfError("down", "timeout")


def test_all_sources_fail_still_outputs(workspace, monkeypatch):
    mods = (build.ecmwf, build.gfs, build.taf, build.hko, build.smg, build.nws, build.jma)
    for mod in (*mods, build.swic):
        monkeypatch.setattr(mod, "fetch", _boom)
    monkeypatch.setattr(build.typhoon, "fetch_cwa", REAL_FETCH_CWA)  # 沒設授權碼
    monkeypatch.setattr(build.typhoon, "fetch_jma", _boom)
    monkeypatch.delenv("CWA_API_KEY", raising=False)
    assert build.main([]) == 0
    out = json.loads((workspace / "public" / "latest.json").read_text("utf-8"))
    assert {
        k: v["ok"] for k, v in out["sources"].items() if k not in ("flights", "tdx", "ai")
    } == dict.fromkeys((*build.SOURCE_NAMES, "cwaTyphoon", "jmaTyphoon", "wn3"), False)
    assert out["sources"]["cwaTyphoon"]["error"] == "no_api_key"
    # HD15b：預設 `private` 每報都跑 wn3；測試沒有服務帳號
    wn = out["sources"]["wn3"]
    assert (wn["error"], wn["mode"]) == ("no_credentials", "private")
    # HD34：兩個都失敗、沒有上一份 → 沒有颱風（網頁不畫）
    ty = json.loads((workspace / "public" / "typhoons.json").read_text("utf-8"))
    assert (ty["active"], ty["storms"], ty["sources"]["jma"]) == (
        False,
        [],
        {"ok": False, "error": "timeout"},
    )
    assert out["sources"]["cwa"]["error"] == "no_api_key"
    assert out["runs"] == {
        "ecmwf": None,
        "ecmwfEns": None,
        "gfs": None,
        "aifs": None,
        "aigfs": None,
        "icon": None,  # HD16
        "jma": None,
        "wn2-ens": None,
        "gem": None,  # HD33b
        "arpege": None,
        "cma": None,
    }
    assert all(s["level"] == "unknown" for a in out["airports"] for s in a["slots"])
    # 沒有上一份、全部 unknown → 沒有機場要評；沒設金鑰照樣記 no_api_key
    assert out["sources"]["ai"]["errors"] == {"claude": "no_api_key", "gemini": "no_api_key"}
    assert all(a["ai"]["claude"]["status"] == "skipped" for a in out["airports"])
    # data/ 裡有 latest 與歷史，public/history 也有
    assert (workspace / "data" / "latest.json").exists()
    assert len(list((workspace / "public" / "history").glob("*.json"))) == 1


def test_full_build_from_fixtures(workspace, monkeypatch, airports):
    """整個 `build.main` 用 fixtures 跑一次：51 個機場都有 20 格，原始快照都寫了。"""
    ec, gf, tf, hk, cw, sm, nw = sample_inputs(airports)
    gf = GfsData(utc(2026, 10, 18, 12), gfs.parse_file(FIXTURES / "gfs_all_f120.grb2", airports))
    tf.raw.update(taf=load_json("taf.json"), metar=load_json("metar.json"))
    hk.raw.update(tc={})
    sm.raw.update(c=(FIXTURES / "smg_c_typhoon_sig3.xml").read_text("utf-8"))
    nw.raw.update(load_json("nws_alerts_active_guz001_typhoon.json"))
    zones_asked = []
    monkeypatch.setattr(build.ecmwf, "fetch", lambda *a, **k: ec)
    monkeypatch.setattr(build.gfs, "fetch", lambda *a, **k: gf)
    af, ag = sample_ai_models(airports)
    monkeypatch.setattr(build.aifs, "fetch", lambda *a, **k: af)
    monkeypatch.setattr(build.aigfs, "fetch", lambda *a, **k: ag)
    monkeypatch.setattr(build.taf, "fetch", lambda *a, **k: tf)
    monkeypatch.setattr(build.hko, "fetch", lambda: hk)
    monkeypatch.setattr(build.cwa, "fetch", lambda *a: cw)
    monkeypatch.setattr(build.smg, "fetch", lambda: sm)
    monkeypatch.setattr(build.nws, "fetch", lambda zones: zones_asked.extend(zones) or nw)
    jm = sample_jma(airports)
    areas_asked = []
    monkeypatch.setattr(build.jma, "fetch", lambda areas: areas_asked.extend(areas) or jm)
    sw = sample_swic()
    swic_asked = []
    monkeypatch.setattr(build.swic, "fetch", lambda aps, now: swic_asked.extend(aps) or sw)
    om = sample_openmeteo(airports)
    monkeypatch.setattr(build.openmeteo, "fetch", lambda *a, **k: om)
    ct, jt = sample_typhoons()
    monkeypatch.setattr(build.typhoon, "fetch_cwa", lambda key: ct)
    monkeypatch.setattr(build.typhoon, "fetch_jma", lambda: jt)
    monkeypatch.setattr(build, "utcnow", lambda: NOW)
    monkeypatch.setattr(build.ai, "EVALUATORS", {"claude": fake_ai("high"), "gemini": fake_ai()})
    assert build.main([]) == 0
    assert zones_asked == ["GUZ001"]
    assert {a.icao for a in swic_asked} == SWIC_ICAOS  # HD29：只給看 cma／kma／pagasa 的機場
    assert sorted(a.class20 for a in areas_asked) == sorted(
        a.jma_area.class20 for a in airports if a.icao in JMA_ICAOS
    )
    out = json.loads((workspace / "public" / "latest.json").read_text("utf-8"))
    # HD38：TDX 沒設金鑰（測試不連網）是 not_configured，其他都成功
    tdx_status = out["sources"]["tdx"]
    assert tdx_status == {"ok": False, "error": "not_configured", "calls": 0, "seconds": 0.0}
    # HD15b：預設 `private`，沒有服務帳號是 no_credentials（只有中繼資料）
    assert out["sources"]["wn3"]["error"] == "no_credentials"
    assert all(s["ok"] for k, s in out["sources"].items() if k not in ("tdx", "wn3"))
    assert [a["icao"] for a in out["airports"]] == ICAOS
    assert all(len(a["slots"]) == 20 for a in out["airports"])
    assert {a["icao"] for a in out["airports"] if a["taf"]} == TAF_ICAOS
    assert {a["icao"] for a in out["airports"] if a["metar"]} == METAR_ICAOS
    assert [r["id"] for r in out["regions"]] == list(REGIONS)
    raw = workspace / "data" / "history" / "raw" / "2026-10-18"
    assert sorted(p.name for p in raw.iterdir()) == [
        f"0810Z-{n}.json"
        for n in (
            "cwa-typhoon",  # HD34（排序 `-` 在 `.` 前面）
            "cwa",
            "hko",
            "jma-typhoon",
            "jma",
            "metar",
            "nws",
            "openmeteo",
            "smg",
            "swic",
            "taf",
        )
    ]
    # HD34：typhoons.json 在 data 根目錄與 Pages（只放最新一份）；latest.json 只多兩個 sources
    assert json.loads((raw / "0810Z-jma-typhoon.json").read_text("utf-8")) == jt.raw
    ty = json.loads((workspace / "public" / "typhoons.json").read_text("utf-8"))
    assert ty == json.loads((workspace / "data" / "typhoons.json").read_text("utf-8"))
    assert ty["generatedAt"] == out["generatedAt"] and ty["active"] is True
    assert [(s["id"], s["source"]) for s in ty["storms"]] == [
        ("2630", "cwa"),
        ("jma-TC2638", "jma"),
    ]
    assert {k: out["sources"][k]["storms"] for k in ("cwaTyphoon", "jmaTyphoon")} == {
        "cwaTyphoon": 2,
        "jmaTyphoon": 3,
    }
    assert json.loads((raw / "0810Z-swic.json").read_text("utf-8")) == sw.raw
    assert out["sources"]["swic"]["caps"] == 1 and "capErrors" not in out["sources"]["swic"]
    wnz = _airport(out, "ZSWZ")
    assert [(w["source"], w["kind"], w["level"]) for w in wnz["warnings"]] == [
        ("cma", "cma_gale_yellow", "low")
    ]
    # HD16：Open-Meteo 原文不縮排（約 1.2 MB）
    assert json.loads((raw / "0810Z-openmeteo.json").read_text("utf-8")) == om.raw
    assert "\n " not in (raw / "0810Z-openmeteo.json").read_text("utf-8")
    assert out["sources"]["openmeteo"] == {
        "ok": True,
        "seconds": out["sources"]["openmeteo"]["seconds"],
        "bytes": 2_300_000,
        "calls": 397.8,
    }
    assert (out["runs"]["icon"], out["runs"]["jma"], out["runs"]["wn2-ens"]) == (
        "2026-10-18T00:00:00Z",
        "2026-10-17T18:00:00Z",
        None,
    )
    # HD14：latest.json 與 history/<時間>.json 不縮排（一行＋結尾換行）；原始快照照舊縮排
    for p in (
        workspace / "public" / "latest.json",
        workspace / "data" / "latest.json",
        workspace / "data" / "history" / "20261018T0810Z.json",
        workspace / "public" / "history" / "20261018T0810Z.json",
    ):
        text = p.read_text("utf-8")
        assert text == json.dumps(out, ensure_ascii=False, separators=(",", ":")) + "\n", p
    assert "\n " in (raw / "0810Z-taf.json").read_text("utf-8")


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
    names = (
        "ecmwf",
        "gfs",
        "aifs",
        "aigfs",
        "openmeteo",
        "taf",
        "hko",
        "smg",
        "nws",
        "jma",
        "swic",
    )
    for name in names:
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


# ---- 颱風路徑（HD21）----


def _events_json(workspace, start="2026-10-18", end="2026-10-20"):
    (workspace / "events.json").write_text(
        json.dumps({"events": [{"id": "29W", "name": "CHAMPI", "from": start, "to": end}]}),
        encoding="utf-8",
    )


def test_tracks_only_during_event(workspace, monkeypatch, airports):
    """事件期間外：不多抓海平面氣壓、不跑 `tracks`、`sources` 沒有 `tracks`。"""
    _, gf, *_ = sample_inputs(airports)
    asked = []
    _fail_all_but(monkeypatch, gfs=lambda *a, **k: asked.append(k) or gf)
    monkeypatch.setattr(build.tracks, "build_tracks", _boom)
    _events_json(workspace, "2026-10-19", "2026-10-28")  # NOW 是台灣 10/18
    assert build.main([]) == 0
    out = json.loads((workspace / "public" / "latest.json").read_text("utf-8"))
    assert "tracks" not in out["sources"]
    assert asked == [{"mslp": False}]
    assert "tracks" not in {line["source"] for line in _timing_lines(workspace)}


def test_tracks_source_in_event(workspace, monkeypatch, airports):
    ec, gf, *_ = sample_inputs(airports)
    af, ag = sample_ai_models(airports)
    asked = {}

    def fetch(name, data):
        def f(*a, **k):
            asked[name] = k.get("mslp")
            return data

        return f

    # AIGFS 失敗（`_fail_all_but` 的預設）→ 不在 mslp 裡
    _fail_all_but(
        monkeypatch, ecmwf=lambda *a, **k: ec, gfs=fetch("gfs", gf), aifs=fetch("aifs", af)
    )
    gf.mslp_files = [workspace / "g.grib2"]
    got = {}

    def fake_build_tracks(history, evs, ifs_run, mslp, workdir):
        got.update(history=history, ids=[e.id for e in evs], ifs_run=ifs_run, mslp=mslp)
        return build.tracks.TracksResult(bytes=1_300_000)

    monkeypatch.setattr(build.tracks, "build_tracks", fake_build_tracks)
    _events_json(workspace)
    assert build.main([]) == 0
    out = json.loads((workspace / "public" / "latest.json").read_text("utf-8"))
    src = out["sources"]["tracks"]
    assert isinstance(src.pop("seconds"), float)
    assert src == {"ok": True, "bytes": 1_300_000}
    assert asked == {"gfs": True, "aifs": True}
    assert got["history"] == Path("data") / "history"  # 相對於工作目錄
    assert got["ids"] == ["29W"] and got["ifs_run"] == ec.run
    assert got["mslp"] == {"gfs": (gf.run, [workspace / "g.grib2"]), "aifs": (af.run, [])}
    line = next(x for x in _timing_lines(workspace) if x["source"] == "tracks")
    assert (line["ok"], line["bytes"]) == (True, 1_300_000)


def test_tracks_partial_or_timeout_not_fatal(workspace, monkeypatch, airports):
    _, gf, *_ = sample_inputs(airports)
    _fail_all_but(monkeypatch, gfs=lambda *a, **k: gf)
    _events_json(workspace)
    monkeypatch.setattr(
        build.tracks,
        "build_tracks",
        lambda *a: build.tracks.TracksResult(failed=["ifs-ens@2026-10-18T00:00:00Z"]),
    )
    assert build.main([]) == 0
    out = json.loads((workspace / "public" / "latest.json").read_text("utf-8"))
    assert out["sources"]["tracks"]["ok"] is False
    assert out["sources"]["tracks"]["error"] == "partial"

    def slow(*a):
        time.sleep(2)

    monkeypatch.setattr(build.tracks, "build_tracks", slow)
    monkeypatch.setitem(build.BUDGET_S, "tracks", 0.2)
    assert build.main([]) == 0
    out = json.loads((workspace / "public" / "latest.json").read_text("utf-8"))
    assert out["sources"]["tracks"] == {"ok": False, "error": "timeout", "seconds": 0.2}
    assert out["sources"]["gfs"]["ok"] is True


def test_track_events_bad_events_json(tmp_path, caplog):
    (tmp_path / "events.json").write_text("{壞掉", encoding="utf-8")
    assert build.track_events(tmp_path / "events.json", NOW) == []
    assert build.track_events(None, NOW) == []
    assert "events.json 讀不了" in caplog.text


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
    assert out["runs"] == {
        "ecmwf": "2026-10-18T00:00:00Z",
        "ecmwfEns": None,
        "gfs": None,
        "aifs": None,
        "aigfs": None,
        "icon": None,  # HD16
        "jma": None,
        "wn2-ens": None,
        "gem": None,  # HD33b
        "arpege": None,
        "cma": None,
    }
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
        **EC_HD8_NONE,
    }
    assert s0["model"]["gfs"] == {
        "gustMs": None,
        "gustKt": None,
        "crosswindKt": None,
        **GFS_HD8_NONE,
    }
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
    assert out["runs"] == {
        "ecmwf": None,
        "ecmwfEns": None,
        "gfs": None,
        "aifs": None,
        "aigfs": None,
        "icon": None,  # HD16
        "jma": None,
        "wn2-ens": None,
        "gem": None,  # HD33b
        "arpege": None,
        "cma": None,
    }
    s0 = _airport(out, "VHHH")["slots"][0]
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
    slots = _airport(out, "VHHH")["slots"]
    s12 = slots[12]
    assert s12["from"] == "2026-10-21T06:00:00Z"
    assert s12["model"]["gfs"] == {
        "gustMs": 20.6,
        "gustKt": 40.0,
        "crosswindKt": 20.0,
        **GFS_HD8_NONE,
    }
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
    s12 = _airport(out, "VHHH")["slots"][12]
    assert s12["from"] == "2026-10-21T06:00:00Z"
    # HD2 以前的格式：gustKt 由 gustMs 補（16 m/s ≈ 31.1 節）
    assert s12["model"]["gfs"] == {
        "gustMs": 16.0,
        "gustKt": 31.1,
        "crosswindKt": 20.0,
        **GFS_HD8_NONE,
    }


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
    assert all(s["model"]["gfs"]["gustMs"] is None for s in _airport(out, "VHHH")["slots"])


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
        "aifs",
        "aigfs",
        "openmeteo",  # HD16
        "taf",
        "hko",
        "cwa",
        "smg",
        "nws",
        "jma",
        "cwaTyphoon",  # HD34
        "jmaTyphoon",
        "swic",  # HD29
        "flights",
        "tdx",  # HD38
        "wn3",  # HD15b：`private` 在算完 G 之後跑
        "airports3h",  # HD35
        "ai",
        "og",
        "done",
    ]
    assert {r["run"] for r in lines} == {"2026-10-18T08:10:00Z"}
    assert lines[0] == {
        "run": "2026-10-18T08:10:00Z",
        "source": "start",
        "ok": True,
        "seconds": 0,
        "commit": "0123456",
        # HD25：手動（預設）沒有排定時間
        "trigger": "manual",
        "slot": None,
        "startedAt": "2026-10-18T08:10:00Z",
        "delayMinutes": None,
    }
    ec_line = lines[1]
    assert set(ec_line) == {"run", "source", "ok", "error", "seconds", "bytes", "mirror"}
    assert (ec_line["ok"], ec_line["error"], ec_line["mirror"]) == (False, "timeout", None)
    gfs_line = lines[2]
    assert set(gfs_line) == {"run", "source", "ok", "error", "seconds", "bytes", "mirror"}
    assert (gfs_line["ok"], gfs_line["error"], gfs_line["bytes"]) == (True, None, 0)
    assert gfs_line["mirror"] is None  # 假的 fetch 沒有記 mirror
    assert lines[8]["error"] == "no_api_key"
    for line in lines[3:5]:  # HD14：aifs、aigfs 也記 mirror
        assert set(line) == {"run", "source", "ok", "error", "seconds", "bytes", "mirror"}
    om_line = lines[5]  # HD16：openmeteo 記加權呼叫次數（失敗是 null）
    assert set(om_line) == {"run", "source", "ok", "error", "seconds", "bytes", "calls"}
    assert (om_line["ok"], om_line["calls"]) == (False, None)
    assert [(r["source"], r["ok"]) for r in lines[12:14]] == [
        ("cwaTyphoon", True),
        ("jmaTyphoon", True),
    ]
    tdx_line = lines[16]  # HD38：tdx 記資料請求數（沒設金鑰是 0），每月上限從這裡數
    assert set(tdx_line) == {"run", "source", "ok", "error", "seconds", "bytes", "calls"}
    assert (tdx_line["error"], tdx_line["calls"]) == ("not_configured", 0)
    wn_line = lines[17]  # HD15b：`private` 沒有服務帳號；只有中繼資料的欄位
    assert set(wn_line) == {
        *("run", "source", "ok", "error", "seconds", "bytes"),
        *("mode", "via", "estimateBytes", "bytesBilled", "stored", "bqError", "zarrError"),
    }
    assert (wn_line["error"], wn_line["mode"]) == ("no_credentials", "private")
    ap_line = lines[18]  # HD35：機場頁的 3 小時格
    assert set(ap_line) == {
        *("run", "source", "ok", "error", "seconds", "bytes", "files", "mismatches"),
    }
    assert (ap_line["ok"], ap_line["error"], ap_line["files"]) == (True, None, 51)
    ai_line = lines[19]  # HD34 在 jma 後面多 cwaTyphoon、jmaTyphoon；HD15b 在 tdx 後面多 wn3
    assert set(ai_line) == {
        *("run", "source", "ok", "error", "seconds", "bytes", "calls"),
        *("usage", "costUsd"),  # HD26
        "errorMessages",  # HD30
    }
    assert ai_line["bytes"] == 0 and ai_line["calls"] == {"claude": 0, "gemini": 0}
    # 兩個都沒金鑰：沒有回應，合計全是 null、calls 0、費用 null
    assert ai_line["usage"] == {
        "claude": {
            "input": None,
            "output": None,
            "cacheRead": None,
            "cacheWrite": None,
            "calls": 0,
        },
        "gemini": {"input": None, "output": None, "thinking": None, "cacheRead": None, "calls": 0},
    }
    assert ai_line["costUsd"] == {"claude": None, "gemini": None}
    assert ai_line["errorMessages"] == {"claude": None, "gemini": None}  # no_api_key 沒有訊息
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


def test_pages_history_only_last_7_days(tmp_path):
    """Pages 的 `history/` 只放 `generatedAt`（＝檔名）在 7 天內的；archive 全部保留。"""
    archive, out = tmp_path / "data", tmp_path / "public"
    stamps = []
    for days in (0, 1, 6.9, 7.1, 30):
        t = NOW - timedelta(days=days)
        stamps.append(f"{t:%Y%m%dT%H%M}Z.json")
        build._dump(archive / "history" / stamps[-1], {"generatedAt": build.iso(t)})
    build._dump(archive / "history" / "notes.json", {})  # 檔名不是時間的不發布
    build._dump(out / "history" / stamps[-1], {})  # 上次發布留下、已經過期的要刪
    build.publish(out, archive, {"generatedAt": build.iso(NOW)}, NOW)
    assert sorted(p.name for p in (out / "history").iterdir()) == sorted(stamps[:3])
    assert len(list((archive / "history").glob("*.json"))) == 6
    assert json.loads((out / "latest.json").read_text("utf-8"))["generatedAt"] == build.iso(NOW)


# ---- AI 對決（HD5）----


def _risky_build(workspace, monkeypatch, airports):
    """ecmwf 以外都失敗；用 fixtures 的 HRES，有幾個機場會有中、高的格。"""
    ec, *_ = sample_inputs(airports)
    _fail_all_but(monkeypatch, ecmwf=lambda *a, **k: ec)


def _out(workspace):
    return json.loads((workspace / "public" / "latest.json").read_text("utf-8"))


def test_build_ai_no_api_key(workspace, monkeypatch, airports):
    """本機沒有金鑰：被選的機場兩顆都 no_api_key（evaluatedAt null），其他照出。"""
    _risky_build(workspace, monkeypatch, airports)
    assert build.main([]) == 0
    out = _out(workspace)
    selected = [a for a in out["airports"] if a["ai"]["claude"].get("error") == "no_api_key"]
    assert selected, "fixtures 應該有中、高的格"
    for a in selected:
        assert a["ai"]["evaluatedAt"] is None
        assert a["ai"]["claude"]["error"] == a["ai"]["gemini"]["error"] == "no_api_key"
    src = out["sources"]["ai"]
    assert src["ok"] is False and src["calls"] == {"claude": 0, "gemini": 0}
    assert src["error"] == "claude:no_api_key,gemini:no_api_key"
    assert out["ai"]["models"] == {"claude": "claude-opus-5-5", "gemini": "gemini-4-argon"}
    # 戰績檔與每日次數在 data 分支，不在 Pages
    hist = workspace / "data" / "history" / "ai"
    assert sorted(p.name for p in hist.iterdir()) == ["2026-10-18.json", "calls-2026-10-18.json"]
    assert len(json.loads((hist / "2026-10-18.json").read_text("utf-8"))) == 51
    assert not (workspace / "public" / "history" / "ai").exists()


def test_build_ai_timeout(workspace, monkeypatch, airports):
    _risky_build(workspace, monkeypatch, airports)
    monkeypatch.setattr(
        build.ai, "EVALUATORS", {"claude": fake_ai("low"), "gemini": fake_ai("high", delay=3)}
    )
    monkeypatch.setitem(build.BUDGET_S, "ai", 0.5)
    # HD23 的預算守門（剩不到逾時＋5 秒不送）在 0.5 秒的預算下一個都不會送；這裡測的是送出後預算到
    monkeypatch.setattr(build.ai, "SEND_MIN_LEFT_S", {"claude": 0.1, "gemini": 0.1})
    t0 = time.monotonic()
    assert build.main([]) == 0
    assert time.monotonic() - t0 < 2.5
    out = _out(workspace)
    picked = [a["ai"] for a in out["airports"] if a["ai"]["claude"]["status"] == "ok"]
    assert len(picked) == 20 and all(ai["gemini"]["error"] == "timeout" for ai in picked)
    src = out["sources"]["ai"]
    assert src["ok"] is True and src["errors"] == {"gemini": "timeout"} and src["seconds"] == 0.5
    line = next(r for r in _timing_lines(workspace) if r["source"] == "ai")
    assert line["seconds"] == 0.5 and line["calls"]["claude"] == len(picked)


def test_build_ai_crash_does_not_break_build(workspace, monkeypatch, airports):
    _risky_build(workspace, monkeypatch, airports)

    def crash(*a, **k):
        raise RuntimeError("bug")

    monkeypatch.setattr(build.ai, "Duel", crash)
    assert build.main([]) == 0
    out = _out(workspace)
    assert out["sources"]["ai"]["ok"] is False
    assert all(a["ai"]["claude"]["error"] == "network" for a in out["airports"])
    assert any(s["level"] == "high" for a in out["airports"] for s in a["slots"])


# ---- 新天氣種類（HD8）----


def test_metar_and_taf_json_weather_fields(latest):
    """舊的 fixtures 去掉了 `visib`／`wxString`／`clouds`：欄位照出、值是空的。"""
    by = {a["icao"]: a for a in latest["airports"]}
    for icao in TAF_ICAOS:
        assert {k: by[icao]["taf"][k] for k in ("visibilityM", "wx", "ceilingFt")} == {
            "visibilityM": None,
            "wx": [],
            "ceilingFt": None,
        }
    m = build.metar_json(taf.Metar(NOW, 90, 5, None, "METAR … 0300 FG VV001", 300, ("FG",), 100))
    assert (m["visibilityM"], m["wx"], m["ceilingFt"]) == (300, ["FG"], 100)


def test_main_period_covers_now():
    t0 = utc(2026, 10, 18, 6)

    def period(kind, a, b, vis):
        return taf.TafPeriod(
            t0 + timedelta(hours=a), t0 + timedelta(hours=b), kind, 0, 5, None, vis
        )

    info = taf.TafInfo(
        None,
        None,
        None,
        "",
        [
            period("main", 0, 4, 9999),
            period("tempo", 0, 6, 800),
            period("main", 4, 24, 3000),  # BECMG 之後的主時段
        ],
    )
    assert build.main_period(info, t0 + timedelta(hours=1)).vis_m == 9999
    assert build.main_period(info, t0 + timedelta(hours=5)).vis_m == 3000
    assert build.main_period(info, t0 + timedelta(hours=30)).vis_m == 9999  # 都過了取第一個
    assert build.taf_json(info, t0 + timedelta(hours=5))["visibilityM"] == 3000


def _hd8_inputs(airports):
    ec, gf, tf, hk, cw, sm, nw = sample_inputs(airports)
    by_lang = {lang: load_json(f"hko_warnsum_tc8ne_{lang}.json") for lang in ("tc", "en", "sc")}
    for lang, name, color in (
        ("tc", "暴雨警告信號", "黑色"),
        ("en", "Rainstorm Warning Signal", "Black"),
        ("sc", "暴雨警告信号", "黑色"),
    ):
        by_lang[lang]["WRAIN"] = {
            "name": name,
            "code": "WRAINB",
            "type": color,
            "actionCode": "ISSUE",
            "issueTime": "2026-10-18T15:00:00+08:00",
        }
        by_lang[lang]["WTS"] = {
            "name": "Thunderstorm Warning",
            "code": "WTS",
            "actionCode": "ISSUE",
            "issueTime": "2026-10-18T15:00:00+08:00",
        }
    hk = hko.HkoData(hko.parse_signal(by_lang), by_lang, hko.parse_warnings(by_lang))
    hz_raw = load_json("cwa_w-c0033-001_heavy_rain.json")
    cw = cwa.CwaData(cw.bulletins, {}, cwa.parse_hazards(hz_raw, utc(2026, 10, 20, 2)), hz_raw)
    return ec, gf, tf, hk, cw, sm, nw


def test_hd8_warnings_in_output(airports):
    ec, gf, tf, hk, cw, sm, nw = _hd8_inputs(airports)
    status = {n: {"ok": True} for n in build.SOURCE_NAMES}
    out = build.assemble(
        now=NOW,
        regions=load_regions(ROOT / "airports.json"),
        airports=airports,
        confirmed=[],
        status=status,
        ec=ec,
        gf=gf,
        tf=tf,
        hk=hk,
        cw=cw,
        sm=sm,
        nw=nw,
    )
    out = json.loads(json.dumps(out))
    by = {a["icao"]: a for a in out["airports"]}
    vhhh = {w["kind"]: w for w in by["VHHH"]["warnings"]}
    assert set(vhhh) == {"tc_signal", "rainstorm_black", "thunderstorm"}
    assert (vhhh["rainstorm_black"]["source"], vhhh["rainstorm_black"]["code"]) == ("hko", "WRAINB")
    assert vhhh["rainstorm_black"]["level"] == "medium"
    assert vhhh["thunderstorm"]["level"] == "low" and vhhh["thunderstorm"]["code"] == "WTS"
    assert by["VHHH"]["slots"][0]["official"]["warnings"] == [
        "tc_signal",
        "rainstorm_black",
        "thunderstorm",
    ]
    # 澳門不看天文台
    assert all(w["source"] != "hko" for w in by["VMMC"]["warnings"])
    # 金門：氣象署大豪雨特報（fixture 的金門縣）→ 中，主因雨
    (kinmen,) = [w for w in by["RCBS"]["warnings"] if w["kind"] == "cwa_heavy_rain"]
    assert (kinmen["source"], kinmen["kind"], kinmen["level"], kinmen["detail"]) == (
        "cwa",
        "cwa_heavy_rain",
        "medium",
        "大豪雨",
    )
    assert set(kinmen["text"]) == LANGS
    s0 = by["RCBS"]["slots"][0]
    assert (s0["basis"], s0["official"]["kind"], s0["official"]["wx"]) == (
        "official",
        "warning",
        None,
    )
    assert "cwa_heavy_rain" in s0["official"]["warnings"]
    assert "rain" in s0["causes"]  # fixture 同時有陸上颱風警報（算 wind）


def test_cwa_heavy_rain_error_recorded():
    assert build._cwa_extra(cwa.CwaData([], {})) == {}
    assert build._cwa_extra(cwa.CwaData([], {}, hazards_error="http_500")) == {
        "heavyRainOk": False,
        "heavyRainError": "http_500",
    }


def _hd13_cw(bulletins=()):
    hz_raw = load_json("cwa_w-c0033-001_dense_fog.json")
    obs_raw = load_json("cwa_o-a0003-001_obs.json")
    return cwa.CwaData(
        list(bulletins),
        {},
        cwa.parse_hazards(hz_raw, NOW),
        hz_raw,
        obs=cwa.parse_obs(obs_raw, ("467110", "467990")),
        obs_raw=obs_raw,
    )


def test_hd13_kinmen_matsu_in_output(airports):
    """金門：局屬站觀測（霧、能見度 300 公尺）撐起第一格＋濃霧特報；馬祖：觀測全部缺測、
    退回模式。"""
    ec, gf, tf, hk, _, sm, nw = sample_inputs(airports)
    status = {n: {"ok": True} for n in build.SOURCE_NAMES}
    out = build.assemble(
        now=NOW,
        regions=load_regions(ROOT / "airports.json"),
        airports=airports,
        confirmed=[],
        status=status,
        ec=ec,
        gf=gf,
        tf=tf,
        hk=hk,
        cw=_hd13_cw(),
        sm=sm,
        nw=nw,
    )
    out = json.loads(json.dumps(out))
    by = {a["icao"]: a for a in out["airports"]}
    rcbs = by["RCBS"]
    assert rcbs["taf"] is None
    m = rcbs["metar"]
    assert (m["source"], m["observedAt"], m["visibilityM"], m["wx"]) == (
        "cwa",
        "2026-10-18T08:00:00Z",
        300,
        ["FG"],
    )
    assert (m["windDirDeg"], m["windKt"], m["gustKt"], m["ceilingFt"]) == (90, 2.9, 6.2, None)
    assert m["raw"].startswith("CWA 467110 2026-10-18T08:00Z 能見度 0.3 km 陰有霧")
    (fog,) = rcbs["warnings"]
    assert (fog["source"], fog["kind"], fog["level"], fog["detail"]) == (
        "cwa",
        "cwa_dense_fog",
        "medium",
        "濃霧",
    )
    assert fog["text"]["zh-TW"] == "中央氣象署濃霧特報，金門在特報範圍"
    assert set(fog["text"]) == LANGS
    s0, s1 = rcbs["slots"][0], rcbs["slots"][1]
    o = s0["official"]
    assert (o["kind"], o["level"], o["warnings"]) == ("metar", "high", ["cwa_dense_fog"])
    assert (o["windKt"], o["gustKt"]) == (2.9, 6.2)
    assert o["wx"] == {
        "phenomena": ["FG"],
        "visibilityM": 300,
        "ceilingFt": None,
        "rain": "low",
        "snow": "low",
        "fog": "high",
    }
    assert (s0["level"], s0["basis"], s0["causes"]) == ("high", "official", ["fog"])
    # 第二格（12Z 起，現在 + 12 小時內）只有濃霧特報 → 官方層中、主因霧
    assert (s1["official"]["kind"], s1["level"], s1["causes"]) == ("warning", "medium", ["fog"])
    # 馬祖：觀測全部缺測 → 有 metar（source cwa）但第一格不由它撐起
    rcfg = by["RCFG"]
    assert rcfg["metar"]["source"] == "cwa" and rcfg["metar"]["visibilityM"] is None
    assert rcfg["warnings"] == [] and rcfg["slots"][0]["official"] is None
    # AviationWeather 的 METAR 沒有 source 鍵；其他台灣機場沒有濃霧特報
    assert "source" not in by["RCTP"]["metar"]
    assert all(w["kind"] != "cwa_dense_fog" for w in by["RCTP"]["warnings"])


def test_station_metar_prefers_aviationweather(airports):
    rcbs = {a.icao: a for a in airports}["RCBS"]
    cw = _hd13_cw()
    aw = taf.Metar(NOW, 60, 8, None, "METAR RCBS …")
    tf = taf.TafData({}, {"RCBS": aw}, {})
    assert build.station_metar(rcbs, tf, cw) is aw
    assert build.station_metar(rcbs, taf.TafData({}, {}, {}), cw) is cw.obs["467110"]
    assert build.station_metar(rcbs, None, cw) is cw.obs["467110"]
    assert build.station_metar(rcbs, None, None) is None
    rctp = {a.icao: a for a in airports}["RCTP"]
    assert build.station_metar(rctp, None, cw) is None  # 沒有 cwaStation


def test_cwa_obs_error_recorded():
    assert build._cwa_extra(cwa.CwaData([], {}, obs_error="http_500")) == {
        "obsOk": False,
        "obsError": "http_500",
    }
    both = cwa.CwaData([], {}, hazards_error="timeout", obs_error="api_error")
    assert build._cwa_extra(both) == {
        "heavyRainOk": False,
        "heavyRainError": "timeout",
        "obsOk": False,
        "obsError": "api_error",
    }


def test_cwa_obs_raw_written_and_stations_passed(workspace, monkeypatch):
    cw = _hd13_cw()
    got = []

    def fake_fetch(api_key, now, stations=()):
        got.append(stations)
        return cw

    _fail_all_but(monkeypatch)
    monkeypatch.setattr(build.cwa, "fetch", fake_fetch)
    assert build.main([]) == 0
    assert got == [("467110", "467990")]
    raw = workspace / "data" / "history" / "raw" / "2026-10-18"
    assert json.loads((raw / "0810Z-cwa-obs.json").read_text("utf-8")) == cw.obs_raw
    out = json.loads((workspace / "public" / "latest.json").read_text("utf-8"))
    rcbs = {a["icao"]: a for a in out["airports"]}["RCBS"]
    assert rcbs["metar"]["source"] == "cwa" and rcbs["slots"][0]["official"]["kind"] == "metar"


def test_cwa_hazards_raw_written(workspace, monkeypatch, airports):
    *_, cw, _, _ = _hd8_inputs(airports)
    _fail_all_but(monkeypatch)
    monkeypatch.setattr(build.cwa, "fetch", lambda *a: cw)
    assert build.main([]) == 0
    raw = workspace / "data" / "history" / "raw" / "2026-10-18"
    assert json.loads((raw / "0810Z-cwa-hazards.json").read_text("utf-8")) == cw.hazards_raw
    assert (raw / "0810Z-cwa.json").exists()


def test_reuse_copies_rain_and_rescores_causes(workspace, monkeypatch):
    ec = {"p10": 0.1, "p15": 0.0, "p25": 0.0, "hresGustMs": 5.0, "crosswindKt": 2.0}
    ec |= {"rain6hMm": 12.0, "ptype": "snow", "temp2mC": -2.0, "rain": "low", "snow": "high"}
    prev = _prev(
        "2026-10-18T02:10:00Z",
        {"ecmwf": "2026-10-18T00:00:00Z", "ecmwfEns": None, "gfs": None},
        ec=ec,
    )
    _write_prev(workspace, prev)
    _fail_all_but(monkeypatch)
    assert build.main([]) == 0
    out = json.loads((workspace / "public" / "latest.json").read_text("utf-8"))
    s0 = _airport(out, "VHHH")["slots"][0]
    m = s0["model"]["ec"]
    assert (m["rain6hMm"], m["ptype"], m["temp2mC"]) == (12.0, "snow", -2.0)
    assert (m["rain"], m["snow"]) == ("low", "high")  # 照抄來的雨量重算（不是抄等級）
    assert (s0["level"], s0["basis"], s0["causes"]) == ("high", "model", ["snow"])


# ---- 多模式投票（HD14）：沿用與重算 ----


def _entry(mid, run=None, **nums):
    keys = ("gustKt", "gustEstimated", "crosswindKt", "rain6hMm", "ptype", "visibilityM")
    levels = dict.fromkeys(("wind", "rain", "snow", "fog"))
    return {"id": mid, "run": run, **dict.fromkeys(keys), **nums, "levels": levels, "level": None}


def test_aifs_aigfs_failure_reuses_models_entries(workspace, monkeypatch, airports):
    """AIFS、AIGFS 失敗 → 從上一份 `models[]` 同 id 那筆抄數字，重算等級與投票。"""
    ec, gf, *_ = sample_inputs(airports)
    prev = _prev(
        "2026-10-18T02:10:00Z",
        {
            "ecmwf": None,
            "ecmwfEns": None,
            "gfs": None,
            "aifs": "2026-10-18T00:00:00Z",
            "aigfs": "2026-10-17T18:00:00Z",
        },
    )
    prev["airports"][0]["slots"][0]["model"]["models"] = [
        _entry("ifs"),
        _entry("gfs"),
        _entry("ifs-ens"),
        _entry("aifs", "2026-10-18T00:00:00Z", gustKt=50.4, crosswindKt=30.0, rain6hMm=3.0),
        _entry("aigfs", "2026-10-17T18:00:00Z", gustKt=49.0, rain6hMm=65.0),
    ]
    prev["airports"][0]["slots"][0]["model"]["models"][3]["ptype"] = "rain"
    _write_hist(workspace, prev, ok={"aifs": True, "aigfs": True})
    _write_prev(workspace, prev)
    _fail_all_but(monkeypatch, ecmwf=lambda *a, **k: ec, gfs=lambda *a, **k: gf)
    assert build.main([]) == 0
    out = json.loads((workspace / "public" / "latest.json").read_text("utf-8"))
    for name in ("aifs", "aigfs"):
        src = out["sources"][name]
        assert (src["ok"], src["reusedFrom"]) == (False, "2026-10-18T02:10:00Z")
    assert (out["runs"]["aifs"], out["runs"]["aigfs"]) == (
        "2026-10-18T00:00:00Z",
        "2026-10-17T18:00:00Z",
    )
    s0 = _airport(out, "VHHH")["slots"][0]
    by = {e["id"]: e for e in s0["model"]["models"]}
    ai, ag = by["aifs"], by["aigfs"]
    assert (ai["gustKt"], ai["gustEstimated"], ai["crosswindKt"], ai["ptype"]) == (
        50.4,
        True,
        30.0,
        "rain",
    )
    assert ai["run"] == "2026-10-18T00:00:00Z"
    assert ai["levels"] == {"wind": "high", "rain": "low", "snow": "low", "fog": None}
    assert (ag["gustKt"], ag["gustEstimated"], ag["run"]) == (49.0, True, "2026-10-17T18:00:00Z")
    assert ag["levels"] == {"wind": "high", "rain": "high", "snow": None, "fog": None}
    # IFS、GFS、系集照這一報的（沒動）；投票照重算
    assert by["gfs"]["gustKt"] == 40.0 and by["gfs"]["run"] == "2026-10-18T00:00:00Z"
    v = s0["model"]["vote"]
    assert v["level"] == s0["model"]["level"] == s0["level"]
    # VHHH 第一格：fixture 的 HRES 沒有這格（IFS 沒有風）、GFS 40 節中、系集低、AIFS 高、AIGFS 高
    assert (by["ifs"]["levels"]["wind"], by["ifs-ens"]["levels"]["wind"]) == (None, "low")
    assert (v["total"], v["high"], v["medium"], v["low"]) == (4, 2, 3, 1)
    assert v["level"] == "high"  # 高 2 × 2 ≥ 4
    # 別的格（上一份沒有）不抄
    assert _airport(out, "VHHH")["slots"][1]["model"]["models"][3]["gustKt"] is None


def test_rescore_revotes_models():
    """`_rescore` 從 ec／gfs 與原本 `models[]` 的數字重組、重新投票。"""
    slot = {
        "from": "2026-10-18T06:00:00Z",
        "basis": "model",
        "level": "low",
        "causes": [],
        "official": None,
        "gap": False,
        "model": {
            "ec": {"hresGustKt": 50.0, "p49Kt": 0.5},
            "gfs": {"gustKt": 40.0},
            "level": "low",
            "agreement": None,
            "models": [_entry("aifs", "2026-10-18T00:00:00Z", gustKt=45.0)],
            "vote": None,
        },
    }
    build._rescore(slot, Thresholds())
    m = slot["model"]
    assert [e["id"] for e in m["models"]] == [
        "ifs",
        "gfs",
        "ifs-ens",
        "aifs",
        "aigfs",
        "icon",
        "jma",
        "wn2-ens",
        "gem",  # HD33b：旁觀
        "arpege",
        "cma",
    ]
    assert m["models"][3]["run"] == "2026-10-18T00:00:00Z"  # 沒給 runs 時維持原值
    winds = [e["levels"]["wind"] for e in m["models"]]
    assert winds == ["high", "medium", "high", "medium", *[None] * 7]
    # 高 2 × 2 ≥ 4（IFS、系集）→ 高
    assert m["vote"] == {
        "total": 4,
        "high": 2,
        "medium": 3,  # 不含系集
        "mediumTotal": 3,  # HD24
        "low": 0,
        "level": "high",
        "thin": False,
    }
    assert (m["level"], slot["level"], slot["causes"]) == ("high", "high", ["wind"])
    build._rescore(slot, Thresholds(), {"ifs": "2026-10-18T06:00:00Z"})
    assert [e["run"] for e in m["models"]] == ["2026-10-18T06:00:00Z"] + [None] * 10


# ---- 估算陣風的係數（HD18）----


def _hd18_models(airports):
    """每個機場：IFS 陣風 30／平均風 20（1.5）、GFS 陣風 34／平均風 20（1.7），120 小時都一樣。"""
    t0 = utc(2026, 10, 18, 6)
    hres = [
        ecmwf.GustInterval(t0 + timedelta(hours=h - 3), t0 + timedelta(hours=h), 30.0, 90.0, 20.0)
        for h in range(3, 121, 3)
    ]
    ec = ecmwf.EcmwfData(
        utc(2026, 10, 18, 0), None, "no_run", {a.icao: ecmwf.EcmwfPoint(hres) for a in airports}
    )
    pts = [GustPoint(t0 + timedelta(hours=h), 34.0, 90.0, wind_kt=20.0) for h in range(0, 121, 6)]
    gf = GfsData(utc(2026, 10, 18, 0), {a.icao: pts for a in airports})
    return ec, gf


def test_gust_factor_files_and_models_keys(workspace, monkeypatch, airports):
    ec, gf = _hd18_models(airports)
    af, _ = sample_ai_models(airports)
    _fail_all_but(
        monkeypatch,
        ecmwf=lambda *a, **k: ec,
        gfs=lambda *a, **k: gf,
        aifs=lambda *a, **k: af,
    )
    assert build.main([]) == 0
    hist = workspace / "data" / "history" / "gustfactor"
    lines = [json.loads(x) for x in (hist / "2026-10.jsonl").read_text("utf-8").splitlines()]
    assert [r["icao"] for r in lines] == ICAOS
    assert lines[0] == {
        "run": "2026-10-18T08:10:00Z",
        "icao": "RCTP",
        "ifs": [1.5] * 20,
        "gfs": [1.7] * 20,
    }
    doc = json.loads((hist / "latest.json").read_text("utf-8"))
    assert doc["generatedAt"] == "2026-10-18T08:10:00Z"
    assert doc["source"] == "ifs"
    assert doc["window"] == {"from": "2026-09-18T08:10:00Z", "to": "2026-10-18T08:10:00Z"}
    n = 51 * 20
    # HD19：G 只看 IFS（1.5），GFS 的 1.7 照存、只算 `nGfs`
    assert doc["all"] == doc["run"] == {"g": 1.5, "n": n, "nIfs": n, "nGfs": n}
    assert set(doc["airports"]) == set(ICAOS)
    # 首報：每個機場都是 run
    assert doc["airports"]["RCTP"] == {"g": 1.5, "n": 20, "nIfs": 20, "nGfs": 20, "basis": "run"}
    out = json.loads((workspace / "public" / "latest.json").read_text("utf-8"))
    by = {e["id"]: e for e in _airport(out, "RCTP")["slots"][0]["model"]["models"]}
    assert (by["ifs"]["windKt"], by["gfs"]["windKt"], by["ifs-ens"]["windKt"]) == (20.0, 20.0, None)
    ai = by["aifs"]
    assert (ai["windKt"], ai["gustKt"], ai["gustEstimated"]) == (31.0, 46.5, True)
    assert (ai["gustFactor"], ai["gustFactorBasis"]) == (1.5, "run")
    assert all(by[i]["gustFactor"] is None for i in ("ifs", "gfs", "ifs-ens", "aigfs"))
    # 樣本與係數不進 Pages
    assert not (workspace / "public" / "history" / "gustfactor").exists()


def test_reused_aifs_recomputed_with_this_runs_factor(workspace, monkeypatch, airports):
    """AIFS 失敗 → 抄上一份的 `windKt`，用這一報的 G 重算估算陣風（不沿用舊 G）。"""
    ec, gf = _hd18_models(airports)
    prev = _prev(
        "2026-10-18T02:10:00Z",
        {"ecmwf": None, "ecmwfEns": None, "gfs": None, "aifs": "2026-10-18T00:00:00Z"},
    )
    prev["airports"][0]["slots"][0]["model"]["models"] = [
        _entry("ifs"),
        _entry("gfs"),
        _entry("ifs-ens"),
        _entry(
            "aifs",
            "2026-10-18T00:00:00Z",
            windKt=32.0,
            gustKt=44.8,
            gustFactor=1.4,
            gustFactorBasis="default",
            crosswindKt=21.0,
        ),
        _entry("aigfs"),
    ]
    _write_hist(workspace, prev, ok={"aifs": True})
    _fail_all_but(monkeypatch, ecmwf=lambda *a, **k: ec, gfs=lambda *a, **k: gf)
    assert build.main([]) == 0
    out = json.loads((workspace / "public" / "latest.json").read_text("utf-8"))
    assert out["sources"]["aifs"]["reusedFrom"] == "2026-10-18T02:10:00Z"
    ai = _airport(out, "VHHH")["slots"][0]["model"]["models"][3]
    assert (ai["windKt"], ai["gustKt"], ai["crosswindKt"]) == (32.0, 48.0, 22.5)
    assert (ai["gustFactor"], ai["gustFactorBasis"], ai["gustEstimated"]) == (1.5, "run", True)
    assert ai["levels"]["wind"] == "high"  # 48 ≥ 48


def test_gust_factor_failure_falls_back_to_default(workspace, monkeypatch, airports):
    """係數算不出來（例外）只 log，全部用 1.4、`default`，build 照常。"""
    _, gf = _hd18_models(airports)
    af, _ = sample_ai_models(airports)

    def broken(*a, **k):
        raise RuntimeError("壞了")

    monkeypatch.setattr(build.gustfactor, "update", broken)
    _fail_all_but(monkeypatch, gfs=lambda *a, **k: gf, aifs=lambda *a, **k: af)
    assert build.main([]) == 0
    out = json.loads((workspace / "public" / "latest.json").read_text("utf-8"))
    ai = _airport(out, "RCTP")["slots"][0]["model"]["models"][3]
    assert (ai["gustKt"], ai["gustFactor"], ai["gustFactorBasis"]) == (43.4, 1.4, "default")


# ---- HD16：Open-Meteo 三票 ----


def _assemble(airports, om, status=None, **kw):
    ec, gf, tf, hk, cw, sm, nw = sample_inputs(airports)
    return build.assemble(
        now=NOW,
        regions=load_regions(ROOT / "airports.json"),
        airports=airports,
        confirmed=[],
        status=status or {},
        ec=ec,
        gf=gf,
        tf=tf,
        hk=hk,
        cw=cw,
        sm=sm,
        nw=nw,
        om=om,
        **kw,
    )


def test_openmeteo_three_votes_in_output(airports):
    """ICON 陣風 20 節（低）、JMA 平均風 15 × 1.4 ＝ 21（估算，低）、WN2 4 個成員 20／40／10／36 節
    × 1.4 → 28／56／14／50.4，2 個 ≥ 48 → 0.5 投高；中位數 28 → 39.2。新千歲第二格的 IFS、GFS、
    AIFS、AIGFS 沒有資料（fixture 沒涵蓋），風的分母是 IFS 系集＋三票＝4。"""
    out = _assemble(airports, sample_openmeteo(airports))
    s = _airport(out, "RJCC")["slots"][1]
    by = {e["id"]: e for e in s["model"]["models"]}
    icon, jm, wn2 = by["icon"], by["jma"], by["wn2-ens"]
    assert (icon["gustKt"], icon["windKt"], icon["gustEstimated"], icon["gustFactor"]) == (
        20.0,
        15.0,
        False,
        None,
    )
    assert (icon["rain6hMm"], icon["ptype"], icon["run"]) == (3.0, "rain", "2026-10-18T00:00:00Z")
    assert icon["levels"] == {"wind": "low", "rain": "low", "snow": "low", "fog": None}
    assert jm["levels"]["wind"] == "low"
    assert (jm["windKt"], jm["gustKt"], jm["gustEstimated"], jm["gustFactorBasis"]) == (
        15.0,
        21.0,
        True,
        "default",
    )
    assert (jm["ptype"], jm["levels"]["snow"]) == ("none", "low")
    assert (wn2["windKt"], wn2["gustKt"], wn2["p49Kt"], wn2["gustEstimated"]) == (
        28.0,
        39.2,
        0.5,
        True,
    )
    assert wn2["levels"] == {"wind": "high", "rain": None, "snow": None, "fog": None}
    assert all(e["p49Kt"] is None for e in s["model"]["models"] if e["id"] != "wn2-ens")
    v = s["model"]["vote"]
    assert (v["total"], v["high"], v["medium"], v["low"]) == (4, 1, 0, 3)
    # 高 1 × 2 < 4；中那一輪兩個系集不算，ICON、JMA 都低 → 低
    assert v["level"] == s["model"]["level"] == "low"
    assert out["runs"]["wn2-ens"] is None and wn2["run"] is None
    assert [m["voting"] for m in out["models"]] == [True] * 8 + [False] * 3  # HD33b


def test_openmeteo_failure_drops_three_votes(airports):
    """Open-Meteo 失敗：三筆全 null、不算分母，其他照 5 票算；整報照出。"""
    status = {"openmeteo": {"ok": False, "error": "timeout", "seconds": 90.0}}
    out = _assemble(airports, None, status)
    with_om = _assemble(airports, sample_openmeteo(airports))
    assert out["sources"]["openmeteo"] == {"ok": False, "error": "timeout", "seconds": 90.0}
    assert (out["runs"]["icon"], out["runs"]["jma"], out["runs"]["wn2-ens"]) == (None, None, None)
    for a, b in zip(out["airports"], with_om["airports"], strict=True):
        for s, t in zip(a["slots"], b["slots"], strict=True):
            es = s["model"]["models"]
            assert all(e["level"] is None and e["gustKt"] is None for e in es[5:])
            assert s["model"]["vote"]["total"] <= 5
            # 前五筆和有 Open-Meteo 時一模一樣
            assert es[:5] == t["model"]["models"][:5]


def test_openmeteo_not_reused(workspace, monkeypatch, airports):
    """Open-Meteo 失敗不沿用：上一份有 ICON、WN2 的數字，這一報那三筆照樣是 null、沒有
    `reusedFrom`。ECMWF 沿用時（`_rescore` 重組 `models[]`）也不會把舊的抄回來。"""
    _, gf, *_ = sample_inputs(airports)
    prev = _prev(
        "2026-10-18T02:10:00Z",
        {
            "ecmwf": "2026-10-18T00:00:00Z",
            "ecmwfEns": None,
            "gfs": None,
            "icon": "2026-10-18T00:00:00Z",
        },
        ec={"hresGustKt": 50.0, "crosswindKt": 12.5},
    )
    prev["sources"] = {"ecmwf": {"ok": True}, "openmeteo": {"ok": True}}
    prev["airports"][0]["slots"][0]["model"]["models"] = [
        _entry("icon", "2026-10-18T00:00:00Z", gustKt=60.0),
        {**_entry("wn2-ens", None, gustKt=55.0), "p49Kt": 0.9, "windKt": 39.0},
    ]
    _write_hist(workspace, prev, ok={"ecmwf": True, "openmeteo": True})
    _write_prev(workspace, prev)
    _fail_all_but(monkeypatch, gfs=lambda *a, **k: gf)
    assert build.main([]) == 0
    out = json.loads((workspace / "public" / "latest.json").read_text("utf-8"))
    assert out["sources"]["ecmwf"]["reusedFrom"] == "2026-10-18T02:10:00Z"
    src = out["sources"]["openmeteo"]
    assert src["ok"] is False and "reusedFrom" not in src
    assert out["runs"]["icon"] is None
    by = {e["id"]: e for e in _airport(out, "VHHH")["slots"][0]["model"]["models"]}
    assert by["ifs"]["gustKt"] == 50.0  # ECMWF 照沿用
    for i in ("icon", "jma", "wn2-ens"):
        assert by[i]["gustKt"] is None and by[i]["level"] is None and by[i]["p49Kt"] is None


def test_rescore_keeps_this_runs_openmeteo_entries(airports):
    """別的模式沿用時 `_rescore` 重組 `models[]`：Open-Meteo 三筆用這一報自己的數字（WN2 的成員
    比例、估算陣風照舊），投票照算。"""
    out = _assemble(airports, sample_openmeteo(airports))
    s = _airport(out, "RJCC")["slots"][1]
    before = [dict(e) for e in s["model"]["models"]]
    build._rescore(s, Thresholds(), build.model_runs(out["runs"]), DEFAULT_GUST_FACTOR)
    after = s["model"]["models"]
    assert after[5:] == before[5:]
    assert s["model"]["vote"]["total"] == 4


# ---- HD33b：Open-Meteo 的三個旁觀模式（UKMO 是 CC BY-SA 4.0，不放） ----

OBSERVERS = ("gem", "arpege", "cma")


def with_observers(om, airports, gust=80.0, wind=50.0, rain=20.0, vis=None):
    """`sample_openmeteo` 再加三個旁觀模式（每小時陣風 80 節、雨 20 mm → 每格風、雨都是高）。"""
    t0 = utc(2026, 10, 18, 0)
    hours = [t0 + timedelta(hours=h) for h in range(144)]
    hourly = {
        mid: {
            a.icao: [openmeteo.OmHour(t, wind, 90.0, gust, rain, 0.0, vis, 63) for t in hours]
            for a in airports
        }
        for mid in OBSERVERS
    }
    runs = {mid: utc(2026, 10, 18, 0) for mid in OBSERVERS}
    return replace(om, hourly={**om.hourly, **hourly}, runs={**om.runs, **runs})


def _strip(out, ids=OBSERVERS):
    """拿掉 `models[]` 裡旁觀模式那幾筆，其他（等級、投票、`causes`、`gap`）整格比。"""
    slots = []
    for a in out["airports"]:
        for s in a["slots"]:
            s = json.loads(json.dumps(s))
            s["model"]["models"] = [e for e in s["model"]["models"] if e["id"] not in ids]
            slots.append(s)
    return slots


def test_observers_listed_but_do_not_change_level_or_vote(airports):
    """三個旁觀模式每格都判高，但 `level`、`vote`、`model.level`、`causes`、`gap` 和沒有它們時
    一模一樣；`models[]` 那三筆照寫（數字、`levels`、`level`、`run`），頂層 `models[]` 三筆
    `voting: false`。"""
    base = _assemble(airports, sample_openmeteo(airports))
    out = _assemble(airports, with_observers(sample_openmeteo(airports), airports))
    assert _strip(out) == _strip(base)
    s = _airport(out, "RJCC")["slots"][1]
    by = {e["id"]: e for e in s["model"]["models"]}
    for mid in OBSERVERS:
        e = by[mid]
        assert (e["gustKt"], e["windKt"], e["gustEstimated"], e["gustFactor"]) == (
            80.0,
            50.0,
            False,
            None,
        )
        assert (e["rain6hMm"], e["ptype"], e["p49Kt"]) == (120.0, "rain", None)
        assert e["levels"]["wind"] == e["levels"]["rain"] == e["level"] == "high"
        assert e["run"] == "2026-10-18T00:00:00Z"
    assert s["model"]["vote"]["total"] == 4 and s["model"]["level"] == "low"
    assert [m["id"] for m in out["models"]][8:] == list(OBSERVERS)
    assert all(m["voting"] is False and m["votesOnlyHigh"] is False for m in out["models"][8:])
    assert out["models"][10]["name"] == {
        "zh-TW": "中國模式",
        "zh-HK": "中國模式",
        "zh-CN": "中国模式",
        "en": "CMA GRAPES",
    }
    assert "ukmo" not in out["runs"]  # UKMO 不進 latest.json（ShareAlike）
    assert {m["id"]: m["name"]["en"] for m in out["models"][8:]} == {
        "gem": "Canada GEM",
        "arpege": "Météo-France ARPEGE",
        "cma": "CMA GRAPES",
    }
    assert all(out["runs"][mid] == "2026-10-18T00:00:00Z" for mid in OBSERVERS)


def test_observer_low_visibility_not_fog_hd33b(airports):
    """CMA 能見度 150 公尺、風雨都小：旁觀那筆 `visibilityM` 照存，但 `levels.fog` 是 null、`level`
    還是低（不因霧變中）；整格的等級、投票、`causes` 和沒有旁觀模式時一樣。"""
    om = with_observers(
        sample_openmeteo(airports), airports, gust=10.0, wind=5.0, rain=0.0, vis=150.0
    )
    out = _assemble(airports, om)
    assert _strip(out) == _strip(_assemble(airports, sample_openmeteo(airports)))
    for a in out["airports"]:
        for s in a["slots"]:
            for e in s["model"]["models"]:
                if e["id"] in OBSERVERS:
                    assert e["visibilityM"] == 150
                    assert e["levels"]["fog"] is None and e["level"] == "low"


def test_observers_missing_do_not_break_report(airports):
    """三個旁觀模式都沒資料（例如被 `parse_forecast` 丟掉）：那三筆全 null、整報照出、其他不變。"""
    om = sample_openmeteo(airports)
    om = replace(
        om,
        hourly={**om.hourly, **{mid: {} for mid in OBSERVERS}},
        model_errors=dict.fromkeys(OBSERVERS, "missing"),
    )
    status = {"openmeteo": {"ok": True, "seconds": 2.0, **build._openmeteo_extra(om)}}
    out = _assemble(airports, om, status)
    assert _strip(out) == _strip(_assemble(airports, sample_openmeteo(airports)))
    assert out["sources"]["openmeteo"]["modelError"] == ("gem:missing,arpege:missing,cma:missing")
    for a in out["airports"]:
        for s in a["slots"]:
            for e in s["model"]["models"]:
                if e["id"] in OBSERVERS:
                    assert e["level"] is None and e["gustKt"] is None and e["windKt"] is None
    # 有資料時沒有 `modelError`
    assert "modelError" not in build._openmeteo_extra(sample_openmeteo(airports))


# ---- HD15：WeatherNext 3 ----


def sample_wn3(airports, run, wind=30.0, p90=40.0):
    """每個機場逐時一樣的 p50 平均風（節），起報後 1–130 小時。"""
    return wn3.Wn3Data(
        run,
        {
            a.icao: [
                wn3.Wn3Hour(run + timedelta(hours=h), wind, wind - 1, p90, 90.0, 0.5, 25.0)
                for h in range(1, 131)
            ]
            for a in airports
        },
        "bigquery",
        0,
        estimate_bytes=5_000_000_000,
        bytes_processed=3_000_000_000,
        bytes_billed=3_000_000_000,
    )


class _NoTfDownloads(build.tracks.Downloads):
    def tf(self, stream, run):
        raise build.tracks.TracksError("測試不連網", "tf_failed")


def test_wn3_report_only_not_in_latest(workspace, monkeypatch, airports):
    """`report-only`（HD15b 前的預設）：5 天前那一報（10/13 06Z，CC BY 4.0）的起報時間在事件
    期間 → 抓那一報、寫事件檔；`latest.json` 沒有 WN3（頂層 `models`、`runs`、每格 `models[]`
    都沒有），只有 `sources.wn3`。"""
    asked = []
    run = utc(2026, 10, 13, 6)

    def fetch(aps, r, start, end, **k):
        asked.append((r, start, end, k))
        return sample_wn3(aps, r)

    monkeypatch.setattr(build, "wn3_mode", lambda: "report-only")
    _fail_all_but(monkeypatch)
    monkeypatch.setattr(build.wn3, "fetch", fetch)
    monkeypatch.setattr(build.tracks, "build_tracks", lambda *a, **k: build.tracks.TracksResult())
    monkeypatch.setattr(build.tracks, "Downloads", _NoTfDownloads)
    _events_json(workspace, "2026-10-13", "2026-10-18")
    assert build.main([]) == 0
    assert asked == [
        (run, run, run + timedelta(hours=120), {"mslp": True, "retry_previous": False})
    ]
    out = json.loads((workspace / "public" / "latest.json").read_text("utf-8"))
    assert "wn3" not in [m["id"] for m in out["models"]] and "wn3" not in out["runs"]
    assert all(
        e["id"] != "wn3" for a in out["airports"] for s in a["slots"] for e in s["model"]["models"]
    )
    src = out["sources"]["wn3"]
    assert isinstance(src.pop("seconds"), float)
    assert src == {
        "ok": True,
        "run": "2026-10-13T06:00:00Z",
        "via": "bigquery",
        "bytes": 0,
        "estimateBytes": 5_000_000_000,
        "bytesProcessed": 3_000_000_000,
        "bytesBilled": 3_000_000_000,
        "mode": "report-only",
    }
    path = workspace / "data" / "history" / "events" / "29W" / "wn3" / "20261013T0600Z.json"
    doc = json.loads(path.read_text("utf-8"))
    assert doc["license"] == "CC BY 4.0" and len(doc["airports"]) == len(airports)
    assert doc["airports"]["RCTP"][0]["windKt"] == 30.0
    line = next(x for x in _timing_lines(workspace) if x["source"] == "wn3")
    assert (line["ok"], line["mode"], line["via"], line["bytesBilled"]) == (
        True,
        "report-only",
        "bigquery",
        3_000_000_000,
    )


def test_wn3_report_only_outside_event_does_not_run(workspace, monkeypatch, airports):
    monkeypatch.setattr(build, "wn3_mode", lambda: "report-only")
    _fail_all_but(monkeypatch)
    monkeypatch.setattr(build.wn3, "fetch", _boom)
    _events_json(workspace, "2026-10-19", "2026-10-28")  # 10/13 那一報不在期間
    assert build.main([]) == 0
    out = json.loads((workspace / "public" / "latest.json").read_text("utf-8"))
    assert "wn3" not in out["sources"]
    assert "wn3" not in {line["source"] for line in _timing_lines(workspace)}


def _observe(monkeypatch, voting=False):
    models = (*build.MODELS, replace(WN3_MODEL, voting=voting))
    monkeypatch.setattr(build, "wn3_mode", lambda: "observe")
    monkeypatch.setattr(build, "MODELS", models)
    monkeypatch.setattr(build.assess, "MODELS", models)


def test_wn3_observe_listed_not_voting(workspace, monkeypatch, airports):
    """`observe`＋旁觀：最新一報（10/17 18Z，查不到再退一報）進 `models[]` 與 `runs`，頂層
    `voting: false`，不算分母。"""
    _observe(monkeypatch)
    asked = []

    def fetch(aps, r, start, end, **k):
        asked.append((r, start, end, k))
        return sample_wn3(aps, r, wind=40.0)

    _fail_all_but(monkeypatch)
    monkeypatch.setattr(build.wn3, "fetch", fetch)
    assert build.main([]) == 0
    slot0 = utc(2026, 10, 18, 6)
    assert asked == [
        (
            utc(2026, 10, 17, 18),
            slot0,
            slot0 + timedelta(hours=120),
            {"mslp": False, "retry_previous": True},
        )
    ]
    out = json.loads((workspace / "public" / "latest.json").read_text("utf-8"))
    assert out["models"][-1] == {
        "id": "wn3",
        "name": WN3_MODEL.name,
        "voting": False,
        "votesOnlyHigh": False,  # HD24
    }
    assert out["runs"]["wn3"] == "2026-10-17T18:00:00Z"
    assert out["sources"]["wn3"]["mode"] == "observe"
    s = _airport(out, "RCTP")["slots"][0]
    e = s["model"]["models"][-1]
    assert (e["id"], e["run"], e["windKt"], e["gustKt"], e["gustEstimated"]) == (
        "wn3",
        "2026-10-17T18:00:00Z",
        40.0,
        56.0,
        True,
    )
    assert (e["windKtP90"], e["ptype"], e["level"]) == (40.0, None, "high")
    assert s["model"]["vote"]["total"] == 0  # 其他模式都失敗、WN3 旁觀 → 沒有票
    assert s["model"]["level"] is None


def test_wn3_not_approved_is_ok_false(workspace, monkeypatch, airports):
    """核准前每報 `http_403`：`sources.wn3.ok: false`、整報照出、那筆全 null。"""
    _observe(monkeypatch)
    _, gf, *_ = sample_inputs(airports)

    def denied(*a, **k):
        raise wn3.Wn3Error("Access Denied", "http_403")

    _fail_all_but(monkeypatch, gfs=lambda *a, **k: gf)
    monkeypatch.setattr(build.wn3, "fetch", denied)
    assert build.main([]) == 0
    out = json.loads((workspace / "public" / "latest.json").read_text("utf-8"))
    src = out["sources"]["wn3"]
    assert (src["ok"], src["error"], src["mode"]) == (False, "http_403", "observe")
    assert out["runs"]["wn3"] is None and out["sources"]["gfs"]["ok"] is True
    e = _airport(out, "RCTP")["slots"][0]["model"]["models"][-1]
    assert e["id"] == "wn3" and e["gustKt"] is None and e["level"] is None
    assert e["windKtP90"] is None


# ---- 排程與跳過（HD25） ----


@pytest.mark.parametrize(
    "t, slot",
    [
        (utc(2026, 10, 21, 0, 30), utc(2026, 10, 20, 20, 25)),  # 01:05 之前是前一天的最後一個
        (utc(2026, 10, 21, 1, 5), utc(2026, 10, 21, 1, 5)),  # 正好排定時間
        (utc(2026, 10, 21, 13, 4), utc(2026, 10, 21, 8, 25)),
        (utc(2026, 10, 20, 17, 53), utc(2026, 10, 20, 13, 5)),  # 實測：13:05 那報 17:53 才觸發
        (utc(2026, 10, 20, 23, 59), utc(2026, 10, 20, 20, 25)),
        (utc(2026, 11, 1, 0, 0), utc(2026, 10, 31, 20, 25)),  # 跨月
    ],
)
def test_slot_of(t, slot):
    assert build.slot_of(t) == slot


def _archive_latest(workspace, generated_at):
    (workspace / "data").mkdir(exist_ok=True)
    doc = {"schema": 1, "generatedAt": generated_at, "airports": []}
    (workspace / "data" / "latest.json").write_text(json.dumps(doc), "utf-8")


def test_already_built(tmp_path):
    slot = utc(2026, 10, 20, 13, 5)
    assert build.already_built(tmp_path, slot) is None  # 沒有上一份 → 照跑
    (tmp_path / "latest.json").write_text("{壞掉", "utf-8")
    assert build.already_built(tmp_path, slot) is None
    (tmp_path / "latest.json").write_text('{"generatedAt": null}', "utf-8")
    assert build.already_built(tmp_path, slot) is None
    for t, want in (
        ("2026-10-20T13:04:00Z", None),
        ("2026-10-20T13:05:00Z", "2026-10-20T13:05:00Z"),
        ("2026-10-20T13:40:00Z", "2026-10-20T13:40:00Z"),
    ):
        (tmp_path / "latest.json").write_text(json.dumps({"generatedAt": t}), "utf-8")
        assert build.already_built(tmp_path, slot) == want


@pytest.mark.parametrize("trigger", ["schedule", "cloudflare"])
def test_skip_when_slot_already_built(workspace, monkeypatch, capsys, trigger):
    """Cloudflare 13:05 那報 13:06 出過，GitHub 的排程 17:53 才到 → 跳過：不產生、不發布，
    timing 只有一行 skip。"""
    _archive_latest(workspace, "2026-10-20T13:06:00Z")
    monkeypatch.setattr(build, "utcnow", lambda: utc(2026, 10, 20, 17, 53, 40))
    monkeypatch.setenv("JOB_STARTED_AT", "2026-10-20T17:52:30Z")
    monkeypatch.setattr(build, "run", lambda **kw: pytest.fail("不該跑"))
    assert build.main(["--trigger", trigger]) == 0
    assert "這個時段 13:05Z 已經在 2026-10-20T13:06:00Z 出過，跳過" in capsys.readouterr().out
    assert not (workspace / "public").exists()
    assert _timing_lines(workspace) == [
        {
            "run": "2026-10-20T17:53:00Z",
            "source": "skip",
            "ok": True,
            "seconds": 0,
            "trigger": trigger,
            "slot": "2026-10-20T13:05:00Z",
            "startedAt": "2026-10-20T17:52:30Z",
            "delayMinutes": 287.5,
            "generatedAt": "2026-10-20T13:06:00Z",
        }
    ]


def _crash(calls):
    def run(**kw):
        calls.append(kw["now"])
        raise RuntimeError("測試只看有沒有跑")

    return run


def test_cloudflare_runs_when_slot_not_built(workspace, monkeypatch):
    _archive_latest(workspace, "2026-10-20T08:26:00Z")  # 上一個時段的
    monkeypatch.setattr(build, "utcnow", lambda: utc(2026, 10, 20, 13, 6, 20))
    monkeypatch.setenv("JOB_STARTED_AT", "2026-10-20T13:05:41Z")
    calls = []
    monkeypatch.setattr(build, "run", _crash(calls))
    assert build.main(["--trigger", "cloudflare"]) == 1  # 跑了（假的 run 失敗、改發布上一份）
    assert calls == [utc(2026, 10, 20, 13, 6)]
    start = _timing_lines(workspace)[0]
    assert {k: start[k] for k in ("source", "trigger", "slot", "startedAt", "delayMinutes")} == {
        "source": "start",
        "trigger": "cloudflare",
        "slot": "2026-10-20T13:05:00Z",
        "startedAt": "2026-10-20T13:05:41Z",
        "delayMinutes": 0.7,
    }


def test_manual_always_runs(workspace, monkeypatch):
    _archive_latest(workspace, "2026-10-20T13:06:00Z")
    monkeypatch.setattr(build, "utcnow", lambda: utc(2026, 10, 20, 13, 30))
    calls = []
    monkeypatch.setattr(build, "run", _crash(calls))
    assert build.main([]) == 1
    assert build.main(["--trigger", "manual"]) == 1
    assert len(calls) == 2
    lines = [r for r in _timing_lines(workspace) if r["source"] == "start"]
    assert [(r["trigger"], r["slot"], r["delayMinutes"]) for r in lines] == [
        ("manual", None, None)
    ] * 2


def test_schedule_runs_without_previous(workspace, monkeypatch):
    """讀不到上一份 latest.json → 照跑（寧可多跑）。"""
    monkeypatch.setattr(build, "utcnow", lambda: utc(2026, 10, 20, 13, 30))
    calls = []
    monkeypatch.setattr(build, "run", _crash(calls))
    monkeypatch.setattr(build, "previous_latest", lambda archive, url: None)
    assert build.main(["--trigger", "schedule"]) == 2
    assert len(calls) == 1


def test_build_yml_trigger_and_slots():
    """build.yml 的 cron 和 `SLOTS` 一致；`--trigger` 由 workflow 傳進來。"""
    yml = (ROOT / ".github" / "workflows" / "build.yml").read_text("utf-8")
    crons = re.findall(r'- cron: "(\d+) (\d+) \* \* \*"', yml)
    assert sorted((int(h), int(m)) for m, h in crons) == sorted(build.SLOTS)
    assert '--trigger "$TRIGGER"' in yml
