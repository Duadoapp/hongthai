"""Claude（Anthropic Messages API，官方 `anthropic` SDK）。金鑰只從環境變數 `ANTHROPIC_API_KEY` 讀。

- `max_tokens` 1200、單次請求逾時 60 秒、SDK 不重試（`max_retries=0`）
- 不送 `temperature`：Claude Opus 5.5 不接受取樣參數（送了回 400）。Opus 5.5 的思考關不掉、
  思考的 token 也算在 `max_tokens` 裡，所以 `effort` 用 `low`（`config.CLAUDE_EFFORT`）
- `stop_reason` 是 `refusal` → `AiError("refusal")`；`max_tokens`（被截斷）→ `bad_format`
- 不開 server-side fallback：對決要的是這個模型自己的判斷，換模型回答會記錯人
"""

from __future__ import annotations

import os

import anthropic

from .config import CLAUDE_EFFORT, MAX_TOKENS, MODELS, TIMEOUT_S
from .parse import AiError, parse_response
from .prompt import SYSTEM


def make_client() -> anthropic.Anthropic:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise AiError("no_api_key")
    return anthropic.Anthropic(api_key=key, timeout=TIMEOUT_S, max_retries=0)


def evaluate(
    text: str, *, client: anthropic.Anthropic | None = None, timeout: float = TIMEOUT_S
) -> dict:
    """一個機場的精簡文字 → `{"level", "comment"}`；失敗丟 `AiError`，不重試。"""
    client = client or make_client()
    try:
        msg = client.with_options(timeout=timeout, max_retries=0).messages.create(
            model=MODELS["claude"],
            max_tokens=MAX_TOKENS,
            system=SYSTEM,
            output_config={"effort": CLAUDE_EFFORT},
            messages=[{"role": "user", "content": text}],
        )
    except anthropic.APITimeoutError as e:  # 是 APIConnectionError 的子類別，要先接
        raise AiError("timeout") from e
    except anthropic.APIStatusError as e:
        raise AiError(f"http_{e.status_code}") from e
    except anthropic.APIConnectionError as e:
        raise AiError("network") from e
    if msg.stop_reason == "refusal":
        raise AiError("refusal")
    if msg.stop_reason == "max_tokens":
        raise AiError("bad_format", "超過 max_tokens 被截斷")
    return parse_response("".join(b.text for b in msg.content if b.type == "text"))
