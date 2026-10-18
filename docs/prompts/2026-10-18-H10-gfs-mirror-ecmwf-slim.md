# H10：GFS 改抓 AWS 鏡像、ECMWF 下載量減半、沿用找最近有資料的一份、記下看不懂的航班狀態

模型：Opus，強度高。這是來源層的修正，不碰等級規則；`latest.json` 既有欄位不改名、不改型別。

先讀 `docs/ORCHESTRATOR.md`、`README.md`、`src/hongthai/sources/gfs.py`、`src/hongthai/sources/ecmwf.py`、
`src/hongthai/grib.py`、`src/hongthai/build.py`（`BUDGET_S`、`previous_latest`、`reuse_models`）、
`src/hongthai/cancellations.py`、`data` 分支的 `history/timing/2026-10.jsonl`。

## 背景（2026-10-18 14:33Z 那次 build，H7 合併後第一次）

```
ecmwf   ok=false  error=timeout   240.0 秒  下載 111,671,090 bytes  mirror=ecmwf
gfs     ok=false  error=http_403    0.3 秒  199 bytes
```

- ECMWF 沒有 429，只是慢：入口的速度在 0.5–1.4 MB/s 之間變動（05:06Z 那次 123 MB 花 90 秒，12:42Z 153 秒，
  這次 240 秒還差一點）。HRES 現在抓 `10fg`、`10fg3`、`10u`、`10v` 四個參數 × 約 40 個步長，全球檔約 113 MB，
  太大了
- GFS：NOMADS 從 12:42Z 那次起就回 403（H6 的程式也一樣，雲端沙盒也是 403；05:06Z 之前都正常）。
  請求是 `find_latest_run` 的第一個 `.idx`，199 bytes，像是 NOMADS 把 GitHub Actions／雲端的 IP 段擋了。
  不管原因是什麼，不能再只靠 NOMADS
- `gfs` 沒有沿用上一份：因為 `reuse_models` 只看「上一份」（12:42Z），那份的 `runs.gfs` 已經是 `null`，
  05:06Z 那份有資料但沒被看。沿用要往前找

## 要做的事

### 1. GFS 改以 AWS 鏡像為主，NOMADS 為備援

NOAA 開放資料（NOAA Open Data Dissemination，公有領域）在 S3 有完整的 GFS：
`https://noaa-gfs-bdp-pds.s3.amazonaws.com/gfs.<YYYYMMDD>/<HH>/atmos/gfs.t<HH>z.pgrb2.0p25.f<FFF>`，
每個檔旁邊有 `.idx`（一行一筆：序號:byte 起點:日期:變數:層:時效…）。不能像 NOMADS filter 那樣裁區域，
但可以用 `.idx` 算出 `GUST:surface`、`UGRD:10 m above ground`、`VGRD:10 m above ground` 三筆的 byte 範圍，
用 HTTP `Range` 只抓那三筆（全球 0.25° 一筆約 0.5–1 MB，21 個步長共約 40–60 MB，比 ECMWF 小）。

- `find_latest_run`：改看 S3 的 `.idx`（最後一個步長存在就表示那一報出齊了），S3 失敗再看 NOMADS
- 下載：先 S3（`.idx` → 三筆 Range；沒有 `.idx` 或 Range 回來不是 GRIB 就當失敗），失敗再退回現在的
  NOMADS filter 流程。`sources.gfs.mirror` 記 `"aws"`／`"nomads"`（規格以外的欄位），`history/timing/`
  的 gfs 那行也加 `mirror`
- 解析沿用 `grib.read_points`（它取機場最近格點，全球檔也能用）；GUST 與 UGRD／VGRD 同一步長配對的規則不變
- 請在沙盒實際對 NOMADS 發一次 `find_latest_run` 的請求，把 403 的回應前 200 個字貼在回報裡（不用進 repo）
- README「資料來源與授權」GFS 那列改成「NOAA GFS（AWS 開放資料鏡像 `noaa-gfs-bdp-pds`，NOMADS 備援）」，
  授權仍是美國政府公有領域

### 2. ECMWF HRES 下載量減半、預算放寬到 300 秒

先量：在沙盒對 `ecmwf` 入口各抓一個步長的 `10fg`、`10fg3`、`10u`、`10v`，記下每個參數每步長的大小，
算出現在一報總共多少、改完多少，寫在回報裡。目標：HRES 一報 **70 MB 以下**。做法（照順序，做到目標為止）：

1. **不再抓 `10fg`**：144 小時內步長是 3 小時一個，`10fg3`（前 3 小時最大陣風）就夠了；144 小時以後
   步長 6 小時一個、只有 `10fg`，那段才抓 `10fg`。`hres_interval_hours` 與 `parse_hres` 照這個規則配
2. `10u`／`10v` 只抓 6 小時整的步長（00／06／12／18 的時間點），3 小時那個陣風區間配**它結束時間往後最近**
   的那個 6 小時步長的風向（`assess.py` 開頭的側風說明同步改）。如果第 1 步就達標，這步不做

然後 `BUDGET_S["ecmwf"]` 240 → 300；`build.yml` 那一步維持 15 分鐘（預算總和約 12.5 分鐘）。
README 的預算表、ORCHESTRATOR 的預算那行同步改。

### 3. 沿用上一份：往前找「最近一份有該模式資料」的

`reuse_models` 現在只看 `previous_latest()`。改成：對每個失敗的模式來源，從 `--archive` 的
`history/<時間>.json` **由新到舊**找第一份「`sources.<名稱>.ok` 是 `true`（不是本身也在沿用的）而且
`runs.<鍵>` 離現在 24 小時內」的，從那份抄；archive 沒有就退回 Pages 的 `latest.json`（現狀）。
`reusedFrom` 記那份的 `generatedAt`。24 小時期限、`ok` 維持 `false` 的規則不變。
`tests/test_build.py` 加：上一份沒資料、再上一份有 → 從再上一份沿用；都超過 24 小時 → 不沿用。

### 4. 看不懂的航班狀態寫進 `data` 分支

現在 `other` 的狀態字串只印在 Actions log，主對話讀不到。`cancellations.py` 加：每次 build 把每個機場
對照表沒列的狀態字串合併進 `history/cancellations/unknown-statuses.json`：

```json
{ "VMMC": { "SOME STATUS": { "count": 3, "firstSeen": "2026-10-18T14:33:00Z", "lastSeen": "…" } } }
```

只存狀態字串與次數，不存班號、時間、航點。`other` 仍照舊算進 `total`。

### 5. 文件與測試

- README「輸出」、「怎麼跑」、「資料來源與授權」、「規格以外加的欄位」（`sources.gfs.mirror`）同步；
  ORCHESTRATOR「資料來源與授權」「已知的保守假設」「來源逾時與沿用」同步
- 測試不連網：GFS 的 `.idx` 解析與 byte 範圍計算用一小段假的 `.idx` 文字；S3 失敗退 NOMADS 的順序用假的
  `http_get`；ECMWF `hres_steps`／參數選擇的規則；沿用往前找；unknown-statuses 合併。`tests/fixtures/` 只加不改
- 不要動 `assess.py` 的門檻與等級規則（側風配風向那段說明可以改）、`airports.json`

## 回報時要附

- NOMADS 403 的回應內容前 200 字、S3 的 `.idx` 是否能直接讀
- ECMWF 每個參數每步長的實測大小、改前改後一報的總量
- 本機跑一次 `python -m hongthai.build --out /tmp/out --archive /tmp/data` 的 `history/timing/` 那幾行
  （連不上的來源說明即可）

本機 `ruff check .`、`ruff format --check .`、`pytest -q` 全過才推，盡量一次推完。
開 PR 之後：`gh pr checks --watch` 等 CI，紅了自己修到綠（最多三輪），全綠時告訴我；
不要自己合併，我會先請主對話審查。
