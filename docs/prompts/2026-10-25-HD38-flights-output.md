# HD38：航班取消、延誤數進輸出（平常每報抓 TDX）

模型：Sonnet，強度中。**動到資料流程與 `latest.json`：現在可以開 PR、跑 CI，等 10/25 16:25（台灣，08:25Z）那報寫進 history、
主對話確認後才合併**。B 組合併順序：HD33b → HD35 → **HD38** → HD34 → HD39；main 有新的合併就自己 rebase、重跑檢查（HD35 合併後，
它的每機場檔也要帶航班）。

先讀 Duado spec 第 16 節「颱風期間功能擴充計畫」的「航班」與 `docs/worklog/2026-10-25.md` 的定案、`cancellations.py`（6 小時統計，
已經每報算、存 `history/cancellations/`）、`sources/flights.py`、`sources/tdx.py`、`flights_log.py`、`events.py`（事件期間每小時那件）、
README 的 TDX 用量與授權、`latest.json` 的 `slots[]`。

## 定案（Shawn 2026-10-23、2026-10-25 00:35）

- 每 6 小時格的取消／延誤數上網頁（紅 X）；網頁是 HW14，這支只做資料
- **平常（沒有颱風事件）每一報抓一次 TDX**（一天 4 次，約 1.4 點／月）；**颱風事件期間照現在每小時存**（`events.py` 不動）
- 表定少於 4 班的格標「班次少」（`FEW_FLIGHTS = 4`，和 HD37 報告工具同一個常數）

## 1. 做什麼

- `build.py` 每報算航班統計的地方加 TDX：台灣十個機場一次請求（同 HD32）；**桃園、松山、高雄、香港、澳門照舊用原本的來源**，TDX 只補其他
  7 個台灣機場（統計時不重複）；TDX 失敗或沒設 secret 就那 7 個沒有，不影響整報
- TDX 的列照 `cancellations.py` 的台灣規則分類，HD37 在報告工具裡補的那幾種（`加班` 正常、`轉降` 另一類、`預計HH:MM到站／離站` 用時間比）
  這支**在 `cancellations.py` 正式補上**，`flights_log.py` 跟著用（分類是新存的資料才套，舊檔不改寫）；`轉降` 在 6 小時統計多一個 `diverted`
- `latest.json`（只加不改名）：`slots[].flights`＝`{"total", "cancelled", "delayed", "diverted", "few": bool, "source", "asOf"}`（出發＋抵達合計，
  另附 `dep`／`arr` 兩組同欄位）；沒有航班資料的機場不寫這個鍵；`airports[].flightSources`（例如 `["tpe"]`、`["tdx"]`）；`sources` 加 TDX 出處
- HD35 的每機場檔：3 小時格也帶 `flights`（同欄位，依表定歸 3 小時格）
- 已經過去、但還在 `slots` 裡的那格照算（現在那格常常已有取消）

## 2. TDX 用量

README 的用量段落改寫：平常每報一次（約 124 次／月 × 約 1.7 MB）＋事件期間每小時；寫明每月 3 點的估算與超過時的處理（TDX 超過 105% 停權，
所以程式裡設每月呼叫數上限常數，超過就跳過 TDX 並 log，預設 600 次）

## 3. 測試

7 個機場用 TDX、5 個用原來源不重複、`few` 的邊界（3／4 班）、新分類（加班、轉降、預計時間）、`latest.json` 新欄位、TDX 失敗與月上限、沒有航班
資料的機場不寫鍵、3 小時檔的 `flights`

## 回報時要附

- 最近一報實跑：每個機場的來源、5 天內有取消的格、`latest.json` 增加的大小
- 和提示詞不一樣的地方與理由

本機 `ruff check .`、`ruff format --check .`、`pytest -q` 全過才推，盡量一次推完。
開 PR 之後：`gh pr checks --watch` 等 CI，紅了自己修並推到同一個分支（最多三輪），全綠時告訴我；
不要自己合併，我會先請主對話審查。
