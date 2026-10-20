# HD15：Google WeatherNext 3——BigQuery／GCS Zarr 接入、旁觀模式、歷史資料試讀、條款確認

模型：Opus，強度高。**現在就做、PR 掛著等 allowlist 核准**（Shawn 2026-10-20 19:04 已送出申請：產品負責人的 Google 帳號與 GitHub Actions
的服務帳號（`GOOGLE_SERVICE_ACCOUNT_JSON` 那把）；勾了 WeatherNext 3 on BigQuery、WeatherNext 3 on GCS (Zarr)、WeatherNext 2 on GCS
(Zarr)、WeatherNext 2 Mean on GCS (Zarr)；兩份條款已同意；審核 5–7 個工作天）。核准前拿不到即時資料：**照文件寫、用文件範例與 mock
測試**。改 `src/hongthai/sources/wn3.py`（新）、`config.py`（`MODELS` 加 `wn3`，`voting` 由 `events.json`／環境變數控制）、`build.py`、
`tracks.py`（WN3 路徑）、`events.py`（補報）、測試、README、`docs/ORCHESTRATOR.md`。**依賴 HD16**（`Model.voting` 開關）——HD16 合併後
再開這支，或從它的分支接。

先讀 `docs/ORCHESTRATOR.md`「多模式投票」（HD14–HD16）與「29W 驗證期凍結」、`docs/worklog/2026-10-19.md`「待決定」裡 WeatherNext 3
的查證、`src/hongthai/sources/aifs.py`、`sources/openmeteo.py`（HD16）、`assess.py`、`tracks.py`、`build.py`、`ai/gemini.py`（服務帳號
JSON 怎麼從環境變數讀、不落地）。

## 定案（Shawn 2026-10-20 19:04）

1. **先做、掛著**：BigQuery 表 `weathernext_3_0_0_0p1deg`（0.1°，表面統計：平均與百分位）或 GCS `gs://weathernext3_statistics_spatial/`
   （Zarr v3，表面統計）取 51 個機場；64 成員原始在 `gs://weathernext3_spatial/`（Zarr v3，含 3D）。文件：
   `developers.google.com/weathernext/guides/access-forecast`、`guides/models`、`guides/dissemination-schedule`（起報時間與延遲）
2. **旁觀模式**：`wn3` 進 `MODELS`，`voting` 預設 **False**（核准若在 2026-10-22 12:00 凍結之後，WN3 照樣每報抓、存進 `models[]` 與 29W
   路徑檔，但不算分母、不投票；網頁標「旁觀，不投票」）；解凍後改 True 再投票。開關放 `config.py` 一個常數＋環境變數
   `WN3_VOTING=1` 可覆寫
3. **歷史資料試讀**：`gs://weathernext3_spatial/` 與 statistics bucket 的**1 小時以前的資料（CC BY 4.0）**，不用 allowlist 能不能匿名讀？
   雲端用 `gsutil ls -r`／`gcloud storage ls` 匿名試（或 `fsspec`＋`gcsfs` 匿名），能讀就寫進 README；能的話颱風過後的報告至少能補
   WN3 的路徑（`backfill-tracks` 加 `wn3`）
4. **條款**：上線前讀完 **GDM Real-Time Weather Forecasting Experimental Data Terms of Use**（連結在 `guides/disclaimers`；PDF 讀得到就
   全文看），回報：即時預報（有效時間 1 小時內或未來）能不能**公開顯示在網頁與 `latest.json`**、能不能存 history、要不要固定標註。
   **不行的話**：WN3 只用 1 小時前以前的資料（CC BY 4.0）做報告比對（路徑、陣風對 METAR），不上網頁、不投票——程式用一個開關
   `WN3_MODE = "observe" | "report-only"` 切
5. 核准後：WN2 系集平均（GCS Zarr 整片網格）拿來找颱風中心比 Open-Meteo 逐點省量——這支把 `tracks.py` 的找中心函式寫成**吃任何
   lat/lon 網格**的通用版，WN3 與之後的 WN2 平均都能用；HD16 的 Open-Meteo 照舊

## 1. 來源 `sources/wn3.py`

- 認證：`GOOGLE_SERVICE_ACCOUNT_JSON`（同 Gemini，`json.loads` → `google.oauth2.service_account.Credentials`，不寫磁碟）、
  `GOOGLE_CLOUD_PROJECT`；**不加新的 secret**
- 首選 **BigQuery**（依賴 `google-cloud-bigquery`，寫進 `pyproject.toml`）：一個查詢取 51 個機場最近一報（主報 00／06／12／18Z、15 天）
  的 6 小時格——表的分割與叢集欄位照文件寫（`init_time`／`forecast_hour`／`lat`／`lon` 之類，**欄位名以文件為準**，mock 照同樣結構）；
  只取需要的欄位：`wind_speed_10m`（或 u／v）、`total_precipitation_1hr`（6 小時加總）、`temperature_2m`、百分位（p50、p90 若有）；
  查詢量要小（`WHERE` 先切 `init_time` 與座標方框，回報預估掃描量與費用——BigQuery 每月 1 TB 免費）
- 備援 **GCS Zarr**（`gcsfs`＋`zarr`＋`xarray`）：只在 BigQuery 失敗時；讀 statistics bucket 的平均場
- 沒陣風 → 平均風 × 機場 G（`gust_estimated=True`）；成員統計有 p90 時另存 `windKtP90`（新鍵，只在 wn3 那筆）
- 起報時間：照 dissemination schedule 取最近「已完整發布」的主報；`runs.wn3`
- `timing` `source: "wn3"`；`BUDGET_S["wn3"] = 120`（總和 1665 → 1785 秒，`build.yml` 那步 30 → 32 分鐘、job 40 → 42）；
  失敗 `sources.wn3.ok: false`、不沿用、整報不壞；核准前每報會是 `error: "http_403"` 之類，**這是預期的**（README 寫明）

## 2. 投票與輸出

- `MODELS` 加 `wn3`「Google WeatherNext 3／Google WeatherNext 3」（接在 `wn2-ens` 之後），`voting=False`（第 2 點）、`gust_estimated=True`
- `models[]` 那筆：`windKt`、估算 `gustKt`、`rain6hMm`、`ptype`（有降雪／型態就填，沒有 null）、`levels`、`level`；頂層 `models[]` 的
  `voting: false`
- `WN3_MODE = "report-only"` 時：不寫進 `latest.json`（`models[]` 沒有這筆、頂層清單也沒有），只寫 `history/events/<id>/tracks/` 與
  一份 `history/events/<id>/wn3/<報時間>.json`（51 機場每格的數字，給報告用）

## 3. 路徑（`tracks.py`）

- 找中心的函式通用化：輸入任意規則 lat/lon 網格的海平面氣壓（numpy 陣列＋座標），HD21 的 GFS／AIGFS／AIFS 改呼叫同一個函式（結果不變，
  有測試保證）；WN3 用 statistics bucket 的 `mean_sea_level_pressure` 平均場（0.1°）找中心，存 `<報>-wn3.json`；若原始 64 成員也讀得到，
  另存 `<報>-wn3-ens.json`（成員路徑＋中位數，同 IFS 系集的格式）
- `backfill-tracks` 加 `wn3`（第 3 點能匿名讀歷史才有用）

## 4. 測試與文件

- 全部用 mock：BigQuery client 假物件回文件結構的列；Zarr 用 `xarray` 造一個小網格存到暫存目錄（`zarr` 本機）；403／沒核准 → `ok: false`
  整報不壞；`voting=False` 不算分母；`WN3_MODE` 兩種；通用找中心函式對 HD21 既有測試結果不變
- README「資料來源」加 WeatherNext 3（即時：GDM 實驗條款；1 小時前以後：CC BY 4.0）、申請與核准流程（不寫帳號名）、兩個開關；
  「已知的保守假設」加「WN3 核准前每報 `ok: false`」；ORCHESTRATOR 多模式投票那條補「HD15 已實作（待核准）」

## 回報時要附

- **條款讀後的結論**（第 4 點，逐條引原文關鍵句）：能不能公開顯示即時預報、能不能存、要怎麼標註
- 匿名讀歷史 Zarr 的結果（第 3 點）：指令與回應
- BigQuery 查詢的 SQL、預估掃描量；Zarr 備援一報要讀多少 MB
- 核准後要做的事清單（Shawn 要做的：確認核准信；主對話要做的：把 `WN3_VOTING`／`WN3_MODE` 切到哪）

本機 `ruff check .`、`ruff format --check .`、`pytest -q` 全過才推，盡量一次推完。
開 PR 之後：`gh pr checks --watch` 等 CI，紅了自己修並推到同一個分支（最多三輪），全綠時告訴我；
不要自己合併，我會先請主對話審查。
