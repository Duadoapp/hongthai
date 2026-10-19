"""AI 對決（HD5）：選機場、提示文字、回應解析、兩個模型的呼叫、每日上限、輸出結構、戰績檔。

全部不連網：SDK 用假物件，`Duel` 的模型換成假的 `evaluate`。
"""

from __future__ import annotations

import json
import re
import threading
import time
from datetime import timedelta
from types import SimpleNamespace

import anthropic
import httpx2
import pytest
from conftest import utc
from google.genai import errors as genai_errors
from google.genai import types as genai_types
from test_build import latest  # noqa: F401

from hongthai.ai import claude, config, gemini, parse, prompt, select
from hongthai.ai import run as ai_run
from hongthai.ai.parse import AiError

T0 = utc(2026, 10, 19, 0)
RUN = "2026-10-19T02:15:00Z"
NOW = utc(2026, 10, 19, 2, 15)
LANGS = ("zh-TW", "zh-HK", "zh-CN", "en")
COMMENT = {
    "zh-TW": "10/23 14–20 時 EC 陣風 75 節、側風 51 節，高。",
    "zh-HK": "10/23 14–20 時 EC 陣風 75 節、側風 51 節，高。",
    "zh-CN": "10/23 14–20 时 EC 阵风 75 节、侧风 51 节，高。",
    "en": "10/23 14–20: EC gust 75 kt, crosswind 51 kt; high.",
}
ENV_KEYS = [k for keys in config.ENV.values() for k in keys]


def slots(levels: list[str], t0=T0) -> list[dict]:
    out = []
    for i, lv in enumerate(levels):
        a, b = t0 + timedelta(hours=6 * i), t0 + timedelta(hours=6 * (i + 1))
        out.append(
            {
                "from": a.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "to": b.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "level": lv,
                "basis": "model",
                "official": None,
                "model": {
                    "ec": {"hresGustKt": 40.0, "crosswindKt": 20.0, "p29Kt": 0.5, "p49Kt": 0.1},
                    "gfs": {"gustKt": 30.0, "crosswindKt": 10.0},
                    "level": lv,
                    "agreement": "disagree",
                },
                "gap": False,
            }
        )
    return out


def airport(icao: str, levels: list[str] | None = None) -> dict:
    return {
        "icao": icao,
        "iata": icao[1:],
        "tz": "Asia/Taipei",
        "name": {"zh-TW": icao, "zh-HK": icao, "zh-CN": icao, "en": icao},
        "official": {"warnings": True},
        "warnings": [],
        "metar": None,
        "taf": None,
        "slots": slots(levels or ["low"] * 20),
        "confirmed": [],
    }


def doc(*airports: dict) -> dict:
    return {"generatedAt": RUN, "sources": {}, "airports": list(airports)}


def lv(n_low: int, level: str, n_after: int = 0, after: str = "low") -> list[str]:
    return ["low"] * n_low + [level] + [after] * (19 - n_low - n_after) + ["low"] * n_after


# ---- 選機場 ----


def test_candidates_level_and_changed():
    cur = doc(
        airport("RCTP", lv(5, "medium")),
        airport("RCSS"),  # 全低、沒變 → 不選
        airport("RCKH"),  # 全低，但和上一份比有一格變了 → changed
        airport("VHHH", lv(0, "confirmed")),
    )
    prev = doc(airport("RCTP"), airport("RCSS"), airport("RCKH", lv(3, "medium")))
    got = [(a["icao"], why) for a, why in select.candidates(cur, prev)]
    assert got == [("VHHH", "level"), ("RCTP", "level"), ("RCKH", "changed")]
    # 沒有上一份就沒有「有變」
    assert [a["icao"] for a, _ in select.candidates(cur, None)] == ["VHHH", "RCTP"]


def test_candidates_changed_only_compares_same_from():
    prev_ap = airport("RCKH", lv(0, "medium"))
    for s in prev_ap["slots"]:  # 上一份的格整個錯開 → 沒有同一個 from 可比
        s["from"] = s["from"].replace("T00", "T03")
    assert select.candidates(doc(airport("RCKH")), doc(prev_ap)) == []
    # unknown → low 也算有變（「任一格 level 不同」）
    cur = airport("RCKH")
    prev2 = airport("RCKH", ["unknown"] * 20)
    assert select.candidates(doc(cur), doc(prev2))[0][1] == "changed"


def test_candidates_sorted_by_max_level_then_first_slot_and_capped():
    aps = [airport(f"RC{i:02d}", lv(i % 19, "medium")) for i in range(25)]
    aps.append(airport("ZZHI", lv(15, "high")))
    aps.append(airport("ZZH2", lv(2, "high")))
    aps.append(airport("ZZCF", lv(18, "confirmed")))
    got = select.candidates(doc(*aps), None)
    assert len(got) == config.MAX_AIRPORTS == 20
    icaos = [a["icao"] for a, _ in got]
    assert icaos[:3] == ["ZZCF", "ZZH2", "ZZHI"]
    # 中級的依第一個中級格早的在前，同格照原順序
    firsts = [
        next(i for i, s in enumerate(a["slots"]) if s["level"] == "medium") for a, _ in got[3:]
    ]
    assert firsts == sorted(firsts)
    assert icaos[3:5] == ["RC00", "RC19"]  # 都是第 0 格，照原順序
    assert len(select.qualifying(doc(*aps), None)) == 28


def test_max_level():
    assert select.max_level(airport("RCTP", lv(3, "high"))) == ("high", "2026-10-19T18:00:00Z")
    assert select.max_level(airport("RCTP", ["unknown"] * 20)) == (None, None)


# ---- 提示文字 ----


def test_system_prompt_rules():
    s = prompt.SYSTEM
    for must in (
        "只能根據",
        "不能自己估",
        "60–120 字",
        "zh-HK",
        "zh-CN",
        "en",
        "不得增減",
        '"level"',
    ):
        assert must in s
    assert "颱風信號" in s and "航班取消" in s


def test_airport_text_contains_data_and_units(latest):  # noqa: F811
    vhhh = next(a for a in latest["airports"] if a["icao"] == "VHHH")
    text = prompt.airport_text(vhhh, latest["generatedAt"])
    assert "香港（Hong Kong，VHHH／HKG），時區 Asia/Hong_Kong（UTC+8）" in text
    assert vhhh["metar"]["raw"] in text and vhhh["taf"]["raw"] in text
    assert vhhh["warnings"][0]["text"]["zh-TW"] in text  # 生效中的警報（8 號信號）
    assert "已確認停飛：\n- 當地 10/19 08:00–10/19 14:00" in text
    lines = [ln for ln in text.splitlines() if re.match(r"\d+\. ", ln)]
    assert len(lines) == 20
    first = lines[0]
    assert first.startswith("1. 10/18 14–20 時｜等級 high（依據 官方）")
    assert "熱帶氣旋信號" in first and "落差" in first
    assert "節" in text and "%" in text and "m/s" not in text and "Ms" not in text
    assert "p29Kt" in text and "p49Kt" in text
    # 規則燈的門檻
    for t in ("≥ 48 節 → high", "≥ 37 節 → medium", "≥ 33 節 → high", "≥ 27 節 → medium", "≥ 30%"):
        assert t in text
    assert "{" not in text  # 不是整段 JSON


def test_airport_text_without_optional_data():
    ap = airport("RCKH", lv(2, "medium"))
    ap["official"] = {"warnings": False}
    ap["slots"][0]["model"] = None
    ap["slots"][1]["official"] = {
        "windKt": 25,
        "gustKt": None,
        "kind": "tempo",
        "level": "low",
        "crosswindKt": None,
        "warnings": ["typhoon_sea"],
    }
    text = prompt.airport_text(ap, RUN)
    assert "METAR：無" in text and "TAF：無" in text
    assert "沒有接官方警報來源" in text
    assert "模式：無" in text
    assert "TAF（tempo）平均風 25 節、陣風 —、側風 —、警報 海上颱風警報" in text


# ---- 回應解析 ----


def _resp(**kw) -> str:
    return json.dumps({"level": "high", "comment": dict(COMMENT), **kw}, ensure_ascii=False)


def test_parse_ok_and_fenced():
    assert parse.parse_response(_resp()) == {"level": "high", "comment": COMMENT}
    assert parse.parse_response("```json\n" + _resp() + "\n```")["level"] == "high"


@pytest.mark.parametrize(
    "text",
    [
        "這不是 JSON",
        "[1, 2]",
        _resp(level="severe"),
        _resp(level="confirmed"),
        _resp(comment={k: v for k, v in COMMENT.items() if k != "zh-CN"}),
        _resp(comment={**COMMENT, "en": "  "}),
        _resp(comment={**COMMENT, "zh-HK": "長" * 401}),
        _resp(comment="一段"),
    ],
)
def test_parse_bad_format(text):
    with pytest.raises(AiError) as e:
        parse.parse_response(text)
    assert e.value.code == "bad_format"


def test_parse_400_chars_ok():
    assert parse.parse_response(_resp(comment={**COMMENT, "en": "x" * 400}))["level"] == "high"


# ---- Claude ----


class FakeAnthropic:
    def __init__(self, result=None, exc=None):
        self.result, self.exc, self.calls, self.options = result, exc, [], []
        self.messages = SimpleNamespace(create=self._create)

    def with_options(self, **kw):
        self.options.append(kw)
        return self

    def _create(self, **kw):
        self.calls.append(kw)
        if self.exc:
            raise self.exc
        return self.result


def _msg(text: str, stop: str = "end_turn"):
    blocks = [
        SimpleNamespace(type="thinking", thinking=""),
        SimpleNamespace(type="text", text=text),
    ]
    return SimpleNamespace(stop_reason=stop, content=blocks)


def test_claude_request_and_parse():
    fake = FakeAnthropic(_msg(_resp()))
    assert claude.evaluate("文字", client=fake, timeout=42)["comment"] == COMMENT
    kw = fake.calls[0]
    assert kw["model"] == "claude-opus-5-5" and kw["max_tokens"] == 1200
    assert kw["system"] == prompt.SYSTEM
    assert kw["messages"] == [{"role": "user", "content": "文字"}]
    assert "temperature" not in kw  # Opus 5.5 不接受取樣參數
    assert kw["output_config"] == {"effort": "low"}
    assert fake.options == [{"timeout": 42, "max_retries": 0}]


_REQ = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


@pytest.mark.parametrize(
    ("exc", "code"),
    [
        (anthropic.APITimeoutError(request=_REQ), "timeout"),
        (anthropic.APIConnectionError(request=_REQ), "network"),
        (
            anthropic.APIStatusError(
                "overloaded", response=httpx2.Response(529, request=_REQ), body=None
            ),
            "http_529",
        ),
        (
            anthropic.RateLimitError(
                "rate", response=httpx2.Response(429, request=_REQ), body=None
            ),
            "http_429",
        ),
    ],
)
def test_claude_errors(exc, code):
    fake = FakeAnthropic(exc=exc)
    with pytest.raises(AiError) as e:
        claude.evaluate("文字", client=fake)
    assert e.value.code == code
    assert len(fake.calls) == 1  # 不重試


@pytest.mark.parametrize(("stop", "code"), [("refusal", "refusal"), ("max_tokens", "bad_format")])
def test_claude_stop_reasons(stop, code):
    with pytest.raises(AiError) as e:
        claude.evaluate("文字", client=FakeAnthropic(_msg(_resp(), stop)))
    assert e.value.code == code


def test_claude_no_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(AiError) as e:
        claude.make_client()
    assert e.value.code == "no_api_key"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-not-a-real-key")
    c = claude.make_client()
    assert c.max_retries == 0


# ---- Gemini ----


class FakeGenai:
    def __init__(self, result=None, exc=None):
        self.result, self.exc, self.calls = result, exc, []
        self.models = SimpleNamespace(generate_content=self._gen)

    def _gen(self, **kw):
        self.calls.append(kw)
        if self.exc:
            raise self.exc
        return self.result


def _gresp(text: str, reason=genai_types.FinishReason.STOP):
    return genai_types.GenerateContentResponse(
        candidates=[
            genai_types.Candidate(
                content=genai_types.Content(
                    role="model",
                    parts=[
                        genai_types.Part(text="想一下", thought=True),
                        genai_types.Part(text=text),
                    ],
                ),
                finish_reason=reason,
            )
        ]
    )


def test_gemini_request_and_parse():
    fake = FakeGenai(_gresp(_resp()))
    assert gemini.evaluate("文字", client=fake, timeout=30)["level"] == "high"
    kw = fake.calls[0]
    assert kw["model"] == "gemini-4-argon" and kw["contents"] == "文字"
    cfg = kw["config"]
    assert cfg.system_instruction == prompt.SYSTEM
    assert (cfg.temperature, cfg.max_output_tokens) == (0.3, 1200)
    assert cfg.response_mime_type == "application/json"
    assert cfg.http_options.timeout == 30_000


@pytest.mark.parametrize(
    ("exc", "code"),
    [
        (genai_errors.APIError(429, {"error": {"code": 429, "message": "quota"}}), "http_429"),
        (genai_errors.ServerError(503, {"error": {"code": 503, "message": "x"}}), "http_503"),
        (gemini.httpx.ReadTimeout("slow"), "timeout"),
        (gemini.requests.ConnectionError("down"), "network"),
        (gemini.auth_exceptions.RefreshError("invalid_grant"), "http_401"),
    ],
)
def test_gemini_errors(exc, code):
    fake = FakeGenai(exc=exc)
    with pytest.raises(AiError) as e:
        gemini.evaluate("文字", client=fake)
    assert e.value.code == code
    assert len(fake.calls) == 1


@pytest.mark.parametrize(
    ("reason", "code"),
    [
        (genai_types.FinishReason.MAX_TOKENS, "bad_format"),
        (genai_types.FinishReason.SAFETY, "refusal"),
    ],
)
def test_gemini_finish_reasons(reason, code):
    with pytest.raises(AiError) as e:
        gemini.evaluate("文字", client=FakeGenai(_gresp(_resp(), reason)))
    assert e.value.code == code


def test_gemini_bad_json_response():
    with pytest.raises(AiError) as e:
        gemini.evaluate("文字", client=FakeGenai(_gresp("not json")))
    assert e.value.code == "bad_format"


@pytest.mark.parametrize("missing", config.ENV["gemini"])
def test_gemini_no_api_key(monkeypatch, missing):
    for k in config.ENV["gemini"]:
        monkeypatch.setenv(k, "x")
    monkeypatch.delenv(missing)
    with pytest.raises(AiError) as e:
        gemini.make_client()
    assert e.value.code == "no_api_key"


def test_gemini_bad_service_account_json(monkeypatch):
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_JSON", "{不是 JSON")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "p")
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "global")
    with pytest.raises(AiError) as e:
        gemini.make_client()
    assert e.value.code == "no_api_key" and "不是 JSON" not in str(e.value)
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_JSON", '{"type": "service_account"}')
    with pytest.raises(AiError):
        gemini.make_client()


# ---- 流程 ----


def fake_model(level="high", delay=0.0, exc: str | None = None, client_error: str | None = None):
    calls: list[str] = []
    lock = threading.Lock()

    def make_client():
        if client_error:
            raise AiError(client_error)
        return object()

    def evaluate(text, *, client=None, timeout=60):
        with lock:
            calls.append(text.splitlines()[0])
        if delay:
            time.sleep(delay)
        if exc:
            raise AiError(exc)
        return {"level": level, "comment": dict(COMMENT)}

    return SimpleNamespace(make_client=make_client, evaluate=evaluate, calls=calls)


def duel_doc(n_risky=2, n_quiet=2) -> dict:
    aps = [airport(f"RC{i:02d}", lv(i, "high")) for i in range(n_risky)]
    aps += [airport(f"ZZ{i:02d}") for i in range(n_quiet)]
    return doc(*aps)


def test_duel_output_structure(tmp_path):
    cl, ge = fake_model("high"), fake_model(exc="bad_format")
    res = ai_run.evaluate_all(
        duel_doc(), None, NOW, tmp_path, evaluators={"claude": cl, "gemini": ge}
    )
    assert res["ai"] == {
        "disclaimer": config.DISCLAIMER,
        "models": {"claude": "claude-opus-5-5", "gemini": "gemini-4-argon"},
    }
    assert set(res["ai"]["disclaimer"]) == set(LANGS)
    risky = res["airports"]["RC00"]
    assert risky == {
        "evaluatedAt": RUN,
        "claude": {
            "status": "ok",
            "level": "high",
            "comment": COMMENT,
            "model": "claude-opus-5-5",
        },
        "gemini": {
            "status": "error",
            "level": None,
            "comment": None,
            "model": "gemini-4-argon",
            "error": "bad_format",
        },
    }
    quiet = res["airports"]["ZZ00"]
    assert quiet["evaluatedAt"] == RUN
    for k in ("claude", "gemini"):
        assert quiet[k] == {
            "status": "skipped",
            "level": "low",
            "comment": config.NO_RISK,
            "model": config.MODELS[k],
        }
    assert config.NO_RISK == {
        "zh-TW": "沒看到明顯風險",
        "zh-HK": "未見明顯風險",
        "zh-CN": "未见明显风险",
        "en": "No notable risk seen",
    }
    assert res["source"] == {
        "ok": True,
        "calls": {"claude": 2, "gemini": 2},
        "errors": {"gemini": "bad_format"},
    }
    assert len(cl.calls) == len(ge.calls) == 2  # 只評被選的


def test_duel_no_api_key_other_model_runs(tmp_path):
    cl, ge = fake_model(client_error="no_api_key"), fake_model("medium")
    res = ai_run.evaluate_all(
        duel_doc(), None, NOW, tmp_path, evaluators={"claude": cl, "gemini": ge}
    )
    a = res["airports"]["RC01"]
    assert a["claude"]["error"] == "no_api_key" and a["claude"]["level"] is None
    assert a["gemini"]["status"] == "ok" and a["gemini"]["level"] == "medium"
    assert a["evaluatedAt"] == RUN
    assert res["source"]["errors"] == {"claude": "no_api_key"}
    assert res["source"]["calls"] == {"claude": 0, "gemini": 2}
    assert res["source"]["ok"] is True


def test_duel_both_errors_evaluated_at_null(tmp_path):
    bad = fake_model(client_error="no_api_key")
    res = ai_run.evaluate_all(
        duel_doc(), None, NOW, tmp_path, evaluators={"claude": bad, "gemini": bad}
    )
    assert res["airports"]["RC00"]["evaluatedAt"] is None
    assert res["airports"]["ZZ00"]["evaluatedAt"] == RUN  # skipped 也填
    src = res["source"]
    assert src["ok"] is False
    assert src["errors"] == {"claude": "no_api_key", "gemini": "no_api_key"}
    assert src["error"] == "claude:no_api_key,gemini:no_api_key"


def test_duel_nothing_selected_still_reports_missing_keys(tmp_path):
    bad, good = fake_model(client_error="no_api_key"), fake_model()
    res = ai_run.evaluate_all(
        duel_doc(0, 3), None, NOW, tmp_path, evaluators={"claude": good, "gemini": good}
    )
    assert res["source"] == {"ok": True, "calls": {"claude": 0, "gemini": 0}}
    res = ai_run.evaluate_all(
        duel_doc(0, 3), None, NOW, tmp_path, evaluators={"claude": bad, "gemini": good}
    )
    assert res["source"]["ok"] is False and res["source"]["errors"] == {"claude": "no_api_key"}


def test_duel_daily_cap(tmp_path):
    path = tmp_path / "ai" / "calls-2026-10-19.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"claude": 78, "gemini": 80}), "utf-8")
    cl, ge = fake_model(), fake_model()
    res = ai_run.evaluate_all(
        duel_doc(4, 0), None, NOW, tmp_path, evaluators={"claude": cl, "gemini": ge}
    )
    statuses = [res["airports"][f"RC{i:02d}"]["claude"] for i in range(4)]
    assert sum(s["status"] == "ok" for s in statuses) == 2
    assert sum(s.get("error") == "daily_cap" for s in statuses) == 2
    assert all(res["airports"][f"RC{i:02d}"]["gemini"]["error"] == "daily_cap" for i in range(4))
    assert len(cl.calls) == 2 and ge.calls == []
    assert json.loads(path.read_text("utf-8")) == {"claude": 80, "gemini": 80}
    assert res["source"]["calls"] == {"claude": 2, "gemini": 0}
    # 換日（UTC）重新算
    res = ai_run.evaluate_all(
        duel_doc(1, 0),
        None,
        NOW + timedelta(days=1),
        tmp_path,
        evaluators={"claude": cl, "gemini": ge},
    )
    assert res["airports"]["RC00"]["gemini"]["status"] == "ok"
    assert json.loads((tmp_path / "ai" / "calls-2026-10-20.json").read_text("utf-8")) == {
        "claude": 1,
        "gemini": 1,
    }


def test_duel_failed_calls_count(tmp_path):
    ev = {"claude": fake_model(exc="http_500"), "gemini": fake_model(exc="timeout")}
    ai_run.evaluate_all(duel_doc(3, 0), None, NOW, tmp_path, evaluators=ev)
    calls = json.loads((tmp_path / "ai" / "calls-2026-10-19.json").read_text("utf-8"))
    assert calls == {"claude": 3, "gemini": 3}


def test_duel_run_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(ai_run, "MAX_AIRPORTS", 2)
    m = fake_model()
    res = ai_run.evaluate_all(
        duel_doc(3, 1), None, NOW, tmp_path, evaluators={"claude": m, "gemini": m}
    )
    # RC02 的高級格最晚 → 排第三，超過上限
    assert res["airports"]["RC02"]["claude"]["error"] == "run_cap"
    assert res["airports"]["RC02"]["evaluatedAt"] is None
    assert res["airports"]["ZZ00"]["claude"]["status"] == "skipped"
    assert res["source"]["ok"] is True and "errors" not in res["source"]


def test_duel_models_run_in_parallel(tmp_path):
    """每個模型 4 個機場、每次 0.4 秒、4 條並行 → 一個模型約 0.4 秒；兩個模型同時跑，總時間
    也約 0.4 秒（不是 0.8 秒；模型內也不平行的話是 3.2 秒）。"""
    ev = {"claude": fake_model(delay=0.4), "gemini": fake_model(delay=0.4)}
    t0 = time.monotonic()
    res = ai_run.evaluate_all(duel_doc(4, 0), None, NOW, tmp_path, evaluators=ev)
    took = time.monotonic() - t0
    assert res["source"]["calls"] == {"claude": 4, "gemini": 4}
    assert took < 0.7, took


def test_duel_timeout_marks_unfinished(tmp_path):
    ev = {"claude": fake_model(delay=0.05), "gemini": fake_model(delay=5)}
    duel = ai_run.Duel(duel_doc(2, 1), None, NOW, tmp_path, budget_s=30, evaluators=ev)
    t = threading.Thread(target=duel.run, daemon=True)
    t.start()
    t.join(0.5)  # build 那邊的預算到了
    res = duel.result(timed_out=True)
    assert res["airports"]["RC00"]["claude"]["status"] == "ok"
    assert res["airports"]["RC00"]["gemini"]["error"] == "timeout"
    assert res["airports"]["ZZ00"]["gemini"]["status"] == "skipped"
    assert res["source"]["errors"] == {"gemini": "timeout"}
    assert duel.result() is res  # 只算一次
    calls = json.loads((tmp_path / "ai" / "calls-2026-10-19.json").read_text("utf-8"))
    assert calls == {"claude": 2, "gemini": 2}  # 送出去的也算


def test_duel_request_timeout_capped_by_budget(tmp_path):
    seen = []

    def evaluate(text, *, client=None, timeout=60):
        seen.append(timeout)
        return {"level": "low", "comment": dict(COMMENT)}

    m = SimpleNamespace(make_client=object, evaluate=evaluate)
    ai_run.evaluate_all(
        duel_doc(1, 0), None, NOW, tmp_path, budget_s=10, evaluators={"claude": m, "gemini": m}
    )
    assert len(seen) == 2 and all(5 < t <= 10 for t in seen)


# ---- 對決戰績 ----


def test_duel_records_written_and_merged(tmp_path):
    ev = {"claude": fake_model("high"), "gemini": fake_model(exc="bad_format")}
    prev = duel_doc(2, 2)
    cur = duel_doc(2, 2)
    cur["airports"][3]["slots"][5]["level"] = "unknown"  # ZZ01 有變
    ai_run.evaluate_all(cur, prev, NOW, tmp_path, evaluators=ev)
    path = tmp_path / "ai" / "2026-10-19.json"
    rows = json.loads(path.read_text("utf-8"))
    assert [r["airport"] for r in rows] == ["RC00", "RC01", "ZZ00", "ZZ01"]
    r = rows[0]
    assert r == {
        "run": RUN,
        "airport": "RC00",
        "selected": "level",
        "rule": {"maxLevel": "high", "firstFrom": "2026-10-19T00:00:00Z"},
        "claude": {"status": "ok", "level": "high"},
        "gemini": {"status": "error", "level": None},
        "slots": [{"from": s["from"], "level": s["level"]} for s in cur["airports"][0]["slots"]],
    }
    assert len(r["slots"]) == 20 and set(r["slots"][0]) == {"from", "level"}
    assert rows[2]["selected"] is None and rows[2]["claude"] == {
        "status": "skipped",
        "level": "low",
    }
    assert rows[3]["selected"] == "changed"
    assert "comment" not in path.read_text("utf-8")  # 不存短評
    # 同一跑次再跑一次：覆蓋，不重複
    ai_run.evaluate_all(cur, prev, NOW, tmp_path, evaluators=ev)
    assert len(json.loads(path.read_text("utf-8"))) == 4
    # 下一跑次：append
    later = duel_doc(2, 2)
    later["generatedAt"] = "2026-10-19T08:25:00Z"
    ai_run.evaluate_all(later, cur, NOW, tmp_path, evaluators=ev)
    rows = json.loads(path.read_text("utf-8"))
    assert len(rows) == 8 and [r["run"] for r in rows[::4]] == [RUN, "2026-10-19T08:25:00Z"]


def test_merge_records_keeps_others():
    old = [{"run": "a", "airport": "X", "v": 1}, {"run": "a", "airport": "Y", "v": 1}, "壞的"]
    new = [{"run": "a", "airport": "Y", "v": 2}, {"run": "b", "airport": "X", "v": 3}]
    assert ai_run.merge_records(old, new) == [
        {"run": "a", "airport": "X", "v": 1},
        {"run": "a", "airport": "Y", "v": 2},
        {"run": "b", "airport": "X", "v": 3},
    ]


def test_no_keys_in_code():
    """程式與測試裡不能出現金鑰（粗略檢查常見的金鑰前綴與私鑰）。"""
    from conftest import ROOT

    for p in [*(ROOT / "src").rglob("*.py"), *(ROOT / "tests").rglob("*.py")]:
        text = p.read_text("utf-8")
        assert "sk-" + "ant-" not in text, p
        assert "BEGIN PRIVATE" + " KEY" not in text, p
