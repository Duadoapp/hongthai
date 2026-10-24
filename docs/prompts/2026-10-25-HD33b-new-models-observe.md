# HD33b：UKMO、GEM、ARPEGE、CMA 進 `models[]` 當旁觀（不投票）

模型：Sonnet，強度中。**動到資料流程：現在可以開 PR、跑 CI，等 10/25 16:25（台灣，08:25Z）那報寫進 history、主對話確認後才合併**
（29W 凍結到那報跑完為止）。B 組合併順序：HD33b → HD35 → HD38 → HD34 → HD39；main 有新的合併就自己 rebase、重跑檢查。

先讀 Duado spec 第 16 節「颱風期間功能擴充計畫」的「新模式」（定案：經 Open-Meteo **旁觀、不投票**，用 29W 回補比過準確度後再決定投票或加權；
**不照解析度加權**）、`src/hongthai/sources/openmeteo.py`、`config.py` 的 `MODELS`、`assess.py` 的旁觀（`voting=False`、`non_voting()`，HD16 的 WN3
寫法）、README「多模式投票」與 `latest.json` 的 `models[]`、HD24（`vote.mediumTotal`、`votesOnlyHigh`）。

## 1. 做什麼

- `openmeteo.py` 的預報請求多帶四個模式（Open-Meteo 代號以文件為準：預計 `ukmo_global_deterministic_10km`、`gem_global`、
  `meteofrance_arpege_world`、`cma_grapes_global`），逐時 10 米風、風向、陣風、雨量；能一個請求帶完就一個（不要讓請求數變多），
  注意每分鐘上限與回應大小
- `config.MODELS` 加四筆，**`voting=False`**：`models[]` 照常寫（`levels`、`level`、陣風、側風、雨量都算），**分母、票數、`level`、
  `vote.*`、`causes` 一律不變**；沒有陣風的模式標 `gustEstimated`（同 JMA GSM）
- id 與四語名稱：`ukmo`「英國模式」、`gem`「加拿大模式」、`arpege`「法國模式」、`cma`「中國模式」（en：UK Met Office、Canada GEM、
  Météo-France ARPEGE、CMA GRAPES；zh-CN、zh-HK 照現有模式名稱的寫法）——名稱放資料端的地方照現有模式
- **AI 不給旁觀模式**：給 Claude／Gemini 的文字維持現在的 8 個模式（改 AI 提示要另外決定），測試要鎖住
- 失敗：四個一起失敗或個別沒資料都不影響整報；不沿用舊資料（同 ICON／JMA）
- 預算：記耗時與大小，`budget.py` 的總預算若會超過就在 PR 說明提出，不要自己改預算

## 2. `latest.json`

- 只加不改名：`models[]` 多四筆（`voting: false`）、`sources` 多 Open-Meteo 的新模式出處；`schema` 照 README 的規則（只加欄位不升）
- 網頁（Duado `site/hongthai/`）已會顯示「旁觀，不投票」；新 id 的中文名稱若網頁是寫死對照表，在 PR 說明列出要請主對話開 HW 的地方，**這支不改 Duado**

## 3. 測試

旁觀不改票數與等級（拿現有 fixture 加四個模式，`level`、`vote` 完全一樣）、AI 文字不含四個模式、請求數、失敗不壞整報、`models[]` 的新欄位

## 回報時要附

- 四個模式實際代號、陣風有沒有、一次請求的大小與耗時、整報耗時變化
- 用最近一報的資料跑一次：各機場 5 天內四個模式各自的最高等級，和 8 個投票模式並列（文字表即可）
- 網頁要配合改的地方（如果有）

本機 `ruff check .`、`ruff format --check .`、`pytest -q` 全過才推，盡量一次推完。
開 PR 之後：`gh pr checks --watch` 等 CI，紅了自己修並推到同一個分支（最多三輪），全綠時告訴我；
不要自己合併，我會先請主對話審查。
