# HD33a（只存資料＋報告工具）：UKMO、GEM、ARPEGE、CMA 回補 29W 期間的預報，和現有 8 個模式一起比

模型：Sonnet，強度中。**只多存資料、只改報告工具**：不改 `latest.json`、`models[]`、等級、投票、AI、網頁；**可以現在合併**
（29W 凍結期間也可以）。改 `src/hongthai/sources/openmeteo_backfill.py`（新）、`src/hongthai/events.py`（多一個手動任務）、
`.github/workflows/events.yml`（`task` 選項多一個）、`tools/report_29w.py`、測試、README、`docs/ORCHESTRATOR.md`。

先讀 `docs/ORCHESTRATOR.md`「29W 驗證期凍結」與 Duado spec 第 16 節「颱風期間功能擴充計畫」的「新模式」那條（定案：UKMO、GEM、ARPEGE、
CMA GRAPES 經 Open-Meteo **先旁觀、不投票**，用 29W 回補比準確度後再決定投票或加權；**不照解析度加權**）、`src/hongthai/sources/openmeteo.py`
（現有 ICON／JMA／WN2 的抓法與授權說明）、`events.py` 的 `backfill-metar`／`backfill-flights`（手動任務的寫法）、`tools/report_29w.py`
（HD22、HD36）。旁觀進 `latest.json` 是另一支 HD33b，這支不做。

## 1. 抓什麼

- 來源：Open-Meteo **Previous Runs API**（`https://previous-runs-api.open-meteo.com/v1/forecast`）——變數加 `_previous_day1`…`_previous_day5`
  是「N 天前那一報」對同一個時間的預報，剛好對報告的提前時間 0–24…96–120 小時。**以 Open-Meteo 文件為準**：先確認這四個模式在
  Previous Runs 有沒有、模式代號（預計 `ukmo_global_deterministic_10km`、`gem_global`、`meteofrance_arpege_world`、`cma_grapes_global`）、
  `previous_day` 最多到幾天、10 月的資料還在不在；沒有的模式在 PR 說明寫清楚，不要換別的 API 硬補
- 變數：逐時 `wind_speed_10m`、`wind_direction_10m`、`wind_gusts_10m`、`precipitation`（`wind_speed_unit=kn`）；某模式沒有陣風（全 null）
  就照 `openmeteo.py` 的做法標 `gustEstimated`，報告用平均風 × 機場的估算係數（`gustfactor` 的係數，同 AIFS／JMA）
- 機場：`events.json` 29W 的 26 個；時間：29W 期間（台灣 10/19 00:00 起）到 `--truth-until` 能用的最後一天；一次請求帶全部座標
  （同 `openmeteo.py`），遵守每分鐘上限
- 存 `data` 分支 `history/events/29W/backfill/openmeteo-<模式>.jsonl`：一行一個（機場、`validAt`、`previousDay`、`windKt`、`windDir`、
  `gustKt`、`gustEstimated`、`precipMm`），**只追加**、重跑不重複（同一鍵已有就跳過）
- 手動任務 `backfill-openmeteo`（`events.yml` 的 `workflow_dispatch` 多這個選項，參數用事件 id）；合併後 Shawn 手動跑一次、10/27 定稿前再跑一次

## 2. 報告工具

- `tools/report_29w.py` 的 (a) 陣風多四列（標「旁觀・回補」），用回補檔：一格（6 小時）的預測取格內逐時陣風最大值，提前時間用
  `previousDay`（N 天前那報 → 提前時間落在哪一段照 HD22 的切法，把「起報」當成 `validAt` 減 N 天的 00Z，PR 說明寫清楚怎麼對的）
- 同一套 METAR 實測、`--until`／`--truth-until`（HD36）照套；37／48 節命中、漏報、誤報照算
- 另一張表：**每格的「模式等級」**（照 `assess.py` 單一模式的陣風與側風門檻判低／中／高）對停飛實測，和現有 8 個模式各自的等級並列——
  這是之後決定「投票或加權」的依據
- 不給回補檔時報告和現在一樣

## 3. 授權

README 資料來源：Open-Meteo（CC BY 4.0）・UK Met Office・ECCC GEM・Météo-France ARPEGE・CMA GRAPES，照 Open-Meteo 文件的出處寫法；
各模式若有額外條款（例如 UKMO）照 Open-Meteo 文件註明。非商業條款同現有說明

## 4. 測試

Previous Runs 回應的 fixture（手造，含某模式陣風全 null）：欄位轉換、只追加不重複、提前時間對應、報告多四列、不給回補檔輸出不變

## 回報時要附

- 四個模式在 Previous Runs 的實際代號、可用天數、陣風有沒有（實測一次）
- 請求數、回應大小、耗時
- 用 `data` 分支現在的資料試跑報告的那幾列

本機 `ruff check .`、`ruff format --check .`、`pytest -q` 全過才推，盡量一次推完。
開 PR 之後：`gh pr checks --watch` 等 CI，紅了自己修並推到同一個分支（最多三輪），全綠時告訴我；
不要自己合併，我會先請主對話審查。
