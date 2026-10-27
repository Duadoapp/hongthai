"""Gemini（Vertex AI，`google-genai` SDK）。

環境變數：
- `GOOGLE_SERVICE_ACCOUNT_JSON`：服務帳號金鑰 JSON 整份原文（不是 base64）；用 `json.loads` 讀、
  交給 `service_account.Credentials.from_service_account_info`，不寫到磁碟
- `GOOGLE_CLOUD_PROJECT`、`GOOGLE_CLOUD_LOCATION`（`global`；Argon 只開 global、us、eu）
少任一個或 JSON 讀不了 → `no_api_key`。
- `GOOGLE_CLOUD_LOCATION_FALLBACK`（HD23，選填）：備援區域，沒設是 `us`、設成空字串＝關掉
  （和主要區域一樣也當關掉）。什麼時候切過去由 `run.py` 決定（`config.FALLBACK_AFTER`），
  用同一把服務帳號

- `max_output_tokens` 3000、`temperature` 0.3、回應要求 JSON（`response_mime_type`）
- 思考：`thinking_level` LOW（`config.GEMINI_THINKING_LEVEL`）、`include_thoughts=False`。
  Gemini 4 的思考關不掉、不接受 `thinking_budget`（送了回 400）、不支援 MINIMAL，LOW 是最低（HD6）
- 單次請求逾時 45 秒（`config.TIMEOUT_S`，HD23 前 60 秒）；SDK 沒設 `retry_options` 就不重試
- `finish_reason` 是 `MAX_TOKENS`（被截斷）→ `bad_format`；安全過濾之類擋下 → `refusal`
- 拿到回應之後的失敗都附 `finish_reason` 與輸出 token 數（`candidates_token_count`，有思考時寫成
  `<回答>+<思考>`），給戰績的 `detail`
- 快取（HD26）：靠 Vertex 的**隱含快取**（預設開、不用改送法；Gemini 4 最小 4,096 token，同樣前綴
  命中時 `cached_content_token_count` > 0），`system_instruction` 每次一樣就是前綴。不做顯式
  context caching（`CachedContent` 要多一次呼叫、按小時收儲存費）
- 每次有回應（成功或失敗）都取 `usage_metadata` 的四個數（`usage_of`）：成功時放在回傳的 `usage`、
  失敗時在 `AiError.usage`，給戰績與 `timing/`（`ai/usage.py`）
- 錯誤訊息（HD30）：HTTP 錯誤取 `errors.APIError` 的 `status`／`message` → `"<status>: <message>"`
  （都取不到用 `str(e)`），逾時、網路、換 token 的錯誤是例外類別＋`str(e)`，清理後放
  `AiError.message`
"""

from __future__ import annotations

import json
import os

import httpx
import requests
from google import genai
from google.auth import exceptions as auth_exceptions
from google.genai import errors, types
from google.oauth2 import service_account

from .config import ENV, GEMINI_THINKING_LEVEL, MAX_TOKENS, MODELS, TEMPERATURE, TIMEOUT_S
from .parse import AiError, exception_text, parse_response, transport_error, with_response
from .prompt import SYSTEM
from .usage import as_count

SCOPES = ("https://www.googleapis.com/auth/cloud-platform",)
TIMEOUT = TIMEOUT_S["gemini"]
FALLBACK_ENV = "GOOGLE_CLOUD_LOCATION_FALLBACK"
FALLBACK_DEFAULT = "us"


def locations() -> tuple[str | None, str | None]:
    """（主要區域, 備援區域）；備援沒開（設成空字串、或和主要一樣）是 `None`。"""
    primary = os.environ.get(ENV["gemini"][2]) or None
    backup = os.environ.get(FALLBACK_ENV, FALLBACK_DEFAULT).strip() or None
    return primary, None if backup == primary else backup


def make_client(location: str | None = None) -> genai.Client:
    """`location` 是 `None` 用 `GOOGLE_CLOUD_LOCATION`；備援區域由 `run.py` 傳進來。"""
    raw, project, primary = (os.environ.get(k) for k in ENV["gemini"])
    location = location or primary
    if not (raw and project and location):
        raise AiError("no_api_key")
    try:
        info = json.loads(raw)
        creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    except (ValueError, KeyError, TypeError) as e:  # 訊息裡不放 JSON 內容
        raise AiError("no_api_key", "GOOGLE_SERVICE_ACCOUNT_JSON 讀不了") from e
    return genai.Client(
        vertexai=True,
        project=project,
        location=location,
        credentials=creds,
        http_options=types.HttpOptions(timeout=TIMEOUT * 1000),
    )


def evaluate(text: str, *, client: genai.Client | None = None, timeout: float = TIMEOUT) -> dict:
    """一個機場的精簡文字 → `{"level", "comment", "sentences", "usage"}`；失敗丟 `AiError`，
    這裡不重試（快回的 `http_503`／`http_504` 由 `run.py` 重試一次、切備援區域也在 `run.py`，
    HD17、HD23）。"""
    client = client or make_client()
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM,
        temperature=TEMPERATURE,
        max_output_tokens=MAX_TOKENS,
        response_mime_type="application/json",
        thinking_config=types.ThinkingConfig(
            thinking_level=types.ThinkingLevel(GEMINI_THINKING_LEVEL), include_thoughts=False
        ),
        http_options=types.HttpOptions(timeout=int(timeout * 1000)),  # 毫秒
    )
    try:
        resp = client.models.generate_content(model=MODELS["gemini"], contents=text, config=config)
    except errors.APIError as e:
        raise transport_error(f"http_{e.code}", status_message(e)) from e
    except (httpx.TimeoutException, requests.Timeout) as e:
        raise transport_error("timeout", exception_text(e)) from e
    except auth_exceptions.RefreshError as e:  # 服務帳號換不到 token（金鑰被撤銷、權限不對）
        raise transport_error("http_401", exception_text(e)) from e
    except (httpx.HTTPError, requests.RequestException, auth_exceptions.GoogleAuthError) as e:
        raise transport_error("network", exception_text(e)) from e
    cands = resp.candidates or []
    reason = cands[0].finish_reason if cands else None
    try:
        if reason == types.FinishReason.MAX_TOKENS:
            raise AiError("bad_format", "超過 max_output_tokens 被截斷")
        if not cands or reason not in (None, types.FinishReason.STOP):
            raise AiError("refusal", str(reason or (resp.prompt_feedback or "沒有 candidates")))
        parts = (cands[0].content.parts if cands[0].content else None) or []
        text = "".join(p.text for p in parts if isinstance(p.text, str) and not p.thought)
        result = parse_response(text)
    except AiError as e:
        with_response(e, getattr(reason, "name", reason), output_tokens(resp), usage_of(resp))
        raise
    return {**result, "usage": usage_of(resp)}


def status_message(e: errors.APIError) -> str:
    """HTTP 錯誤時 API 回的錯誤訊息（HD30）：`"<status>: <message>"`（只有一個就只寫那個）；
    都沒有用 `str(e)`。"""
    parts = [str(x) for x in (e.status, e.message) if x]
    return ": ".join(parts) if parts else str(e)


def usage_of(resp: types.GenerateContentResponse) -> dict | None:
    """回應的 token 數（`ai/usage.py`）；沒有 `usage_metadata` 是 `None`，缺的欄位是 `None`
    （不寫 0）。"""
    u = resp.usage_metadata
    if u is None:
        return None
    return {
        "input": as_count(u.prompt_token_count),
        "output": as_count(u.candidates_token_count),
        "thinking": as_count(u.thoughts_token_count),
        "cacheRead": as_count(u.cached_content_token_count),
    }


def output_tokens(resp: types.GenerateContentResponse) -> str | None:
    """`<回答>` 或 `<回答>+<思考>` 的 token 數；沒有 `usage_metadata` 時 `None`。"""
    u = resp.usage_metadata
    if u is None:
        return None
    out = str(u.candidates_token_count or 0)
    return f"{out}+{u.thoughts_token_count}" if u.thoughts_token_count else out
