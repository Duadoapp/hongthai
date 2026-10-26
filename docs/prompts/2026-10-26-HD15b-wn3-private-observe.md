# HD15b：WeatherNext 3 隱形旁觀（私人 bucket）＋29W 補抓＋超過 121 小時搬進 `data` 分支

模型：Opus，強度高。**急**：29W 報告定稿排在 10/27 09:00（台灣），第 2 節（29W 補抓）要在那之前合併、跑完。
做完整支 PR 一起送；來不及的話第 2 節先單獨開一支 PR（第 1、3 節之後再送）。

先讀：`docs/worklog/2026-10-26.md`（今天的定案）、`docs/ORCHESTRATOR.md` 的 HD15 段、README「WeatherNext 3 的條款」、
`sources/wn3.py`、`wn3report.py`、`events.py` 的 `backfill-tracks`、`build.py` 裡 WN3 的部分、`config.py` 的 `WN3_MODE`、
`tools/report_29w.py` 的 `load_wn3`。

## 背景（2026-10-26）

- Google 10/26 核准存取（Shawn 的 Gmail 與 hongthai-actions 服務帳號，Earth Engine／BigQuery／GCS）。Shawn 正在建：
  BigQuery 連結資料集 `hongthai-512102.weathernext_3`（`weathernext_3_0_0_0p1deg`，程式預設就是這個）、私人 bucket
  **`<GOOGLE_CLOUD_PROJECT>-wn3-private`**（us-central1、公開存取封鎖；服務帳號 Storage Object Admin）、BigQuery 預算提醒
  US$5／月、每日查詢上限 100 GiB
- 條款（`terms-of-use.pdf`，2026-09-03 版，10/26 重讀沒變）：「relates to a time less than 1 hour ago and the future」是即時資料；
  1 小時以前的是 CC BY 4.0。**照比較嚴的讀法（看有效時間）做**：有效時間還沒過 1 小時的數值，一律不能出現在任何公開的地方。
  內部用途可以；公開「findings」（統計）可以，要標出處（Section 4(b)）
- **公開的地方包括**：`latest.json`、GitHub Pages、`data` 分支（公開 repo）、**Actions 的日誌與 artifact**（公開 repo 的日誌誰都看得到）、
  PR 說明與留言、測試 fixture 裡的真實數值

## 1. 隱形旁觀（新模式 `private`，設成預設）

- `config.WN3_MODES` 加 `private`，**預設改 `private`**（`report-only`、`observe` 留著）
- build 每報抓**最新的主報**（`latest_run`，00／06／12／18Z；不用每小時的臨時報），照現在 `observe` 的算法算每格（0–120 小時、
  6 小時一格，同 `wn3report` 事件檔的格式＋`levels`／`level`），**整份寫進私人 bucket** `gs://<專案>-wn3-private/observe/<起報>.json`
  （同一個起報寫過就跳過或覆寫，PR 說明寫你選哪個）；**不進 `latest.json` 的 `models[]`／`slots`、不投票**
- `latest.json` 的 `sources.wn3` 照現在只放中繼資料（`ok`、`mode`、`via`、`estimateBytes`、`bytesBilled`、秒數、起報時間），
  **不放任何預報值或等級**
- **日誌不能印 WN3 的數值或等級**（現有的 log 也檢查一遍）：只印起報時間、機場數、bytes、秒數、錯誤碼。寫一個測試用 `caplog`
  確認整個 `private` 流程的 log 裡沒有 fixture 的數值
- 失敗（403、沒憑證、bucket 寫不進去、超過 `BQ_MAX_BYTES`）只記 `sources.wn3` 的錯誤碼，整報照出
- 費用：照現在每個查詢 dry run → `maximum_bytes_billed` 8 GB；**第一報實跑的 `estimateBytes`、`bytesBilled` 寫進 PR 說明**
  （合併後主對話看第一報）

## 2. 29W 補抓（給 10/27 的定稿報告）

- `wn3report.backfill` 現在只補「起報 ≤ 現在 − 121 小時」的整報。改成：事件期間每個主報都補，但**公開寫進 `data` 分支的只留
  有效時間已經過了 1 小時的部分**——每格的 `to` ≤ 現在 − 1 小時才寫（路徑檔的點同理，`validAt` ≤ 現在 − 1 小時）；檔頭加
  `clippedAt`（截到哪個時間）、`license: "CC BY 4.0"`、`attribution` 照 `ATTRIBUTION_CC`
- 截過的檔，下次補的時候如果能多寫幾格（`clippedAt` 之後又有格過了 1 小時），重抓並補寫；整報 120 小時都過了的不再抓
- `events` workflow 的 `backfill-tracks` 輸入照用（主對話會代按，`event=29W`）；**原本 29W 的檔一個都不改**，只新增 `wn3/` 與
  `tracks/*-wn3.json`
- 報告工具 `load_wn3` 讀截過的檔要正常（缺的格當沒有預報，不算誤差）；`--until` 對 WN3 照起報時間篩（現在就是）
- 估算陣風的 G：照現在補報用 `history/gustfactor/latest.json`

## 3. 超過 121 小時搬進 `data` 分支

- 每天一次（放進 `events` workflow 每小時那支，00Z 那次跑就好）：私人 bucket 裡起報 ≤ 現在 − 121 小時、還沒搬過的
  `observe/<起報>.json`，複製到 `data` 分支 `history/wn3/<起報>.json`（格式同事件檔，標 `license`、`attribution`）；起報落在事件
  期間的，事件目錄 `wn3/` 也放一份（已經有就不覆寫）
- 私人 bucket 的檔留著（之後 Google 回信再決定要不要刪）

## 4. 不做

- 網頁顯示 WN3 等級（HD15c：R2＋依國家判斷，之後另開）
- 投票、`observe` 模式的行為不改
- 29W 報告工具除了讀截過的檔，不改

## 5. 測試

`private` 模式：寫私人 bucket（mock）、`latest.json` 完全沒有 WN3 的值、log 沒有數值；補抓截到「現在 − 1 小時」、截過的檔之後補寫、
整報過了不再抓；搬家只搬 121 小時以前、事件目錄不覆寫；`load_wn3` 讀截過的檔。fixture 用手造的數值，不要放真實的 WN3 即時數值

## 回報時要附

- 第一報實跑：`sources.wn3`（起報、via、`estimateBytes`、`bytesBilled`、秒數），**不要貼任何預報值**
- 29W 補抓預計要抓幾報、每報的掃描量
- 和提示詞不一樣的地方與理由

本機 `ruff check .`、`ruff format --check .`、`pytest -q` 全過才推，盡量一次推完。
開 PR 之後：`gh pr checks --watch` 等 CI，紅了自己修並推到同一個分支（最多三輪），全綠時告訴我；
不要自己合併，我會先請主對話審查。
