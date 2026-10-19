# HD6：AI 短評的用字規則（白話、四語語系規則、不出現內部代號）＋ 用字檢查

模型：Opus，強度中。只改 `src/hongthai/ai/prompt.py`（系統提示）、`src/hongthai/ai/parse.py`（檢查）、`ai/config.py`
（代碼清單）與測試、README；不碰呼叫流程、欄位、預算。

先讀 `docs/prompts/2026-10-19-HD5-ai-duel.md`、`src/hongthai/ai/prompt.py`（`SYSTEM`、`airport_text`）、
`src/hongthai/ai/parse.py`、`tests/test_ai.py`。

## 用字規則（產品負責人 2026-10-19 定案，全部寫進系統提示）

1. **不出現內部代號**：`p29Kt`、`p49Kt`、`EC`、`GFS`、`HRES`、`TAF`、`METAR`、`crosswindKt`、`gustKt`、`basis`、
   `agreement` 這些欄位名或縮寫都不要寫在短評裡。改成白話：
   - 「歐洲模式」「美國模式」（EC／GFS）
   - 「陣風超過 49 節的機率 56%」（p49Kt 56%）、「陣風超過 29 節的機率 …」（p29Kt）
   - 「機場預報（TAF）」第一次出現時可以括號附原名，之後只寫「機場預報」；「機場觀測」（METAR）同樣處理
   - 「側風」「陣風」「平均風」直接用中文
   - 數字照抄資料，不准自己估
2. **四語照 Duado 的語系規則**：
   - zh-TW 用台灣用語
   - zh-HK 用**書面語加香港用語**，不用粵語口語（不寫喺、同、啱啱、嘅、咗、嚟）。詞彙對照（Duado 的對照表，這裡列
     短評會用到的）：颱風警報→颱風信號／熱帶氣旋警告信號、機場預報→機場預報、陣風→陣風、停飛→停飛、
     航班→航班、飯店→酒店、計程車→的士、公車→巴士、早上／晚上→上午／晚上
   - zh-CN 用簡體加大陸用語：颱風→台风、航班取消／停飛→航班取消（但整段的叫法見第 4 點）、側風→侧风、
     陣風→阵风、機場預報→机场预报、信號→信号、節→节
   - en 用自然英文（gusts、crosswind、typhoon signal、airport forecast (TAF)）
   - **內容四語完全一樣，只換用語，不增不減**
3. **不寫英文等級字**：不出現「高（high）」這種寫法；等級用該語言的字——中文「低／中／高」，英文「Low／Medium／High」
4. **一致的叫法**：中文三語統一叫「停飛風險」（zh-CN「停飞风险」），不要一則寫「停飛」、一則寫「航班取消」；
   英文統一 "disruption risk"（不要一下 cancellation 一下 suspension）

## 要做的事

### 1. 系統提示（`prompt.py` 的 `SYSTEM`）

把上面四條逐條寫進去，放在現有「規則」之後，標題「用字」；附上面的對照表（zh-HK、zh-CN 各自那幾組）。
現有規則 1–7 不動（只用給的數據、不估機率、節、三選一、60–120 字、四語一樣、只回 JSON）。
`airport_text` 給模型看的數據**維持**用代號（p29Kt 這些是數據標籤，模型要看懂），但在數據最後那段「說明」裡
加一行：「短評裡請用白話，不要照抄上面的欄位名」。

### 2. 用字檢查（`parse.py`，新代碼 `bad_wording`）

`parse_response` 通過格式檢查後，再做用字檢查，不過就丟 `AiError("bad_wording", "<哪一語、哪個詞>")`，
呼叫端照 `error` 處理（不採用、不重試、記 `status: "error"`、`error: "bad_wording"`）：

- 四語任一語出現內部代號（大小寫不分、整字比對，避免 "TAFF" 之類誤判；`TAF`／`METAR` **允許**出現在括號裡
  一次，例如「機場預報（TAF）」「airport forecast (TAF)」，第二次以上才算違規）：
  `p29Kt`、`p49Kt`、`p37Kt`、`p10`、`p15`、`p25`、`HRES`、`GFS`、`EC`（整字）、`crosswindKt`、`gustKt`、`hresGustKt`、
  `basis`、`agreement`、`slots`、`latest.json`
- 中文三語出現「（high）」「（medium）」「（low）」或「(high)」這類英文等級字
- zh-HK 出現粵語口語字：喺、嘅、咗、嚟、啱啱、唔、佢、冇、咁
- zh-CN 含繁體常見字（抽查幾個：颱、風、機、場、預、報、節、側、陣 的繁體形）→ 違規；zh-TW、zh-HK 含簡體常見字
  （台风的「风」、机、场、预、报、节、侧、阵）→ 違規
- 中文三語同時出現「停飛」和「航班取消」兩種叫法 → 違規（任一語內）

代碼清單與訊息集中在 `ai/config.py`（`FORBIDDEN_TOKENS`、`CANTONESE_CHARS` 等），之後要加詞只改那裡。
`bad_wording` 加進 `sources.ai.errors` 可能出現的代碼；README「AI 對決」那節補一段「用字規則與檢查」。

### 3. 測試（`tests/test_ai.py`）

- 系統提示含四條用字規則與對照表的關鍵詞（例如「歐洲模式」「不用粵語口語」「停飛風險」）
- `parse_response`：合格的四語短評通過；各種違規各一個案例（代號、`TAF` 第二次出現、英文等級字、粵語字、
  簡繁混用、叫法不一致）→ `bad_wording`，訊息指出哪一語哪個詞
- 既有的 `bad_format` 案例照舊

### 4. 文件

- README「AI 對決」補用字規則（四條）與 `bad_wording`；`docs/ORCHESTRATOR.md` 第四階段那條加一句「短評用字規則
  見 HD6」

## 回報時要附

- 更新後的 `SYSTEM` 全文
- 用一份 Pages 上的 `latest.json`（本機沒金鑰，所以用假的回應）跑 `parse_response` 的合格與違規各一個例子

本機 `ruff check .`、`ruff format --check .`、`pytest -q` 全過才推，盡量一次推完。
開 PR 之後：`gh pr checks --watch` 等 CI，紅了自己修並推到同一個分支（最多三輪），全綠時告訴我；
不要自己合併，我會先請主對話審查。
