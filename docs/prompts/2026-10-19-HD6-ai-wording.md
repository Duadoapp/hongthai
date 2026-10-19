# HD6：AI 對決第一次實跑的修正（bad_format、429）＋ 短評用字規則與檢查

模型：Opus，強度高。改 `src/hongthai/ai/`（`claude.py`、`gemini.py`、`run.py`、`prompt.py`、`parse.py`、`config.py`）與測試、
README；不改 `latest.json` 欄位、不改每日 80 次上限與 180 秒預算。

先讀 `docs/prompts/2026-10-19-HD5-ai-duel.md`、`src/hongthai/ai/` 全部、`tests/test_ai.py`、`src/hongthai/og.py` 的
`lights_for`，以及 `data` 分支 `history/ai/2026-10-19.json`（`git fetch origin data` 後 `git show data:history/ai/2026-10-19.json`）
和 `history/20261019T0357Z.json`。

## 0. 第一次實跑（2026-10-19T03:57Z）的結果，先修這些

`sources.ai`：`ok: true`、62.5 秒、`calls` 各 20。但 **`bad_format` 太多：Claude 9/20、Gemini 17/20**，Gemini 另有 1 次
`http_429`。成功的：Claude 11 個（RMQ、HUN、TTT、MZG、LZN、FOC、JJN、ISG、NRT、CTS、GUM）、Gemini 2 個（TNN、MMY）。
`run_cap` 7 個（符合條件 27 個），和預估一樣，先不改。

### 0a. `bad_format` 的原因與修法（每天 80 次的上限內解決，不靠重試）

先查原因：`bad_format` 是被 `max_tokens`／`MAX_TOKENS` **截斷**，還是 JSON 外面多包了東西、或四語有缺？
請在本機用金鑰以外的方式判斷不出來的話，就從程式邏輯與兩個模型的文件推：
- Claude Opus 5.5 的思考關不掉、思考 token 算在 `max_tokens` 裡；HD5 用 `effort: low`＋1200，9/20 還是不夠
- **Gemini 4 Argon 的思考 token 很可能也算在 `max_output_tokens` 裡**（17/20 失敗、比 Claude 嚴重，很像是這個）

修法（都做）：
1. `MAX_TOKENS` 1200 → **3000**（四語短評本身約 600–900 token，剩下留給思考）；Gemini 另外在 `GenerateContentConfig`
   設 `thinking_config`：若 SDK 允許，`thinking_budget` 設 **512**（或該模型允許的最低值；不允許關就設最低），
   `include_thoughts=False`
2. **失敗時把 `stop_reason`／`finish_reason`、輸出 token 數（`usage`）記進 log 與 `history/ai/` 戰績那筆**（新增
   `"detail": "<代碼>:<stop_reason>:<output_tokens>"`，**不記內容**），下次再失敗主對話直接從 `data` 分支看得到原因
3. `parse.py` 容忍：JSON 前後有說明文字時，取第一個 `{` 到最後一個 `}` 之間再解析；仍失敗才算 `bad_format`
4. 系統提示末尾再加一句「不要在 JSON 外面寫任何字、不要加 Markdown 標記」

### 0b. Gemini 的 `http_429`

新 GCP 專案 Vertex 的配額可能很低。請查：
- 是不是 Gemini 4 條並行就撞到每分鐘請求數上限（HD5 是每個模型 4 條並行）。**Gemini 降成 2 條並行**（`config.py`
  加 `PARALLEL = {"claude": 4, "gemini": 2}`），Claude 維持 4
- 在 README「AI 對決」寫清楚要去 GCP 申請提高哪個配額（Vertex AI 的「Generate content requests per minute per project
  per base model per region」之類，寫出你在文件上查到的確切名稱與路徑），Shawn 自己去申請

### 0c. 預覽圖

`og/khh.png` 還是一顆「高」的規則燈。查 `og.lights_for`：HD5 的設計是**兩顆 AI 都不是 `ok` 時維持一顆**，高雄兩顆都
`bad_format`，所以一顆是對的、不是漏改（GUM 的 Claude 是 ok，`og/gum.png` 應該已是三顆，請確認）。不用改邏輯；
在 README「分享預覽圖」補一句「AI 兩顆都失敗時仍是一顆規則燈」。

### 0d. 用字問題（實跑抓到的，照第 2 節的規則修，並當測試案例）

- MZG（Claude）、TNN／MMY（Gemini）的短評滿是 `p29Kt`、`p49Kt`、`EC`、`GFS`
- NRT（Claude）的 zh-HK 用了「喺、同、啱啱」
- MMY（Gemini）寫「高（high）」
- TNN（Gemini）zh-CN 寫「航班取消风险」，zh-TW 卻寫「停飛風險」

這四則的實際文字在 `history/20261019T0357Z.json` 的 `airports[].ai.*.comment`，**把它們（去掉機場名以外的個資沒有，
直接用）抄進 `tests/test_ai.py` 當 `bad_wording` 的案例**。

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
     短評會用到的）：**颱風警報→颱風警告**（台灣、日本、其他地方發的都寫「颱風警告」；**只有提到香港天文台的
     熱帶氣旋警告信號時才寫「信號」**，例如「八號信號」）、機場預報→機場預報、陣風→陣風、停飛→停飛、
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
  簡繁混用、叫法不一致）→ `bad_wording`，訊息指出哪一語哪個詞；**第 0d 節那四則實跑的短評各一個案例**
- JSON 外面有說明文字時仍能解析；`MAX_TOKENS`、`PARALLEL`、`thinking_config` 的參數有送到（假 SDK 檢查）；
  戰績那筆有 `detail`
- 既有的 `bad_format` 案例照舊

### 4. 文件

- README「AI 對決」補用字規則（四條）與 `bad_wording`；`docs/ORCHESTRATOR.md` 第四階段那條加一句「短評用字規則
  見 HD6」

## 回報時要附

- `bad_format` 的原因判斷與依據（兩個模型的文件連結）、最後用的 `MAX_TOKENS`／`thinking_budget`／`PARALLEL`
- 要申請的 Vertex 配額名稱與路徑
- 更新後的 `SYSTEM` 全文
- 用一份 Pages 上的 `latest.json`（本機沒金鑰，所以用假的回應）跑 `parse_response` 的合格與違規各一個例子

本機 `ruff check .`、`ruff format --check .`、`pytest -q` 全過才推，盡量一次推完。
開 PR 之後：`gh pr checks --watch` 等 CI，紅了自己修並推到同一個分支（最多三輪），全綠時告訴我；
不要自己合併，我會先請主對話審查。
