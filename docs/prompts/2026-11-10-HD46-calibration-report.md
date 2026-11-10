# HD46：回測校準報告——燈號等級對實際取消／延誤

模型：Opus，強度高。**只新增** `tools/calibration_report.py`、`tests/test_calibration_report.py`、`report/calibration-2026-11.md`／`.json`，README 加一小段用法。
**不改 `assess.py`、門檻、任何每報的輸出**（要不要調門檻是 Shawn 看完報告後決定）。同時在跑的 HD44、HD45、HD47 的檔不要碰。

先讀：`docs/ORCHESTRATOR.md`（等級叫「風險」不叫「機率」、航班統計 H6／HD32／HD38、29W 報告的做法）、`tools/report_29w.py`（可以借讀檔與統計的寫法，
但不要改它）、`report/29W.md`、`src/hongthai/cancellations.py`、`flights_log.py`、README「輸出」裡 `history/` 的說明。`data` 分支用
`git fetch --depth 1 origin +refs/heads/data:refs/remotes/origin/data` 後 `git worktree add` 取出（很大，不要 clone 全部歷史）。

## 問題

從 2026-10-18 起每報的快照都在 `data` 分支 `history/<時間>Z.json`，每 6 小時格的實際取消／延誤統計在 `history/cancellations/`（HD38 起另有逐班的
`history/flights/`、`history/tdx/`）。要回答：**我們說「高／中／低」的時候，實際上各有多少比例真的大量取消或延誤？**

## 報告內容（`python -m tools.calibration_report --archive <data> --from 2026-10-18 --to <日期> --out … --json …`）

1. **資料盤點**：期間、幾報、幾個機場有航班統計、每個機場有效的格數；沒有航班資料的機場列出來（不算）
2. **事件定義**（至少三種門檻並列，不要只挑一個）：一格內取消率 ≥ 10%／25%／50%（分母是那格的表定班次；班次少於 N 的格另列或排除，N 你定、寫明）；
   另算「取消＋延誤 ≥ 60 分鐘」的版本（有延誤分鐘資料的機場）
3. **校準表**：綜合等級（低／中／高，另分「已確認」）× 提前時間（0–24／24–48／48–72／72–96／96–120 小時）→ 格數、事件發生的比例（附 Wilson 95% 區間）、
   命中／誤報／漏報；每個等級「說了高，結果有事件」的比例是重點
4. **分原因**：風、雨、雪、霧各自（`causes`）；29W 期間與非颱風期間分開（非颱風期間事件很少，照實寫樣本數）
5. **分層**：官方層（TAF／警報）對模式投票層；AI 燈（Claude、Gemini）各自的校準（只算等級）
6. **分機場**：樣本夠的機場各一列；明顯偏高或偏低的點出來
7. **限制**（寫在最前面）：只有三週多、只有一個颱風、取消不一定是天氣造成（沒有原因資料）、各機場航班資料來源與起始日不同（H6、HD32、HD38）
8. **不要下「該把門檻改成多少」的結論**；最後一節只列「值得 Shawn 看的現象」，每條附數字

## 規則

- WN3：2026-10-30 起有投票，但快照裡本來就沒有它的數值；報告只用 `latest.json` 快照與航班統計，**不讀私人 bucket**
- 純讀、只用標準函式庫（可用 numpy 若 `requirements.txt` 已有）；跑一次在幾分鐘內
- 同一個有效時段被很多報預報過：照提前時間分桶後，每個（機場、格、提前時間桶）取最靠近桶中間的一報，避免同一事件被重複算很多次；做法寫進報告
- 把這次實際跑出來的報告 commit 進 `report/`（Markdown 與 JSON），報告開頭註明資料截止時間與 commit

## 測試

用小的假 `history/` 目錄：等級與事件的對表、分桶與去重、Wilson 區間、沒有航班資料的機場被排除、班次太少的格的處理

## 回報時要附

- 報告的重點（五條以內）與你覺得最不可靠的地方
- 和提示詞不一樣的地方

本機 `ruff check .`、`ruff format --check .`、`pytest -q` 全過才推，盡量一次推完。
開 PR 之後：`gh pr checks --watch` 等 CI，紅了自己修並推到同一個分支（最多三輪），全綠時告訴我；
不要自己合併，我會先請主對話審查。
