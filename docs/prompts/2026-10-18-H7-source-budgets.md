# H7：來源時間預算、ECMWF 429 與鏡像、沿用上一份模式資料、每次 build 的耗時紀錄

模型：Opus，強度高。這是 build 流程的韌性修正，不碰等級規則、不改 `latest.json` 既有欄位。

先讀 `docs/ORCHESTRATOR.md`、`README.md`、`src/hongthai/build.py`（`_call`、`run`、`previous_latest`）、
`src/hongthai/sources/__init__.py`（`http_get`）、`src/hongthai/sources/ecmwf.py`、`src/hongthai/sources/gfs.py`。

## 背景（2026-10-18 build #4 失敗的原因）

手動跑 build 時，ECMWF 開放資料入口從一開始就回 `429 Too Many Requests`。`ecmwf-opendata` 底下的 `multiurl`
預設 `retry_after=120`、`maximum_retries=500`，所以程式每兩分鐘重試一次、打算試 500 次；10 分鐘到被 Actions
砍掉，後面的 GFS、TAF、警報、航班全部沒跑到，整次沒有產出。

另外 ECMWF 的提示：入口限 500 個同時連線，資料同步鏡像在 AWS、Azure、Google Cloud，建議從那裡抓。

## 要做的事

### 1. ECMWF：有上限的重試、改用鏡像

`ecmwf-opendata` 的 `Client(...)` 從某個版本起接受 `maximum_retries`、`retry_after`、`use_server_retry_after`
（0.3.35 有；請用 `inspect.signature(Client.__init__)` 確認，並把 `pyproject.toml` 的最低版本提到有這些參數的
那一版）。`source` 可以是 `"ecmwf"`、`"aws"`（`https://ecmwf-forecasts.s3.eu-central-1.amazonaws.com`）、
`"google"`、`"azure"`；`latest()` 和 `retrieve()` 都打同一個 source。

- 建 Client 時傳 `maximum_retries=3`、`retry_after=10`、`use_server_retry_after=False`（伺服器的 Retry-After
  可能比預算長，不要照它等）
- 順序：**先用 `ecmwf` 的 `latest()` 找最新報**（請求很小），然後下載**先試 `aws`**，aws 沒有那一報
  （404／空檔）或失敗再回 `ecmwf`，再失敗才試 `google`。如果 `ecmwf` 的 `latest()` 本身就 429 到超過重試上限，
  改用 `aws` 的 `latest()`。這樣鏡像落後幾分鐘時不會拿到舊的一報而不自知
- 每個 source 各自計時，`sources.ecmwf` 加 `mirror: "aws"|"ecmwf"|"google"`（規格以外的欄位）表示實際從哪裡抓到
- 系集（enfo）照同一套；系集失敗不影響 HRES（現狀）

### 2. 每個來源有時間預算，超時就記 `ok:false` 繼續跑

`build.py` 的 `_call()` 改成在 **daemon 執行緒**裡跑 `fn`，主執行緒 `join(timeout=預算)`；超時就記
`sources.<名稱> = {"ok": false, "error": "timeout", "seconds": <預算>}`，不等它、繼續下一個來源。
航班那段（`flight_stats`）也走同一套。

預算（秒；預設值，Shawn 確認過的照這裡）：

| 來源 | 預算 | 2026-10-18 實測 |
| --- | --- | --- |
| ecmwf（HRES＋系集，含鏡像切換） | 240 | 約 90＋10 |
| gfs | 180 | 約 110 |
| taf、metar | 各 45 | 幾秒 |
| hko、smg | 各 30 | 幾秒 |
| cwa | 45 | 幾秒 |
| flights（抓＋統計＋寫檔） | 120 | 約 20 |

總和約 12 分鐘，所以 `build.yml` 的「產生 latest.json」`timeout-minutes` 改成 15、job 的改成 25
（排程間隔至少 4.5 小時，不會重疊）。預算集中寫在一處（例如 `build.py` 開頭的 `BUDGET_S` dict），之後好調。

被放棄的執行緒還會在背景繼續跑，要處理兩件事：
- GRIB 解析不是執行緒安全的：`grib.py` 的 `read_points`（或所有呼叫 eccodes 的地方）加一個全域 `threading.Lock`，
  而且超時後主執行緒設一個 `cancelled` 旗標，被放棄的執行緒在下載完要解析前檢查旗標、直接結束，不再解析
- daemon 執行緒不會擋住程式結束；`build.py` 結束時不要 `join` 它們

### 3. 模式來源失敗時沿用上一份

`ecmwf` 或 `gfs` 失敗（任何原因：逾時、429 用盡、格式錯）時，從上一份 `latest.json`（`previous_latest()` 那份，
先找 `--archive` 裡的，沒有就從 Pages 抓）把**同一個機場、同一個 `from`** 的 `slots[].model.ec`（ecmwf 失敗時）
或 `slots[].model.gfs`（gfs 失敗時）抄過來，等級照常用抄來的值算。沒有對到的格維持 `null`。

- **`sources.<名稱>.ok` 一定維持 `false`**＋原本的 `error`，另外加 `reusedFrom: "<上一份的 generatedAt>"`
  （規格以外的欄位）。網頁靠 `ok:false` 顯示「這次沒讀到」，沿用的資料不能看起來像這次新抓的
- `runs.ecmwf`／`runs.ecmwfEns`／`runs.gfs` 用上一份的值（這是舊預報的真實時次，不要改成現在）
- **沿用有期限：24 小時**。用上一份的 `runs.<名稱>`（模式時次）判斷：`現在 − runs.<名稱>` 超過 24 小時就不沿用，
  那段 `model.ec`／`model.gfs` 留 `null`、`runs.<名稱>` 留 `null`、不加 `reusedFrom`，照現有缺資料的規則處理
  （`model.level` 為 `null`、`agreement` 為 `null`、都沒資料的格 `level: "unknown"`）。因為沿用時 `runs` 帶的是
  舊時次，連續失敗時會自然在 24 小時後停掉，不會一直拿舊預報當新的；系集（`runs.ecmwfEns`）各自算
- 只有模式層這樣做；TAF、METAR、警報是官方即時資料，失敗就空著，不沿用
- 上一份也沒有（第一次跑、或 Pages 抓不到）就照現在的行為

### 4. 每次 build 的耗時紀錄（`data` 分支，逾時被砍也留得下來）

寫 `history/timing/<YYYY-MM>.jsonl`（一行一筆 JSON，**每個來源一跑完就立刻 append 並 flush**，不要等全部結束
才寫）。`build.yml` 的「推 data 分支」是 `if: always()`，所以就算「產生 latest.json」被砍，已經寫進去的行會
跟著推上去。每行：

```json
{"run": "2026-10-18T09:28:35Z", "source": "ecmwf", "ok": false, "error": "timeout", "seconds": 240.0, "bytes": 0, "mirror": "aws"}
```

- 開始時先寫一行 `{"run": "...", "source": "start", "ok": true, "seconds": 0, "commit": "<GITHUB_SHA 前 7 碼，沒有就 null>"}`，
  全部跑完再寫 `{"run": "...", "source": "done", "ok": <整次有沒有產出 latest.json>, "seconds": <總秒數>}`。
  沒有 `done` 那行就表示那次被砍了
- `error` 用 `sources.<名稱>.error` 同一套代碼；`mirror` 只有 ecmwf 有；欄位名固定，之後主對話會直接
  `git show data:history/timing/2026-10.jsonl` 來看

### 5. 文件與測試

- `README.md`：「怎麼跑」補預算與逾時行為；「輸出」的 `data` 分支那段加 `history/timing/`；
  「規格以外加的欄位」補 `sources.ecmwf.mirror`、`sources.<模式>.reusedFrom`、`sources.<名稱>.error="timeout"`；
  「資料來源與授權」ECMWF 那列補「經 AWS／Google 鏡像」（授權不變，仍是 CC BY 4.0，© ECMWF）
- `docs/ORCHESTRATOR.md`：「`data` 分支」那節加 `history/timing/`；「已知的保守假設」下面加一段「來源逾時與沿用」
- 測試：`tests/test_build.py` 加——預算超時會記 `timeout` 且後面的來源照跑（用一個會 `sleep` 的假 fetch，
  預算設 0.2 秒）、ecmwf 失敗時 `model.ec` 從上一份抄過來、`ok` 仍是 `false` 且 `reusedFrom` 有值、上一份的 `runs.ecmwf` 超過 24 小時就不抄（`model.ec` 為 `null`、沒有 `reusedFrom`）、timing 檔每個來源一行而且
  在來源之間就已經寫進去；`tests/test_sources.py` 加 ECMWF 鏡像順序（用假 Client：ecmwf `latest()` 成功、
  aws 下載 404 → 回 ecmwf 下載；ecmwf `latest()` 一直 429 → 改用 aws 的）。測試照舊不連網
- `latest.json` 既有欄位不改名、不改型別；`tests/test_build.py` 的契約測試照舊要過
- 不要動 `assess.py`、`airports.json` 的門檻、`cancellations.py` 的規則

## 回報時要附

- `ecmwf-opendata` 最低版本改成多少、為什麼
- 預算表最後用的數字
- 用本機跑一次 `python -m hongthai.build --out /tmp/out --archive /tmp/data`（沙盒連得上網的話），貼
  `history/timing/` 那幾行；連不上就說明哪些只靠測試驗證

本機 `ruff check .`、`ruff format --check .`、`pytest -q` 全過才推，盡量一次推完。
開 PR 之後：`gh pr checks --watch` 等 CI，紅了自己修到綠（最多三輪），全綠時告訴我；
不要自己合併，我會先請主對話審查。
