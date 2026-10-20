"""日本氣象廳（JMA）大雪警報（HD9）：防災 JSON `warning/data/r8/<office>.json` 的解析與請求。"""

from __future__ import annotations

import pytest
from conftest import load_json

from hongthai.config import JmaArea
from hongthai.sources import jma

CHITOSE = JmaArea("016000", "0122400", "千歳市", "Chitose City")
SAPPORO = JmaArea("016000", "0110000", "札幌市", "Sapporo City")
EBETSU = JmaArea("016000", "0121700", "江別市", "Ebetsu City")
ENIWA = JmaArea("016000", "0123100", "恵庭市", "Eniwa City")
ISHIGAKI = JmaArea("474000", "4720700", "石垣市", "Ishigaki City")


def _kinds(ws):
    return [(w.kind, w.level, w.code, w.issued_at) for w in ws]


def test_real_response_no_snow_warnings():
    # 2026-10-20 實抓：千歲市當時有濃霧注意報（20）、土砂的注意報已解除（29），都不是要的種類
    doc = load_json("jma_r8_016000_none.json")
    assert {r["dataTypeCode"] for r in doc} == {"VPWW55", "VPWW56", "VPWW58", "VPWW59", "VPWW61"}
    for area in (CHITOSE, SAPPORO, EBETSU, ENIWA):
        assert jma.parse_area(doc, area) == []
    assert jma.parse_area(load_json("jma_r8_474000_none.json"), ISHIGAKI) == []


def test_snow_warnings_only_three_kinds_on_the_right_row():
    doc = load_json("jma_r8_016000_snow.json")
    # 千歲：大雪警報（雪的電文）＋暴風雪警報（風的電文），中的在前；取消的那筆不算
    assert _kinds(jma.parse_area(doc, CHITOSE)) == [
        ("jma_heavy_snow", "medium", "06", "2026-12-10T07:40:00Z"),
        ("jma_snowstorm", "low", "02", "2026-12-10T07:40:00Z"),
    ]
    # 札幌：雪的電文舊的那筆是大雪警報、新的那筆整份取代成大雪特別警報；風雪注意報（13）不列
    assert _kinds(jma.parse_area(doc, SAPPORO)) == [
        ("jma_heavy_snow_emergency", "high", "36", "2026-12-10T07:40:00Z"),
    ]
    # 江別：大雪注意報（12）、風雪注意報（13）不列
    assert jma.parse_area(doc, EBETSU) == []
    # 惠庭：舊的那筆發布大雪警報，新的那筆解除 → 不算
    assert jma.parse_area(doc, ENIWA) == []


def test_text_four_languages():
    (w, _) = jma.parse_area(load_json("jma_r8_016000_snow.json"), CHITOSE)
    assert w.text == {
        "zh-TW": "日本氣象廳大雪警報（千歳市）",
        "zh-HK": "日本氣象廳大雪警報（千歳市）",
        "zh-CN": "日本气象厅大雪警报（千歳市）",
        "en": "JMA heavy snow warning (Chitose)",
    }
    assert jma.text_for("jma_heavy_snow_emergency", SAPPORO) == {
        "zh-TW": "日本氣象廳大雪特別警報（札幌市）",
        "zh-HK": "日本氣象廳大雪特別警報（札幌市）",
        "zh-CN": "日本气象厅大雪特别警报（札幌市）",
        "en": "JMA heavy snow emergency warning (Sapporo)",
    }
    assert jma.text_for("jma_snowstorm", JmaArea("130000", "1311100", "大田区", "Ota City")) == {
        "zh-TW": "日本氣象廳暴風雪警報（大田区）",
        "zh-HK": "日本氣象廳暴風雪警報（大田区）",
        "zh-CN": "日本气象厅暴风雪警报（大田区）",
        "en": "JMA snowstorm warning (Ota)",
    }
    assert jma.en_name("Tajiri Town") == "Tajiri"
    assert jma.en_name("Ishigaki") == "Ishigaki"


def test_old_format_rejected():
    # 2026-05-28 以前的格式（`areaTypes`）：最上層是 dict，當格式錯誤
    with pytest.raises(jma.JmaError) as e:
        jma.parse_area({"reportDatetime": "2026-05-28T04:03:00+09:00", "areaTypes": []}, CHITOSE)
    assert e.value.code == "bad_format"


class _Resp:
    def __init__(self, doc):
        self.doc = doc

    def json(self):
        return self.doc


def test_fetch_one_request_per_office(monkeypatch):
    docs = {
        "016000": load_json("jma_r8_016000_snow.json"),
        "474000": load_json("jma_r8_474000_none.json"),
    }
    asked = []

    def fake_get(url, **kw):
        asked.append(url)
        return _Resp(docs[url.rsplit("/", 1)[-1].removesuffix(".json")])

    monkeypatch.setattr(jma, "http_get", fake_get)
    data = jma.fetch([CHITOSE, ISHIGAKI, SAPPORO, EBETSU])
    assert asked == [
        "https://www.jma.go.jp/bosai/warning/data/r8/016000.json",
        "https://www.jma.go.jp/bosai/warning/data/r8/474000.json",
    ]
    assert set(data.raw) == {"016000", "474000"}
    assert [w.kind for w in data.warnings["0122400"]] == ["jma_heavy_snow", "jma_snowstorm"]
    assert data.warnings["4720700"] == [] and data.warnings["0121700"] == []
    assert [w.code for w in data.warnings["0110000"]] == ["36"]


def test_fetch_without_areas():
    with pytest.raises(jma.JmaError) as e:
        jma.fetch([])
    assert e.value.code == "no_area"


def test_bad_json(monkeypatch):
    class Bad:
        def json(self):
            raise ValueError("not json")

    monkeypatch.setattr(jma, "http_get", lambda url, **kw: Bad())
    with pytest.raises(jma.JmaError) as e:
        jma.fetch([CHITOSE])
    assert e.value.code == "bad_json"
