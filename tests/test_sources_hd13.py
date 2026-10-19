"""金門、馬祖的霧（HD13）：氣象署濃霧特報、局屬站觀測（`O-A0003-001`）當 METAR 用。"""

from __future__ import annotations

import pytest
from conftest import load_json, utc

from hongthai.sources import cwa

NOW = utc(2026, 10, 20, 2)  # 台灣 10:00
OBS_NOW = utc(2026, 10, 18, 8, 10)  # 觀測 fixture 是台灣 16:00（08:00Z）
STATIONS = ("467110", "467990")


# ---- 濃霧特報 ----


def test_dense_fog_only_airports_in_area(airports):
    hz = cwa.parse_hazards(load_json("cwa_w-c0033-001_dense_fog.json"), NOW)
    by = {a.icao: a for a in airports}
    rcbs = by["RCBS"]
    (w,) = cwa.dense_fog_for_airport(hz, rcbs.cwa_areas, rcbs.name)
    assert (w.kind, w.level, w.detail, w.issued_at) == (
        "cwa_dense_fog",
        "medium",
        "濃霧",
        "2026-10-18T07:00:00Z",  # 台灣時間 15:00
    )
    assert w.text == {
        "zh-TW": "中央氣象署濃霧特報，金門在特報範圍",
        "zh-HK": "中央氣象署濃霧特報，金門在特報範圍",
        "zh-CN": "中央气象署浓雾特报，金门在特报范围",
        "en": "CWA dense fog advisory; Kinmen is in the advisory area",
    }
    # 濃霧不是豪雨；真實回應裡其他縣市的陸上強風已經結束
    assert cwa.heavy_rain_for_airport(hz, rcbs.cwa_areas, rcbs.name) == []
    for icao in ("RCTP", "RCSS", "RCKH", "RCFG", "RCMQ"):
        a = by[icao]
        assert cwa.dense_fog_for_airport(hz, a.cwa_areas, a.name) == []


def test_dense_fog_one_per_airport(airports):
    # HD8 的 fixture 金門縣有大豪雨＋濃霧；同一縣市重複兩則濃霧也只出一則
    hz = cwa.parse_hazards(load_json("cwa_w-c0033-001_heavy_rain.json"), NOW)
    hz = hz + [cwa.CwaHazard("金門縣", "濃霧", None, None)]
    rcbs = {a.icao: a for a in airports}["RCBS"]
    assert [w.kind for w in cwa.dense_fog_for_airport(hz, rcbs.cwa_areas, rcbs.name)] == [
        "cwa_dense_fog"
    ]


# ---- 局屬站觀測 ----


def test_parse_obs_kinmen_fog():
    obs = cwa.parse_obs(load_json("cwa_o-a0003-001_obs.json"), STATIONS)
    assert set(obs) == set(STATIONS)  # 臺北 466920 沒要，濾掉
    m = obs["467110"]
    assert m.observed == utc(2026, 10, 18, 8)
    assert (m.wdir, m.wind_kt, m.gust_kt) == (90, 2.9, 6.2)  # 1.5、3.2 m/s → 節
    assert (m.vis_m, m.wx, m.ceiling_ft, m.source) == (300, ("FG",), None, "cwa")
    assert m.raw == "CWA 467110 2026-10-18T08:00Z 能見度 0.3 km 陰有霧 風 090° 1.5 m/s 陣風 3.2 m/s"


def test_parse_obs_missing_values():
    m = cwa.parse_obs(load_json("cwa_o-a0003-001_obs.json"), STATIONS)["467990"]
    # 能見度 -99、風速 X → None；風向 990（不定）→ None；陣風是 13 小時前的 → 不算
    assert (m.vis_m, m.wind_kt, m.wdir, m.gust_kt, m.wx) == (None, None, None, None, ())
    assert m.raw == "CWA 467990 2026-10-18T08:00Z 多雲"
    assert m.observed == utc(2026, 10, 18, 8)


def test_parse_obs_all_stations_when_not_filtered():
    obs = cwa.parse_obs(load_json("cwa_o-a0003-001_obs.json"))
    assert obs["466920"].vis_m == 9999 and obs["466920"].wx == ()


def test_parse_obs_bad_format():
    with pytest.raises(cwa.CwaError) as e:
        cwa.parse_obs({"records": {}})
    assert e.value.code == "bad_format"


@pytest.mark.parametrize(
    ("desc", "m"),
    [
        (">30", 9999),
        ("30", 9999),
        ("12.5", 9999),
        ("0.5", 500),
        ("0.38", 400),  # 四捨五入到 50 公尺
        ("<1", 950),  # 「以下」記少 50 公尺，霧至少算中
        ("2-5", 2000),  # 區間取下限
        ("-99", None),
        ("X", None),
        ("", None),
        (None, None),
        (-99, None),
        (0.8, 800),
    ],
)
def test_cwa_vis_m(desc, m):
    assert cwa.cwa_vis_m(desc) == m


@pytest.mark.parametrize(
    ("weather", "wx"),
    [
        ("陰有霧", ("FG",)),
        ("多雲有靄", ("BR",)),
        ("晴有霾", ("HZ",)),
        ("陰有雨", ("RA",)),
        ("陰有陣雨", ("SHRA",)),
        ("陰有雷雨", ("TSRA",)),
        ("陰大雷雨", ("+TSRA",)),
        ("陰大雷雹", ("+TSGR",)),
        ("陰有雨雪", ("RASN",)),
        ("陰陣雨雪", ("SHRASN",)),
        ("陰有大雪", ("+SN",)),
        ("陰有冰珠", ("PL",)),
        ("陰有雷", ("TS",)),
        ("多雲有閃電", ("閃電",)),  # 對不到的放原文
        ("晴", ()),
        ("多雲-", ()),
        ("-99", ()),
        (None, ()),
    ],
)
def test_cwa_wx(weather, wx):
    assert cwa.cwa_wx(weather) == wx


class _Resp:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


def test_fetch_obs_with_station_ids(monkeypatch):
    typhoon = load_json("cwa_w-c0034-001_cancel.json")
    hazards = load_json("cwa_w-c0033-001_dense_fog.json")
    obs = load_json("cwa_o-a0003-001_obs.json")
    calls = []

    def fake_get(url, **kw):
        calls.append((url, kw.get("params"), kw["headers"]))
        return _Resp({cwa.URL: typhoon, cwa.HAZARD_URL: hazards, cwa.OBS_URL: obs}[url])

    monkeypatch.setattr(cwa, "http_get", fake_get)
    data = cwa.fetch("key", OBS_NOW, STATIONS)
    assert [u for u, _, _ in calls] == [cwa.URL, cwa.HAZARD_URL, cwa.OBS_URL]
    assert calls[2][1] == {"StationId": "467110,467990"}
    assert all(h == {"Authorization": "key"} for _, _, h in calls)
    assert data.obs_raw is obs and data.obs_error is None
    assert set(data.obs) == set(STATIONS)


def test_fetch_without_stations_skips_obs(monkeypatch):
    typhoon = load_json("cwa_w-c0034-001_cancel.json")
    urls = []

    def fake_get(url, **kw):
        urls.append(url)
        return _Resp(typhoon if url == cwa.URL else load_json("cwa_w-c0033-001_dense_fog.json"))

    monkeypatch.setattr(cwa, "http_get", fake_get)
    data = cwa.fetch("key", OBS_NOW)
    assert urls == [cwa.URL, cwa.HAZARD_URL]
    assert (data.obs, data.obs_raw, data.obs_error) == ({}, None, None)


def test_fetch_obs_failure_keeps_typhoon_and_hazards(monkeypatch):
    typhoon = load_json("cwa_w-c0034-001_land.json")
    hazards = load_json("cwa_w-c0033-001_dense_fog.json")

    def fake_get(url, **kw):
        if url == cwa.OBS_URL:
            raise cwa.CwaError("HTTP 500", "http_500")
        return _Resp(typhoon if url == cwa.URL else hazards)

    monkeypatch.setattr(cwa, "http_get", fake_get)
    data = cwa.fetch("key", NOW, STATIONS)
    assert data.bulletins == cwa.parse_bulletins(typhoon, NOW)
    assert data.hazards == cwa.parse_hazards(hazards, NOW) and data.hazards_error is None
    assert (data.obs, data.obs_raw, data.obs_error) == ({}, None, "http_500")


def test_fetch_obs_not_success(monkeypatch):
    def fake_get(url, **kw):
        if url == cwa.OBS_URL:
            return _Resp({"success": "false"})
        return _Resp(load_json("cwa_w-c0034-001_cancel.json") if url == cwa.URL else {})

    monkeypatch.setattr(cwa, "http_get", fake_get)
    data = cwa.fetch("key", NOW, STATIONS)
    assert data.obs_error == "api_error"
