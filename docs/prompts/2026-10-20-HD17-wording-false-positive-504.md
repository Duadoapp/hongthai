# HD17：`bad_wording` 誤判英文常用字（causes／basis／agreement／slots）；Gemini 的 504 只重試一次

模型：Sonnet 或 Opus 皆可，強度低。改 `src/hongthai/ai/config.py`、`src/hongthai/ai/parse.py`、`src/hongthai/ai/run.py`
（或 `gemini.py`，看重試放哪裡順）、`tests/test_ai.py`、README、`docs/ORCHESTRATOR.md`。`latest.json` 欄位與錯誤代碼不變。

先讀 `src/hongthai/ai/config.py`（`FORBIDDEN_TOKENS`）、`src/hongthai/ai/parse.py`（`_word`、`check_wording`）、`src/hongthai/ai/run.py`
（`_one`、`TIMEOUT_S`、預算 `deadline`）、`src/hongthai/ai/gemini.py`、`tests/test_ai.py` 的 `bad_wording` 與 `http_*` 案例，
以及 `data` 分支 `history/ai/2026-10-19.json` 裡 `run` 是 `2026-10-19T18:07:00Z` 的那 20 筆（`detail`、`seconds`）。

## 起因（2026-10-19T18:07Z 那報，HD13 合併後第一報）

- **`bad_wording` 4 個，全部是 `en/causes`**（Claude RCYU、Gemini RCFN／RCTP／ROMY）：HD8 把 `causes` 加進 `FORBIDDEN_TOKENS`
  當內部代號擋，但 `_word` 是整字、不分大小寫，英文短評寫「strong wind causes…」就被擋——**這是檢查誤判，不是模型用字問題**。
  同一份清單裡 `basis`、`agreement`、`slots` 也是英文常用字（"on the basis of"、"models are in agreement"），一樣會誤判
- **Gemini `http_504` 4 個**（RCFG、RCKH、ROIG、ZSQZ），每個都卡 **57 秒**才回（Vertex 閘道逾時），和上一報的 2 個比變多；
  依字母順序 3 條並行，RCFG／RCKH 幾乎同時送、ROIG／ZSQZ 也是——偏向是負載相關。Gemini 20 筆共約 470 秒，3 條並行要
  157 秒；降回 2 條會到 235 秒、撞 240 秒預算，所以**不降並行**，改成 504 只重試一次

## 定案（Shawn 2026-10-20 02:41 確認）

1. **英文常用字不當代號擋**：`config.py` 加 `EN_PLAIN_WORDS = ("causes", "basis", "agreement", "slots")`；`check_wording` 檢查
   `en` 時跳過這四個（中文三語照擋——中文短評裡出現這些英文字只會是抄欄位名）。其他代號（`p49Kt`、`ptype`、`rain6hMm`…）
   四語都照擋。**不要放寬別的檢查**
2. **Gemini 的 `http_504`（和 `http_503`）只重試一次**：同一個請求、不改內容；只在**剩餘預算 ≥ 70 秒**時重試（一次請求逾時
   60 秒），不夠就照舊記 `http_504`；重試仍失敗記 `http_504`、`detail` 加 `:retried`；戰績的 `seconds` 記兩次合計。429、400、
   `bad_format`、`bad_wording`、`refusal` **都不重試**（維持「不重試」原則，504 是閘道沒回應、不是模型回了壞東西，也不計費）。
   Claude 那邊 5xx 很少見，同一套邏輯一起套（程式共用），README 寫清楚
3. Gemini 維持 3 條並行；README「AI 對決」補這兩條與 18:07Z 的數字

## 測試

- `check_wording`：en 寫 "Strong winds causes…"、"on the basis of"、"in agreement"、"afternoon slots" 都通過；zh-TW 出現 `causes`
  仍是 `bad_wording`；en 出現 `p49Kt`／`ptype` 仍是 `bad_wording`
- 假 SDK：第一次 504、第二次 ok → `status: ok`、`seconds` 是兩次合計；兩次都 504 → `error: http_504`、`detail` 含 `retried`；
  剩餘預算 < 70 秒時不重試；429 不重試；`calls` 計數：重試算一次呼叫（次數檔累加 2）

## 回報時要附

- 改後的 `EN_PLAIN_WORDS` 與重試那段程式
- 用 18:07Z 戰績的四則 `en/causes` 說明改後會通過（短評沒存，用 `detail` 說明即可）

本機 `ruff check .`、`ruff format --check .`、`pytest -q` 全過才推，盡量一次推完。
開 PR 之後：`gh pr checks --watch` 等 CI，紅了自己修並推到同一個分支（最多三輪），全綠時告訴我；
不要自己合併，我會先請主對話審查。
