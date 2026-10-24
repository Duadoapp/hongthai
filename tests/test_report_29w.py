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


def test_window_truncated_to_cancellations_as_of(archive):
    # HD36：航班資料只到 10/23 08Z → 實測的最後時間是 asOf（早於實測截止）；C（10/23 06–12Z）
    # 還沒結束，從四個窗丟掉（以前整個窗算「還沒結束」），剩下的照比
    for p in (archive / "data" / "history" / "cancellations").glob("*.json"):
        rows = json.loads(p.read_text(encoding="utf-8"))
        _write(p, [r | {"asOf": "2026-10-23T08:00:00Z"} for r in rows])
    lv = rpt.build_result(archive / "data", _event(archive), CUTOFF, 0.3, 10).levels
    assert lv.truth_last == utc(2026, 10, 23, 8)
    assert (lv.counts["windowTruncated"], lv.counts["windowNoTruth"]) == (4, 0)
    assert lv.counts["slotPastTruth"] == 4
    claude = lv.window["claude"].risky
    assert (claude.tp, claude.tn) == (2, 2)  # 桃園 B 停飛、香港沒有
    assert lv.window_full["claude"].risky.summary()["tp"] == 0  # 每個窗都被截短


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


# ---- HD36：--until、--truth-until ----


def _t(*args):
    return utc(2026, 10, *args)


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("2026-10-26T24:00+08:00", _t(26, 16)),
        ("2026-10-26T24:00:00+08:00", _t(26, 16)),
        ("2026-10-31T24:00Z", utc(2026, 11, 1, 0)),
        ("2026-10-25T14:00+08:00", _t(25, 6)),
        ("2026-10-25T08:25Z", _t(25, 8, 25)),
        ("2026-10-25T08:25:00+00:00", _t(25, 8, 25)),
    ],
)
def test_parse_cli_time(text, want):
    assert rpt.parse_cli_time(text) == want


@pytest.mark.parametrize("text", ["2026-10-25T14:00", "2026-10-25", "明天", "2026-10-26T25:00Z"])
def test_parse_cli_time_rejects(text):
    with pytest.raises(ValueError):
        rpt.parse_cli_time(text)


def test_default_truth_until(archive):
    from dataclasses import replace
    from datetime import date

    event = _event(archive)
    assert rpt.default_truth_until(event) == _t(28, 16)  # fixture 的 to 是 10-28
    assert rpt.default_truth_until(replace(event, end=date(2026, 10, 26))) == _t(26, 16)
    assert _result(archive).truth_until == _t(28, 16)


def test_select_until():
    xs = [_t(21), _t(22), _t(23)]
    same = rpt.select_until(xs, lambda t: t, _t(22))
    assert same == ([_t(21), _t(22), _t(23)], True)  # 剛好等於 22 的：22 算，再加之後的第一報
    assert rpt.select_until(xs, lambda t: t, _t(21, 12)) == ([_t(21), _t(22)], True)
    assert rpt.select_until(xs, lambda t: t, _t(24)) == (xs, False)  # 之後沒有報
    assert rpt.select_until(xs, lambda t: t, None) == (xs, False)
    assert rpt.select_until(xs, lambda t: t, _t(20)) == ([_t(21)], True)


R3 = utc(2026, 10, 23, 1)


def _add_r3_and_wn3(archive):
    d = archive / "data" / "history" / "events" / "29W"
    _write(d / f"{R3:%Y%m%dT%H%MZ}.json", _snapshot(R3, [_slot(C, "high", {"ifs": 60.0})], []))
    for run in (_t(23), _t(24)):
        _write(
            d / "wn3" / f"{run:%Y%m%dT%H%MZ}.json",
            {"model": "wn3", "run": iso(run), "airports": {"RCTP": []}},
        )


def test_until_reports_and_wn3(archive):
    _add_r3_and_wn3(archive)
    # 剛好等於 R1：R1 算、再加之後的第一報 R2；R3 不算。WN3 起報 10/22 00Z 前沒有 → 只算 10/22
    res = _result(archive, until=iso(R1))
    assert [r.generated for r in res.reports] == [R1, R2]
    assert res.until_has_next
    assert res.excluded["reports"] == 1 and res.excluded["wn3"] == 2
    # 介於 R1、R2：一樣多算下一報 R2
    res = _result(archive, until="2026-10-21T12:00+08:00")
    assert [r.generated for r in res.reports] == [R1, R2]
    # 剛好等於 WN3 10/22 00Z：10/22、10/23 兩報，10/24 不算
    res = _result(archive, until="2026-10-22T00:00Z")
    assert res.excluded["wn3"] == 1 and len(res.reports) == 2
    # 之後沒有報
    res = _result(archive, until="2026-10-30T00:00Z")
    assert len(res.reports) == 3 and not res.until_has_next
    assert (res.excluded["reports"], res.excluded["wn3"]) == (0, 0)
    assert "時間之後還沒有報" in "\n".join(rpt.summary_lines(res))


def test_until_tracks_follow_kept_reports(archive):
    d = archive / "data" / "history" / "events" / "29W"
    _write(
        d / "tracks" / "20261020T1800Z-ifs.json",
        {"model": "ifs", "run": "2026-10-20T18:00:00Z", "storm": None, "members": [], "mean": []},
    )
    # 兩報用的 ifs 都是 10/20 18Z：那份路徑收，10/21 00Z 起報的（沒有報用過）不收
    res = _result(archive, until=iso(R2))
    assert {(t.model, t.run) for t in res.track_runs} == {("ifs", utc(2026, 10, 20, 18))}
    assert res.excluded["tracks"] == 3
    assert len(_result(archive).track_runs) == 4  # 不給 --until：全部


def test_truth_until_gust_slots(archive):
    # T＝10/22 10Z：B（06–12Z）、C 的格超過；R1 的 A、R2 的 D 照算；WN3 的 B 也超過
    g = _result(archive, truth_until=_t(22, 10)).gust
    assert g.past_truth == 5
    assert g.no_metar == 0  # 原本沒有觀測的 C 現在算超過實測截止
    assert g.all["ifs"][0].summary()["n"] == 2
    assert g.all["ifs"][1].summary()["n"] == 0
    assert "wn3" not in g.all


def test_truth_until_drops_metar_after_t(archive):
    metars = rpt.load_metars(archive / "data" / "history" / "events" / "29W", _t(22, 5))
    assert [o.at for o in metars["RCTP"]][-1] == _t(22, 3)  # 10/22 08Z 那筆不用


def test_truth_until_levels_truncate_windows(archive):
    # T＝10/22 10Z（早於航班 asOf 10/24）：B、C 結束得晚，每格算超過；窗截到 A／D
    lv = _result(archive, truth_until=_t(22, 10)).levels
    assert lv.truth_last == _t(22, 10)
    assert lv.counts["slotPastTruth"] == 8
    assert (lv.counts["windowTruncated"], lv.counts["windowNoTruth"]) == (4, 0)
    claude = lv.window["claude"].summary()
    # 桃園：R1 截短後只剩 A（沒停飛）→ 判高誤報；R2 剩 D（停飛）→ 命中，first＝D 的 0–24
    # 香港：截短後剩的 A／D 都沒有航班列，HD37 起不當成「沒停飛」（以前算兩個 TN）
    assert (claude["risky"]["tp"], claude["risky"]["fp"], claude["risky"]["tn"]) == (1, 1, 0)
    assert lv.counts["windowNoFlights"] == 2
    assert claude["recallByFirstStop"]["risky"][0] == 1.0
    # 規則燈的預測仍取整個 0–120 小時：R1 桃園最高是 B 的 high → 誤報
    assert lv.window[rpt.rule_key(rpt.BEFORE)].high.fp == 1
    # 只算完整窗：四個都被截短，什麼都沒有
    for w in lv.window_full.values():
        assert w.risky.tp + w.risky.fp + w.risky.fn + w.risky.tn == 0


def test_truth_until_window_empty_after_truncation(archive):
    lv = _result(archive, truth_until=_t(21, 5)).levels  # A 06Z 才結束：每個窗一格不剩
    assert (lv.counts["windowTruncated"], lv.counts["windowNoTruth"]) == (4, 4)
    assert lv.window["claude"].risky.summary()["tp"] == 0
    assert lv.counts["claudeNotOk"] == 0  # 不算的窗也不算 AI 的 not ok


def test_window_complete_matches_when_nothing_dropped(archive):
    lv = _result(archive).levels
    assert lv.counts["windowTruncated"] == 0
    for k, w in lv.window.items():
        assert lv.window_full[k].summary() == w.summary()


def test_truth_until_tracks(archive):
    # T＝10/21 06Z：gfs 12Z、10/22 00Z 與系集中位數 12Z 的點超過
    res = _result(archive, jtwc=FIXTURES / "bwp292026_sample.dat", truth_until=_t(21, 6))
    (tr,) = res.tracks
    assert tr.past_truth == 3
    assert tr.models["gfs"][0].summary() == {"n": 1, "mean": 0.0, "median": 0.0}
    assert tr.members["ifs-ens"][0].summary()["n"] == 0  # 成員 12Z 也不比
    assert tr.spread["ifs-ens"][0].summary()["n"] == 2  # 離散不用真相，照算


def test_truth_clipped_to_truth_until(archive):
    d = archive / "data" / "history" / "events" / "29W"
    bwp = FIXTURES / "bwp292026_sample.dat"
    (jtwc,) = rpt.truths(d, _event(archive), bwp, None, None, _t(21, 9))
    assert max(t for t, _, _ in jtwc.tracks[0].points) == _t(21, 6)
    assert jtwc.at(_t(21, 8)) is None  # 不拿 12Z（截止後）的點內插
    (prov,) = rpt.truths(d, _event(archive), None, None, None, _t(21, 9))
    assert [len(t.points) for t in prov.tracks] == [2, 1]  # JTWC 00、06Z；JMA 只剩 00Z


HD37_LEVEL_FIELDS = (
    "fewFlights",
    "slotFew",
    "windowFew",
    "windowCompleteFew",
    "truthSources",
    "flightClasses",
    "reclassified",
    "unknownStatuses",
)


def _hd36_fields(doc: dict) -> dict:
    """HD37 加的欄位拿掉，剩下的要和 HD37 前一模一樣。"""
    doc = json.loads(json.dumps(doc))
    for k in HD37_LEVEL_FIELDS:
        doc["levels"].pop(k)
    return doc


def _digest(doc: dict) -> str:
    import hashlib

    return hashlib.sha256(json.dumps(doc, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


# HD37 前的程式（HD36）對同一個 fixture 的 `to_json`（sort_keys 後的 sha256）
HD36_DIGEST_BOTH = "576d040a4fb143f1efa2005311157adc38990aa962702b7b3eeae475d78b94f1"
HD36_DIGEST_PLAIN = "ccc142b005e0db03688150f4f3702a1fb87c6234a0aec99ac242c57adac01fff"


def _old_fields(doc: dict) -> dict:
    """HD36、HD37 加的欄位拿掉，剩下的要和 HD36 前一模一樣。"""
    doc = _hd36_fields(doc)
    for k in (
        "until",
        "untilHasNext",
        "lastReport",
        "excludedByUntil",
        "truthUntil",
        "truthUntilDefault",
    ):
        doc.pop(k)
    doc["gust"].pop("pastTruth")
    for k in ("truthLast", "windowComplete"):
        doc["levels"].pop(k)
    for k in ("slotPastTruth", "windowTruncated", "windowNoTruth"):
        assert doc["levels"]["skipped"].pop(k) == 0
    for t in doc["tracks"]:
        t.pop("pastTruth")
    return doc


def test_no_new_args_same_as_before(archive):
    import hashlib

    def digest(doc):
        body = json.dumps(_old_fields(doc), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(body.encode()).hexdigest()

    # HD36 前的程式對同一個 fixture 的 `to_json`（sort_keys 後的 sha256）
    both = _result(
        archive, jtwc=FIXTURES / "bwp292026_sample.dat", jma=FIXTURES / "jma_bst_sample.txt"
    )
    assert digest(rpt.to_json(both)) == (
        "8ea11ca0e0f4fa20e98334d16ed0cb76dc9ccdccebcdc961cfe4bc20379b4593"
    )
    assert digest(rpt.to_json(_result(archive))) == (
        "acea80bda42ca8a97f74057c69c4b064b1ed412e77dc0d7c20060b9e2a6edf7f"
    )


def test_main_until_and_truth_until(archive, capsys):
    js = archive / "report" / "29W.json"
    code = rpt.main(
        [
            "--archive",
            str(archive / "data"),
            "--events",
            str(archive / "events.json"),
            "--until",
            "2026-10-21T12:00+08:00",
            "--truth-until",
            "2026-10-22T24:00+08:00",
            "--out",
            str(archive / "report" / "29W.md"),
            "--json",
            str(js),
        ]
    )
    assert code == 0
    doc = json.loads(js.read_text(encoding="utf-8"))
    assert doc["until"] == "2026-10-21T12:00+08:00"
    assert doc["lastReport"] == "2026-10-22T05:00:00Z"
    assert doc["truthUntil"] == "2026-10-22T16:00:00Z" and doc["truthUntilDefault"] is False
    assert doc["levels"]["skipped"]["windowTruncated"] == 4  # C（10/23）在兩報兩個機場的窗都超過
    assert "windowComplete" in doc["levels"]
    printed = capsys.readouterr().out
    until = "`--until` 2026-10-21T12:00+08:00 之後的第一報"
    assert f"預報算到：2026-10-22T05:00:00Z（台北 10/22 13:00；{until}）" in printed
    assert "實測到：2026-10-22T16:00:00Z（台北 10/23 00:00；`--truth-until`）" in printed
    md = (archive / "report" / "29W.md").read_text(encoding="utf-8")
    assert "對照：只算完整窗" in md and "超過實測截止" in md


@pytest.mark.parametrize("flag", ["--until", "--truth-until"])
def test_main_bad_time(archive, capsys, flag):
    code = rpt.main(
        ["--archive", str(archive / "data"), "--events", str(archive / "events.json"), flag, "x"]
    )
    assert code == 1
    assert flag in capsys.readouterr().err


# ---- HD37：逐班航班補停飛實測、班次少、狀態重新分類 ----


def _flight(airport, direction, flight, sched, cls, status="", t=None, source="tdx"):
    return {
        "t": iso(t or _t(24, 0)),
        "airport": airport,
        "dir": direction,
        "flight": flight,
        "codeshares": [],
        "peer": "TPE",
        "schedUtc": iso(sched),
        "estUtc": None,
        "actUtc": None,
        "status": status,
        "class": cls,
        "source": source,
    }


def _add_roah(archive, rows=None):
    """ROAH（`cancellations/` 沒有）補逐班紀錄與兩報的格：B 3 班取消 1（停飛、班次少）、
    D 4 班取消 1（沒停飛、不算班次少）、C 1 班轉降（沒停飛、班次少）。"""
    d = archive / "data" / "history" / "events" / "29W"
    if rows is None:
        rows = [
            _flight("ROAH", "dep", "NH1", _t(22, 7), "cancelled", "取消"),
            _flight("ROAH", "arr", "NH2", _t(22, 8), "normal"),
            _flight("ROAH", "arr", "NH3", _t(22, 11, 59), "normal"),
            *[_flight("ROAH", "dep", f"JL{i}", _t(22, i), "normal") for i in (1, 2, 3)],
            _flight("ROAH", "arr", "JL9", _t(22, 5), "cancelled", "取消"),
            _flight("ROAH", "arr", "NU1", _t(23, 7), "other", "轉降"),
        ]
    _jsonl(d / "flights" / "2026-10-22.jsonl", rows)
    levels = {
        R1: [(A, "low"), (B, "medium"), (C, "low")],
        R2: [(D, "medium"), (B, "high"), (C, "low")],
    }
    for at, spans in levels.items():
        p = d / f"{at:%Y%m%dT%H%MZ}.json"
        doc = json.loads(p.read_text(encoding="utf-8"))
        for a in doc["airports"]:
            if a["icao"] == "ROAH":
                a["slots"] = [_slot(span, lv) for span, lv in spans]
        _write(p, doc)


def _truth(archive, until=None):
    history = archive / "data" / "history"
    canc = rpt.load_cancellations(history)
    tz = rpt.airport_tz(ROOT / "airports.json")
    rpt.load_flights(history / "events" / "29W", canc, ["RCTP", "VHHH", "ROAH"], tz, until)
    return canc


def test_flights_latest_row_per_flight(archive):
    _add_roah(
        archive,
        [
            _flight("ROAH", "dep", "NH1", _t(22, 7), "normal", t=_t(22, 1)),
            _flight("ROAH", "dep", "NH1", _t(22, 7), "cancelled", "取消", t=_t(22, 6)),
            # 同 `t`：取檔裡後面的那行
            _flight("ROAH", "arr", "NH2", _t(22, 8), "cancelled", "取消", t=_t(22, 6)),
            _flight("ROAH", "arr", "NH2", _t(22, 8), "normal", t=_t(22, 6)),
            # 不同 `source` 算不同班；只讀 `tdx`
            _flight("ROAH", "arr", "NH2", _t(22, 8), "cancelled", source="other", t=_t(22, 9)),
        ],
    )
    a = _truth(archive).by_airport["ROAH"]
    assert a.source == rpt.FLIGHTS
    assert a.last == _t(22, 6)  # 只看 tdx 的行
    row = a.rows[B[0]]
    assert (row["dep"]["total"], row["dep"]["cancelled"]) == (1, 1)
    assert (row["arr"]["total"], row["arr"]["cancelled"]) == (1, 0)


def test_flights_slot_by_schedule(archive):
    _add_roah(
        archive,
        [
            _flight("ROAH", "dep", "A1", _t(22, 5, 59), "cancelled"),
            _flight("ROAH", "dep", "A2", _t(22, 6), "normal"),
        ],
    )
    a = _truth(archive).by_airport["ROAH"]
    assert sorted(a.rows) == [D[0], B[0]]
    assert a.rows[D[0]]["dep"]["cancelled"] == 1 and a.rows[B[0]]["dep"]["cancelled"] == 0


def test_few_flights_boundary(archive):
    _add_roah(archive)
    canc = _truth(archive)
    # B 3 班取消 1：33% ≥ 30% 停飛，班次少；D 4 班取消 1：25% 沒停飛，不算班次少
    assert canc.stopped("ROAH", *B, 0.3, 10) == (True, True)
    assert canc.stopped("ROAH", *D, 0.3, 10) == (False, False)
    assert canc.stopped("ROAH", *A, 0.3, 10) == (None, False)  # 那格沒有航班
    # `cancellations/` 的機場用同一個標準：C 20 班不算班次少
    assert canc.stopped("RCTP", *C, 0.3, 10) == (False, False)
    assert rpt.FEW_FLIGHTS == 4


@pytest.mark.parametrize(
    ("status", "cls", "want"),
    [
        ("加班", "other", ("normal", "extra")),
        ("加班Extra", "other", ("normal", "extra")),
        ("轉降", "other", ("diverted", "diverted")),
        ("轉降桃園DivertTPE", "other", ("diverted", "diverted")),
        # 表定 10/23 08:30（東京）
        ("預計09:30到站", "other", ("delayed", "estDelayed")),  # 晚 60 分鐘
        ("預計09:29離站", "other", ("normal", "estOnTime")),
        ("預計08:00出發", "other", ("normal", "estOnTime")),
        ("預計10/23 09:45到站", "other", ("delayed", "estDelayed")),
        ("預計2026/10/23 08:40到站", "other", ("normal", "estOnTime")),
        ("預計10/24 08:00到站", "other", ("delayed", "estDelayed")),  # 有日期：隔天
        ("檢查", "other", ("other", None)),
        ("預計13/40 09:00到站", "other", ("other", None)),  # 日期不對
        ("取消", "cancelled", ("cancelled", None)),
        ("", "normal", ("normal", None)),
    ],
)
def test_reclassify(status, cls, want):
    from zoneinfo import ZoneInfo

    row = _flight("ROAH", "arr", "X1", _t(22, 23, 30), cls, status)
    assert rpt.reclassify(row, ZoneInfo("Asia/Tokyo")) == want


def test_reclassify_estimate_without_date_crosses_midnight():
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("Asia/Taipei")
    row = _flight("RCMQ", "arr", "X1", _t(23, 15, 30), "other", "預計00:40到站")  # 表定 23:30
    assert rpt.reclassify(row, tz) == ("delayed", "estDelayed")  # 隔天 00:40，晚 70 分鐘
    row = _flight("RCMQ", "arr", "X1", _t(23, 16, 30), "other", "預計23:50到站")  # 表定隔天 00:30
    assert rpt.reclassify(row, tz) == ("normal", "estOnTime")  # 前一天 23:50（提早）


def test_flights_reclassified_counts(archive):
    _add_roah(
        archive,
        [
            _flight("ROAH", "arr", "A1", _t(22, 7), "other", "轉降"),
            _flight("ROAH", "arr", "A2", _t(22, 7), "other", "加班"),
            _flight("ROAH", "arr", "A3", _t(22, 7), "other", "預計18:00到站"),  # 表定 16:00
            _flight("ROAH", "arr", "A4", _t(22, 7), "other", "檢查"),
            _flight("ROAH", "arr", "A5", _t(22, 8), "other", "檢查"),
            _flight("ROAH", "arr", "A6", _t(22, 8), "cancelled", "取消"),
            _flight("ROAH", "arr", "A7", _t(25, 8), "other", "回航"),  # 實測截止之後結束
        ],
    )
    canc = _truth(archive)
    row = canc.by_airport["ROAH"].rows[B[0]]["arr"]
    assert row == {"total": 6, "cancelled": 1, "delayed": 1, "diverted": 1, "other": 2}
    assert rpt.is_stopped({"arr": row}, 0.3, 10) is False  # 轉降不算取消（1/6）
    assert dict(canc.classes) == {
        "diverted": 1,
        "normal": 1,
        "delayed": 1,
        "other": 2,
        "cancelled": 1,
    }
    assert dict(canc.reclassified) == {"diverted": 1, "extra": 1, "estDelayed": 1}
    assert canc.unknown.most_common() == [("檢查", 2)]


def test_per_airport_truth_last_and_truth_until(archive):
    rows = [
        _flight("ROAH", "dep", "NH1", _t(22, 7), "cancelled", t=_t(22, 1)),
        _flight("ROAH", "dep", "NH2", _t(22, 8), "normal", t=_t(22, 13)),
        _flight("ROAH", "dep", "NH3", _t(23, 7), "cancelled", t=_t(22, 2)),
    ]
    _add_roah(archive, rows)
    canc = _truth(archive)
    assert canc.by_airport["ROAH"].last == _t(22, 13)  # 整批 tdx 最新的 t（不是桃園的 asOf）
    assert canc.last("ROAH", None) == _t(22, 13)
    assert canc.last("ROAH", _t(22, 10)) == _t(22, 10)
    assert canc.last("RCTP", None) == utc(2026, 10, 24)
    assert canc.stopped("ROAH", *C, 0.3, 10) == (None, False)  # C 在 ROAH 的最後時間之後結束
    lv = _result(archive).levels
    src = lv.sources["ROAH"]
    assert (src.source, src.last, src.used, src.slots) == ("flights", _t(22, 13), _t(22, 13), 1)
    assert lv.sources["RCTP"].used == utc(2026, 10, 24)
    assert lv.truth_last == utc(2026, 10, 24)  # 各機場最晚的
    lv = _result(archive, truth_until=_t(22, 10)).levels
    assert lv.sources["ROAH"].used == _t(22, 10) and lv.sources["ROAH"].slots == 0


def test_flights_truth_last_is_batch_latest_t(archive):
    # ROAH 最後一行很早（10/22 01Z），但同一批 TDX 有更新的 t：桃園（取消統計的機場、逐班不用）
    # 與不在事件裡的綠島 → ROAH 的最後時間是整批最新的 10/22 13Z，B（06–12Z）照算
    rows = [
        _flight("ROAH", "dep", "NH1", _t(22, 7), "cancelled", t=_t(22, 1)),
        _flight("ROAH", "arr", "NH2", _t(22, 8), "normal", t=_t(22, 1)),
        _flight("RCTP", "dep", "CI1", _t(22, 9), "normal", t=_t(22, 12)),
        _flight("RCGI", "dep", "B71", _t(22, 9), "normal", t=_t(22, 13)),
        _flight("RCGI", "dep", "B72", _t(22, 9), "normal", t=_t(23, 1), source="other"),
    ]
    _add_roah(archive, rows)
    canc = _truth(archive)
    assert canc.by_airport["ROAH"].last == _t(22, 13)
    assert canc.stopped("ROAH", *B, 0.3, 10) == (True, True)
    assert canc.stopped("ROAH", *C, 0.3, 10) == (None, False)  # 10/23 12Z 才結束
    assert set(canc.by_airport) == {"RCTP", "VHHH", "ROAH"}  # 綠島不在事件裡，只用來算 t
    assert canc.last("RCTP", None) == utc(2026, 10, 24)  # 取消統計照舊用 asOf
    src = _result(archive, truth_until=_t(22, 12)).levels.sources["ROAH"]
    assert (src.last, src.used, src.slots) == (_t(22, 13), _t(22, 12), 1)


def test_cancellations_preferred_over_flights(archive):
    # 桃園兩種都有：照舊用 `cancellations/`，逐班的不看；數字和 HD37 前一樣
    _add_roah(archive, [_flight("RCTP", "dep", f"CI{i}", _t(22, 7), "cancelled") for i in range(9)])
    canc = _truth(archive)
    assert canc.by_airport["RCTP"].source == rpt.CANCELLATIONS
    assert "ROAH" not in canc.by_airport
    assert canc.by_airport["RCTP"].rows[B[0]]["dep"]["total"] == 50
    assert _digest(_hd36_fields(rpt.to_json(_result(archive)))) == HD36_DIGEST_PLAIN


def test_levels_with_flights_and_few(archive):
    _add_roah(archive)
    lv = _result(archive).levels
    assert lv.airports == ["RCTP", "ROAH", "VHHH"]
    few_before, few_after = lv.slot_few[rpt.BEFORE]["risky"], lv.slot_few[rpt.AFTER]["risky"]
    # R1：B 判中、停飛、班次少 → 24–48 TP；C 判低、沒停飛（轉降 1 班）、班次少 → 48–72 TN
    assert (few_before[1].tp, few_before[2].tn) == (1, 1)
    # R2：B 判高、停飛 → 0–24 TP；C → 24–48 TN；D 4 班不算班次少
    assert (few_after[0].tp, few_after[0].fp, few_after[1].tn) == (1, 0, 1)
    assert lv.slot[rpt.AFTER]["risky"][0].fp == 1  # D：判中、沒停飛（只在主表）
    # 每報每機場：ROAH 兩報的窗停飛都只靠 B（班次少）→ 列進班次少
    assert lv.window_few[rpt.rule_key(rpt.BEFORE)].risky.tp == 1
    assert lv.window_few[rpt.rule_key(rpt.AFTER)].high.tp == 1
    assert lv.window_few["claude"].risky.tp == 0  # ROAH 沒有 AI
    assert lv.counts["windowNoFlights"] == 0


def test_few_window_rule():
    assert rpt.few_window([(0, False, False), (1, True, True)]) is True
    assert rpt.few_window([(0, True, False), (1, True, True)]) is False
    assert rpt.few_window([(0, False, True), (1, None, False)]) is True
    assert rpt.few_window([(0, False, True), (1, False, False)]) is False
    assert rpt.few_window([(0, None, False)]) is False


def test_window_without_any_flights_not_counted(archive):
    # ROAH 只有 10/25 的航班：兩報的窗（A–C、D–C）都沒有航班列 → 不當成「沒停飛」
    _add_roah(archive, [_flight("ROAH", "dep", "NH1", _t(25, 7), "cancelled")])
    lv = _result(archive).levels
    assert lv.counts["windowNoFlights"] == 2
    assert lv.window[rpt.rule_key(rpt.BEFORE)].risky.fp == 0


def test_render_and_json_with_flights(archive):
    _add_roah(archive)
    res = _result(archive)
    md = rpt.render(res)
    assert "### 停飛實測" in md
    last = "2026-10-24T00:00:00Z"
    assert f"| ROAH | 逐班（tdx） | {last} | {last} | 3 | 2 | 8 | 2 | 0 | 1 |" in md
    assert "| RCTP | 取消統計 |" in md and "| 0 | 270 | 54 | 0 | - |" in md
    assert "（其中班次少）" in md
    assert "`轉降` → 轉降 1 班" in md
    assert "逐班（tdx）ROAH" in "\n".join(rpt.summary_lines(res))
    doc = rpt.to_json(res)["levels"]
    assert doc["fewFlights"] == 4
    assert doc["truthSources"]["ROAH"]["fewSlots"] == 2
    assert doc["truthSources"]["RCTP"]["diverted"] is None
    assert doc["flightClasses"] == {
        "normal": 5,
        "cancelled": 2,
        "delayed": 0,
        "diverted": 1,
        "other": 0,
    }
    assert doc["slotFew"][rpt.BEFORE]["risky"][1]["tp"] == 1
    assert doc["windowFew"][rpt.rule_key(rpt.BEFORE)]["risky"]["tp"] == 1


def test_no_flights_same_as_hd36(archive):
    """沒有 `flights/`：拿掉 HD37 加的欄位，JSON 和 HD37 前的程式一模一樣。"""
    both = _result(
        archive, jtwc=FIXTURES / "bwp292026_sample.dat", jma=FIXTURES / "jma_bst_sample.txt"
    )
    assert _digest(_hd36_fields(rpt.to_json(both))) == HD36_DIGEST_BOTH
    assert _digest(_hd36_fields(rpt.to_json(_result(archive)))) == HD36_DIGEST_PLAIN


# ---- HD33a：旁觀・回補 ----


def _bf(icao, at, day, wind, gust=None, wdir=49.1, estimated=False):
    return {
        "icao": icao,
        "validAt": iso(at),
        "previousDay": day,
        "windKt": wind,
        "windDir": wdir,
        "gustKt": None if estimated else gust,
        "gustEstimated": estimated,
        "precipMm": 0.0,
    }


def _hours(span):
    """格的 (from, to] 小時（前一小時的值）＋ from 那個小時（估算的平均風看 [from, to]）。"""
    from datetime import timedelta

    return [span[0] + timedelta(hours=h) for h in range(7)]


def _add_backfill(archive, g=None, levels=False):
    """RCTP 的格 B（10/22 06–12Z，實際停飛、METAR 最大 45 節）：ukmo 提前 1 天陣風 50（高）、
    提前 0 天 30（低）、提前 5 天 60（120 小時以後，不算）；cma 是估算陣風（平均風 30）。
    `g`：R1 快照 aifs 那幾筆的 `gustFactor`；`levels`：快照每筆補 `levels.wind`。"""
    d = archive / "data" / "history" / "events" / "29W"
    ukmo = []
    for i, t in enumerate(_hours(B)):
        ukmo.append(_bf("RCTP", t, 1, 30, 40 + 10 * (i == 3)))
        ukmo.append(_bf("RCTP", t, 0, 20, 30))
        ukmo.append(_bf("RCTP", t, 5, 40, 60))
    ukmo.append(_bf("RCTP", B[0], 1, 1, 1))  # 重複的鍵：留第一行
    ukmo.append(_bf("RJCC", B[1], 1, 99, 99))  # 不在事件機場
    _jsonl(d / "backfill" / "openmeteo-ukmo.jsonl", ukmo)
    cma = [_bf("RCTP", t, 1, 20 + 10 * (i == 0), estimated=True) for i, t in enumerate(_hours(B))]
    _jsonl(d / "backfill" / "openmeteo-cma.jsonl", cma)
    if g is None and not levels:
        return
    for p in sorted(d.glob("2026*.json")):
        doc = json.loads(p.read_text(encoding="utf-8"))
        for a in doc["airports"]:
            for s in a["slots"]:
                for e in s["model"]["models"]:
                    if g is not None and p.stem.startswith("20261021") and e["id"] == "aifs":
                        e["gustFactor"] = g
                    gust = e.get("gustKt")
                    if levels and gust is not None:
                        e["levels"] = {"wind": "high" if gust >= 48 else "low"}
        _write(p, doc)


def test_no_backfill_files_no_change(archive):
    res = _result(archive)
    assert res.backfill is None
    assert "旁觀" not in rpt.render(res)
    assert "backfill" not in rpt.to_json(res)


def test_backfill_json_keeps_old_fields(archive):
    before = rpt.to_json(_result(archive))
    _add_backfill(archive)
    after = rpt.to_json(_result(archive))
    assert after.pop("backfill")["rows"] == {"ukmo": 21, "cma": 7}
    assert after == before


def test_backfill_lead_from_previous_day(archive):
    _add_backfill(archive)
    bf = _result(archive).backfill
    assert bf is not None
    runs = {(r.model, iso(r.run)): r for r in bf.runs}
    # 起報＝格開始時間減 previousDay 天那一天的 00Z；previousDay 5 不算
    assert set(runs) == {
        ("ukmo", "2026-10-21T00:00:00Z"),
        ("ukmo", "2026-10-22T00:00:00Z"),
        ("cma", "2026-10-21T00:00:00Z"),
    }
    # 提前 1 天：格 B 的提前時間 30 小時 → 24–48；提前 0 天：6 小時 → 0–24
    ukmo = bf.gust.all["ukmo"]
    assert [c.pairs for c in ukmo] == [[(30.0, 45.0)], [(50.0, 45.0)], [], [], []]
    assert bf.gust.estimated == {"cma"}


def test_backfill_slot_hours_and_estimated_gust(archive):
    _add_backfill(archive)
    bf = _result(archive).backfill
    assert bf is not None
    run = next(r for r in bf.runs if r.model == "cma")
    (slot,) = run.airports["RCTP"]
    # 估算：[from, to] 最大平均風 30（from 那個小時）× G（快照沒有 gustFactor → 1.4）
    assert (slot.start, slot.end) == B
    assert slot.gusts[0].gust == 42.0 and slot.gusts[0].estimated
    assert slot.winds == {"cma": "medium"}
    # 有陣風：只看 (from, to]；from 那個小時屬於前一格，前一格只有這一個小時 → 不算
    ukmo = next(r for r in bf.runs if r.model == "ukmo" and r.run == utc(2026, 10, 21))
    assert [s.start for s in ukmo.airports["RCTP"]] == [B[0]]


def test_backfill_gust_factor_from_snapshot(archive):
    _add_backfill(archive, g=1.6)
    bf = _result(archive).backfill
    assert bf is not None
    run = next(r for r in bf.runs if r.model == "cma")
    # 起報 10/21 00Z 之前沒有快照 → 用最早有 G 的那報（R1）
    assert run.airports["RCTP"][0].gusts[0].gust == 48.0


def test_backfill_gust_rows_in_markdown(archive):
    _add_backfill(archive)
    res = _result(archive)
    md = rpt.render(res)
    assert "| ukmo（旁觀・回補） |" in md and "| cma*（旁觀・回補） |" in md
    assert "旁觀・回補（Open-Meteo Previous Runs）：ukmo 21 行、cma（估算陣風） 7 行" in md
    # 門檻命中：ukmo 24–48 段預測 50、實測 45 → ≥37 命中 1/1、≥48 誤報 1
    line = next(x for x in md.splitlines() if x.startswith("| ukmo（旁觀・回補） | ≥37"))
    # 0–24 段預測 30 → ≥37 漏報；24–48 段預測 50、實測 45 → ≥37 命中、≥48 誤報
    assert line.split(" | ")[1:3] == [
        "≥37：0/1（0）、≥48：0/0（0）",
        "≥37：1/1（0）、≥48：0/0（1）",
    ]
    doc = rpt.to_json(res)["backfill"]
    assert doc["gust"]["all"]["ukmo"][1]["ge48"]["false"] == 1
    assert doc["gustEstimated"] == {"ukmo": False, "cma": True}


def test_backfill_model_levels_vs_stops(archive):
    _add_backfill(archive, levels=True)
    res = _result(archive)
    bf = res.backfill
    assert bf is not None
    lv = bf.levels.models
    # 格 B 實際停飛：ukmo 提前 1 天判高（TP）、提前 0 天判低（FN）
    assert (lv["ukmo"]["high"][1].tp, lv["ukmo"]["high"][0].fn) == (1, 1)
    assert lv["cma"]["risky"][1].tp == 1 and lv["cma"]["high"][1].fn == 1
    # 快照的模式照 `levels.wind` 一起比：R1 的 IFS 在格 B 陣風 50（高，24–48）；R2 在格 B 44、
    # 所在的格 D 10（都低，0–24），兩格都停飛
    assert lv["ifs"]["high"][1].tp == 1 and lv["ifs"]["high"][0].fn == 2
    md = rpt.render(res)
    assert "### 每格各模式的風等級（陣風與側風）vs 實際停飛" in md
    assert "| ukmo（旁觀・回補）判高 |" in md and "| ifs判高 |" in md
    assert "modelLevels" in rpt.to_json(res)["backfill"]


def test_backfill_until_and_truth_until(archive):
    _add_backfill(archive)
    # `--until` 10/21 00Z → 留 R1（之後的第一報，10/21 01Z）→ 起報 ≤ R1 的才算
    bf = _result(archive, until="2026-10-21T00:00Z").backfill
    assert bf is not None
    assert {(r.model, r.run) for r in bf.runs} == {
        ("ukmo", utc(2026, 10, 21)),
        ("cma", utc(2026, 10, 21)),
    }
    assert bf.excluded_runs == 1
    # 實測截止在格 B 結束前 → 不算命中也不算誤報
    bf = _result(archive, truth_until=utc(2026, 10, 22, 11)).backfill
    assert bf is not None
    assert all(not c.pairs for cells in bf.gust.all.values() for c in cells)
    assert bf.gust.past_truth > 0


def test_backfill_slot_matches_assess():
    """報告照抄的換算要和 `assess.hourly_for_slot`（ICON／JMA）一樣。"""
    from datetime import timedelta

    from hongthai import assess
    from hongthai.assess import GustFactor
    from hongthai.config import Runway
    from hongthai.sources.openmeteo import OmHour

    runways = (Runway("05/23", (49.1, 229.1)),)
    start = utc(2026, 10, 22, 6)
    rows = [
        (start + timedelta(hours=h), 10.0 + 3 * h, (40 + 37 * h) % 360, 18.0 + 5 * (h % 4))
        for h in range(-1, 8)
    ]
    om = [OmHour(t, w, d, g, None, None, None, None) for t, w, d, g in rows]
    bf = {t: rpt.BfHour(t, w, d, g) for t, w, d, g in rows}
    end = start + timedelta(hours=6)
    want = assess.hourly_for_slot(om, start, end, runways)
    assert rpt.backfill_slot(bf, start, end, False, runways, 1.0) == (
        want["gustKt"],
        want["crosswindKt"],
    )
    want = assess.hourly_for_slot(om, start, end, runways, GustFactor(1.55, "airport30d"))
    assert rpt.backfill_slot(bf, start, end, True, runways, 1.55) == (
        want["gustKt"],
        want["crosswindKt"],
    )


def test_wind_level_matches_assess():
    from hongthai import assess
    from hongthai.config import Thresholds

    th = Thresholds()
    for gust in (None, 10.0, 37.0, 47.9, 48.0):
        for xw in (None, 5.0, 27.0, 33.0):
            assert rpt.wind_level(gust, xw, th) == assess._wind_level(gust, xw, th)
