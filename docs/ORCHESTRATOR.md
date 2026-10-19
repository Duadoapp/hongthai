# HongThai 主對話須知

給之後接手這個 repo 的 Claude 主對話（HongThai 專用對話）讀的一頁。先讀這份，再讀 `README.md`。
這份不放任何金鑰或個資。

## 這個 repo 做什麼

用公開氣象資料，每天四次算 **51 個機場、九個地區**（台灣 10、華東 8、華南・港澳 8、沖繩 3、日本 8、
韓國 4、越南 5、菲律賓 3、關島・帛琉 2；H9 起 41 個、HD3 起 51 個，名單見 README「機場」）未來 120 小時、
每 6 小時一格的**強風停飛風險**（低／中／高），
輸出一份 `latest.json` 發布在 GitHub Pages：<https://duadoapp.github.io/hongthai/latest.json>。

- 只產資料。網頁 <https://duado.app/hongthai/> 在 Duado 的私人 repo（`site/hongthai/`），不在這裡
- 程式：`src/hongthai/`（`sources/` 各資料來源、`assess.py` 判讀、`build.py` 組 JSON 與失敗處理）
- 設定：`airports.json`（地區、機場、跑道、門檻、看哪些官方警報）、`confirmed.json`（人工填的已確認停飛）

## 和產品負責人（Shawn）合作的方式

- 回覆一律繁體中文（台灣）用語；叫他 Shawn
- 問他問題：一次最多 5 題、每題一行、附你的建議。他答完，先把「題目＋他的答案」整理成清單給他確認，
  確認後才寫進文件。還沒定案的寫進 `docs/worklog/<日期>.md` 的「待決定」（對話會被壓縮，文件不會）
- 給他的指令一律完整可貼（他用 Windows cmd）。這個 repo 幾乎沒有本機指令：部署是 Actions，
  他只在 GitHub 網頁按 Run workflow、設 Secrets
- 每個功能一個 PR。主對話寫提示詞放 `docs/prompts/<日期>-<代號>-<名稱>.md`（只放文字，不放截圖內容、
  個資、金鑰），開新的雲端對話貼「照 docs/prompts/<檔名> 做」。**編號規則（2026-10-18 定案）**：H 系列不再兩個
  repo 共用。已經命名的維持原樣、不改檔名：H1–H10（H1、H4、H6、H7 在這裡；H8 是 Duado 網頁的分地區；H9 是這裡
  41 個機場的資料端；H10 是這裡修 GFS／ECMWF 來源）。從下一支起，hongthai 這邊的提示詞用 **HD** 字頭（Data），
  從 HD1 開始自己往下排，不用再看 Duado；Duado 那邊的 HongThai 網頁用 **HW** 字頭（Web）。提到對方的工作時
  寫 HD／HW 編號。提示詞最後都要有
  「開 PR 之後：gh pr checks --watch 等 CI，紅了自己修到綠（最多三輪）」
- 主對話審 PR 不等 CI：他給號碼就審，審完回「可以合併」，他再開 auto-merge
  - 已設（2026-10-18）：`main` 的 ruleset 要求 PR、必要檢查 `ci`、禁止 force push；Allow auto-merge 已開。
    `ci.yml` 的 job 名稱就是 `ci`（必要檢查比對的是 job 名稱，不是 workflow 名稱），不要改名
  - 雲端對話用不了 GitHub GraphQL，這類操作走 REST
- 金鑰（`CWA_API_KEY`、之後 AI 評論用的 Anthropic 金鑰與 Google 服務帳號等）只由他自己放進 Actions secrets，
  不貼進對話、PR、截圖；程式只從環境變數讀

## 已經做過的決定（不要重問）

- 名稱 HongThai，只放 duado.app/hongthai/ 網頁、不進 App；網頁在 Duado 私人 repo（`site/hongthai/`），
  本 repo 只產資料
- 定位（2026-10-18）：**純資訊網頁**，不給「下一步該怎麼做」、不做通知、公開給大家看；跟 Duado App 接排到很後期。
  名字維持 HongThai，副標「機場停飛風險」，加了雨雪霧之後仍用這個名字。語言維持四語（zh-TW、zh-HK、zh-CN、en），
  不加日文、韓文；機場名稱與 AI 短評都只出這四語。網頁會做分享預覽卡與每個機場的獨立網址（Duado 總指揮排）；
  資料端要多給什麼（例如每個機場一句摘要）由那邊再提
- `latest.json` 的格式是和網頁的契約，以 Duado `docs/spec.md` 第 16 節為準：既有欄位不改名、不改型別，
  只能加；要改就兩邊同時改，先跟 Duado 的主對話說（經 Shawn 轉）
- 分階段：
  - 第一階段（PR #1）：桃園、香港
  - 第二階段（H4）：側風分跑道、松山／高雄／澳門
  - 第二階段之後的來源與統計修正（不算一個階段）：H6 航班統計、H7 來源預算、H10 GFS 鏡像與 ECMWF 瘦身
    （見 `docs/prompts/`）
  - **第三階段（2026-10-18 定案，Duado spec 第 16 節的第三階段；資料端代號 H9）：機場擴成 41 個，分六個地區**（HD3 起 **51 個、九個地區**，見下面 HD3），每個機場多一個地區欄位（網頁依此分組）：
    台灣（10）：桃園、松山、高雄、台中、台南、花蓮、台東、澎湖、金門、馬祖南竿；
    華東（8）：上海浦東、虹橋、杭州、寧波、溫州、福州、廈門、泉州；
    華南・港澳（8）：潮汕、深圳、廣州、香港、澳門、珠海、海口、三亞；
    沖繩（3）：那霸、石垣、宮古；
    日本（8）：鹿兒島、福岡、關西、中部、羽田、成田、新千歲、仙台；
    韓國（4）：濟州、釜山、仁川、金浦。
    做法：41 個先全部用全球資料上線（ECMWF、GFS、TAF／METAR、跑道側風），
    官方警報逐國補：日本先、韓國再來；中國官方颱風預警先不接。台灣機場的氣象署警戒區關鍵字每個機場一組。
    沒有官方警報來源的機場要在 `latest.json` 標出來（`airports[].official.warnings`，布林），讓網頁顯示
    「官方警報：尚未提供」。
    提示詞 `docs/prompts/2026-10-19-H9-41-airports.md`（要在 HD2 之後）
  - **HD2（2026-10-19 定案，要在 H9 之前）：風速一律用節＋新門檻**——陣風中 ≥ 37 節、高 ≥ 48 節（桃園機場空橋
    規則 37／48／55 節）、TAF 平均風 ≥ 35 節高不變；側風中 ≥ 27、高 ≥ 33 節（窄體機作業限制）；系集機率改用
    28／37／48 節的門檻（28 只當參考）；所有機場先同一套，之後個別覆寫。之後新天氣種類的單位：雨量毫米、
    能見度公尺、積雪公分。提示詞 `docs/prompts/2026-10-19-HD2-units-thresholds.md`
  - **HD3（2026-10-19 定案，排在 H9 之後）：再加三個地區、十個機場**，共 9 個地區、51 個——越南（5）：河內、
    胡志明、峴港、芽莊（金蘭）、富國島；菲律賓（3）：馬尼拉、宿霧、克拉克；關島・帛琉（2）：關島、帛琉。
    名單 Shawn 指定（台灣有定期直飛）。越南、菲律賓官方警報先不接；關島、帛琉要評估 NWS Guam 的開放資料，
    能接就接。同一支順便補石垣的跑道（OurAirports 沒有，用日本 AIP 或跑道頭座標算）。
    提示詞 `docs/prompts/2026-10-19-HD3-ten-airports-ishigaki.md`。
    做完的結果（HD3 PR）：**機場共 51 個、九個地區**；關島接 NWS（`api.weather.gov` 的
    `/alerts/active?zone=GUZ001`，Typhoon／Tropical Storm Warning → 高、Watch → 中，Shawn 2026-10-19 定案）；
    帛琉查不到 NWS 的警報（zone `PWZ001`–`PWZ008` 存在但 2026-04 起一筆警報都沒有），先不接；
    石垣跑道 04/22 用 OpenStreetMap 跑道頭座標算出真北 035.7°／215.7°（日本 AIP 沙盒連不上）
  - **HD1（Duado #374 定案，排在 H9 之後、可在 AI 對決之前）：分享預覽圖**——每報跑完用 Pillow 畫每個機場一張
    1200×630 的分享預覽圖，發布到 Pages 的 `og/<iata>.png`（iata 小寫）。內容：IATA 大字、機場名（zh-TW＋en）、
    燈號（AI 上線前一顆規則燈，上線後自動變三顆）、更新時間、HongThai 字樣。字型由 hongthai 自備（OFL 授權的
    中日韓字型放在 repo，附授權檔）；Duado 用 Pages Function 轉送這張圖。提示詞 `docs/prompts/2026-10-19-HD1-og-image.md`
    做完的結果（HD1 PR）：`src/hongthai/og.py`，網址 `https://duadoapp.github.io/hongthai/og/<iata 小寫>.png`；
    燈號＝未來 5 天最高等級＋第一個達到那級的格（當地時間，跨午夜寫兩個日期），有已確認的格時顯示「已確認」；
    字型芫荽（中文）＋Fraunces SOFT 100／wght 600（ASCII）＋Noto Sans TC（備援，目前沒用到）的子集放
    `assets/fonts/`，加機場要跑 `tools/make_font_subset.py`（測試會擋）；51 張約 0.9 MB、本機約 3 秒，預算 60 秒
  - **第四階段：AI 對決「三顆燈」（2026-10-18 定案）**——規則（現有等級）、Claude Opus 5.5、Gemini 4 Argon
    各一顆燈。兩個 AI 各自讀該機場的全部數據，給自己的等級＋一段短評（像評論員）；數據照舊全部保留給讀者。
    只請 AI 評「未來 5 天有任一時段 ≥ 中、或等級有變」的機場，其他機場兩個 AI 燈直接寫「沒看到明顯風險」、
    不呼叫。短評一次輸出四語，以 zh-TW 為準、其他三語是忠實翻譯，四語內容完全一樣不得增減，zh-HK、zh-CN
    用當地用語。AI 只能根據 `latest.json` 裡的數據講、不能自己生機率數字；附「AI 評論僅供參考，以航空公司與
    機場公告為準」。記「對決戰績」：用停飛統計回頭比較規則、Opus、Argon 誰事前比較準，11/18 看第一份，
    之後再決定要不要公開。金鑰：HongThai 專屬的 Anthropic 金鑰與 Google 服務帳號，各設每月上限 30 美元，
    不跟 Duado 共用，只放 Actions secrets（`ANTHROPIC_API_KEY`、`GOOGLE_SERVICE_ACCOUNT_JSON`＝JSON 整份原文、
    `GOOGLE_CLOUD_PROJECT`、`GOOGLE_CLOUD_LOCATION`＝`global`）。模型 `claude-opus-5-5`、`gemini-4-argon`（Vertex）。
    保險：每報最多評 20 個機場、每天每模型 80 次、不重試、預算 180 秒、兩模型平行。提示詞
    `docs/prompts/2026-10-19-HD5-ai-duel.md`。短評用字規則（不出現內部代號、四語照 Duado 語系規則、不寫英文
    等級字、統一「停飛風險」；違規記 `bad_wording`）見 `docs/prompts/2026-10-19-HD6-ai-wording.md`
    **已實作（HD5 PR）**：`src/hongthai/ai/`——`config.py`（模型字串、免責四語、上限，換模型只改這裡）、
    `select.py`（選機場）、`prompt.py`（系統提示 `SYSTEM` 與精簡文字）、`parse.py`（回應檢查、錯誤代碼）、
    `claude.py`、`gemini.py`、`run.py`（平行呼叫、每日上限、`ai` 欄位、戰績）；`build.run_ai` 在寫檔前跑、
    `og.lights_for` 有 `ok` 的 AI 燈時畫三顆。戰績 `data` 分支 `history/ai/<日期>.json`、每日次數
    `history/ai/calls-<日期>.json`。和提示詞不一樣的地方：Claude 不送 `temperature`（Opus 5.5 送了回 400）、
    `effort: "low"`；多兩個錯誤代碼 `run_cap`（排在 20 個之後沒評）、`refusal`（拒答）。欄位與代碼見 README
    「輸出」的 HD5 那段與「AI 對決」。
    **HD6（第一次實跑的修正＋短評用字規則，已實作）**：短評用字規則見 HD6
    （`docs/prompts/2026-10-19-HD6-ai-wording.md`；系統提示「用字」那段、`ai/parse.py` 的 `check_wording`、
    詞表在 `ai/config.py`，違規記 `bad_wording`）。en 不能有任何中日文字或全形字（CJK，例如「10/19 12–13 時」）；
    zh-CN 不能用台灣用語「机率」「资料」（要寫「概率」「数据」，HD7）。
    `max_tokens` 3000、Gemini `thinking_level: LOW`（Gemini 4 不接受 `thinking_budget`）、字數上限中文 300／en 800（HD5 的 400 擋掉一半 en）、Gemini 2 條並行；
    戰績檔失敗那顆多 `detail`（`<代碼>:<stop_reason>:<輸出 token 數>[:<標記>]`）。Gemini 的 429：Argon 在
    `global` 的 Standard PayGo 是組織層級用量級距、沒有每專案配額可申請，見 README「AI 對決」
  - **第五階段：新天氣種類**——大雨／雷雨、大雪／結冰、濃霧；12 月北海道下雪前上線。
    **定案（2026-10-19，HD8）**：三類 `rain`／`snow`／`fog`（fog 含低雲幕），颱風的雨歸 `wind`；**燈號維持一種等級**，
    種類只進每格的 `causes`（主因在前）、預覽圖小字（「・濃霧」）、AI 短評。原則：貼近實際會停飛的情況，只會延誤的
    不升級。官方層：+TSRA 或 TS 且能見度 ≤ 1600 公尺 → 中、冰雹 → 高；SN 且 ≤ 1600 → 中、+SN／凍雨／冰粒 → 高、-SN 不升級；
    能見度 < 1000 公尺或雲底 ≤ 200 呎 → 中、< 400 公尺或 ≤ 100 呎 → 高（METAR 只套第一格）。模式層：ECMWF `tp`／`ptype`／
    `2t`＋系集 `tpg25`／`tpg50`、GFS `APCP`／類別降水／`VIS`；雨 6 小時 ≥ 30 mm 或系集 ≥ 50 mm 機率 ≥ 30% → 中、≥ 60 → 高；
    雪 ≥ 5 mm 水當量 → 中、≥ 10 → 高、凍雨 ≥ 1 mm → 高；霧只有 GFS 能見度（同官方門檻）。門檻先上線、一個月後再調。
    警報：天文台黑雨 → 中，紅雨、雷暴只列出不升級；氣象署大豪雨以上且機場在範圍 → 中；JMA 大雪警報另開 HD9；
    澳門、韓國、越南、菲律賓這階段不加。欄位清單在 `docs/worklog/2026-10-19.md`「待網頁配合」。
    提示詞 `docs/prompts/2026-10-19-HD8-weather-types.md`。金門、馬祖沒有 TAF／METAR，霧先只有模式層（HD8 查來源）
    **HD10（2026-10-19 定案）：模式層的霧（GFS 能見度）最高只到「中」**，要到「高」必須官方層（TAF／METAR）真的有霧或
    低雲幕達 < 400 公尺或雲底 ≤ 100 呎——GFS 能見度不準、只有一個模式沒對照、大雨時也會被壓很低（06:56Z 釜山只靠
    GFS 308 公尺判 high；花蓮台東大雨格 76–92 公尺）。提示詞 `docs/prompts/2026-10-19-HD10-model-fog-cap.md`。
    HD9 留給 JMA 大雪警報
    **HD11（2026-10-19 定案）：開發期間取消 AI 每日上限**（`DAILY_CAP=0` 不限，代碼 `daily_cap` 留著不用），每報 20 個
    機場、不重試、180 秒預算、月 30 美元硬上限不變；正式推廣前再評估。提示詞
    `docs/prompts/2026-10-19-HD11-ai-daily-cap-off.md`，排在 HD10 之後
    **已實作（HD8 PR）**：規則在 `assess.py`（開頭 docstring「新天氣種類」）、門檻在 `config.Thresholds`（12 個
    camelCase 鍵，`airports.json` 可覆寫）、TAF／METAR 的 `vis_m`／`wx`／`ceiling_ft` 在 `sources/taf.py`、
    ECMWF `tp`／`ptype`／`2t`＋`tpg25`／`tpg50`、GFS `APCP`／類別降水／`VIS`、天文台 `WRAIN`／`WTS`、
    氣象署 `W-C0033-001`；預覽圖小字「・濃霧」、AI 短評說出主因。實測 ECMWF 151 MB／166 秒（`2t` 保留）、
    GFS 74 MB／54 秒；`latest.json` 640 → 1,019 KB（gzip 45 KB）。和提示詞不一樣的地方：
    - GFS 的降水與能見度在 `.idx` 裡是「選配」（`gfs.IDX_OPTIONAL`）：找不到只 log、陣風照抓，不會因為
      NOAA 改了降水的欄位讓整個 GFS 失敗
    - ECMWF 的 `tp`／`ptype`／`2t` 和 `10u`／`10v` 放同一個請求（同一套步長，多第一格的開始步長算 6 小時雨量）
    - 氣象署特報的原始回應另存 `history/raw/<日期>/<時間>-cwa-hazards.json`（`-cwa.json` 維持颱風警報原文、
      格式不變）；特報那個請求失敗時 `sources.cwa` 多 `heavyRainOk: false`＋`heavyRainError`（提示詞沒列的欄位）
    - 特報的時間沒有時區時當台灣時間；W-C0033-001 沒有授權碼沒辦法實抓，格式照文件寫，**合併後第一報要看
      `-cwa-hazards.json` 對一次**
    - 天文台黃雨（`WRAINA`）不產生警報（定案的 `kind` 只有黑、紅、雷暴）
    - 「低的警報不撐起官方層」照字面套到所有低的警報：**天文台 1 號信號（低）單獨生效時，那幾格從「官方
      低」變成退回模式**（以前會蓋掉模式層）。現有測試沒有這個案例，結果都沒變
    - 只有警報（沒 TAF）的格 `wx` 是 `null`，所以 METAR 的霧在這種格不算（照「官方層只有警報時 wx 是 null」）
    - 能見度英里換公尺是 × 1609 後換算到 50 公尺（主對話 2026-10-19 改，讓公制 TAF 的 1000／0400／1600
      換得回原值），見 README「已知的保守假設」
    - `BLSN`／`DRSN`（吹雪、低吹雪）也算 `SN`（字串含 SN）
    - TAF 的 `visibilityM`／`wx`／`ceilingFt`「主時段」＝涵蓋現在的主時段（FM／BECMG 之後的也算），沒有就
      第一個還沒結束的
    - AI 用字對照多 zh-CN「公尺 → 米、呎 → 英尺」
    - 既有測試的結果一個都沒改；比對整個 dict 的幾個測試（`model.ec`／`model.gfs`、ECMWF 請求內容）補了新鍵
    - 金門、馬祖的查證（只回報、不實作）見 HD8 PR 說明：飛航服務總臺 AOAWS 有兩站的 METAR／SPECI（免金鑰的
      `POST /Report/get_metar_speci`，非正式介面）、沒有公開的 TAF；氣象署 O-A0003-001 有金門 467110、
      馬祖 467990 的能見度（要授權碼）
  - 順序（2026-10-19 定案）：HD2 → H9 → HD3（十個新機場）→ HD1（預覽圖）→ AI 對決 → 天氣種類；
    **新天氣種類有硬期限（12 月北海道下雪前），AI 對決拖到的話天氣種類排到 AI 前面**。11/18 檢討停飛統計
    能不能拿來校準等級。**階段號碼以 Duado `docs/spec.md` 第 16 節為準**，兩邊要一樣
  - 還沒排進階段的：FNV3／WeatherNext Cyclones 颱風路徑（授權是實驗性條款、商用待確認，所以排後面）、
    日本機場（JMA bosai JSON 非正式）、華南與馬尼拉（只能爬網頁）、推播（要接進 App，屬 Duado 的規格）
- 等級叫「風險」不叫「機率」，等用實際停飛紀錄回測校準後才改。停飛紀錄沒有現成的，從第一天起從航班狀態
  自己累積（`data` 分支；H6 起只存每 6 小時格的取消／延誤統計，不存原始航班資料）
- 保守假設都在 `assess.py` 與 `airports.json` 的門檻，改之前先跟 Shawn 確認；單位一律用節（HD2 起）
- 隱私：這個 repo 不碰任何個資；公開 repo，程式裡不能有金鑰

## 和 Duado 的分工

- 這個 repo 的改動由 HongThai 專用對話負責；duado.app/hongthai/ 網頁與 JSON 契約由 Duado 的主對話負責
- 需要網頁配合（例如顯示側風數字）時，把要加的欄位與意思寫清楚，Shawn 會轉給 Duado 那邊
- 目前待網頁配合：每格的 `official.crosswindKt`、`model.ec.crosswindKt`、`model.gfs.crosswindKt`
  （節；含陣風、所有跑道裡最小的側風分量；沒有風向時＝風速本身；`null`＝沒資料或沒設跑道）
  要加進網頁的「依據」區；澳門的警報 `source` 是 `"smg"`
- HD2 加的節欄位（要進 Duado `docs/spec.md` 第 16 節）：`model.ec.hresGustKt`、`model.gfs.gustKt`（節）、
  `model.ec.p29Kt`／`p37Kt`／`p49Kt`（系集陣風 ≥ 29／37／49 節機率；`p29Kt`＝`p15`、`p49Kt`＝`p25`、
  `p37Kt` 一律 `null`）。網頁之後顯示風速請改用節的欄位
- 第三階段（H9，41 個機場）加的欄位，要和 Duado `docs/spec.md` 第 16 節一致，經 Shawn 轉給 Duado 總指揮：
  頂層 `regions`（`[{id, name: {四語}}]`，顯示順序；id 是 `taiwan`、`east-china`、`south-china-hkmo`、
  `okinawa`、`japan`、`korea`）、`airports[].region`（地區 id）、`airports[].official.warnings`（布林，
  有沒有接官方警報來源；`false` 顯示「官方警報：尚未提供」）。沒有 TAF／METAR 的機場 `taf`／`metar` 是
  `null`（原本就是可空）
- HD3（51 個機場）要經 Shawn 轉給 Duado 總指揮、進 Duado `docs/spec.md` 第 16 節的（只加值，不加欄位）：
  `regions` 多 `vietnam`（越南）、`philippines`（菲律賓／菲律宾）、`guam-palau`（關島・帛琉／关岛・帕劳／
  Guam & Palau），接在 `korea` 之後；`airports[]` 變 51 個；`warnings[].source` 多 `"nws"`（關島），`kind` 是
  `typhoon_warning`／`typhoon_watch`／`ts_warning`／`ts_watch`，`code` 是 NWS 的 event；`sources.nws`。
  關島 `official.warnings: true`，越南、菲律賓、帛琉 `false`

- HD8（第五階段天氣種類）加的欄位：`slots[].causes`、`slots[].official.wx`、`slots[].model.ec`／`gfs` 的雨量、降水型態、
  能見度、三類等級，`warnings[].kind` 的 `rainstorm_black`／`rainstorm_red`／`thunderstorm`／`cwa_heavy_rain`，
  `airports[].taf`／`metar` 的 `visibilityM`／`wx`／`ceilingFt`；完整清單與值域在 `docs/worklog/2026-10-19.md`
  「待網頁配合」，經 Shawn 轉給 Duado 總指揮
- HD5（AI 對決）加的欄位，要和 Duado `docs/spec.md` 第 16 節一致：頂層 `ai`（`disclaimer` 四語、`models`）、
  `airports[].ai`（`evaluatedAt`、`claude`、`gemini` 兩顆燈）、`sources.ai`（`ok`、`seconds`、`calls`、
  `errors`）。錯誤代碼比定稿多兩個，要經 Shawn 轉給 Duado 總指揮：`run_cap`（符合條件但排在前 20 個之後、
  沒評）、`refusal`（模型拒答或被安全過濾擋下）；網頁照 `error` 處理（燈顯示資料不足）即可

## 安全與隱私

- 公開 repo：程式、測試、PR、提示詞、截圖裡都不能有金鑰或個資；這個 repo 不碰任何個資
- 金鑰只由 Shawn 放進 **Settings → Secrets and variables → Actions**，程式只從環境變數讀
  （`build.yml` 的「產生 latest.json」那一步把 secrets 帶進環境變數）：
  - `CWA_API_KEY`：中央氣象署開放資料授權碼
  - `ANTHROPIC_API_KEY`：Claude Console「HongThai」Workspace 的金鑰（AI 對決，HD5）
  - `GOOGLE_SERVICE_ACCOUNT_JSON`：GCP 服務帳號金鑰 **JSON 整份原文**（不是 base64）；程式 `json.loads`
    後交給 `service_account.Credentials.from_service_account_info`，不寫到磁碟（HD5）
  - `GOOGLE_CLOUD_PROJECT`：GCP 專案 ID（HD5）
  - `GOOGLE_CLOUD_LOCATION`：`global`（Gemini 4 Argon 只開 global、us、eu；HD5）
- AI 的金鑰 HongThai 專屬、各月上限 30 美元、不跟 Duado 共用；程式內另有每報 20 個機場的上限
  （`src/hongthai/ai/config.py`）。每天每模型 80 次的上限**開發期間不限**（2026-10-19 定案，HD11，`DAILY_CAP=0`），
  正式推廣前再評估；手動 Run workflow 也照常跑 AI

## 流程

1. 主對話寫提示詞（`docs/prompts/…`）→ 雲端對話實作、開 PR 到 `main`
2. `ci`（`.github/workflows/ci.yml`）：ruff check、ruff format --check、pytest；全部不連網（用 `tests/fixtures/`）
3. 主對話審 PR → 回 Shawn「可以合併」→ Shawn 合併（或開 auto-merge）
4. `build`（`.github/workflows/build.yml`）排程每天 UTC 01:05、08:25、13:05、20:25 跑
   `python -m hongthai.build`，結果推 `data` 分支、發布 GitHub Pages；`publish()` 之後畫 51 張分享預覽圖
   `public/og/<iata>.png`（HD1，只在 Pages、不進 `data` 分支；畫不出來只 log，`history/timing/` 有 `og` 那行）。
   寫檔前跑 AI 對決（HD5，`history/timing/` 有 `ai` 那行，`calls` 是兩個模型的呼叫次數）
5. 改了來源或格式的 PR，合併後請 Shawn 到 **Actions → build → Run workflow** 手動跑一次，
   然後開 latest.json 確認

Shawn 要做的手動步驟（一次性，PR #1 時列過）：Settings → Pages 的 Source 選 GitHub Actions；
Settings → Secrets and variables → Actions 新增 `CWA_API_KEY`（氣象署開放資料平台授權碼）。

## 資料來源與授權

| 來源 | 用途 | 授權 |
| --- | --- | --- |
| ECMWF 開放資料（經 AWS／Google 鏡像） | HRES 10 米陣風與 10 米風（側風的風向）、系集陣風機率；HD8 起 HRES 總降水、降水型態、2 米溫度與系集 24 小時雨量機率 | CC BY 4.0（要標示 © ECMWF） |
| NOAA GFS（AWS 開放資料鏡像 `noaa-gfs-bdp-pds`，NOMADS 備援；H10） | 地面陣風、10 米風；HD8 起 6 小時降水、類別降水、地面能見度 | 美國政府公有領域 |
| AviationWeather.gov Data API | 51 個機場的 TAF、METAR（一個請求帶全部；7 個沒有 TAF，見 README「機場」；HD3 的十個都有） | 美國政府公有領域 |
| OurAirports（`airports.csv`、`runways.csv`；H9、HD3） | 新增 46 個機場的座標與跑道真北方位 | 公有領域（Unlicense） |
| OpenStreetMap（跑道 way 114511749；HD3） | 石垣跑道兩端座標（算真北方位） | ODbL，© OpenStreetMap contributors |
| 美國國家氣象局 api.weather.gov（`/alerts/active?zone=GUZ001`；HD3） | 颱風／熱帶風暴警報與守視（關島）。帛琉查過不接，見下面 | 美國政府公有領域 |
| 中央氣象署開放資料（`W-C0034-001`；HD8 起加 `W-C0033-001`） | 颱風警報（台灣十個機場，每個機場一組警戒區關鍵字）；天氣特報（大豪雨、超大豪雨） | 政府資料開放授權條款；要授權碼 |
| 香港天文台開放數據（warnsum） | 熱帶氣旋信號（香港）；HD8 起加暴雨警告信號、雷暴警告 | data.gov.hk 使用條款 |
| 澳門地球物理氣象局 SMG（`xml.smg.gov.mo`，data.gov.mo 資料集「熱帶氣旋信號」） | 熱帶氣旋信號（澳門） | 澳門政府數據開放平台使用條款（須註明平台與取得日期） |
| 航班狀態（香港機管局、桃園機場、松山／高雄／澳門見 README） | 算每 6 小時格的取消／延誤統計（不存原始資料），之後回測 | 各自條款，見 README |
| 芫荽 Iansui、Fraunces、Noto Sans TC（子集，`assets/fonts/`；HD1） | 分享預覽圖的字型 | SIL OFL 1.1（各附 `OFL-*.txt`） |

NWS 查的結果（HD3，2026-10-18；細節在 README「資料來源與授權」與 `src/hongthai/sources/nws.py` 開頭）：
- 關島：`/zones?area=GU` → `GUZ001`（PGUM 的 `/points` 的 `forecastZone`）；`/alerts?zone=GUZ001` 有超強颱風
  Champi（29W）期間的 Typhoon Watch／Warning（10-15～10-18，更新是 `Update`、解除是 `Cancel`）→ 接了
- 帛琉：`/zones?area=PW` 有 `PWZ001`–`PWZ008`（PTRO 在 Airai＝`PWZ003`，2026-04-16 生效），但 `/alerts?area=PW`
  自 2026-04-01 起零筆、Champi 期間也沒有；`/offices/PQW` 404、`/points/7.367,134.5441` 500；HLS 只有 `PQ2`
  （馬里亞納）→ 不接，`warningSources: []`。之後看到帛琉的警報再加 `nws`＋`nwsZone: "PWZ003"`

## `latest.json` 是契約

- 以 Duado `docs/spec.md` 第 16 節為準；README 的「輸出」有範例與「規格以外加的欄位」清單
- 既有欄位不改名、不改型別，只能加。改格式要兩邊一起改，先經 Shawn 跟 Duado 主對話說
- `tests/test_build.py` 是契約測試：加欄位時一起更新

## 等級規則在哪

- `src/hongthai/assess.py`：所有規則與本 repo 自己的約定（開頭的 docstring 寫齊了）
- `airports.json` 的 `thresholds`：每個機場可覆寫的門檻（預設值在 `src/hongthai/config.py` 的 `Thresholds`）
- 官方警報對機場：`airports.json` 的 `warningSources`（`cwa`／`hko`／`smg`／`nws`）、`cwaAreas`（氣象署警戒區
  關鍵字）與 `nwsZone`（NWS 的 zone，關島 `GUZ001`；HD3）

## 已知的保守假設與待校準的參數

都是初版，等有停飛紀錄回測後再調（調之前先跟 Shawn 確認）。HD2（2026-10-19）起一律用節：

- 陣風（模式 HRES／GFS 與 TAF 同一套）：≥ 48 節高、≥ 37 節中（桃園機場空橋規則 37／48／55 節）；
  TAF 平均風 ≥ 35 節高
- EC 系集：陣風 ≥ 25 m/s（≈ 48.6 節，`p49Kt`）機率 ≥ 30% 高；**中級不用系集**（ECMWF 開放資料只有
  ≥ 10／15／25 m/s 的機率，沒有 37 節的）。`p29Kt`（＝`p15`）只輸出；`p37Kt` 一律 `null`，之後用 GEFS
  系集成員自己算
- 側風：含陣風側風 ≥ 33 節高、≥ 27 節中（737-800 濕／乾跑道起飛約 27／33 節）；用陣風（不是平均風）算側風；
  沒有風向時側風＝風速本身
- 所有機場先同一套（`config.py` 的 `Thresholds`），之後找到個別機場的作業標準再在 `airports.json` 覆寫
- HRES 的 10 米風只抓 00／06／12／18Z 的時間點（H10，減少下載量），每個 3 小時陣風區間配結束時間往後
  最近的那個時間點的風向（最多差 3 小時）
- 跑道方位用真北（風向都是真北）；所有跑道取最小側風（假設最好的那條跑道都能用，沒算跑道關閉、
  長度、機型限制）
- 目前生效的警報只套用到開始時間早於「現在 + 12 小時」的格（警報本身沒有預報時段）
- 氣象署警戒區是關鍵字比對（「東北部」也會比到「北部」），偏保守
- EC 系集機率是 24 小時窗，6 小時格取包住它的窗的最小值
- 0–30 小時以官方為準；METAR 只算進現在那一格的側風
- **三類（雨、雪、霧）門檻先照 2026-10-19 定案上線，累積一個月紀錄再調**（HD8）；**霧的模式層只有 GFS**
  （ECMWF 開放資料沒有能見度；GFS 能見度大雨時也會很低，大雨格常常同時是霧）；**金門馬祖沒有 TAF／METAR**
  （AviationWeather 沒有這兩站），霧只有 GFS
- 低的警報（紅雨、雷暴、天文台 1 號信號）不會自己撐起官方層（HD8）
- 已經過去的 TAF 時段不算（HD7，2026-10-19，`docs/prompts/2026-10-19-HD7-taf-past-periods.md`）：TAF 各時段
  只算結束時間在產出時間之後的，只影響第一格；第一格的 TAF 時段全部過去時當作沒有 TAF（有警報走「只有警報」
  的路、METAR 側風照算，沒有警報退回模式）。起因是關島 10/19 03:57Z 那報第一格被 02–03Z 的 TEMPO 判高
- 2026-10-19 HD7 前的第一格官方層可能含已過去的 TEMPO
  （HD7 合併後第一份的 `generatedAt`：**2026-10-19T05:25:00Z**，台北 13:25）。`history/*.json` 不重算；回看戰績
  （`history/ai/`、`history/cancellations/`）時 `run` 在 05:25Z 之前的第一格要打折看。實際上 HD7 合併後第一報只有
  GUM 第一格 high → low，其他 50 個機場第一格沒變，`run_cap` 4 個，沒有預期中的一次性大量

### 來源逾時與沿用（H7，2026-10-18 build #4 被 ECMWF 429 卡到被砍之後）

- 每個來源有時間預算（`build.py` 的 `BUDGET_S`：ecmwf 300（H10 起，原 240）、gfs 180、taf 45、hko 30、
  smg 30、cwa 45、nws 30（HD3）、flights 120、ai 180（HD5）、og 60（HD1）秒，總和 17 分鐘），超過記
  `error: "timeout"` 繼續跑下一個；Actions 那一步 18 分鐘、job 28 分鐘（HD5 前 15／25）
- ECMWF 重試最多 3 次、間隔 10 秒、不照 Retry-After；找最新一報先問入口、下載先試 AWS 鏡像
  （→ 入口 → Google；AWS 下載不重試，S3 的 503 Slow Down 一來就換），`sources.ecmwf.mirror` 記實際來源。`ecmwf-opendata` 最低 0.3.34（有重試參數）
- GFS（H10）：先 AWS 開放資料鏡像（`.idx`＋HTTP `Range` 只抓三筆），失敗才 NOMADS（2026-10-18 12:42Z 起
  NOMADS 對 Actions 回 403）；`sources.gfs.mirror` 與 timing 的 gfs 那行記 `aws`／`nomads`
- ECMWF HRES（H10）：每個步長只有一個陣風參數（`10fg` 或 `10fg3`，不能只抓 `10fg3`）；`10u`／`10v`
  只抓 6 小時整的步長，一報從約 112 MB 降到約 82 MB（目標 70 MB 沒達到，見 PR 說明）
- `ecmwf`／`gfs` 失敗時沿用「最近一份有該模式資料」的同機場同格 `model.ec`／`model.gfs`，等級照常算。
  H10 起往前找：`data` 分支 `history/<時間>.json` 由新到舊，第一份 `sources.<名稱>.ok` 是 `true` 而且
  模式時次在 24 小時內的；找不到才退回上一份 `latest.json`。`ok` 維持 `false`、加 `reusedFrom`
  （那一份的 `generatedAt`），`runs` 是那一份的。模式時次超過 24 小時不沿用（系集各自算），
  所以連續失敗時 24 小時後自然停。TAF、METAR、警報不沿用
- 預算是用一天的實測抓的初版，之後看 `history/timing/` 調整：
  `git show data:history/timing/2026-10.jsonl`（沒有 `done` 那行＝那次被砍）

## `data` 分支

Actions 自動推，不要手動改。內容：

- `latest.json`、`history/<YYYYMMDDTHHMM>Z.json`：每次的結果
- `history/raw/<日期>/<HHMM>Z-{taf,metar,hko,cwa,smg,nws}.json`：官方來源原始回應（SMG 是 XML 原文包在 JSON 裡；
  NWS 是 HD3 起）；`<HHMM>Z-cwa-hazards.json` 是氣象署天氣特報 `W-C0033-001`（HD8 起）
- `history/cancellations/<日期>.json`：每機場每 UTC 6 小時格的航班取消／延誤統計（之後回測停飛用；
  H6 起，原始航班資料不再存）。日期是格的 UTC 日期；每次 build 合併進去，同一格新的覆蓋舊的，
  但新的總班數比舊的少就留舊的。格式與規則見 README「輸出」、`src/hongthai/cancellations.py` 開頭
- `history/cancellations/unknown-statuses.json`：各機場航班狀態對照表沒列的字串、累計次數、第一次與最近一次
  看到的時間（H10 起；只存字串與次數）。看到新字串就補進 `cancellations.py` 的對照表
- `history/timing/<YYYY-MM>.jsonl`：每次 build 每個來源的耗時（H7 起）。一行一筆，`start`、各來源、
  `done`；每個來源一跑完就寫，所以被 Actions 砍掉也留得下來，沒有 `done` 就是那次被砍了。
  欄位見 README「輸出」
- `history/flights/2026-10-18/`：H6 之前存的一天份航班快照（gz），留著不管
- `history/ai/<YYYY-MM-DD>.json`：AI 對決戰績（HD5），每報每機場一筆三方等級＋20 格的 `from`／`level`，
  不存短評；`history/ai/calls-<YYYY-MM-DD>.json`：每個模型今天（UTC）呼叫了幾次（每日上限 80 用）。
  11/18 拿戰績對 `history/cancellations/` 回看誰事前比較準

GitHub Pages（`public/`）只放 `latest.json` 與**最近 7 天**的 `history/<時間>.json`（H9 起，一份約 515 KB；HD3 起約 642 KB，2026-10-18 實測；
`build.py` 的 `PAGES_HISTORY_DAYS`，Shawn 確認中），以及分享預覽圖 `og/<iata 小寫>.png`（HD1，每報重畫，
不留歷史），不放原始快照與航班統計。`data` 分支的 `history/<時間>.json` 照舊全部保留；`og/` 不進 `data` 分支。
