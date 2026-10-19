"""第五階段天氣種類（HD8）的來源：GFS 降水與能見度、ECMWF 降水、天文台暴雨、氣象署豪雨特報。"""

from __future__ import annotations

import copy
from datetime import timedelta

import pytest
from conftest import load_json, utc

from hongthai.grib import PointSeries
from hongthai.sources import cwa, ecmwf, gfs, hko

# 2026-10-19 00Z 的 `.idx` 真實片段（f012、f006、f000）
IDX_F012 = """\
10:4268486:d=2026101900:VIS:surface:12 hour fcst:
14:5948569:d=2026101900:GUST:surface:12 hour fcst:
15:6560177:d=2026101900:HGT:0.01 mb:12 hour fcst:
588:422538109:d=2026101900:UGRD:10 m above ground:12 hour fcst:
589:423505789:d=2026101900:VGRD:10 m above ground:12 hour fcst:
590:424452587:d=2026101900:ICEG:10 m above mean sea level:12 hour fcst:
595:425804532:d=2026101900:PRATE:surface:6-12 hour ave fcst:
596:426485744:d=2026101900:APCP:surface:6-12 hour acc fcst:
597:426846480:d=2026101900:APCP:surface:0-12 hour acc fcst:
601:428183714:d=2026101900:CSNOW:surface:12 hour fcst:
602:428218755:d=2026101900:CICEP:surface:12 hour fcst:
603:428218976:d=2026101900:CFRZR:surface:12 hour fcst:
604:428220072:d=2026101900:CRAIN:surface:12 hour fcst:
605:428327274:d=2026101900:CSNOW:surface:6-12 hour ave fcst:
606:428355627:d=2026101900:CICEP:surface:6-12 hour ave fcst:
607:428355916:d=2026101900:CFRZR:surface:6-12 hour ave fcst:
608:428357365:d=2026101900:CRAIN:surface:6-12 hour ave fcst:
609:428444106:d=2026101900:LFTX:surface:12 hour fcst:
"""


def test_gfs_idx_picks_6h_bucket_and_instant_categories():
    ranges = gfs.byte_ranges(IDX_F012, gfs.IDX_FIELDS, 12, gfs.fields_for(12))
    assert ranges == [
        (4268486, 6560176),  # VIS＋GUST（這段片段裡兩筆相鄰，併成一段）
        (422538109, 424452586),  # UGRD＋VGRD
        (426485744, 426846479),  # APCP 6-12（不是 0-12）
        (428183714, 428327273),  # CSNOW／CICEP／CFRZR／CRAIN 瞬時（相鄰併成一段）
    ]


def test_gfs_idx_f006_two_identical_apcp_takes_first():
    idx = IDX_F012.replace("12 hour fcst", "6 hour fcst").replace("6-12 hour", "0-6 hour")
    idx = idx.replace("0-0-6 hour", "0-6 hour").replace("0-12 hour acc", "0-6 hour acc")
    ranges = gfs.byte_ranges(idx, gfs.IDX_FIELDS, 6, gfs.fields_for(6))
    assert (426485744, 426846479) in ranges


def test_gfs_idx_f000_has_no_apcp_and_missing_optional_only_logs(caplog):
    assert ("APCP", "surface", "acc6") not in gfs.fields_for(0)
    # 少了 HD8 的欄位：只 log，陣風照抓
    idx = "\n".join(line for line in IDX_F012.splitlines() if "VIS" not in line)
    ranges = gfs.byte_ranges(idx, gfs.IDX_FIELDS, 12, gfs.fields_for(12))
    assert (5948569, 6560176) in ranges  # GUST
    assert "VIS:surface:inst" in caplog.text
    # 少了陣風還是 bad_idx
    with pytest.raises(gfs.GfsError) as e:
        gfs.byte_ranges(IDX_F012.replace("GUST", "XXXX"), gfs.IDX_FIELDS, 12, gfs.fields_for(12))
    assert e.value.code == "bad_idx"


@pytest.mark.parametrize(
    ("cats", "ptype"),
    [
        ({"crain": 1, "csnow": 1, "cfrzr": 1, "cicep": 0}, "freezing_rain"),
        ({"crain": 1, "csnow": 1, "cfrzr": 0, "cicep": 1}, "ice_pellets"),
        ({"crain": 1, "csnow": 1, "cfrzr": 0, "cicep": 0}, "snow"),
        ({"crain": 1, "csnow": 0, "cfrzr": 0, "cicep": 0}, "rain"),
        ({"crain": 0, "csnow": 0, "cfrzr": 0, "cicep": 0}, "none"),
        ({}, None),
    ],
)
def test_gfs_ptype_from_categories(cats, ptype):
    assert gfs.ptype_from_categories(cats) == ptype


def _series(run, **by_key):
    return {k: PointSeries(run, [s for s, _ in v], [x for _, x in v]) for k, v in by_key.items()}


def test_gfs_parse_file_new_fields(monkeypatch, airports):
    run = utc(2026, 10, 19, 0)
    one = _series(
        run,
        gust=[(12.0, 10.0)],
        tp=[(12.0, 35.5)],
        vis=[(12.0, 650.0)],
        csnow=[(12.0, 1.0)],
        crain=[(12.0, 0.0)],
        cfrzr=[(12.0, 0.0)],
        cicep=[(12.0, 0.0)],
        **{"csnow:avg": [(12.0, 0.5)]},
    )
    monkeypatch.setattr(gfs, "read_points", lambda path, pts: {k: one for k in pts})
    p = gfs.parse_file("x.grib2", airports[:1])[airports[0].icao][0]
    assert p.valid == run + timedelta(hours=12)
    assert (p.rain6h_mm, p.ptype, p.vis_m) == (35.5, "snow", 650.0)


def test_ecmwf_precip_steps_add_first_slot_start():
    steps = ecmwf.hres_steps(12, 144)
    assert ecmwf.precip_steps(steps, 12) == list(range(12, 133, 6))
    assert ecmwf.precip_steps(ecmwf.hres_steps(0, 240), 0)[0] == 6  # tp(0) 當 0，不抓


def test_ecmwf_parse_precip_differences_and_ptype():
    run = utc(2026, 10, 18, 18)
    series = _series(
        run,
        tp=[(12.0, 0.010), (18.0, 0.0425), (24.0, 0.0424)],  # m，累積
        ptype=[(12.0, 1.0), (18.0, 5.0), (24.0, 99.0)],
        **{"2t": [(12.0, 273.15), (18.0, 270.0), (24.0, None)]},
    )
    out = ecmwf.parse_precip(series, run)
    assert [p.valid for p in out] == [run + timedelta(hours=h) for h in (12, 18, 24)]
    assert out[0].rain6h_mm is None  # 前 6 小時沒抓
    assert out[1].rain6h_mm == pytest.approx(32.5)
    assert out[2].rain6h_mm == 0.0  # 微小負值當 0
    assert [p.ptype for p in out] == ["rain", "snow", "other"]
    assert out[0].temp2m_c == pytest.approx(0.0)
    assert out[2].temp2m_c is None
    # 步長 6 的前一個是 0：tp(0) 當 0
    first = ecmwf.parse_precip(_series(run, tp=[(6.0, 0.002)]), run)[0]
    assert first.rain6h_mm == pytest.approx(2.0)


@pytest.mark.parametrize(
    ("code", "name"),
    [(0, "none"), (1, "rain"), (3, "freezing_rain"), (5, "snow"), (6, "wet_snow")]
    + [(7, "rain_snow"), (8, "ice_pellets"), (12, "freezing_drizzle"), (2, "other")],
)
def test_ecmwf_ptype_names(code, name):
    assert ecmwf.ptype_name(float(code)) == name


def test_ecmwf_parse_ens_rain_probabilities(monkeypatch, airports):
    run = utc(2026, 10, 18, 12)
    one = _series(
        run,
        **{
            "10fgg25": [(24.0, 10.0)],
            "tpg25": [(24.0, 40.0)],
            "tpg50": [(24.0, 30.0)],
        },
    )
    monkeypatch.setattr(ecmwf, "read_points", lambda path, pts: {k: one for k in pts})
    _, ens = ecmwf.parse_ens("x.grib2", airports[:1])
    w = ens[airports[0].icao][0]
    assert (w.p25, w.tp25, w.tp50) == (0.1, 0.4, 0.3)


# ---- 天文台暴雨與雷暴 ----


def _warnsum(**entries):
    """`entries` 是 `{鍵: {"code", "type", ...}}`；三語都放一樣的英文以外，名稱照語言給。"""
    names = {
        "WRAIN": {"tc": "暴雨警告信號", "en": "Rainstorm Warning Signal", "sc": "暴雨警告信号"},
        "WTS": {"tc": "雷暴警告", "en": "Thunderstorm Warning", "sc": "雷暴警告"},
    }
    colors = {"WRAINB": {"tc": "黑色", "en": "Black", "sc": "黑色"}}
    out = {}
    for lang in ("tc", "en", "sc"):
        d = {}
        for key, e in entries.items():
            w = {
                "name": names[key][lang],
                "code": e["code"],
                "actionCode": e.get("action", "ISSUE"),
            }
            w["issueTime"] = "2026-10-20T09:40:00+08:00"
            if e["code"] in colors:
                w["type"] = colors[e["code"]][lang]
            d[key] = w
        out[lang] = d
    return out


def test_hko_black_rain_medium_and_thunderstorm_low():
    ws = hko.parse_warnings(_warnsum(WRAIN={"code": "WRAINB"}, WTS={"code": "WTS"}))
    by = {w.kind: w for w in ws}
    black, ts = by["rainstorm_black"], by["thunderstorm"]
    assert (black.code, black.level) == ("WRAINB", "medium")
    assert black.text == {
        "zh-TW": "黑色暴雨警告信號",
        "zh-HK": "黑色暴雨警告信號",
        "zh-CN": "黑色暴雨警告信号",
        "en": "Black Rainstorm Warning Signal",
    }
    assert black.issued_at == "2026-10-20T01:40:00Z"
    assert (ts.code, ts.level, ts.text["en"]) == ("WTS", "low", "Thunderstorm Warning")


def test_hko_red_rain_low_amber_and_cancel_ignored():
    (red,) = hko.parse_warnings(_warnsum(WRAIN={"code": "WRAINR"}))
    assert (red.kind, red.level) == ("rainstorm_red", "low")
    assert red.text["zh-TW"] == "暴雨警告信號"  # 沒有顏色的 type 就用名稱
    assert hko.parse_warnings(_warnsum(WRAIN={"code": "WRAINA"})) == []  # 黃雨不在定案的種類
    assert hko.parse_warnings(_warnsum(WRAIN={"code": "WRAINB", "action": "CANCEL"})) == []


def test_hko_real_samples_have_no_rain_warning():
    tc8 = {lang: load_json(f"hko_warnsum_tc8ne_{lang}.json") for lang in ("tc", "en", "sc")}
    data = copy.deepcopy(tc8)
    assert hko.parse_warnings(data) == []
    assert hko.parse_signal(data).code == "TC8NE"  # 熱帶氣旋信號照舊


# ---- 氣象署豪雨特報 ----

NOW = utc(2026, 10, 20, 2)  # 台灣 10:00
KINMEN = {"zh-TW": "金門", "zh-HK": "金門", "zh-CN": "金门", "en": "Kinmen"}


def test_cwa_parse_hazards():
    hz = cwa.parse_hazards(load_json("cwa_w-c0033-001_heavy_rain.json"), NOW)
    got = [(h.location, h.phenomena, h.start, h.end) for h in hz]
    assert got == [
        ("金門縣", "大豪雨", "2026-10-20T00:00:00Z", "2026-10-20T12:00:00Z"),  # 台灣時間 08–20
        ("金門縣", "濃霧", "2026-10-19T21:00:00Z", "2026-10-20T03:00:00Z"),
        ("連江縣", "豪雨", "2026-10-20T00:00:00Z", "2026-10-20T12:00:00Z"),
        ("高雄市", "超大豪雨", "2026-10-20T00:00:00Z", "2026-10-20T12:00:00Z"),  # hazards 是物件
        # 臺北市那則 10/19 20:00 已經結束，不算
    ]


def test_cwa_heavy_rain_only_torrential_in_area(airports):
    hz = cwa.parse_hazards(load_json("cwa_w-c0033-001_heavy_rain.json"), NOW)
    by = {a.icao: a for a in airports}
    (w,) = cwa.heavy_rain_for_airport(hz, by["RCBS"].cwa_areas, KINMEN)
    assert (w.kind, w.level, w.detail, w.issued_at) == (
        "cwa_heavy_rain",
        "medium",
        "大豪雨",
        "2026-10-20T00:00:00Z",
    )
    assert w.text == {
        "zh-TW": "中央氣象署大豪雨特報，金門在特報範圍",
        "zh-HK": "中央氣象署大豪雨特報，金門在特報範圍",
        "zh-CN": "中央气象署大豪雨特报，金门在特报范围",
        "en": "CWA torrential rain advisory; Kinmen is in the advisory area",
    }
    # 馬祖只有豪雨（不算）；高雄超大豪雨；台北的已經結束；台中沒有
    rcfg = by["RCFG"]
    assert cwa.heavy_rain_for_airport(hz, rcfg.cwa_areas, rcfg.name) == []
    (kh,) = cwa.heavy_rain_for_airport(hz, by["RCKH"].cwa_areas, by["RCKH"].name)
    assert kh.detail == "超大豪雨"
    assert kh.text["en"].startswith("CWA extremely torrential rain advisory")
    for icao in ("RCTP", "RCMQ"):
        assert cwa.heavy_rain_for_airport(hz, by[icao].cwa_areas, by[icao].name) == []


def test_cwa_hazards_bad_format():
    with pytest.raises(cwa.CwaError) as e:
        cwa.parse_hazards({"records": {}}, NOW)
    assert e.value.code == "bad_format"


class _Resp:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


def test_cwa_fetch_hazard_failure_keeps_typhoon(monkeypatch):
    typhoon = load_json("cwa_w-c0034-001_land.json")

    def fake_get(url, **kw):
        if url == cwa.URL:
            return _Resp(typhoon)
        raise cwa.CwaError("HTTP 500", "http_500")

    monkeypatch.setattr(cwa, "http_get", fake_get)
    now = utc(2026, 10, 20, 2)
    data = cwa.fetch("key", now)
    assert data.bulletins == cwa.parse_bulletins(typhoon, now)
    assert (data.hazards, data.hazards_raw, data.hazards_error) == ([], None, "http_500")


def test_cwa_fetch_both(monkeypatch):
    typhoon = load_json("cwa_w-c0034-001_cancel.json")
    hazards = load_json("cwa_w-c0033-001_heavy_rain.json")
    calls = []

    def fake_get(url, **kw):
        calls.append((url, kw["headers"]))
        return _Resp(typhoon if url == cwa.URL else hazards)

    monkeypatch.setattr(cwa, "http_get", fake_get)
    data = cwa.fetch("key", NOW)
    assert [u for u, _ in calls] == [cwa.URL, cwa.HAZARD_URL]
    assert all(h == {"Authorization": "key"} for _, h in calls)
    assert data.hazards_error is None and data.hazards_raw is hazards
    assert len(data.hazards) == 4
