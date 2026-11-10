# HD50：AI 評論改成平常一天 1 報、「有颱風而且有高」時一天 2 報

模型：Opus，強度高。動到每報的 AI 流程與 `latest.json`（**只加欄位**）。只改 `src/hongthai/ai/`、`build.py` 裡 `run_ai` 與呼叫它的地方、`.github/workflows/build.yml`
（只加一個手動輸入）、對應測試、README 的 AI 段。同時在跑的 HD48（`assess.public_slots`、`build.hide_wn3`、公開等級開關）、HD49（`sources/wn3.py`、`wn3report.py`）
的地方不要碰；`build.py` 只動 AI 那一段。

先讀：`docs/worklog/2026-11-11.md`（Shawn 00:51 定案）、`src/hongthai/ai/run.py`（`Duel`、選機場、`skipped`／`run_cap`／`daily_cap`、`evaluatedAt`、戰績 `history/ai/`）、
`ai/config.py`、`build.py` 的 `run_ai`（`prev` 是上一份 `latest.json`）、`build.yml` 的四個排程與 `TRIGGER`、`typhoons.py`（`typhoons.json` 的 `storms`、`ended`）、
Duado `docs/spec.md` 第 16 節 AI 的部分（網頁怎麼顯示 `evaluatedAt`、`status`）。

## 定案（Shawn 2026-11-11 00:51）

- **平常**：Claude、Gemini 都只在**台灣早上那一報**評（09:05 那報，排程 `5 1 * * *` UTC）
- **「有颱風，而且總評風險出現『高』」**：一天 2 報——早上那報＋晚上 21:05 那報（`5 13 * * *` UTC）。只有颱風但沒有高：維持 1 報
- 每月費用估計（HD47 之後每次 Claude 約 US$0.098、Gemini 約 US$0.040，12/1 起約 US$0.081；平常每報約 9 個機場）：平常約 US$38／月（12/1 起約 US$49）；
  颱風而且有高的日子每天約 US$7（2 報 × 最多 20 個機場 × 兩家）

## 規則（主對話照建議定的細節，可以反悔；做法不同要在 PR 說明寫理由）

1. **哪一報要評**（純函式，容易測）：輸入這一報的時間、觸發方式、`latest`（這報剛算好的）、`typhoons`：
   - 早上那報（UTC 01:05 那個時段；用「時段」判斷，不要寫死分鐘——排程會晚、Worker 與 GitHub 都會觸發，照 `build.py`「這個時段已出過就跳過」同一套時段的算法）：評
   - 晚上那報（UTC 13:05 那個時段）：**有颱風**＝這報的 `typhoons.json` 裡有還沒結束的颱風（`storms[]` 有 `ended` 是空的）；**有高**＝這報任何一個機場的規則燈
     綜合等級（5 天內最高，AI 選機場用的同一個等級）是 `high`。兩個都成立才評
   - 其他兩報（04:25、16:25）：不評
   - 手動 build：`build.yml` 的 `workflow_dispatch` 加輸入 `ai`（`auto`／`on`／`off`，預設 `auto`）；`auto` 照上面的時段規則（手動按在非評論時段就不評），
     `on` 一律評、`off` 一律不評。Worker 觸發不帶這個輸入＝`auto`
2. **不評的那幾報 AI 欄位怎麼出**：沿用上一份 `latest.json` 每個機場的 `ai`（兩顆燈的 `status`、`level`、`comment`、`sentences`、`model` 與 **原本的 `evaluatedAt`**，
   網頁本來就顯示「評估於〈時間〉」），但：
   - 上一份的 `evaluatedAt` 超過 26 小時、或沒有上一份、或那個機場上一份沒有 `ai`：兩顆燈 `status: "error"`、`error: "off_schedule"`、`evaluatedAt: null`
   - 上一份那顆燈是 `skipped`（「沒看到明顯風險」）或等級比這報的規則燈低一級以上，而這報規則燈已經是 `medium` 以上：那顆燈改 `status: "error"`、
     `error: "stale"`（不能讓「沒看到明顯風險」掛在已經亮中、高的機場上）
   - 上一份是 `error` 的照樣沿用它的 `error`
   - 頂層 `ai`（`disclaimer`、`models`）照舊；新增 `ai.schedule`：`{"evaluated": true|false, "reason": "morning"|"typhoon_high"|"off_schedule"|"forced"|"disabled", "nextSlot": "<下一個會評的時段的 ISO 時間，照平常規則>"}`
   - `sources.ai`：不評時 `ok: true`、`calls` 都是 0、多 `skipped: "off_schedule"`；不寫戰績、不算每日次數
3. 評的那幾報：流程完全照現在（選機場、每報 20 個、`DAILY_CAP`、WN3 防洩漏、戰績）
4. 新的錯誤代碼 `off_schedule`、`stale` 寫進 README；網頁對不認得的代碼一律顯示「資料不足」（已經是這樣），所以**網頁不用改**
5. 一致性／`gap`／og 圖若有用到 AI 燈：沿用的燈照樣可以用（og 圖上 AI 燈畫的是 `level`）；`error` 的畫灰（現有行為）
6. 做成設定：`ai/config.py` 加 `SCHEDULE`（例如 `{"always": [1], "typhoonHigh": [13]}`，UTC 小時代表的時段），改回一天四報只要改這裡

## 測試

- 時段判斷：四個時段 × 有沒有颱風 × 有沒有高 × `ai` 輸入三種；排程晚到、Worker 與 schedule 重複觸發
- 沿用：正常沿用（`evaluatedAt` 不變）、超過 26 小時、沒有上一份、`skipped` 遇到規則燈升到中／高變 `stale`、上一份 `error` 照沿用
- 不評時不呼叫任何 AI client、不寫戰績與次數檔；`sources.ai` 的樣子
- 評的那報和現在的輸出一樣（除了多 `ai.schedule`）
- HD43 的 WN3 防洩漏測試照過

## 回報時要附

- 不評的一報 `airports[].ai` 與頂層 `ai.schedule`、`sources.ai` 的範例（假資料）
- 你怎麼判斷「時段」與「有高」（用了哪個現有函式）
- 和提示詞不一樣的地方

本機 `ruff check .`、`ruff format --check .`、`pytest -q` 全過才推，盡量一次推完。
開 PR 之後：`gh pr checks --watch` 等 CI，紅了自己修並推到同一個分支（最多三輪），全綠時告訴我；
不要自己合併，我會先請主對話審查。
