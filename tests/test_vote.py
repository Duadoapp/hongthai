"""多模式投票（HD14，Shawn 2026-10-19 定案）。

某等級 L 的票＝等級 ≥ L 的模式數，票數 × 2 ≥ 分母就成立，取成立的最高；分母＝有資料的模式。
IFS 系集只投「高」（判中時不算分母）。
"""

from __future__ import annotations

import pytest

from hongthai.assess import fill_model_wx, model_entries, model_levels, model_vote, vote
from hongthai.config import MODELS, Thresholds

TH = Thresholds()


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


def entries(ec=None, gfs=None, aifs=None, aigfs=None, runs=None):
    ec, gfs = ec or {}, gfs or {}
    fill_model_wx(ec, gfs, TH)
    return model_entries(ec, gfs, {"aifs": aifs or {}, "aigfs": aigfs or {}}, runs or {}, TH)


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
            "levels",
            "level",
        }
        assert e["levels"] == {"wind": None, "rain": None, "snow": None, "fog": None}
        assert e["level"] is None and e["gustKt"] is None and e["gustEstimated"] is None
        assert e["windKt"] is None and e["gustFactor"] is None and e["gustFactorBasis"] is None
    cats, v = model_vote(es)
    assert v == {"total": 0, "high": 0, "medium": 0, "low": 0, "level": None, "thin": True}
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
    assert v == {"total": 5, "high": 2, "medium": 3, "low": 1, "level": "medium", "thin": False}


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
    assert snow == ["high", "low", None, "low", None]
    cats, _ = model_vote(es)
    assert cats["snow"] == "low"  # 高 1 × 2 < 3
    # AIFS 也判雪 → 2 × 2 ≥ 3 高
    es = entries(_ec(rain=12, ptype="snow"), _gfs(rain=1, ptype="rain"), _ai(rain=12, ptype="snow"))
    assert model_vote(es)[0]["snow"] == "high"


def test_fog_denominator_is_one():
    """霧只有 GFS 能見度：分母永遠是 1，它說了算（封頂在中，HD10）。"""
    es = entries(_ec(hres=5), _gfs(gust=5, vis=300), _ai(gust=5), _ai(gust=5))
    assert [e["levels"]["fog"] for e in es] == [None, "medium", None, None, None]
    cats, v = model_vote(es)
    assert cats["fog"] == "medium" and v["level"] == "medium"
    assert v["thin"] is False  # thin 看風的分母


def test_rain_ensemble_does_not_vote():
    """雨：IFS（HRES 雨量或系集 24 小時雨量機率，同 `ec.rain`）、GFS、AIFS、AIGFS 投；
    系集那筆不投。"""
    es = entries(_ec(rain=35), _gfs(rain=5), _ai(rain=40), _ai(rain=2))
    assert [e["levels"]["rain"] for e in es] == ["medium", "low", None, "medium", "low"]
    assert model_vote(es)[0]["rain"] == "medium"  # 中 2 × 2 ≥ 4


def test_thin_with_one_wind_model():
    es = entries(None, _gfs(gust=50))
    cats, v = model_vote(es)
    assert (cats["wind"], v["total"], v["thin"], v["level"]) == ("high", 1, True, "high")


@pytest.mark.parametrize(("gust", "level"), [(36.9, "low"), (37, "medium"), (48, "high")])
def test_estimated_gust_uses_model_thresholds(gust, level):
    es = entries(aifs=_ai(gust=gust))
    assert es[3]["levels"]["wind"] == level
