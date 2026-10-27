"""模型回應的檢查（兩個模型共用）與錯誤代碼：先檢查格式（`bad_format`），再檢查用字（`bad_wording`）。"""

from __future__ import annotations

import json
import re

from .config import (
    CANCEL_TERMS,
    CANTONESE,
    CHINESE_LANGS,
    CJK_RANGES,
    EN_LEVEL_WORDS,
    EN_PLAIN_WORDS,
    EN_RISK_FORBIDDEN,
    FORBIDDEN_TOKENS,
    LANGS,
    LEVELS,
    MAX_COMMENT_CHARS,
    ONCE_IN_PARENS,
    SIMPLIFIED_CHARS,
    SOURCES,
    SUSPEND_TERMS,
    TRADITIONAL_CHARS,
    ZH_CN_TAIWAN_TERMS,
)


class AiError(Exception):
    """一次呼叫失敗；`code` 是寫進 `latest.json` 的 `error`：`no_api_key`／`timeout`／
    `bad_format`／`bad_wording`／`http_<碼>`／`network`／`refusal`（`daily_cap`、`run_cap` 由
    `run.py` 判斷）。

    `tag` 是不含短評內容的短標記（例如 `en_too_long`、`zh-HK/喺`）；`stop_reason`、`output_tokens`
    由 `claude.py`／`gemini.py` 在拿到回應後補上，`trace()` 給 log 與對決戰績的 `detail` 用；
    `usage` 是那次回應的 token 數（HD26，`ai/usage.py`），沒拿到回應是 `None`；`message` 是
    HTTP、逾時、網路錯誤時清理過的錯誤訊息（HD30，`transport_error`），其他是 `None`。"""

    def __init__(self, code: str, detail: str = "", *, tag: str = "", message: str | None = None):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.tag = tag
        self.message = message
        self.stop_reason: str | None = None
        self.output_tokens: str | None = None
        self.usage: dict | None = None

    def trace(self) -> str:
        """`<代碼>:<stop_reason>:<輸出 token 數>`，有 `tag` 時再加 `:<tag>`；沒有的欄位寫 `-`。"""
        parts = [self.code, self.stop_reason or "-", self.output_tokens or "-"]
        return ":".join([*parts, self.tag] if self.tag else parts)


def with_response(
    e: AiError, stop_reason: object, output_tokens: object, usage: dict | None = None
) -> None:
    """拿到回應之後的失敗：補上 `stop_reason`／`finish_reason`、輸出 token 數與 `usage`
    （不記內容）。"""
    e.stop_reason = None if stop_reason is None else str(stop_reason)
    e.output_tokens = None if output_tokens is None else str(output_tokens)
    e.usage = usage


# ---- 錯誤訊息（HD30） ----

MAX_MESSAGE_CHARS = 200
# 看起來像金鑰或權杖的片段：Anthropic 金鑰、Google API 金鑰、Bearer 後面、長度 ≥ 32 的英數字串
_SECRETS = [
    (re.compile("sk-" + r"ant-[A-Za-z0-9_\-]*"), "***"),  # 拆開寫：test_no_keys_in_code
    (re.compile(r"AIza[A-Za-z0-9_\-]*"), "***"),
    (re.compile(r"(Bearer\s+)\S+", re.IGNORECASE), r"\1***"),
    (re.compile(r"[A-Za-z0-9_\-]{32,}"), "***"),
]


def clean_message(raw: object) -> str | None:
    """錯誤訊息 → 遮掉金鑰樣式、換行改空白、只留前 `MAX_MESSAGE_CHARS` 字；空的是 `None`。
    先遮再截，截斷的地方不會露出半截金鑰。"""
    s = "" if raw is None else str(raw)
    for pat, repl in _SECRETS:
        s = pat.sub(repl, s)
    s = " ".join(s.split())
    return s[:MAX_MESSAGE_CHARS] or None


def exception_text(e: BaseException) -> str:
    """逾時、網路錯誤的訊息：`<例外類別>: <str(e)>`（`str(e)` 是空的只寫類別）。"""
    text = str(e)
    return f"{type(e).__name__}: {text}" if text else type(e).__name__


def transport_error(code: str, raw: object) -> AiError:
    """HTTP、逾時、網路錯誤的 `AiError`：`message` 是 `clean_message(raw)`，也放進例外的文字，
    log 那行就印得出來。不放請求內容與回應內文，只放 API 回的錯誤訊息或例外訊息。"""
    message = clean_message(raw)
    return AiError(code, message or "", message=message)


_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def _load(s: str) -> object:
    """整段解析；不行的話取第一個 `{` 到最後一個 `}` 之間再解析（前後多了說明文字）。"""
    m = _FENCE.match(s)
    if m:
        s = m.group(1)
    try:
        return json.loads(s)
    except ValueError:
        i, j = s.find("{"), s.rfind("}")
        if i < 0 or j <= i:
            raise
        return json.loads(s[i : j + 1])


def parse_response(text: str) -> dict:
    """`{"level", "sentences": {四語: [{"text", "src"}]}}`（HD40）→ `{"level", "comment",
    "sentences"}`；`comment` 是同一語的句子依序接起來（`join_sentences`），模型自己另給的
    `comment` 不用。外面包了 ``` 或前後有說明文字也接受。

    `AiError("bad_format")`：JSON 解析失敗、`level` 不在三種裡、沒有 `sentences`（舊格式只有
    `comment` 也是）、四語有缺或不是非空的陣列、句子不是 `{"text", "src"}` 或 `text` 空白、`src`
    不是非空的字串陣列或有不在 `config.SOURCES` 的代號、四語句數不同、同一個位置的 `src` 不同、
    接起來任一語超過 `MAX_COMMENT_CHARS`。格式通過後再對接起來的四語做用字檢查（`check_wording`），
    不過 → `AiError("bad_wording")`。不幫模型補代號或句子。"""
    s = (text or "").strip()
    try:
        obj = _load(s)
    except ValueError as e:
        raise AiError("bad_format", f"不是 JSON：{s[:80]!r}", tag="not_json") from e
    if not isinstance(obj, dict):
        raise AiError("bad_format", "不是 JSON 物件", tag="not_object")
    level = obj.get("level")
    if level not in LEVELS:
        raise AiError("bad_format", f"level 不對：{level!r}", tag="level")
    sentences = parse_sentences(obj.get("sentences"))
    comment = {}
    for lang in LANGS:
        c = join_sentences(lang, [x["text"] for x in sentences[lang]])
        limit = MAX_COMMENT_CHARS[lang]
        if len(c) > limit:
            raise AiError("bad_format", f"{lang} 超過 {limit} 字", tag=f"{lang}_too_long")
        comment[lang] = c
    check_wording(comment)
    return {"level": level, "comment": comment, "sentences": sentences}


def join_sentences(lang: str, texts: list[str]) -> str:
    """一語的句子接成整段短評：中文直接接（句子自己帶「。」），en 用一個空白隔開。"""
    return (" " if lang == "en" else "").join(texts)


def parse_sentences(raw: object) -> dict[str, list[dict]]:
    """`sentences` 的格式檢查（見 `parse_response`）；回傳去掉頭尾空白的
    `{四語: [{"text", "src"}]}`，`src` 照模型給的順序。"""
    if not isinstance(raw, dict):
        raise AiError("bad_format", "沒有 sentences", tag="no_sentences")
    out: dict[str, list[dict]] = {}
    for lang in LANGS:
        items = raw.get(lang)
        if not isinstance(items, list) or not items:
            raise AiError("bad_format", f"缺 {lang}", tag=f"missing_{lang}")
        out[lang] = [_sentence(lang, i, x) for i, x in enumerate(items, 1)]
    base = out[LANGS[0]]
    for lang in LANGS[1:]:
        if len(out[lang]) != len(base):
            raise AiError(
                "bad_format",
                f"{lang} 有 {len(out[lang])} 句、{LANGS[0]} 有 {len(base)} 句",
                tag="sentence_count",
            )
        for i, (a, b) in enumerate(zip(base, out[lang], strict=True), 1):
            if a["src"] != b["src"]:
                raise AiError(
                    "bad_format", f"{lang} 第 {i} 句的 src 和 {LANGS[0]} 不同", tag="src_mismatch"
                )
    return out


def _sentence(lang: str, i: int, x: object) -> dict:
    if not isinstance(x, dict):
        raise AiError("bad_format", f"{lang} 第 {i} 句不是物件", tag=f"{lang}_sentence")
    text = x.get("text")
    if not isinstance(text, str) or not text.strip():
        raise AiError("bad_format", f"{lang} 第 {i} 句沒有 text", tag=f"{lang}_sentence")
    src = x.get("src")
    if not isinstance(src, list) or not src or not all(isinstance(c, str) for c in src):
        raise AiError("bad_format", f"{lang} 第 {i} 句沒有 src", tag=f"{lang}_no_src")
    unknown = [c for c in src if c not in SOURCES]
    if unknown:  # 訊息只放代號（模型給的字串截短），不放句子
        raise AiError(
            "bad_format",
            f"{lang} 第 {i} 句有未知代號 {unknown[0][:20]!r}",
            tag=f"{lang}_src_unknown",
        )
    return {"text": text.strip(), "src": list(src)}


# ---- 用字檢查（HD6） ----


def _word(token: str) -> re.Pattern[str]:
    """整字比對、大小寫不分：前後不能是英文字母、數字或底線（中文字旁邊照樣抓得到，例如「EC陣風」）。"""
    return re.compile(rf"(?<![A-Za-z0-9_]){re.escape(token)}(?![A-Za-z0-9_])", re.IGNORECASE)


_FORBIDDEN = [(t, _word(t)) for t in FORBIDDEN_TOKENS]
_FORBIDDEN_EN = [(t, pat) for t, pat in _FORBIDDEN if t not in EN_PLAIN_WORDS]  # HD17
_ONCE = [(t, _word(t)) for t in ONCE_IN_PARENS]
_EN_LEVEL = re.compile(
    rf"[（(]\s*({'|'.join(EN_LEVEL_WORDS)})\s*[）)]",
    re.IGNORECASE,
)
_EN_RISK = [(t, re.compile(rf"\b{re.escape(t)}\b", re.IGNORECASE)) for t in EN_RISK_FORBIDDEN]
_CJK = re.compile(f"[{CJK_RANGES}]")
# 句子裡不能有精簡文字的來源標籤（HD40：代號只放 `src`），例如「[taf]」「［ifs］」
_SRC_TAG = re.compile(
    rf"[\[［]\s*({'|'.join(re.escape(c) for c in SOURCES)})\s*[\]］]", re.IGNORECASE
)


def _bad(lang: str, what: str, message: str) -> AiError:
    return AiError("bad_wording", message, tag=f"{lang}/{what}")


def _in_parens(text: str, m: re.Match[str]) -> bool:
    before, after = text[: m.start()].rstrip(), text[m.end() :].lstrip()
    return before.endswith(("(", "（")) and after.startswith((")", "）"))


def check_wording(comment: dict[str, str]) -> None:
    """四語短評的用字規則（產品負責人 2026-10-19 定案）；第一個違規丟 `AiError("bad_wording")`，
    訊息寫哪一語、哪個詞。詞表在 `config.py`。"""
    # 中文三語的叫法：有一語寫「停飛」，另一處又寫「航班取消」（任一語）
    if any(t in comment[lang] for lang in CHINESE_LANGS for t in SUSPEND_TERMS):
        for lang in CHINESE_LANGS:
            for t in CANCEL_TERMS:
                if t in comment[lang]:
                    raise _bad(lang, t, f"{lang}：叫法不一致「{t}」（要用停飛風險）")
    for lang in LANGS:
        text = comment[lang]
        if m := _SRC_TAG.search(text):
            raise _bad(lang, m.group(0), f"{lang}：來源代號寫進句子 {m.group(0)}")
        for token, pat in _FORBIDDEN_EN if lang == "en" else _FORBIDDEN:
            if pat.search(text):
                raise _bad(lang, token, f"{lang}：內部代號 {token}")
        for token, pat in _ONCE:
            found = list(pat.finditer(text))
            if len(found) > 1:
                raise _bad(lang, token, f"{lang}：{token} 出現第 2 次")
            if found and not _in_parens(text, found[0]):
                raise _bad(lang, token, f"{lang}：{token} 沒放在括號裡")
        if lang in CHINESE_LANGS:
            m = _EN_LEVEL.search(text)
            if m:
                raise _bad(lang, m.group(0), f"{lang}：英文等級字 {m.group(0)}")
        if lang == "zh-HK":
            for w in CANTONESE:
                if w in text:
                    raise _bad(lang, w, f"{lang}：粵語口語「{w}」")
        if lang == "zh-CN":
            for ch in TRADITIONAL_CHARS:
                if ch in text:
                    raise _bad(lang, ch, f"{lang}：繁體字「{ch}」")
            for w in ZH_CN_TAIWAN_TERMS:
                if w in text:
                    raise _bad(lang, w, f"{lang} 用了台灣用語：{w}")
        if lang in ("zh-TW", "zh-HK"):
            for ch in SIMPLIFIED_CHARS:
                if ch in text:
                    raise _bad(lang, ch, f"{lang}：簡體字「{ch}」")
        if lang == "en":
            m = _CJK.search(text)
            if m:
                raise _bad(lang, m.group(0), f"en 含中日文字「{m.group(0)}」")
            for term, pat in _EN_RISK:
                if pat.search(text):
                    raise _bad(lang, term, f"{lang}：叫法不一致「{term}」（要用 disruption risk）")
