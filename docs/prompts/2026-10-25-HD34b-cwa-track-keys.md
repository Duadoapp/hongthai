# HD34b：氣象署颱風路徑的鍵名對不上、編號和日本氣象廳差一號——修 `parse_cwa` 與配對

模型：Sonnet，強度中。只動 `typhoons.json`（`latest.json` 不動），**修好 CI 綠、主對話審過就合併**。

## 發生什麼事（主對話 2026-10-25 22:00 查 13:06Z 那報）

`typhoons.json` 裡薔琵（Champi）標 `source: "jma"`，`others` 是氣象署 `ty30`、`issuedAt: null`；`outOfRange` 有一筆 `2629`（`cwa`）。
拿 `data` 分支的原始回應 `history/raw/2026-10-25/1306Z-cwa-typhoon.json` 對過，兩個問題：

1. **鍵名猜錯，氣象署每顆都解析不到任何位置與時間**。實際格式（`records.TropicalCyclones.TropicalCyclone[]`）：
   - 每顆：`Year`、`TyphoonName`（英文，`CHAMPI`、`IN-FA`）、`CwaTyphoonName`（中文）、`CwaTdNo`、`CwaTyNo`
   - `AnalysisData.Fix[]`：`DateTime`（`2026-10-25T14:00:00+08:00`）、`CoordinateLongitude`、`CoordinateLatitude`、`MaxWindSpeed`、
     `MaxGustSpeed`、`Pressure`、`MovingSpeed`、`MovingDirection`（暴風半徑的鍵以原始檔為準）
   - `ForecastData.Fix[]`：`InitialTime`、`ForecastHour`、`CoordinateLongitude`、`CoordinateLatitude`、`Circle15ms.Radius`、
     `Radius70PercentProbability`（`Circle25ms` 等以原始檔為準；`result.fields` 有完整欄位清單）
   - 程式找的是 `fix_time`、`coordinate`、`init_time`、`tau`、`circle_of_15ms`、`radius_of_70percent_probability`，`_get` 的正規化
     （拿掉 `_`、小寫）對不上 → 所有 `Fix` 被丟掉
2. **氣象署的颱風編號不等於國際編號**：氣象署 `CwaTyNo` 薔琵 29、烟花 30；日本氣象廳薔琵 2630、烟花 2631。`same_storm` 第 1 條「兩邊都有
   編號就只比編號」把**氣象署烟花（2630）配給日本氣象廳薔琵（2630）**，氣象署薔琵（2629）沒配到、又沒位置 → `outOfRange`。
   現在畫出來的內容剛好都是日本氣象廳的、沒畫錯，但來源規則（曾進台灣附近就用氣象署）完全沒作用

## 要做

- `parse_cwa` 照實際鍵名解析（舊的猜測鍵名可以留著當別名）；`fix_time`→`DateTime`、座標用兩個欄位、預報時間＝`InitialTime`＋`ForecastHour`
- **配對**：氣象署的 `CwaTyNo` 不是國際編號——`number`（`id`）不要再用 `year`＋`CwaTyNo` 組；`same_storm` 改成**英文名優先**（`TyphoonName`
  對日本氣象廳英文名，同現在的名稱正規化），兩邊都沒英文名才用位置＋時間；`id` 的規則（沒有國際編號時怎麼給）在 PR 說明寫清楚，
  網頁（HW15）只拿 `id` 當鍵，**格式不能變成網頁認不得的**（照現有的字串型態）
- 模組說明（`typhoons.py`、`sources/typhoon.py`）照實際格式改寫，拿掉「`cwb_ty_no` 和國際編號同號」
- 上一份 `typhoons.json` 裡錯配的那筆（`others` 是 `cwa ty30` 的薔琵）不能讓 `_previous_entry` 把烟花認成薔琵：確認新的配對下
  上一份的錯誤 `others` 不會造成沿用錯顆（必要時 `_previous_entry` 也只認英文名或 `id`）

## 測試

- **用真的回應當 fixture**：`history/raw/2026-10-25/1306Z-cwa-typhoon.json` 與同一報的 `1306Z-jma-typhoon.json`（`data` 分支，政府開放資料，
  沒有金鑰；太大就裁成兩顆、各留幾個點，裁法寫在 fixture 旁）
- 用這組實跑：薔琵 `source: "cwa"`（過去路徑進過 `TAIWAN_NEAR`）、`others` 是日本氣象廳薔琵；烟花 `jma`（沒進過台灣附近）、`others` 是氣象署烟花；
  `outOfRange` 沒有東西（兩顆都在範圍內的話）；`issuedAt` 不是 null
- 原本手造 fixture 的測試照過；上一份有錯配那筆時的沿用

## 回報時要附

- 用 13:06Z 那組原始檔實跑出來的 `typhoons.json` 兩顆的 `id`、`source`、`others`、`issuedAt`、過去路徑點數、預報點數
- `id` 規則與和提示詞不一樣的地方

本機 `ruff check .`、`ruff format --check .`、`pytest -q` 全過才推，盡量一次推完。
開 PR 之後：`gh pr checks --watch` 等 CI，紅了自己修並推到同一個分支（最多三輪），全綠時告訴我；
不要自己合併，我會先請主對話審查。
