"""HD18：估算陣風的係數 G（每個機場、30 天、IFS＋GFS 自己的陣風÷平均風中位數）。"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from conftest import utc

from hongthai import gustfactor
from hongthai.assess import GustFactor
from hongthai.config import Airport, Thresholds
from hongthai.sources.ecmwf import EcmwfData, EcmwfPoint, GustInterval
from hongthai.sources.gfs import GfsData, GustPoint
from hongthai.timeutil import iso, slot_bounds

NOW = utc(2026, 10, 20, 8, 25)
RUN = iso(NOW)
SLOTS = slot_bounds(NOW)
S0 = SLOTS[0][0]  # 2026-10-20T06:00Z


def _airport(icao: str) -> Airport:
    return Airport(icao, icao[1:], "UTC", {"en": icao}, 25.0, 121.0, (), Thresholds())


def row(icao, ifs=(), gfs=(), run=RUN):
    return {"run": run, "icao": icao, "ifs": list(ifs), "gfs": list(gfs)}


def ec_data(gust_kt: float, wind_kt: float | None) -> EcmwfData:
    """整段一樣的 HRES：每 3 小時一個區間，平均風配格結束步長的。"""
    hres = [
        GustInterval(S0 + timedelta(hours=h - 3), S0 + timedelta(hours=h), gust_kt, None, wind_kt)
        for h in range(3, 121, 3)
    ]
    return EcmwfData(S0, None, None, {"RCTP": EcmwfPoint(hres)})


def gfs_data(points: list[GustPoint]) -> GfsData:
    return GfsData(S0, {"RCTP": points})


# ---- 樣本 ----


def test_ratio_only_wind_at_least_10kt():
    assert gustfactor.ratio(15.0, 10.0) == 1.5
    assert gustfactor.ratio(15.0, 9.9) is None
    assert gustfactor.ratio(None, 20.0) is None and gustfactor.ratio(20.0, None) is None
    assert gustfactor.ratio(31.0, 21.0) == 1.48  # 兩位小數


def test_run_samples_ifs_and_gfs_separately():
    # IFS：陣風 30、平均風 20 → 1.5，20 格都收
    # GFS：格內兩個時間點，取陣風大的那一點的平均風（陣風 30／平均風 15 → 2.0，不是 20／25）
    pts = [
        GustPoint(S0 + timedelta(hours=h), 30.0 if h % 12 == 0 else 20.0, None, wind_kt=w)
        for h in range(0, 121, 6)
        for w in [15.0 if h % 12 == 0 else 25.0]
    ]
    s = gustfactor.run_samples(ec_data(30.0, 20.0), gfs_data(pts), [_airport("RCTP")], SLOTS)
    assert s["RCTP"]["ifs"] == [1.5] * 20
    assert s["RCTP"]["gfs"] == [2.0] * 20


def test_run_samples_skip_weak_wind_and_missing():
    weak = [GustPoint(S0 + timedelta(hours=h), 15.0, None, wind_kt=9.0) for h in range(0, 121, 6)]
    s = gustfactor.run_samples(ec_data(30.0, None), gfs_data(weak), [_airport("RCTP")], SLOTS)
    assert s["RCTP"] == {"ifs": [], "gfs": []}


def test_run_samples_reused_model_is_empty():
    """沿用（`ecmwf`／`gfs` 失敗、用舊資料）的那一報不算新樣本：那個模式寫 `[]`。"""
    s = gustfactor.run_samples(ec_data(30.0, 20.0), None, [_airport("RCTP")], SLOTS)
    assert s["RCTP"] == {"ifs": [1.5] * 20, "gfs": []}
    s = gustfactor.run_samples(None, None, [_airport("RCTP")], SLOTS)
    assert s["RCTP"] == {"ifs": [], "gfs": []}


# ---- 係數 ----

OLD = "2026-10-19T08:25:00Z"  # 前一報（不是首報）


def test_median_of_ifs_and_gfs_combined():
    rows = [row("RCTP", [1.3] * 30, [1.5] * 11, run=OLD), row("RCTP", [], [1.7], run=RUN)]
    factors, doc = gustfactor.compute(rows, RUN, ["RCTP"])
    assert factors["RCTP"] == GustFactor(1.3, "airport30d")  # 42 個裡 30 個 1.3
    assert doc["airports"]["RCTP"] == {
        "g": 1.3,
        "n": 42,
        "nIfs": 30,
        "nGfs": 12,
        "basis": "airport30d",
    }


@pytest.mark.parametrize(("value", "g"), [(2.6, 2.0), (1.05, 1.2), (1.57, 1.57)])
def test_clamped_to_range(value, g):
    rows = [row("RCTP", [value] * 40, run=OLD), row("RCTP", run=RUN)]
    factors, _ = gustfactor.compute(rows, RUN, ["RCTP"])
    assert factors["RCTP"] == GustFactor(g, "airport30d")


def test_airport_under_40_uses_all_airports():
    rows = [
        row("RCTP", [1.9] * 39, run=OLD),
        row("RJTT", [1.4] * 50, run=OLD),
        row("RCTP", run=RUN),
    ]
    factors, doc = gustfactor.compute(rows, RUN, ["RCTP", "RJTT", "PGUM"])
    assert factors["RJTT"] == GustFactor(1.4, "airport30d")
    assert factors["RCTP"] == factors["PGUM"] == GustFactor(1.4, "all30d")  # 89 個的中位數
    assert doc["all"] == {"g": 1.4, "n": 89, "nIfs": 89, "nGfs": 0}
    assert doc["airports"]["PGUM"] == {"g": 1.4, "n": 0, "nIfs": 0, "nGfs": 0, "basis": "all30d"}


def test_all_under_40_uses_this_run():
    rows = [row("RCTP", [1.9] * 20, run=OLD), row("RJTT", [1.5, 1.6], [1.7], run=RUN)]
    factors, doc = gustfactor.compute(rows, RUN, ["RCTP", "RJTT"])
    assert factors["RCTP"] == factors["RJTT"] == GustFactor(1.6, "run")
    assert doc["run"] == {"g": 1.6, "n": 3, "nIfs": 2, "nGfs": 1}


def test_no_samples_default_1_4():
    rows = [row("RCTP", [1.9] * 20, run=OLD), row("RCTP", run=RUN)]
    factors, doc = gustfactor.compute(rows, RUN, ["RCTP"])
    assert factors["RCTP"] == GustFactor(1.4, "default")
    assert doc["run"] == {"g": None, "n": 0, "nIfs": 0, "nGfs": 0}


def test_first_run_is_run_basis():
    """首報（窗裡只有這一報）：就算樣本 ≥ 40 也標 `run`。"""
    rows = [row("RCTP", [1.5] * 20, [1.3] * 20), row("RJTT", [1.7] * 20)]
    factors, _ = gustfactor.compute(rows, RUN, ["RCTP", "RJTT"])
    assert factors["RCTP"] == factors["RJTT"] == GustFactor(1.5, "run")


# ---- 檔案與 30 天窗 ----


def _write(history, month, rows):
    path = history / "gustfactor" / f"{month}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def test_window_30_days_across_months(tmp_path):
    now = utc(2026, 11, 5, 8, 25)
    _write(
        tmp_path,
        "2026-10",
        [
            row("RCTP", [1.9], run="2026-10-05T08:24:00Z"),  # 30 天又 1 分鐘前：不算
            row("RCTP", [1.5], run="2026-10-06T08:25:00Z"),  # 剛好 30 天：算
            row("RCTP", [1.6], run="2026-10-20T08:25:00Z"),
        ],
    )
    _write(tmp_path, "2026-09", [row("RCTP", [1.9], run="2026-09-30T08:25:00Z")])
    _write(tmp_path, "2026-11", [row("RCTP", [1.7], run="2026-11-01T08:25:00Z")])
    (tmp_path / "gustfactor" / "2026-11.jsonl").open("a").write("壞掉的行\n{}\n")
    rows = gustfactor.load_window(tmp_path, now)
    assert sorted(r["ifs"][0] for r in rows) == [1.5, 1.6, 1.7]


def test_update_writes_samples_and_latest(tmp_path):
    _write(tmp_path, "2026-10", [row("RCTP", [1.8] * 45, run=OLD)])
    samples = {"RCTP": {"ifs": [1.5, 1.52], "gfs": []}, "RJTT": {"ifs": [], "gfs": [1.31]}}
    factors = gustfactor.update(tmp_path, NOW, samples, ["RCTP", "RJTT"])
    assert factors == {
        "RCTP": GustFactor(1.8, "airport30d"),
        "RJTT": GustFactor(1.8, "all30d"),
    }
    lines = (tmp_path / "gustfactor" / "2026-10.jsonl").read_text("utf-8").splitlines()
    assert [json.loads(x) for x in lines[1:]] == [
        {"run": RUN, "icao": "RCTP", "ifs": [1.5, 1.52], "gfs": []},
        {"run": RUN, "icao": "RJTT", "ifs": [], "gfs": [1.31]},
    ]
    doc = json.loads((tmp_path / "gustfactor" / "latest.json").read_text("utf-8"))
    assert doc["generatedAt"] == RUN
    assert doc["window"] == {"from": "2026-09-20T08:25:00Z", "to": RUN}
    assert doc["all"] == {"g": 1.8, "n": 48, "nIfs": 47, "nGfs": 1}
    assert doc["run"] == {"g": 1.5, "n": 3, "nIfs": 2, "nGfs": 1}
    assert doc["airports"]["RCTP"] == {
        "g": 1.8,
        "n": 47,
        "nIfs": 47,
        "nGfs": 0,
        "basis": "airport30d",
    }
    assert doc["airports"]["RJTT"]["basis"] == "all30d"
    # 同一報再跑一次（重跑）不會重複算
    gustfactor.update(tmp_path, NOW, samples, ["RCTP", "RJTT"])
    doc = json.loads((tmp_path / "gustfactor" / "latest.json").read_text("utf-8"))
    assert doc["all"]["n"] == 48


def test_update_first_run(tmp_path):
    """`history/gustfactor/` 還沒有：`run`。"""
    samples = {"RCTP": {"ifs": [1.5], "gfs": [1.3, 1.4]}}
    factors = gustfactor.update(tmp_path, NOW, samples, ["RCTP"])
    assert factors == {"RCTP": GustFactor(1.4, "run")}


# ---- 驗證報表（tools/gust_factor_report.py）----


def test_report_tool(tmp_path, capsys):
    import importlib.util

    from conftest import ROOT

    spec = importlib.util.spec_from_file_location(
        "gust_factor_report", ROOT / "tools" / "gust_factor_report.py"
    )
    assert spec is not None and spec.loader is not None
    report = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(report)

    def entry(mid, gust):
        return {"id": mid, "gustKt": gust}

    slot = {
        "from": "2026-10-20T06:00:00Z",
        "to": "2026-10-20T12:00:00Z",
        "model": {
            "models": [
                entry("ifs", 40.0),
                entry("gfs", 30.0),
                entry("aifs", 24.0),
                entry("aigfs", None),
            ]
        },
    }
    metar = {"observedAt": "2026-10-20T08:00:00Z", "windKt": 15, "gustKt": 25}
    doc = {
        "generatedAt": RUN,
        "airports": [
            {"icao": "RCTP", "metar": metar, "slots": [slot]},
            # METAR 平均風 < 10 節、太舊的不算
            {"icao": "RJTT", "metar": {**metar, "windKt": 8}, "slots": [slot]},
            {
                "icao": "PGUM",
                "metar": {**metar, "observedAt": "2026-10-20T05:00:00Z"},
                "slots": [slot],
            },
        ],
    }
    (tmp_path / "history").mkdir()
    (tmp_path / "history" / "20261020T0825Z.json").write_text(json.dumps(doc), "utf-8")
    _write(tmp_path / "history", "2026-10", [row("RCTP", [1.5, 1.7], [1.2])])
    assert report.main([str(tmp_path)]) == 0
    out = capsys.readouterr().out
    lines = {ln.split()[0]: ln.split()[1:] for ln in out.splitlines() if ln.strip()}
    assert lines["ifs"] == ["1", "15.0", "1.60"]
    assert lines["gfs"] == ["1", "5.0", "1.20"]
    assert lines["aifs"] == ["1", "-1.0", "0.96"]
    assert lines["aigfs"] == ["0", "-", "-"]
    assert lines["RCTP"] == ["1.60", "2", "1.20", "1", "1.50", "3"]
    assert lines["全部"] == ["1.60", "2", "1.20", "1", "1.50", "3"]
