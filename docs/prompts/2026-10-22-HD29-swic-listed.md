# HD29：中國氣象局、韓國氣象廳、PAGASA 官方警報經 WMO SWIC 接入——只列出、不升級（凍結前上線）

模型：Opus，強度高。**10/22 12:00（台灣）凍結前合併**。新來源 `src/hongthai/sources/swic.py`、`build.py`（接來源、`BUDGET_S["swic"] = 45`、
`collect_warnings`、頂層每個機場加 `warningSources`）、`airports.json`（三國 21 個機場的對應欄位與 `warningSources`）、`config.py`、`assess.py`
（種類集合）、測試、README、`docs/ORCHESTRATOR.md`。**等級規則、投票、門檻都不動：新種類一律 `level: "low"`（只列出）**，任何一格的
`level`、`causes` 都不會因為這支改變。`latest.json` 只加值與一個新欄位（見第 4 點）。

先讀 **`docs/surveys/2026-10-22-cap-warnings.md` 全文**（HD28 調查報告：SWIC 的 `json/wmo_all.json`、各則 CAP 的網址、`mid` 代碼、中國 `id`
前碼、韓國多邊形、菲律賓 SAME 省碼、樣本在 `docs/surveys/samples/2026-10-22-cap/`、第 5.2、5.3 節的做法與 kind 命名）、`sources/nws.py`（同一機場
同一種取最新那筆的寫法）、`sources/jma.py`、`sources/cwa.py`（`ActiveWarning`、四語 `text`、原文存檔）、`assess.py` 的種類集合與「低的警報不撐起
官方層」、`build.py` 的 `_call`／`BUDGET_S`／`timing`／`collect_warnings`、`docs/ORCHESTRATOR.md`「29W 驗證期凍結」。

## 定案（Shawn 2026-10-22 02:21，全照主對話建議）

1. 現在先做「只列出、不升級」，12:00 前上線；等級 29W 報告後再定（調查報告 5.3 節的等級建議先不用）
2. `warnings[].source` **分開標**：`"cma"`（中國氣象局）、`"kma"`（韓國氣象廳）、`"pagasa"`（菲律賓 PAGASA）；`text` 與網頁寫「中國氣象局（經 WMO SWIC）」
   這類；`sources.swic` 是來源執行狀態（一個）
3. 中國用**縣級**代碼對機場（`geocode` 前 6 碼；地市、省級代碼也算涵蓋）
4. 菲律賓**走 SWIC**（PAGASA 原始 feed 之後當備援，這支不做）
5. 帛琉**不接**；越南不接

## 1. 來源（`sources/swic.py`）

照報告 5.2 節：
- GET `https://severeweather.wmo.int/json/wmo_all.json`（一次），只留三國的 `mid`；`event` 白名單篩種類（第 2 點）；中國再用 `id` 前碼篩到我們機場的地市
- 剩下的逐則抓 CAP（`https://severeweather.wmo.int/v2/cap-alerts/<url>`），同一個 URL 一報只抓一次，可平行（最多 4 條）；`status` 是 `Actual`、`msgType`
  不是 `Cancel`、`expires` 在產出時間之後才算；中國解除電文（headline 含「解除」／"lifts"）不算；同一機場同一 kind 取 `sent` 最新的
- 對機場：中國 `cmaAreas`（縣級 6 碼，地市、省級前綴也算）；韓國用 CAP `<polygon>` 對機場座標加 5 公里緩衝；菲律賓 `psgcAreas`（SAME 省碼）——代碼由雲端照
  報告第 2.3 節的表填進 `airports.json`，**每個機場的代碼寫進 PR 說明讓主對話核對**（尤其 SWA）
- `User-Agent` 寫 HongThai 與 repo 網址；`wmo_all.json` 逾時 20 秒、每則 CAP 10 秒；失敗只記 `sources.swic.ok: false`，其他來源與整報不受影響
- 原文存 `history/raw/<日期>/<時間>-swic.json`（`wmo_all.json` 三國摘錄＋抓過的 CAP 原文）
- `BUDGET_S["swic"] = 45`；預算總和若超過 `build.yml`「產生 latest.json」那步的 32 分鐘，那步加 1 分鐘、job 加 1 分鐘（寫進註解）

## 2. 種類（照報告 5.3 節的 kind 命名，**全部 low**）

- 中國：颱風 紅／橙／黃／藍（`cma_typhoon_<顏色>`）、大風 紅／橙／黃（`cma_gale_<顏色>`，藍色不收）、暴雨 紅／橙（`cma_rainstorm_<顏色>`）、大霧 紅／橙（`cma_fog_<顏色>`）
- 韓國：颱風警報／注意報（`kma_typhoon_warning`／`_advisory`）、強風警報／注意報（`kma_strong_wind_*`）、豪雨警報（`kma_heavy_rain_warning`）、
  大雪警報（`kma_heavy_snow_warning`）；`event` 的實際寫法（"StrongWind Advisory Change" 之類，含 Issue／Change／Release）照樣本核對，Release 不算
- 菲律賓：風球 #1–#5（`pagasa_tcws_<n>`）、豪雨紅色（`pagasa_rainfall_red`，`event` 寫法待確認，沒有樣本就先接照文件猜的、註明）
- 類別：暴雨、豪雨 → `RAIN_WARNING_KINDS`；大霧 → `FOG_WARNING_KINDS`；大雪 → `SNOW_WARNING_KINDS`；其他 → `wind`（現有規則）
- **四語 `text`**：
  - 中國：CAP 的 `zh-CN` info 的 headline 當 zh-CN；zh-TW、zh-HK 用 OpenCC 轉（`s2twp`、`s2hk`；依賴寫進 `pyproject.toml`，用純 Python 的套件或有 wheel
    的，CI 跟著裝）；en 用 CAP 的 `en-US` info 的 headline；每語結尾加「（中國氣象局，經 WMO SWIC）」／"(CMA via WMO SWIC)"
  - 韓國、菲律賓：中文三語用固定句型（例「韓國氣象廳強風注意報（濟州）」「菲律賓 PAGASA 熱帶氣旋 2 號風球（巴丹群島）」，zh-CN 簡體），en 用 CAP 的英文
    headline；結尾同樣標「經 WMO SWIC」
- `detail` 放原文 headline；`issuedAt` 用 CAP `sent`

## 3. 授權與標示

README「資料來源」加 WMO SWIC（香港天文台代 WMO 經營）：使用須知原文「The information is free for re-use by media or other websites.」與「要註明由相應
機關發布」；中國、韓國、菲律賓各自的發布機關名；「SWIC 沒有不代表官方沒發」那句也寫進 README。

## 4. `latest.json` 加 `airports[].warningSources`（新欄位，只加不改）

每個機場一個字串陣列，照 `airports.json` 的 `warningSources`（現有的 `cwa`、`hko`、`smg`、`nws`、`jma`，加這支的 `cma`、`kma`、`pagasa`；沒接的是 `[]`）。
網頁 HW12 現在用 ICAO 前兩碼推，之後改讀這個欄位（Duado HW13）。三國 21 個機場的 `official.warnings` 從 `false` 變 `true`。

## 5. 測試與文件

- `tests/test_sources_swic.py`：用 `docs/surveys/samples/2026-10-22-cap/` 的真實樣本做 fixture（`wmo_all` 三國摘錄、溫州大風黃、廣德大霧黃、韓國強風注意報 Change、
  菲律賓 2 號風球）：篩種類、對機場（溫州 WNZ 中、不在範圍的不中；韓國多邊形；菲律賓省碼）、過期與 Cancel 與解除不算、同 kind 取最新、四語 `text`（OpenCC 轉換後
  的繁體）、全部 low；網路失敗 → `ok: false`、整報照出
- `tests/test_assess.py`：新種類 low 的格與沒有警報時完全一樣（同 HD27 的鎖）
- `tests/test_build.py`：`airports[].warningSources` 每個機場都有、內容對；`sources.swic`；三國 `official.warnings: true`
- 用今天實際的 `wmo_all.json` 跑一次，回報 21 個機場各列出哪些警報
- README「怎麼算」警報那列、「輸出」補 `warningSources` 與三個 `source`；ORCHESTRATOR 凍結段補「HD29 只列出、不改等級」

## 回報時要附

- 21 個機場的對應代碼（cmaAreas／psgcAreas／韓國用多邊形）
- 今天實跑：每個機場列出的警報、`sources.swic` 秒數與抓了幾則 CAP
- 和提示詞不一樣的地方

本機 `ruff check .`、`ruff format --check .`、`pytest -q` 全過才推，盡量一次推完。
開 PR 之後：`gh pr checks --watch` 等 CI，紅了自己修並推到同一個分支（最多三輪），全綠時告訴我；
不要自己合併，我會先請主對話審查。
