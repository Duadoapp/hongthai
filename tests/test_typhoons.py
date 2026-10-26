"""HD34：颱風地圖的官方路徑與暴風圈（`sources/typhoon.py`、`typhoons.py`）——只轉載、不計算。"""

from __future__ import annotations

import json
import re
from dataclasses import replace
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
    # 氣象署的颱風編號不是國際編號（HD34b）：number 一律 None
    assert (champi.source, champi.key, champi.number) == ("cwa", "ty30", None)
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
        None,
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
    # 29W 進過台灣附近 → 只放氣象署那份、others 記 JMA；TD 只有 JMA → 用 JMA
    assert [(s["id"], s["source"]) for s in doc["storms"]] == [
        ("2630", "cwa"),
        ("jma-TC2638", "jma"),
    ]
    # In-fa 從沒進過台灣附近 → 日本氣象廳那份（範圍外）
    assert doc["outOfRange"] == [{"id": "2631", "source": "jma"}]
    champi, td = doc["storms"]
    assert (champi["sourceId"], td["sourceId"]) == ("ty30", "TC2638")
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
    # 不比編號（HD34b：氣象署的 CwaTyNo 不是國際編號）：編號一樣、名字不同不算，反過來算
    assert not typhoons.same_storm(
        _storm("cwa", "ty30", "2630", "IN-FA"), _storm("jma", "TC2636", "2630", "Champi")
    )
    assert typhoons.same_storm(
        _storm("cwa", "ty29", "2629", "CHAMPI"), _storm("jma", "TC2636", "2630", "Champi")
    )
    # 1. 英文名：不分大小寫、忽略連字號
    assert typhoons.same_storm(
        _storm("cwa", "ty31", en="IN-FA"), _storm("jma", "TC2637", en="In-fa")
    )
    assert not typhoons.same_storm(
        _storm("cwa", "ty31", en="Kong-rey"), _storm("jma", "TC2637", en="In-fa")
    )
    # 2. 有一邊沒有英文名：位置 300 公里、6 小時內
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


# ---- 以颱風為單位分來源（Shawn 2026-10-25：台灣附近 TAIWAN_NEAR，中途不換）----

T0 = "2026-10-24T18:00:00Z"
ISSUED = utc(2026, 10, 24, 18)


def _pt(lat, lon, t=None):
    return {"time": t, "lat": lat, "lon": lon}


def _pair(past, now, issued=ISSUED):
    """同一顆（國際編號 2640，只有 JMA 有）的氣象署與 JMA 兩份；`past`／`now` 是 (緯, 經)。"""

    def one(source, key, number):
        n = {**_pt(*now, T0), "radius15": [], "radius25": []}
        pts = [_pt(lat, lon) for lat, lon in past] + [_pt(*now, T0)]
        return Storm(source, key, number, "", "Test", issued, pts, n, [])

    return one("cwa", "ty40", None), one("jma", "TC2644", "2640")


def _doc(c, j, previous=None, now=NOW, status=OK):
    return typhoons.build(
        None if c is False else TyphoonData([c] if c else [], {}),
        None if j is False else TyphoonData([j] if j else [], {}),
        status,
        now,
        previous,
    )


def _src(doc):
    return [(s["id"], s["source"]) for s in doc["storms"]]


def test_taiwan_near_constant():
    assert typhoons.TAIWAN_NEAR == {"south": 18, "north": 30, "west": 112, "east": 130}
    c, _ = _pair([(15.0, 140.0)], (18.0, 130.0))  # 邊上算
    assert typhoons.near_taiwan(c)
    c, _ = _pair([(15.0, 140.0)], (17.9, 130.0))
    assert not typhoons.near_taiwan(c)
    c.forecast = [{"lat": 22.0, "lon": 125.0}]  # 預報點不算
    assert not typhoons.near_taiwan(c)


def test_never_near_taiwan_uses_jma():
    c, j = _pair([(14.0, 140.0), (16.0, 136.0)], (18.0, 133.0))
    doc = _doc(c, j)
    assert _src(doc) == [("2640", "jma")]
    assert doc["storms"][0]["others"][0]["source"] == "cwa"
    assert doc["storms"][0]["sourceId"] == "TC2644"


def test_entered_near_taiwan_uses_cwa_whole_life():
    # 上一報還在外面（jma），這一報進了台灣附近 → 改用氣象署（只會 jma → cwa，不會反過來）
    c, j = _pair([(14.0, 140.0)], (18.0, 133.0))
    before = _doc(c, j)
    assert _src(before) == [("2640", "jma")]
    c, j = _pair([(14.0, 140.0), (18.0, 133.0)], (20.0, 129.5))
    doc = _doc(c, j, before)
    assert _src(doc) == [("2640", "cwa")]
    assert doc["storms"][0]["others"][0] == {
        "source": "jma",
        "id": "TC2644",
        "issuedAt": "2026-10-24T18:00:00Z",
        "url": typhoon.JMA_PAGE,
    }


def test_left_near_taiwan_stays_cwa():
    # 離開台灣附近：氣象署的過去路徑還有那一段 → 仍是 cwa
    c, j = _pair([(20.0, 129.5), (28.0, 128.0)], (33.0, 135.0))
    first = _doc(c, j)
    assert _src(first) == [("2640", "cwa")]
    # 就算這一報氣象署的過去路徑沒有那一段（判斷不出來），上一份是 cwa 就維持 cwa
    c, j = _pair([(31.0, 131.0)], (34.0, 137.0))
    assert not typhoons.near_taiwan(c)
    assert _src(_doc(c, j, first)) == [("2640", "cwa")]
    # 上一份是 jma 的照常判斷
    assert _src(_doc(c, j, _doc(*_pair([(14.0, 140.0)], (18.0, 133.0))))) == [("2640", "jma")]


def test_previous_cwa_but_cwa_missing_this_run():
    """上一份是 cwa、這一報氣象署沒資料：沿用上一份那筆（stale 重算、記 reusedFrom），
    不切回 jma。"""
    c, j = _pair([(20.0, 129.5)], (24.0, 127.0))
    first = _doc(c, j)
    later = utc(2026, 10, 25, 7)
    _, j2 = _pair([(20.0, 129.5), (24.0, 127.0)], (27.0, 126.0), utc(2026, 10, 25, 3))
    # 1. 氣象署成功、但沒列這顆，日本氣象廳還有
    doc = _doc(None, j2, first, later)
    (s,) = doc["storms"]
    assert (s["source"], s["sourceId"], s["now"]["lat"]) == ("cwa", "ty40", 24.0)
    assert (s["reusedFrom"], s["stale"]) == (first["generatedAt"], True)
    assert s["others"] == [
        {
            "source": "jma",
            "id": "TC2644",
            "issuedAt": "2026-10-25T03:00:00Z",
            "url": typhoon.JMA_PAGE,
        }
    ]
    # 再下一報還是沒有：reusedFrom 維持最早沿用的那份
    assert _doc(None, j2, doc, later)["storms"][0]["reusedFrom"] == first["generatedAt"]
    # 2. 氣象署整個失敗：日本氣象廳有或沒有都沿用
    failed = {"cwaTyphoon": {"ok": False, "error": "timeout"}, "jmaTyphoon": {"ok": True}}
    assert _src(_doc(False, j2, first, later, failed)) == [("2640", "cwa")]
    assert _src(_doc(False, None, first, later, failed)) == [("2640", "cwa")]
    # 3. 氣象署成功、兩邊都沒有這顆了 → 颱風結束，拿掉
    gone = _doc(None, None, first, later)
    assert (gone["active"], gone["storms"]) == (False, [])
    # 4. 氣象署回來了 → 用這一報的
    c3, j3 = _pair([(31.0, 131.0)], (34.0, 137.0), utc(2026, 10, 25, 6))
    s3 = _doc(c3, j3, doc, later)["storms"][0]
    assert (s3["source"], s3["issuedAt"], "reusedFrom" in s3) == (
        "cwa",
        "2026-10-25T06:00:00Z",
        False,
    )


def test_cwa_only_never_near_taiwan_still_drawn():
    c, _ = _pair([(14.0, 140.0)], (18.0, 133.0))
    assert _src(_doc(c, None)) == [("cwa-ty40", "cwa")]


# ---- HD34b：2026-10-25 13:06Z 實抓的氣象署與日本氣象廳（fixtures/README.md 有裁法）----

AT_1306 = utc(2026, 10, 25, 13, 6)


def _real_1306():
    cwa_raw = load_json("cwa_typhoon_1306z.json")
    jma_raw = load_json("jma_typhoon_1306z.json")
    jma_storms = [
        typhoon.parse_jma(tc, v["specifications"], v["forecast"])
        for tc, v in jma_raw.items()
        if tc != "targetTc"
    ]
    return TyphoonData(typhoon.parse_cwa(cwa_raw), cwa_raw), TyphoonData(jma_storms, jma_raw)


def test_parse_cwa_real_1306z():
    """實際的鍵名（`DateTime`、`CoordinateLatitude`、`InitialTime`、`ForecastHour`、`Circle15ms`、
    `Radius70PercentProbability`）讀得到位置與時間。"""
    cwa, _ = _real_1306()
    champi, infa = cwa.storms
    assert (champi.key, champi.number, champi.name_zh, champi.name_en) == (
        "ty29",
        None,  # CwaTyNo 29 不是國際編號 2630
        "薔琵",
        "Champi",
    )
    assert (infa.key, infa.number, infa.name_zh, infa.name_en) == ("ty30", None, "煙花", "In-Fa")
    assert champi.issued_at == utc(2026, 10, 25, 6)  # InitialTime 14:00+08:00
    assert (len(champi.past), len(champi.forecast)) == (13, 4)
    assert champi.past[0] == {"time": "2026-10-14T00:00:00Z", "lat": 9.5, "lon": 160.3}
    assert champi.now == {
        "time": "2026-10-25T06:00:00Z",
        "lat": 30.1,
        "lon": 125.4,
        "radius15": [{"dir": "all", "km": 150}],  # Radius；四象限 QuadrantRadii 不轉
        "radius25": [],  # 沒有 Circle25ms
    }
    assert champi.forecast[0] == {
        "time": "2026-10-25T12:00:00Z",  # InitialTime＋ForecastHour 6
        "lat": 30.6,
        "lon": 126.5,
        "radius15": [{"dir": "all", "km": 150}],
        "radius25": [],
        "leadHours": 6,
        "probabilityRadius": {"km": 40},
        "stormWarning": [],
    }
    assert champi.forecast[-1]["radius15"] == []  # 24 小時那點沒有 Circle15ms
    assert (len(infa.past), len(infa.forecast)) == (10, 9)
    assert infa.now["radius25"] == [{"dir": "all", "km": 40}]
    assert (infa.forecast[-1]["leadHours"], infa.forecast[-1]["time"]) == (
        120,
        "2026-10-30T06:00:00Z",
    )
    assert infa.forecast[-1]["probabilityRadius"] == {"km": 460}


def test_build_real_1306z():
    """薔琵進過台灣附近 → 氣象署、`others` 是日本氣象廳薔琵；煙花沒進過 → 日本氣象廳、`others` 是
    氣象署煙花。HD34 時氣象署煙花（ty30）被當成 2630 配給日本氣象廳薔琵。HD34c 起日本氣象廳那份
    薔琵已是 `LOW`，整顆拿掉、記在 `ended`。"""
    cwa, jma = _real_1306()
    pairs = typhoons.pair_up(cwa.storms, jma.storms)
    assert [(c.key, j.key) for c, j in pairs] == [("ty29", "TC2636"), ("ty30", "TC2637")]
    c_champi, j_champi = pairs[0]
    s, others = typhoons.choose(c_champi, j_champi, None, True)
    assert (s.source, [o.key for o in others]) == ("cwa", ["TC2636"])
    doc = typhoons.build(cwa, jma, OK, AT_1306)
    (infa,) = doc["storms"]
    assert (doc["active"], doc["outOfRange"]) == (True, [])
    assert doc["ended"] == [{"id": "2630", "source": "jma", "reason": "jma_low"}]
    assert (infa["id"], infa["source"], infa["sourceId"]) == ("2631", "jma", "TC2637")
    assert infa["issuedAt"] == "2026-10-25T10:10:00Z"
    # 日本氣象廳那份只有英文名：配到的氣象署那份的中文名借給 zh-TW／zh-HK（2026-10-26）
    assert infa["name"] == {"zh-TW": "煙花", "zh-HK": "煙花", "zh-CN": "In-fa", "en": "In-fa"}
    assert infa["others"] == [
        {
            "source": "cwa",
            "id": "ty30",
            "issuedAt": "2026-10-25T06:00:00Z",
            "url": typhoon.CWA_PAGE,
        }
    ]
    assert (len(infa["past"]), len(infa["forecast"])) == (21, 5)
    # 上一份是 HD34 錯配的那份（薔琵 jma、others 是氣象署 ty30；outOfRange 有 cwa 2629）：結果一樣
    prev = load_json("typhoons_1306z_mispaired.json")
    assert prev["storms"][0]["others"][0]["id"] == "ty30"
    assert typhoons.build(cwa, jma, OK, AT_1306, prev) == doc


def test_previous_entry_named_ignores_others():
    """上一份那筆的 `others` 配錯過也不會認錯顆：英文名都有時只比英文名、不看 `others`。"""
    cwa, jma = _real_1306()
    (c_champi, c_infa), (j_champi, j_infa) = cwa.storms, jma.storms
    prev = load_json("typhoons_1306z_mispaired.json")["storms"]
    assert typhoons._previous_entry(prev, c_infa, j_infa)["sourceId"] == "TC2637"
    assert typhoons._previous_entry(prev, c_champi, j_champi)["sourceId"] == "TC2636"
    assert typhoons._previous_entry(prev, c_infa, None)["id"] == "2631"
    # 上一份薔琵是 cwa、others 錯配成日本氣象廳煙花：舊的認法會讓煙花沿用 cwa（中途不換）
    sticky = [
        {
            **prev[0],
            "source": "cwa",
            "sourceId": "ty29",
            "others": [{**prev[0]["others"][0], "source": "jma", "id": "TC2637"}],
        }
    ]
    doc = typhoons.build(cwa, jma, OK, AT_1306, {"storms": sticky, "generatedAt": "x"})
    # 薔琵日本氣象廳那份已是 LOW（HD34c 拿掉）；煙花沒有被帶成 cwa
    assert [(s["id"], s["source"]) for s in doc["storms"]] == [("2631", "jma")]
    assert [e["id"] for e in doc["ended"]] == ["2630"]


def test_storm_id_rules():
    """`id`：國際編號（日本氣象廳的）→ 上一份同一顆的國際編號 → `<來源>-<代號>`。"""
    c, j = _pair([(20.0, 129.5)], (24.0, 127.0))
    first = _doc(c, j)
    assert _src(first) == [("2640", "cwa")]  # 用氣象署那份也拿日本氣象廳的國際編號
    # 日本氣象廳不列這顆了、只剩氣象署：沿用上一份的國際編號，不變成 cwa-ty40
    assert _src(_doc(c, None, first)) == [("2640", "cwa")]
    assert _src(_doc(c, None)) == [("cwa-ty40", "cwa")]  # 沒有上一份
    # 熱帶性低氣壓（沒有名字、沒有編號）→ 命名後拿到國際編號
    td = _doc(_storm("cwa", "td35"), _storm("jma", "TC2639"))
    assert _src(td) == [("cwa-td35", "cwa")]  # 20N 125E 在台灣附近
    # 命名後氣象署代號變 ty31：上一份那筆沒有英文名，靠 others 的日本氣象廳代號認出來，維持 cwa
    # （這一報氣象署的過去路徑沒有台灣附近那段）
    c2 = _storm("cwa", "ty31", en="FUNG-WONG", lat=31.0, lon=131.0)
    j2 = _storm("jma", "TC2639", "2632", "Fung-wong", lat=31.0, lon=131.0)
    assert not typhoons.near_taiwan(c2)
    assert _src(_doc(c2, j2, td)) == [("2632", "cwa")]
    assert _src(_doc(c2, j2)) == [("2632", "jma")]


def test_names_borrow_cwa_zh_only_for_jma():
    """借名只借氣象署那份的中文名；自己有中文名、或配到的不是氣象署的，不借。"""
    j = _storm("jma", "TC2637", "2631", en="In-fa")
    c = _storm("cwa", "ty30", en="In-fa")
    c.name_zh = "煙花"
    assert typhoons.names(j) == dict.fromkeys(("zh-TW", "zh-HK", "zh-CN", "en"), "In-fa")
    assert typhoons.names(j, [c])["zh-TW"] == "煙花"
    assert typhoons.names(j, [c])["zh-CN"] == "In-fa"
    c2 = _storm("cwa", "ty29", en="Champi")
    c2.name_zh = "薔琵"
    assert typhoons.names(c2, [j])["zh-HK"] == "薔琵"


# ---- HD34c：颱風名稱對照表、減弱的颱風拿掉 ----

TABLE = typhoons.load_names(ROOT / typhoons.NAMES_FILENAME)
# 哪個機關的官方頁抓不到、那一欄先空著的名字（{英文名: {欄位}}）；2026-10-26 三個都抓到，沒有
EMPTY_OK: dict[str, set[str]] = {}


def test_names_table_file():
    doc = json.loads((ROOT / typhoons.NAMES_FILENAME).read_text("utf-8"))
    rows = doc["names"]
    assert len(rows) == 140
    keys = [typhoons._name_key(r["en"]) for r in rows]
    assert len(set(keys)) == 140 and all(keys)
    for r in rows:
        assert set(r) == {"en", *typhoons.ZH}
        for k in typhoons.ZH:
            assert r[k] or k in EMPTY_OK.get(r["en"], set()), (r["en"], k)
    # 三個機關的官方頁網址與抓取時間
    for k, host in (("zh-TW", "cwa.gov.tw"), ("zh-HK", "hko.gov.hk"), ("zh-CN", "nmc.cn")):
        src = doc["sources"][k]
        assert host in src["url"] and src["fetchedAt"] and src["agency"]
    assert len(TABLE) == 140
    assert TABLE["CHAMPI"] == {"zh-TW": "薔琵", "zh-HK": "薔琵", "zh-CN": "蔷琵"}
    assert TABLE["INFA"] == {"zh-TW": "煙花", "zh-HK": "煙花", "zh-CN": "烟花"}
    # 三個機關譯名不同的（照各自的官方名單，不統一）
    assert TABLE["DAMREY"] == {"zh-TW": "丹瑞", "zh-HK": "達維", "zh-CN": "达维"}


AT_0826 = utc(2026, 10, 26, 8, 26)


def _real_0826():
    cwa_raw = load_json("cwa_typhoon_0826z.json")
    jma_raw = load_json("jma_typhoon_0826z.json")
    jma_storms = [
        typhoon.parse_jma(tc, v["specifications"], v["forecast"])
        for tc, v in jma_raw.items()
        if tc != "targetTc"
    ]
    return TyphoonData(typhoon.parse_cwa(cwa_raw), cwa_raw), TyphoonData(jma_storms, jma_raw)


def test_build_real_0826z():
    """`data` 分支 2026-10-26 08:26Z 的原始回應：日本氣象廳 TC2636（薔琵）10-25 21:45 JST 標 `LOW`
    之後 `targetTc` 還留著 → 拿掉、記在 `ended`；烟花三種中文都照對照表。"""
    cwa, jma = _real_0826()
    assert [(s.key, s.category) for s in jma.storms] == [("TC2637", "TY"), ("TC2636", "LOW")]
    assert [(s.key, s.max_wind) for s in cwa.storms] == [("ty30", 40)]
    doc = typhoons.build(cwa, jma, OK, AT_0826, table=TABLE)
    assert [(s["id"], s["source"]) for s in doc["storms"]] == [("2631", "jma")]
    assert doc["ended"] == [{"id": "2630", "source": "jma", "reason": "jma_low"}]
    assert (doc["active"], doc["outOfRange"]) == (True, [])
    (infa,) = doc["storms"]
    assert infa["name"] == {"zh-TW": "煙花", "zh-HK": "煙花", "zh-CN": "烟花", "en": "In-fa"}
    assert infa["others"][0]["id"] == "ty30"
    # 上一份薔琵是 cwa（中途不換；假設 13:06Z 那報日本氣象廳還沒標 LOW）：氣象署這一報沒列薔琵、
    # 或氣象署整個失敗，都不沿用上一份那筆
    c13, j13 = _real_1306()
    j13.storms = [replace(s, category="TS") if s.key == "TC2636" else s for s in j13.storms]
    prev = typhoons.build(c13, j13, OK, AT_1306, table=TABLE)
    assert [(s["id"], s["source"]) for s in prev["storms"]] == [("2630", "cwa"), ("2631", "jma")]
    failed = {"cwaTyphoon": {"ok": False, "error": "timeout"}, "jmaTyphoon": {"ok": True}}
    for c_now, st in ((cwa, OK), (None, failed)):
        d = typhoons.build(c_now, jma, st, AT_0826, prev, TABLE)
        assert [(s["id"], s["source"]) for s in d["storms"]] == [("2631", "jma")]
        assert d["ended"] == doc["ended"]
        assert all("reusedFrom" not in s for s in d["storms"])
    json.dumps(doc)


def test_names_table_first_then_cwa_then_en(caplog):
    c = _storm("cwa", "ty29", en="CHAMPI")
    c.name_zh = "某譯名"  # 對照表優先於氣象署這一報給的
    assert typhoons.names(c, table=TABLE) == {
        "zh-TW": "薔琵",
        "zh-HK": "薔琵",
        "zh-CN": "蔷琵",
        "en": "CHAMPI",  # en 一律來源的英文名
    }
    # 對照表有、但那一欄空著 → 那一欄照舊（氣象署的中文名；zh-CN 英文名）
    partial = {"CHAMPI": {"zh-TW": "薔琵"}}
    assert typhoons.names(c, table=partial) == {
        "zh-TW": "薔琵",
        "zh-HK": "某譯名",
        "zh-CN": "CHAMPI",
        "en": "CHAMPI",
    }
    # 對照表查不到（新名字）：氣象署中文名 → 英文名，build 寫一行 log（英文名與編號）
    new = _storm("cwa", "ty41", en="Newname", lat=22.0, lon=121.0)
    new.name_zh = "新名"
    j = _storm("jma", "TC2650", "2641", en="Newname", lat=22.0, lon=121.0)
    with caplog.at_level("WARNING", logger="hongthai"):
        doc = _doc_t(new, j)
    assert doc["storms"][0]["name"] == {
        "zh-TW": "新名",
        "zh-HK": "新名",
        "zh-CN": "Newname",
        "en": "Newname",
    }
    (rec,) = [r for r in caplog.records if "對照表沒有" in r.getMessage()]
    assert "Newname" in rec.getMessage() and "2641" in rec.getMessage()
    # 沒有英文名的（熱帶性低氣壓）不查表、不寫 log
    caplog.clear()
    with caplog.at_level("WARNING", logger="hongthai"):
        _doc_t(_storm("cwa", "td35"), None)
    assert not [r for r in caplog.records if "對照表沒有" in r.getMessage()]


def _doc_t(c, j, previous=None, now=NOW):
    return typhoons.build(
        TyphoonData([c] if c else [], {}),
        TyphoonData([j] if j else [], {}),
        OK,
        now,
        previous,
        TABLE,
    )


def test_reused_entry_gets_table_names():
    c, j = _pair([(20.0, 129.5)], (24.0, 127.0))
    c.name_en, j.name_en = "CHAMPI", "Champi"
    first = _doc(c, j)  # 沒有對照表時的那份
    assert first["storms"][0]["name"]["zh-CN"] == "CHAMPI"
    doc = typhoons.build(TyphoonData([], {}), TyphoonData([j], {}), OK, NOW, first, TABLE)
    (s,) = doc["storms"]
    assert s["reusedFrom"] == first["generatedAt"]
    assert s["name"] == {"zh-TW": "薔琵", "zh-HK": "薔琵", "zh-CN": "蔷琵", "en": "CHAMPI"}


def test_cwa_weakened_to_td_removed():
    """氣象署命名過的颱風最新定位 `MaxWindSpeed` < 17.2 m/s → 整顆拿掉（日本氣象廳那份也不畫）。"""
    assert typhoons.CWA_TY_MIN_MS == 17.2
    for wind, gone in ((17, True), (17.1, True), (17.2, False), (18, False), (None, False)):
        c, j = _pair([(20.0, 129.5)], (24.0, 127.0))
        c.max_wind = wind
        doc = _doc(c, j)
        assert (doc["ended"] != [], doc["storms"] == []) == (gone, gone), wind
    c, j = _pair([(20.0, 129.5)], (24.0, 127.0))
    c.max_wind = 15
    assert _doc(c, j)["ended"] == [{"id": "2640", "source": "cwa", "reason": "cwa_td"}]
    assert _doc(c, None)["ended"] == [{"id": "cwa-ty40", "source": "cwa", "reason": "cwa_td"}]
    # 範圍外的也記在 ended，不記 outOfRange
    c2, j2 = _pair([(10.0, 170.0)], (12.0, 170.0))
    c2.max_wind = 15
    far = _doc(c2, j2)
    assert (far["outOfRange"], len(far["ended"])) == ([], 1)


def test_cwa_unnamed_td_still_shown():
    """從沒命名過的熱帶性低氣壓（只有 `CwaTdNo`）風速本來就低，照舊顯示。"""
    td = _storm("cwa", "td35")
    td.max_wind = 12
    doc = _doc(td, None)
    assert (_src(doc), doc["ended"]) == ([("cwa-td35", "cwa")], [])
    raw = load_json("cwa_typhoon_1306z.json")  # 實際回應：MaxWindSpeed 讀得到
    assert [s.max_wind for s in typhoon.parse_cwa(raw)] == [18, 30]


def test_ended_not_reused_and_comes_back():
    """任一來源說減弱：上一份是 cwa（中途不換）也不沿用；之後再增強照一般規則回來。"""
    c, j = _pair([(20.0, 129.5)], (24.0, 127.0))
    first = _doc(c, j)
    assert _src(first) == [("2640", "cwa")]
    later = utc(2026, 10, 25, 7)
    # 氣象署成功但沒列這顆、日本氣象廳說 LOW → 拿掉（不是沿用上一份那筆）
    j.category = "LOW"
    doc = _doc(None, j, first, later)
    assert (doc["storms"], doc["ended"]) == (
        [],
        [{"id": "2640", "source": "jma", "reason": "jma_low"}],
    )
    # 氣象署整個失敗也一樣
    failed = {"cwaTyphoon": {"ok": False, "error": "timeout"}, "jmaTyphoon": {"ok": True}}
    assert _doc(False, j, first, later, failed)["storms"] == []
    # 氣象署那份還是颱風強度也拿掉（任一來源）
    assert _doc(c, j, first, later)["storms"] == []
    # 再下一報日本氣象廳又發 TS：照一般規則回來（上一份沒有這顆了，照台灣附近判斷）
    j.category = "TS"
    assert _src(_doc(c, j, doc, later)) == [("2640", "cwa")]


def test_jma_td_not_removed_yet():
    """日本氣象廳 `TD`（台風から変わった熱帯低気圧）先不拿掉（等 Shawn 決定）。"""
    _, j = _pair([(20.0, 129.5)], (24.0, 127.0))
    j.category = "TD"
    assert (_src(_doc(None, j)), _doc(None, j)["ended"]) == ([("2640", "jma")], [])
    raw = load_json("jma_typhoon_1306z.json")["TC2636"]
    assert typhoon.parse_jma("TC2636", raw["specifications"], raw["forecast"]).category == "LOW"
