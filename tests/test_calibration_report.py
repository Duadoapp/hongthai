"""HD46：回測校準報告工具（`tools/calibration_report.py`）——手造一個小 `history/`：幾報快照、
桃園（`cancellations/`）、台東（事件保存的 TDX 逐班）、浦東（沒有航班資料）。"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import timedelta

import pytest
from conftest import ROOT, utc

from hongthai.timeutil import iso

_spec = importlib.util.spec_from_file_location(
    "calibration_report", ROOT / "tools" / "calibration_report.py"
)
assert _spec and _spec.loader
cal = importlib.util.module_from_spec(_spec)
sys.modules["calibration_report"] = cal  # dataclass 要找得到模組
_spec.loader.exec_module(cal)

H6 = timedelta(hours=6)
S1 = utc(2026, 10, 20, 12)  # 桃園：取消 30/100（≥ 25%，不到 50%）
S2 = utc(2026, 10, 20, 18)  # 桃園：取消 0/100、延誤 30（只有「取消＋延誤」的事件）
S3 = utc(2026, 10, 21, 0)  # 桃園：表定只有 5 班、取消 3（班次少）
S4 = utc(2026, 10, 21, 6)  # 桃園：格結束（12Z）晚於資料最新的 asOf（10Z）→ 還沒有結果
RA = utc(2026, 10, 20, 1)  # S1 提前 11 小時
RB = utc(2026, 10, 19, 23)  # S1 提前 13 小時（和 RA 一樣靠近 12，取比較新的 RA）
RC = utc(2026, 10, 20, 7)  # S1 提前 5 小時（離 12 比較遠）
LAST = utc(2026, 10, 21, 10)


def _slot(start, level, official=None, model=None, causes=()):
    return {
        "from": iso(start),
        "to": iso(start + H6),
        "level": level,
        "causes": list(causes),
        "official": None if official is None else {"level": official},
        "model": {"level": model or level},
    }


def _airport(icao, slots, ai=("ok", "high")):
    status, level = ai
    light = {"status": status, "level": level}
    ai_doc = {"claude": light, "gemini": light}
    return {"icao": icao, "iata": icao[1:], "slots": slots, "ai": ai_doc}


def _snapshot(history, run, airports):
    doc = {"generatedAt": iso(run), "airports": airports}
    (history / f"{run.strftime('%Y%m%dT%H%MZ')}.json").write_text(json.dumps(doc), "utf-8")


def _row(icao, start, total, cancelled, delayed=0, as_of=LAST):
    half = total // 2
    return {
        "airport": icao,
        "from": iso(start),
        "to": iso(start + H6),
        "asOf": iso(as_of),
        "dep": {"total": half, "cancelled": cancelled, "delayed": delayed, "other": 0},
        "arr": {"total": total - half, "cancelled": 0, "delayed": 0, "other": 0},
    }


def _tdx(flight, sched, cls, t):
    return {
        "t": iso(t),
        "airport": "RCFN",
        "dir": "dep",
        "flight": flight,
        "schedUtc": iso(sched),
        "status": "取消" if cls == "cancelled" else "準時",
        "class": cls,
        "source": "tdx",
    }


@pytest.fixture
def archive(tmp_path):
    history = tmp_path / "data" / "history"
    history.mkdir(parents=True)
    rctp = [
        _slot(S1, "high", official="high", model="medium", causes=["wind"]),
        _slot(S2, "medium", model="medium", causes=["rain"]),
        _slot(S3, "high", causes=["wind"]),
        _slot(S4, "high", causes=["wind"]),
    ]
    zspd = [_slot(S1, "high"), _slot(S2, "low")]
    # RC：S1 改說低（提前 5 小時，去重時不會被選到）
    rc = [_slot(S1, "low"), *rctp[1:]]
    _snapshot(history, RB, [_airport("RCTP", rctp), _airport("ZSPD", zspd)])
    _snapshot(history, RA, [_airport("RCTP", rctp), _airport("ZSPD", zspd)])
    _snapshot(history, RC, [_airport("RCTP", rc), _airport("ZSPD", zspd)])
    # 範圍外的一報（`--to 2026-10-20` 不收）
    _snapshot(history, utc(2026, 10, 21, 1), [_airport("RCTP", [_slot(S4, "low")])])
    (history / "cancellations").mkdir()
    rows = [
        _row("RCTP", S1, 100, 30),
        _row("RCTP", S2, 100, 0, delayed=30, as_of=utc(2026, 10, 20, 20)),
        _row("RCTP", S3, 5, 3),
        _row("RCTP", S4, 100, 80),
    ]
    (history / "cancellations" / "2026-10-20.json").write_text(json.dumps(rows), "utf-8")
    # 台東：事件保存的 TDX 逐班；S1 那格 12 班、取消 6 班（≥ 50%）
    flights = history / "events" / "29W" / "flights"
    flights.mkdir(parents=True)
    t0 = utc(2026, 10, 20, 9)
    lines = [
        _tdx(f"AE{i}", S1 + timedelta(minutes=10 * i), "cancelled" if i < 6 else "normal", t0)
        for i in range(12)
    ]
    lines.append(_tdx("AE99", S2, "normal", LAST))  # 整批最新的 t
    (flights / "2026-10-20.jsonl").write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in lines), "utf-8"
    )
    tdx_slots = [_slot(S1, "low", official="low", model="medium")]
    for run in (RA, RB, RC):
        doc = json.loads((history / f"{run.strftime('%Y%m%dT%H%MZ')}.json").read_text("utf-8"))
        doc["airports"].append(_airport("RCFN", tdx_slots, ai=("skipped", "low")))
        (history / f"{run.strftime('%Y%m%dT%H%MZ')}.json").write_text(json.dumps(doc), "utf-8")
    events = tmp_path / "events.json"
    events.write_text(
        json.dumps(
            {
                "events": [
                    {
                        "id": "29W",
                        "name": "CHAMPI（薔琵）",
                        "from": "2026-10-20",
                        "to": "2026-10-20",
                        "airports": ["RCTP", "RCFN"],
                    }
                ]
            }
        ),
        "utf-8",
    )
    return tmp_path / "data", events


def _compute(archive, min_flights=10):
    data, events = archive
    return cal.compute(
        data,
        utc(2026, 10, 19),
        utc(2026, 10, 21),
        min_flights,
        events_path=events,
        args={"from": "2026-10-19", "to": "2026-10-20"},
        git=False,
    )


def test_wilson():
    assert cal.wilson(0, 0) is None
    lo, hi = cal.wilson(5, 10)
    assert lo == pytest.approx(0.2366, abs=1e-4)
    assert hi == pytest.approx(0.7634, abs=1e-4)
    lo, hi = cal.wilson(0, 10)
    assert lo == 0.0
    assert hi == pytest.approx(0.2775, abs=1e-4)
    lo, hi = cal.wilson(10, 10)
    assert hi == 1.0
    assert lo == pytest.approx(0.7225, abs=1e-4)


def test_bucket_and_dedupe():
    def fc(run, start=S1):
        lead = (start - run).total_seconds() / 3600
        return cal.Forecast("RCTP", start, run, lead, cal.bucket_of(lead), "low", None, "low", ())

    assert cal.bucket_of(-3) == 0
    assert cal.bucket_of(23.9) == 0
    assert cal.bucket_of(24) == 1
    assert cal.bucket_of(120) == 4
    assert cal.bucket_of(121) is None
    # 11 與 13 小時一樣靠近 12：取比較新的那報；5 小時離得遠
    kept = cal.dedupe([fc(RB), fc(RC), fc(RA)])
    assert [f.run for f in kept] == [RA]
    # 不同提前時間段各留一筆
    far = utc(2026, 10, 18, 0)  # S1 提前 60 小時
    kept = cal.dedupe([fc(RA), fc(far), fc(utc(2026, 10, 18, 6))])
    assert sorted((f.bucket, f.run) for f in kept) == [(0, RA), (2, far)]


def test_levels_vs_events(archive):
    res = _compute(archive)
    pairs = {(f.airport, f.start): (f, t) for f, t in res.pairs}
    # S1：去重選 RA（說高），不是 RC（說低）
    f, t = pairs[("RCTP", S1)]
    assert (f.run, f.level, t.total, t.cancelled) == (RA, "high", 100, 30)
    hi0 = res.calib["c25"]["high"][0]
    assert (hi0.n, hi0.k) == (1, 1)
    assert res.calib["c50"]["high"][0].k == 0
    # S2：說中，只有「取消＋延誤」到 25%
    assert res.calib["c25"]["medium"][0].k == 0
    assert res.calib["cd25"]["medium"][0].k == 1
    c = res.conf["c25:high"][0]
    assert (c.tp, c.fp) == (1, 0)
    c = res.conf["cd25:risky"][-1]
    assert c.tp == 2
    # 原因、期間
    assert res.causes["wind:high"]["c25"].k == 1
    assert res.causes["rain:medium"]["cd25"].k == 1
    assert res.periods["29W:high"]["c25"].n == 1  # S1 在 29W 期間（台灣 10/20）
    assert res.periods[f"{cal.NON_TYPHOON}:medium"]["cd25"].n == 1  # S2 台灣 10/21 02:00


def test_airport_without_flights_excluded(archive):
    res = _compute(archive)
    assert all(f.airport != "ZSPD" for f, _ in [*res.pairs, *res.few_pairs])
    doc = cal.to_json(res)
    assert doc["inventory"]["airportsWithoutFlights"] == ["ZSPD"]
    assert "RCTP" in doc["inventory"]["airportsWithFlights"]
    assert "ZSPD" in cal.render(res)


def test_few_flights_and_pending(archive):
    res = _compute(archive)
    starts = {f.start for f, _ in res.pairs if f.airport == "RCTP"}
    assert S3 not in starts  # 5 班 < 10
    assert any(f.start == S3 for f, _ in res.few_pairs)
    assert S4 not in starts and all(f.start != S4 for f, _ in res.few_pairs)  # 還沒有結果
    assert res.truth.pending["RCTP"] == 1
    # 門檻 4 班的對照收得到 S3（RA、RC 落在 0–24、RB 提前 25 小時落在 24–48，兩段各一筆）
    few4 = res.calib_few4["c50"]["high"]
    assert [(c.n, c.k) for c in few4[:2]] == [(2, 1), (1, 1)]
    res4 = _compute(archive, min_flights=4)
    assert S3 in {f.start for f, _ in res4.pairs}
    # `asOf` 早於格結束的列標 early
    assert res.truth.slots[("RCTP", S2)].early is True  # asOf 20Z < 格結束 24Z
    assert res.truth.slots[("RCTP", S1)].early is False


def test_tdx_flights_truth(archive):
    res = _compute(archive)
    t = res.truth.slots[("RCFN", S1)]
    assert (t.total, t.cancelled, t.source) == (12, 6, "tdx")
    # 0–24 小時說低（官方層低、模式層中）但取消 50% → 漏報
    miss = res.misses["c50"]
    assert [(f.airport, f.official, f.model) for f, _ in miss] == [("RCFN", "low", "medium")]
    assert any("官方層說低、模式層說中以上" in p for p in cal.phenomena(res))


def test_ai_windows(archive):
    res = _compute(archive)
    # 每個機場每個 UTC 日只取當天第一報：RCTP 10/19 RB、10/20 RA；RC 不算
    # RCTP 的窗含 S4（還沒有結果）→ 不算；RCFN 的窗只有 S1
    assert res.ai.skipped["windowNotFinished"] == 2
    assert res.ai.windows == 2
    assert res.ai.rows["claude:skipped:low"]["c50"].k == 2
    assert res.ai.rows["rule:low"]["c50"].k == 2


def test_cli_writes_files(archive, tmp_path):
    data, events = archive
    out, js = tmp_path / "r.md", tmp_path / "r.json"
    code = cal.main(
        [
            "--archive",
            str(data),
            "--from",
            "2026-10-19",
            "--to",
            "2026-10-20",
            "--events",
            str(events),
            "--out",
            str(out),
            "--json",
            str(js),
        ]
    )
    assert code == 0
    md = out.read_text("utf-8")
    assert md.index("## 限制") < md.index("## 1. 資料盤點")
    assert "值得 Shawn 看的現象" in md
    doc = json.loads(js.read_text("utf-8"))
    assert doc["meta"]["runs"] == 3  # 10/21 那報在 `--to` 之外
    assert doc["calibration"]["c25"]["high"]["0–24 h"]["k"] == 1
    assert set(doc["calibration"]) == {e.key for e in cal.EVENTS}
