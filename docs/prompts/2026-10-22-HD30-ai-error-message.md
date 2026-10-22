# HD30（修 bug）：AI 呼叫失敗時記下錯誤訊息的前 200 字

模型：Sonnet，強度低。**凍結期間的 bug 修正**：只改 `src/hongthai/ai/parse.py`、`claude.py`、`gemini.py`、`run.py`（紀錄）、測試、README。
**提示詞、模型、參數、等級、`latest.json` 都不動**（`sources.ai.errors` 維持只有代碼）。

先讀 `src/hongthai/ai/parse.py` 的 `AiError`／`trace()`、`claude.py` 與 `gemini.py` 把例外轉成 `AiError` 的地方、`run.py` 戰績
`history/ai/<日期>.json` 的 `detail` 與 `timing/` 的 `ai` 那行。

## 為什麼（2026-10-22 09:25）

01:05Z 那報 Claude 20 個全部 `http_400`，紀錄只有 `http_400:-:-`，看不出原因；Shawn 到 Console 才知道是**餘額不足**。下次要從紀錄直接看得出來。

## 做法

- `AiError` 多一個 `message`（字串或 `None`）：HTTP 錯誤時取 API 回的錯誤訊息
  - Claude：`anthropic.APIStatusError` 的 `body`（`{"error": {"type", "message"}}`）→ `"<type>: <message>"`；取不到用 `str(e)`
  - Gemini：`google.genai.errors.APIError` 的 `message`／`status`
  - 逾時、網路錯誤：例外類別名稱＋`str(e)`
- **清理**：只留前 200 字、換行改空白；把看起來像金鑰或權杖的片段遮掉（`sk-ant-` 開頭、`AIza` 開頭、`Bearer ` 後面、長度 ≥ 32 的英數字串）換成 `***`；
  不記請求內容與回應內文
- 戰績 `history/ai/<日期>.json` 那筆多 `message`（只在有錯誤時）；`timing/` 的 `ai` 那行多 `errorMessages`：每個模型這一報**第一則**錯誤的 `message`
  （同一報 20 個都一樣時只記一次）
- log 照樣印一行（含清理後的訊息）

## 測試

Claude 400（餘額不足的樣子：`{"type": "error", "error": {"type": "invalid_request_error", "message": "Your credit balance is too low ..."}}`）、
Gemini 504、逾時三種：`message` 內容對、長度 ≤ 200、金鑰樣式被遮掉；戰績與 `timing/` 有新欄位；`latest.json` 的 `sources.ai` 不變

本機 `ruff check .`、`ruff format --check .`、`pytest -q` 全過才推，盡量一次推完。
開 PR 之後：`gh pr checks --watch` 等 CI，紅了自己修並推到同一個分支（最多三輪），全綠時告訴我；
不要自己合併，我會先請主對話審查。
