# H5：航班快照 → 每 6 小時格的停飛統計（不再存原始航班資料）

模型：Opus，強度高。這是純 Python 的資料處理，不碰 `latest.json` 的格式，也不碰等級規則。

先讀 `docs/ORCHESTRATOR.md`、`README.md`、`src/hongthai/sources/flights.py` 的 docstring、`src/hongthai/build.py`
的 `run()`／`publish()`，再動手。

## 背景

現在每次 build 把五個機場的航班狀態快照整份 gzip 存進 `data` 分支（`history/flights/<日期>/<機場>-<HHMM>.json.gz`，
一次五個機場約 110 KB，一年約 160 MB，而且 gzip 檔在 git 裡沒辦法差異壓縮）。這些快照唯一的用途是之後回測
「風險等級 vs 實際停飛」，但回測只需要每機場每 6 小時格的統計數字。

這個 PR 要：**每次 build 從快照算出統計、只存統計，不再存原始航班資料。**

## 要做的事

### 1. 新模組 `src/hongthai/cancellations.py`（純函式，不連網）

輸入：`flights.py` 各機場 `fetch` 回來的原始資料（現在存進 gz 的那個結構）＋機場時區＋現在時間。
輸出：每機場、每個 UTC 6 小時格（和 `latest.json` 一樣對齊 00／06／12／18Z）的統計：

```json
{
  "airport": "RCTP",
  "from": "2026-10-18T06:00:00Z",
  "to": "2026-10-18T12:00:00Z",
  "asOf": "2026-10-18T13:05:00Z",
  "dep": { "total": 118, "cancelled": 2, "delayed": 7, "other": 0 },
  "arr": { "total": 121, "cancelled": 1, "delayed": 9, "other": 0 }
}
```

規則（預設值，Shawn 已確認的照這裡；他要改會另外說）：

- **依表定時間歸格**（不是預計或實際時間；取消的班機才會留在原本的格）。各機場的表定時間是當地時間，
  用 `airports.json` 的 `tz` 轉成 UTC
- 出發（`dep`）與抵達（`arr`）分開算；**不含貨機**（香港的 `cargo=false` 已經排掉；其他機場有貨機欄位的話也排掉）
- 一班航班只算一次：共掛班號（香港 `flight` 陣列有多個班號）算一班；桃園同一筆出現在多個航廈時以班號＋表定時間去重
- `cancelled`：狀態表示取消（桃園「取消CANCELLED」、香港 `Cancelled`、澳門 `CANCELLED`／`Cancelled`、
  松山／高雄請從實際資料確認用語）
- `delayed`：狀態表示延誤（桃園「延遲DELAY」、高雄「延遲」、松山「延誤…」等），**或**預計／實際時間比表定時間
  晚 60 分鐘以上（有時間欄位的機場才算；香港 `Dep HH:MM`、澳門 `TOOK OFF AT HH:MM` 這種從狀態字串解析）。
  取消的不重複算延誤
- `other`：**看不懂的狀態**（對照表沒列的）。這些仍然算進 `total`，不能悄悄丟掉；log 印出沒對到的狀態字串
  （每種印一次）
- 時間格的 `from`／`to` 用 `timeutil.iso`
- 每機場每個來源的狀態字串對照表寫在模組開頭的 docstring，並說明是從 `data` 分支 2026-10-18 的快照整理的
  （`git fetch origin data` 之後 `git show data:history/flights/2026-10-18/<機場>-0506.json.gz | gunzip`
  可以看到每個機場的實際結構與狀態用語；澳門的 `status` 有 `"0"` 這種值，當成「還沒有狀態」處理）

### 2. 存檔：`history/cancellations/<YYYY-MM-DD>.json`（`data` 分支）

- 日期是**格的 UTC 日期**，一天一個檔，內容是陣列，每個元素是上面那種物件，依 `airport`、`from` 排序；
  JSON 用兩個空白縮排（git 差異壓縮才有效）
- 每次 build 把這次算出來的所有格**合併**進對應日期的檔案（桃園的資料含前一天與後一天、香港含前一天，
  所以一次可能動到兩三個日期的檔）：
  - 同一 `airport`＋`from` 已經有紀錄時，**新的跑次覆蓋舊的，但新跑次的 `dep.total + arr.total`
    比舊的少就保留舊的**（來源只給當天的機場，隔天看不到前一天的班機，不能讓它把昨天的統計洗成 0）
  - 沒有的就加進去
- 只進 `data` 分支，**不進 GitHub Pages、不進 `latest.json`**（`publish()` 不要帶它）
- **不再寫** `history/flights/*.json.gz`；`flights.py` 的 `fetch_and_store` 改成只回傳資料（或拆成 `fetch` 一個函式），
  快照的存檔邏輯刪掉。`data` 分支上既有的一天份舊檔不用管
- 某個機場抓不到時：那個機場這次不產生統計、`sources.flights` 照現在的方式回報失敗；其他機場照算

### 3. `build.py`

- `run()` 裡抓航班的那一段改成：抓 → 算統計 → 合併寫檔。統計失敗（例如某機場格式突然變了）只 log、
  不讓整個 build 失敗，`sources.flights` 加 `"statsError": "<機場>:<訊息>"`（這是規格以外的欄位，README 的
  「規格以外加的欄位」要補一行）
- `latest.json` **任何既有欄位不改名、不改型別**；這個 PR 不新增 `latest.json` 的欄位

### 4. 文件與測試

- `README.md`：「輸出」那段把 `history/flights/…` 改成 `history/cancellations/<日期>.json` 並寫格式與合併規則；
  「資料來源與授權」表的航班那幾列，用途改成「算每 6 小時格的取消／延誤統計（不存原始資料）」；
  「怎麼跑」那段不變
- `docs/ORCHESTRATOR.md`：「`data` 分支」那節同步改
- `flights.py` docstring 最後一段（存成 gz 的說明）改掉
- 測試：`tests/test_cancellations.py`，用既有的 fixtures（`tests/fixtures/hkg_arrival.json`、`tpe_flights_big5.txt`、
  `tsa_intl_departure.json`、`khh_intdep.json`、`mfm_departure_en.json`）測：歸格對不對（含跨 UTC 日期）、取消／
  延誤／other 的計數、去重、合併規則（新的覆蓋、total 變少時保留舊的）。`tests/test_build.py` 的契約測試照舊要過；
  如果 fixtures 不夠用（例如沒有取消的班機），在 fixture 裡**加**幾筆，不要改既有的筆
- 不要動 `assess.py`、`airports.json` 的門檻、`.github/workflows/*.yml`

## 回報時要附

- 每個機場對照表裡「取消」「延誤」各對到哪些狀態字串
- 用 `data` 分支 2026-10-18 的快照實際跑一次 `cancellations.py`，貼每個機場有幾格、取消與延誤各幾班、`other` 是哪些字串
- 一年下來 `history/cancellations/` 大概多大（估算就好）

本機 `ruff check .`、`ruff format --check .`、`pytest -q` 全過才推，盡量一次推完。
開 PR 之後：`gh pr checks --watch` 等 CI，紅了自己修到綠（最多三輪），全綠時告訴我；
不要自己合併，我會先請主對話審查。
