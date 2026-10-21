"""HD27：日本氣象廳暴風、大雨警報與氣象署陸上強風特報——只列出（low）、不升級。"""

from __future__ import annotations

from conftest import load_json, utc

from hongthai.assess import RAIN_WARNING_KINDS, warning_cause
from hongthai.config import JmaArea
from hongthai.sources import cwa, jma

NAHA = JmaArea("471000", "4720100", "那覇市", "Naha City")
URASOE = JmaArea("471000", "4720800", "浦添市", "Urasoe City")
TOMIGUSUKU = JmaArea("471000", "4721200", "豊見城市", "Tomigusuku City")
ITOMAN = JmaArea("471000", "4721000", "糸満市", "Itoman City")
NANJO = JmaArea("471000", "4721500", "南城市", "Nanjo City")


def _kinds(ws):
    return [(w.kind, w.level, w.code) for w in ws]


def _report(code: str, issued: str, rows: dict[str, list[dict]], info: str = "発表") -> dict:
    return {
        "reportDatetime": issued,
        "infoType": info,
        "dataTypeCode": code,
        "warning": {"class20Items": [{"areaCode": a, "kinds": kinds} for a, kinds in rows.items()]},
    }


def _office() -> list[dict]:
    """手造的沖繩本島 office（471000）：大雨（VPWW55）、風（VPWW58）、波浪（VPWW59）電文。"""
    return [
        _report(
            "VPWW55",
            "2026-10-22T05:00:00+09:00",
            {
                NAHA.class20: [{"code": "03", "status": "発表"}],  # 大雨警報
                URASOE.class20: [{"code": "43", "status": "発表"}],  # 大雨危険警報
                TOMIGUSUKU.class20: [{"code": "33", "status": "発表"}],  # 大雨特別警報
                ITOMAN.class20: [{"code": "10", "status": "発表"}],  # 大雨注意報：不列
                NANJO.class20: [{"code": "03", "status": "解除"}],  # 解除：不列
            },
        ),
        # 舊的大雨電文：被上面那筆整份取代
        _report(
            "VPWW55",
            "2026-10-22T03:00:00+09:00",
            {ITOMAN.class20: [{"code": "33", "status": "発表"}]},
        ),
        _report(
            "VPWW58",
            "2026-10-22T05:00:00+09:00",
            {
                NAHA.class20: [{"code": "05", "status": "継続"}],  # 暴風警報
                URASOE.class20: [{"code": "35", "status": "発表"}],  # 暴風特別警報
                TOMIGUSUKU.class20: [{"code": "15", "status": "発表"}],  # 強風注意報：不列
                ITOMAN.class20: [{"code": "05", "status": "解除"}],  # 解除：不列
                NANJO.class20: [{"status": "発表警報・注意報はなし"}],
            },
        ),
        _report(
            "VPWW59",
            "2026-10-22T05:00:00+09:00",
            {a.class20: [{"code": "07", "status": "発表"}] for a in (NAHA, ITOMAN)},  # 波浪警報
        ),
        # 取消的那筆不算
        _report(
            "VPWW58",
            "2026-10-22T06:00:00+09:00",
            {NANJO.class20: [{"code": "35", "status": "発表"}]},
            info="取消",
        ),
    ]


# ---- JMA 暴風、大雨 ----


def test_storm_and_heavy_rain_only_listed_kinds_on_the_right_row():
    doc = _office()
    assert _kinds(jma.parse_area(doc, NAHA)) == [
        ("jma_heavy_rain", "low", "03"),
        ("jma_storm", "low", "05"),
    ]
    assert _kinds(jma.parse_area(doc, URASOE)) == [
        ("jma_heavy_rain_danger", "low", "43"),
        ("jma_storm_emergency", "low", "35"),
    ]
    # 強風注意報（15）不列
    assert _kinds(jma.parse_area(doc, TOMIGUSUKU)) == [
        ("jma_heavy_rain_emergency", "low", "33"),
    ]
    # 大雨注意報、暴風解除、波浪警報、舊電文的大雨特別警報都不列
    assert jma.parse_area(doc, ITOMAN) == []
    # 解除、なし、取消的那筆都不算
    assert jma.parse_area(doc, NANJO) == []
    assert all(w.issued_at == "2026-10-21T20:00:00Z" for w in jma.parse_area(doc, NAHA))


def test_storm_and_heavy_rain_text_four_languages():
    assert jma.text_for("jma_storm", NAHA) == {
        "zh-TW": "日本氣象廳暴風警報（那覇市）",
        "zh-HK": "日本氣象廳暴風警報（那覇市）",
        "zh-CN": "日本气象厅暴风警报（那覇市）",
        "en": "JMA storm warning (Naha)",
    }
    assert jma.text_for("jma_storm_emergency", NAHA) == {
        "zh-TW": "日本氣象廳暴風特別警報（那覇市）",
        "zh-HK": "日本氣象廳暴風特別警報（那覇市）",
        "zh-CN": "日本气象厅暴风特别警报（那覇市）",
        "en": "JMA storm emergency warning (Naha)",
    }
    assert jma.text_for("jma_heavy_rain", NAHA) == {
        "zh-TW": "日本氣象廳大雨警報（那覇市）",
        "zh-HK": "日本氣象廳大雨警報（那覇市）",
        "zh-CN": "日本气象厅大雨警报（那覇市）",
        "en": "JMA heavy rain warning (Naha)",
    }
    assert jma.text_for("jma_heavy_rain_danger", NAHA) == {
        "zh-TW": "日本氣象廳大雨危險警報（那覇市）",
        "zh-HK": "日本氣象廳大雨危險警報（那覇市）",
        "zh-CN": "日本气象厅大雨危险警报（那覇市）",
        "en": "JMA heavy rain danger warning (Naha)",
    }
    assert jma.text_for("jma_heavy_rain_emergency", NAHA) == {
        "zh-TW": "日本氣象廳大雨特別警報（那覇市）",
        "zh-HK": "日本氣象廳大雨特別警報（那覇市）",
        "zh-CN": "日本气象厅大雨特别警报（那覇市）",
        "en": "JMA heavy rain emergency warning (Naha)",
    }


def test_new_kinds_are_all_low_and_causes():
    for code in ("05", "35", "03", "43", "33"):
        assert jma.CODES[code][1] == "low"
    for kind in ("jma_heavy_rain", "jma_heavy_rain_danger", "jma_heavy_rain_emergency"):
        assert kind in RAIN_WARNING_KINDS and warning_cause(kind) == "rain"
    for kind in ("jma_storm", "jma_storm_emergency", "cwa_strong_wind"):
        assert warning_cause(kind) == "wind"


def test_real_29w_naha_wave_warning_not_listed():
    # 2026-10-22 02:53（日本時間）實抓：那霸是強風注意報（15）、波浪警報（07）、雷注意報（14），
    # 警報地圖的紅色是波浪警報，這支不接
    assert jma.parse_area(load_json("jma_r8_471000_29w.json"), NAHA) == []


# ---- 氣象署陸上強風特報 ----

NOW = utc(2026, 10, 21, 18)  # 台灣 10/22 02:00


def _hazards(*locs: tuple[str, str, str]) -> dict:
    """(縣市, phenomena, endTime) → 手造的 `W-C0033-001` 回應。"""
    return {
        "records": {
            "location": [
                {
                    "locationName": name,
                    "hazardConditions": {
                        "hazards": [
                            {
                                "info": {"phenomena": phen, "significance": "特報"},
                                "validTime": {"startTime": "2026-10-21 22:17:00", "endTime": end},
                            }
                        ]
                        if phen
                        else []
                    },
                }
                for name, phen, end in locs
            ]
        }
    }


def test_strong_wind_county_with_and_without(airports):
    by = {a.icao: a for a in airports}
    data = _hazards(
        ("高雄市", "陸上強風", "2026-10-22 23:00:00"),
        ("花蓮縣", "", ""),
        ("臺東縣", "陸上強風", "2026-10-21 23:00:00"),  # 已經過了
        ("金門縣", "濃霧", "2026-10-22 23:00:00"),
    )
    hz = cwa.parse_hazards(data, NOW)
    (w,) = cwa.strong_wind_for_airport(hz, by["RCKH"].cwa_areas)
    assert (w.kind, w.level, w.detail, w.issued_at) == (
        "cwa_strong_wind",
        "low",
        "陸上強風",
        "2026-10-21T14:17:00Z",
    )
    assert w.text == {
        "zh-TW": "中央氣象署陸上強風特報（高雄市）",
        "zh-HK": "中央氣象署陸上強風特報（高雄市）",
        "zh-CN": "中央气象署陆上强风特报（高雄市）",
        "en": "CWA land strong wind advisory (Kaohsiung)",
    }
    for icao in ("RCYU", "RCFN", "RCBS", "RCTP"):
        assert cwa.strong_wind_for_airport(hz, by[icao].cwa_areas) == []
    # 其他特報的函式不受影響
    assert cwa.heavy_rain_for_airport(hz, by["RCKH"].cwa_areas, by["RCKH"].name) == []


def test_strong_wind_real_29w(airports):
    # 2026-10-21 17:22Z 實抓：南投縣、嘉義市以外全部有陸上強風特報 → 台灣十個機場都列出一則
    hz = cwa.parse_hazards(load_json("cwa_w-c0033-001_strong_wind.json"), NOW)
    by = {a.icao: a for a in airports}
    got = {
        a.icao: w.text["zh-TW"]
        for a in airports
        if a.region == "taiwan"
        for w in cwa.strong_wind_for_airport(hz, a.cwa_areas)
    }
    assert got == {
        "RCTP": "中央氣象署陸上強風特報（桃園市、臺北市、新北市）",
        "RCSS": "中央氣象署陸上強風特報（桃園市、臺北市、新北市）",
        "RCKH": "中央氣象署陸上強風特報（高雄市）",
        "RCMQ": "中央氣象署陸上強風特報（臺中市）",
        "RCNN": "中央氣象署陸上強風特報（臺南市）",
        "RCYU": "中央氣象署陸上強風特報（花蓮縣）",
        "RCFN": "中央氣象署陸上強風特報（臺東縣）",
        "RCQC": "中央氣象署陸上強風特報（澎湖縣）",
        "RCBS": "中央氣象署陸上強風特報（金門縣）",
        "RCFG": "中央氣象署陸上強風特報（連江縣）",
    }
    (w,) = cwa.strong_wind_for_airport(hz, by["RCTP"].cwa_areas)
    assert w.text["zh-CN"] == "中央气象署陆上强风特报（桃园市、台北市、新北市）"
    assert w.text["en"] == "CWA land strong wind advisory (Taoyuan, Taipei, New Taipei)"
    (w,) = cwa.strong_wind_for_airport(hz, by["RCFG"].cwa_areas)
    assert w.text["en"] == "CWA land strong wind advisory (Lienchiang)"
    # 陸上強風不是大豪雨、濃霧
    assert all(
        cwa.heavy_rain_for_airport(hz, a.cwa_areas, a.name) == []
        and cwa.dense_fog_for_airport(hz, a.cwa_areas, a.name) == []
        for a in airports
        if a.region == "taiwan"
    )
