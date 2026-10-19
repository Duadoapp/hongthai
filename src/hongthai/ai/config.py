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

# 兩個模型的思考 token 都算在輸出上限裡（HD6）：四語短評本身約 600–900 token，其他留給思考
MAX_TOKENS = 3000
TEMPERATURE = 0.3  # 只有 Gemini 用：Claude Opus 5.5 不接受 temperature（送了回 400）
CLAUDE_EFFORT = "low"  # Opus 5.5 的思考關不掉、算在 max_tokens 裡；用 low 留空間給四語短評
# Gemini 4 只接受 `thinking_level`（送 `thinking_budget` 回 400），不支援 MINIMAL；LOW 是最低
GEMINI_THINKING_LEVEL = "LOW"
TIMEOUT_S = 60  # 單次請求
# 只重試一次的錯誤（HD17）：閘道沒回應（Vertex 504 卡 57 秒才回），不是模型回了壞東西、也不計費；
# 同一個請求、不改內容，剩餘預算 ≥ `RETRY_MIN_LEFT_S` 才重試（一次請求逾時 60 秒）。
# 429、400、`bad_format`、`bad_wording`、`refusal` 都不重試
RETRY_CODES = ("http_503", "http_504")
RETRY_MIN_LEFT_S = 70

MAX_AIRPORTS = 20  # 每報最多評幾個機場
# 每天（UTC）每個模型最多呼叫幾次；0 代表不限（開發期間，2026-10-19 定案；
# 正式推廣前再評估，恢復時改成 80 之類的數字即可）
DAILY_CAP = 0
# 每個模型幾條並行。Gemini 4 條時撞過 429、降到 2（HD6）；HD12 升回 3 再觀察，429 回來就降回 2
PARALLEL = {"claude": 4, "gemini": 3}

LEVELS = ("low", "medium", "high")
LANGS = ("zh-TW", "zh-HK", "zh-CN", "en")
# 任一語超過就當格式不對。HD5 是四語都 400：第一次實跑成功的 en 有 318–400 字（關島剛好 400），
# 中文 127–192 字，en 被 400 擋掉的多半是 bad_format 的大宗；en 放寬到 800（HD6）
MAX_COMMENT_CHARS = {"zh-TW": 300, "zh-HK": 300, "zh-CN": 300, "en": 800}

# ---- 用字檢查（HD6，`parse.check_wording`）；之後要加詞只改這裡 ----

# 內部代號：四語都不能出現（大小寫不分、整字比對：前後不能是英文字母、數字或底線）；
# `EN_PLAIN_WORDS` 在 en 例外（HD17）
FORBIDDEN_TOKENS = (
    "p29Kt",
    "p49Kt",
    "p37Kt",
    "p10",
    "p15",
    "p25",
    "HRES",
    "GFS",
    "EC",
    "crosswindKt",
    "gustKt",
    "hresGustKt",
    "basis",
    "agreement",
    "slots",
    "latest.json",
    # HD8
    "ptype",
    "rain6hMm",
    "visibilityM",
    "ceilingFt",
    "causes",
    "p24hRain25",
    "p24hRain50",
    "APCP",
    "CSNOW",
    "CFRZR",
)
# 英文常用字（HD17）：en 不當代號擋（"strong wind causes…"、"on the basis of"、"models are in
# agreement"、"afternoon slots"）；中文三語照擋——中文短評裡出現這些英文字只會是抄欄位名
EN_PLAIN_WORDS = ("causes", "basis", "agreement", "slots")
# 可以在括號裡出現一次（「機場預報（TAF）」「airport forecast (TAF)」），沒括號或第二次以上算違規
ONCE_IN_PARENS = ("TAF", "METAR")
CHINESE_LANGS = ("zh-TW", "zh-HK", "zh-CN")
# 中文三語不能寫英文等級字：「（high）」「(high)」這類
EN_LEVEL_WORDS = ("high", "medium", "low")
# zh-HK 用書面語，不用粵語口語
CANTONESE = ("喺", "嘅", "咗", "嚟", "啱啱", "唔", "佢", "冇", "咁")
# zh-CN 不能有的繁體字；zh-TW、zh-HK 不能有的簡體字（抽查常見字）
TRADITIONAL_CHARS = ("颱", "風", "機", "場", "預", "報", "節", "側", "陣", "霧", "見")
SIMPLIFIED_CHARS = ("风", "机", "场", "预", "报", "节", "侧", "阵", "雾", "见")
# zh-CN 不能用的台灣用語（HD7）：机率 → 概率、资料 → 数据；zh-TW、zh-HK 照樣寫「機率」「資料」
ZH_CN_TAIWAN_TERMS = ("机率", "资料")
# 中文三語統一叫「停飛風險」：有一語寫「停飛／停飞」、另一處又寫「航班取消」就違規
SUSPEND_TERMS = ("停飛", "停飞")
CANCEL_TERMS = ("航班取消",)
# 英文統一 "disruption risk"
EN_RISK_FORBIDDEN = ("cancellation risk", "suspension risk")
# en 不能有中日文字（CJK 標點、假名、漢字、全形字）
CJK_RANGES = "\u3000-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uff00-\uffef"

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
