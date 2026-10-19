"""模型回應的檢查（兩個模型共用）與錯誤代碼。"""

from __future__ import annotations

import json
import re

from .config import LANGS, LEVELS, MAX_COMMENT_CHARS


class AiError(Exception):
    """一次呼叫失敗；`code` 是寫進 `latest.json` 的 `error`：`no_api_key`／`timeout`／
    `bad_format`／`http_<碼>`／`network`／`refusal`（`daily_cap`、`run_cap` 由 `run.py` 判斷）。"""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def parse_response(text: str) -> dict:
    """`{"level", "comment": {四語}}`；JSON 解析失敗、`level` 不在三種裡、四語有缺或空白、
    任一語超過 `MAX_COMMENT_CHARS` 字 → `AiError("bad_format")`。外面包了 ``` 也接受。"""
    s = (text or "").strip()
    m = _FENCE.match(s)
    if m:
        s = m.group(1)
    try:
        obj = json.loads(s)
    except ValueError as e:
        raise AiError("bad_format", f"不是 JSON：{s[:80]!r}") from e
    if not isinstance(obj, dict):
        raise AiError("bad_format", "不是 JSON 物件")
    level = obj.get("level")
    if level not in LEVELS:
        raise AiError("bad_format", f"level 不對：{level!r}")
    comment = obj.get("comment")
    if not isinstance(comment, dict):
        raise AiError("bad_format", "沒有 comment")
    out = {}
    for lang in LANGS:
        c = comment.get(lang)
        if not isinstance(c, str) or not c.strip():
            raise AiError("bad_format", f"缺 {lang}")
        if len(c.strip()) > MAX_COMMENT_CHARS:
            raise AiError("bad_format", f"{lang} 超過 {MAX_COMMENT_CHARS} 字")
        out[lang] = c.strip()
    return {"level": level, "comment": out}
