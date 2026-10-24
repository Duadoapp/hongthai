# HD39：分享預覽圖換 HongThai 新品牌（風眼夜航）

模型：Sonnet，強度中。**動到每報的輸出（`og/<iata>.png`）：現在可以開 PR、跑 CI，等 10/25 16:25（台灣，08:25Z）那報寫進 history、
主對話確認後才合併**。B 組合併順序：HD33b → HD35 → HD38 → HD34 → HD39；main 有新的合併就自己 rebase、重跑檢查。只改 `src/hongthai/og.py`、
`assets/fonts/`（子集）、測試、README、`docs/ORCHESTRATOR.md`。

先讀 `src/hongthai/og.py`（HD1、HD4、HD5 的規格在 docstring）、`assets/fonts/README.md`，以及 Duado repo 的網頁新品牌（`Duadoapp/duado` 的
`site/hongthai/theme.ts`、`brand.ts`，HW8 提示詞 `docs/prompts/2026-10-21-hw8-hongthai-redesign.md`，設計稿 `docs/prompts/2026-10-21-hw8-design/`）
——用 `gh api` 讀，不用 clone。

## 1. 改什麼

- **配色**換成網頁的 token（`theme.ts`）：底 `night #0E1726`、色塊 `card #17233A`、文字 `text #E8EEF6`／`textSoft`／`textMuted`、強調 `eye #5CC8E8`；
  等級 `low #2F4263`（＋`lowEdge` 內框）、`medium #F2B84B`、`high #FF6B5A`、`confirmed`、`none`（AI error）。色碼集中在 `COLORS`／`LEVEL_COLORS`，
  註明來源是 Duado `site/hongthai/theme.ts`（兩邊要一起改）
- **品牌**：右下改成漩渦 LOGO＋「HongThai」字標＋「風颱」、下面 `duado.app/hongthai`。漩渦照 `brand.ts` 的 SVG（圓 r=7、兩條弧線，`viewBox 0 0 48 48`），
  字標用 `brand.ts` 那個 Space Grotesk Bold 外框路徑（自己把貝茲曲線攤平成多邊形畫，或改用 Space Grotesk Bold 子集字檔畫「HongThai」八個字母——
  選一種，PR 說明寫理由；Space Grotesk 是 SIL OFL 1.1，授權檔放 `assets/fonts/`）
- **字型**：中文改用 Noto Sans TC（現在已是後備字型）、數字與 IATA 用 Space Grotesk（子集，只收 ASCII）；拿掉 Fraunces、芫荽（晨光風格的字）。
  子集重做的方法寫進 `assets/fonts/README.md`
- 版面、內容（IATA 大字、機場名、燈號、三顆燈、20 格時間軸、更新時間）**不變**；等級除了顏色要有文字（燈號色塊裡照現在寫字）
- 調色盤模式＋`optimize=True`，每張 ≤ 60 KB；`_palette` 跟著新顏色重算
- 檔名、發布位置、`og:image` 網址都不變（網頁不用改）

## 2. 測試

顏色只用 token、三種燈號組合與「已確認」「資料不足」都畫得出來、檔案大小上限、字標或 LOGO 有畫上（像素抽查）

## 回報時要附

- 用 `?sample` 等級的資料畫 TPE（高）、HKG（中）、一個全低的機場三張，PNG 附在 PR（或說明怎麼在本機產生）
- 每張大小、字檔大小、和網頁設計稿不一樣的地方

本機 `ruff check .`、`ruff format --check .`、`pytest -q` 全過才推，盡量一次推完。
開 PR 之後：`gh pr checks --watch` 等 CI，紅了自己修並推到同一個分支（最多三輪），全綠時告訴我；
不要自己合併，我會先請主對話審查。
