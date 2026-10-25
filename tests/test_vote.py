"""多模式投票（HD14，Shawn 2026-10-19 定案；HD16 加 ICON、JMA GSM、WeatherNext 2 系集成 8 票）。

某等級 L 的票＝等級 ≥ L 的模式數，票數 × 2 ≥ 分母就成立，取成立的最高；分母＝有資料的模式。
IFS 系集、WN2 系集只投「高」（判中時不算分母）；旁觀模式（`voting=False`）哪一輪都不算。
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from hongthai import assess
from hongthai.assess import fill_model_wx, model_entries, model_levels, model_vote, tally, vote
from hongthai.config import MODELS, Thresholds

TH = Thresholds()
OBS = [None] * 3  # HD33b：三個旁觀模式（gem、arpege、cma）沒給資料


def test_vote_two_models_one_high_is_high():
    """2 票 1 高 1 低 → 高（和 HD14 以前兩個模式取較高一致）。"""
    assert vote(["high", "low"]) == "high"
    assert vote(["medium", "low"]) == "medium"


def test_vote_three_models_one_high_two_medium():
    """高 1 × 2 < 3 不成立；中 3 × 2 ≥ 3 成立 → 中。"""
    assert vote(["high", "medium", "medium"]) == "medium"


def test_vote_four_models_two_high():
    assert vote(["high", "high", "low", "low"]) == "high"
    assert vote(["high", "medium", "low", "low"]) == "medium"  # 中 2 × 2 ≥ 4
    assert vote(["high", "low", "low", "low"]) == "low"


def test_vote_ensemble_low_does_not_drag_medium():
    """3 個模式 2 中 1 低＋系集低 → 中：判中時系集不算分母（2 × 2 ≥ 3）。"""
    assert vote(["medium", "medium", "low", "low"], [False, False, False, True]) == "medium"
    # 系集若算分母就是 2 × 2 ≥ 4 也成立；換成 1 中看得出差別：1 × 2 < 4 但 1 × 2 < 3 也不成立
    assert vote(["medium", "low", "low", "low"], [False, False, False, True]) == "low"
    assert vote(["medium", "low", "low"], [False, False, True]) == "medium"  # 1 × 2 ≥ 2


def test_vote_ensemble_alone_cannot_make_high():
    """IFS 低、GFS 低、系集 p49Kt ≥ 30% 投高 → 3 票 1 高：1 × 2 < 3 不成立；中（系集不算）0 票 →
    低。這是規則的結果：系集單獨撐不起高（HD14 以前系集 ≥ 30% 就是高）。"""
    assert vote(["low", "low", "high"], [False, False, True]) == "low"
    # 有一個確定性模式也投高就成立：2 × 2 ≥ 3
    assert vote(["high", "low", "high"], [False, False, True]) == "high"


def test_vote_single_model_decides_and_empty():
    assert vote([None, "medium", None]) == "medium"
    assert vote(["high"]) == "high"
    assert vote([None, None]) is None
    assert vote([]) is None
    # 只有系集有資料：高照投；低時中那一輪沒有分母，落到低
    assert vote([None, "low"], [False, True]) == "low"
    assert vote([None, "high"], [False, True]) == "high"


# ---- 用 models[] 投（每個模式的整理與 `model.vote`）----


def _ec(hres=None, p49=None, rain=None, ptype=None, xw=None):
    return {"hresGustKt": hres, "p49Kt": p49, "rain6hMm": rain, "ptype": ptype, "crosswindKt": xw}


def _gfs(gust=None, rain=None, ptype=None, vis=None, xw=None):
    return {"gustKt": gust, "rain6hMm": rain, "ptype": ptype, "visibilityM": vis, "crosswindKt": xw}


def _ai(gust=None, rain=None, ptype=None, xw=None):
    return {"gustKt": gust, "crosswindKt": xw, "rain6hMm": rain, "ptype": ptype}


def entries(ec=None, gfs=None, aifs=None, aigfs=None, runs=None, icon=None, jma=None, wn2=None):
    ec, gfs = ec or {}, gfs or {}
    fill_model_wx(ec, gfs, TH)
    others = {"aifs": aifs or {}, "aigfs": aigfs or {}, "icon": icon or {}, "jma": jma or {}}
    return model_entries(ec, gfs, {**others, "wn2-ens": wn2 or {}}, runs or {}, TH)


def test_entries_in_config_order_with_nulls():
    es = entries()
    assert (
        [e["id"] for e in es]
        == [m.id for m in MODELS]
        == [
            "ifs",
            "gfs",
            "ifs-ens",
            "aifs",
            "aigfs",
            "icon",  # HD16
            "jma",
            "wn2-ens",
            "gem",  # HD33b：旁觀
            "arpege",
            "cma",
        ]
    )
    for e in es:
        assert set(e) == {
            "id",
            "run",
            "windKt",  # HD18
            "gustKt",
            "gustEstimated",
            "gustFactor",  # HD18
            "gustFactorBasis",  # HD18
            "crosswindKt",
            "rain6hMm",
            "ptype",
            "visibilityM",
            "p49Kt",  # HD16
            "levels",
            "level",
        }
        assert e["levels"] == {"wind": None, "rain": None, "snow": None, "fog": None}
        assert e["level"] is None and e["gustKt"] is None and e["gustEstimated"] is None
        assert e["windKt"] is None and e["gustFactor"] is None and e["gustFactorBasis"] is None
        assert e["p49Kt"] is None
    cats, v = model_vote(es)
    assert v == {
        "total": 0,
        "high": 0,
        "medium": 0,
        "mediumTotal": 0,  # HD24
        "low": 0,
        "level": None,
        "thin": True,
    }
    assert model_levels(es) is None


def test_five_models_vote_json():
    es = entries(
        _ec(hres=50, p49=0.4),  # 高、系集高
        _gfs(gust=40),  # 中
        _ai(gust=43.4),  # 中（估算）
        _ai(gust=20),  # 低
        runs={"ifs": "2026-10-19T12:00:00Z", "aifs": "2026-10-19T12:00:00Z"},
    )
    by = {e["id"]: e for e in es}
    assert [by[i]["levels"]["wind"] for i in ("ifs", "gfs", "ifs-ens", "aifs", "aigfs")] == [
        "high",
        "medium",
        "high",
        "medium",
        "low",
    ]
    assert (by["ifs"]["run"], by["gfs"]["run"]) == ("2026-10-19T12:00:00Z", None)
    assert (by["ifs"]["gustEstimated"], by["aifs"]["gustEstimated"]) == (False, True)
    # 系集那筆：數字全 null，只有風的等級
    ens = by["ifs-ens"]
    assert ens["gustKt"] is None and ens["gustEstimated"] is None
    assert ens["levels"] == {"wind": "high", "rain": None, "snow": None, "fog": None}
    cats, v = model_vote(es)
    # 高 2 × 2 < 5；中（系集不算）3 × 2 ≥ 4 → 中
    assert cats["wind"] == "medium"
    assert v == {
        "total": 5,
        "high": 2,
        "medium": 3,
        "mediumTotal": 4,
        "low": 1,
        "level": "medium",
        "thin": False,
    }


def test_snow_denominator_excludes_aigfs():
    """雪只讓有降水型態的模式投：IFS、GFS、AIFS；AIGFS 沒有型態，雪的等級是 None。"""
    es = entries(
        _ec(rain=12, ptype="snow"),  # 雪 高
        _gfs(rain=1, ptype="rain"),  # 雪 低
        _ai(rain=1, ptype="rain"),  # 雪 低
        _ai(rain=12),  # 沒有型態
    )
    by = {e["id"]: e for e in es}
    assert by["aigfs"]["levels"]["snow"] is None
    assert by["aigfs"]["levels"]["rain"] == "low"
    snow = [e["levels"]["snow"] for e in es]
    assert snow == ["high", "low", None, "low", None, None, None, None, *OBS]
    cats, _ = model_vote(es)
    assert cats["snow"] == "low"  # 高 1 × 2 < 3
    # AIFS 也判雪 → 2 × 2 ≥ 3 高
    es = entries(_ec(rain=12, ptype="snow"), _gfs(rain=1, ptype="rain"), _ai(rain=12, ptype="snow"))
    assert model_vote(es)[0]["snow"] == "high"


def test_fog_denominator_is_one():
    """霧只有 GFS 能見度：分母永遠是 1，它說了算（封頂在中，HD10）。"""
    es = entries(_ec(hres=5), _gfs(gust=5, vis=300), _ai(gust=5), _ai(gust=5))
    assert [e["levels"]["fog"] for e in es] == [None, "medium", *[None] * 6, *OBS]
    cats, v = model_vote(es)
    assert cats["fog"] == "medium" and v["level"] == "medium"
    assert v["thin"] is False  # thin 看風的分母


def test_rain_ensemble_does_not_vote():
    """雨：IFS（HRES 雨量或系集 24 小時雨量機率，同 `ec.rain`）、GFS、AIFS、AIGFS 投；
    系集那筆不投。"""
    es = entries(_ec(rain=35), _gfs(rain=5), _ai(rain=40), _ai(rain=2))
    assert [e["levels"]["rain"] for e in es] == [
        "medium",
        "low",
        None,
        "medium",
        "low",
        *[None] * 3,
        *OBS,
    ]
    assert model_vote(es)[0]["rain"] == "medium"  # 中 2 × 2 ≥ 4


def test_thin_with_one_wind_model():
    es = entries(None, _gfs(gust=50))
    cats, v = model_vote(es)
    assert (cats["wind"], v["total"], v["thin"], v["level"]) == ("high", 1, True, "high")


@pytest.mark.parametrize(("gust", "level"), [(36.9, "low"), (37, "medium"), (48, "high")])
def test_estimated_gust_uses_model_thresholds(gust, level):
    es = entries(aifs=_ai(gust=gust))
    assert es[3]["levels"]["wind"] == level


# ---- HD16：8 票、WN2 系集只投高、旁觀模式 ----


def _wn2(p49=None, wind=None, gust=None):
    return {
        "windKt": wind,
        "gustKt": gust,
        "gustFactor": 1.5,
        "gustFactorBasis": "run",
        "p49Kt": p49,
    }


def test_eight_models_vote():
    """風：IFS 高、GFS 中、IFS 系集高、AIFS 中、AIGFS 低、ICON 低、JMA 中（估算）、WN2 系集高。
    高 3 × 2 < 8；中那一輪兩個系集不算：6 個裡 4 個 ≥ 中 → 中。"""
    kw = {
        "ec": _ec(hres=50, p49=0.4),
        "gfs": _gfs(gust=40),
        "aifs": _ai(gust=43.4),
        "aigfs": _ai(gust=20),
        "jma": _ai(gust=40, rain=1, ptype="rain"),
        "wn2": _wn2(p49=0.5, wind=31, gust=46.5),
    }
    es = entries(**kw, icon=_ai(gust=30, rain=2, ptype="rain"))
    assert [e["levels"]["wind"] for e in es] == [
        "high",
        "medium",
        "high",
        "medium",
        "low",
        "low",
        "medium",
        "high",
        *OBS,
    ]
    cats, v = model_vote(es)
    assert v == {
        "total": 8,
        "high": 3,
        "medium": 4,
        "mediumTotal": 6,  # HD24：兩個系集不算判中的分母
        "low": 2,
        "level": "medium",
        "thin": False,
    }
    assert tally(es, "wind", "high") == (3, 8) and tally(es, "wind", "medium") == (4, 6)
    # ICON 也高 → 4 × 2 ≥ 8 → 高
    es = entries(**kw, icon=_ai(gust=50))
    assert model_vote(es)[1]["level"] == "high"
    by = {e["id"]: e for e in es}
    assert (by["icon"]["gustEstimated"], by["jma"]["gustEstimated"]) == (False, True)


def test_wn2_votes_only_high():
    """WN2 系集比照 IFS 系集：`p49Kt`（成員比例）≥ 30% 投高、否則投低，不投雨、雪、霧；數字是中位數
    成員的估算陣風。"""
    es = entries(wn2=_wn2(p49=0.3, wind=31.0, gust=46.5))
    w = next(e for e in es if e["id"] == "wn2-ens")
    assert w["levels"] == {"wind": "high", "rain": None, "snow": None, "fog": None}
    assert (w["windKt"], w["gustKt"], w["gustEstimated"], w["p49Kt"]) == (31.0, 46.5, True, 0.3)
    assert (w["gustFactor"], w["gustFactorBasis"]) == (1.5, "run")
    assert (w["crosswindKt"], w["rain6hMm"], w["ptype"], w["visibilityM"]) == (None,) * 4
    assert entries(wn2=_wn2(p49=0.29))[7]["levels"]["wind"] == "low"
    # 其他筆的 `p49Kt` 都是 null（IFS 系集的機率在 model.ec）
    assert [e["p49Kt"] for e in entries(_ec(p49=0.5), wn2=_wn2(p49=0.4))] == [
        *[None] * 7,
        0.4,
        *OBS,
    ]
    # 判中時不算分母：GFS 中、ICON 低、WN2 低 → 中那一輪 1 × 2 ≥ 2
    es = entries(gfs=_gfs(gust=40), icon=_ai(gust=20), wn2=_wn2(p49=0.1))
    assert model_vote(es)[1] == {
        "total": 3,
        "high": 0,
        "medium": 1,
        "mediumTotal": 2,
        "low": 2,
        "level": "medium",
        "thin": False,
    }


def test_three_absent_same_as_five_votes():
    """Open-Meteo 失敗（三筆全 null）→ 投票結果和只有 5 票時一樣。"""
    kw = {
        "ec": _ec(hres=50, p49=0.4, rain=35),
        "gfs": _gfs(gust=40, vis=300),
        "aifs": _ai(gust=43.4),
    }
    es = entries(**kw, aigfs=_ai(gust=20))
    assert all(e["level"] is None for e in es[5:])
    five = [e["levels"] for e in es[:5]]
    only_high = [False, False, True, False, False]
    expected = {c: vote([lv[c] for lv in five], only_high) for c in ("wind", "rain", "snow", "fog")}
    cats, v = model_vote(es)
    assert cats == expected
    assert v == {
        "total": 5,
        "high": 2,
        "medium": 3,
        "mediumTotal": 4,  # HD24：三票缺席，判中的分母跟著少（8 票時是 6）
        "low": 1,
        "level": "medium",
        "thin": False,
    }


def test_vote_skips_non_voting():
    """`voting` 為假的模式哪一輪都不算（不在分母、也不算票）。"""
    assert vote(["high", "low", "low"]) == "low"
    assert vote(["high", "low", "low"], voting=[True, True, False]) == "high"  # 1 × 2 ≥ 2
    assert vote(["high"], voting=[False]) is None


def test_non_voting_model_listed_but_not_counted(monkeypatch):
    """旁觀模式（HD16 的開關；HD15 的 WN3 會用）：`models[]` 照寫、等級照算，但不投票、
    `vote.total` 不含它。這裡把 ICON 暫時改成旁觀。"""
    monkeypatch.setattr(
        assess, "MODELS", tuple(replace(m, voting=False) if m.id == "icon" else m for m in MODELS)
    )
    es = entries(gfs=_gfs(gust=20), aifs=_ai(gust=20), icon=_ai(gust=60, rain=70, ptype="rain"))
    icon = next(e for e in es if e["id"] == "icon")
    assert icon["levels"]["wind"] == "high" and icon["levels"]["rain"] == "high"
    cats, v = model_vote(es)
    assert (cats["wind"], cats["rain"]) == ("low", None)
    assert v == {
        "total": 2,
        "high": 0,
        "medium": 0,
        "mediumTotal": 2,  # HD24：旁觀的 ICON 不算
        "low": 2,
        "level": "low",
        "thin": False,
    }
    assert tally(es, "wind", "high") == (0, 2)
    assert assess.non_voting() == {"icon", "gem", "arpege", "cma"}  # HD33b 的三個


def test_observer_does_not_judge_fog_hd33b():
    """HD33b：旁觀模式不判霧——CMA 能見度 200 公尺（投票模式會是霧「中」），那筆 `levels.fog` 還是
    null、`level` 照風與雨算（低）；`visibilityM` 照存。投票模式（這裡把 ICON 給同樣的能見度）
    照判。"""
    low_vis = {"gustKt": 20.0, "crosswindKt": 5.0, "rain6hMm": 0.0, "ptype": "none"}
    es = model_entries(
        {},
        {},
        {"icon": {**low_vis, "visibilityM": 200.0}, "cma": {**low_vis, "visibilityM": 200.0}},
        {},
        TH,
    )
    by = {e["id"]: e for e in es}
    assert by["icon"]["levels"]["fog"] == "medium"  # 投票模式照判（HD16 的規則不變）
    cma = by["cma"]
    assert cma["visibilityM"] == 200.0
    assert cma["levels"] == {"wind": "low", "rain": "low", "snow": "low", "fog": None}
    assert cma["level"] == "low"


# ---- HD24：判中的分母 `mediumTotal` ----


def test_medium_total_excludes_only_high_ensembles():
    """8 票含兩個只投高的系集：`total` 8、`mediumTotal` 6（＝`tally` 判中那一輪的分母）。"""
    es = entries(
        _ec(hres=50, p49=0.4),
        _gfs(gust=40),
        _ai(gust=43.4),
        _ai(gust=20),
        icon=_ai(gust=30),
        jma=_ai(gust=40),
        wn2=_wn2(p49=0.5, wind=31, gust=46.5),
    )
    _, v = model_vote(es)
    assert (v["total"], v["medium"], v["mediumTotal"]) == (8, 4, 6)
    assert tally(es, "wind", "medium") == (v["medium"], v["mediumTotal"])
    assert list(v) == ["total", "high", "medium", "mediumTotal", "low", "level", "thin"]


def test_medium_total_equals_total_without_ensembles():
    """兩個系集都沒資料 → `mediumTotal` ＝ `total`。"""
    es = entries(_ec(hres=50), _gfs(gust=40), _ai(gust=43.4), _ai(gust=20), icon=_ai(gust=30))
    by = {e["id"]: e for e in es}
    assert by["ifs-ens"]["levels"]["wind"] is None and by["wn2-ens"]["levels"]["wind"] is None
    _, v = model_vote(es)
    assert v["total"] == v["mediumTotal"] == 5


def test_medium_total_skips_non_voting(monkeypatch):
    """旁觀模式不算進 `mediumTotal`（也不算進 `total`）。"""
    monkeypatch.setattr(
        assess, "MODELS", tuple(replace(m, voting=False) if m.id == "jma" else m for m in MODELS)
    )
    es = entries(
        _ec(hres=50, p49=0.4),
        _gfs(gust=40),
        icon=_ai(gust=30),
        jma=_ai(gust=40),
        wn2=_wn2(p49=0.1),
    )
    _, v = model_vote(es)
    assert (v["total"], v["mediumTotal"]) == (5, 3)  # ifs、gfs、icon
