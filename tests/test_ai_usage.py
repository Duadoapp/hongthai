"""HD26：AI 提示快取與 token 紀錄——Claude 的 `system` 快取 block、兩家 `usage` 的取法、
每報第一個機場先單獨評、戰績與 `timing/` 的 `usage`、估計費用與命中率、`tools/ai_cost.py`。

全部不連網：SDK 回應用假物件，`Duel` 的模型換成假的 `evaluate`，單價用假的。
"""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
import time
from types import SimpleNamespace

import pytest
from conftest import ROOT
from google.genai import types as genai_types
from test_ai import COMMENT, NOW, FakeAnthropic, FakeGenai, _resp, duel_doc, ok_result

from hongthai.ai import claude, config, gemini, prompt, usage
from hongthai.ai import run as ai_run
from hongthai.ai.parse import AiError

_spec = importlib.util.spec_from_file_location("ai_cost", ROOT / "tools" / "ai_cost.py")
assert _spec and _spec.loader
ai_cost = importlib.util.module_from_spec(_spec)
sys.modules["ai_cost"] = ai_cost
_spec.loader.exec_module(ai_cost)

# 好算的假單價（美元／百萬 token）
FAKE_PRICES = {
    "claude": [(None, {"input": 1.0, "output": 10.0, "cacheWrite": 2.0, "cacheRead": 0.1})],
    "gemini": [
        ("2026-10-31", {"input": 1.0, "output": 10.0, "cacheRead": 0.1}),
        (None, {"input": 2.0, "output": 20.0, "cacheRead": None}),
    ],
}


@pytest.fixture
def prices(monkeypatch):
    monkeypatch.setattr(usage, "PRICES", FAKE_PRICES)


# ---- Claude ----


def _cmsg(text: str, stop: str = "end_turn", **u):
    blocks = [SimpleNamespace(type="text", text=text)]
    return SimpleNamespace(stop_reason=stop, content=blocks, usage=SimpleNamespace(**u))


def test_claude_system_is_cached_block():
    fake = FakeAnthropic(_cmsg(_resp(), input_tokens=900, output_tokens=800))
    claude.evaluate("文字", client=fake)
    system = fake.calls[0]["system"]
    assert system == [
        {"type": "text", "text": prompt.SYSTEM, "cache_control": {"type": "ephemeral"}}
    ]
    assert "ttl" not in system[0]["cache_control"]  # 預設 5 分鐘
    # 其他參數一個都沒動
    kw = fake.calls[0]
    assert set(kw) == {"model", "max_tokens", "system", "output_config", "messages"}
    assert kw["messages"] == [{"role": "user", "content": "文字"}]


def test_claude_usage_from_response():
    msg = _cmsg(
        _resp(),
        input_tokens=900,
        output_tokens=812,
        cache_read_input_tokens=3100,
        cache_creation_input_tokens=0,
    )
    res = claude.evaluate("文字", client=FakeAnthropic(msg))
    assert res["level"] == "high" and res["comment"] == COMMENT
    assert res["usage"] == {"input": 900, "output": 812, "cacheRead": 3100, "cacheWrite": 0}


def test_claude_usage_missing_fields_null():
    # 舊回應沒有快取欄位、或 SDK 給 None：寫 null、不寫 0
    msg = _cmsg(_resp(), input_tokens=900, output_tokens=812, cache_read_input_tokens=None)
    assert claude.evaluate("文字", client=FakeAnthropic(msg))["usage"] == {
        "input": 900,
        "output": 812,
        "cacheRead": None,
        "cacheWrite": None,
    }
    assert claude.usage_of(SimpleNamespace(usage=None)) is None
    assert claude.usage_of(SimpleNamespace()) is None


def test_claude_usage_on_failure_with_response():
    msg = _cmsg("不是 JSON", input_tokens=50, output_tokens=640, cache_creation_input_tokens=3100)
    with pytest.raises(AiError) as e:
        claude.evaluate("文字", client=FakeAnthropic(msg))
    assert e.value.trace() == "bad_format:end_turn:640:not_json"
    assert e.value.usage == {"input": 50, "output": 640, "cacheRead": None, "cacheWrite": 3100}


def test_claude_no_response_no_usage():
    import anthropic
    import httpx2

    req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    with pytest.raises(AiError) as e:
        claude.evaluate("文字", client=FakeAnthropic(exc=anthropic.APITimeoutError(request=req)))
    assert e.value.code == "timeout" and e.value.usage is None


# ---- Gemini ----


def _gmeta(**kw) -> genai_types.GenerateContentResponse:
    return genai_types.GenerateContentResponse(
        usage_metadata=genai_types.GenerateContentResponseUsageMetadata(**kw),
        candidates=[
            genai_types.Candidate(
                content=genai_types.Content(role="model", parts=[genai_types.Part(text=_resp())]),
                finish_reason=genai_types.FinishReason.STOP,
            )
        ],
    )


def test_gemini_usage_four_numbers():
    resp = _gmeta(
        prompt_token_count=5200,
        candidates_token_count=700,
        thoughts_token_count=900,
        cached_content_token_count=4100,
    )
    fake = FakeGenai(resp)
    res = gemini.evaluate("文字", client=fake)
    assert res["usage"] == {"input": 5200, "output": 700, "thinking": 900, "cacheRead": 4100}
    # 送法沒變：system_instruction 還是 SYSTEM 字串、沒有 cached_content
    cfg = fake.calls[0]["config"]
    assert cfg.system_instruction == prompt.SYSTEM and cfg.cached_content is None


def test_gemini_usage_missing_null():
    # 沒命中時回應不帶 cached_content_token_count：寫 null
    res = gemini.evaluate("文字", client=FakeGenai(_gmeta(prompt_token_count=5200)))
    assert res["usage"] == {"input": 5200, "output": None, "thinking": None, "cacheRead": None}
    resp = _gmeta(prompt_token_count=1)
    resp.usage_metadata = None
    assert gemini.usage_of(resp) is None


def test_gemini_usage_on_failure():
    resp = _gmeta(prompt_token_count=5200, candidates_token_count=3000, thoughts_token_count=10)
    resp.candidates[0].finish_reason = genai_types.FinishReason.MAX_TOKENS
    with pytest.raises(AiError) as e:
        gemini.evaluate("文字", client=FakeGenai(resp))
    assert e.value.trace() == "bad_format:MAX_TOKENS:3000+10"
    assert e.value.usage == {"input": 5200, "output": 3000, "thinking": 10, "cacheRead": None}


# ---- 第一個機場先單獨評（HD26）----


def timed_model(delay: float, fail_first: bool = False):
    """記每次呼叫（機場、開始、結束）的假模型。"""
    log: list[tuple[str, float, float]] = []
    lock = threading.Lock()

    def evaluate(text, *, client=None, timeout=60):
        icao = text.splitlines()[0]
        t0 = time.monotonic()
        time.sleep(delay)
        with lock:
            first = not log
            log.append((icao, t0, time.monotonic()))
        if fail_first and first:
            raise AiError("bad_format")
        return ok_result("high")

    return SimpleNamespace(make_client=object, evaluate=evaluate, log=log)


def test_warmup_only_claude_hd26():
    assert config.WARMUP == {"claude": True, "gemini": False}
    assert set(config.WARMUP) == set(config.MODELS)


@pytest.mark.parametrize("fail_first", [False, True])
def test_claude_first_airport_alone_then_parallel(tmp_path, fail_first):
    """Claude 第一個機場（排序第一的 RC00）先單獨評完，其他的才開線並行；第一個失敗也照樣開線。"""
    ev = {"claude": timed_model(0.2, fail_first), "gemini": timed_model(0.2)}
    res = ai_run.evaluate_all(duel_doc(5, 0), None, NOW, tmp_path, evaluators=ev)
    calls = sorted(ev["claude"].log, key=lambda r: r[1])  # 依開始時間
    assert len(calls) == 5
    first, rest = calls[0], calls[1:]
    assert "RC00" in first[0]
    assert all(r[1] >= first[2] for r in rest)  # 第一個結束後才開始
    starts = [r[1] for r in rest]  # 其他的並行：前兩個幾乎同時開始
    assert starts[1] - starts[0] < 0.1
    assert res["source"]["calls"]["claude"] == 5
    lights = [res["airports"][f"RC0{i}"]["claude"]["status"] for i in range(5)]
    assert lights == ["error" if fail_first else "ok"] + ["ok"] * 4


def test_gemini_no_warmup(tmp_path):
    """Gemini 不先單獨評：一開始就 3 條線同時送（隱含快取最小 4,096 token，SYSTEM 不到）。"""
    ev = {"claude": timed_model(0.2), "gemini": timed_model(0.2)}
    res = ai_run.evaluate_all(duel_doc(5, 0), None, NOW, tmp_path, evaluators=ev)
    calls = sorted(ev["gemini"].log, key=lambda r: r[1])
    assert len(calls) == 5 and res["source"]["calls"]["gemini"] == 5
    # 前 3 個（含 RC00）同時開始，沒有等第一個結束
    assert calls[2][1] - calls[0][1] < 0.1
    assert calls[1][1] < calls[0][2]
    assert any("RC00" in c[0] for c in calls[:3])


# ---- 戰績、timing ----


def usage_model(key: str, rows: list[dict | None], exc_at: int | None = None):
    """依序回傳 `rows` 的 usage（`exc_at` 那次丟有回應的 `bad_format`）。"""
    n = {"i": 0}
    lock = threading.Lock()

    def evaluate(text, *, client=None, timeout=60):
        with lock:
            i = n["i"]
            n["i"] += 1
        u = rows[min(i, len(rows) - 1)]
        if i == exc_at:
            e = AiError("bad_format", tag="not_json")
            e.usage = u
            raise e
        return {**ok_result("high"), "usage": u}

    return SimpleNamespace(make_client=object, evaluate=evaluate)


def test_duel_records_usage_and_totals(tmp_path, monkeypatch, prices):
    monkeypatch.setattr(ai_run, "PARALLEL", {"claude": 1, "gemini": 1})  # 依序，好對
    cu = [
        {"input": 900, "output": 800, "cacheRead": 0, "cacheWrite": 3000},
        {"input": 950, "output": 700, "cacheRead": 3000, "cacheWrite": 0},
    ]
    gu = [
        {"input": 5000, "output": 600, "thinking": 400, "cacheRead": None},
        {"input": 5100, "output": 650, "thinking": None, "cacheRead": 4096},
    ]
    ev = {"claude": usage_model("claude", cu), "gemini": usage_model("gemini", gu, exc_at=1)}
    res = ai_run.evaluate_all(duel_doc(2, 1), None, NOW, tmp_path, evaluators=ev)
    rows = {
        r["airport"]: r
        for r in json.loads((tmp_path / "ai" / "2026-10-19.json").read_text("utf-8"))
    }
    assert rows["RC00"]["claude"]["usage"] == cu[0] and rows["RC01"]["claude"]["usage"] == cu[1]
    assert rows["RC00"]["gemini"]["usage"] == gu[0]
    assert rows["RC01"]["gemini"]["status"] == "error"
    assert rows["RC01"]["gemini"]["usage"] == gu[1]  # 失敗但有回應也記
    assert "usage" not in rows["ZZ00"]["claude"]  # skipped：沒送
    # latest.json 不加
    for a in res["airports"].values():
        assert all("usage" not in a[k] for k in ("claude", "gemini"))
    assert "usage" not in res["source"] and "costUsd" not in res["source"]
    assert res["usage"] == {
        "claude": {
            "input": 1850,
            "output": 1500,
            "cacheRead": 3000,
            "cacheWrite": 3000,
            "calls": 2,
        },
        "gemini": {"input": 10100, "output": 1250, "thinking": 400, "cacheRead": 4096, "calls": 2},
    }
    # Claude：1850×1 + 1500×10 + 3000×0.1 + 3000×2 = 23150 → 0.02315
    # Gemini（10/19 用前一段單價）：(10100−4096)×1 + 4096×0.1 + (1250+400)×10 = 22913.6
    assert res["costUsd"] == {"claude": 0.02315, "gemini": 0.022914}


def test_duel_no_response_usage_null(tmp_path):
    def evaluate(text, *, client=None, timeout=60):
        raise AiError("http_429")

    ev = {
        "claude": SimpleNamespace(make_client=object, evaluate=evaluate),
        "gemini": usage_model("gemini", [{"input": 10, "output": 5}]),
    }
    res = ai_run.evaluate_all(duel_doc(1, 0), None, NOW, tmp_path, evaluators=ev)
    row = json.loads((tmp_path / "ai" / "2026-10-19.json").read_text("utf-8"))[0]
    assert row["claude"]["usage"] is None and row["claude"]["detail"] == "http_429:-:-"
    assert res["usage"]["claude"]["calls"] == 0 and res["costUsd"]["claude"] is None
    assert res["usage"]["gemini"]["calls"] == 1


# ---- 合計、命中率、費用 ----


def test_total_skips_nulls():
    rows = [
        {"input": 10, "output": 1, "cacheRead": None, "cacheWrite": 5},
        None,
        {"input": 20, "output": None, "cacheRead": None, "cacheWrite": 0},
    ]
    assert usage.total("claude", rows) == {
        "input": 30,
        "output": 1,
        "cacheRead": None,
        "cacheWrite": 5,
        "calls": 2,
    }
    assert usage.total("gemini", []) == {
        "input": None,
        "output": None,
        "thinking": None,
        "cacheRead": None,
        "calls": 0,
    }


def test_hit_rate_formulas():
    # Claude 的 input 不含快取：3000 ÷ (1000 + 3000 + 0)
    assert usage.hit_rate("claude", {"input": 1000, "cacheRead": 3000, "cacheWrite": 0}) == 0.75
    assert usage.hit_rate("claude", {"input": 1000, "cacheRead": 0, "cacheWrite": 3000}) == 0
    # Gemini 的 input 含快取：4000 ÷ 5000
    assert usage.hit_rate("gemini", {"input": 5000, "cacheRead": 4000}) == 0.8
    assert usage.hit_rate("gemini", {"input": 5000, "cacheRead": None}) == 0
    assert usage.hit_rate("gemini", {"input": None, "cacheRead": 1}) is None
    assert usage.hit_rate("claude", None) is None


def test_cost_with_fake_prices(prices):
    u = {"input": 1_000_000, "output": 100_000, "cacheRead": 2_000_000, "cacheWrite": None}
    assert usage.cost_usd("claude", u, "2026-10-21") == 1.0 + 1.0 + 0.2
    g = {"input": 1_000_000, "output": 100_000, "thinking": 50_000, "cacheRead": 400_000}
    assert usage.cost_usd("gemini", g, "2026-10-31") == pytest.approx(0.6 + 0.04 + 1.5)
    # 11/1 起換單價；cacheRead 單價 None → 有命中就算不出來，沒命中照算
    assert usage.cost_usd("gemini", g, "2026-11-01") is None
    assert usage.cost_usd("gemini", {**g, "cacheRead": None}, "2026-11-01") == 2.0 + 3.0
    assert usage.cost_usd("claude", {"input": None, "output": 5}, "2026-10-21") is None
    assert usage.cost_usd("claude", None, "2026-10-21") is None


def test_real_prices_hd26():
    """單價表（2026-10-21 查）：Opus 5.5、Argon global（11/30 前促銷價）。"""
    assert usage.price("claude", "2026-10-21") == {
        "input": 4.0,
        "output": 20.0,
        "cacheWrite": 5.0,
        "cacheRead": 0.20,
    }
    assert usage.price("gemini", "2026-11-30") == {"input": 2.0, "output": 10.0, "cacheRead": 0.10}
    assert usage.price("gemini", "2026-12-01") == {"input": 4.0, "output": 20.0, "cacheRead": 0.20}
    assert set(config.PRICES) == set(config.MODELS)


# ---- tools/ai_cost.py ----


def _write_day(archive, day: str, rows: list[dict]) -> None:
    p = archive / "history" / "ai" / f"{day}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rows), encoding="utf-8")


def _row(run: str, icao: str, cu: object = "-", gu: object = "-") -> dict:
    def light(u: object) -> dict:
        return {"status": "ok", "level": "low"} | ({} if u == "-" else {"usage": u})

    return {"run": run, "airport": icao, "claude": light(cu), "gemini": light(gu)}


def test_ai_cost_summary(tmp_path, prices, capsys):
    r1, r2 = "2026-10-21T02:15:00Z", "2026-10-21T08:15:00Z"
    c1 = {"input": 1000, "output": 800, "cacheRead": 0, "cacheWrite": 3000}
    c2 = {"input": 1000, "output": 600, "cacheRead": 3000, "cacheWrite": 0}
    g1 = {"input": 5000, "output": 600, "thinking": 400, "cacheRead": 4000}
    _write_day(
        tmp_path,
        "2026-10-21",
        [
            _row(r1, "RCTP", c1, g1),
            _row(r1, "RCKH", c2, None),  # Gemini 送了沒回應
            _row(r2, "RCTP", c2, "-"),  # Gemini 沒送
        ],
    )
    _write_day(tmp_path, "2026-10-20", [_row("2026-10-20T02:15:00Z", "RCTP")])  # --from 之前
    (tmp_path / "history" / "ai" / "calls-2026-10-21.json").write_text("{}", "utf-8")
    res = ai_cost.summarize(ai_cost.load(tmp_path, "2026-10-21", None))
    assert [d["day"] for d in res["days"]] == ["2026-10-21"]
    day = res["days"][0]
    cl, ge = day["claude"], day["gemini"]
    assert (cl["calls"], cl["responded"]) == (3, 3)
    assert cl["avg"] == {"input": 1000, "output": 666.7, "cacheRead": 2000, "cacheWrite": 1000}
    # 6000 ÷ (3000 + 6000 + 3000)
    assert cl["hitRate"] == 0.5
    # 3000×1 + 2000×10 + 6000×0.1 + 3000×2 = 29600
    assert cl["costUsd"] == 0.0296 and cl["costPerCallUsd"] == round(0.0296 / 3, 6)
    assert (ge["calls"], ge["responded"]) == (2, 1)
    assert ge["hitRate"] == 0.8
    # (5000−4000)×1 + 4000×0.1 + (600+400)×10 = 11400
    assert ge["costUsd"] == 0.0114
    runs = {r["run"]: r for r in day["runs"]}
    assert runs[r2]["gemini"]["calls"] == 0 and runs[r2]["gemini"]["costUsd"] == 0
    assert runs[r1]["claude"]["calls"] == 2
    assert res["total"]["claude"]["costUsd"] == 0.0296
    # 印表與 JSON
    assert ai_cost.main(["--archive", str(tmp_path), "--from", "2026-10-21"]) == 0
    out = capsys.readouterr().out
    assert "cacheRead ÷ (input + cacheRead + cacheWrite)" in out
    assert "claude 呼叫 3（有回應 3）" in out and "命中 50.0%" in out
    assert ai_cost.main(["--archive", str(tmp_path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["total"]["gemini"]["hitRate"] == 0.8


def test_ai_cost_unknown_price_null(tmp_path, prices):
    g = {"input": 5000, "output": 600, "thinking": None, "cacheRead": 4000}
    _write_day(tmp_path, "2026-11-02", [_row("2026-11-02T02:15:00Z", "RCTP", gu=g)])
    res = ai_cost.summarize(ai_cost.load(tmp_path, "2026-10-21", None))
    assert res["total"]["gemini"]["costUsd"] is None  # 假單價表 11/1 起 cacheRead 是 None
    assert res["total"]["claude"]["calls"] == 0 and res["total"]["claude"]["hitRate"] is None
