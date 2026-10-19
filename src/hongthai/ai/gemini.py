"""Gemini（Vertex AI，`google-genai` SDK）。

環境變數：
- `GOOGLE_SERVICE_ACCOUNT_JSON`：服務帳號金鑰 JSON 整份原文（不是 base64）；用 `json.loads` 讀、
  交給 `service_account.Credentials.from_service_account_info`，不寫到磁碟
- `GOOGLE_CLOUD_PROJECT`、`GOOGLE_CLOUD_LOCATION`（`global`；Argon 只開 global、us、eu）
少任一個或 JSON 讀不了 → `no_api_key`。

- `max_output_tokens` 1200、`temperature` 0.3、回應要求 JSON（`response_mime_type`）
- 單次請求逾時 60 秒；SDK 沒設 `retry_options` 就不重試
- `finish_reason` 是 `MAX_TOKENS`（被截斷）→ `bad_format`；安全過濾之類擋下 → `refusal`
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

from .config import ENV, MAX_TOKENS, MODELS, TEMPERATURE, TIMEOUT_S
from .parse import AiError, parse_response
from .prompt import SYSTEM

SCOPES = ("https://www.googleapis.com/auth/cloud-platform",)


def make_client() -> genai.Client:
    raw, project, location = (os.environ.get(k) for k in ENV["gemini"])
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
        http_options=types.HttpOptions(timeout=TIMEOUT_S * 1000),
    )


def evaluate(text: str, *, client: genai.Client | None = None, timeout: float = TIMEOUT_S) -> dict:
    """一個機場的精簡文字 → `{"level", "comment"}`；失敗丟 `AiError`，不重試。"""
    client = client or make_client()
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM,
        temperature=TEMPERATURE,
        max_output_tokens=MAX_TOKENS,
        response_mime_type="application/json",
        http_options=types.HttpOptions(timeout=int(timeout * 1000)),  # 毫秒
    )
    try:
        resp = client.models.generate_content(model=MODELS["gemini"], contents=text, config=config)
    except errors.APIError as e:
        raise AiError(f"http_{e.code}") from e
    except (httpx.TimeoutException, requests.Timeout) as e:
        raise AiError("timeout") from e
    except auth_exceptions.RefreshError as e:  # 服務帳號換不到 token（金鑰被撤銷、權限不對）
        raise AiError("http_401") from e
    except (httpx.HTTPError, requests.RequestException, auth_exceptions.GoogleAuthError) as e:
        raise AiError("network") from e
    cands = resp.candidates or []
    reason = cands[0].finish_reason if cands else None
    if reason == types.FinishReason.MAX_TOKENS:
        raise AiError("bad_format", "超過 max_output_tokens 被截斷")
    if not cands or reason not in (None, types.FinishReason.STOP):
        raise AiError("refusal", str(reason or (resp.prompt_feedback or "沒有 candidates")))
    parts = (cands[0].content.parts if cands[0].content else None) or []
    text = "".join(p.text for p in parts if isinstance(p.text, str) and not p.thought)
    return parse_response(text)
