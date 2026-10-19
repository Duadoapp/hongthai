"""TAF／METAR 的能見度、天氣現象、雲底解析（HD8）。fixture 是 `data` 分支的真實快照片段。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hongthai.sources import taf

FIXTURE = Path(__file__).parent / "fixtures" / "taf_metar_wx_20261018.json"


@pytest.fixture(scope="module")
def raw() -> dict:
    return json.loads(FIXTURE.read_text("utf-8"))


@pytest.mark.parametrize(
    ("visib", "meters"),
    [
        ("6+", 9999),  # 公制 9999 解碼成這個
        ("10+", 9999),  # 美國站 10SM 以上
        ("P6SM", 9999),
        (4.97, 7997),  # 8000 公尺
        (0.75, 1207),  # 1200 公尺
        (0.5, 805),
        (2, 3218),
        ("1/2", 805),
        ("1 1/2", 2414),
        ("M1/4", 402),
        ("", None),  # TEMPO 沒報能見度
        (None, None),
        ("abc", None),
        (True, None),
    ],
)
def test_vis_m(visib, meters):
    assert taf.vis_m(visib) == meters


def test_wx_tokens():
    assert taf.wx_tokens("-SHRA BR") == ("-SHRA", "BR")
    assert taf.wx_tokens("+tsra") == ("+TSRA",)
    assert taf.wx_tokens(None) == ()
    assert taf.wx_tokens("") == ()


def test_ceiling_lowest_bkn_ovc_or_vertvis():
    clouds = [
        {"cover": "FEW", "base": 300},
        {"cover": "SCT", "base": 800},
        {"cover": "BKN", "base": 1500},
        {"cover": "OVC", "base": 1200},
    ]
    assert taf.ceiling_ft(clouds, None) == 1200  # FEW／SCT 不算雲幕
    assert taf.ceiling_ft(clouds, 200) == 200  # 垂直能見度比較低
    assert taf.ceiling_ft([{"cover": "OVX", "base": 100}], None) == 100
    assert taf.ceiling_ft([{"cover": "FEW", "base": 100}], None) is None
    assert taf.ceiling_ft([], None) is None
    assert taf.ceiling_ft(None, 300) == 300


def test_real_taf_periods(raw):
    vvts = taf.parse_tafs(raw["taf"])["VVTS"]
    main, tempo_shra, tempo_ts = vvts.periods
    # 主時段 9999 SCT020
    assert (main.vis_m, main.wx, main.ceiling_ft) == (9999, (), None)
    # TEMPO 5000 SHRA BKN015 FEW017CB
    assert (tempo_shra.vis_m, tempo_shra.wx, tempo_shra.ceiling_ft) == (5004, ("SHRA",), 1500)
    # TEMPO 15015G28KT 1200 +TSRA BKN015 SCT017CB BKN040
    assert (tempo_ts.vis_m, tempo_ts.wx, tempo_ts.ceiling_ft) == (1207, ("+TSRA",), 1500)
    # 原本的欄位不變
    assert (tempo_ts.kind, tempo_ts.wind_kt, tempo_ts.gust_kt, tempo_ts.wdir) == (
        "tempo",
        15,
        28,
        150,
    )


def test_real_taf_tempo_without_visibility(raw):
    rctp = taf.parse_tafs(raw["taf"])["RCTP"]
    tempo = next(p for p in rctp.periods if p.kind == "tempo")
    # TEMPO 1820/1901 12005KT：只改風，能見度是空字串、沒有雲
    assert (tempo.vis_m, tempo.wx, tempo.ceiling_ft) == (None, (), None)
    assert rctp.periods[0].ceiling_ft == 3200  # FEW015 BKN032


def test_real_metars(raw):
    metars = taf.parse_metars(raw["metar"])
    rjfk = metars["RJFK"]  # 9999 BCFG FEW001
    assert (rjfk.vis_m, rjfk.wx, rjfk.ceiling_ft) == (9999, ("BCFG",), None)
    pgum = metars["PGUM"]  # 10SM BKN017 OVC022
    assert (pgum.vis_m, pgum.wx, pgum.ceiling_ft) == (9999, (), 1700)
