"""HD29：WMO SWIC 轉存的中國氣象局、韓國氣象廳、PAGASA 警報——只列出（low）、不升級。

樣本是 HD28 調查實抓的（`docs/surveys/samples/2026-10-22-cap/swic/`，2026-10-21 17:52Z 前後）。
"""

from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from conftest import ROOT, utc

from hongthai import assess, build
from hongthai.config import load_airports
from hongthai.sources import swic

SAMPLES = ROOT / "docs" / "surveys" / "samples" / "2026-10-22-cap" / "swic"
NOW = utc(2026, 10, 21, 18, 0)
WENZHOU = "cn-cma-xx/2026/10/21/01/35/00-a6e3df0a2f11cf6b3c4fa5510bb70f17.xml"
GUANGDE = "cn-cma-xx/2026/10/21/17/37/34-35ebfa152439c99abc6164972198f19.xml"
KR_WIND = "kr-kma-weather-en/2026/10/21/15/00/00-75d3564d185d9b181d02b50b11e1c24b.xml"
PH_TCWS2 = "ph-pagasa-en/2026/10/21/14/43/05-5ef42418fa2806173b6dc93c8d5b199c.xml"


def cap(name: str) -> str:
    return (SAMPLES / "cap" / name).read_text("utf-8")


WENZHOU_XML = cap("cn-wenzhou-gale-yellow.xml")
GUANGDE_XML = cap("cn-guangde-dense-fog-yellow.xml")
KR_XML = cap("kr-strongwind-advisory-change.xml")
PH_XML = cap("ph-tcws2-batanes.xml")


@pytest.fixture(scope="module")
def ap():
    return {a.iata: a for a in load_airports(ROOT / "airports.json")}


def wmo_all() -> dict:
    return json.loads((SAMPLES / "wmo_all-cn-kr-ph.json").read_text("utf-8"))


def parse(xml: str, source: str, now=NOW):
    return swic.parse_cap(xml, source, now, "x.xml")


def kinds(alerts, airport):
    return [w.kind for w in swic.for_airport(alerts, airport)]


# ---- 清單：篩種類與發布台 ----


def test_list_filter_real_sample(ap):
    airports = [a for a in ap.values() if swic.SOURCES & set(a.warning_sources)]
    cities, issuers = swic.cn_prefixes(airports)
    assert cities == {
        "3101", "3301", "3302", "3303", "3501", "3502", "3505",
        "4452", "4403", "4401", "4404", "4601", "4602",
    }  # fmt: skip
    assert {"310000", "330000", "350000", "440000", "460000", "000000"} <= issuers
    picked = [i for i in wmo_all()["items"] if swic._wanted(i, cities, issuers, NOW)]
    by = {}
    for i in picked:
        by.setdefault(i["mid"], []).append(i)
    # 中國：浙江沿海那排大風（溫州市台與轄下縣市台、寧波北侖、象山）；廣德大霧（安徽）不抓
    assert {i["id"][:6] for i in by["001"]} == {
        "330300", "330327", "330326", "330305", "330381", "330383", "330382", "330206", "330225",
    }  # fmt: skip
    assert {i["event"] for i in by["001"]} == {"gale"}
    assert GUANGDE not in {i["url"] for i in picked}
    # 韓國：強風注意報抓、風浪注意報不抓
    assert [i["url"] for i in by["095"]] == [KR_WIND]
    # 菲律賓：風球 6 則都抓（清單的 expires 都還沒到）、淹水的 GFA 不抓
    assert len(by["021"]) == 6
    assert {i["event"] for i in by["021"]} == {"Tropical Cyclone Warning"}
    # 清單的 expires 已過的不抓
    late = utc(2026, 10, 21, 20, 55)
    assert len([i for i in by["021"] if swic._wanted(i, cities, issuers, late)]) == 2


# ---- 中國 ----


def test_cn_wenzhou_gale_yellow_hits_wnz_only(ap):
    a = parse(WENZHOU_XML, "cma")
    assert (a.kind, a.family, a.code, a.areas) == (
        "cma_gale_yellow",
        "cma_gale",
        "gale",
        ("330303003000",),
    )
    assert a.issued_at == "2026-10-21T01:35:00Z"
    assert kinds([a], ap["WNZ"]) == ["cma_gale_yellow"]
    for iata in ("NGB", "HGH", "PVG", "FOC", "CAN"):  # 同省別市、別省都不中
        assert kinds([a], ap[iata]) == []
    w = swic.for_airport([a], ap["WNZ"])[0]
    assert (w.source, w.level, w.code) == ("cma", "low", "gale")
    assert w.detail == "温州市气象台发布大风黄色预警[Ⅲ级/较重]"
    assert w.text == {
        "zh-TW": "溫州市氣象臺發布大風黃色預警[Ⅲ級/較重]（中國氣象局，經 WMO SWIC）",
        "zh-HK": "温州市氣象台發佈大風黃色預警[Ⅲ級/較重]（中國氣象局，經 WMO SWIC）",
        "zh-CN": "温州市气象台发布大风黄色预警[Ⅲ级/较重]（中国气象局，经 WMO SWIC）",
        "en": "Wenzhou Meteorological Observatory issues a yellow warning for strong winds "
        "[Level III/Severe] (CMA via WMO SWIC)",
    }


@pytest.mark.parametrize(
    ("code", "hits"),
    [
        ("330300000000", {"WNZ"}),  # 溫州市（地市級）
        ("330000000000", {"WNZ", "HGH", "NGB"}),  # 浙江省
        ("310115007000", {"PVG"}),  # 浦東新區的街道
        ("310112000000", {"SHA"}),  # 虹橋跨兩區
        ("440114000000", {"CAN"}),
        ("445202000000", {"SWA"}),
        ("440300000000", {"SZX"}),
        ("330302000000", set()),  # 溫州鹿城區：同市別區不中
    ],
)
def test_cn_area_codes(ap, code, hits):
    a = parse(WENZHOU_XML.replace("330303003000", code), "cma")
    cn = [x for x in ap.values() if "cma" in x.warning_sources]
    assert {x.iata for x in cn if kinds([a], x)} == hits


def test_cn_fog_yellow_not_listed_orange_is(ap):
    a = parse(GUANGDE_XML, "cma")
    assert (a.kind, a.family) == (None, "cma_fog")  # 大霧黃色不收
    orange = GUANGDE_XML.replace("黄色", "橙色").replace("yellow", "orange")
    orange = orange.replace("341882102000", "440306000000")  # 搬到寶安區
    a = parse(orange, "cma")
    assert a.kind == "cma_fog_orange"
    assert kinds([a], ap["SZX"]) == ["cma_fog_orange"]
    assert swic.for_airport([a], ap["SZX"])[0].text["zh-TW"] == (
        "廣德市氣象臺發布大霧橙色預警[III級/較重]（中國氣象局，經 WMO SWIC）"
    )


@pytest.mark.parametrize(
    ("zh", "en", "kind"),
    [
        ("台风", "typhoon", "cma_typhoon_blue"),
        ("大风", "gale", None),  # 大風藍色不收
        ("暴雨", "Rainstorm", None),  # 暴雨藍色不收
    ],
)
def test_cn_blue(zh, en, kind):
    xml = WENZHOU_XML.replace("<event>大风</event>", f"<event>{zh}</event>")
    xml = xml.replace("<event>gale</event>", f"<event>{en}</event>").replace("黄色", "蓝色")
    a = parse(xml, "cma")
    assert a.kind == kind


def test_cn_without_zh_info_uses_english():
    xml = WENZHOU_XML[: WENZHOU_XML.index("<info>\n\t\t<language>zh-CN")] + "</alert>"
    xml = xml.replace("yellow", "orange")
    a = parse(xml, "cma")
    assert (a.kind, a.headline_zh) == ("cma_gale_orange", "")
    tx = swic.text_for(a, None)
    assert tx["zh-TW"] == "大風橙色預警（中國氣象局，經 WMO SWIC）"
    assert tx["zh-CN"] == "大风橙色预警（中国气象局，经 WMO SWIC）"


def test_cn_lift_expired_cancel_not_actual(ap):
    a = parse(WENZHOU_XML, "cma")
    lift = parse(
        WENZHOU_XML.replace("发布大风", "解除大风")
        .replace("issues a yellow", "lifts the yellow")
        .replace("2026-10-21T09:35:00+08:00</sent>", "2026-10-21T20:00:00+08:00</sent>"),
        "cma",
    )
    assert (lift.kind, lift.family) == (None, "cma_gale")
    assert kinds([a, lift], ap["WNZ"]) == []  # 解除比較新：不列
    assert kinds([lift], ap["WNZ"]) == []
    # 過期
    assert parse(WENZHOU_XML, "cma", utc(2026, 10, 24, 2)) is None
    # Cancel 也只拿來蓋掉舊的
    cancel = parse(WENZHOU_XML.replace("<msgType>Alert", "<msgType>Cancel"), "cma")
    assert cancel.kind is None
    # 演習、測試
    assert parse(WENZHOU_XML.replace("<status>Actual", "<status>Exercise"), "cma") is None
    # 其他種類（寒潮）不要
    other = WENZHOU_XML.replace("<event>大风</event>", "<event>寒潮</event>")
    assert parse(other.replace("<event>gale</event>", "<event>cold wave</event>"), "cma") is None


def test_cn_same_family_latest(ap):
    yellow = parse(WENZHOU_XML, "cma")
    orange = parse(
        WENZHOU_XML.replace("黄色", "橙色")
        .replace("yellow", "orange")
        .replace("2026-10-21T09:35:00+08:00</sent>", "2026-10-21T15:00:00+08:00</sent>"),
        "cma",
    )
    assert kinds([yellow, orange], ap["WNZ"]) == ["cma_gale_orange"]
    assert kinds([orange, yellow], ap["WNZ"]) == ["cma_gale_orange"]
    # 降級成藍色（不收）：較新的藍色蓋掉黃色
    blue = parse(
        WENZHOU_XML.replace("黄色", "蓝色")
        .replace("yellow", "blue")
        .replace("2026-10-21T09:35:00+08:00</sent>", "2026-10-21T15:00:00+08:00</sent>"),
        "cma",
    )
    assert kinds([yellow, blue], ap["WNZ"]) == []
    # 不同種類各自列
    fog = parse(
        GUANGDE_XML.replace("黄色", "红色")
        .replace("yellow", "red")
        .replace("341882102000", "330303000000"),
        "cma",
    )
    assert kinds([yellow, fog], ap["WNZ"]) == ["cma_fog_red", "cma_gale_yellow"]


# ---- 韓國 ----


def test_kr_strong_wind_advisory_polygon(ap):
    a = parse(KR_XML, "kma")
    assert (a.kind, a.family, a.code) == (
        "kma_strong_wind_advisory",
        "kma_strong_wind",
        "StrongWind Advisory Change",
    )
    assert a.issued_at == "2026-10-21T15:00:00Z" and len(a.polygons) == 1
    for iata in ("CJU", "PUS", "ICN", "GMP"):  # 黑山島、紅島：我們的機場都不在
        assert kinds([a], ap[iata]) == []
    # 把濟州搬到多邊形裡、邊界外 4 公里、外 6 公里
    cju = ap["CJU"]
    assert kinds([a], replace(cju, lat=34.680, lon=125.375)) == ["kma_strong_wind_advisory"]
    east = 125.396122 + 4 / (111.32 * 0.8222)  # 最東的頂點往東 4 公里
    assert kinds([a], replace(cju, lat=34.691703, lon=east)) == ["kma_strong_wind_advisory"]
    east = 125.396122 + 6 / (111.32 * 0.8222)
    assert kinds([a], replace(cju, lat=34.691703, lon=east)) == []
    w = swic.for_airport([a], replace(cju, lat=34.680, lon=125.375))[0]
    assert w.level == "low" and w.detail == "StrongWind Advisory Change"
    assert w.text == {
        "zh-TW": "韓國氣象廳強風注意報（濟州，經 WMO SWIC）",
        "zh-HK": "韓國氣象廳強風注意報（濟州，經 WMO SWIC）",
        "zh-CN": "韩国气象厅强风注意报（济州，经 WMO SWIC）",
        "en": "StrongWind Advisory Change (KMA via WMO SWIC)",
    }


def test_kr_distance():
    square = ((0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0))
    assert swic.distance_km(0.5, 0.5, square) == 0
    assert swic.distance_km(0.5, 1.1, square) == pytest.approx(11.13, abs=0.05)
    assert swic.distance_km(-0.1, 0.5, square) == pytest.approx(11.06, abs=0.05)


@pytest.mark.parametrize(
    ("event", "kind", "family"),
    [
        ("StrongWind Warning", "kma_strong_wind_warning", "kma_strong_wind"),
        ("Strong Wind Warning Change", "kma_strong_wind_warning", "kma_strong_wind"),
        ("StrongWind Advisory Clear", None, "kma_strong_wind"),
        ("StrongWind Advisory Release", None, "kma_strong_wind"),
        ("Typhoon Warning", "kma_typhoon_warning", "kma_typhoon"),
        ("Typhoon Advisory Issue", "kma_typhoon_advisory", "kma_typhoon"),
        ("HeavyRain Warning", "kma_heavy_rain_warning", "kma_heavy_rain"),
        ("HeavyRain Advisory", None, "kma_heavy_rain"),  # 豪雨注意報不收
        ("HeavySnow Warning Change", "kma_heavy_snow_warning", "kma_heavy_snow"),
        ("HeavySnow Advisory", None, "kma_heavy_snow"),
    ],
)
def test_kr_events(event, kind, family):
    a = parse(KR_XML.replace("StrongWind Advisory Change</event>", f"{event}</event>"), "kma")
    assert (a.kind, a.family) == (kind, family)


def test_kr_other_events_and_clear(ap):
    for event in ("Wind Wave Advisory", "ColdWave Advisory", "Wind Wave Advisory Clear"):
        xml = KR_XML.replace("StrongWind Advisory Change</event>", f"{event}</event>")
        assert parse(xml, "kma") is None
    old = parse(KR_XML, "kma")
    clear = parse(
        KR_XML.replace(
            "StrongWind Advisory Change</event>", "StrongWind Advisory Clear</event>"
        ).replace("2026-10-22T00:00:00+09:00</sent>", "2026-10-22T03:00:00+09:00</sent>"),
        "kma",
    )
    inside = replace(ap["CJU"], lat=34.680, lon=125.375)
    assert kinds([old, clear], inside) == []
    # 過期（KST 06:00）
    assert parse(KR_XML, "kma", utc(2026, 10, 21, 21, 0)) is None


# ---- 菲律賓 ----


def test_ph_tcws2_batanes(ap):
    a = parse(PH_XML, "pagasa")
    assert (a.kind, a.family, a.code, a.areas) == (
        "pagasa_tcws_2",
        "pagasa_tcws",
        "Tropical Cyclone Warning",
        ("020900000",),
    )
    assert a.issued_at == "2026-10-21T14:43:05Z"
    for iata in ("MNL", "CEB", "CRK"):
        assert kinds([a], ap[iata]) == []
    basco = replace(ap["MNL"], psgc_areas=("020900000",))
    w = swic.for_airport([a], basco)[0]
    assert (w.kind, w.level) == ("pagasa_tcws_2", "low")
    assert w.detail == "Tropical Cyclone Warning : Super Typhoon Rosal (CHAMPI) Signal #2"
    assert w.text == {
        "zh-TW": "菲律賓 PAGASA 熱帶氣旋 2 號風球（馬尼拉，經 WMO SWIC）",
        "zh-HK": "菲律賓 PAGASA 熱帶氣旋 2 號風球（馬尼拉，經 WMO SWIC）",
        "zh-CN": "菲律宾 PAGASA 热带气旋 2 号风球（马尼拉，经 WMO SWIC）",
        "en": "Tropical Cyclone Warning : Super Typhoon Rosal (CHAMPI) Signal #2 "
        "(PAGASA via WMO SWIC)",
    }
    # 換到 MNL 的省碼（馬尼拉大都會第 4 區）就中
    a = parse(PH_XML.replace("020900000", "137600000"), "pagasa")
    assert kinds([a], ap["MNL"]) == ["pagasa_tcws_2"]


def test_ph_signal_from_headline_and_latest(ap):
    no_param = PH_XML.replace(swic.PH_SIGNAL_PARAM, "something else")
    assert parse(no_param.replace("Signal #2", "Signal #4"), "pagasa").kind == "pagasa_tcws_4"
    assert parse(no_param.replace("Signal #2", "Signal"), "pagasa") is None
    # 過期（PHT 10:42）
    assert parse(PH_XML, "pagasa", utc(2026, 10, 22, 3)) is None
    # 同一省降成 1 號：取最新那則
    two = parse(PH_XML.replace("020900000", "137600000"), "pagasa")
    one = parse(
        PH_XML.replace("020900000", "137600000")
        .replace("<value>2</value>", "<value>1</value>")
        .replace("2026-10-21T22:43:05+08:00</sent>", "2026-10-22T04:43:05+08:00</sent>"),
        "pagasa",
    )
    assert one.kind == "pagasa_tcws_1"
    assert kinds([two, one], ap["MNL"]) == ["pagasa_tcws_1"]


def test_ph_rainfall_red_guess(ap):
    xml = PH_XML.replace("<event>Tropical Cyclone Warning", "<event>Heavy Rainfall Warning")
    xml = xml.replace(
        "Tropical Cyclone Warning : Super Typhoon Rosal (CHAMPI) Signal #2",
        "Heavy Rainfall Warning No. 3: RED Warning",
    ).replace("020900000", "137600000")
    a = parse(xml, "pagasa")
    assert (a.kind, a.family) == ("pagasa_rainfall_red", "pagasa_rainfall")
    w = swic.for_airport([a], ap["MNL"])[0]
    assert w.text["zh-TW"] == "菲律賓 PAGASA 豪雨紅色警報（馬尼拉，經 WMO SWIC）"
    assert w.text["zh-CN"] == "菲律宾 PAGASA 暴雨红色警报（马尼拉，经 WMO SWIC）"
    assert parse(xml.replace("RED Warning", "ORANGE Warning"), "pagasa") is None


# ---- 種類、等級 ----


def test_all_kinds_low_and_causes():
    assert set(swic.KINDS.values()) == {"low"}
    assert len(swic.KINDS) == 4 + 3 + 2 + 2 + 6 + 5 + 1
    rain = {"cma_rainstorm_red", "cma_rainstorm_orange", "kma_heavy_rain_warning"}
    for k in swic.KINDS:
        want = (
            "rain"
            if k in rain or k == "pagasa_rainfall_red"
            else "fog"
            if k.startswith("cma_fog")
            else "snow"
            if k == "kma_heavy_snow_warning"
            else "wind"
        )
        assert assess.warning_cause(k) == want, k


def test_only_sources_the_airport_has(ap):
    a = parse(WENZHOU_XML, "cma")
    assert kinds([a], replace(ap["WNZ"], warning_sources=())) == []
    assert kinds([a], replace(ap["WNZ"], warning_sources=("kma",))) == []


# ---- 抓（不連網） ----


def fake_http(caps: dict[str, str], fail_list=False, calls=None):
    def http_get(url, **kw):
        if calls is not None:
            calls.append((url, kw.get("timeout")))
        if url == swic.URL:
            if fail_list:
                raise swic.SwicError("down", "timeout")
            return SimpleNamespace(json=wmo_all, content=b"{}")
        key = url.removeprefix("https://severeweather.wmo.int/v2/cap-alerts/")
        if key not in caps:
            raise swic.SwicError("404", "http_404")
        return SimpleNamespace(content=caps[key].encode("utf-8"))

    return http_get


def test_fetch_with_samples(ap, monkeypatch):
    calls = []
    caps = {WENZHOU: WENZHOU_XML, KR_WIND: KR_XML, PH_TCWS2: PH_XML}
    monkeypatch.setattr(swic, "http_get", fake_http(caps, calls=calls))
    airports = list(ap.values())
    data = swic.fetch(airports, NOW)
    # 中國 9 則＋韓國 1＋菲律賓 6，每個 URL 一次；沒有原文的那幾則記在 cap_errors
    assert data.caps == 16
    assert len(calls) == 17 and len({u for u, _ in calls}) == 17
    assert calls[0] == (swic.URL, swic.LIST_TIMEOUT)
    assert {t for _, t in calls[1:]} == {swic.CAP_TIMEOUT}
    assert set(data.cap_errors) == set(data.raw["capErrors"]) and len(data.cap_errors) == 13
    assert sorted(a.kind for a in data.alerts) == [
        "cma_gale_yellow",
        "kma_strong_wind_advisory",
        "pagasa_tcws_2",
    ]
    assert data.raw["caps"] == caps
    assert {i["mid"] for i in data.raw["wmoAll"]["items"]} == {"001", "095", "021"}
    assert len(data.raw["wmoAll"]["items"]) == 355
    hit = {a.iata: kinds(data.alerts, a) for a in airports if kinds(data.alerts, a)}
    assert hit == {"WNZ": ["cma_gale_yellow"]}


def test_fetch_list_failure_and_no_airports(ap, monkeypatch):
    monkeypatch.setattr(swic, "http_get", fake_http({}, fail_list=True))
    with pytest.raises(swic.SwicError) as e:
        swic.fetch(list(ap.values()), NOW)
    assert e.value.code == "timeout"
    with pytest.raises(swic.SwicError) as e:
        swic.fetch([ap["TPE"], ap["HKG"]], NOW)
    assert e.value.code == "no_area"


def test_build_call_records_failure(ap, monkeypatch):
    monkeypatch.setattr(swic, "http_get", fake_http({}, fail_list=True))
    status: dict = {}
    assert build._call("swic", lambda: swic.fetch(list(ap.values()), NOW), status) is None
    assert status["swic"]["ok"] is False and status["swic"]["error"] == "timeout"
    monkeypatch.setattr(swic, "http_get", fake_http({WENZHOU: WENZHOU_XML}))
    sw = build._call(
        "swic", lambda: swic.fetch(list(ap.values()), NOW), status, extra=build._swic_extra
    )
    assert sw is not None
    assert (status["swic"]["ok"], status["swic"]["caps"], status["swic"]["capErrors"]) == (
        True,
        16,
        15,
    )
