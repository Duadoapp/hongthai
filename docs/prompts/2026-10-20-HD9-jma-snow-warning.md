# HD9：日本氣象廳（JMA）大雪警報——日本與沖繩 11 個機場接官方警報

模型：Opus，強度中。新來源 `src/hongthai/sources/jma.py`、`build.py`（接來源、`BUDGET_S["jma"]`）、`assess.py`（只加警報種類的對照，
**規則不動**）、`airports.json`（11 個機場的 JMA 區域代碼、`warningSources` 加 `jma`）、`config.py`、測試、README、`docs/ORCHESTRATOR.md`。
`latest.json` 只加值：`warnings[].source` 多 `"jma"`、`kind` 多 `jma_heavy_snow`、`jma_heavy_snow_emergency`、`jma_snowstorm`；
`sources.jma`；日本 11 個機場 `official.warnings` 從 `false` 變 `true`。硬期限：**12 月北海道下雪前**上線。

先讀 `docs/ORCHESTRATOR.md` 第五階段（第 4 點：JMA 大雪警報另開 HD9）與「29W 驗證期凍結」、`src/hongthai/sources/nws.py`
（警報來源的寫法：種類對照、四語 `text`、`ActiveWarning`、timing）、`src/hongthai/sources/hko.py`（低的警報只列出）、`assess.py` 的
`RAIN_WARNING_KINDS`／`FOG_WARNING_KINDS`／`warning_cause`、`build.py` 的 `_warnings_for`、`airports.json`。

## 定案（Shawn 2026-10-19 第五階段第 4 點；本支只做 JMA）

- JMA **大雪警報 → 中**、**大雪特別警報 → 高**，算 `snow`；暴風雪警報只列出不升級（`level: "low"`，`jma_snowstorm`，算 `snow`，
  同紅雨／雷暴的做法）；注意報（大雪注意報、風雪注意報）**不列**；大雨、暴風、波浪等其他警報**不接**（風的警報留給之後，
  而且 29W 期間不能動到風的等級——這支上線不會改變任何現在的等級，因為 10–11 月沒有大雪警報）
- 期間內（警報生效中）套到「現在 + 12 小時」以前開始的格（`WARNING_HORIZON_H`，同其他警報）
- 日本 8 個（CTS、SDJ、NRT、HND、NGO、KIX、FUK、KOJ）＋沖繩 3 個（OKA、MMY、ISG）都接；沖繩實務上不會有大雪警報，但接了
  `official.warnings` 一致為 `true`、網頁不用再寫「尚未提供」

## 1. 來源（`sources/jma.py`）

- JMA 防災 JSON（bosai，非正式但穩定、不用金鑰、公有）：
  - 區域表 `https://www.jma.go.jp/bosai/common/const/area.json`（`class20s` 是市町村代碼、`class15s`／`class10s` 往上、`offices`
    是都道府縣氣象台代碼）
  - 警報 `https://www.jma.go.jp/bosai/warning/data/warning/<office 代碼>.json`：`areaTypes[].areas[]` 每個區域（class10／class15／
    class20 各一層）的 `warnings[]`，每筆 `code`（警報種類）、`status`（發表／継続／解除／発表警報・注意報はなし）、`condition`…；
    `reportDatetime` 是發布時間。**警報種類代碼以第一次實抓與文件為準**（印象中：大雪警報 `06`、暴風雪警報 `05`、
    大雪特別警報 `33`、暴風雪特別警報 `35`、大雪注意報 `12`、風雪注意報 `13`——雲端對實際 JSON 核對後寫進程式註解，不要照抄）
- `airports.json` 每個日本／沖繩機場加 `jmaArea: {"office": "<office 代碼>", "class20": "<市町村代碼>"}`（機場所在市町村：新千歲
  千歲市、仙台 名取市、成田 成田市、羽田 東京都大田區、中部 常滑市、關西 泉佐野市（或田尻町，查機場屬地）、福岡 福岡市、
  鹿兒島 霧島市、那霸 那霸市、宮古 宮古島市、石垣 石垣市）——代碼由雲端從 `area.json` 查、寫進 PR 說明
- 每報：依 `office` 去重後**一個 office 一個請求**（11 個機場約 9 個 office），找該機場 `class20` 那一列的 `warnings[]`，
  `status` 不是解除／なし 的才算；對照成 `ActiveWarning(source="jma", kind, level, text 四語, issued_at=reportDatetime, code=<JMA 代碼>)`
- 四語 `text`：zh-TW「日本氣象廳大雪警報（千歲市）」、zh-HK 同、zh-CN「日本气象厅大雪警报（千岁市）」、en "JMA heavy snow warning
  (Chitose)"；特別警報「大雪特別警報」／"heavy snow emergency warning"；暴風雪「暴風雪警報」／"snowstorm warning"。市町村名
  用 `area.json` 的日文名（漢字直接用在三個中文，en 用 `enName`）
- 原文存 `history/raw/<日期>/<時間>-jma.json`（每個 office 的回應，一個 dict）；`sources.jma {ok, seconds}`；預算 `BUDGET_S["jma"] = 45`
  （總和 1530 → 1575 秒，`build.yml` 那步 28 分鐘夠、不用改）；失敗記 `ok: false`，其他來源不受影響

## 2. 規則對照（`assess.py`，不改規則本身）

- `SNOW_WARNING_KINDS = {"jma_heavy_snow", "jma_heavy_snow_emergency", "jma_snowstorm"}`，`warning_cause` 回 `snow`；官方層的 `snow`
  等級把這類警報算進去（同 `rain`／`fog` 的寫法）；低的警報不撐起官方層（現有規則）
- 等級：`jma_heavy_snow` medium、`jma_heavy_snow_emergency` high、`jma_snowstorm` low

## 3. 測試與文件

- `tests/test_sources_hd9.py`：用雲端抓一份真的 office JSON 當 fixture（沒有警報時也存一份），再手造一份含大雪警報、大雪特別警報、
  暴風雪、大雪注意報、已解除的：只出前三種、等級對、`class20` 對到正確的列、`text` 四語、office 去重後請求數
- `tests/test_assess.py`：大雪警報 → 第一格官方層 `snow` medium、`causes ["snow"]`；特別警報 high；暴風雪單獨不撐起官方層
- `tests/test_build.py`：日本 11 個機場 `official.warnings: true`；`sources.jma`
- README「資料來源」加 JMA（公有、非正式介面）、「怎麼算」警報那列補三種、「輸出」補 `source: "jma"` 與三個 `kind`；
  ORCHESTRATOR 第五階段補「HD9 已實作」；凍結那段補一句「HD9 只加雪的警報，29W 期間不影響風的等級」

## 回報時要附

- 警報種類代碼的實際對照（從 JSON 或文件）、11 個機場的 `office`／`class20` 代碼
- 一次實抓：9 個 office 的秒數、有沒有任何機場現在有警報（10 月應該都沒有）

本機 `ruff check .`、`ruff format --check .`、`pytest -q` 全過才推，盡量一次推完。
開 PR 之後：`gh pr checks --watch` 等 CI，紅了自己修並推到同一個分支（最多三輪），全綠時告訴我；
不要自己合併，我會先請主對話審查。
