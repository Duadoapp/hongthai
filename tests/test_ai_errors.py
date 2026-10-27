"""HD30：AI 呼叫失敗時記下錯誤訊息——`AiError.message` 的取法與清理（≤ 200 字、換行改空白、
遮金鑰樣式）、戰績的 `message`、`timing/` 的 `errorMessages`；`latest.json` 的 `sources.ai` 不變。

全部不連網：SDK 的例外用真的類別建、`Duel` 的模型換成假的 `evaluate`。
"""

from __future__ import annotations

import json
import threading
from types import SimpleNamespace

import anthropic
import httpx2
import pytest
from google.genai import errors as genai_errors
from test_ai import NOW, FakeAnthropic, FakeGenai, _msg, duel_doc, fake_model, ok_result

from hongthai import build
from hongthai.ai import claude, gemini, parse
from hongthai.ai import run as ai_run
from hongthai.ai.parse import AiError

_REQ = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
CREDIT = (
    "Your credit balance is too low to access the Anthropic API. "
    "Please go to Plans & Billing to upgrade or purchase credits."
)
CREDIT_BODY = {"type": "error", "error": {"type": "invalid_request_error", "message": CREDIT}}
CREDIT_MESSAGE = f"invalid_request_error: {CREDIT}"
ANTHROPIC_PREFIX = "sk-" + "ant-"  # 拆開寫：test_no_keys_in_code
FAKE_ANTHROPIC_KEY = ANTHROPIC_PREFIX + "api03-" + "Ab1_" * 20
FAKE_GOOGLE_KEY = "AIza" + "x9Y-" * 9
LONG_TOKEN = "Q" * 40


def _status_error(status: int, body: object) -> anthropic.APIStatusError:
    """照 SDK 收到錯誤回應時的做法建例外（`body` 是整份 JSON、訊息是 `Error code: ...`）。"""
    response = httpx2.Response(status, json=body, request=_REQ)
    client = anthropic.Anthropic(api_key="test-not-a-real-key", max_retries=0)
    return client._make_status_error_from_response(response)


def _claude_error(exc: Exception) -> AiError:
    with pytest.raises(AiError) as e:
        claude.evaluate("文字", client=FakeAnthropic(exc=exc))
    return e.value


def _gemini_error(exc: Exception) -> AiError:
    with pytest.raises(AiError) as e:
        gemini.evaluate("文字", client=FakeGenai(exc=exc))
    return e.value


def _no_secrets(s: str) -> None:
    for secret in (ANTHROPIC_PREFIX, "AIza", LONG_TOKEN, "Ab1_Ab1_", "x9Y-x9Y-"):
        assert secret not in s


# ---- 清理 ----


def test_clean_message_masks_secrets():
    raw = (
        f"key {FAKE_ANTHROPIC_KEY} and {FAKE_GOOGLE_KEY}\n"
        f"Authorization: Bearer abc.def-ghi\r\n\ttoken={LONG_TOKEN} short=abcdef0123456789"
    )
    out = parse.clean_message(raw)
    assert out == ("key *** and *** Authorization: Bearer *** token=*** short=abcdef0123456789")
    _no_secrets(out)


def test_clean_message_cut_and_empty():
    assert parse.MAX_MESSAGE_CHARS == 200
    out = parse.clean_message("錯誤 " * 300)
    assert out is not None and len(out) == 200 and "\n" not in out
    # 先遮再截：金鑰跨過第 200 字也不會露出前半截
    out = parse.clean_message("a " * 95 + FAKE_ANTHROPIC_KEY)
    assert out is not None and len(out) <= 200 and out.endswith("***")
    _no_secrets(out)
    assert parse.clean_message("") is None
    assert parse.clean_message(None) is None
    assert parse.clean_message(" \n ") is None


def test_transport_error_message_in_log_text():
    e = parse.transport_error("http_400", "invalid_request_error: 餘額\n不足")
    assert e.code == "http_400" and e.message == "invalid_request_error: 餘額 不足"
    assert str(e) == "http_400: invalid_request_error: 餘額 不足"  # log 那行印這個
    assert e.trace() == "http_400:-:-"  # detail 不變
    assert AiError("bad_format", "不是 JSON：'…'").message is None  # 內容錯誤不記訊息


# ---- Claude ----


def test_claude_400_credit_balance():
    e = _claude_error(_status_error(400, CREDIT_BODY))
    assert e.code == "http_400" and e.trace() == "http_400:-:-"
    assert e.message == CREDIT_MESSAGE and len(e.message) <= 200


def test_claude_status_message_cleaned_and_fallback():
    body = {
        "type": "error",
        "error": {
            "type": "authentication_error",
            "message": f"invalid x-api-key {FAKE_ANTHROPIC_KEY}\n" + "詳細 " * 200,
        },
    }
    e = _claude_error(_status_error(401, body))
    assert e.code == "http_401" and e.message is not None
    assert e.message.startswith("authentication_error: invalid x-api-key *** 詳細")
    assert len(e.message) == 200 and "\n" not in e.message
    _no_secrets(e.message)
    # 不是 {"error": {...}} 的回應：用 str(e)
    e = _claude_error(
        anthropic.APIStatusError(
            "upstream down", response=httpx2.Response(529, request=_REQ), body=None
        )
    )
    assert e.code == "http_529" and e.message == "upstream down"


@pytest.mark.parametrize(
    ("exc", "code", "message"),
    [
        (
            anthropic.APITimeoutError(request=_REQ),
            "timeout",
            "APITimeoutError: Request timed out or interrupted.",
        ),
        (
            anthropic.APIConnectionError(request=_REQ),
            "network",
            "APIConnectionError: Connection error.",
        ),
    ],
)
def test_claude_timeout_network_message(exc, code, message):
    e = _claude_error(exc)
    assert e.code == code and e.message is not None
    assert e.message.startswith(message) and len(e.message) <= 200


def test_claude_content_errors_no_message():
    with pytest.raises(AiError) as e:
        claude.evaluate("文字", client=FakeAnthropic(_msg("不是 JSON")))
    assert e.value.code == "bad_format" and e.value.message is None


# ---- Gemini ----


def test_gemini_504():
    body = {
        "error": {
            "code": 504,
            "message": "Deadline expired before operation could complete.",
            "status": "DEADLINE_EXCEEDED",
        }
    }
    e = _gemini_error(genai_errors.ServerError(504, body))
    assert e.code == "http_504" and e.trace() == "http_504:-:-"
    assert e.message == "DEADLINE_EXCEEDED: Deadline expired before operation could complete."


def test_gemini_status_message_cleaned_and_fallback():
    body = {"error": {"code": 403, "message": f"API key {FAKE_GOOGLE_KEY} not valid\nfor this"}}
    e = _gemini_error(genai_errors.ClientError(403, body))
    assert e.message == "API key *** not valid for this"  # 沒有 status 只寫 message
    e = _gemini_error(genai_errors.ServerError(503, {}))  # 什麼都沒有：str(e)
    assert e.code == "http_503" and e.message == "503 None. {}"


@pytest.mark.parametrize(
    ("exc", "code", "message"),
    [
        (
            gemini.httpx.ReadTimeout("The read operation timed out"),
            "timeout",
            "ReadTimeout: The read operation timed out",
        ),
        (gemini.requests.ReadTimeout("read timed out"), "timeout", "ReadTimeout: read timed out"),
        (gemini.requests.ConnectionError("down"), "network", "ConnectionError: down"),
        (
            gemini.auth_exceptions.RefreshError("invalid_grant"),
            "http_401",
            "RefreshError: invalid_grant",
        ),
    ],
)
def test_gemini_timeout_network_message(exc, code, message):
    e = _gemini_error(exc)
    assert (e.code, e.message) == (code, message)


# ---- 戰績、timing、latest.json ----


def msg_model(*outcomes: tuple[str, str] | None):
    """依序回 `outcomes`（`(代碼, 訊息)`，`None` 是成功）；用完了就重複最後一個。"""
    n = {"i": 0}
    lock = threading.Lock()

    def evaluate(text, *, client=None, timeout=60):
        with lock:
            out = outcomes[min(n["i"], len(outcomes) - 1)]
            n["i"] += 1
        if out:
            raise parse.transport_error(*out)
        return ok_result("high")

    return SimpleNamespace(make_client=object, evaluate=evaluate)


def _rows(tmp_path) -> dict[str, dict]:
    rows = json.loads((tmp_path / "ai" / "2026-10-19.json").read_text("utf-8"))
    return {r["airport"]: r for r in rows}


def test_duel_records_messages(tmp_path):
    """Claude 3 個全部 400（餘額不足）：每筆記 `message`、`errorMessages` 只一則；Gemini 成功沒有
    `message`。`latest.json` 的 `sources.ai` 照舊只有代碼。"""
    ev = {"claude": msg_model(("http_400", CREDIT_MESSAGE)), "gemini": fake_model()}
    res = ai_run.evaluate_all(duel_doc(3, 1), None, NOW, tmp_path, evaluators=ev)
    rows = _rows(tmp_path)
    for icao in ("RC00", "RC01", "RC02"):
        assert rows[icao]["claude"]["detail"] == "http_400:-:-"
        assert rows[icao]["claude"]["message"] == CREDIT_MESSAGE
        assert "message" not in rows[icao]["gemini"]
    assert "message" not in rows["ZZ00"]["claude"]  # skipped
    assert res["errorMessages"] == {"claude": CREDIT_MESSAGE, "gemini": None}
    src = res["source"]
    assert src["errors"] == {"claude": "http_400"}
    assert "errorMessages" not in src and "message" not in json.dumps(src)
    for a in res["airports"].values():
        assert all("message" not in a[k] for k in ("claude", "gemini"))


def test_duel_retry_message(tmp_path):
    """503 重試後 429：戰績記第二次的訊息，`errorMessages` 是第一則（重試前那次）。"""
    ge = msg_model(
        ("http_503", "UNAVAILABLE: overloaded"), ("http_429", "RESOURCE_EXHAUSTED: quota")
    )
    res = ai_run.evaluate_all(
        duel_doc(1, 0), None, NOW, tmp_path, evaluators={"claude": fake_model(), "gemini": ge}
    )
    g = _rows(tmp_path)["RC00"]["gemini"]
    assert g["detail"] == "http_429:-:-:retried" and g["message"] == "RESOURCE_EXHAUSTED: quota"
    assert res["errorMessages"] == {"claude": None, "gemini": "UNAVAILABLE: overloaded"}


def test_duel_retry_then_ok_keeps_first_message(tmp_path):
    ge = msg_model(("http_504", "DEADLINE_EXCEEDED: x"), None)
    res = ai_run.evaluate_all(
        duel_doc(1, 0), None, NOW, tmp_path, evaluators={"claude": fake_model(), "gemini": ge}
    )
    g = _rows(tmp_path)["RC00"]["gemini"]
    assert g["status"] == "ok" and "message" not in g and "detail" not in g
    assert res["errorMessages"]["gemini"] == "DEADLINE_EXCEEDED: x"


def test_duel_content_error_no_message(tmp_path):
    ev = {"claude": fake_model(exc="bad_format"), "gemini": fake_model()}
    res = ai_run.evaluate_all(duel_doc(1, 0), None, NOW, tmp_path, evaluators=ev)
    c = _rows(tmp_path)["RC00"]["claude"]
    assert c["detail"] == "bad_format:-:-:not_json" and "message" not in c
    assert res["errorMessages"] == {"claude": None, "gemini": None}


def test_run_ai_timing_error_messages(tmp_path, monkeypatch):
    """`timing/` 的 `ai` 那行多 `errorMessages`；`latest.json` 的 `sources.ai` 不加。"""
    monkeypatch.setattr(
        ai_run,
        "EVALUATORS",
        {"claude": msg_model(("http_400", CREDIT_MESSAGE)), "gemini": fake_model()},
    )
    latest = duel_doc(2, 0)
    timing = build.Timing(tmp_path, NOW)
    build.run_ai(latest, None, NOW, tmp_path / "history", timing)
    line = json.loads(timing.path.read_text("utf-8").splitlines()[-1])
    assert line["source"] == "ai"
    assert line["errorMessages"] == {"claude": CREDIT_MESSAGE, "gemini": None}
    src = latest["sources"]["ai"]
    assert src["errors"] == {"claude": "http_400"} and "errorMessages" not in src
    assert set(src) == {"ok", "seconds", "calls", "errors"}


def test_run_ai_fallback_timing_error_messages_null(tmp_path, monkeypatch):
    def crash(*a, **k):
        raise RuntimeError("bug")

    monkeypatch.setattr(build.ai, "Duel", crash)
    timing = build.Timing(tmp_path, NOW)
    build.run_ai(duel_doc(1, 0), None, NOW, tmp_path / "history", timing)
    line = json.loads(timing.path.read_text("utf-8").splitlines()[-1])
    assert line["errorMessages"] is None
