# HD11：開發期間取消 AI 的每日上限（`DAILY_CAP=0` 代表不限）

模型：Sonnet 或 Opus 皆可，強度低。改動小：`src/hongthai/ai/config.py`、`src/hongthai/ai/run.py`、`tests/test_ai.py`、
README、`docs/ORCHESTRATOR.md`。`latest.json` 欄位與錯誤代碼不變。

先讀 `src/hongthai/ai/config.py`（`DAILY_CAP`）、`src/hongthai/ai/run.py`（`_one` 裡 `self.calls[key] >= DAILY_CAP` 那段、
每日次數檔 `history/ai/calls-<日期>.json` 的讀寫）、`tests/test_ai.py` 裡 `daily_cap` 的測試。

## 定案（Shawn 2026-10-19，產品負責人）

- **開發期間取消每日上限**（每家每天 80 次那條），手動 Run workflow 也照常跑 AI。2026-10-19 手動跑太多次，兩家都在
  14:56 那報撞到 `daily_cap`，HD8 的短評改動一整天看不到
- **保留的保險不變**：每報最多 20 個機場（`MAX_AIRPORTS`）、不重試、AI 預算 180 秒、Gemini 2 條並行；Anthropic workspace
  每月 30 美元硬上限、GCP 30 美元預算警示（在平台上設，不在程式裡）
- `daily_cap` 這個錯誤代碼**留著不用**；設定改成「可以關」，之後要恢復時改一個數字就好
- 「開發期間不限、正式推廣前再評估」要寫進 README 和 ORCHESTRATOR

## 要做的

1. `ai/config.py`：`DAILY_CAP = 0`，註解寫「每天（UTC）每個模型最多呼叫幾次；**0 代表不限**（開發期間，2026-10-19 定案；
   正式推廣前再評估，恢復時改成 80 之類的數字即可）」
2. `ai/run.py`：`DAILY_CAP` 是 0（或負數）時不檢查、不產生 `daily_cap`；**每日次數檔 `history/ai/calls-<日期>.json` 照常
   累加**（之後評估要看實際用量）。模組說明那段同步
3. 測試：`DAILY_CAP=0` 時連續超過 80 次都照常呼叫、次數檔照常累加；monkeypatch 成 2 時第 3 次是 `daily_cap`（既有的上限
   測試改成這種寫法，不要刪）
4. README「AI 對決」保險那段、錯誤代碼 `daily_cap` 的說明（「目前 `DAILY_CAP=0` 不限，不會出現」）、`history/ai/calls-*`
   的說明；`docs/ORCHESTRATOR.md`「安全與隱私」裡「每天每模型 80 次」那句與第四階段「保險」那句都改成「開發期間不限
   （`DAILY_CAP=0`），正式推廣前再評估；每報 20 個機場、不重試、180 秒預算不變」

## 回報時要附

- 改後的 `DAILY_CAP` 那行與 `run.py` 判斷那段

本機 `ruff check .`、`ruff format --check .`、`pytest -q` 全過才推，盡量一次推完。
開 PR 之後：`gh pr checks --watch` 等 CI，紅了自己修並推到同一個分支（最多三輪），全綠時告訴我；
不要自己合併，我會先請主對話審查。
