"""HD50：AI 評論平常一天 1 報、「有颱風而且有高」時一天 2 報。

`ai/schedule.py`、`build.run_ai`。
"""

from __future__ import annotations

import copy
import json
from datetime import timedelta

import pytest
import yaml
from conftest import utc
from test_ai import NOW, RUN, airport, doc, lv
from test_build import NOW as BUILD_NOW
from test_build import (
    ROOT,
    _out,
    _risky_build,
    _timing_lines,
    fake_ai,
    workspace,  # noqa: F401
)

from hongthai import build
from hongthai.ai import config, schedule
from hongthai.ai import run as ai_run

DAY = utc(2026, 11, 11, 0, 0)
SLOT_TIMES = {h: DAY + timedelta(hours=h, minutes=m) for h, m in build.SLOTS}
STORM = {"id": "2630", "source": "cwa", "now": {"lat": 22.0, "lon": 121.0}}
TYPHOONS = {"active": True, "storms": [STORM], "ended": []}
NO_TYPHOON = {"active": False, "storms": [], "ended": [{"id": "2629", "source": "jma"}]}


def high_doc() -> dict:
    return doc(airport("RC00", lv(3, "high")), airport("ZZ00"))


def medium_doc() -> dict:
    return doc(airport("RC00", lv(3, "medium")), airport("ZZ00"))


def bomb():
    """被呼叫就失敗的假模型：不評的那報不能建 client、不能呼叫。"""

    def make_client(*a, **k):
        raise AssertionError("不評的那報不該建 client")

    def evaluate(*a, **k):
        raise AssertionError("不評的那報不該呼叫")

    return type("Bomb", (), {"make_client": staticmethod(make_client), "evaluate": evaluate})


# ---- 哪一報要評 ----


@pytest.mark.parametrize("hour", [1, 8, 13, 20])
@pytest.mark.parametrize("typhoon", [True, False])
@pytest.mark.parametrize("high", [True, False])
@pytest.mark.parametrize("mode", ["auto", "on", "off"])
def test_decide_matrix(hour, typhoon, high, mode):
    latest = high_doc() if high else medium_doc()
    got = schedule.decide(SLOT_TIMES[hour], mode, latest, TYPHOONS if typhoon else NO_TYPHOON)
    if mode == "off":
        assert got == (False, "disabled")
    elif mode == "on":
        assert got == (True, "forced")
    elif hour == 1:
        assert got == (True, "morning")
    elif hour == 13 and typhoon and high:
        assert got == (True, "typhoon_high")
    else:
        assert got == (False, "off_schedule")


@pytest.mark.parametrize(
    ("started", "expected"),
    [
        (utc(2026, 11, 11, 1, 5), (True, "morning")),
        (utc(2026, 11, 11, 1, 9), (True, "morning")),  # Worker 準時
        (utc(2026, 11, 11, 4, 59), (True, "morning")),  # GitHub 排程晚到近 4 小時
        (utc(2026, 11, 11, 8, 24), (True, "morning")),  # 還在 01:05 那個時段
        (utc(2026, 11, 11, 8, 25), (False, "off_schedule")),
        (utc(2026, 11, 11, 0, 59), (False, "off_schedule")),  # 前一天 20:25 那個時段
        (utc(2026, 11, 11, 13, 5), (True, "typhoon_high")),
        (utc(2026, 11, 11, 20, 24), (True, "typhoon_high")),  # 晚到也還是 13:05 那個時段
        (utc(2026, 11, 11, 20, 25), (False, "off_schedule")),
    ],
)
def test_decide_uses_build_slot(started, expected):
    """用 `build.slot_of` 算時段（`build.py`「這個時段已出過就跳過」同一套），不看分鐘。"""
    assert schedule.decide(build.slot_of(started), "auto", high_doc(), TYPHOONS) == expected


def test_duplicate_trigger_skipped_before_ai(workspace, monkeypatch):  # noqa: F811
    """Worker 與 GitHub 排程都觸發同一個時段：後到的在開頭就跳過（HD25），不會再評一次。"""
    archive = workspace / "data"
    archive.mkdir()
    (archive / "latest.json").write_text(json.dumps({"generatedAt": "2026-11-11T01:07:00Z"}))
    monkeypatch.setattr(build, "utcnow", lambda: utc(2026, 11, 11, 1, 40))
    monkeypatch.setattr(build, "run", lambda **k: pytest.fail("同一個時段不該再跑"))
    assert build.main(["--trigger", "schedule"]) == 0


def test_has_typhoon():
    assert schedule.has_typhoon(TYPHOONS)
    assert not schedule.has_typhoon(NO_TYPHOON)  # 減弱或結束的在 `ended`、不在 `storms`
    assert not schedule.has_typhoon(None)
    assert not schedule.has_typhoon({"storms": "壞掉"})
    assert not schedule.has_typhoon({"storms": [{**STORM, "ended": {"reason": "jma_low"}}]})
    assert schedule.has_typhoon({"storms": [{**STORM, "ended": None}]})


def test_has_high_uses_max_level():
    assert schedule.has_high(high_doc())
    assert schedule.has_high(doc(airport("RC00", lv(19, "confirmed"))))  # 已確認比高還高
    assert not schedule.has_high(medium_doc())
    assert not schedule.has_high(doc(airport("RC00", ["unknown"] * 20)))


def test_next_slot_and_plan():
    assert schedule.next_slot(SLOT_TIMES[1], build.SLOTS) == SLOT_TIMES[1] + timedelta(days=1)
    for h in (8, 13, 20):
        assert schedule.next_slot(SLOT_TIMES[h], build.SLOTS) == SLOT_TIMES[1] + timedelta(days=1)
    assert schedule.next_slot(SLOT_TIMES[1] - timedelta(hours=5), build.SLOTS) == SLOT_TIMES[1]
    assert schedule.plan(SLOT_TIMES[13], "auto", high_doc(), TYPHOONS, build.SLOTS) == {
        "evaluated": True,
        "reason": "typhoon_high",
        "nextSlot": "2026-11-12T01:05:00Z",  # 照平常規則（只有早上那報）
    }


def test_schedule_config_back_to_four_runs(monkeypatch):
    """改回一天四報只改 `config.SCHEDULE`。"""
    monkeypatch.setitem(config.SCHEDULE, "always", (1, 8, 13, 20))
    monkeypatch.setitem(config.SCHEDULE, "typhoonHigh", ())
    for h, t in SLOT_TIMES.items():
        assert schedule.decide(t, "auto", medium_doc(), None) == (True, "morning"), h
    assert schedule.next_slot(SLOT_TIMES[8], build.SLOTS) == SLOT_TIMES[13]


# ---- 沿用上一份 ----


def ok_light(key: str, level: str) -> dict:
    return {
        "status": "ok",
        "level": level,
        "comment": {"zh-TW": f"舊的 {key}"},
        "model": "舊版模型",
        "sentences": {"zh-TW": [{"text": f"舊的 {key}", "src": ["rule"]}]},
    }


def prev_doc(claude: dict, gemini: dict, evaluated: str | None = "2026-10-18T02:15:00Z") -> dict:
    ai = {"evaluatedAt": evaluated, "claude": claude, "gemini": gemini}
    return {"generatedAt": evaluated, "airports": [{"icao": "RC00", "ai": ai}]}


def carry(levels: list[str], prev: dict | None) -> dict:
    return schedule.carry_over(doc(airport("RC00", levels)), prev)["RC00"]


def test_carry_normal_keeps_evaluated_at():
    prev = prev_doc(ok_light("claude", "high"), ai_run.skipped("gemini"))
    got = carry(["low"] * 20, prev)
    assert got == prev["airports"][0]["ai"]  # 兩顆燈與原本的 evaluatedAt 都不變
    assert got["claude"] is not prev["airports"][0]["ai"]["claude"]  # 是複本


def test_carry_previous_error_kept():
    prev = prev_doc(ok_light("claude", "medium"), ai_run.error("gemini", "bad_format"))
    got = carry(lv(5, "medium"), prev)
    assert got["evaluatedAt"] == "2026-10-18T02:15:00Z"
    assert got["claude"]["level"] == "medium"
    assert got["gemini"] == ai_run.error("gemini", "bad_format")


@pytest.mark.parametrize(
    ("evaluated", "kept"),
    [
        ("2026-10-18T00:15:00Z", True),  # RUN 前 26 小時整：還可以
        ("2026-10-18T00:14:00Z", False),  # 超過 26 小時
        (None, False),  # 上一份兩顆都 error：沒有時間不能判斷新舊
        ("壞掉", False),
    ],
)
def test_carry_age(evaluated, kept):
    prev = prev_doc(ok_light("claude", "low"), ok_light("gemini", "low"), evaluated)
    got = carry(["low"] * 20, prev)
    if kept:
        assert got["evaluatedAt"] == evaluated and got["claude"]["status"] == "ok"
    else:
        assert got == {
            "evaluatedAt": None,
            "claude": ai_run.error("claude", "off_schedule"),
            "gemini": ai_run.error("gemini", "off_schedule"),
        }


@pytest.mark.parametrize(
    "prev",
    [
        None,
        {"generatedAt": RUN, "airports": [{"icao": "XX00", "ai": {}}]},  # 那個機場上一份沒有
        {"generatedAt": RUN, "airports": [{"icao": "RC00"}]},  # 上一份那個機場沒有 `ai`
    ],
)
def test_carry_without_previous(prev):
    got = carry(lv(2, "high"), prev)
    assert got["evaluatedAt"] is None
    assert {k: (got[k]["status"], got[k]["error"]) for k in config.KEYS} == {
        "claude": ("error", "off_schedule"),
        "gemini": ("error", "off_schedule"),
    }


@pytest.mark.parametrize(
    ("old", "rule", "stale"),
    [
        ("skipped", "medium", True),  # 「沒看到明顯風險」不能掛在亮中的機場
        ("skipped", "high", True),
        ("skipped", "low", False),
        ("low", "medium", True),
        ("medium", "high", True),  # 低一級也算
        ("low", "high", True),
        ("medium", "medium", False),
        ("high", "medium", False),  # AI 比規則燈高沒關係
        ("high", "confirmed", False),  # AI 沒有 confirmed，當 high 比
        ("medium", "confirmed", True),
        ("low", "low", False),
    ],
)
def test_carry_stale(old, rule, stale):
    claude = ai_run.skipped("claude") if old == "skipped" else ok_light("claude", old)
    prev = prev_doc(claude, ai_run.error("gemini", "timeout"))
    levels = ["low"] * 20 if rule == "low" else lv(4, rule)
    got = carry(levels, prev)
    if stale:
        assert got["claude"] == ai_run.error("claude", "stale")
        assert got["evaluatedAt"] is None  # 兩顆都 error 了
    else:
        assert got["claude"] == claude
        assert got["evaluatedAt"] == "2026-10-18T02:15:00Z"
    assert got["gemini"]["error"] == "timeout"  # error 照樣沿用、不改成 stale


# ---- build.run_ai ----


def _run(latest, prev, history, mode="auto", slot=None, storms=None):
    build.run_ai(latest, prev, NOW, history, None, slot or SLOT_TIMES[8], mode, storms)
    return latest


def test_off_schedule_no_calls_no_files(tmp_path, monkeypatch):
    ev = {"claude": fake_ai("high"), "gemini": fake_ai(None, "bad_format")}
    monkeypatch.setattr(build.ai, "EVALUATORS", ev)
    prev = _run(high_doc(), None, tmp_path / "a", mode="on")  # 先有一份評過的（假的模型）
    history = tmp_path / "b"
    monkeypatch.setattr(build.ai, "EVALUATORS", {"claude": bomb(), "gemini": bomb()})
    latest = _run(high_doc(), copy.deepcopy(prev), history)
    assert not history.exists()  # 不寫戰績、不寫每日次數
    assert latest["ai"]["schedule"] == {
        "evaluated": False,
        "reason": "off_schedule",
        "nextSlot": "2026-11-12T01:05:00Z",
    }
    assert latest["ai"]["disclaimer"] == config.DISCLAIMER
    src = latest["sources"]["ai"]
    assert src == {
        "ok": True,
        "seconds": src["seconds"],
        "calls": {"claude": 0, "gemini": 0},
        "skipped": "off_schedule",
    }
    rc = next(a["ai"] for a in latest["airports"] if a["icao"] == "RC00")
    old = next(a["ai"] for a in prev["airports"] if a["icao"] == "RC00")
    assert rc == old and rc["evaluatedAt"] == RUN  # Claude 的 ok 與 Gemini 的 error 照沿用
    assert rc["gemini"]["status"] == "error"


def test_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr(build.ai, "EVALUATORS", {"claude": bomb(), "gemini": bomb()})
    latest = _run(high_doc(), None, tmp_path, mode="off", slot=SLOT_TIMES[1])
    assert latest["ai"]["schedule"]["reason"] == "disabled"
    assert latest["sources"]["ai"]["skipped"] == "disabled"
    assert all(a["ai"]["claude"]["error"] == "off_schedule" for a in latest["airports"])
    assert not tmp_path.exists() or not any(tmp_path.iterdir())


def test_evaluated_run_same_as_before(tmp_path, monkeypatch):
    """評的那報：和直接跑 `Duel`（HD50 之前的流程）一樣，只多 `ai.schedule`。"""
    ev = {"claude": fake_ai("high"), "gemini": fake_ai(None, "bad_format")}
    monkeypatch.setattr(build.ai, "EVALUATORS", ev)
    latest = _run(high_doc(), None, tmp_path / "new", slot=SLOT_TIMES[13], storms=TYPHOONS)
    before = high_doc()
    res = ai_run.Duel(before, None, NOW, tmp_path / "old", evaluators=ev).run()
    ai_run.apply(before, res, {"ok": res["source"]["ok"], **res["source"]})
    assert latest["ai"] == {**before["ai"], "schedule": latest["ai"]["schedule"]}
    assert latest["ai"]["schedule"]["reason"] == "typhoon_high"
    assert [a["ai"] for a in latest["airports"]] == [a["ai"] for a in before["airports"]]
    drop = {"seconds"}
    assert {k: v for k, v in latest["sources"]["ai"].items() if k not in drop} == {
        k: v for k, v in before["sources"]["ai"].items() if k not in drop
    }
    for name in ("calls-2026-10-19.json", "2026-10-19.json"):  # 戰績與次數照寫
        new = json.loads((tmp_path / "new" / "ai" / name).read_text("utf-8"))
        old = json.loads((tmp_path / "old" / "ai" / name).read_text("utf-8"))
        if isinstance(new, list):
            for rows in (new, old):
                for r in rows:
                    for k in config.KEYS:
                        r[k].pop("seconds", None)
        assert new == old


def test_morning_without_typhoon_evaluated(tmp_path, monkeypatch):
    monkeypatch.setattr(build.ai, "EVALUATORS", {"claude": fake_ai(), "gemini": fake_ai()})
    latest = _run(medium_doc(), None, tmp_path, slot=SLOT_TIMES[1])
    assert latest["ai"]["schedule"]["reason"] == "morning"
    assert latest["sources"]["ai"]["calls"] == {"claude": 1, "gemini": 1}


# ---- 整個 build ----


def test_build_second_run_carries_ai(workspace, monkeypatch, airports):  # noqa: F811
    """08:10Z（01:05 那個時段）評；14:10Z（13:05 那個時段、沒有颱風）沿用，不呼叫、不寫戰績。"""
    _risky_build(workspace, monkeypatch, airports)
    monkeypatch.setattr(build.ai, "EVALUATORS", {"claude": fake_ai(), "gemini": fake_ai("low")})
    assert build.main([]) == 0
    first = _out(workspace)
    assert first["ai"]["schedule"] == {
        "evaluated": True,
        "reason": "morning",
        "nextSlot": "2026-10-19T01:05:00Z",
    }
    hist = workspace / "data" / "history" / "ai"
    files = {p.name: p.read_text("utf-8") for p in hist.iterdir()}

    monkeypatch.setattr(build.ai, "EVALUATORS", {"claude": bomb(), "gemini": bomb()})
    monkeypatch.setattr(build, "utcnow", lambda: BUILD_NOW + timedelta(hours=6))
    assert build.main(["--trigger", "cloudflare"]) == 0
    out = _out(workspace)
    assert {p.name: p.read_text("utf-8") for p in hist.iterdir()} == files
    assert out["ai"]["schedule"]["reason"] == "off_schedule"
    assert out["sources"]["ai"]["skipped"] == "off_schedule"
    before = {a["icao"]: a["ai"] for a in first["airports"]}
    carried = 0
    for a in out["airports"]:
        ai, old = a["ai"], before[a["icao"]]
        if old["evaluatedAt"] is None:  # 上一份兩顆都 error（`run_cap`）：沒有時間，不沿用
            assert ai["claude"]["error"] == ai["gemini"]["error"] == "off_schedule"
            continue
        for k in config.KEYS:
            if ai[k].get("error") != "stale":
                assert ai[k] == old[k]
                carried += 1
        if any(ai[k]["status"] != "error" for k in config.KEYS):
            assert ai["evaluatedAt"] == first["generatedAt"]
    assert carried
    line = [r for r in _timing_lines(workspace) if r["source"] == "ai"][-1]
    assert (line["ok"], line["calls"], line["skipped"]) == (
        True,
        {"claude": 0, "gemini": 0},
        "off_schedule",
    )
    assert line["costUsd"] == {"claude": 0.0, "gemini": 0.0}


def test_build_manual_ai_input(workspace, monkeypatch, airports):  # noqa: F811
    _risky_build(workspace, monkeypatch, airports)
    monkeypatch.setattr(build, "utcnow", lambda: BUILD_NOW + timedelta(hours=13))  # 20:25 時段
    monkeypatch.setattr(build.ai, "EVALUATORS", {"claude": fake_ai(), "gemini": fake_ai()})
    assert build.main(["--ai", "on"]) == 0
    assert _out(workspace)["ai"]["schedule"]["reason"] == "forced"
    monkeypatch.setattr(build.ai, "EVALUATORS", {"claude": bomb(), "gemini": bomb()})
    assert build.main([]) == 0  # 手動按、auto、非評論時段：不評
    assert _out(workspace)["ai"]["schedule"]["reason"] == "off_schedule"
    with pytest.raises(SystemExit):
        build.main(["--ai", "maybe"])


def test_build_yml_ai_input():
    yml = (ROOT / ".github" / "workflows" / "build.yml").read_text("utf-8")
    on = yaml.safe_load(yml)[True]  # PyYAML 把 `on:` 讀成 True
    ai = on["workflow_dispatch"]["inputs"]["ai"]
    assert (ai["type"], ai["options"], ai["default"]) == ("choice", ["auto", "on", "off"], "auto")
    assert "AI_MODE: ${{ inputs.ai || 'auto' }}" in yml
    assert '--ai "$AI_MODE"' in yml
