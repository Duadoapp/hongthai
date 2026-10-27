"""HD41：「幾點進暴風圈」——依官方暴風圈預報推算的進入／離開時間（`stormentry.py`、
`typhoons.json` 的 `entries`）。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

import pytest
from conftest import load_json, utc

from hongthai import stormentry, typhoons
from hongthai.sources import typhoon
from hongthai.sources.typhoon import Storm, TyphoonData
from hongthai.timeutil import iso

T0 = utc(2026, 10, 28, 0)
OK = {"cwaTyphoon": {"ok": True}, "jmaTyphoon": {"ok": True}}
KM_PER_DEG_LAT = 111.195


@dataclass
class Ap:
    iata: str
    icao: str
    lat: float
    lon: float


def _r(km: float | None, d: str = "all") -> list[dict]:
    return [] if km is None else [{"dir": d, "km": km}]


def _pt(hours: float, lat: float, lon: float, r15=None, r25=None, warn=None, **extra) -> dict:
    p = {
        "time": iso(T0 + timedelta(hours=hours)),
        "lat": lat,
        "lon": lon,
        "radius15": r15 if isinstance(r15, list) else _r(r15),
        "radius25": r25 if isinstance(r25, list) else _r(r25),
    }
    if hours:  # 預報點
        p.update(leadHours=hours, probabilityRadius={"km": 999}, stormWarning=_r(warn))
    return p | extra


def _storm(source: str, now: dict | None, *forecast: dict, **extra) -> dict:
    return {
        "id": "2699",
        "source": source,
        "issuedAt": iso(T0),
        "stale": False,
        "now": now,
        "forecast": list(forecast),
    } | extra


def _at(h: float) -> str:
    return iso(T0 + timedelta(hours=h))


def _brief(entries: list[dict]) -> list[tuple]:
    return [(e["iata"], e["circle"], e["now"], e["enterAt"], e["exitAt"]) for e in entries]


AP = Ap("TST", "XTST", 25.0, 121.0)


def test_straight_pass_both_cwa_circles():
    """直直走過機場：每小時往東 1 度（北緯 25 度約 100.8 公里）。七級風 150 公里在第 2–4 小時在圈內
    （進入第 2 小時、離開第 5 小時），十級風 50 公里只有第 3 小時。兩種圈各自一筆。"""
    s = _storm("cwa", _pt(0, 25.0, 118.0, 150, 50), _pt(6, 25.0, 124.0, 150, 50))
    out = stormentry.entries([s], [AP])
    assert _brief(out) == [
        ("TST", "cwa_r15", False, _at(2), _at(5)),
        ("TST", "cwa_r25", False, _at(3), _at(4)),
    ]
    assert out[0] == {
        "iata": "TST",
        "icao": "XTST",
        "stormId": "2699",
        "source": "cwa",
        "circle": "cwa_r15",
        "enterAt": "2026-10-28T02:00:00Z",
        "exitAt": "2026-10-28T05:00:00Z",
        "now": False,
        "issuedAt": "2026-10-28T00:00:00Z",
        "method": "linear_hourly",
    }


def test_quadrant_radii_graze():
    """氣象署實況的四象限半徑：南邊兩個象限只有 50 公里，機場在中心正南 90 公里 → 實況不在圈內；
    預報點只有整圈 150，南邊的半徑照時間從 50 內插到 150（第 2.4 小時到 90）→ 第 3 小時進入、
    預報範圍結束還在圈內（`exitAt` null）。正北 90 公里的機場（北邊 200）實況就在圈內。沒有四象限
    （上一份沿用的那筆）用整圈，南邊那個實況就在圈內。"""
    quads = [{"dir": d, "km": km} for d, km in (("NE", 200), ("SE", 50), ("SW", 50), ("NW", 200))]
    d = 90 / KM_PER_DEG_LAT
    south, north = Ap("SSS", "XSSS", 26.0 - d, 120.0), Ap("NNN", "XNNN", 26.0 + d, 120.0)
    now = _pt(0, 26.0, 120.0, 150, radius15Quadrants=quads)
    s = _storm("cwa", now, _pt(6, 26.0, 120.0, 150))
    assert _brief(stormentry.entries([s], [south, north])) == [
        ("SSS", "cwa_r15", False, _at(3), None),
        ("NNN", "cwa_r15", True, None, None),
    ]
    plain = _storm("cwa", _pt(0, 26.0, 120.0, 150), _pt(6, 26.0, 120.0, 150))
    assert _brief(stormentry.entries([plain], [south])) == [("SSS", "cwa_r15", True, None, None)]


def test_now_inside_then_exit():
    """實況點就在圈內 → `now: true`、`enterAt` null；往東走，第 2 小時離開。"""
    s = _storm("cwa", _pt(0, 25.0, 121.0, 150), _pt(6, 25.0, 127.0, 150))
    assert _brief(stormentry.entries([s], [AP])) == [("TST", "cwa_r15", True, None, _at(2))]


def test_no_exit_within_forecast_range():
    """每小時 0.5 度靠近、最後一點停在機場上：第 4 小時進入（第 3 小時 151 公里 > 140），預報範圍
    結束時還在圈內 → `exitAt` null。"""
    s = _storm("cwa", _pt(0, 25.0, 118.0, 140), _pt(6, 25.0, 121.0, 140))
    assert _brief(stormentry.entries([s], [AP])) == [("TST", "cwa_r15", False, _at(4), None)]


def test_no_extrapolation():
    """一直往機場走，但最後一個預報點還在 300 公里外：最後一點之後不算 → 沒有這筆。只有實況點、
    沒有預報點的也只看實況。"""
    s = _storm("cwa", _pt(0, 25.0, 115.0, 150), _pt(6, 25.0, 118.0, 150))
    assert stormentry.entries([s], [AP]) == []
    only_now = _storm("cwa", _pt(0, 25.0, 119.0, 150))
    assert stormentry.entries([only_now], [AP]) == []
    assert _brief(stormentry.entries([_storm("cwa", _pt(0, 25.0, 120.0, 150))], [AP])) == [
        ("TST", "cwa_r15", True, None, None)
    ]


def test_gap_in_circle_stops_the_run():
    """中間有一點沒有這種圈（十級風 6 小時那點沒有）：到前一點為止，不跨過去；七級風照算。"""
    s = _storm(
        "cwa",
        _pt(0, 25.0, 121.0, 150, 50),
        _pt(6, 25.0, 121.0, 150),
        _pt(12, 25.0, 121.0, 150, 50),
    )
    assert _brief(stormentry.entries([s], [AP])) == [
        ("TST", "cwa_r15", True, None, None),
        ("TST", "cwa_r25", True, None, None),
    ]
    # 實況沒有十級風、6 小時那點才有：從那一點開始（`now` false），之前不算
    s = _storm("cwa", _pt(0, 25.0, 121.0, 150), _pt(6, 25.0, 121.0, 150, 50))
    assert _brief(stormentry.entries([s], [AP]))[1] == ("TST", "cwa_r25", False, _at(6), None)


def test_stale_storm_skipped():
    s = _storm("cwa", _pt(0, 25.0, 121.0, 150), _pt(6, 25.0, 127.0, 150), stale=True)
    assert stormentry.entries([s], [AP]) == []


def test_jma_storm_warning_and_now_only_circles():
    """日本氣象廳：`jma_storm_warning` 從實況的暴風域（100 公里）接到 24 小時的暴風警戒域
    （300 公里），圓心每小時往東 0.25 度；`jma_storm`、`jma_gale` 預報點沒有，只看實況。強風域
    `北` 330／`南` 220 是偏心圓（圓心往北 55 公里、半徑 275）。"""
    gale = [{"dir": "N", "area": "北", "km": 330}, {"dir": "S", "area": "南", "km": 220}]
    now = _pt(0, 20.0, 130.0, gale, 100) | {"category": "TY"}
    fc = _pt(24, 20.0, 136.0, [], [], 300) | {"category": "TY"}
    s = _storm("jma", now, fc)
    far = Ap("FAR", "XFAR", 20.0, 133.0)  # 實況 313 公里
    near = Ap("NEA", "XNEA", 20.0, 130.5)  # 實況 52 公里
    north = Ap("NOR", "XNOR", 20.0 + 300 / KM_PER_DEG_LAT, 130.0)  # 正北 300：偏心圓裡（245）
    south = Ap("SOU", "XSOU", 20.0 - 230 / KM_PER_DEG_LAT, 130.0)  # 正南 230：偏心圓外（285）
    assert _brief(stormentry.entries([s], [far, near, north, south])) == [
        # 距離 (3 - h/4)×104.5、半徑 100 + 8.33h：第 6.2 小時進入、第 23.2 小時離開
        ("FAR", "jma_storm_warning", False, _at(7), _at(24)),
        # 距離 (h/4 - 0.5)×104.5：第 8.6 小時離開
        ("NEA", "jma_storm_warning", True, None, _at(9)),
        ("NEA", "jma_storm", True, None, None),
        ("NEA", "jma_gale", True, None, None),
        ("NOR", "jma_gale", True, None, None),
    ]
    assert {e["source"] for e in stormentry.entries([s], [near])} == {"jma"}


def test_shape_units_and_eccentric():
    """只有海浬的換公里；`全域` 整圈；兩個相對方位是偏心圓；其他組合用最大的當整圈。"""
    p = {"lat": 20.0, "lon": 130.0}
    lat, lon, radii = stormentry.shape(p | {"x": [{"dir": "all", "nm": 100}]}, "x")
    assert (lat, lon, radii) == (20.0, 130.0, pytest.approx((185.2,) * 4))
    assert stormentry.shape(p | {"x": [{"dir": "all", "km": 90, "nm": 50}]}, "x")[2] == (90,) * 4
    assert stormentry.shape(p | {"x": []}, "x") is None
    lat, lon, radii = stormentry.shape(
        p | {"x": [{"dir": "SW", "km": 220}, {"dir": "NE", "km": 165}]}, "x"
    )
    assert radii == (192.5,) * 4
    assert round(stormentry.km_between(20.0, 130.0, lat, lon), 6) == 27.5
    assert 200 < stormentry.bearing(20.0, 130.0, lat, lon) < 250  # 往南西移
    odd = [{"dir": "N", "km": 300}, {"dir": "E", "km": 200}]
    assert stormentry.shape(p | {"x": odd}, "x") == (20.0, 130.0, (300,) * 4)


def test_eccentric_matches_jma_gale_warning_area():
    """實抓（2026-10-25 13:06Z 煙花 TC2637 實況強風域 `南西` 220 公里、`北東` 165 公里）：偏心圓的
    圓心和 JMA 自己 `forecast.json` 的 `galeWarningArea` 差 1 公里內；半徑 192.5 公里（JMA 用海浬
    算 (120＋90)÷2＝105 海浬＝194.46 公里，這裡照原文的公里）。"""
    raw = load_json("jma_typhoon_1306z.json")["TC2637"]
    infa = typhoon.parse_jma("TC2637", raw["specifications"], raw["forecast"])
    area = infa.now["jmaShapes"]["galeWarningArea"]
    lat, lon, radii = stormentry.shape(infa.now, "radius15")
    assert stormentry.km_between(lat, lon, *area["center"]) < 1
    assert radii == (192.5,) * 4
    assert abs(radii[0] - area["radius"] / 1000) < 2.5


def _jma_storm(key: str, lat: float, lon: float, category: str) -> Storm:
    now = _pt(0, lat, lon, 300, 100) | {"category": category}
    return Storm(
        source="jma",
        key=key,
        number=key[2:],
        name_zh="",
        name_en=key,
        issued_at=T0,
        now=now,
        forecast=[_pt(24, lat, lon + 1, [], [], 200) | {"category": category}],
        category=category,
    )


def test_build_entries_skip_ended_and_reuse_previous():
    """`typhoons.build`：`entries` 每報都有（沒給機場是 `[]`）；`ended`（日本氣象廳 `LOW`）不算；
    兩個來源都失敗沿用上一份 `storms` 時照沿用的那筆算，`stale` 了就不算。"""
    ap = Ap("TST", "XTST", 25.0, 130.0)
    live, low = _jma_storm("TC2698", 25.0, 130.0, "TY"), _jma_storm("TC2699", 25.0, 130.5, "LOW")
    now = T0 + timedelta(hours=1)
    doc = typhoons.build(None, TyphoonData([live, low], {}), OK, now, airports=[ap])
    assert [e["id"] for e in doc["ended"]] == ["2699"]
    assert _brief(doc["entries"]) == [
        ("TST", "jma_storm_warning", True, None, None),
        ("TST", "jma_storm", True, None, None),
        ("TST", "jma_gale", True, None, None),
    ]
    assert {e["stormId"] for e in doc["entries"]} == {"2698"}
    assert typhoons.build(None, TyphoonData([live], {}), OK, now)["entries"] == []
    failed = {"cwaTyphoon": {"ok": False}, "jmaTyphoon": {"ok": False}}
    again = typhoons.build(None, None, failed, now + timedelta(hours=1), doc, airports=[ap])
    assert (again["reusedFrom"], again["entries"]) == (doc["generatedAt"], doc["entries"])
    late = typhoons.build(None, None, failed, T0 + timedelta(hours=13), doc, airports=[ap])
    assert (late["storms"][0]["stale"], late["entries"]) == (True, [])


def test_real_1306z(airports):
    """實抓 2026-10-25 13:06Z：日本氣象廳煙花（TC2637）的暴風警戒域 117 小時那點（北緯 17.6、東經
    147.4、650 公里）蓋到關島，10-30 01Z 進入、預報範圍結束（06Z）還在圈內；薔琵（日本氣象廳 `LOW`）
    拿掉、不算。氣象署那份的薔琵單獨算（日本氣象廳當作失敗）：七級風在 10-26 00Z（18 小時那點，150
    公里）蓋到鹿兒島，24 小時那點沒有七級風（變性為溫帶氣旋）→ 沒有離開時間。"""
    cwa_raw, jma_raw = load_json("cwa_typhoon_1306z.json"), load_json("jma_typhoon_1306z.json")
    jma = [
        typhoon.parse_jma(tc, v["specifications"], v["forecast"])
        for tc, v in jma_raw.items()
        if tc != "targetTc"
    ]
    cwa = TyphoonData(typhoon.parse_cwa(cwa_raw), cwa_raw)
    at = utc(2026, 10, 25, 13, 6)
    doc = typhoons.build(cwa, TyphoonData(jma, jma_raw), OK, at, airports=airports)
    assert doc["entries"] == [
        {
            "iata": "GUM",
            "icao": "PGUM",
            "stormId": "2631",
            "source": "jma",
            "circle": "jma_storm_warning",
            "enterAt": "2026-10-30T01:00:00Z",
            "exitAt": None,
            "now": False,
            "issuedAt": "2026-10-25T10:10:00Z",
            "method": "linear_hourly",
        }
    ]
    status = {"cwaTyphoon": {"ok": True}, "jmaTyphoon": {"ok": False, "error": "timeout"}}
    only_cwa = typhoons.build(cwa, None, status, at, airports=airports)
    assert _brief(only_cwa["entries"]) == [("KOJ", "cwa_r15", False, "2026-10-26T00:00:00Z", None)]
    assert {e["stormId"] for e in only_cwa["entries"]} == {"cwa-ty29"}


def test_entries_failure_keeps_map(monkeypatch, caplog):
    """算進暴風圈時間出錯只 log、`entries` 是 `[]`，`storms` 照出。"""

    def boom(*a, **k):
        raise ZeroDivisionError

    monkeypatch.setattr(stormentry, "entries", boom)
    live = _jma_storm("TC2698", 25.0, 130.0, "TY")
    with caplog.at_level("ERROR", logger="hongthai"):
        doc = typhoons.build(None, TyphoonData([live], {}), OK, T0, airports=[AP])
    assert (len(doc["storms"]), doc["entries"]) == (1, [])
    assert any("進暴風圈" in r.getMessage() for r in caplog.records)
