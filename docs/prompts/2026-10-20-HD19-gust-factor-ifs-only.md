# HD19：估算陣風的係數 G 只用 IFS 的樣本算（GFS 樣本照存、報表照分開印）

模型：Sonnet 或 Opus 皆可，強度低。HD18 的後續、改動小：`src/hongthai/gustfactor.py`、`src/hongthai/config.py`（說明）、測試、
README、`docs/ORCHESTRATOR.md`。`latest.json` 欄位不變；`history/gustfactor/` 兩個檔的格式不變（`latest.json` 的 `n`、`nIfs`、
`nGfs` 照寫，只是 `g` 改成只看 IFS）。

先讀 `src/hongthai/gustfactor.py`（`summary`、`compute`）、`tests/test_gust_factor.py`、`tools/gust_factor_report.py`、
`docs/prompts/2026-10-20-HD18-gust-factor.md`。

## 定案（Shawn 2026-10-20 11:24，產品負責人）

HD18 首報：IFS 中位數約 1.65、GFS 約 1.27，差 0.4——`10fg` 是時段內最大陣風、`GUST` 是時間點值，定義不同已經很明顯。
不等 30 天，**現在就改成只用 IFS 的比例算 G**：每機場 30 天中位數、只用平均風 ≥ 10 節、夾 1.2～2.0、退回順序
（`airport30d` → `all30d` → `run` → `default`）都照舊，**只是樣本只取 IFS**。理由：每格看的是 6 小時內最大陣風，和 IFS `10fg`
的定義一致；颱風季不想讓 AI 模式再偏低一個月。**GFS 的樣本照樣存進 `history/gustfactor/<YYYY-MM>.jsonl`，報表照樣
IFS、GFS 分開印**，30 天後一起檢討。

## 要做的

1. `gustfactor.summary`：`g` 改成 `clamp(median(ifs))`（沒有 IFS 樣本時 None）；`n` 改成 IFS 樣本數（和門檻 40 比的是它），
   `nIfs`、`nGfs` 照寫（`nGfs` 只是備查）；`compute` 的三個門檻判斷都跟著用 IFS 的 `n`
2. `run_samples`、`append_samples` 不動（GFS 照收照存）；`tools/gust_factor_report.py` 不動（本來就分開印），只在標題加一句
   「G 目前只用 IFS（HD19）」
3. `config.py` 的註解、`history/gustfactor/latest.json` 加一個 `"source": "ifs"` 欄位（之後改回合併或改 GFS 時改這裡，網頁不用）
4. 測試：`summary` 只看 IFS（IFS 空、GFS 有 → `g` None、`basis` 退到下一層）；既有案例裡用到合併中位數的改成 IFS；門檻用
   IFS 的 `n`
5. README「怎麼算」估算陣風那段與 ORCHESTRATOR HD18 那條補「HD19 起只用 IFS，GFS 樣本照存、30 天後檢討」

## 回報時要附

- 用 `data` 分支最近一報的樣本算：全機場 IFS 中位數與 n；桃園、關島、羽田的 G 與 basis（改前合併值對照）

本機 `ruff check .`、`ruff format --check .`、`pytest -q` 全過才推，盡量一次推完。
開 PR 之後：`gh pr checks --watch` 等 CI，紅了自己修並推到同一個分支（最多三輪），全綠時告訴我；
不要自己合併，我會先請主對話審查。
