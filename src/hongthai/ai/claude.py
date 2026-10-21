"""Claude（Anthropic Messages API，官方 `anthropic` SDK）。金鑰只從環境變數 `ANTHROPIC_API_KEY` 讀。

- `max_tokens` 3000（HD6；HD5 的 1200 不夠）、單次請求逾時 60 秒、SDK 不重試（`max_retries=0`）
- 不送 `temperature`：Claude Opus 5.5 不接受取樣參數（送了回 400）。Opus 5.5 的思考關不掉、
  思考的 token 也算在 `max_tokens` 裡，所以 `effort` 用 `low`（`config.CLAUDE_EFFORT`）
- `stop_reason` 是 `refusal` → `AiError("refusal")`；`max_tokens`（被截斷）→ `bad_format`
- 拿到回應之後的失敗都附 `stop_reason` 與 `usage.output_tokens`（含思考），給戰績的 `detail`
- 不開 server-side fallback：對決要的是這個模型自己的判斷，換模型回答會記錯人
- 提示快取（HD26）：`system` 送成一個 text block（內容就是 `SYSTEM`，一個字不改）加
  `cache_control: ephemeral`（預設 5 分鐘 TTL）。Opus 5.5 最小可快取長度 512 token，`SYSTEM` 不到時
  API 不報錯、只是不快取（`cacheWrite`／`cacheRead` 一直是 0）
- 每次有回應（成功或失敗）都取 `usage`（`usage_of`）：成功時放在回傳的 `usage`、失敗時在
  `AiError.usage`，給戰績與 `timing/`（`ai/usage.py`）
"""

from __future__ import annotations

import os

import anthropic

from .config import CLAUDE_EFFORT, MAX_TOKENS, MODELS, TIMEOUT_S
from .parse import AiError, parse_response, with_response
from .prompt import SYSTEM
from .usage import as_count

TIMEOUT = TIMEOUT_S["claude"]
# 系統提示當快取前綴（HD26）；每次送同一個 list，內容與 `SYSTEM` 完全相同
SYSTEM_BLOCKS = [{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}]


def make_client() -> anthropic.Anthropic:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise AiError("no_api_key")
    return anthropic.Anthropic(api_key=key, timeout=TIMEOUT, max_retries=0)


def evaluate(
    text: str, *, client: anthropic.Anthropic | None = None, timeout: float = TIMEOUT
) -> dict:
    """一個機場的精簡文字 → `{"level", "comment", "usage"}`；失敗丟 `AiError`，這裡不重試
    （快回的 `http_503`／`http_504` 由 `run.py` 重試一次，HD17、HD23）。"""
    client = client or make_client()
    try:
        msg = client.with_options(timeout=timeout, max_retries=0).messages.create(
            model=MODELS["claude"],
            max_tokens=MAX_TOKENS,
            system=SYSTEM_BLOCKS,
            output_config={"effort": CLAUDE_EFFORT},
            messages=[{"role": "user", "content": text}],
        )
    except anthropic.APITimeoutError as e:  # 是 APIConnectionError 的子類別，要先接
        raise AiError("timeout") from e
    except anthropic.APIStatusError as e:
        raise AiError(f"http_{e.status_code}") from e
    except anthropic.APIConnectionError as e:
        raise AiError("network") from e
    usage = getattr(msg, "usage", None)
    try:
        if msg.stop_reason == "refusal":
            raise AiError("refusal")
        if msg.stop_reason == "max_tokens":
            raise AiError("bad_format", "超過 max_tokens 被截斷")
        result = parse_response("".join(b.text for b in msg.content if b.type == "text"))
    except AiError as e:
        with_response(e, msg.stop_reason, getattr(usage, "output_tokens", None), usage_of(msg))
        raise
    return {**result, "usage": usage_of(msg)}


def usage_of(msg: object) -> dict | None:
    """回應的 token 數（`ai/usage.py`）；沒有 `usage` 是 `None`，缺的欄位是 `None`（不寫 0）。"""
    u = getattr(msg, "usage", None)
    if u is None:
        return None
    return {
        "input": as_count(getattr(u, "input_tokens", None)),
        "output": as_count(getattr(u, "output_tokens", None)),
        "cacheRead": as_count(getattr(u, "cache_read_input_tokens", None)),
        "cacheWrite": as_count(getattr(u, "cache_creation_input_tokens", None)),
    }
