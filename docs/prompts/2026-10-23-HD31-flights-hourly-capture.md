# HD31（急件，只存資料）：每小時存逐班精簡航班紀錄——29W 對答案用

模型：Sonnet，強度中。**今天（10/23）上線**：薔琵這兩天經過，航班是 29W 報告的真相資料。**只多存資料**：不改 `latest.json`、等級、投票、
`build.py` 的輸出、網頁；和 HD20 的 METAR 保存同一類，凍結期間可以合併。改 `src/hongthai/events.py`（`hourly` 多一件事、新子命令
`backfill-flights`）、`src/hongthai/flights_log.py`（新，純函式）、`.github/workflows/events.yml`（`backfill-flights` 勾選項）、測試、README「事件保存」、
`docs/ORCHESTRATOR.md`。

先讀 `src/hongthai/events.py` 檔頭（`hourly` 每小時三件事、`metar/` 的去重與格式）、`src/hongthai/sources/flights.py`（五個來源 `fetch_hkg`／`fetch_tpe`／
`fetch_tsa`／`fetch_khh`／`fetch_mfm` 與各自的欄位、HKG 的 `past?date=`）、`src/hongthai/cancellations.py`（狀態對照表、共掛班號怎麼去重、沒有日期的時間怎麼
放、高雄換日的判斷、分類 `cancelled`／`delayed`／`other`——**全部沿用，不要另寫一套**）、`.github/workflows/events.yml`。

## 1. 每小時存（`hourly` 第四件事，獨立 try，失敗只記 log）

- 事件期間內（同 METAR，`events.json` 的 `from`～`to`）每小時抓五個來源（桃園、松山、高雄、香港、澳門），**逐班**寫進
  `history/events/<id>/flights/<YYYY-MM-DD>.jsonl`（日期是**表定時間的 UTC 日期**）
- 一班一行：`{"t": 抓的時間, "airport": ICAO, "dir": "dep"|"arr", "flight": 營運班號, "codeshares": [掛名班號…], "peer": 對方機場（IATA 或原文）,
  "schedUtc", "estUtc", "actUtc"（沒有是 null）, "status": 原始狀態文字, "class": "cancelled"|"delayed"|"other"|"normal", "source"}`
  ——`class` 用 `cancellations.py` 同一套規則（延誤含「預計／實際比表定晚 60 分鐘以上」）；共掛照 `cancellations.py` 合成一班
- **只在有變化時寫新的一行**：同一個 `airport`＋`dir`＋`flight`＋`schedUtc`，`status`、`class`、`estUtc`、`actUtc` 任一個和最後一行不同才寫；第一次看到也寫。
  這樣一天約 2,500 班、幾千行，不會爆
- 原始回應**不存**（太大）；解析失敗的筆數記 log

## 2. 補過去的（香港）

`python -m hongthai.events backfill-flights --archive data --from 2026-10-19`：香港的 `past?date=` 可以查過去的日子，從 `--from` 到今天每天查一次（`arrival`
true／false 各一），照上面的格式寫（`t` 寫實際抓的時間、多 `"backfill": true`），已有同一班同狀態的不重寫。其他四個來源只有當天，補不到，只記 log。
`events.yml` 的 `workflow_dispatch` 加 `backfill-flights` 勾選項；合併後 Shawn 手動跑一次。

## 3. 測試與文件

- `tests/test_flights_log.py`：五個來源各用一份手造（或現有 fixture）資料：逐班轉換、共掛合併、分類和 `cancellations.py` 一致、只在變化時寫、跨日的 UTC 日期歸檔、
  高雄換日
- `tests/test_events.py`：`hourly` 第四件事失敗不影響前三件；事件期間外不寫
- README「事件保存」補 `flights/`；ORCHESTRATOR 29W 那條補「HD31 每小時逐班航班紀錄（10/23 起）」

## 回報時要附

- **第一筆紀錄的時間**（合併後第一個整點 xx:07 那次）與各機場第一小時寫了幾行
- 香港 backfill 補到幾天、幾班
- 一天大概多少行、多少 KB（用第一天推）

本機 `ruff check .`、`ruff format --check .`、`pytest -q` 全過才推，盡量一次推完。
開 PR 之後：`gh pr checks --watch` 等 CI，紅了自己修並推到同一個分支（最多三輪），全綠時告訴我；
不要自己合併，我會先請主對話審查。
