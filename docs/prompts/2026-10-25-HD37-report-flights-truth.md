# HD37（只改報告工具）：停飛實測加讀逐班航班（台灣其他 7 個機場）＋狀態重新分類

模型：Sonnet，強度中。**只改 `tools/report_29w.py`、`tests/test_report_29w.py`、README 的報告工具段落、`docs/ORCHESTRATOR.md`**：不碰管線
（`src/`，包括 `flights_log.py`、`cancellations.py`）、等級、`latest.json`、`events.json`；**可以現在合併**。**10/26 早上前要合併**（初版報告）。

先讀 `tools/report_29w.py`（HD22 docstring、HD36 的兩個截止）、`src/hongthai/flights_log.py` 與 `cancellations.py`（逐班格式與台灣分類規則，只讀）、
README「事件保存」的 `flights/`（HD31、HD32）、`docs/worklog/2026-10-24.md`。

## 背景

報告 (b) 的停飛實測現在只讀 `history/cancellations/`（每 6 小時的取消統計），只有桃園、松山、高雄、香港、澳門。HD31／HD32 起
`history/events/29W/flights/<表定 UTC 日期>.jsonl` 有逐班紀錄（`source` 是原本的來源或 `tdx`），TDX 台灣十個機場第一次抓（10/24 02:31Z）
就回傳了 10/22 起的航班，所以台中、台南、花蓮、台東、澎湖、金門、綠島也有實測可對。

## 1. 做什麼

- 停飛實測的來源依機場選：**`cancellations/` 有的機場照舊用它**（和定版以來一致）；沒有的機場用 `flights/` 的逐班紀錄（`source: tdx`）
- 逐班 → 每 6 小時格：同一班（`airport`、`dir`、`flight`、`schedUtc`、`source`）取**最新一行**；表定時間落在格內的算進這格；
  格的「停飛」規則和 `cancellations/` **完全一樣**（出發＋抵達取消率 ≥ `--cancel-rate` 或取消 ≥ `--cancel-count` 班）；那格沒有航班不算
- 實測的最後時間：每個機場自己的最新 `t`（取代全域的 `asOf`），再和 `--truth-until` 取早的（HD36 的規則照套，只是變成每個機場各一個）
- **狀態重新分類**（只在報告工具裡，不改存檔）：`class: other` 的列依原始 `status`：`加班` → 正常；`轉降` → 新類「轉降」（不算取消，
  另外計數印出）；`預計HH:MM到站／離站`（含沒寫日期的）→ 用預計時間和表定比，晚 60 分鐘以上算延誤，否則正常（日期推法照
  `cancellations.py` 沒日期時間的規則）；其他看不懂的照舊 `other` 並列出前 10 種與次數
- 報告「停飛實測」那段加一張表：每個機場用哪個來源、最新時間、格數、取消／延誤／轉降班數；(b) 的範圍（`scope`）變大，在摘要寫明

## 2. 不變的

- 不給 `flights/` 時輸出和現在一樣；`cancellations/` 的五個機場數字和現在一樣（測試鎖住）
- JSON 只加不改名

## 3. 測試

最新一行、跨格、轉降、加班、預計時間（有日期／沒日期）、每機場最後時間＋`--truth-until`、兩種來源並存時選 `cancellations/`、不給 `flights/` 輸出不變

## 回報時要附

- 用 `data` 分支現在的資料試跑：每個機場的來源與格數、各類次數、(b) 每格與每報每機場的筆數變化（加之前／之後）
- 和提示詞不一樣的地方與理由

本機 `ruff check .`、`ruff format --check .`、`pytest -q` 全過才推，盡量一次推完。
開 PR 之後：`gh pr checks --watch` 等 CI，紅了自己修並推到同一個分支（最多三輪），全綠時告訴我；
不要自己合併，我會先請主對話審查。
