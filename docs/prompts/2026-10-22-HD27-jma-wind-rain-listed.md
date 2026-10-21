# HD27：日本氣象廳暴風、大雨警報——只列出、不升級（凍結前上線）

模型：Sonnet，強度中。**10/22 12:00（台灣）凍結前合併**。只改 `src/hongthai/sources/jma.py`（代碼對照）、`assess.py`（種類集合）、測試、README、
`docs/ORCHESTRATOR.md`。**等級規則、投票、門檻都不動**：新加的警報一律 `level: "low"`（只列出），和香港紅雨、雷暴警告、日本暴風雪警報
同一個做法，所以任何一格的燈號都不會因為這支改變。`latest.json` 只多值（`warnings[].kind` 的新種類），不加欄位。

先讀 `src/hongthai/sources/jma.py` 檔頭（r8 格式、代碼怎麼查到的、`status` 規則）與代碼對照表、`assess.py` 的 `RAIN_WARNING_KINDS`／
`SNOW_WARNING_KINDS`／`warning_cause`／「低的警報不撐起官方層」那段、`docs/ORCHESTRATOR.md`「29W 驗證期凍結」。

## 為什麼（Shawn 2026-10-22 01:35）

颱風 29W 接近，日本氣象廳 02:30 發布的警報地圖上沖繩本島、先島是紅色（警報），但 HongThai 只接大雪類，那霸、石垣、宮古的「官方警報」寫
「目前沒有」，和官方對不上。HD9 當時刻意不接風的警報（29W 期間不能動到風的等級），所以這支**只列出、不升級**。

## 1. 代碼（`jma.py`）

照檔頭的方法（JMA 警報頁的 JS 對照表＋實抓）核對後加：
- 暴風警報（檔頭已查到 `05`）→ `jma_storm`，low
- 暴風特別警報（`35`）→ `jma_storm_emergency`，low
- 大雨警報、大雨特別警報（檔頭寫特別警報 `33`；警報的代碼與 r8 新制的「大雨危険警報」等分級，**照實際 JSON 查**，有幾種就接幾種）→
  `jma_heavy_rain`、`jma_heavy_rain_emergency`（新制若多一級危険警報，另一個 kind `jma_heavy_rain_danger`），全部 low
- 四語 `text` 照現有寫法：「日本氣象廳暴風警報（那霸市）」／"JMA storm warning (Naha)"；特別警報、大雨同理（zh-CN 簡體）
- 注意報、波浪、高潮、洪水、土砂災害**不接**

## 2. 種類集合（`assess.py`）

- 大雨類加進 `RAIN_WARNING_KINDS`（`warning_cause` 回 `rain`）；暴風類照現有「其他警報算 `wind`」
- 確認 low 的警報**不撐起官方層、不改任何一格的 `level`**（現有規則；加測試鎖住）

## 3. 測試與文件

- `tests/test_sources_hd9.py`（或新檔）：手造含暴風、暴風特別、大雨、大雨特別（＋新制危険警報若有）、注意報、解除的 office JSON：只出接的幾種、
  都是 low、四語文字、`class20` 對到正確的列
- `tests/test_assess.py`：只有暴風警報或大雨特別警報（low）的格，`level` 和沒有警報時**完全一樣**；`warnings[]` 照樣列出
- 用 `data` 分支今天（10/22）最近一份 `history/raw/<日期>/*-jma.json` 跑一次，回報沖繩三個機場會列出哪些警報
- README「怎麼算」警報那列補「日本氣象廳暴風、大雨警報只列出（low）」；ORCHESTRATOR 凍結段補「HD27 只列出、不改等級」

## 回報時要附

- 實際查到的代碼對照（含新制大雨分級）
- 用今天的原始 JSON 跑出來：OKA、ISG、MMY（與其他日本機場）各列出哪些警報

本機 `ruff check .`、`ruff format --check .`、`pytest -q` 全過才推，盡量一次推完。
開 PR 之後：`gh pr checks --watch` 等 CI，紅了自己修並推到同一個分支（最多三輪），全綠時告訴我；
不要自己合併，我會先請主對話審查。
