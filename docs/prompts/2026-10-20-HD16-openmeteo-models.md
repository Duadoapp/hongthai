# HD16：Open-Meteo 加三票——DWD ICON、JMA GSM、Google WeatherNext 2 系集；旁觀模式開關；暴風雪特別警報

模型：Opus，強度高。**今晚開工、10/21 合併上線**（Shawn 2026-10-20 19:04 定案；10/22 12:00 台灣時間起凍結）。
改 `src/hongthai/sources/openmeteo.py`（新）、`config.py`（`MODELS` 加三個、`Model.voting` 開關）、`assess.py`（投票吃 `voting`、
WN2 系集只投高）、`build.py`（來源 `openmeteo`、預算、沿用）、`gustfactor.py`（係數套到新模式）、`sources/jma.py`（暴風雪特別警報）、
`ai/prompt.py`、測試、README、`docs/ORCHESTRATOR.md`。`latest.json` 只加：頂層 `models[]` 多三筆（含新鍵 `voting`）、
`slots[].model.models[]` 多三筆、`sources.openmeteo`、`runs.icon`／`runs.jma`／`runs.wn2-ens`。

先讀 `docs/ORCHESTRATOR.md`「多模式投票」那條（HD14／HD18／HD19）與「29W 驗證期凍結」、`src/hongthai/config.py`（`Model`、`MODELS`）、
`assess.py`（`model_entries`、`vote`、`_pool`、`estimated_for_slot`）、`gustfactor.py`、`build.py`（`BUDGET_S`、`REUSE_FIELDS`、
`_rescore`、`timing`）、`sources/aifs.py`（沒陣風的模式怎麼接）、`sources/jma.py`、README「怎麼算」投票那段。

## 定案（Shawn 2026-10-20 19:04，加 WN2 補充）

1. **三票**：DWD ICON global（`icon`，有陣風）、JMA GSM（`jma`，陣風看 Open-Meteo 有沒有給，沒有就估算）、Google WeatherNext 2 系集
   （`wn2-ens`，64 成員、0.25°、15 天、Open-Meteo 只處理 00／12Z）。投票 5 → **8 票**
2. **WN2 系集比照 IFS 系集只投高**：64 成員各自 10 米風 × 該機場 G 算估算陣風，≥ 49 節（`modelHighGustKt`＋估算）的成員比例 ≥ 30%
   （`ecP49High`）投高、否則投低；判「中」時不算分母。`models[]` 那筆 `levels.wind` high／low、其他 null，數字欄位放**中位數成員**
   的 `windKt`／估算 `gustKt`（`gustEstimated: true`）、`p49Kt`（成員比例，新鍵只在這筆有，其他筆 null）
3. **保險**：Open-Meteo 失敗或逾時 → 這一報沒有這三票（`models[]` 三筆數字全 null、`levels` 全 null、不算分母）、`sources.openmeteo
   .ok: false`＋`error`；**整報不能失敗**；也不沿用舊資料（避免 24 小時前的 WN2 當今天的票——和 ecmwf／gfs 的沿用不同，寫清楚）
4. **旁觀模式**：`Model.voting: bool = True`；`voting: False` 的模式照樣抓、照樣寫進 `models[]`（含 `levels`、`level`）和 29W 路徑檔，
   但**不算進任何一類的分母、不投票**；`vote.total` 不含它。頂層 `models[]` 每筆加 `voting`（布林）讓網頁標「旁觀，不投票」。
   HD16 的三票 `voting: True`；這個開關給 HD15 的 WN3 與之後的新模式用
5. **暴風雪特別警報（JMA 代碼 32）**：接，`kind: "jma_snowstorm_emergency"`、`level: "high"`、算 `snow`（和大雪特別警報同級）
6. **WN2 的路徑不做**（Open-Meteo 逐點 API 對網格查太重；核准 WN 原始資料後再用 GCS Zarr 的系集平均找中心）
7. 授權：Open-Meteo 免費版只限非商業（HongThai、Duado 目前沒收費、沒廣告）；README 與 ORCHESTRATOR 寫明 **(a) 一旦收費、訂閱或放
   廣告，必須改買商業方案或拿掉這三個模式；(b) 網頁與資料來源標「Open-Meteo（CC BY 4.0）・DWD ICON・JMA・Google WeatherNext 2」**；
   Open-Meteo 的 WeatherNext 頁沒列 Google 額外限制，但 Google 對即時 WN 資料另有實驗條款、Open-Meteo 的授權來源查不到——
   README「已知的保守假設」記這個不確定性

## 1. 來源 `sources/openmeteo.py`

- 兩個端點、**每個端點一個請求帶 51 個座標**（`latitude=…,…&longitude=…,…`，逗號分隔）：
  - `https://api.open-meteo.com/v1/forecast?models=icon_global,jma_gsm&hourly=wind_speed_10m,wind_direction_10m,wind_gusts_10m,
    precipitation,snowfall,visibility,weather_code&forecast_days=6&wind_speed_unit=kn&timezone=UTC`（變數名以文件為準；JMA 沒有的
    變數會回 null）
  - `https://ensemble-api.open-meteo.com/v1/ensemble?models=google_weathernext2_ensemble&hourly=wind_speed_10m,wind_direction_10m,
    precipitation&forecast_days=6&temporal_resolution=native&wind_speed_unit=kn&timezone=UTC`（64 成員 `wind_speed_10m_member00`…）
  - 不用金鑰；`User-Agent` 寫 HongThai 與 repo 網址；逾時 60 秒；失敗不重試（保險見定案第 3 點）
- 起報時間：回應沒有直接給，用文件的 model updates 時程推（或 `/v1/forecast` 的 `generationtime`——查文件有沒有 `last_run`／
  `model_run` 之類；沒有就記抓取時間、`runs.*` 寫推算的最近一報並在 README 註明）
- 轉成每模式每 6 小時格：ICON／JMA 格內逐時最大陣風（沒陣風的用估算）、對應時間風向、格結束時 6 小時雨量（逐時加總）、降水型態
  （`snowfall` > 0 且佔一半以上 → `snow`，`weather_code` 的凍雨碼 → `freezing_rain`，其餘 `rain`／`none`）、能見度最小值（ICON 有、
  JMA 沒有）；WN2 每成員格內最大 10 米風 × G
- **呼叫量**：Open-Meteo 以加權呼叫計（一地 7 天單變數 ≈ 6.4 次；免費版每日 10,000、每月 300,000）。**第一次實跑把兩個請求的加權
  次數算出來回報**（文件的 API 頁會顯示「equivalent to N calls」，照它的公式）；一天 4 報若超過每日 5,000，WN2 系集改成只抓
  「上一報 ≥ 中或有變」的最多 20 個機場（同 AI 候選的選法）、其他機場 `wn2-ens` 那筆 null；ICON／JMA 一律 51 個
- `timing` 一行 `source: "openmeteo"`；`BUDGET_S["openmeteo"] = 90`（總和 1575 → 1665 秒，`build.yml` 那步 28 → 30 分鐘、job 38 → 40）；
  原文存 `history/raw/<日期>/<時間>-openmeteo.json`（兩個回應）

## 2. 投票（`config.py`、`assess.py`、`gustfactor.py`）

- `MODELS` 加（順序接在 `aigfs` 之後）：`icon`「德國 ICON／DWD ICON」、`jma`「日本 GSM／JMA GSM」、`wn2-ens`「Google WeatherNext 2
  系集／Google WeatherNext 2 ensemble」（四語照 HD14 的寫法）；`wn2-ens` `votes_only_high=True`、`gust_estimated=True`；`jma`
  `gust_estimated` 視 Open-Meteo 有沒有陣風而定（有就 False）
- `Model.voting`（第 4 點）：`_pool`／`vote`／`tally` 一律跳過 `voting=False` 的模式；`vote.total`／`high`／`medium`／`low` 不含它；
  `models[]` 每筆照常寫
- 雪的投票：有降水型態的模式才投（ICON、JMA 有 `snowfall` → 投；WN2 不投雪、不投雨、不投霧，同 IFS 系集）；霧：ICON 有能見度 →
  霧的分母變 2（GFS＋ICON），模式層霧仍封頂中（HD10）
- `gustfactor`：G 照 HD19（IFS 樣本）；ICON 有陣風就不估算；新模式**不進樣本**
- `_rescore`／沿用：這三個模式**不沿用**（第 3 點）

## 3. 暴風雪特別警報（`sources/jma.py`）

代碼 32 → `jma_snowstorm_emergency`、high、`SNOW_WARNING_KINDS` 加；四語「暴風雪特別警報」／"snowstorm emergency warning"；測試一個案例。

## 4. AI 短評、預覽圖

- `ai/prompt.py`：`airport_text` 的模式列會自動多三行（吃 `models[]`）；投票句用 `vote.total`（旁觀的不算）；`FORBIDDEN_TOKENS` 加
  `ICON`（整字）、`GSM`、`WeatherNext`——短評寫「德國模式」「日本模式」「Google 的 AI 系集」
- `og.py` 不動

## 5. 測試與文件

- `tests/test_sources_openmeteo.py`：用雲端實抓一份（裁到 3 個機場、WN2 裁到 8 個成員）當 fixture；格的換算、型態、能見度、失敗回 None
- `tests/test_vote.py`：8 票的案例；`voting=False` 不算分母也不投；WN2 只投高、p49 比例；三票缺席時退回 5 票結果和現在一樣
- `tests/test_build.py`：`sources.openmeteo` ok／false 兩種、整報不失敗、頂層 `models[]` 有 `voting`、不沿用
- README：「怎麼算」投票改 8 票（含旁觀模式）、「資料來源」加 Open-Meteo 三個與授權條件（定案第 7 點）、「已知的保守假設」加
  WN2 授權不確定、起報時間推算；`docs/ORCHESTRATOR.md` 多模式投票那條補「HD16 已實作」與不一樣的地方，`models[].voting` 要轉 Duado

## 回報時要附

- 兩個請求的實際參數、回應大小、秒數、**加權呼叫次數**（一報、一天）
- 最近一報 8 票的 `vote` 分布：1020 格裡高／中／低各幾格，對照只有 5 票時
- JMA GSM 有沒有陣風；ICON 能見度有沒有值

本機 `ruff check .`、`ruff format --check .`、`pytest -q` 全過才推，盡量一次推完。
開 PR 之後：`gh pr checks --watch` 等 CI，紅了自己修並推到同一個分支（最多三輪），全綠時告訴我；
不要自己合併，我會先請主對話審查。
