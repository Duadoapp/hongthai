# HD24：`vote.mediumTotal` 與頂層 `models[].votesOnlyHigh`——只加兩個欄位，讓網頁寫對判「中」的分母

模型：Sonnet，強度中。**只加欄位、不改任何規則與票數**（凍結前最後一支，10/22 12:00 台灣時間前要合併）。
改 `src/hongthai/assess.py`（`model_vote`）、`build.py`（頂層 `models[]`）、測試、README「輸出」、`docs/ORCHESTRATOR.md`。

先讀 `docs/ORCHESTRATOR.md`「多模式投票」（HD14／HD16）與「29W 驗證期凍結」、`src/hongthai/assess.py` 的 `model_vote`／`_pool`／`vote`
／`ONLY_HIGH`、`config.py` 的 `Model.votes_only_high`、`build.py` 頂層 `models[]` 那行（`{"id", "name", "voting"}`）。

## 為什麼

網頁（Duado `site/hongthai/`）投票那列寫「8 個模式中 3 個認為中以上」，但判「中」時兩個只投高的系集（`ifs-ens`、`wn2-ens`）
不算分母，實際是 6 個中 3 個；`vote.total` 含系集、`vote.medium` 不含，網頁拿不到判中的分母，也不知道哪些模式只投高。
Shawn 2026-10-20 23:27 看 TPE 10/23 14–20 時那格提的（計算是對的、顯示會誤會）。

## 1. `slots[].model.vote` 加 `mediumTotal`

- `mediumTotal`：判「中」時的分母＝有風的等級、在投票（`voting`）、**不是** `votes_only_high` 的模式數（就是 `_pool(..., target="medium")`
  的長度）；整數，沒有任何模式有資料時和 `total` 一樣是 0
- `total`、`high`、`medium`、`low`、`level`、`thin` **一個字都不改**；`mediumTotal` 接在 `medium` 後面

## 2. 頂層 `models[]` 加 `votesOnlyHigh`

- 每筆多 `"votesOnlyHigh": <布林>`（`Model.votes_only_high`）：目前 `ifs-ens`、`wn2-ens` 是 `true`，其他 `false`
- `slots[].model.models[]` 每筆**不加**（網頁對頂層清單就夠）

## 3. 測試與文件

- `tests/test_vote.py`：8 票含兩個只投高的系集 → `mediumTotal` 6、`total` 8；系集缺席時 `mediumTotal` ＝ `total`；旁觀模式不算進
  `mediumTotal`；三票缺席（HD16 保險）時 `mediumTotal` 跟著少
- `tests/test_build.py`：頂層 `models[]` 每筆有 `votesOnlyHigh`，`ifs-ens`、`wn2-ens` 是 `true`
- README「輸出」補兩個欄位；`docs/ORCHESTRATOR.md` 多模式投票那條補「HD24 已實作（只加欄位）」；凍結那段補一句「HD24 只加欄位、不改票數」

## 回報時要附

- 用最近一報跑 `python -m hongthai.build` 的 TPE 10/23 06Z 與 12Z 兩格 `vote`（含 `mediumTotal`）
- `latest.json` 大小前後（應該只多幾 KB）

本機 `ruff check .`、`ruff format --check .`、`pytest -q` 全過才推，盡量一次推完。
開 PR 之後：`gh pr checks --watch` 等 CI，紅了自己修並推到同一個分支（最多三輪），全綠時告訴我；
不要自己合併，我會先請主對話審查。
