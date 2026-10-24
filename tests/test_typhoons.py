"""HD34：颱風地圖的官方路徑與暴風圈（`sources/typhoon.py`、`typhoons.py`）——只轉載、不計算。"""

from __future__ import annotations

import json
import re
from math import ceil, floor

import pytest
from conftest import ROOT, load_json, utc

from hongthai import typhoons
from hongthai.sources import typhoon
from hongthai.sources.typhoon import Storm, TyphoonData

NOW = utc(2026, 10, 24, 20, 10)
OK = {"cwaTyphoon": {"ok": True}, "jmaTyphoon": {"ok": True}}


def _jma_storms(raw: dict) -> list[Storm]:
    return [
        typhoon.parse_jma(tc, raw[tc]["specifications"], raw[tc]["forecast"])
        for tc in ("TC2637", "TC2636", "TC2638")
    ]


@pytest.fixture
def cwa():
    return TyphoonData(typhoon.parse_cwa(load_json("cwa_typhoon_track.json")), {})


@pytest.fixture
def jma():
    return TyphoonData(_jma_storms(load_json("jma_typhoon.json")), {})


def _snake(obj):
    """手造的 camelCase 氣象署回應 → XML 那種 snake_case、`cwb_`（鍵名寫法不同也要讀得到）。"""
    if isinstance(obj, list):
        return [_snake(v) for v in obj]
    if not isinstance(obj, dict):
        return obj
    out = {}
    for k, v in obj.items():
        k = re.sub(r"(?<=[a-z0-9])([A-Z])", r"_\1", k).lower().replace("cwa", "cwb")
        out[k] = _snake(v)
    return out


# ---- 氣象署 W-C0034-005 ----


def test_parse_cwa(cwa):
    champi, infa = cwa.storms
    assert (champi.source, champi.key, champi.number) == ("cwa", "ty30", "2630")
    assert (champi.name_zh, champi.name_en) == ("薔琵", "Champi")
    assert champi.issued_at == utc(2026, 10, 24, 18)  # 預報的 init_time
    # 過去路徑照定位時間排（原文順序亂的也排好），含目前那一點；座標是「經度,緯度」
    assert champi.past == [
        {"time": "2026-10-24T06:00:00Z", "lat": 26.4, "lon": 123.3},
        {"time": "2026-10-24T12:00:00Z", "lat": 27.4, "lon": 123.2},
        {"time": "2026-10-24T18:00:00Z", "lat": 27.9, "lon": 123.5},
    ]
    assert champi.now == {
        "time": "2026-10-24T18:00:00Z",
        "lat": 27.9,
        "lon": 123.5,
        "radius15": [{"dir": "all", "km": 250}],
        "radius25": [],  # -99＝沒有
    }
    # 預報點：時間＝init_time＋tau（原文兩個欄位相加），依時距排；半徑照原文的公里
    assert [(p["leadHours"], p["time"]) for p in champi.forecast] == [
        (12, "2026-10-25T06:00:00Z"),
        (24, "2026-10-25T18:00:00Z"),
        (36, "2026-10-26T06:00:00Z"),
    ]
    assert champi.forecast[0] == {
        "time": "2026-10-25T06:00:00Z",
        "lat": 29.8,
        "lon": 124.9,
        "radius15": [{"dir": "all", "km": 200}],
        "radius25": [],
        "leadHours": 12,
        "probabilityRadius": {"km": 60},
        "stormWarning": [],
    }
    assert champi.forecast[2]["radius15"] == []
    # 只有一筆定位時不是 list 也讀得到
    assert (infa.number, infa.name_en, infa.now["lon"], len(infa.past)) == (
        "2631",
        "In-Fa",
        165.3,
        1,
    )


def test_parse_cwa_snake_case_keys():
    """JSON 版鍵名沒有文件：XML 的 snake_case、`cwb_` 也讀得到，結果一樣。"""
    camel = typhoon.parse_cwa(load_json("cwa_typhoon_track.json"))
    snake_doc = _snake(load_json("cwa_typhoon_track.json"))
    assert "cwb_typhoon_name" in json.dumps(snake_doc, ensure_ascii=False)
    assert typhoon.parse_cwa(snake_doc) == camel


def test_parse_cwa_lat_lon_fields_and_td():
    doc = {
        "records": {
            "tropicalCyclones": {
                "tropicalCyclone": {
                    "year": "2026",
                    "cwbTdNo": "32",
                    "analysisData": {
                        "fix": {
                            "fixTime": "2026-10-25T08:00:00+08:00",
                            "latitude": "16.0",
                            "longitude": "115.0",
                        }
                    },
                }
            }
        }
    }
    (td,) = typhoon.parse_cwa(doc)
    assert (td.key, td.number, td.name_zh, td.name_en) == ("td32", None, "", "")
    assert (td.now["lat"], td.now["lon"], td.forecast) == (16, 115, [])
    assert td.issued_at == utc(2026, 10, 25)  # 沒有預報就用最後一個定位時間
    assert typhoons.names(td) == dict.fromkeys(("zh-TW", "zh-HK", "zh-CN", "en"), "TD32")


def test_parse_cwa_empty_and_bad():
    assert typhoon.parse_cwa({"success": "true", "records": {}}) == []
    assert typhoon.parse_cwa({"records": {"tropicalCyclones": {}}}) == []
    with pytest.raises(typhoon.TyphoonError) as e:
        typhoon.parse_cwa({"success": "true"})
    assert e.value.code == "bad_format"


def test_fetch_cwa_needs_key():
    with pytest.raises(typhoon.TyphoonError) as e:
        typhoon.fetch_cwa(None)
    assert e.value.code == "no_api_key"


# ---- 日本氣象廳 ----


def test_parse_jma_real_29w():
    """2026-10-25 00:45 JST 實抓的 TC2636（29W 薔琵）。"""
    raw = load_json("jma_typhoon.json")["TC2636"]
    s = typhoon.parse_jma("TC2636", raw["specifications"], raw["forecast"])
    assert (s.source, s.key, s.number, s.name_zh, s.name_en) == (
        "jma",
        "TC2636",
        "2630",
        "",
        "Champi",
    )
    assert s.issued_at == utc(2026, 10, 24, 15, 45)
    assert s.now == {
        "time": "2026-10-24T15:00:00Z",
        "lat": 27.7,
        "lon": 123.5,
        "category": "STS",
        # 強風域照原文的方位、公里與海浬（沒有換算）
        "radius15": [
            {"dir": "E", "area": "東", "km": 650, "nm": 350},
            {"dir": "W", "area": "西", "km": 560, "nm": 300},
        ],
        "radius25": [],
        "jmaShapes": {"galeWarningArea": {"center": [27.7, 123.97], "radius": 601900}},
    }
    assert [(p["leadHours"], p["category"], p["probabilityRadius"]) for p in s.forecast] == [
        (12, "TS", {"km": 65, "nm": 35}),
        (24, "TS", {"km": 95, "nm": 50}),
        (45, "LOW", {"km": 210, "nm": 115}),
    ]
    assert s.forecast[0]["time"] == "2026-10-25T03:00:00Z"
    assert s.forecast[0]["jmaShapes"]["probabilityCircle"]["radius"] == 64820
    # 過去路徑：forecast.json 的 track 原樣（沒有時間），最後一點就是目前位置
    assert len(s.past) == 115
    assert s.past[0] == {"time": None, "lat": 9.5, "lon": 160.0, "stage": "preTyphoon"}
    assert s.past[-1] == {"time": None, "lat": 27.7, "lon": 123.5, "stage": "typhoon"}


def test_parse_jma_storm_warning_area():
    raw = load_json("jma_typhoon.json")["TC2637"]
    s = typhoon.parse_jma("TC2637", raw["specifications"], raw["forecast"])
    assert s.forecast[0]["stormWarning"] == [{"dir": "all", "area": "全域", "km": 180, "nm": 97}]
    assert s.forecast[0]["radius25"] == []  # 預報點的是暴風警戒域，不放進 radius25
    assert s.now["radius15"] == [
        {"dir": "SW", "area": "南西", "km": 220, "nm": 120},
        {"dir": "NE", "area": "北東", "km": 165, "nm": 90},
    ]


def test_parse_jma_bad():
    assert typhoon.parse_jma("TC1", {"x": 1}) is None
    assert typhoon.parse_jma("TC1", [{"part": "title"}]) is None


def test_fetch_jma_one_storm_fails(monkeypatch):
    """某一顆的 specifications 抓不到只跳過那顆；forecast.json 抓不到只少過去路徑。"""
    raw = load_json("jma_typhoon.json")

    class Resp:
        def __init__(self, data):
            self.data = data

        def json(self):
            return self.data

    def fake_get(url, **k):
        if url == typhoon.JMA_TARGET_URL:
            return Resp(raw["targetTc"])
        tc, kind = url.rsplit("/", 2)[-2:]
        if tc == "TC2637":
            raise typhoon.TyphoonError("x", "http_500")
        if tc == "TC2638" and kind == "forecast.json":
            raise typhoon.TyphoonError("x", "timeout")
        return Resp(raw[tc]["specifications" if kind.startswith("spec") else "forecast"])

    monkeypatch.setattr(typhoon, "http_get", fake_get)
    out = typhoon.fetch_jma()
    assert [s.key for s in out.storms] == ["TC2636", "TC2638"]
    assert out.errors == {"TC2637": "http_500", "TC2638/forecast": "timeout"}
    assert out.storms[1].past == [] and out.storms[1].forecast
    assert out.raw["TC2638"]["forecast"] is None and "TC2637" not in out.raw


# ---- 選哪一份、範圍、stale ----


def test_build_selects_cwa_and_jma_only(cwa, jma):
    doc = typhoons.build(cwa, jma, OK, NOW)
    assert doc["active"] is True
    assert doc["bounds"] == typhoons.BOUNDS
    assert doc["sources"] == {"cwa": {"ok": True}, "jma": {"ok": True}}
    # 29W 兩邊都有 → 只放氣象署那份、others 記 JMA；TD 只有 JMA → 用 JMA；In-fa 範圍外
    assert [(s["id"], s["source"]) for s in doc["storms"]] == [
        ("2630", "cwa"),
        ("jma-TC2638", "jma"),
    ]
    assert doc["outOfRange"] == [{"id": "2631", "source": "cwa"}]
    champi, td = doc["storms"]
    assert champi["name"] == {"zh-TW": "薔琵", "zh-HK": "薔琵", "zh-CN": "Champi", "en": "Champi"}
    assert champi["url"] == typhoon.CWA_PAGE and champi["issuedAt"] == "2026-10-24T18:00:00Z"
    assert champi["others"] == [
        {
            "source": "jma",
            "id": "TC2636",
            "issuedAt": "2026-10-24T15:45:00Z",
            "url": typhoon.JMA_PAGE,
        }
    ]
    assert champi["stale"] is False and len(champi["forecast"]) == 3
    assert td["name"] == dict.fromkeys(("zh-TW", "zh-HK", "zh-CN", "en"), "TC2638")
    assert (td["url"], td["others"], td["now"]["category"]) == (typhoon.JMA_PAGE, [], "TD")
    assert td["forecast"][0]["stormWarning"] == [
        {"dir": "all", "area": "全域", "km": 220, "nm": 120}
    ]
    json.dumps(doc)  # 能寫成 JSON


def test_build_cwa_failed_uses_jma(jma):
    status = {"cwaTyphoon": {"ok": False, "error": "http_500"}, "jmaTyphoon": {"ok": True}}
    doc = typhoons.build(None, jma, status, NOW)
    assert doc["sources"]["cwa"] == {"ok": False, "error": "http_500"}
    assert [(s["id"], s["source"]) for s in doc["storms"]] == [
        ("2630", "jma"),
        ("jma-TC2638", "jma"),
    ]
    assert doc["storms"][0]["name"]["zh-TW"] == "Champi"  # JMA 沒有中文名
    assert doc["outOfRange"] == [{"id": "2631", "source": "jma"}]


def _storm(source, key, number=None, en="", lat=20.0, lon=125.0, t="2026-10-24T18:00:00Z"):
    now = {"time": t, "lat": lat, "lon": lon, "radius15": [], "radius25": []}
    return Storm(source, key, number, "", en, utc(2026, 10, 24, 18), [], now, [])


def test_same_storm_rules():
    # 1. 編號：兩邊都有就只看編號（名字一樣、編號不同也不算）
    assert typhoons.same_storm(_storm("cwa", "ty30", "2630"), _storm("jma", "TC2636", "2630"))
    assert not typhoons.same_storm(
        _storm("cwa", "ty30", "2630", "X"), _storm("jma", "TC2636", "2631", "X")
    )
    # 2. 英文名：不分大小寫、忽略連字號
    assert typhoons.same_storm(
        _storm("cwa", "ty31", en="IN-FA"), _storm("jma", "TC2637", en="In-fa")
    )
    assert not typhoons.same_storm(
        _storm("cwa", "ty31", en="Kong-rey"), _storm("jma", "TC2637", en="In-fa")
    )
    # 3. 位置：300 公里、6 小時內
    c = _storm("cwa", "td32")
    assert typhoons.same_storm(c, _storm("jma", "TC2639", lat=21.5, t="2026-10-24T15:00:00Z"))
    assert not typhoons.same_storm(c, _storm("jma", "TC2639", lat=23.0))  # 約 333 公里
    assert not typhoons.same_storm(c, _storm("jma", "TC2639", t="2026-10-24T09:00:00Z"))


def test_in_range_uses_now_and_forecast_only():
    s = _storm("jma", "TC1", lat=10.0, lon=160.0)
    assert not typhoons.in_range(s)
    s.past = [{"time": None, "lat": 20.0, "lon": 120.0}]  # 過去路徑不算
    assert not typhoons.in_range(s)
    s.forecast = [{"lat": 2.3, "lon": 149.8}]  # 邊上算
    assert typhoons.in_range(s)
    s.now, s.forecast = None, [{"lat": 2.2, "lon": 149.8}]
    assert not typhoons.in_range(s)


def test_bounds_match_airports():
    """`BOUNDS` 是 51 個機場的經緯度外擴 5 度、往外取到 0.1 度（和網頁 HW15 用同一組）。"""
    aps = json.loads((ROOT / "airports.json").read_text("utf-8"))["airports"]
    assert len(aps) == 51
    lats, lons = [a["lat"] for a in aps], [a["lon"] for a in aps]
    m = typhoons.MARGIN_DEG
    assert typhoons.BOUNDS == {
        "south": floor((min(lats) - m) * 10) / 10,
        "north": ceil((max(lats) + m) * 10) / 10,
        "west": floor((min(lons) - m) * 10) / 10,
        "east": ceil((max(lons) + m) * 10) / 10,
    }


def test_stale_after_12_hours(cwa, jma):
    assert typhoons.build(cwa, jma, OK, utc(2026, 10, 25, 6))["storms"][0]["stale"] is False
    late = typhoons.build(cwa, jma, OK, utc(2026, 10, 25, 6, 1))
    # 氣象署那份 18:00Z 起算過了 12 小時；JMA 的 TD 15:50Z 早就過了
    assert [s["stale"] for s in late["storms"]] == [True, True]
    assert typhoons.build(cwa, jma, OK, utc(2026, 10, 25, 3, 50))["storms"][1]["stale"] is False


def test_no_typhoons():
    doc = typhoons.build(TyphoonData([], {}), TyphoonData([], {}), OK, NOW)
    assert (doc["active"], doc["storms"], doc["outOfRange"]) == (False, [], [])
    assert "reusedFrom" not in doc


def test_only_out_of_range():
    raw = load_json("jma_typhoon.json")["TC2637"]
    infa = typhoon.parse_jma("TC2637", raw["specifications"], raw["forecast"])
    doc = typhoons.build(None, TyphoonData([infa], {}), OK, NOW)
    assert (doc["active"], doc["storms"], doc["outOfRange"]) == (
        False,
        [],
        [{"id": "2631", "source": "jma"}],
    )


def test_both_failed_reuses_previous(cwa, jma):
    prev = typhoons.build(cwa, jma, OK, NOW)
    failed = {
        "cwaTyphoon": {"ok": False, "error": "timeout"},
        "jmaTyphoon": {"ok": False, "error": "network"},
    }
    later = utc(2026, 10, 25, 7)
    doc = typhoons.build(None, None, failed, later, prev)
    assert doc["reusedFrom"] == prev["generatedAt"] and doc["generatedAt"] == "2026-10-25T07:00:00Z"
    assert doc["active"] is True
    assert [s["id"] for s in doc["storms"]] == ["2630", "jma-TC2638"]
    assert [s["stale"] for s in doc["storms"]] == [True, True]  # 照這一報的時間重算
    assert doc["sources"] == {
        "cwa": {"ok": False, "error": "timeout"},
        "jma": {"ok": False, "error": "network"},
    }
    # 沒有上一份（或上一份壞了）就是沒有颱風
    for p in (None, {"storms": "壞"}, {"storms": []}):
        d = typhoons.build(None, None, failed, later, p)
        assert (d["active"], d["storms"], "reusedFrom" in d) == (False, [], False)


def test_read_previous(tmp_path):
    assert typhoons.read_previous(tmp_path) is None
    (tmp_path / typhoons.FILENAME).write_text("{壞", "utf-8")
    assert typhoons.read_previous(tmp_path) is None
    (tmp_path / typhoons.FILENAME).write_text('{"storms": []}', "utf-8")
    assert typhoons.read_previous(tmp_path) == {"storms": []}
