"""等級規則：每條規則一個 case。風速一律用節（HD2）。"""

from __future__ import annotations

import math
from datetime import timedelta

import pytest
from conftest import utc

from hongthai.assess import (
    MODEL_CAUSE_ORDER,
    ActiveWarning,
    GustFactor,
    assess_slots,
    causes_from,
    crosswind_kt,
    crosswind_level,
    fill_kt,
    max_level,
    model_level,
    refactor_estimated,
    taf_for_slot,
    taf_level,
    warning_cause,
)
from hongthai.config import ConfirmedPeriod, Runway, Thresholds
from hongthai.grib import wind_dir_from_uv
from hongthai.sources import swic
from hongthai.sources.aifs import AifsStep
from hongthai.sources.aigfs import AigfsStep
from hongthai.sources.ecmwf import EcmwfPoint, GustInterval, PrecipStep, ProbWindow
from hongthai.sources.gfs import GustPoint
from hongthai.sources.taf import Metar, TafPeriod
from hongthai.timeutil import slot_bounds

TH = Thresholds()
NOW = utc(2026, 10, 18, 8, 10)
SLOTS = slot_bounds(NOW)
S0 = SLOTS[0][0]  # 2026-10-18T06:00Z


def ec(p10=None, p29=None, p49=None, hres=None):
    """`hres` 是 HRES 陣風（節）；`p29`／`p49` 是系集陣風 ≥ 29／49 節的機率。"""
    return {"p10": p10, "p29Kt": p29, "p37Kt": None, "p49Kt": p49, "hresGustKt": hres}


def gfs(g=None):
    return {"gustKt": g}


def warn(level, kind="tc_signal", source="hko"):
    return ActiveWarning(source, kind, level, {"en": kind}, None)


def flat_ec(hres: float, p15: float = 0.0, p25: float = 0.0) -> EcmwfPoint:
    """整段 120 小時都一樣的 EC 資料（陣風是節）。"""
    hres_list = [
        GustInterval(S0 + timedelta(hours=h - 3), S0 + timedelta(hours=h), hres)
        for h in range(3, 121, 3)
    ]
    ens = [
        ProbWindow(S0 + timedelta(hours=s), S0 + timedelta(hours=s + 24), 1.0, p15, p25)
        for s in range(-12, 120, 12)
    ]
    return EcmwfPoint(hres_list, ens)


def flat_gfs(g: float) -> list[GustPoint]:
    """陣風是節。"""
    return [GustPoint(S0 + timedelta(hours=h), g) for h in range(0, 121, 6)]


def run(**kw):
    args = dict(
        now=NOW,
        slots=SLOTS,
        thresholds=TH,
        ec=flat_ec(5),
        gfs=flat_gfs(5),
        taf_periods=None,
        warnings=[],
        confirmed=[],
    )
    args.update(kw)
    return assess_slots(**args)


# ---- 時間格 ----


def test_slots_start_at_floor_and_cover_120h():
    assert len(SLOTS) == 20
    assert SLOTS[0][0] == utc(2026, 10, 18, 6)
    assert SLOTS[-1][1] == utc(2026, 10, 23, 6)


# ---- 模式規則 ----


def test_default_thresholds_in_knots():
    assert TH == Thresholds(
        model_medium_gust_kt=37,
        model_high_gust_kt=48,
        taf_medium_gust_kt=37,
        taf_high_gust_kt=48,
        taf_high_wind_kt=35,
        crosswind_medium_kt=27,
        crosswind_high_kt=33,
        ec_p49_high=0.3,
    )


def test_model_high_by_ec_p49():
    assert model_level(ec(p49=0.30), gfs(5), TH) == "high"
    assert model_level(ec(p49=0.29), gfs(5), TH) == "low"


def test_model_high_by_hres_gust():
    assert model_level(ec(hres=48.0), gfs(5), TH) == "high"
    assert model_level(ec(hres=47.9), gfs(5), TH) == "medium"


def test_model_high_by_gfs_gust():
    assert model_level(ec(hres=5), gfs(48.0), TH) == "high"


def test_model_medium_does_not_use_ensemble():
    # ECMWF 沒有 ≥ 37 節的機率；≥ 29 節的機率再高也不進規則
    assert model_level(ec(p10=1.0, p29=1.0, p49=0.29, hres=30), gfs(30), TH) == "low"


def test_model_medium_by_any_gust():
    assert model_level(ec(hres=37.0), gfs(3), TH) == "medium"
    assert model_level(ec(hres=3), gfs(37.0), TH) == "medium"
    assert model_level(ec(hres=36.9), gfs(36.9), TH) == "low"


def test_model_low_and_missing():
    assert model_level(ec(p10=0.9, p29=0.1, p49=0, hres=24), gfs(29), TH) == "low"
    assert model_level(ec(), gfs(), TH) is None


def test_ec_slot_uses_hres_max_and_min_of_containing_windows():
    point = EcmwfPoint(
        hres=[
            GustInterval(S0, S0 + timedelta(hours=3), 20.0),
            GustInterval(S0 + timedelta(hours=3), S0 + timedelta(hours=6), 37.04),
            GustInterval(S0 + timedelta(hours=6), S0 + timedelta(hours=9), 60.0),
        ],
        ens=[
            ProbWindow(S0 - timedelta(hours=12), S0 + timedelta(hours=12), 0.9, 0.6, 0.2),
            ProbWindow(S0, S0 + timedelta(hours=24), 0.8, 0.4, 0.35),
            ProbWindow(S0 + timedelta(hours=12), S0 + timedelta(hours=36), 1, 1, 1),
        ],
    )
    s = run(ec=point, gfs=None)[0]
    assert s["model"]["ec"] == {
        "p10": 0.8,
        "p15": 0.4,
        "p25": 0.2,
        "p29Kt": 0.4,  # ＝p15（15 m/s ≈ 29.2 節）
        "p37Kt": None,  # 沒有來源
        "p49Kt": 0.2,  # ＝p25（25 m/s ≈ 48.6 節）
        "hresGustMs": 19.1,  # 37.04 節換回 m/s
        "hresGustKt": 37.0,
        "crosswindKt": None,
        # HD8：沒有降水資料時都是 None
        "rain6hMm": None,
        "ptype": None,
        "p24hRain25": None,
        "p24hRain50": None,
        "temp2mC": None,
        "rain": None,
        "snow": None,
    }
    assert s["model"]["level"] == "medium"


def test_gfs_slot_outputs_knots_and_ms():
    s = run(gfs=flat_gfs(50.0))[0]
    assert s["model"]["gfs"] == {
        "gustMs": 25.7,
        "gustKt": 50.0,
        "crosswindKt": None,
        # HD8：沒有降水與能見度時都是 None
        "rain6hMm": None,
        "ptype": None,
        "visibilityM": None,
        "rain": None,
        "snow": None,
        "fog": None,
    }


def test_fill_kt_from_ms_fields():
    """HD2 以前的結果（只有 m/s 欄位）被沿用時補節的欄位。"""
    e = {"p10": 0.9, "p15": 0.6, "p25": 0.3, "hresGustMs": 25.0, "crosswindKt": 1.0}
    g = {"gustMs": 19.0, "crosswindKt": 2.0}
    fill_kt(e, g)
    assert (e["hresGustKt"], e["p29Kt"], e["p37Kt"], e["p49Kt"]) == (48.6, 0.6, None, 0.3)
    assert g["gustKt"] == 36.9
    # 已經有節的欄位就不動
    e2 = {"p15": 0.6, "p29Kt": 0.5, "hresGustMs": 25.0, "hresGustKt": 48.5}
    fill_kt(e2, {})
    assert (e2["p29Kt"], e2["hresGustKt"]) == (0.5, 48.5)


# ---- 官方規則 ----


def test_hko_signal8_high_signal3_medium():
    assert run(warnings=[warn("high")])[0]["official"]["level"] == "high"
    s = run(warnings=[warn("medium")])[0]
    assert s["official"]["level"] == "medium"
    assert s["official"]["kind"] == "warning"
    assert s["official"]["warnings"] == ["tc_signal"]


def test_cwa_land_in_zone_high_sea_medium():
    s = run(warnings=[warn("high", "typhoon_land", "cwa")])[0]
    assert (s["level"], s["basis"]) == ("high", "official")
    s = run(warnings=[warn("medium", "typhoon_sea", "cwa")])[0]
    assert s["level"] == "medium"


def test_warning_only_applies_to_first_12_hours():
    slots = run(warnings=[warn("high")])
    assert [s["official"] is not None for s in slots[:4]] == [True, True, True, False]


def taf(kind, wind, gust, start_h=0, end_h=6):
    return TafPeriod(
        S0 + timedelta(hours=start_h), S0 + timedelta(hours=end_h), kind, 90, wind, gust
    )


def test_taf_gust48_high():
    assert taf_for_slot([taf("main", 20, 48)], NOW, *SLOTS[0], TH)["level"] == "high"
    assert taf_for_slot([taf("main", 20, 47)], NOW, *SLOTS[0], TH)["level"] == "medium"


def test_taf_wind35_high():
    assert taf_for_slot([taf("main", 35, None)], NOW, *SLOTS[0], TH)["level"] == "high"


def test_taf_gust37_medium_and_kind_of_worst_period():
    o = taf_for_slot([taf("main", 15, None), taf("tempo", 25, 38, 2, 4)], NOW, *SLOTS[0], TH)
    assert o == {
        "windKt": 25,
        "gustKt": 38,
        "kind": "tempo",
        "level": "medium",
        "crosswindKt": None,
    }


def test_taf_prob_period_counts():
    o = taf_for_slot([taf("main", 10, None), taf("prob30", 30, 50, 1, 3)], NOW, *SLOTS[0], TH)
    assert (o["kind"], o["level"]) == ("prob30", "high")


def test_taf_below_threshold_low_and_no_overlap_none():
    assert taf_for_slot([taf("main", 20, 36)], NOW, *SLOTS[0], TH)["level"] == "low"
    assert taf_for_slot([taf("main", 20, 36, 6, 12)], NOW, *SLOTS[0], TH) is None


# ---- 0–30 小時官方優先 ----


def test_official_overrides_model_within_30h():
    periods = [taf("main", 10, None, 0, 30)]
    # HD14 投票：IFS、GFS 都高（系集低）模式層才是高
    slots = run(ec=flat_ec(50), gfs=flat_gfs(50), taf_periods=periods)
    s = slots[0]
    assert (s["level"], s["basis"]) == ("low", "official")
    assert s["model"]["level"] == "high"


def test_after_30h_only_model():
    periods = [taf("main", 10, None, 0, 120)]  # 就算 TAF 很長，超過 30 小時也不看
    slots = run(ec=flat_ec(40), taf_periods=periods)
    # 現在 08:10，+30h = 隔天 14:10 → 開始時間 < 14:10 的格（前 6 格）是官方
    assert [s["basis"] for s in slots[:7]] == ["official"] * 6 + ["model"]
    assert slots[6]["official"] is None
    assert slots[6]["level"] == "medium"


def test_no_official_data_falls_back_to_model():
    s = run(ec=flat_ec(40), taf_periods=None)[0]
    assert (s["level"], s["basis"], s["official"]) == ("medium", "model", None)


def test_no_data_at_all_unknown():
    s = run(ec=None, gfs=None)[0]
    assert (s["level"], s["basis"]) == ("unknown", "none")
    assert s["model"]["level"] is None


# ---- 落差 ----


def test_gap_when_official_and_model_differ():
    slots = run(ec=flat_ec(50), taf_periods=[taf("main", 10, None, 0, 30)])
    assert slots[0]["gap"] is True


def test_no_gap_when_same_or_no_official():
    slots = run(ec=flat_ec(5), taf_periods=[taf("main", 10, None, 0, 30)])
    assert slots[0]["gap"] is False
    assert slots[10]["gap"] is False


# ---- 一致性 ----


def test_agreement_same_class_agree():
    s = run(ec=flat_ec(40), gfs=flat_gfs(47.9))[0]
    assert s["model"]["agreement"] == "agree"


def test_agreement_different_class_disagree():
    s = run(ec=flat_ec(40), gfs=flat_gfs(36.9))[0]
    assert s["model"]["agreement"] == "disagree"


def test_agreement_missing_model_none():
    assert run(gfs=None)[0]["model"]["agreement"] is None


# ---- 已確認 ----


def test_confirmed_overrides_everything():
    c = ConfirmedPeriod("VHHH", S0 + timedelta(hours=7), S0 + timedelta(hours=8), {"en": "x"})
    slots = run(confirmed=[c], warnings=[warn("high")])
    assert (slots[1]["level"], slots[1]["basis"]) == ("confirmed", "confirmed")
    assert slots[0]["level"] == "high"
    assert slots[3]["level"] == "low"  # 警報只套到現在 + 12 小時


# ---- 側風 ----

RWY_05 = (Runway("05/23", (50.0, 230.0)),)
RWY_TWO = (Runway("05/23", (50.0, 230.0)), Runway("16/34", (160.0, 340.0)))


def test_crosswind_geometry():
    # 正側風：風從跑道方位 ±90° 吹來
    assert crosswind_kt(30, 140, RWY_05) == pytest.approx(30)
    assert crosswind_kt(30, 320, RWY_05) == pytest.approx(30)
    # 順風、逆風：沒有側風
    assert crosswind_kt(30, 50, RWY_05) == pytest.approx(0, abs=1e-9)
    assert crosswind_kt(30, 230, RWY_05) == pytest.approx(0, abs=1e-9)
    # 斜風 30°：sin 30° = 0.5
    assert crosswind_kt(40, 80, RWY_05) == pytest.approx(20)
    assert crosswind_kt(40, 200, RWY_05) == pytest.approx(20)
    # 風向可變或沒有風向：等於風速本身
    assert crosswind_kt(28, None, RWY_05) == 28
    # 沒有跑道資料：不算
    assert crosswind_kt(28, 140, ()) is None
    assert crosswind_kt(None, 140, RWY_05) is None


def test_crosswind_takes_best_runway():
    # 140° 對 05/23 是正側風，對 16/34 只差 20°
    assert crosswind_kt(40, 140, RWY_TWO) == pytest.approx(40 * math.sin(math.radians(20)))
    # 只有一條跑道時就是正側風
    assert crosswind_kt(40, 140, RWY_TWO[:1]) == pytest.approx(40)


def test_wind_dir_from_uv():
    assert wind_dir_from_uv(0, -10) == pytest.approx(0)  # 北風（往南吹）
    assert wind_dir_from_uv(-10, 0) == pytest.approx(90)  # 東風
    assert wind_dir_from_uv(0, 10) == pytest.approx(180)
    assert wind_dir_from_uv(10, 0) == pytest.approx(270)
    assert wind_dir_from_uv(-5, -5) == pytest.approx(45)
    assert wind_dir_from_uv(0, 0) is None
    assert wind_dir_from_uv(None, 3) is None


def test_crosswind_thresholds():
    assert crosswind_level(None, TH) is None
    assert crosswind_level(26.9, TH) == "low"
    assert crosswind_level(27, TH) == "medium"
    assert crosswind_level(32.9, TH) == "medium"
    assert crosswind_level(33, TH) == "high"
    custom = Thresholds(crosswind_medium_kt=20, crosswind_high_kt=30)
    assert crosswind_level(25, custom) == "medium" and crosswind_level(30, custom) == "high"


def test_taf_crosswind_raises_level():
    # 陣風 28 節（陣風規則低），正側風 → 側風 28 節 → 中
    p = TafPeriod(S0, S0 + timedelta(hours=6), "main", 140, 15, 28)
    t = taf_for_slot([p], NOW, S0, S0 + timedelta(hours=6), TH, RWY_05)
    assert t["crosswindKt"] == 28 and t["level"] == "medium"
    # 同樣的風沿著跑道吹 → 側風 0、低
    p = TafPeriod(S0, S0 + timedelta(hours=6), "main", 50, 15, 28)
    t = taf_for_slot([p], NOW, S0, S0 + timedelta(hours=6), TH, RWY_05)
    assert t["crosswindKt"] == 0 and t["level"] == "low"
    # 沒有陣風用平均風；VRB 用風速本身
    p = TafPeriod(S0, S0 + timedelta(hours=6), "tempo", None, 36, None)
    t = taf_for_slot([p], NOW, S0, S0 + timedelta(hours=6), TH, RWY_05)
    assert t["crosswindKt"] == 36 and t["level"] == "high"


def test_taf_gust_rule_wins_over_low_crosswind():
    # 陣風 48 節沿跑道 → 側風 0，但陣風規則是高 → 高
    p = TafPeriod(S0, S0 + timedelta(hours=6), "main", 50, 30, 48)
    t = taf_for_slot([p], NOW, S0, S0 + timedelta(hours=6), TH, RWY_05)
    assert t["crosswindKt"] == 0 and t["level"] == "high"


def test_official_slot_crosswind_and_metar():
    periods = [TafPeriod(S0, S0 + timedelta(hours=30), "main", 50, 10, None)]
    metar = Metar(NOW - timedelta(minutes=40), 140, 20, 30, "METAR X")
    slots = run(taf_periods=periods, runways=RWY_05, metar=metar)
    # METAR 正側風 30 節只算進現在所在的那一格
    assert slots[0]["official"]["crosswindKt"] == 30
    assert slots[0]["level"] == "medium"
    assert slots[1]["official"]["crosswindKt"] == 0
    assert slots[1]["level"] == "low"
    # 太舊的 METAR 不算
    old = Metar(NOW - timedelta(hours=4), 140, 20, 30, "METAR X")
    assert run(taf_periods=periods, runways=RWY_05, metar=old)[0]["level"] == "low"


def test_model_crosswind_from_direction():
    # HRES 陣風 28 節（陣風規則低），風向 140° 正側風 → 中
    hres = [
        GustInterval(S0 + timedelta(hours=h - 3), S0 + timedelta(hours=h), 28.0, 140.0)
        for h in range(3, 121, 3)
    ]
    gfs_pts = [GustPoint(S0 + timedelta(hours=h), 28.0, 50.0) for h in range(0, 121, 6)]
    s = run(ec=EcmwfPoint(hres, []), gfs=gfs_pts, runways=RWY_05)[10]
    assert s["model"]["ec"]["crosswindKt"] == pytest.approx(28.0)
    assert s["model"]["gfs"]["crosswindKt"] == 0  # GFS 風向沿跑道
    assert s["model"]["level"] == "medium"
    # 34 節正側風 → 高；陣風規則是低
    hres = [GustInterval(g.start, g.end, 34.0, 320.0) for g in hres]
    assert run(ec=EcmwfPoint(hres, []), gfs=None, runways=RWY_05)[10]["model"]["level"] == "high"


def test_model_crosswind_no_direction_uses_gust():
    gfs_pts = [GustPoint(S0 + timedelta(hours=h), 28.0) for h in range(0, 121, 6)]
    s = run(ec=None, gfs=gfs_pts, runways=RWY_05)[10]
    assert s["model"]["gfs"]["crosswindKt"] == 28.0
    assert s["model"]["level"] == "medium"


def test_no_runways_no_crosswind_rule():
    s = run(ec=None, gfs=[GustPoint(S0 + timedelta(hours=60), 28.0, 140.0)])[10]
    assert s["model"]["gfs"]["crosswindKt"] is None
    assert s["model"]["level"] == "low"


# ---- 真實案例：2026-10-18 16:15Z 那一報（`data` 分支 `history/20261018T1615Z.json`） ----

# 第一個真實強風案例（10/23 桃園、松山、高雄都是 high）。數字照抄那份檔（HD2 以前的格式，只有
# m/s 欄位，跟被沿用時一樣由 `fill_kt` 補節）；`old` 是那一報用舊門檻算出、檔裡記的 `level`。
# 這些格都是 `basis: "model"`（TAF 只到 10/19），所以整格等級＝模式層等級。
# （機場, from, HRES m/s, GFS m/s, p10, p15, p25, EC 側風節, GFS 側風節, old, new）
REAL_1615Z_MODEL = [
    # 舊門檻靠系集 p15 ≥ 50% 進中；新門檻中級不用系集，HRES 28.2 節 < 37 → 低
    ("RCTP", "2026-10-21T00", 14.5, 11.5, 1.0, 0.78, 0.0, 4.4, 2.5, "medium", "low"),
    # HRES 32.7 節、GFS 24.1 節都 < 37；舊門檻是 HRES ≥ 15 m/s → 中
    ("RCTP", "2026-10-22T00", 16.8, 12.4, 1.0, 0.81, 0.01, 5.7, 6.2, "medium", "low"),
    # HRES 22.5 m/s ≈ 43.7 節 ≥ 37 → 中（兩套一樣）
    ("RCTP", "2026-10-22T18", 22.5, 17.0, 1.0, 0.93, 0.12, 15.3, 3.1, "medium", "medium"),
    # p25（＝p49Kt）49% ≥ 30% → 高
    ("RCTP", "2026-10-23T00", 23.5, 22.9, 1.0, 0.99, 0.49, 15.5, 3.9, "high", "high"),
    # HRES 55.6 節、GFS 57.7 節 ≥ 48 → 高
    ("RCTP", "2026-10-23T06", 28.6, 29.7, 1.0, 0.99, 0.49, 21.0, 26.1, "high", "high"),
    # 只有 p15 51% 撐著中 → 低
    ("RCSS", "2026-10-22T12", 9.6, 8.9, 0.96, 0.51, 0.03, 15.3, 10.9, "medium", "low"),
    # EC 側風 26.7 節：舊門檻 ≥ 25 中，新門檻 < 27 → 低（HRES 30.3 節也 < 37）
    ("RCSS", "2026-10-22T18", 15.6, 14.0, 0.96, 0.51, 0.03, 26.7, 18.5, "medium", "low"),
    ("RCSS", "2026-10-23T00", 20.3, 21.4, 0.98, 0.94, 0.42, 28.0, 18.5, "high", "high"),
    # 側風 28.0 節 ≥ 27 → 中（兩套一樣）
    ("RCKH", "2026-10-22T06", 14.5, 4.7, 0.95, 0.4, 0.01, 28.0, 9.1, "medium", "medium"),
    # 側風 26.7 節 < 27、p25 21% < 30% → 低
    ("RCKH", "2026-10-22T12", 13.8, 6.1, 0.93, 0.68, 0.21, 26.7, 11.9, "medium", "low"),
    # 側風 39.2 節 ≥ 33 → 高
    ("RCKH", "2026-10-22T18", 20.6, 11.5, 0.93, 0.68, 0.21, 39.2, 22.4, "high", "high"),
    # 模式側風 50.5 節（HRES 與 GFS 都是）
    ("RCKH", "2026-10-23T06", 32.5, 30.7, 0.93, 0.87, 0.66, 50.5, 50.5, "high", "high"),
    # 側風 27.7 節 ≥ 27 → 中（兩套一樣）
    ("VHHH", "2026-10-23T00", 14.3, 11.0, 0.93, 0.51, 0.0, 27.7, 19.6, "medium", "medium"),
    # 側風 22.4 節、HRES 22.5 節；舊門檻靠 p15 51% 與 HRES ≥ 15 m/s → 中
    ("VHHH", "2026-10-23T06", 11.6, 11.0, 0.93, 0.51, 0.0, 22.4, 20.5, "medium", "low"),
    ("VMMC", "2026-10-23T06", 10.6, 12.2, 0.84, 0.02, 0.0, 0.7, 3.4, "low", "low"),
]

# 官方層（TAF）的格：（機場, from, TAF 平均風節, 陣風節, 側風節, old, new）
REAL_1615Z_TAF = [
    ("RCTP", "2026-10-18T12", 5, None, 6.2, "low", "low"),
    ("RCSS", "2026-10-18T12", 12, None, 2.5, "low", "low"),
]


# HD14 起模式層投票（這份檔只有 IFS、GFS、IFS 系集三票）：這三格 HD2 的規則是高，投票變中
HD14_VOTE = {
    # IFS 45.7、GFS 44.5 節都是中，只有系集 p49Kt 49% 投高：高 1 票 × 2 < 3；中 2／2（系集不算）
    ("RCTP", "2026-10-23T00"): "medium",
    # 同上（IFS 側風 28.0 節中、陣風 39.5 中；GFS 41.6 中；系集 42% 高）
    ("RCSS", "2026-10-23T00"): "medium",
    # 只有 IFS 側風 39.2 節投高，GFS 低、系集 21% 低：高 1／3 不成立；中 1／2（系集不算）成立
    ("RCKH", "2026-10-22T18"): "medium",
}


def test_real_case_20261018_1615z():
    wrong = []
    for icao, start, hres, gfs_ms, p10, p15, p25, ec_xw, gfs_xw, old, new in REAL_1615Z_MODEL:
        e = {"p10": p10, "p15": p15, "p25": p25, "hresGustMs": hres, "crosswindKt": ec_xw}
        g = {"gustMs": gfs_ms, "crosswindKt": gfs_xw}
        fill_kt(e, g)
        assert e["p49Kt"] == p25 and e["p37Kt"] is None
        new = HD14_VOTE.get((icao, start), new)
        if (got := model_level(e, g, TH)) != new:
            wrong.append((icao, start, old, new, got))
    for icao, start, wind, gust, xw, old, new in REAL_1615Z_TAF:
        if (got := max_level([taf_level(wind, gust, TH), crosswind_level(xw, TH)])) != new:
            wrong.append((icao, start, old, new, got))
    assert wrong == []


# ---- 已經過去的 TAF 時段不算（HD7） ----

# 關島 2026-10-19T03:57Z 那報（`data` 分支 `history/raw/2026-10-19/0357Z-taf.json` 的 PGUM，原文
# `TAF PGUM 190208Z 1902/2006 13016G27KT ... TEMPO 1902/1903 VRB30G46KT ...`）：TEMPO 02–03Z
# 在產出前就結束了，第一格（00–06Z）卻因為它判 high。METAR 是 `190354Z 14011G19KT`。
GUM_NOW = utc(2026, 10, 19, 3, 57)
GUM_SLOTS = slot_bounds(GUM_NOW)
GUM_RWY = (Runway("06L/24R、06R/24L", (65.0, 245.0)),)
GUM_MAIN = TafPeriod(utc(2026, 10, 19, 2), utc(2026, 10, 20, 6), "main", 130, 16, 27)
GUM_TEMPO = TafPeriod(utc(2026, 10, 19, 2), utc(2026, 10, 19, 3), "tempo", None, 30, 46)
GUM_METAR = Metar(utc(2026, 10, 19, 3, 54), 140, 11, 19, "METAR PGUM 190354Z 14011G19KT")


def gum(**kw):
    args = dict(
        now=GUM_NOW,
        slots=GUM_SLOTS,
        ec=None,
        gfs=None,
        taf_periods=[GUM_MAIN, GUM_TEMPO],
        runways=GUM_RWY,
        metar=GUM_METAR,
    )
    args.update(kw)
    return run(**args)


def test_past_tempo_not_counted_gum():
    assert GUM_SLOTS[0] == (utc(2026, 10, 19, 0), utc(2026, 10, 19, 6))
    t = taf_for_slot([GUM_MAIN, GUM_TEMPO], GUM_NOW, *GUM_SLOTS[0], TH, GUM_RWY)
    # 只剩主時段：陣風 27 節（< 37）、側風 27 × sin(130° − 65°) ≈ 24.5 節（< 27）→ 低
    assert t == {"windKt": 16, "gustKt": 27, "kind": "main", "level": "low", "crosswindKt": 24.5}
    s = gum()[0]
    assert (s["level"], s["basis"]) == ("low", "official")
    # METAR 側風 19 × sin(75°) ≈ 18.4 節，比主時段小
    assert s["official"]["crosswindKt"] == 24.5 and s["official"]["kind"] == "main"


def test_tempo_spanning_now_still_counts():
    # 同一份 TAF，產出時間在 TEMPO 裡（02:30Z）→ 照算：VRB 陣風 46 節 → 側風 46 節 → 高
    now = utc(2026, 10, 19, 2, 30)
    t = taf_for_slot([GUM_MAIN, GUM_TEMPO], now, *GUM_SLOTS[0], TH, GUM_RWY)
    assert (t["kind"], t["gustKt"], t["crosswindKt"], t["level"]) == ("tempo", 46, 46, "high")
    assert gum(now=now)[0]["level"] == "high"
    # 結束時間剛好等於現在也算已經過去
    assert taf_for_slot([GUM_TEMPO], utc(2026, 10, 19, 3), *GUM_SLOTS[0], TH) is None


def test_past_main_only_tempo_counts():
    # 主時段 00–03Z 平均風 35 節（高）已經過去；TEMPO 02–05Z 陣風 38 節（中）還沒結束 → 只算 TEMPO
    main = TafPeriod(utc(2026, 10, 19, 0), utc(2026, 10, 19, 3), "main", 130, 35, 50)
    tempo = TafPeriod(utc(2026, 10, 19, 2), utc(2026, 10, 19, 5), "tempo", 70, 25, 38)
    t = taf_for_slot([main, tempo], GUM_NOW, *GUM_SLOTS[0], TH, GUM_RWY)
    assert (t["kind"], t["windKt"], t["gustKt"], t["level"]) == ("tempo", 25, 38, "medium")


def test_all_taf_periods_past_only_metar_and_warnings():
    main = TafPeriod(utc(2026, 10, 19, 0), utc(2026, 10, 19, 3), "main", 130, 35, 50)
    tempo = TafPeriod(utc(2026, 10, 19, 2), utc(2026, 10, 19, 3), "tempo", None, 30, 46)
    metar = Metar(utc(2026, 10, 19, 3, 54), 155, 20, 30, "METAR PGUM")  # 正側風 30 節 → 中
    # 有警報：走「只有警報」的路，METAR 側風照算進第一格
    s = gum(taf_periods=[main, tempo], metar=metar, warnings=[warn("medium", "ts_watch", "nws")])
    o = s[0]["official"]
    assert o["kind"] == "warning" and o["windKt"] is None and o["gustKt"] is None
    assert o["crosswindKt"] == 30 and o["warnings"] == ["ts_watch"]
    assert (s[0]["level"], s[0]["basis"]) == ("medium", "official")
    # 沒有警報：沒有官方層（TAF 全部過去＝過期，跟沒有 TAF 一樣），退回模式
    s = gum(taf_periods=[main, tempo], metar=metar, ec=flat_ec(5), gfs=flat_gfs(5))
    assert s[0]["official"] is None and s[0]["basis"] == "model"


# ---- 新天氣種類（HD8）----


def wxp(wx=(), vis=None, ceil=None, start_h=0, end_h=6, kind="main", gust=None):
    """一段 TAF 時段（風很小），只看天氣現象、能見度（公尺）、雲底（呎）。"""
    return TafPeriod(
        S0 + timedelta(hours=start_h),
        S0 + timedelta(hours=end_h),
        kind,
        90,
        5,
        gust,
        vis,
        tuple(wx),
        ceil,
    )


def off_wx(*periods, **kw):
    """第一格官方層的 `wx`。"""
    return run(taf_periods=list(periods), **kw)[0]["official"]["wx"]


@pytest.mark.parametrize(
    ("wx", "vis", "level"),
    [
        (("+TSRA",), 9999, "medium"),
        (("+TSRA", "BR"), 3000, "medium"),
        (("TSGR",), 9999, "high"),
        (("+TSGR",), 9999, "high"),
        (("SHGR",), 9999, "high"),
        (("TSRA",), 1600, "medium"),  # TS 且能見度 ≤ 1600
        (("TS",), 1200, "medium"),
        (("TSRA",), 1700, "low"),
        (("TSRA",), 9999, "low"),  # 單純 TSRA 不升級
        (("TS",), None, "low"),  # 沒報能見度
        (("SHRA",), 800, "low"),  # 不是雷雨（能見度另外走 fog）
        (("+SHRA",), 9999, "low"),
    ],
)
def test_official_rain_levels(wx, vis, level):
    assert off_wx(wxp(wx, vis))["rain"] == level


@pytest.mark.parametrize(
    ("wx", "vis", "level"),
    [
        (("SN",), 1600, "medium"),
        (("SHSN",), 1200, "medium"),
        (("SN",), 2000, "low"),  # SN 但能見度 > 1600 不升級
        (("-SN",), 800, "low"),  # 小雪不升級
        (("-SHSN",), 800, "low"),
        (("+SN",), 9999, "high"),
        (("+SHSN",), 9999, "high"),
        (("FZRA",), 9999, "high"),
        (("-FZRA",), 9999, "high"),
        (("FZDZ",), 9999, "high"),
        (("PL",), 9999, "high"),
        (("FZFG",), 300, "low"),  # 凍霧不走 snow
    ],
)
def test_official_snow_levels(wx, vis, level):
    assert off_wx(wxp(wx, vis))["snow"] == level


@pytest.mark.parametrize(
    ("vis", "ceil", "level"),
    [
        (800, None, "medium"),
        (999, None, "medium"),
        (1000, None, "low"),
        (300, None, "high"),
        (399, None, "high"),
        (400, None, "medium"),
        (None, 200, "medium"),
        (None, 300, "low"),
        (None, 100, "high"),
        (9999, 100, "high"),  # 雲底低就算
        (None, None, "low"),  # 都沒報
    ],
)
def test_official_fog_levels(vis, ceil, level):
    assert off_wx(wxp((), vis, ceil))["fog"] == level


def test_fzfg_goes_to_fog():
    w = off_wx(wxp(("FZFG",), 300))
    assert (w["snow"], w["fog"]) == ("low", "high")


def test_official_wx_object():
    w = off_wx(
        wxp(("-SHRA", "BR"), 3000, 800),
        wxp(("+TSRA", "BR"), 800, 200, kind="tempo"),
    )
    assert w == {
        "phenomena": ["-SHRA", "BR", "+TSRA"],  # 去重、照出現順序
        "visibilityM": 800,
        "ceilingFt": 200,
        "rain": "medium",
        "snow": "low",
        "fog": "medium",
    }


def test_ts_and_low_visibility_must_be_same_period():
    """TS 在一段、低能見度在另一段 → 雷雨不升級（霧照算）。"""
    w = off_wx(wxp(("TSRA",), 9999), wxp(("BR",), 1500, kind="tempo"))
    assert (w["rain"], w["fog"]) == ("low", "low")


def test_official_level_is_max_of_wind_and_weather():
    # 陣風 40 節（中）＋能見度 300（高）→ 高，主因霧
    s = run(taf_periods=[wxp((), 300, gust=40)])[0]
    assert (s["official"]["level"], s["level"], s["basis"]) == ("high", "high", "official")
    assert s["causes"] == ["fog", "wind"]
    assert s["official"]["kind"] == "main"  # kind 還是風的時段種類
    # 只有天氣、風很小
    s = run(taf_periods=[wxp(("+SN",), 600)])[0]
    assert s["official"]["level"] == "high"
    assert s["causes"] == ["snow", "fog"]  # 雪高、霧中


def test_weather_does_not_change_wind_fields():
    s = run(taf_periods=[wxp(("+TSRA",), 800, gust=40)])[0]
    o = s["official"]
    assert (o["windKt"], o["gustKt"], o["kind"]) == (5, 40, "main")


def test_metar_weather_only_first_slot_and_fresh():
    periods = [wxp((), 9999, start_h=0, end_h=24)]
    fog = Metar(
        NOW - timedelta(minutes=10), 90, 5, None, "METAR … 0300 FG VV001", 300, ("FG",), 100
    )
    slots = run(taf_periods=periods, metar=fog)
    w0, w1 = slots[0]["official"]["wx"], slots[1]["official"]["wx"]
    assert (w0["fog"], w0["phenomena"], w0["visibilityM"]) == ("high", ["FG"], 300)
    assert (w1["fog"], w1["phenomena"]) == ("low", [])
    old = Metar(NOW - timedelta(hours=4), 90, 5, None, "METAR …", 300, ("FG",), 100)
    assert run(taf_periods=periods, metar=old)[0]["official"]["wx"]["fog"] == "low"


def test_metar_weather_not_counted_without_taf():
    """只有警報的格 `wx` 是 null，METAR 的霧不算。HD13 起限「有 TAF、但這格的時段都過去了」的機場
    （HD7 的當作沒有 TAF）；完全沒有 TAF 的機場第一格改由 METAR 撐起（見下面 HD13 的測試）。"""
    fog = Metar(NOW - timedelta(minutes=10), 90, 5, None, "METAR …", 300, ("FG",), 100)
    past = wxp((), 9999, start_h=0, end_h=1)  # 06–07Z，現在 08:10Z 已經過去
    s = run(taf_periods=[past], warnings=[warn("medium")], metar=fog)[0]
    assert s["official"]["wx"] is None
    assert s["official"]["level"] == "medium"
    assert s["causes"] == ["wind"]


def test_low_warning_alone_does_not_make_official_layer():
    # 雷暴警告（低）只有它、沒有 TAF → 官方層 null、退回模式
    s = run(ec=flat_ec(40), warnings=[warn("low", "thunderstorm")])[0]
    assert s["official"] is None
    assert (s["level"], s["basis"]) == ("medium", "model")
    # 有中以上的警報時列全部（含低的）
    s = run(warnings=[warn("low", "thunderstorm"), warn("medium", "rainstorm_black")])[0]
    assert s["official"]["warnings"] == ["thunderstorm", "rainstorm_black"]
    assert (s["official"]["level"], s["causes"]) == ("medium", ["rain"])
    # 有 TAF 時低的警報照樣列出、不升級
    s = run(taf_periods=[wxp()], warnings=[warn("low", "rainstorm_red")])[0]
    assert s["official"]["warnings"] == ["rainstorm_red"]
    assert (s["official"]["level"], s["causes"]) == ("low", [])


def test_cwa_heavy_rain_warning_is_rain_cause():
    s = run(warnings=[warn("medium", "cwa_heavy_rain", "cwa")])[0]
    assert (s["level"], s["basis"], s["causes"]) == ("medium", "official", ["rain"])


# ---- 沒有 TAF 的機場：METAR 撐起第一格、濃霧特報（HD13）----


def kinmen_fog(age=timedelta(minutes=10), vis=300, wind=2.9, gust=6.2, wdir=90):
    """金門的局屬站觀測（`sources/cwa.py` 轉成的 `Metar`）。"""
    return Metar(NOW - age, wdir, wind, gust, "CWA 467110 …", vis, ("FG",), None, "cwa")


def test_no_taf_fresh_metar_makes_first_slot_official():
    slots = run(metar=kinmen_fog())
    s0, s1 = slots[0], slots[1]
    o = s0["official"]
    assert (o["kind"], o["level"], o["windKt"], o["gustKt"]) == ("metar", "high", 2.9, 6.2)
    assert o["warnings"] == [] and o["crosswindKt"] is None  # 沒給跑道
    assert (o["wx"]["phenomena"], o["wx"]["visibilityM"], o["wx"]["fog"]) == (["FG"], 300, "high")
    assert (s0["level"], s0["basis"], s0["causes"]) == ("high", "official", ["fog"])
    # 之後的格照舊退回模式
    assert s1["official"] is None and s1["basis"] == "model"


def test_no_taf_metar_wind_and_crosswind():
    # 能見度 9999、沒有天氣；陣風 40 節 → 中；正側風 40 節（跑道 05/23，風 140°）→ 高
    m = Metar(NOW - timedelta(minutes=30), 140, 25, 40, "METAR X", 9999)
    o = run(metar=m)[0]["official"]
    assert (o["kind"], o["gustKt"], o["level"]) == ("metar", 40, "medium")
    s = run(metar=m, runways=RWY_05)[0]
    assert (s["official"]["crosswindKt"], s["level"], s["causes"]) == (40, "high", ["wind"])


def test_no_taf_old_metar_falls_back_to_model():
    s = run(metar=kinmen_fog(age=timedelta(hours=4)))[0]
    assert s["official"] is None and s["basis"] == "model"
    # 空的 TAF 清單也算沒有 TAF
    assert run(taf_periods=[], metar=kinmen_fog())[0]["official"]["kind"] == "metar"
    # 全部缺測的觀測（能見度 -99、風速 X）不算
    empty = Metar(NOW - timedelta(minutes=10), None, None, None, "CWA 467990 …", source="cwa")
    assert run(metar=empty)[0]["official"] is None


def test_no_taf_metar_with_warnings_overlaid():
    s = run(metar=kinmen_fog(vis=800), warnings=[warn("high", "typhoon_land", "cwa")])[0]
    o = s["official"]
    assert (o["kind"], o["warnings"], o["wx"]["fog"]) == ("metar", ["typhoon_land"], "medium")
    assert (s["level"], s["causes"]) == ("high", ["wind", "fog"])
    # 低的警報也照列（METAR 已經撐起官方層）
    s = run(metar=kinmen_fog(vis=9999), warnings=[warn("low", "thunderstorm")])[0]
    assert (s["official"]["warnings"], s["level"], s["causes"]) == (["thunderstorm"], "low", [])


def test_metar_alone_ignored_when_airport_has_taf():
    # 有 TAF 的機場不走這條：TAF 全部過去、沒有警報 → 還是沒有官方層（HD7）
    past = wxp((), 9999, start_h=0, end_h=1)
    s = run(taf_periods=[past], metar=kinmen_fog())[0]
    assert s["official"] is None and s["basis"] == "model"


def test_dense_fog_warning_is_fog_cause():
    # 沒有 TAF、沒有 METAR：濃霧特報（中）自己撐起官方層
    s = run(warnings=[warn("medium", "cwa_dense_fog", "cwa")])[0]
    o = s["official"]
    assert (o["kind"], o["level"], o["wx"]) == ("warning", "medium", None)
    assert (s["level"], s["basis"], s["causes"]) == ("medium", "official", ["fog"])
    # 有 TAF 時疊上去：TAF 霧低、特報中 → 霧中
    s = run(taf_periods=[wxp((), 9999)], warnings=[warn("medium", "cwa_dense_fog", "cwa")])[0]
    assert (s["official"]["kind"], s["level"], s["causes"]) == ("main", "medium", ["fog"])
    # METAR 的霧比特報高 → 高
    s = run(metar=kinmen_fog(), warnings=[warn("medium", "cwa_dense_fog", "cwa")])[0]
    assert (s["official"]["kind"], s["level"], s["causes"]) == ("metar", "high", ["fog"])


# ---- JMA 大雪警報（HD9）----


def test_jma_heavy_snow_warning_is_snow_cause():
    # 沒有 TAF：大雪警報（中）自己撐起官方層，算 `snow`，風不受影響
    slots = run(warnings=[warn("medium", "jma_heavy_snow", "jma")])
    s = slots[0]
    o = s["official"]
    assert (o["kind"], o["level"], o["warnings"], o["wx"]) == (
        "warning",
        "medium",
        ["jma_heavy_snow"],
        None,
    )
    assert (s["level"], s["basis"], s["causes"]) == ("medium", "official", ["snow"])
    # 只套到「現在 + 12 小時」以前開始的格
    assert all(x["official"] is None for x in slots[3:])
    # 有 TAF（只有 -SN，雪低）時疊上去 → 雪中
    s = run(taf_periods=[wxp(("-SN",), 3000)], warnings=[warn("medium", "jma_heavy_snow", "jma")])
    assert (s[0]["official"]["kind"], s[0]["level"], s[0]["causes"]) == ("main", "medium", ["snow"])


def test_jma_heavy_snow_emergency_is_high():
    s = run(warnings=[warn("high", "jma_heavy_snow_emergency", "jma")])[0]
    assert (s["level"], s["basis"], s["causes"]) == ("high", "official", ["snow"])


def test_jma_snowstorm_alone_does_not_make_official_layer():
    # 暴風雪警報（低）只列出：自己撐不起官方層，退回模式
    s = run(ec=flat_ec(40), warnings=[warn("low", "jma_snowstorm", "jma")])[0]
    assert s["official"] is None
    assert (s["level"], s["basis"], s["causes"]) == ("medium", "model", ["wind"])
    # 和大雪警報一起時列出、不升級
    ws = [warn("medium", "jma_heavy_snow", "jma"), warn("low", "jma_snowstorm", "jma")]
    s = run(warnings=ws)[0]
    assert s["official"]["warnings"] == ["jma_heavy_snow", "jma_snowstorm"]
    assert (s["official"]["level"], s["causes"]) == ("medium", ["snow"])
    # 有 TAF 時照樣列出；暴風雪警報算雪、不算風
    s = run(taf_periods=[wxp()], warnings=[warn("low", "jma_snowstorm", "jma")])[0]
    assert s["official"]["warnings"] == ["jma_snowstorm"]
    assert (s["official"]["level"], s["causes"]) == ("low", [])
    assert warning_cause("jma_snowstorm") == "snow"


# ---- HD27：JMA 暴風、大雨警報與氣象署陸上強風特報只列出 ----


HD27_LOW = (
    ("jma_storm", "jma"),
    ("jma_storm_emergency", "jma"),
    ("jma_heavy_rain", "jma"),
    ("jma_heavy_rain_danger", "jma"),
    ("jma_heavy_rain_emergency", "jma"),
    ("cwa_strong_wind", "cwa"),
)


def _without_warnings(slot: dict) -> dict:
    s = {k: v for k, v in slot.items() if k != "official"}
    if slot["official"] is not None:
        s["official"] = {k: v for k, v in slot["official"].items() if k != "warnings"}
    return s


@pytest.mark.parametrize(("kind", "source"), HD27_LOW)
@pytest.mark.parametrize(
    "kw",
    [
        {},  # 沒有官方資料：退回模式（低）
        {"ec": flat_ec(40)},  # 模式中
        {"ec": flat_ec(50), "gfs": flat_gfs(50)},  # 模式高
        {"taf_periods": [wxp(gust=40)]},  # 有 TAF（中）
        {"taf_periods": [wxp(("+RA",), 3000)]},  # 有 TAF（雨中）
    ],
)
def test_hd27_low_warning_changes_no_level(kind, source, kw):
    """只有暴風警報、大雨特別警報、陸上強風特報這類低的警報時，每一格除了 `warnings` 以外
    都和沒有警報時一樣。"""
    base = run(**kw)
    got = run(warnings=[warn("low", kind, source)], **kw)
    assert [_without_warnings(s) for s in got] == [_without_warnings(s) for s in base]
    # 有官方層（TAF）的格照樣列出
    assert all(s["official"]["warnings"] == [kind] for s in got[:2] if s["official"] is not None)


def test_hd27_low_warning_listed_with_medium():
    # 和中的警報一起時列出、不升級，也不多主因
    ws = [warn("medium", "cwa_dense_fog", "cwa"), warn("low", "cwa_strong_wind", "cwa")]
    s = run(warnings=ws)[0]
    assert s["official"]["warnings"] == ["cwa_dense_fog", "cwa_strong_wind"]
    assert (s["official"]["level"], s["causes"]) == ("medium", ["fog"])
    ws = [warn("low", "jma_heavy_rain_emergency", "jma"), warn("low", "jma_storm", "jma")]
    s = run(ec=flat_ec(40), warnings=ws)[0]
    assert s["official"] is None
    assert (s["level"], s["basis"], s["causes"]) == ("medium", "model", ["wind"])


# ---- HD29：經 WMO SWIC 的中國氣象局、韓國氣象廳、PAGASA 警報只列出 ----


HD29_LOW = tuple((kind, kind.split("_", 1)[0]) for kind in swic.KINDS)


@pytest.mark.parametrize(("kind", "source"), HD29_LOW)
@pytest.mark.parametrize(
    "kw",
    [
        {},  # 沒有官方資料：退回模式（低）
        {"ec": flat_ec(40)},  # 模式中
        {"ec": flat_ec(50), "gfs": flat_gfs(50)},  # 模式高
        {"taf_periods": [wxp(gust=40)]},  # 有 TAF（中）
        {"taf_periods": [wxp(("+RA",), 3000)]},  # 有 TAF（雨中）
    ],
)
def test_hd29_low_warning_changes_no_level(kind, source, kw):
    """中國大風黃色、韓國颱風警報、PAGASA 風球這些（HD29 全部 low）：每一格除了 `warnings`
    以外都和沒有警報時一樣（同 HD27 的鎖）。"""
    assert source in ("cma", "kma", "pagasa")
    base = run(**kw)
    got = run(warnings=[warn("low", kind, source)], **kw)
    assert [_without_warnings(s) for s in got] == [_without_warnings(s) for s in base]
    assert all(s["official"]["warnings"] == [kind] for s in got[:2] if s["official"] is not None)


def test_hd29_all_together_still_no_change():
    ws = [warn("low", k, s) for k, s in HD29_LOW]
    for kw in ({}, {"ec": flat_ec(40)}, {"taf_periods": [wxp(gust=40)]}):
        base, got = run(**kw), run(warnings=ws, **kw)
        assert [_without_warnings(s) for s in got] == [_without_warnings(s) for s in base]


def precip_ec(mm=0.0, ptype="none", p50=None, hres=5.0) -> EcmwfPoint:
    """整段一樣的 EC：每 6 小時一筆雨量與型態；`p50` 是系集 24 小時 ≥ 50 mm 的機率。"""
    pt = flat_ec(hres)
    pt.precip = [PrecipStep(S0 + timedelta(hours=h), mm, ptype, 1.0) for h in range(6, 121, 6)]
    pt.ens = [ProbWindow(w.start, w.end, w.p10, w.p15, w.p25, None, p50) for w in pt.ens]
    return pt


def precip_gfs(mm=None, ptype=None, vis=None, g=5.0) -> list[GustPoint]:
    return [GustPoint(S0 + timedelta(hours=h), g, None, mm, ptype, vis) for h in range(0, 121, 6)]


@pytest.mark.parametrize(
    ("ec_kw", "gfs_kw", "rain"),
    [
        ({"mm": 29.9}, {}, "low"),
        ({"mm": 30}, {}, "medium"),
        ({"mm": 60}, {}, "high"),
        ({}, {"mm": 30}, "medium"),
        ({}, {"mm": 60}, "high"),
        ({"p50": 0.3}, {}, "medium"),  # 系集 24 小時 ≥ 50 mm 機率 ≥ 30%
        ({"p50": 0.29}, {}, "low"),
        ({"mm": 60, "p50": 0.3}, {}, "high"),
    ],
)
def test_model_rain_levels(ec_kw, gfs_kw, rain):
    s = run(ec=precip_ec(**ec_kw), gfs=precip_gfs(**gfs_kw))[0]
    assert s["model"]["level"] == rain
    assert s["causes"] == ([] if rain == "low" else ["rain"])


@pytest.mark.parametrize(
    ("mm", "ptype", "snow"),
    [
        (4.9, "snow", "low"),
        (5, "snow", "medium"),
        (5, "wet_snow", "medium"),
        (9, "rain_snow", "medium"),
        (10, "snow", "high"),
        (10, "rain", "low"),  # 雨不算雪
        (1, "freezing_rain", "high"),
        (1, "freezing_drizzle", "high"),
        (1, "ice_pellets", "high"),
        (0.9, "freezing_rain", "low"),
        (20, "none", "low"),
    ],
)
def test_model_snow_levels(mm, ptype, snow):
    s = run(ec=precip_ec(mm, ptype))[0]
    assert s["model"]["ec"]["snow"] == snow
    # GFS 同一套（型態來自類別欄位）
    g = run(ec=flat_ec(5), gfs=precip_gfs(mm, ptype))[0]
    assert g["model"]["gfs"]["snow"] == snow


def test_model_takes_higher_of_ec_and_gfs_snow():
    s = run(ec=precip_ec(5, "snow"), gfs=precip_gfs(12, "snow"))[0]
    assert (s["model"]["ec"]["snow"], s["model"]["gfs"]["snow"]) == ("medium", "high")
    assert s["model"]["level"] == "high"
    assert s["causes"] == ["snow"]


@pytest.mark.parametrize(
    ("vis", "fog"), [(900, "medium"), (300, "medium"), (1000, "low"), (None, None)]
)
def test_model_fog_only_gfs(vis, fog):
    s = run(gfs=precip_gfs(0, "none", vis))[0]
    assert s["model"]["gfs"]["fog"] == fog
    assert "fog" not in s["model"]["ec"]  # EC 沒有能見度
    assert s["model"]["level"] == (fog if fog in ("medium", "high") else "low")


def test_model_slot_values_use_slot_end():
    """一格的雨量與型態用格結束那個時間點；GFS 能見度取格內最小。"""
    pt = flat_ec(5)
    pt.precip = [
        PrecipStep(S0 + timedelta(hours=6), 12.34, "rain", 25.04),
        PrecipStep(S0 + timedelta(hours=12), 50.0, "snow", -1.0),
    ]
    g = [
        GustPoint(S0, 5, None, 99.0, "snow", 300.4),
        GustPoint(S0 + timedelta(hours=6), 5, None, 3.21, "rain", 5000.0),
    ]
    s = run(ec=pt, gfs=g)[0]
    ec_v, gfs_v = s["model"]["ec"], s["model"]["gfs"]
    assert (ec_v["rain6hMm"], ec_v["ptype"], ec_v["temp2mC"]) == (12.3, "rain", 25.0)
    assert (gfs_v["rain6hMm"], gfs_v["ptype"], gfs_v["visibilityM"]) == (3.2, "rain", 300)
    assert gfs_v["fog"] == "medium"  # 模式層的霧封頂在中（HD10）


def test_agreement_still_only_wind():
    s = run(ec=precip_ec(80, hres=40), gfs=precip_gfs(0, "none", g=40))[0]
    assert s["model"]["agreement"] == "agree"  # 陣風都是中；雨量差很多也不影響
    assert s["model"]["level"] == "high"
    assert s["causes"] == ["rain", "wind"]


def test_causes_order():
    assert causes_from({"wind": "medium", "rain": "medium", "snow": "medium", "fog": "medium"}) == [
        "wind",
        "snow",
        "fog",
        "rain",
    ]
    assert causes_from({"wind": "medium", "rain": "high", "snow": "low", "fog": None}) == [
        "rain",
        "wind",
    ]
    assert causes_from({"wind": "low", "rain": "low", "snow": "low", "fog": "low"}) == []
    # 依據是模式層：同級的雨排在霧前面（HD10）
    assert causes_from(
        {"wind": "medium", "rain": "medium", "snow": "medium", "fog": "medium"}, MODEL_CAUSE_ORDER
    ) == ["wind", "snow", "rain", "fog"]


# ---- 模式層的霧封頂在中（HD10）；數字取自 2026-10-19T06:56Z 那報 ----


def test_model_fog_capped_medium_pus():
    """釜山 10/20 12Z：只靠 GFS 能見度 308 公尺、幾乎沒雨。HD8 判高，HD10 起是中。"""
    s = run(ec=precip_ec(5.2, "rain", p50=0.0), gfs=precip_gfs(1.6, "rain", 308))[0]
    assert s["model"]["gfs"]["fog"] == "medium"
    assert (s["model"]["level"], s["level"], s["basis"]) == ("medium", "medium", "model")
    assert s["causes"] == ["fog"]


def test_model_fog_capped_with_heavy_rain_and_wind_hun():
    """花蓮 10/23 06Z：GFS 能見度 76 公尺、6 小時雨量 174.4 mm、HRES 陣風 62.6 節。"""
    s = run(
        ec=precip_ec(44.8, "rain", p50=0.81, hres=62.6),
        gfs=precip_gfs(174.4, "rain", 76, g=39.1),
    )[0]
    assert (s["model"]["gfs"]["rain"], s["model"]["gfs"]["fog"]) == ("high", "medium")
    assert s["model"]["level"] == "high"
    # HD14 投票：風只有 IFS 高（GFS 中、系集 0% 低）→ 高 1／3 不成立、中 2／2 → 中；
    # 雨 IFS 中、GFS 高 → 高 1／2 成立。所以雨排第一（HD10 時是風、雨、霧）
    assert s["causes"] == ["rain", "wind", "fog"]


def test_model_fog_and_rain_both_medium_rain_first_ttt():
    """台東 10/24 00Z：GFS 能見度 92 公尺、GFS 雨 40.5 mm、EC 雨 27.7 mm、系集 47%。
    雨、霧都是中；依據是模式層，雨排在霧前面。"""
    s = run(
        ec=precip_ec(27.7, "rain", p50=0.47, hres=27.9),
        gfs=precip_gfs(40.5, "rain", 92, g=20.8),
    )[0]
    assert (s["model"]["ec"]["rain"], s["model"]["gfs"]["rain"]) == ("medium", "medium")
    assert s["model"]["gfs"]["fog"] == "medium"
    assert s["model"]["level"] == "medium"
    assert s["causes"] == ["rain", "fog"]


def test_official_fog_still_high():
    """官方層的霧不封頂：TAF 能見度 300 公尺仍是高；同級的霧照原本順序排在雨前面。"""
    s = run(taf_periods=[wxp((), 300)])[0]
    assert s["official"]["wx"]["fog"] == "high"
    assert (s["basis"], s["level"], s["causes"]) == ("official", "high", ["fog"])
    s = run(taf_periods=[wxp(("+TSRA",), 800)])[0]
    assert (s["official"]["wx"]["rain"], s["official"]["wx"]["fog"]) == ("medium", "medium")
    assert s["causes"] == ["fog", "rain"]


def test_causes_confirmed_and_unknown():
    confirmed = [ConfirmedPeriod("RCTP", S0, S0 + timedelta(hours=6), {})]
    # 0–30 小時有 TAF：蓋掉的是官方層
    s = run(taf_periods=[wxp((), 300)], ec=precip_ec(80), confirmed=confirmed)[0]
    assert (s["level"], s["basis"], s["causes"]) == ("confirmed", "confirmed", ["fog"])
    # 沒有官方層：看模式層
    s = run(ec=precip_ec(80), confirmed=confirmed)[0]
    assert (s["basis"], s["causes"]) == ("confirmed", ["rain"])
    # 沒有任何資料
    s = run(ec=None, gfs=None)[0]
    assert (s["level"], s["causes"]) == ("unknown", [])


def test_causes_from_official_layer_ignore_model():
    """依據是官方層時 causes 只看官方層（模式的大雨不列）。"""
    s = run(taf_periods=[wxp((), 9999, gust=40)], ec=precip_ec(80))[0]
    assert (s["basis"], s["level"], s["causes"]) == ("official", "medium", ["wind"])
    assert s["gap"] is True  # 模式層是高


# ---- 多模式投票（HD14）----


def flat_aifs(wind=31.0, wdir=None, rain=0.0, snow=0.0) -> list[AifsStep]:
    """整段一樣的 AIFS（10 米平均風，節）。"""
    return [AifsStep(S0 + timedelta(hours=h), wind, wdir, rain, snow) for h in range(0, 121, 6)]


def flat_aigfs(wind=10.0, rain=0.0) -> list[AigfsStep]:
    return [AigfsStep(S0 + timedelta(hours=h), wind, None, rain) for h in range(0, 121, 6)]


RUNS = {
    "ifs": "2026-10-18T00:00:00Z",
    "gfs": "2026-10-18T00:00:00Z",
    "ifs-ens": "2026-10-18T00:00:00Z",
    "aifs": "2026-10-18T00:00:00Z",
    "aigfs": None,
}


def test_models_entries_numbers_and_levels():
    rwy = (Runway("05/23", (50.0, 230.0)),)
    s = run(
        ec=precip_ec(12.3, "rain", hres=40),
        gfs=precip_gfs(31.0, "rain", 5000, g=20),
        aifs=flat_aifs(31.0, 140.0, rain=3.1),
        aigfs=flat_aigfs(10.0, rain=0.4),
        runways=rwy,
        runs=RUNS,
    )[0]
    m = s["model"]
    by = {e["id"]: e for e in m["models"]}
    assert list(by) == [
        *("ifs", "gfs", "ifs-ens", "aifs", "aigfs", "icon", "jma", "wn2-ens"),
        *("ukmo", "gem", "arpege", "cma"),  # HD33b：旁觀
    ]
    ifs, g, ens, ai, ag = (by[i] for i in ("ifs", "gfs", "ifs-ens", "aifs", "aigfs"))
    assert (ifs["gustKt"], ifs["gustEstimated"], ifs["rain6hMm"], ifs["ptype"]) == (
        40.0,
        False,
        12.3,
        "rain",
    )
    # HRES 沒有風向 → 側風＝陣風 40 節 ≥ 33 → 高
    assert ifs["crosswindKt"] == 40.0
    assert ifs["levels"] == {"wind": "high", "rain": "low", "snow": "low", "fog": None}
    # IFS／GFS 三類的等級就是 model.ec／model.gfs 的（值照舊）
    assert (ifs["levels"]["rain"], ifs["levels"]["snow"]) == (m["ec"]["rain"], m["ec"]["snow"])
    assert g["levels"] == {"wind": "low", "rain": "medium", "snow": "low", "fog": "low"}
    assert g["visibilityM"] == 5000 and g["level"] == "medium"
    assert ens["levels"]["wind"] == "low" and ens["gustKt"] is None
    # AIFS：平均風 31 節 × 1.4 → 估算陣風 43.4 節 → 中；側風用估算陣風（風向 140°、跑道 050°）
    assert (ai["gustKt"], ai["gustEstimated"], ai["crosswindKt"]) == (43.4, True, 43.4)
    assert (ai["rain6hMm"], ai["ptype"], ai["visibilityM"]) == (3.1, "rain", None)
    assert ai["levels"] == {"wind": "high", "rain": "low", "snow": "low", "fog": None}
    assert ai["run"] == "2026-10-18T00:00:00Z"
    # AIGFS：14 節、沒有型態 → 不投雪；run 是 null（這一報沒有時次）
    assert (ag["gustKt"], ag["gustEstimated"], ag["ptype"]) == (14.0, True, None)
    assert ag["levels"] == {"wind": "low", "rain": "low", "snow": None, "fog": None}
    assert ag["run"] is None


def test_aifs_estimated_gust_medium():
    """AIFS 平均風 31 節 × 1.4＝43.4 → 中、`gustEstimated`；沒有跑道就只看陣風。"""
    s = run(ec=flat_ec(40), gfs=flat_gfs(5), aifs=flat_aifs(31.0), aigfs=flat_aigfs(5.0))[0]
    ai = s["model"]["models"][3]
    assert (ai["gustKt"], ai["gustEstimated"], ai["crosswindKt"]) == (43.4, True, None)
    assert ai["levels"]["wind"] == "medium"
    # 風：IFS 中、GFS 低、系集低、AIFS 中、AIGFS 低 → 中（系集不算）2 × 2 ≥ 4
    assert s["model"]["vote"] == {
        "total": 5,
        "high": 0,
        "medium": 2,
        "mediumTotal": 4,  # HD24
        "low": 3,
        "level": "medium",
        "thin": False,
    }
    assert (s["model"]["level"], s["level"], s["causes"]) == ("medium", "medium", ["wind"])


def test_vote_level_is_model_level_and_gap():
    """`model.level`＝投票結果；落差照舊用它比官方層。"""
    s = run(ec=flat_ec(50), gfs=flat_gfs(5), aifs=flat_aifs(5.0), aigfs=flat_aigfs(5.0))[0]
    # 只有 IFS 高：高 1／5 不成立；中（系集不算）1 × 2 < 4 → 低
    assert s["model"]["vote"]["level"] == s["model"]["level"] == "low"
    # model.ec／gfs／agreement 照舊
    assert s["model"]["ec"]["hresGustKt"] == 50 and s["model"]["agreement"] == "disagree"
    s = run(
        ec=flat_ec(50),
        gfs=flat_gfs(50),
        aifs=flat_aifs(5.0),
        aigfs=flat_aigfs(5.0),
        taf_periods=[taf("main", 10, None, 0, 30)],
    )[0]
    assert (s["model"]["level"], s["official"]["level"], s["gap"]) == ("medium", "low", True)


def test_causes_use_voted_levels():
    """依據是模式層時 causes 用投票後的各類等級：雨只有 IFS 高（GFS、AIFS、AIGFS 低）→ 雨是低、
    不列；風 IFS、GFS、AIFS 都中 → 中。"""
    s = run(
        ec=precip_ec(80, "rain", hres=40),
        gfs=precip_gfs(0, "none", g=40),
        aifs=flat_aifs(28.0),
        aigfs=flat_aigfs(5.0),
    )[0]
    assert s["model"]["ec"]["rain"] == "high"  # 欄位值照舊
    assert s["model"]["models"][0]["levels"]["rain"] == "high"
    assert (s["model"]["level"], s["causes"]) == ("medium", ["wind"])


def test_models_present_when_sources_missing():
    s = run(ec=None, gfs=None)[0]
    assert [e["id"] for e in s["model"]["models"]] == [
        "ifs",
        "gfs",
        "ifs-ens",
        "aifs",
        "aigfs",
        "icon",
        "jma",
        "wn2-ens",
        "ukmo",  # HD33b：旁觀
        "gem",
        "arpege",
        "cma",
    ]
    assert all(e["level"] is None for e in s["model"]["models"])
    assert s["model"]["vote"]["level"] is None and s["model"]["vote"]["thin"] is True


# ---- 估算陣風的係數（HD18）----


def test_aifs_gust_uses_airport_factor():
    """AIFS 平均風 20 節、G 1.6 → 估算陣風 32 節、`gustFactor` 1.6；IFS、GFS、系集沒有係數。"""
    s = run(
        ec=flat_ec(5),
        gfs=flat_gfs(5),
        aifs=flat_aifs(20.0),
        aigfs=flat_aigfs(25.0),
        gust_factor=GustFactor(1.6, "airport30d"),
    )[0]
    by = {e["id"]: e for e in s["model"]["models"]}
    ai, ag = by["aifs"], by["aigfs"]
    assert (ai["windKt"], ai["gustKt"], ai["gustEstimated"]) == (20.0, 32.0, True)
    assert (ai["gustFactor"], ai["gustFactorBasis"]) == (1.6, "airport30d")
    assert (ag["windKt"], ag["gustKt"], ag["gustFactor"]) == (25.0, 40.0, 1.6)
    assert ag["levels"]["wind"] == "medium"  # 40 ≥ 37
    for i in ("ifs", "gfs", "ifs-ens"):
        assert (by[i]["gustFactor"], by[i]["gustFactorBasis"]) == (None, None)
    # model.ec／gfs 沒有新鍵
    assert "windKt" not in s["model"]["ec"] and "windKt" not in s["model"]["gfs"]


def test_default_factor_is_1_4():
    ai = run(aifs=flat_aifs(31.0))[0]["model"]["models"][3]
    assert (ai["gustKt"], ai["gustFactor"], ai["gustFactorBasis"]) == (43.4, 1.4, "default")


def test_estimated_crosswind_uses_factor():
    rwy = (Runway("05/23", (50.0, 230.0)),)
    s = run(aifs=flat_aifs(20.0, 140.0), runways=rwy, gust_factor=GustFactor(1.5, "run"))[0]
    ai = s["model"]["models"][3]
    assert (ai["gustKt"], ai["crosswindKt"]) == (30.0, 30.0)  # 風向和跑道垂直


def test_wind_kt_ifs_slot_end_and_gfs_at_max_gust():
    """`windKt`：IFS 取格結束步長的平均風；GFS 取格內陣風最大那一點的；系集 null。"""
    hres = [
        GustInterval(S0 + timedelta(hours=h - 3), S0 + timedelta(hours=h), 30.0, None, float(h))
        for h in range(3, 121, 3)
    ]
    pts = [
        GustPoint(S0, 20.0, wind_kt=11.0),
        GustPoint(S0 + timedelta(hours=6), 25.0, wind_kt=14.04),
    ]
    s = run(ec=EcmwfPoint(hres), gfs=pts)[0]
    by = {e["id"]: e for e in s["model"]["models"]}
    assert by["ifs"]["windKt"] == 6.0  # 格 06–12Z 的結束步長（區間 3–6 小時，wind_kt=6）
    assert by["gfs"]["windKt"] == 14.0
    assert by["ifs-ens"]["windKt"] is None
    assert by["aifs"]["windKt"] is None and by["aifs"]["gustFactor"] is None  # 沒資料


def test_refactor_estimated():
    """沿用的那筆：`windKt` × 新 G；側風照新舊 G 比例；HD18 以前的沒有 `windKt` 時用 1.4 倒推。"""
    e = {"windKt": 20.0, "gustKt": 28.0, "gustFactor": 1.4, "crosswindKt": 14.0}
    refactor_estimated(e, GustFactor(1.6, "all30d"))
    assert e == {
        "windKt": 20.0,
        "gustKt": 32.0,
        "gustFactor": 1.6,
        "gustFactorBasis": "all30d",
        "crosswindKt": 16.0,
    }
    old = {"gustKt": 50.4, "crosswindKt": 30.0}
    refactor_estimated(old, GustFactor(1.5, "run"))
    assert (old["windKt"], old["gustKt"], old["crosswindKt"]) == (36.0, 54.0, 32.1)
    empty = {"gustKt": None}
    refactor_estimated(empty, GustFactor(1.5, "run"))
    assert empty == {"gustKt": None}
