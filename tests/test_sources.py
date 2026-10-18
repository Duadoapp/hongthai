"""各來源的解析，用 `fixtures/` 裡的小樣本（不連網）。"""

from __future__ import annotations

import gzip
import json
from datetime import timedelta

import pytest
from conftest import FIXTURES, load_json, utc

from hongthai.sources import cwa, ecmwf, flights, gfs, hko, taf

# ---- TAF／METAR ----


def test_parse_tafs_real_sample():
    tafs = taf.parse_tafs(load_json("taf.json"))
    assert set(tafs) == {"RCTP", "VHHH"}
    t = tafs["RCTP"]
    assert t.issued == utc(2026, 10, 17, 23)
    assert t.valid_from == utc(2026, 10, 18, 0)
    assert t.raw.startswith("TAF RCTP")
    assert [p.kind for p in t.periods] == ["main", "main", "main", "tempo", "main"]
    assert t.periods[0].wind_kt == 5 and t.periods[0].gust_kt is None
    assert t.periods[2].wdir == 90


def test_period_kind_prob_and_tempo():
    assert taf.period_kind({"fcstChange": "TEMPO", "probability": None}) == "tempo"
    assert taf.period_kind({"fcstChange": "PROB", "probability": 30}) == "prob30"
    assert taf.period_kind({"fcstChange": "TEMPO", "probability": 40}) == "prob40"
    assert taf.period_kind({"fcstChange": "BECMG"}) == "main"
    assert taf.period_kind({"fcstChange": None}) == "main"


def test_parse_metars_real_sample():
    m = taf.parse_metars(load_json("metar.json"))
    assert m["VHHH"].wind_kt == 11
    assert m["VHHH"].wdir == 90
    assert m["VHHH"].gust_kt is None
    assert m["RCTP"].observed.tzinfo is not None
    assert m["RCTP"].raw.startswith("METAR RCTP")


def test_metar_variable_direction():
    m = taf.parse_metars([{"icaoId": "X", "obsTime": 0, "wdir": "VRB", "wspd": 3, "rawOb": ""}])
    assert m["X"].wdir is None


# ---- 天文台 ----


def _hko(kind):
    return {lang: load_json(f"hko_warnsum_{kind}_{lang}.json") for lang in ("tc", "en", "sc")}


def test_hko_no_signal_real_sample():
    assert hko.parse_signal(_hko("fire")) is None


def test_hko_signal8():
    s = hko.parse_signal(_hko("tc8ne"))
    assert s.code == "TC8NE"
    assert s.level == "high"
    assert s.text["zh-TW"] == s.text["zh-HK"] == "八號東北烈風或暴風信號"
    assert s.text["zh-CN"] == "八号东北烈风或暴风信号"
    assert s.text["en"] == "Gale or Storm Signal No. 8 Northeast"
    assert s.issued_at == "2026-10-20T01:40:00Z"


@pytest.mark.parametrize(
    "code,level",
    [("TC1", "low"), ("TC3", "medium"), ("TC8SW", "high"), ("TC9", "high"), ("TC10", "high")],
)
def test_hko_signal_levels(code, level):
    assert hko.signal_level(code) == level


def test_hko_cancelled_signal_ignored():
    data = _hko("tc8ne")
    for d in data.values():
        d["WTCSGNL"]["actionCode"] = "CANCEL"
    assert hko.parse_signal(data) is None


# ---- 氣象署 ----


def test_cwa_cancel_real_sample_no_warning():
    assert cwa.parse_warnings(load_json("cwa_w-c0034-001_cancel.json"), utc(2026, 8, 28, 7)) == []


def test_cwa_land_warning_taoyuan_in_zone():
    ws = cwa.parse_warnings(load_json("cwa_w-c0034-001_land.json"), utc(2026, 8, 27, 5))
    assert len(ws) == 1
    w = ws[0]
    assert (w.kind, w.level, w.in_zone) == ("typhoon_land", "high", True)
    assert "沙德爾" in w.text["zh-TW"] and "桃園在警戒區" in w.text["zh-TW"]
    assert "Saudel" in w.text["en"]
    assert set(w.text) == {"zh-TW", "zh-HK", "zh-CN", "en"}
    assert w.issued_at == "2026-08-27T03:30:00Z"
    assert "桃園市" in w.detail


def test_cwa_sea_warning_medium():
    ws = cwa.parse_warnings(load_json("cwa_w-c0034-001_sea.json"), utc(2026, 8, 27, 5))
    assert [(w.kind, w.level, w.in_zone) for w in ws] == [("typhoon_sea", "medium", False)]


def test_cwa_north_text_counts_but_not_north_sea():
    info = {"area": [{"areaDesc": "臺灣北部海面"}], "description": {"section": []}}
    assert cwa.taoyuan_in_zone(info) is False
    info["description"]["section"] = [{"title": "警戒區域及事項", "value": "北部地區應嚴加戒備"}]
    assert cwa.taoyuan_in_zone(info) is True


def test_cwa_stale_warning_ignored():
    data = load_json("cwa_w-c0034-001_land.json")
    assert cwa.parse_warnings(data, utc(2026, 8, 28, 0)) == []


def test_cwa_no_key():
    with pytest.raises(cwa.CwaError) as e:
        cwa.fetch(None, utc(2026, 10, 18))
    assert e.value.code == "no_api_key"


# ---- GRIB：ECMWF、GFS ----


def test_ecmwf_hres_parse(airports):
    run, pts = ecmwf.parse_hres(FIXTURES / "ecmwf_oper_subregion.grib2", airports)
    assert run == utc(2026, 10, 17, 18)
    g = pts["VHHH"]
    assert [x.end - run for x in g] == [timedelta(hours=h) for h in (87, 90, 93, 96)]
    # 0–90 小時的 10fg 是前 1 小時，93 以後的 10fg3 是前 3 小時
    assert g[0].end - g[0].start == timedelta(hours=1)
    assert g[2].end - g[2].start == timedelta(hours=3)
    assert g[2].gust_ms == pytest.approx(9.08, abs=0.01)


def test_ecmwf_ens_parse(airports):
    run, pts = ecmwf.parse_ens(FIXTURES / "ecmwf_ep_subregion.grib2", airports)
    assert run == utc(2026, 10, 17, 12)
    w = pts["VHHH"][0]
    assert (w.start - run, w.end - run) == (timedelta(hours=0), timedelta(hours=24))
    assert (w.p10, w.p15, w.p25) == (0.86, 0.07, 0.0)


def test_ecmwf_step_helpers():
    assert ecmwf.hres_steps(6, 144)[:2] == [9, 12]
    assert ecmwf.hres_steps(6, 144)[-1] == 126
    assert ecmwf.hres_steps(36, 240)[-4:] == [141, 144, 150, 156]  # 144 以後只有每 6 小時
    assert ecmwf.hres_steps(36, 144)[-1] == 144
    assert ecmwf.ens_windows(0)[:2] == ["0-24", "12-36"]
    assert ecmwf.ens_windows(18)[0] == "0-24"


def test_gfs_parse(airports):
    from hongthai.grib import read_points

    pts = read_points(
        FIXTURES / "gfs_subregion_f006.grb2", {a.icao: (a.lat, a.lon) for a in airports}
    )
    s = pts["RCTP"]["gust"]
    assert s.run == utc(2026, 10, 18, 0)
    assert s.steps == [6.0]
    assert s.values[0] == pytest.approx(2.8, abs=0.01)


def test_gfs_subregion(airports):
    r = gfs.subregion(airports)
    assert float(r["toplat"]) == pytest.approx(26.08)
    assert float(r["leftlon"]) == pytest.approx(112.92)
    assert gfs.file_name(utc(2026, 10, 18, 6), 12) == "gfs.t06z.pgrb2.0p25.f012"
    assert gfs.run_dir(utc(2026, 10, 18, 6)) == "/gfs.20261018/06/atmos"


# ---- 航班 ----


def test_tpe_parse_big5():
    rows = flights.parse_tpe((FIXTURES / "tpe_flights_big5.txt").read_bytes())
    assert len(rows) == 5
    assert rows[0]["airlineName"] == "真航空"
    assert rows[0]["airportZh"] == "仁川"
    assert rows[0]["status"].endswith("ARRIVED")


def test_flight_snapshot_path(tmp_path):
    hk = load_json("hkg_arrival.json")
    now = utc(2026, 10, 18, 7, 25)
    p = flights.write_snapshot(tmp_path, "VHHH", now, {"arrival": hk})
    assert p == tmp_path / "flights" / "2026-10-18" / "VHHH-0725.json.gz"
    body = json.loads(gzip.decompress(p.read_bytes()))
    assert body["fetchedAt"] == "2026-10-18T07:25:00Z"
    assert body["arrival"][0]["list"][0]["flight"]


def test_cwa_tls_adapter_keeps_verification_but_not_strict():
    import ssl

    from hongthai.sources import NonStrictTLSAdapter

    ctx = NonStrictTLSAdapter._context()
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname
    assert not ctx.verify_flags & ssl.VERIFY_X509_STRICT
