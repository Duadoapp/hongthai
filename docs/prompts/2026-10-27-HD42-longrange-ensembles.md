# HD42：遠期關注——三套系集第 6–15 天「陣風達 49／29 節」的成員比例

模型：Opus，強度高。**新輸出 `longrange.json`**，`latest.json` 不動、不給 AI、不參與投票。網頁是 Duado HW22（這支合併後開）。

先讀：`docs/worklog/2026-10-27.md`（21:28–21:37 Shawn 的定案）、`sources/ecmwf.py`（系集機率 `10fgg15`／`10fgg25`、24 小時窗、`p29Kt`／`p49Kt`）、
`sources/gfs.py`（AWS、`.idx` 分段下載）、`sources/openmeteo.py`（WN2 系集、計量與每分鐘 600／每天 5,000 次上限）、`gustfactor.py`（估算陣風係數 G）、
`budget.py`（`BUDGET_S` 總和已經 1,910 秒、build 上限 45 分）、`events.yml`（另一支 workflow 的寫法）、README「資料來源與授權」。

## 定案（Shawn 2026-10-27 21:28–21:37）

1. **三套系集分開列，不合併**：歐洲系集（ECMWF ENS，51 成員，用它現成的陣風機率產品）、**美國系集 GEFS**（31 成員，新來源，NOAA AWS 開放資料）、
   **Google WN2 系集**（64 成員，經 Open-Meteo；只有平均風 → 用 G 估算陣風、標「估算」；**遠期那段一天抓一次**，控制在 Open-Meteo 免費額度內）
2. 看每套系集「陣風達 **49 節**」的成員比例，也列「達 **29 節**」；颱風位置不做
3. **第 6 到 15 天，每天一格**（24 小時窗），不給幾點；0–5 天的燈號照舊
4. 網頁顯示門檻：任一套 49 節比例 ≥ **20%** 那天才顯示（網頁 HW22 判斷；資料端**每天每個機場都存**，之後對照準不準）
5. 不給 AI、不參與 AI 評論與投票

## 1. 怎麼算

- **窗**：三套用同一組 24 小時窗，對齊歐洲系集機率產品的窗（00Z 起報的提前 120–144、144–168…336–360 小時，也就是第 6–15 天的 UTC 00Z–24Z）；
  網頁怎麼標日期由 HW22 決定，資料端每窗給 `from`／`to`（UTC）
- **歐洲系集**：開放資料的 `10fgg15`（≥ 15 m/s ≈ 29 節）、`10fgg25`（≥ 25 m/s ≈ 49 節），延長到 360 小時（先確認開放資料的 ep 產品真的到 360 小時、每 12 小時一窗，只取上面那 10 個窗）。
  取機場最近格點，同現在 `p29Kt`／`p49Kt` 的做法
- **GEFS**：31 個成員（控制＋30 擾動），只下載需要的欄位（`.idx` 分段）。有 `GUST` 就用陣風；沒有就用 10 米風 × 機場的 G（同 AI 模式的估算，標 `estimated: true`）。
  每個成員每窗取格內最大，數 ≥ 49／29 節的成員比例。解析度、步長（0.5° 到 384 小時？）以 NOAA 實際檔案為準，PR 說明寫清楚
- **WN2**：Open-Meteo 系集 API、同現在的模型代號，`forecast_days` 拉到 15（或只抓第 6–15 天，看 API 能不能），10 米風 × G、每成員每窗最大，數比例；
  **一天只抓一次**，估一次的加權呼叫數，加上現在每天約 1,600 次，要明顯低於 5,000（PR 說明列算式）
- 起報：每套取最新完整的 00Z（或最近的）起報，各自記 `run`

## 2. 跑在哪裡

- **不放進 build**（預算已經 1,910 秒）：新 workflow（例如 `longrange.yml`），**每天一次**，排在三套 00Z 都發布之後（時間你查發布表決定），
  也可以手動觸發；Cloudflare Worker 不用改（GitHub cron 就好，PR 說明寫你選的時間）
- 失敗一套就那套 `null`、其他照出；整個失敗沿用上一份並標 `stale`

## 3. 輸出

- GitHub Pages 發布 `longrange.json`（只放最新一份），`data` 分支 `history/longrange/<YYYY-MM-DD>.json` 每天存一份：

      {"schema": 1, "generatedAt", "runs": {"ifsEns", "gefs", "wn2Ens"}, "sources": {<各套 ok／error>},
       "windows": [{"from", "to"} × 10],
       "airports": {"<ICAO>": [{"from", "to",
           "ifsEns": {"p29", "p49", "members": 51},
           "gefs": {"p29", "p49", "members": 31, "estimated": bool},
           "wn2Ens": {"p29", "p49", "members": 64, "estimated": true}} × 10]}}

  比例 0–1、缺的套是 `null`；51 個機場都寫
- README：新來源 GEFS 的出處與授權（NOAA 公有領域）、`longrange.json` 格式、Open-Meteo 用量的新算式
- Duado 的同網域轉送（`functions/hongthai/`）要加 `longrange.json` 的話，PR 說明寫出來，我請 Duado 總指揮處理

## 測試

各套的解析（手造 GRIB／JSON fixture，沿用現有工具）、比例計算（含估算陣風）、窗對齊、一套失敗其他照出、沿用上一份標 `stale`、`latest.json` 完全不變、
Open-Meteo 用量估算

## 回報時要附

- 三套實際能拿到的範圍（到幾小時、步長、有沒有陣風）、每天下載量與耗時、Open-Meteo 加權呼叫數
- 實跑一次（今天 00Z）：任一套 49 節比例 ≥ 20% 的機場與日期（**11/9–11/11 前後的台灣、華南、港澳機場特別看一下**——Shawn 10/27 在 Windy 看到 EC 那報
  11/10 北部灣有颱風＋東北季風）
- 和提示詞不一樣的地方與理由

本機 `ruff check .`、`ruff format --check .`、`pytest -q` 全過才推，盡量一次推完。
開 PR 之後：`gh pr checks --watch` 等 CI，紅了自己修並推到同一個分支（最多三輪），全綠時告訴我；
不要自己合併，我會先請主對話審查。
