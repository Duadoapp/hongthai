# HD40：AI 評論只陳述資料來源、不延伸推論＋逐句出處

模型：Opus，強度高。動到 AI 提示詞與 `latest.json` 的 `ai`（**只加欄位、不改名**）。網頁顯示出處是 Duado HW20（等這支合併後開）。

先讀：`docs/worklog/2026-10-27.md`（氣象署回覆全文與 Shawn 16:52 定案第 3 點）、`docs/ORCHESTRATOR.md`「《氣象法》」、`src/hongthai/ai/prompt.py`
（`SYSTEM` 規則與用字）、`ai/parse.py`（回覆格式檢查、`check_wording`）、`ai/run.py`、README「AI 對決」與 `latest.json` 的 `ai` 欄位。

## 背景

氣象署 2026-10-27 回覆第 1 點：忠實引用國外氣象機構的預測屬「播報」；**AI 評論若逾越其資料來源而做出延伸詮釋**，又公開發布，可能涉及
預報。Shawn 定案：AI 提示詞加一條「**只陳述資料來源說的內容，不自行延伸推論**」；**逐句註明出處**（10/21 待決定 (h)：提示詞改成每句附
來源代號，網頁轉上標）一起做。

## 1. 提示詞

- 規則加一條（放在現在第 1 條旁邊，措辭你定，意思要到）：每一句都要能在給你的資料裡找到根據；**只陳述資料說了什麼**（哪個來源、哪一格、
  什麼數字、幾個模式怎麼投）；**不自行延伸推論**——不能預測資料沒寫的天氣變化（例如「風會再增強」「颱風可能轉向」）、不能把一個來源的
  說法延伸到它沒涵蓋的時段或地點。等級（low／medium／high）照舊要給，但短評裡說明等級時只能引用資料
- 每一句附**來源代號**：代號清單寫在提示詞裡、和精簡文字（`airport_text`）每一段的標籤一一對應，例如官方的 `taf`、`metar`、`warning`、
  `confirmed`（已確認停飛）、每個模式的 id（`ifs`、`gfs`、`ifs-ens`、`aifs`、`aigfs`、`icon`、`jma`、`wn2-ens`）、`vote`（投票結果）、
  `rule`（規則燈的門檻與等級）。實際清單以 `airport_text` 給的段落為準，PR 說明列出最後的清單與每個代號在網頁該顯示的名稱（四語）
- 回覆格式（只加不改）：

      {"level": "...", "comment": {四語}, "sentences": {"zh-TW": [{"text": "…", "src": ["taf", "ifs"]}, …], "zh-HK": […], "zh-CN": […], "en": […]}}

  四語的句數一樣、同一個位置的 `src` 一樣；`comment` 照舊（＝那一語的句子接起來，程式組，不讓模型另寫一份）

## 2. 檢查（`parse.py`）

- 每一句的 `src` 至少一個、全部在清單裡；四語句數與 `src` 對得上；`text` 照現在 `check_wording` 的用字檢查
- 不合格的處理照現在 `bad_format` 的流程（重試／這盞燈 `error`），**不要**為了過檢查而自己補代號
- `comment` 由 `sentences` 組；模型沒給 `sentences`（舊格式）→ `bad_format`

## 3. 輸出

- `latest.json` 的 `ai.<燈>` 多 `sentences`（同上格式），`comment` 照舊；README 的欄位說明與範例更新
- 歷史快照照存；分享預覽圖（og）不改
- 預算：輸出變長，記一報的 token 與費用變化（`usage.py`），PR 說明寫

## 測試

- 提示詞裡有新規則與代號清單、和 `airport_text` 的段落對得上（加一個測試擋：`airport_text` 多了新段落卻沒有代號）
- 合格的回覆 → `sentences`、`comment` 組對；缺 `src`、未知代號、四語句數不同、`src` 不一致、舊格式 → `bad_format`
- `latest.json` 的 `ai` 只多 `sentences`、其他欄位不變（拿現有 fixture 比）

## 回報時要附

- 新規則的原文、代號清單與四語名稱
- 用最近一報實跑一個機場（Claude、Gemini 各一）的 `sentences`（評論本來就公開，可以貼）
- token 與費用的變化
- 和提示詞不一樣的地方

本機 `ruff check .`、`ruff format --check .`、`pytest -q` 全過才推，盡量一次推完。
開 PR 之後：`gh pr checks --watch` 等 CI，紅了自己修並推到同一個分支（最多三輪），全綠時告訴我；
不要自己合併，我會先請主對話審查。
