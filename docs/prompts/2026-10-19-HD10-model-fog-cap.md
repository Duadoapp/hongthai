# HD10：模式層的霧（GFS 能見度）最高只到「中」

模型：Opus，強度中。HD8 的後續、改動小：只改 `src/hongthai/assess.py`（模式層 fog 的規則）、`src/hongthai/config.py`
（門檻說明）、`src/hongthai/ai/prompt.py`（給模型看的規則說明那段）、測試、README、`docs/ORCHESTRATOR.md`。
`latest.json` 欄位不改名、不改型別、不加欄位；官方層（TAF／METAR）的霧規則不動。

先讀 `src/hongthai/assess.py` 開頭「新天氣種類」那段與 `fog_level`、`fog_model_level`、`model_levels`、`fill_model_wx`、
`causes_from`；`tests/test_assess.py` HD8 的模式層案例；`data` 分支（`git fetch origin data`）
`history/20261019T0656Z.json`（HD8 合併後第一報）。

## 定案（Shawn 2026-10-19，產品負責人）

**只靠模式（GFS 能見度）時，`fog` 最高只到「中」，不能到「高」。** 要到「高」必須是官方層（TAF／METAR）真的有霧或
低雲幕，達到「能見度 < 400 公尺或雲底 ≤ 100 呎」。

理由：GFS 能見度不準，而且只有一個模式、沒有對照——06:56Z 那報釜山（PUS）10/20 12Z、18Z 兩格只靠 GFS 能見度 308 公尺、
幾乎沒下雨就判 high；大雨時 GFS 能見度也會被壓得很低（花蓮 HUN、台東 TTT 10/23 那幾格 76–92 公尺，同時 6 小時雨量
63–174 mm）。

## 要做的

1. `fog_model_level`（模式層）：套同一組 `fogMediumVisM`／`fogHighVisM` 之後**封頂在 `medium`**——`< 400` 也只回 `medium`。
   `slots[].model.gfs.fog` 跟著最高是 `medium`。官方層 `fog_level` 不動
2. `config.Thresholds` 的 `fogHighVisM`／`fogHighCeilingFt` 註解改成「只用在官方層；模式層的霧封頂在中（HD10）」；
   `assess.py` 開頭「新天氣種類」模式層 `fog` 那條改寫
3. `ai/prompt.py` 給模型看的規則說明（`airport_text` 最後「說明」那段、霧那一條）補「模式層的霧最高只到 medium」
4. 測試（`tests/test_assess.py`）：
   - GFS 能見度 300 公尺、沒雨 → 模式層 `fog` 是 `medium`、`model.level` 是 `medium`、`causes == ["fog"]`
     （**PUS 06:56Z 10/20 12Z 那格的數字**：GFS 能見度 308、GFS 雨 1.6 mm、EC 雨 5.2 mm、`p24hRain50` 0；改前 `high`、改後
     `medium`）
   - GFS 能見度 76 公尺、GFS 6 小時雨量 174.4 mm（**HUN 10/23 06Z**）：`rain` 自己是 `high`（≥ 60 mm）、`fog` 封頂 `medium`，
     加上風 high → `model.level` 仍 `high`、`causes` 照規則重排成 `["wind", "rain", "fog"]`（高的在前，同級 wind、snow、fog、
     rain）——寫成測試時把風的數字也放進去（那格 HRES 陣風 ≥ 48 節）
   - GFS 能見度 92 公尺、GFS 雨 40.5 mm、EC 雨 27.7 mm、`p24hRain50` 0.47（**TTT 10/24 00Z**）：`rain` 是 `medium`
     （GFS ≥ 30、系集 ≥ 30%）、`fog` `medium` → `model.level` `medium`、`causes == ["fog", "rain"]`
   - 官方層能見度 300 公尺 → 仍是 `high`（確認官方層沒被改到）
   - 既有測試：HD8 有「GFS 能見度 < 400 → high」的案例就改成 `medium`，其他一個都不能變
5. README「怎麼算」三類的表、「已知的保守假設」補一行「模式層的霧只到中（HD10）」；`docs/ORCHESTRATOR.md` 第五階段
   那條補「HD10：模式層霧封頂中」

## 回報時要附

- 用 `history/20261019T0656Z.json` 重算：PUS、HUN、TTT 三個機場改前改後的 `level` 與 `causes` 對照表（只列有變的格）；
  51 個機場裡還有哪些格因此從 high 降到 medium（列機場與格）

本機 `ruff check .`、`ruff format --check .`、`pytest -q` 全過才推，盡量一次推完。
開 PR 之後：`gh pr checks --watch` 等 CI，紅了自己修並推到同一個分支（最多三輪），全綠時告訴我；
不要自己合併，我會先請主對話審查。
