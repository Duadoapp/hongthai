"""HD22：颱風 29W 驗證報告工具（`tools/report_29w.py`）——手造一個小事件目錄：2 報、3 個機場、
3 格、2 個模式（IFS、估算陣風的 AIFS）、幾小時的 METAR、一份假的航班統計、路徑與假的最佳路徑。"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from conftest import FIXTURES, ROOT, utc

from hongthai.timeutil import iso

_spec = importlib.util.spec_from_file_location("report_29w", ROOT / "tools" / "report_29w.py")
assert _spec and _spec.loader
rpt = importlib.util.module_from_spec(_spec)
sys.modules["report_29w"] = rpt  # dataclass 要找得到模組
_spec.loader.exec_module(rpt)

R1 = utc(2026, 10, 21, 1)  # 定版前
R2 = utc(2026, 10, 22, 5)  # 定版後（切點 10/22 04Z）
A = (utc(2026, 10, 21, 0), utc(2026, 10, 21, 6))
B = (utc(2026, 10, 22, 6), utc(2026, 10, 22, 12))
C = (utc(2026, 10, 23, 6), utc(2026, 10, 23, 12))
D = (utc(2026, 10, 22, 0), utc(2026, 10, 22, 6))
CUTOFF = utc(2026, 10, 22, 4)


def _slot(span, level, gusts=None):
    models = [
        {
            "id": mid,
            "run": "2026-10-20T18:00:00Z",
            "gustKt": g,
            "gustEstimated": mid == "aifs",
            "level": "low",
        }
        for mid, g in (gusts or {}).items()
    ]
    if gusts:
        models.append(
            {"id": "ifs-ens", "run": "2026-10-20T12:00:00Z", "gustKt": None, "level": "low"}
        )
    return {
        "from": iso(span[0]),
        "to": iso(span[1]),
        "level": level,
        "model": {"models": models, "vote": {"total": 5 if gusts else 8}},
    }


def _light(level, status="ok"):
    return {"status": status, "level": level if status == "ok" else None}


def _snapshot(generated, rctp_slots, vhhh_levels):
    vhhh = [_slot(span, lv) for span, lv in vhhh_levels]
    return {
        "generatedAt": iso(generated),
        "runs": {},
        "airports": [
            {
                "icao": "RCTP",
                "slots": rctp_slots,
                "ai": {"claude": _light("high"), "gemini": _light(None, "error")},
            },
            {
                "icao": "VHHH",
                "slots": vhhh,
                "ai": {"claude": _light("low"), "gemini": _light("low")},
            },
            {"icao": "ROAH", "slots": [], "ai": None},
            {"icao": "RJCC", "slots": [_slot(A, "high", {"ifs": 99.0})]},  # 不在事件機場
        ],
    }


def _row(airport, span, total, cancelled):
    half = total // 2
    return {
        "airport": airport,
        "from": iso(span[0]),
        "to": iso(span[1]),
        "asOf": "2026-10-24T00:00:00Z",
        "dep": {"total": half, "cancelled": cancelled, "delayed": 0, "other": 0},
        "arr": {"total": total - half, "cancelled": 0, "delayed": 0, "other": 0},
    }


def _metar(icao, at, wind, gust=None):
    return {"icao": icao, "observedAt": iso(at), "windKt": wind, "gustKt": gust}


def _write(path: Path, doc) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")


def _jsonl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def _pos(source, at, lat, lon, kind="analysis"):
    return {"issuedAt": iso(at), "kind": kind, "validAt": iso(at), "lat": lat, "lon": lon}


@pytest.fixture
def archive(tmp_path):
    history = tmp_path / "data" / "history"
    d = history / "events" / "29W"
    s1 = _snapshot(
        R1,
        [
            _slot(A, "low", {"ifs": 24.0, "aifs": 18.0}),
            _slot(B, "high", {"ifs": 50.0, "aifs": 40.0}),
            _slot(C, "medium", {"ifs": 30.0}),
        ],
        [(A, "low"), (B, "low"), (C, "low")],
    )
    s2 = _snapshot(
        R2,
        [
            _slot(D, "medium", {"ifs": 10.0, "aifs": 6.0}),
            _slot(B, "high", {"ifs": 44.0, "aifs": 30.0}),
            _slot(C, "low", {"ifs": 20.0}),
        ],
        [(D, "low"), (B, "low"), (C, "low")],
    )
    _write(d / f"{R1:%Y%m%dT%H%MZ}.json", s1)
    _write(d / f"{R2:%Y%m%dT%H%MZ}.json", s2)
    _jsonl(
        d / "metar" / "2026-10-21.jsonl",
        [
            _metar("RCTP", utc(2026, 10, 21, 2), 12, 20),
            _metar("RCTP", utc(2026, 10, 21, 4), 15),
            _metar("RCTP", utc(2026, 10, 21, 4), 99),  # 同一站同一時間：留第一筆
        ],
    )
    _jsonl(
        d / "metar" / "2026-10-22.jsonl",
        [_metar("RCTP", utc(2026, 10, 22, 3), 8), _metar("RCTP", utc(2026, 10, 22, 8), 30, 45)],
    )
    _write(
        d / "wn3" / "20261022T0000Z.json",
        {
            "model": "wn3",
            "run": "2026-10-22T00:00:00Z",
            "airports": {"RCTP": [{"from": iso(B[0]), "to": iso(B[1]), "gustKt": 41.0}]},
        },
    )
    _write(
        history / "cancellations" / "2026-10-21.json",
        [_row("RCTP", A, 100, 0)],
    )
    _write(
        history / "cancellations" / "2026-10-22.json",
        [_row("RCTP", B, 100, 40), _row("RCTP", D, 50, 12), _row("VHHH", B, 100, 0)],
    )
    _write(history / "cancellations" / "2026-10-23.json", [_row("RCTP", C, 20, 2)])
    run = "2026-10-21T00:00:00Z"
    _write(
        d / "tracks" / "20261021T0000Z-gfs.json",
        {
            "model": "gfs",
            "run": run,
            "seed": None,
            "points": [
                {"validAt": "2026-10-21T00:00:00Z", "lat": 20.0, "lon": 130.0},
                {"validAt": "2026-10-21T12:00:00Z", "lat": 21.0, "lon": 130.0},
                {"validAt": "2026-10-22T00:00:00Z", "lat": 22.0, "lon": 128.0},
                {"validAt": "2026-10-26T06:00:00Z", "lat": 30.0, "lon": 140.0},  # 超過 120 小時
            ],
            "stop": "weak",
        },
    )
    _write(
        d / "tracks" / "20261021T0000Z-ifs-ens.json",
        {
            "model": "ifs-ens",
            "run": run,
            "storm": {"id": "36W", "name": "CHAMPI"},
            "members": [
                {
                    "member": 1,
                    "points": [{"validAt": "2026-10-21T12:00:00Z", "lat": 21.0, "lon": 129.5}],
                },
                {
                    "member": 2,
                    "points": [{"validAt": "2026-10-21T12:00:00Z", "lat": 21.0, "lon": 128.5}],
                },
            ],
            "mean": [{"validAt": "2026-10-21T12:00:00Z", "lat": 21.0, "lon": 129.0, "n": 2}],
        },
    )
    _write(
        d / "tracks" / "20261021T0000Z-ifs.json",
        {"model": "ifs", "run": run, "storm": None, "members": [], "mean": []},
    )
    _jsonl(
        d / "position" / "jtwc-2026-10-21.jsonl",
        [
            _pos("jtwc", utc(2026, 10, 21, 0), 20.0, 130.0),
            _pos("jtwc", utc(2026, 10, 21, 6), 20.5, 129.5),
            _pos("jtwc", utc(2026, 10, 21, 12), 99.0, 99.0, kind="forecast"),
        ],
    )
    _jsonl(
        d / "position" / "jma-2026-10-21.jsonl",
        [
            _pos("jma", utc(2026, 10, 21, 0), 25.0, 125.0),
            _pos("jma", utc(2026, 10, 21, 12), 21.0, 129.0),
        ],
    )
    events = tmp_path / "events.json"
    _write(
        events,
        {
            "events": [
                {
                    "id": "29W",
                    "name": "CHAMPI（薔琵）",
                    "from": "2026-10-19",
                    "to": "2026-10-28",
                    "airports": ["RCTP", "VHHH", "ROAH"],
                }
            ]
        },
    )
    return tmp_path


def _event(archive):
    from hongthai.config import load_events

    return load_events(archive / "events.json")[0]


def _result(archive, **kw):
    return rpt.build_result(archive / "data", _event(archive), CUTOFF, 0.3, 10, **kw)


# ---- 提前段 ----


@pytest.mark.parametrize(
    ("lead", "want"),
    [(-5, 0), (0, 0), (23.9, 0), (24, 1), (47.5, 1), (96, 4), (119, 4), (120, 4), (120.5, None)],
)
def test_bucket(lead, want):
    assert rpt.bucket(lead) == want


def test_version_split():
    assert rpt.version_of(utc(2026, 10, 22, 3, 59), CUTOFF) == rpt.BEFORE
    assert rpt.version_of(CUTOFF, CUTOFF) == rpt.AFTER


# ---- (a) 陣風 ----


def test_gust_mae_bias_by_lead(archive):
    g = _result(archive).gust
    ifs = [c.summary() for c in g.all["ifs"]]
    # 0–24：R1 的 A（24 對 20）、R2 的 D（10 對 8）與 B（44 對 45）
    assert ifs[0]["n"] == 3
    assert ifs[0]["mae"] == pytest.approx(7 / 3, abs=0.01)
    assert ifs[0]["bias"] == pytest.approx(5 / 3, abs=0.01)
    # 24–48：R1 的 B（50 對 45）；R1、R2 的 C 沒有觀測
    assert (ifs[1]["n"], ifs[1]["bias"]) == (1, 5.0)
    assert [c["n"] for c in ifs[2:]] == [0, 0, 0]
    assert g.no_metar == 2
    # 只算格內最大平均風 ≥ 10 節：D（平均風 8）不算
    windy = g.windy["ifs"][0].summary()
    assert (windy["n"], windy["mae"], windy["bias"]) == (2, 2.5, 1.5)
    aifs = g.all["aifs"][0].summary()
    assert aifs["bias"] == pytest.approx(-19 / 3, abs=0.01)
    assert g.estimated == {"aifs", "wn3"}
    assert "RJCC" not in json.dumps(rpt.to_json(_result(archive)))
    # WN3 的事件檔：提前時間用起報（B 從 06Z 起，起報 00Z → 0–24）
    assert g.all["wn3"][0].pairs == [(41.0, 45.0)]


def test_gust_thresholds(archive):
    g = _result(archive).gust
    b0, b1 = g.all["ifs"][0].summary(), g.all["ifs"][1].summary()
    assert b0["ge37"] == {"hit": 1, "miss": 0, "false": 0, "pod": 1.0}
    assert b1["ge48"] == {"hit": 0, "miss": 0, "false": 1, "pod": None}
    assert g.all["aifs"][0].summary()["ge37"]["miss"] == 1  # 30 對 45


def test_slot_obs_uses_gust_else_wind():
    obs = [rpt.Obs(utc(2026, 10, 21, 2), 20, 12), rpt.Obs(utc(2026, 10, 21, 4), 15, 15)]
    assert rpt.slot_obs(obs, *A) == (20, 15)
    assert rpt.slot_obs(obs, *B) is None


# ---- (b) 等級 ----


def test_levels_per_slot_by_version(archive):
    lv = _result(archive).levels
    assert lv.airports == ["RCTP", "VHHH"]  # ROAH 沒有航班資料
    before, after = lv.slot[rpt.BEFORE], lv.slot[rpt.AFTER]
    s = [c.summary() for c in before["risky"]]
    assert (s[0]["tn"], s[1]["tp"], s[1]["tn"], s[2]["fp"]) == (1, 1, 1, 1)
    assert s[2]["precision"] == 0.0
    a = after["risky"][0].summary()
    assert (a["tp"], a["fp"], a["fn"], a["tn"]) == (2, 0, 0, 1)
    h = after["high"][0].summary()  # D 判中、實際停飛（取消 12 班，率 24%）→ 判高漏報
    assert (h["tp"], h["fn"], h["recall"]) == (1, 1, 0.5)
    # VHHH 沒有航班列的格不算
    assert lv.counts["slotNoTruth"] == 4


def test_levels_window_ai(archive):
    lv = _result(archive).levels
    claude = lv.window["claude"].summary()
    assert (claude["risky"]["tp"], claude["risky"]["tn"]) == (2, 2)
    assert claude["recallByFirstStop"]["risky"][:2] == [1.0, 1.0]  # R2 第一個停飛是 D、R1 是 B
    gemini = lv.window["gemini"].summary()["risky"]
    assert (gemini["tp"], gemini["tn"]) == (0, 2)  # RCTP 是 error 不算
    assert lv.counts["geminiNotOk"] == 2
    assert lv.window[rpt.rule_key(rpt.BEFORE)].risky.tp == 1
    assert lv.window[rpt.rule_key(rpt.AFTER)].risky.tp == 1


def test_stop_definition_threshold():
    row = _row("RCTP", A, 100, 29)
    assert rpt.is_stopped(row, 0.3, 30) is False
    assert rpt.is_stopped(row, 0.29, 30) is True
    assert rpt.is_stopped(row, 0.9, 29) is True
    assert rpt.is_stopped(_row("RCTP", A, 0, 0), 0.3, 10) is None


def test_window_open_until_cancellations_cover_it(archive):
    # 航班資料只到 10/23 08Z：C（10/23 06–12Z）還沒結束，兩報四個機場窗都還沒有結果
    for p in (archive / "data" / "history" / "cancellations").glob("*.json"):
        rows = json.loads(p.read_text(encoding="utf-8"))
        _write(p, [r | {"asOf": "2026-10-23T08:00:00Z"} for r in rows])
    lv = rpt.build_result(archive / "data", _event(archive), CUTOFF, 0.3, 10).levels
    assert lv.counts["windowOpen"] == 4
    assert lv.window["claude"].risky.tp == 0


def test_ai_falls_back_to_history_records(archive):
    rec = {(str(R1), "ROAH"): {"claude": {"status": "ok", "level": "medium"}}}
    doc = _snapshot(R1, [], [])
    r = rpt.parse_report(doc, "x", ["ROAH"], rec)
    assert r.airports["ROAH"].ai == {"claude": "medium", "gemini": None}


def test_legacy_snapshot_model_entries():
    model = {"ec": {"p10": 0.5, "hresGustMs": 10.0}, "gfs": {"gustKt": 20.0}}
    runs = {"ecmwf": "2026-10-18T06:00:00Z", "ecmwfEns": "2026-10-18T00:00:00Z", "gfs": "x"}
    out = {e["id"]: e for e in rpt.model_entries(model, runs)}
    assert out["ifs"]["gustKt"] == pytest.approx(19.44, abs=0.01)
    assert out["ifs-ens"]["gustKt"] is None and out["ifs-ens"]["run"] == runs["ecmwfEns"]
    assert out["gfs"]["gustKt"] == 20.0


# ---- (c) 路徑 ----


def test_parse_atcf_fixture():
    pts = rpt.parse_atcf((FIXTURES / "bwp292026_sample.dat").read_text(encoding="utf-8"))
    assert len(pts) == 5  # 00Z 三行風圈只留一點
    assert pts[0] == (utc(2026, 10, 21, 0), 20.0, 130.0)
    assert pts[-1] == (utc(2026, 10, 22, 0), 22.0, 128.0)
    assert rpt.parse_atcf("WP, 29, 2026102100, , BEST, 0, 50S, 1700W, 30")[0][1:] == (-5.0, -170.0)


def test_parse_jma_bst_fixture():
    storms = rpt.parse_jma_bst((FIXTURES / "jma_bst_sample.txt").read_text(encoding="utf-8"))
    assert [(s.number, s.name, len(s.points)) for s in storms] == [
        ("2629", "OTHERSTORM", 3),
        ("2630", "CHAMPI", 5),
    ]
    assert storms[1].points[0] == (utc(2026, 10, 21, 0), 19.9, 130.1)
    assert rpt.pick_bst(storms, None, "CHAMPI").number == "2630"
    assert rpt.pick_bst(storms, "2629", "CHAMPI").name == "OTHERSTORM"
    with pytest.raises(ValueError, match="2631"):
        rpt.pick_bst(storms, "2631", "CHAMPI")
    with pytest.raises(ValueError, match="--jma-id"):
        rpt.pick_bst(storms, None, "NOPE")
    assert rpt.pick_bst(storms[1:], None, "NOPE").number == "2630"  # 單一颱風的檔


def test_track_interpolation():
    t = rpt.Track("x", [(utc(2026, 10, 21, 6), 20.0, 130.0), (utc(2026, 10, 21, 18), 21.0, 128.0)])
    assert t.at(utc(2026, 10, 21, 12)) == (20.5, 129.0)
    assert t.at(utc(2026, 10, 21, 6)) == (20.0, 130.0)
    assert t.at(utc(2026, 10, 21, 5)) is None
    assert t.at(utc(2026, 10, 21, 19)) is None
    gap = rpt.Track(
        "x", [(utc(2026, 10, 21, 0), 20.0, 130.0), (utc(2026, 10, 21, 18), 21.0, 128.0)]
    )
    assert gap.at(utc(2026, 10, 21, 6)) is None  # 前後相隔 18 小時 > 12


def test_track_errors_against_jtwc(archive):
    res = _result(archive, jtwc=FIXTURES / "bwp292026_sample.dat")
    (tr,) = res.tracks
    assert not tr.provisional and tr.label.startswith("JTWC")
    gfs = [c.summary() for c in tr.models["gfs"]]
    one_deg = rpt.distance_km(21.0, 130.0, 21.0, 129.0)
    assert 100 < one_deg < 106
    assert gfs[0]["n"] == 2  # 0、12 小時；120 小時以後的不算
    assert gfs[0]["mean"] == pytest.approx(one_deg / 2, abs=0.1)
    assert gfs[1] == {"n": 1, "mean": 0.0, "median": 0.0}
    ens = tr.models["ifs-ens"][0].summary()
    assert ens == {"n": 1, "mean": 0.0, "median": 0.0}  # 中位數位置正好在最佳路徑上
    half = rpt.distance_km(21.0, 129.5, 21.0, 129.0)
    assert tr.members["ifs-ens"][0].summary()["mean"] == pytest.approx(half, abs=0.1)
    assert tr.spread["ifs-ens"][0].summary()["mean"] == pytest.approx(half, abs=0.1)
    assert tr.models["ifs"][0].summary()["n"] == 0  # 路徑產品裡沒有這顆
    stops = {(t.model, t.stop, t.steps) for t in res.track_runs}
    assert ("ifs", "none", 0) in stops and ("gfs", "weak", 4) in stops


def test_jtwc_and_jma_side_by_side(archive):
    res = _result(
        archive,
        jtwc=FIXTURES / "bwp292026_sample.dat",
        jma=FIXTURES / "jma_bst_sample.txt",
    )
    assert [t.label.split("（")[0] for t in res.tracks] == ["JTWC 最佳路徑", "JMA 最佳路徑"]
    assert "2630 CHAMPI" in res.tracks[1].label
    assert res.tracks[1].models["gfs"][1].summary()["mean"] > 0  # JMA 那份 22.1N 127.9E


def test_provisional_truth_jtwc_then_jma(archive):
    res = _result(archive)
    (tr,) = res.tracks
    assert tr.provisional and "暫時真相" in tr.label
    # 00Z：JTWC 有（20.0, 130.0）→ 誤差 0
    # 12Z：JTWC 只到 06Z（forecast 不算），改用 JMA 的 21.0, 129.0
    gfs = tr.models["gfs"][0]
    assert gfs.errors[0] == 0.0
    assert gfs.errors[1] == pytest.approx(rpt.distance_km(21.0, 130.0, 21.0, 129.0), abs=0.1)
    assert tr.used["jtwc"] >= 1 and tr.used["jma"] >= 1
    assert tr.no_truth == 1  # gfs 10/22 00Z 兩份現報都內插不到


# ---- 完整度與輸出 ----


def test_completeness(archive):
    res = _result(archive)
    assert [len(rpt.models_present(r)) for r in res.reports] == [3, 3]  # ifs、ifs-ens、aifs
    assert [r.votes for r in res.reports] == [8, 8]
    assert res.reports[0].ai_ok == {"claude": 2, "gemini": 1}
    assert res.metar_hours == {"RCTP": 4, "VHHH": 0, "ROAH": 0}
    assert res.metar_span == 31  # 10/21 02Z – 10/22 08Z


def test_main_writes_markdown_and_json(archive, capsys):
    out, js = archive / "report" / "29W.md", archive / "report" / "29W.json"
    code = rpt.main(
        [
            "--archive",
            str(archive / "data"),
            "--events",
            str(archive / "events.json"),
            "--out",
            str(out),
            "--json",
            str(js),
        ]
    )
    assert code == 0
    md = out.read_text(encoding="utf-8")
    for heading in ("## 摘要", "## (a)", "## (b)", "## (c)", "## 資料完整度", "## 附錄：每報"):
        assert heading in md
    assert "暫時真相：現報" in md
    assert "aifs*" in md
    assert "取消率 ≥ 30% 或取消 ≥ 10 班" in md
    doc = json.loads(js.read_text(encoding="utf-8"))
    assert doc["cutoff"] == "2026-10-22T04:00:00Z"
    assert [r["version"] for r in doc["reports"]] == [rpt.BEFORE, rpt.AFTER]
    assert doc["tracks"][0]["provisional"] is True
    assert doc["levels"]["airports"] == ["RCTP", "VHHH"]
    printed = capsys.readouterr().out
    assert "## 摘要" in printed and "定版前 1 報、定版後 1 報" in printed


def test_main_unknown_event(archive, capsys):
    code = rpt.main(
        [
            "--archive",
            str(archive / "data"),
            "--events",
            str(archive / "events.json"),
            "--event",
            "30W",
        ]
    )
    assert code == 1
