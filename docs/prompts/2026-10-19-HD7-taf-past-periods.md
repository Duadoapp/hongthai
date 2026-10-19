# HD7：規則燈不再把「產出時間之前就結束」的 TAF 時段算進第一格；en 短評不能有中日文字

模型：Opus，強度高。改 `src/hongthai/assess.py`（等級規則）、`src/hongthai/ai/parse.py`／`config.py`（用字檢查）、測試、
README。`latest.json` 既有欄位不改名、不改型別、不加欄位。

先讀 `docs/ORCHESTRATOR.md`「已知的保守假設」、`src/hongthai/assess.py`（`taf_for_slot`、`assess_slots`、開頭 docstring）、
`src/hongthai/sources/taf.py`（`TafPeriod`）、`tests/test_assess.py`、`docs/prompts/2026-10-19-HD6-ai-wording.md` 第 2 節。

## 1. 已經過去的 TAF 時段不算（Shawn 2026-10-19 從關島看到）

實例：2026-10-19T03:57Z 那報（關島當地 13:57），GUM 第 1 格（00–06Z）判 `high`，依據是 TAF 的 TEMPO 當地 12–13 時
陣風 46 節；但那一小時在產出時已經過了，13:54 的 METAR 只有 11 節、陣風 19 節。Claude 因此判低，預覽圖卻掛著
「最高：高 10/19 10–16 時」。

改法（定案）：
- `taf_for_slot` 只算**在 `now` 之後還有效**的時段：`p.end > now`（主時段、TEMPO、BECMG、PROB 都一樣）。
  第一格裡已經結束的 TEMPO 不算；跨過 `now` 的時段照算（它還沒結束）
- `taf_for_slot` 要多吃 `now`（`assess_slots` 已有），簽名改了就把呼叫端一起改
- 一格裡全部 TAF 時段都已經過了（只會發生在第一格）：`official` 照現有「只有 METAR／警報」的路，METAR 側風規則不變
  （觀測 3 小時內、且該格本來有官方資料），警報照舊
- 模式層不動

**對歷史紀錄的影響**（寫進 README「已知的保守假設」與 ORCHESTRATOR）：
- 只影響**第一格**（`now` 所在的那格）的 `official` 與 `level`；`history/*.json` 既有的檔案不重算、不改
- 之後回看戰績（`history/ai/`、`history/cancellations/`）時，HD7 合併前的第一格可能偏高；戰績檔的 `run` 時間在
  HD7 合併時間之前的，第一格要打折看。請在 `docs/ORCHESTRATOR.md`「已知的保守假設」寫一行「2026-10-19 HD7 前的
  第一格官方層可能含已過去的 TEMPO」，並把 HD7 合併的 `generatedAt` 留白讓主對話補
- 分享預覽圖、AI 候選（「等級有變」）會跟著第一格變：HD7 合併後第一次 build，很多機場的第一格會從中／高變低而
  被選進 AI（`changed`），**那一報可能撞 `run_cap`**，是預期的、一次性的

測試：`tests/test_assess.py` 加——第一格有一段已過去的 TEMPO 46 節 → 不算、等級照其他時段；跨過 `now` 的 TEMPO →
照算；主時段已過去但 TEMPO 還沒 → 只算 TEMPO；一格全部過去 → `official` 只剩 METAR／警報。用關島這個實例的數字
當 fixture（TAF 原文在 `data` 分支 `history/raw/2026-10-19/0357Z-taf.json`，只抄 PGUM 那段）。

## 2. 用字檢查再加一條：en 短評不能出現中日文字

實例：GUM（Claude）的英文短評寫成「10/19 12–13 時」。

- `parse.py` 的 `bad_wording` 加：`en` 裡出現任何 CJK 字（Unicode 範圍 `　–ヿ`、`㐀–䶿`、`一–鿿`、
  `＀–￯` 的全形標點與字母）→ `bad_wording`，訊息「en 含中日文字」
- 系統提示「用字」那段加一句：英文短評的時間寫法用 `10/19 12:00–13:00` 或 `12–13 h local`，不寫「時」
- 測試：GUM 那則英文短評（在 `history/20261019T0357Z.json`）當案例；一則合格的英文通過
- 如果 HD6 已經先做了這條（看 `parse.py` 有沒有 CJK 檢查），這節只補測試案例

## 3. 文件

- README「怎麼算」官方那列補「只算產出時間之後還有效的 TAF 時段」；「已知的保守假設」補第 1 節的影響說明
- `docs/ORCHESTRATOR.md`「已知的保守假設與待校準的參數」同步；「AI 對決」那條補 en 不能有 CJK

## 回報時要附

- 用 `history/20261019T0357Z.json` 的 PGUM 重算第一格：改前 `high`、改後應是什麼，附依據
- 五個機場（`data` 分支最近一份）第一格改前改後的等級差異表

本機 `ruff check .`、`ruff format --check .`、`pytest -q` 全過才推，盡量一次推完。
開 PR 之後：`gh pr checks --watch` 等 CI，紅了自己修並推到同一個分支（最多三輪），全綠時告訴我；
不要自己合併，我會先請主對話審查。
