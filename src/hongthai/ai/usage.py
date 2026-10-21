"""每次呼叫的 token 數（HD26）：合計、快取命中率、估計費用。`run.py`（`timing/` 的 `ai` 那行）與
`tools/ai_cost.py` 共用；從回應取數字在 `claude.usage_of`、`gemini.usage_of`。

一次呼叫的 `usage`（戰績 `history/ai/<日期>.json` 那筆；沒拿到回應是 `null`，缺的欄位是 `null`）：
- Claude：`{"input", "output", "cacheRead", "cacheWrite"}`＝`input_tokens`、`output_tokens`
  （含思考）、`cache_read_input_tokens`、`cache_creation_input_tokens`。`input_tokens` **不含**
  快取讀寫的部分
- Gemini：`{"input", "output", "thinking", "cacheRead"}`＝`prompt_token_count`（**含**快取命中的
  部分）、`candidates_token_count`、`thoughts_token_count`、`cached_content_token_count`

命中率（`hit_rate`）：Claude 是 `cacheRead ÷ (input + cacheRead + cacheWrite)`、Gemini 是
`cacheRead ÷ input`，兩個都是「整個輸入裡有多少是從快取讀的」。Gemini 沒命中時回應不帶
`cached_content_token_count`、沒思考時不帶 `thoughts_token_count`（proto 的 0 不輸出），
所以算命中率與費用時 `cacheRead`、`cacheWrite`、`thinking` 缺的當 0；`input`、`output` 缺的整筆不算
（費用、命中率是 `None`）。
"""

from __future__ import annotations

from collections.abc import Iterable

from .config import PRICES

FIELDS = {
    "claude": ("input", "output", "cacheRead", "cacheWrite"),
    "gemini": ("input", "output", "thinking", "cacheRead"),
}
# 缺了當 0 的欄位（見上面）
OPTIONAL = ("cacheRead", "cacheWrite", "thinking")


def as_count(v: object) -> int | None:
    """SDK 給的數字 → `int`；沒有或不是整數是 `None`（不寫 0）。"""
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def total(key: str, usages: Iterable[dict | None]) -> dict:
    """多次呼叫加總：每個欄位只加有數字的，全部都缺是 `None`；`calls` 是有 `usage`（有回應）的
    次數。"""
    out: dict[str, int | None] = dict.fromkeys(FIELDS[key])
    calls = 0
    for u in usages:
        if not isinstance(u, dict):
            continue
        calls += 1
        for f in FIELDS[key]:
            if (v := as_count(u.get(f))) is not None:
                out[f] = (out[f] or 0) + v
    return {**out, "calls": calls}


def price(key: str, day: str) -> dict[str, float | None] | None:
    """`day`（`YYYY-MM-DD`，UTC）那天的單價（美元／百萬 token）；沒有是 `None`。"""
    for last, p in PRICES.get(key, []):
        if last is None or day <= last:
            return p
    return None


def _n(u: dict, f: str) -> int | None:
    v = as_count(u.get(f))
    return 0 if v is None and f in OPTIONAL else v


def cost_usd(key: str, usage: dict | None, day: str) -> float | None:
    """一次（或加總後）的估計費用（美元，6 位小數）；`usage` 是 `None`、`input`／`output` 缺、
    或用到的單價是 `None` 都回 `None`。"""
    p = price(key, day)
    if not isinstance(usage, dict) or p is None:
        return None
    n = {f: _n(usage, f) for f in FIELDS[key]}
    if n["input"] is None or n["output"] is None:
        return None
    if key == "claude":
        parts = {f: n[f] for f in ("input", "output", "cacheRead", "cacheWrite")}
    else:  # Gemini：`input` 含快取命中的部分；思考算 output
        cached = n["cacheRead"] or 0
        parts = {
            "input": n["input"] - cached,
            "cacheRead": cached,
            "output": n["output"] + (n["thinking"] or 0),
        }
    total_usd = 0.0
    for f, tokens in parts.items():
        if not tokens:
            continue
        if (rate := p.get(f)) is None:
            return None
        total_usd += tokens * rate / 1_000_000
    return round(total_usd, 6)


def hit_rate(key: str, usage: dict | None) -> float | None:
    """快取命中率（0–1）；分母是 0 或 `input` 缺時 `None`。公式見模組說明。"""
    if not isinstance(usage, dict) or (inp := as_count(usage.get("input"))) is None:
        return None
    read = _n(usage, "cacheRead") or 0
    whole = inp + read + (_n(usage, "cacheWrite") or 0) if key == "claude" else inp
    return read / whole if whole else None
