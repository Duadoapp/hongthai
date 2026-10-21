# HD26：AI 提示快取（Claude prompt caching、Gemini 隱含快取）與每次呼叫的 token 紀錄

模型：Opus，強度中。**凍結前（2026-10-22 12:00 台灣時間）合併**。只改**送法**與**紀錄**：提示的文字、順序、模型、`effort`／
`thinking_level`、溫度、`max_tokens` **一個字都不改**，AI 的答案不應該因為這支而變。`latest.json` **不加欄位**。
改 `src/hongthai/ai/claude.py`、`gemini.py`、`run.py`（戰績與 timing 記 token）、`config.py`（單價常數）、新 `tools/ai_cost.py`、測試、
README、`docs/ORCHESTRATOR.md`。

先讀 `docs/ORCHESTRATOR.md`「29W 驗證期凍結」與 AI 那幾條（HD11／HD12／HD17／HD23）、`src/hongthai/ai/claude.py`、`gemini.py`、
`prompt.py`（`SYSTEM`、`airport_text`、`rules_text`）、`run.py`（四條／三條線、戰績 `history/ai/<日期>.json` 與
`history/ai/calls-<日期>.json` 的格式、`timing` 的 `ai` 那行）。

## 為什麼（Shawn 2026-10-21 11:25，產品負責人看了帳單）

Claude 10/19 US$8.72、10/20 US$11.83（全是 Opus 5.5）；GCP 10/18–10/20 約 US$12.9（含 Duado 的 Gemini）。每天 4 報、每報約 20 個機場，
推算 Claude 約 US$150／月、Gemini 同一個量級。HongThai workspace 月上限已從 30 調到 100 美元撐過颱風。現在**不知道每次呼叫用了
多少 token**，先開快取、記數字，颱風報告出來再談怎麼省（日誌「待決定」）。

## 1. Claude：prompt caching

- `system` 改成一個 text block 陣列 `[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}]`（內容就是現在的
  `SYSTEM`，一個字不改）；`messages` 照舊
- **先查文件**：Opus 5.5 的最小可快取長度（舊的 Opus 是 1,024 或 4,096 token，以現在的文件為準）。用 `client.messages.count_tokens`
  量 `SYSTEM` 有多少 token，**回報**；低於最小長度時快取不會生效（API 不報錯，`cache_read_input_tokens` 一直是 0）——照樣送
  `cache_control`（之後提示變長就會生效），回報裡寫清楚
- 同一報四條線同時起跑會各寫一次快取：**每報第一個機場先單獨評完、再開四條線**（只改排程順序，不改每個機場送的內容；
  `run.py` 的預算守門照舊）；第一個機場失敗也照樣開線
- 快取 TTL 用預設 5 分鐘（一報 AI 約 1.5–2 分鐘，夠）

## 2. Gemini：隱含快取（implicit caching）

- **先查 Vertex 文件**：Gemini 4 Argon 在 Vertex（`global` 與 `us`）是否支援**隱含快取**（自動、不用改程式、同樣前綴命中時
  `usage_metadata.cached_content_token_count` > 0）、最小長度。`system_instruction` 是前綴，現在已經每次一樣，所以**大概不用改任何
  送法**——這支對 Gemini 主要是**記數字**看有沒有命中
- **不做顯式 context caching**（`CachedContent` 要多一次 API 呼叫、按小時收儲存費，Argon 504 時還多一個會失敗的步驟）；
  若隱含快取不支援，回報裡寫清楚、這支不做
- 和 Claude 一樣「第一個機場先單獨評完再開三條線」（隱含快取也要第一次寫進去）

## 3. 紀錄 token

- 每次呼叫（含失敗但有回應的）在戰績 `history/ai/<日期>.json` 那筆多 `usage`：
  - Claude：`{"input": input_tokens, "output": output_tokens, "cacheRead": cache_read_input_tokens, "cacheWrite": cache_creation_input_tokens}`
  - Gemini：`{"input": prompt_token_count, "output": candidates_token_count, "thinking": thoughts_token_count, "cacheRead": cached_content_token_count}`
  - 沒有回應（逾時、504）是 `null`；欄位缺的寫 `null`、不要寫 0
- `timing/` 的 `ai` 那行多兩家各自的合計 `usage`（同上的鍵，加 `calls`）與**估計費用** `costUsd`（見第 4 點）；`latest.json` **不加**
- `history/ai/calls-<日期>.json` 不動

## 4. 估計費用

- `ai/config.py` 放單價常數（美元／百萬 token）：Claude Opus 5.5 的 input、output、cache write（5 分鐘）、cache read；Gemini 4 Argon
  在 Vertex 的 input、output（思考算 output，**以文件為準**）、cached input；**每個數字旁邊註明來源網址與查詢日期**。單價查不到的
  寫 `None`，費用那項就是 `null`、不要猜
- `tools/ai_cost.py`：`python -m tools.ai_cost --archive data --from 2026-10-21` 讀 `history/ai/` 的 `usage`，印每天、每報、每家：
  呼叫數、平均 input／output／思考 token、快取命中率（`cacheRead ÷ input`；Claude 的 `input_tokens` 不含快取讀取的部分，命中率用
  `cacheRead ÷ (input + cacheRead + cacheWrite)`，兩家公式寫清楚）、估計費用；`--json` 輸出給之後畫圖

## 5. 測試與文件

- 測試：Claude 送出的 `system` 是含 `cache_control` 的 block、文字和 `SYSTEM` 完全相同；`usage` 從假回應正確取出（含缺欄位 → null）；
  Gemini `usage_metadata` 的四個數；第一個機場先單獨跑再開線（用假 client 記呼叫時間順序）；`ai_cost` 的命中率與費用（用假單價）
- README「AI 對決」補快取與 `usage`、`tools/ai_cost.py`；ORCHESTRATOR 凍結那段補「HD26 只改送法與紀錄，不改提示與參數」

## 回報時要附

- 兩家的最小可快取長度（文件原文）、`SYSTEM` 的 token 數；Argon 在 Vertex 支不支援隱含快取
- 單價表與來源網址
- **合併後第一報**（主對話會請 Shawn 手動跑一次，或等下一個排程）跑 `tools/ai_cost.py` 的結果：兩家各自每次呼叫平均 token、
  快取命中率、估計每次費用。PR 裡先附用假資料跑的範例輸出

本機 `ruff check .`、`ruff format --check .`、`pytest -q` 全過才推，盡量一次推完。
開 PR 之後：`gh pr checks --watch` 等 CI，紅了自己修並推到同一個分支（最多三輪），全綠時告訴我；
不要自己合併，我會先請主對話審查。
