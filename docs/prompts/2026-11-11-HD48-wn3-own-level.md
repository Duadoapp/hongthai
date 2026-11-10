# HD48：公開 WeatherNext 3 自己的等級（只有高／中／低，沒有數值）

模型：Opus，強度高。動到 `latest.json`（**只加欄位**）。網頁是 Duado HW26（這支合併後開）。同時在跑的 HD49（WN3 加雨量）會改
`src/hongthai/sources/wn3.py`、`wn3report.py`、`wn3private.py`——**這支不要碰那三個檔**；兩支都會動 `tests/test_wn3_vote.py` 的話各自只加自己的測試、不重排現有的。

先讀：`docs/worklog/2026-10-28.md`（Google 第三封回信、Shawn 20:35 七條定案）、`docs/worklog/2026-11-11.md`（Shawn 11/11 定案：要顯示）、
`docs/prompts/2026-10-28-HD43-wn3-vote.md`、`assess.public_slots`、`build.hide_wn3`、`ai/prompt.py` 與 `ai/parse.py` 的 WN3 防洩漏、README「WeatherNext 3 的條款」。

## 定案（Shawn 2026-11-11 00:03）

WeatherNext 3 自己的高／低**要顯示**（10/28 的待決定，當時不顯示）。主對話照建議定的範圍（可以反悔）：

- 只公開**每格的整體等級**（`low`／`medium`／`high`，沒資料 `null`）。**不公開**分項等級（風／雨／雪／霧各自的 `levels`）、任何數值、達門檻比例
- 日本、南韓 15 個機場照舊完全沒有 WN3（不投票、沒有這筆）
- AI 評論的規則**不變**：不准寫 WN3 的數值、不准把判斷歸給 WN3、出處標「多模式綜合」；防洩漏檢查照舊
- 其餘照 HD43：未來時段的數值不能出現在任何公開的地方（`latest.json`、`data` 分支、Pages、og 圖、Actions 日誌、artifact、PR 說明、測試 fixture 的真實數值）

## 要做

1. `latest.json` 每格 `model.models[]` 的 `wn3` 那筆從 `{"id": "wn3", "valuesHidden": true}` 變成
   `{"id": "wn3", "valuesHidden": true, "level": "low" | "medium" | "high" | null}`——**只多 `level` 一個鍵**；`level` 就是它投票用的那個整體等級
   （和 `model.vote` 算的同一個值，不要另外算）。每機場檔（`airports/<iata>.json`，HD35 的 3 小時格）有 wn3 筆的地方比照
2. 頂層 `models[]` 的 `wn3` 加 `levelPublic: true`（新欄位，網頁用它判斷要不要畫等級；沒有這個欄位的舊資料照 HW24 的寫法顯示）
3. 做成設定：`config` 加一個開關（例如 `WN3_PUBLIC_LEVEL`，預設開；repo Variable 可關），關掉時輸出和現在逐位元組一樣（沒有 `level`、沒有 `levelPublic`）
4. 檢查所有用到「valuesHidden 的筆只有 id」這個假設的地方（HD43 的測試、`gap`、og、分享文字、`history` 快照、事件保存、`tools/` 的報告工具讀快照的地方）：
   多一個 `level` 不能讓它們壞掉或把 WN3 當成有數值的模式
5. README「輸出」與「WeatherNext 3 的條款」更新：公開的是整體等級；`tests/test_build.py` 更新
6. `sources.wn3.attribution` 照舊

## 測試

- 非日韓機場的 wn3 筆只有 `id`、`valuesHidden`、`level` 三個鍵，`level` 等於投票用的等級；日韓機場沒有這筆
- 整份 `latest.json`、每機場檔、`data` 分支寫出的檔沒有任何 WN3 fixture 數值、沒有 `levels`（延用 HD43 的寫法）
- 開關關掉：輸出和 HD43 一樣
- AI 防洩漏的測試照過（不改）

## 回報時要附

- 用假資料跑一次：某個非日韓機場一格的 `model`（只貼結構）
- 你檢查過的「假設只有 id」的地方清單
- 和提示詞不一樣的地方

本機 `ruff check .`、`ruff format --check .`、`pytest -q` 全過才推，盡量一次推完。
開 PR 之後：`gh pr checks --watch` 等 CI，紅了自己修並推到同一個分支（最多三輪），全綠時告訴我；
不要自己合併，我會先請主對話審查。
