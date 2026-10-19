"""AI 對決的設定集中在這裡：換模型、改上限只改這個檔。

金鑰只從環境變數讀（`ENV`），程式與測試裡不能出現任何金鑰。
"""

from __future__ import annotations

MODELS = {"claude": "claude-opus-5-5", "gemini": "gemini-4-argon"}
KEYS = tuple(MODELS)  # `latest.json` 的鍵名（模型換版不用改鍵名）

# 每個模型要的環境變數；少任一個就 `no_api_key`、不呼叫
ENV = {
    "claude": ("ANTHROPIC_API_KEY",),
    "gemini": ("GOOGLE_SERVICE_ACCOUNT_JSON", "GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_LOCATION"),
}

MAX_TOKENS = 1200
TEMPERATURE = 0.3  # 只有 Gemini 用：Claude Opus 5.5 不接受 temperature（送了回 400）
CLAUDE_EFFORT = "low"  # Opus 5.5 的思考關不掉、算在 max_tokens 裡；用 low 留空間給四語短評
TIMEOUT_S = 60  # 單次請求

MAX_AIRPORTS = 20  # 每報最多評幾個機場
DAILY_CAP = 80  # 每天（UTC）每個模型最多呼叫幾次
WORKERS = 4  # 每個模型幾條並行

LEVELS = ("low", "medium", "high")
LANGS = ("zh-TW", "zh-HK", "zh-CN", "en")
MAX_COMMENT_CHARS = 400  # 任一語超過就當格式不對

DISCLAIMER = {
    "zh-TW": "AI 評論僅供參考，以航空公司與機場公告為準",
    "zh-HK": "AI 評論僅供參考，以航空公司及機場公告為準",
    "zh-CN": "AI 评论仅供参考，以航空公司与机场公告为准",
    "en": "AI commentary is for reference only; follow airline and airport announcements.",
}

# 沒被選的機場兩顆 AI 燈的固定短評（不呼叫）
NO_RISK = {
    "zh-TW": "沒看到明顯風險",
    "zh-HK": "未見明顯風險",
    "zh-CN": "未见明显风险",
    "en": "No notable risk seen",
}
