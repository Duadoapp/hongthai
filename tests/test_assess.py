"""等級規則：每條規則一個 case。"""

from __future__ import annotations

import math
from datetime import timedelta

import pytest
from conftest import utc

from hongthai.assess import (
    ActiveWarning,
    assess_slots,
    crosswind_kt,
    crosswind_level,
    model_level,
    taf_for_slot,
)
from hongthai.config import ConfirmedPeriod, Runway, Thresholds
from hongthai.grib import wind_dir_from_uv
from hongthai.sources.ecmwf import EcmwfPoint, GustInterval, ProbWindow
from hongthai.sources.gfs import GustPoint
from hongthai.sources.taf import Metar, TafPeriod
from hongthai.timeutil import slot_bounds

TH = Thresholds()
NOW = utc(2026, 10, 18, 8, 10)
SLOTS = slot_bounds(NOW)
S0 = SLOTS[0][0]  # 2026-10-18T06:00Z


def ec(p10=None, p15=None, p25=None, hres=None):
    return {"p10": p10, "p15": p15, "p25": p25, "hresGustMs": hres}


def gfs(g=None):
    return {"gustMs": g}


def warn(level, kind="tc_signal", source="hko"):
    return ActiveWarning(source, kind, level, {"en": kind}, None)


def flat_ec(hres: float, p15: float = 0.0, p25: float = 0.0) -> EcmwfPoint:
    """整段 120 小時都一樣的 EC 資料。"""
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


def test_model_high_by_ec_p25():
    assert model_level(ec(p25=0.30), gfs(5), TH) == "high"
    assert model_level(ec(p25=0.29), gfs(5), TH) == "low"


def test_model_high_by_hres_gust():
    assert model_level(ec(hres=25.0), gfs(5), TH) == "high"


def test_model_high_by_gfs_gust():
    assert model_level(ec(hres=5), gfs(25.0), TH) == "high"


def test_model_medium_by_ec_p15():
    assert model_level(ec(p15=0.5, p25=0.1), gfs(5), TH) == "medium"
    assert model_level(ec(p15=0.49), gfs(5), TH) == "low"


def test_model_medium_by_any_gust():
    assert model_level(ec(hres=15.0), gfs(3), TH) == "medium"
    assert model_level(ec(hres=3), gfs(15.0), TH) == "medium"


def test_model_low_and_missing():
    assert model_level(ec(p10=0.9, p15=0.1, p25=0, hres=12), gfs(14.9), TH) == "low"
    assert model_level(ec(), gfs(), TH) is None


def test_ec_slot_uses_hres_max_and_min_of_containing_windows():
    point = EcmwfPoint(
        hres=[
            GustInterval(S0, S0 + timedelta(hours=3), 10.0),
            GustInterval(S0 + timedelta(hours=3), S0 + timedelta(hours=6), 18.04),
            GustInterval(S0 + timedelta(hours=6), S0 + timedelta(hours=9), 30.0),
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
        "hresGustMs": 18.0,
        "crosswindKt": None,
    }
    assert s["model"]["level"] == "medium"


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


def test_taf_gust45_high():
    assert taf_for_slot([taf("main", 20, 45)], *SLOTS[0], TH)["level"] == "high"


def test_taf_wind35_high():
    assert taf_for_slot([taf("main", 35, None)], *SLOTS[0], TH)["level"] == "high"


def test_taf_gust30_medium_and_kind_of_worst_period():
    o = taf_for_slot([taf("main", 15, None), taf("tempo", 25, 38, 2, 4)], *SLOTS[0], TH)
    assert o == {
        "windKt": 25,
        "gustKt": 38,
        "kind": "tempo",
        "level": "medium",
        "crosswindKt": None,
    }


def test_taf_prob_period_counts():
    o = taf_for_slot([taf("main", 10, None), taf("prob30", 30, 50, 1, 3)], *SLOTS[0], TH)
    assert (o["kind"], o["level"]) == ("prob30", "high")


def test_taf_below_threshold_low_and_no_overlap_none():
    assert taf_for_slot([taf("main", 20, 29)], *SLOTS[0], TH)["level"] == "low"
    assert taf_for_slot([taf("main", 20, 29, 6, 12)], *SLOTS[0], TH) is None


# ---- 0–30 小時官方優先 ----


def test_official_overrides_model_within_30h():
    periods = [taf("main", 10, None, 0, 30)]
    slots = run(ec=flat_ec(26), taf_periods=periods)
    s = slots[0]
    assert (s["level"], s["basis"]) == ("low", "official")
    assert s["model"]["level"] == "high"


def test_after_30h_only_model():
    periods = [taf("main", 10, None, 0, 120)]  # 就算 TAF 很長，超過 30 小時也不看
    slots = run(ec=flat_ec(16), taf_periods=periods)
    # 現在 08:10，+30h = 隔天 14:10 → 開始時間 < 14:10 的格（前 6 格）是官方
    assert [s["basis"] for s in slots[:7]] == ["official"] * 6 + ["model"]
    assert slots[6]["official"] is None
    assert slots[6]["level"] == "medium"


def test_no_official_data_falls_back_to_model():
    s = run(ec=flat_ec(16), taf_periods=None)[0]
    assert (s["level"], s["basis"], s["official"]) == ("medium", "model", None)


def test_no_data_at_all_unknown():
    s = run(ec=None, gfs=None)[0]
    assert (s["level"], s["basis"]) == ("unknown", "none")
    assert s["model"]["level"] is None


# ---- 落差 ----


def test_gap_when_official_and_model_differ():
    slots = run(ec=flat_ec(26), taf_periods=[taf("main", 10, None, 0, 30)])
    assert slots[0]["gap"] is True


def test_no_gap_when_same_or_no_official():
    slots = run(ec=flat_ec(5), taf_periods=[taf("main", 10, None, 0, 30)])
    assert slots[0]["gap"] is False
    assert slots[10]["gap"] is False


# ---- 一致性 ----


def test_agreement_same_class_agree():
    s = run(ec=flat_ec(16), gfs=flat_gfs(24.9))[0]
    assert s["model"]["agreement"] == "agree"


def test_agreement_different_class_disagree():
    s = run(ec=flat_ec(16), gfs=flat_gfs(14.9))[0]
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
    assert crosswind_level(24.9, TH) == "low"
    assert crosswind_level(25, TH) == "medium"
    assert crosswind_level(34.9, TH) == "medium"
    assert crosswind_level(35, TH) == "high"
    custom = Thresholds(crosswind_medium_kt=20, crosswind_high_kt=30)
    assert crosswind_level(25, custom) == "medium" and crosswind_level(30, custom) == "high"


def test_taf_crosswind_raises_level():
    # 陣風 28 節（陣風規則低），正側風 → 側風 28 節 → 中
    p = TafPeriod(S0, S0 + timedelta(hours=6), "main", 140, 15, 28)
    t = taf_for_slot([p], S0, S0 + timedelta(hours=6), TH, RWY_05)
    assert t["crosswindKt"] == 28 and t["level"] == "medium"
    # 同樣的風沿著跑道吹 → 側風 0、低
    p = TafPeriod(S0, S0 + timedelta(hours=6), "main", 50, 15, 28)
    t = taf_for_slot([p], S0, S0 + timedelta(hours=6), TH, RWY_05)
    assert t["crosswindKt"] == 0 and t["level"] == "low"
    # 沒有陣風用平均風；VRB 用風速本身
    p = TafPeriod(S0, S0 + timedelta(hours=6), "tempo", None, 36, None)
    t = taf_for_slot([p], S0, S0 + timedelta(hours=6), TH, RWY_05)
    assert t["crosswindKt"] == 36 and t["level"] == "high"


def test_taf_gust_rule_wins_over_low_crosswind():
    # 陣風 45 節沿跑道 → 側風 0，但陣風規則是高 → 高
    p = TafPeriod(S0, S0 + timedelta(hours=6), "main", 50, 30, 45)
    t = taf_for_slot([p], S0, S0 + timedelta(hours=6), TH, RWY_05)
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
    # HRES 陣風 14 m/s（≈27.2 節，陣風規則低），風向 140° 正側風 → 中
    hres = [
        GustInterval(S0 + timedelta(hours=h - 3), S0 + timedelta(hours=h), 14.0, 140.0)
        for h in range(3, 121, 3)
    ]
    gfs_pts = [GustPoint(S0 + timedelta(hours=h), 14.0, 50.0) for h in range(0, 121, 6)]
    s = run(ec=EcmwfPoint(hres, []), gfs=gfs_pts, runways=RWY_05)[10]
    assert s["model"]["ec"]["crosswindKt"] == pytest.approx(27.2, abs=0.05)
    assert s["model"]["gfs"]["crosswindKt"] == 0  # GFS 風向沿跑道
    assert s["model"]["level"] == "medium"
    # 18.5 m/s（≈36 節）正側風 → 高；陣風規則只到中
    hres = [GustInterval(g.start, g.end, 18.5, 320.0) for g in hres]
    assert run(ec=EcmwfPoint(hres, []), gfs=None, runways=RWY_05)[10]["model"]["level"] == "high"


def test_model_crosswind_no_direction_uses_gust():
    gfs_pts = [GustPoint(S0 + timedelta(hours=h), 14.0) for h in range(0, 121, 6)]
    s = run(ec=None, gfs=gfs_pts, runways=RWY_05)[10]
    assert s["model"]["gfs"]["crosswindKt"] == pytest.approx(27.2, abs=0.05)
    assert s["model"]["level"] == "medium"


def test_no_runways_no_crosswind_rule():
    s = run(ec=None, gfs=[GustPoint(S0 + timedelta(hours=60), 14.0, 140.0)])[10]
    assert s["model"]["gfs"]["crosswindKt"] is None
    assert s["model"]["level"] == "low"
