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
    保險：每日上限開發期間不限（`DAILY_CAP=0`），正式推廣前再評估；每報 20 個機場、不重試、180 秒預算不變；兩模型平行。提示詞
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
    **HD10 補充（產品負責人同意）：`causes` 依據是模式層（霧只來自模式、官方層沒有霧）時同級的 `rain` 排在 `fog`
    前面**（`wind`、`snow`、`rain`、`fog`，`assess.MODEL_CAUSE_ORDER`）——模式的低能見度常是大雨造成的，主因寫雨；
    官方層照原本 `wind`、`snow`、`fog`、`rain`。所以台東 10/24 00Z 是 `["rain", "fog"]`。
    **已實作（HD10 PR）：模式層霧封頂中**（`assess.fog_model_level`；`slots[].model.gfs.fog` 最高 `medium`，
    欄位不變）。用 06:56Z 那報重算：51 個機場只有釜山 10/20 12Z、18Z 與台東 10/24 00Z 從 high 降到 medium，
    花蓮、台東其他大雨格等級不變、`causes` 的雨排到霧前面。HD9 留給 JMA 大雪警報
    **HD11（2026-10-19 定案）：開發期間取消 AI 每日上限**（`DAILY_CAP=0` 不限，代碼 `daily_cap` 留著不用），每報 20 個
    機場、不重試、180 秒預算、月 30 美元硬上限不變；正式推廣前再評估。提示詞
    `docs/prompts/2026-10-19-HD11-ai-daily-cap-off.md`，排在 HD10 之後
    **HD12（2026-10-19 定案）**：HD11 後第一報 AI 178 秒頂到 180 秒預算（Gemini 2 條並行、HD8 後資料變長、兩個 504）→
    預算 240 秒、Gemini 3 條並行（429 回來就降回 2）、戰績每筆記 `seconds`。提示詞 `docs/prompts/2026-10-19-HD12-ai-budget.md`。
    **第五階段（HD8／HD10／HD11）2026-10-19 Shawn 確認上線**，網頁端由 Duado 開 HW3
    **HD13（2026-10-19 定案，「金馬照建議」）：金門、馬祖的霧**——氣象署濃霧特報（`W-C0033-001` 已在抓）→ 警報
    `cwa_dense_fog`（中，台灣十個機場都適用）；氣象署局屬站觀測 `O-A0003-001`（金門 467110、馬祖 467990）當 METAR 用
    （`metar.source: "cwa"`）；沒有 TAF 的機場第一格可由 3 小時內的 METAR 單獨撐起官方層（`official.kind: "metar"`，宮古
    也會受益）；AOAWS 非正式介面不接。提示詞 `docs/prompts/2026-10-19-HD13-kinmen-matsu-fog.md`
    **HD9 已實作（2026-10-20，JMA 大雪警報）**：日本 8 個＋沖繩 3 個機場 `warningSources: ["jma"]`、`jmaArea`（office＋
    市町村 class20），來源 `sources/jma.py`（`BUDGET_S["jma"] = 45`，總和 1575 秒）。大雪警報 `jma_heavy_snow` 中、
    大雪特別警報 `jma_heavy_snow_emergency` 高、暴風雪警報 `jma_snowstorm` 低（只列出），都算 `snow`；注意報與其他
    警報不接。和提示詞不一樣：(a) 舊端點 `warning/data/warning/<office>.json` 停在 2026-05-28（JMA 改新制），改讀
    `warning/data/r8/<office>.json`（每種電文一筆的 list）；(b) 代碼照 JMA 警報頁 JS：大雪警報 `06`、大雪特別警報
    `36`（不是 33）、暴風雪警報 `02`（不是 05）；(c) 11 個機場剛好 11 個 office（不是 9 個）；(d) 市町村名放在
    `jmaArea.name`／`enName`（每報不抓 `area.json`），中文三語用日文漢字原樣（「千歳市」不轉「千歲」）；
    (e) 暴風雪特別警報 `32` 不在定案裡，先不接（待 Shawn 決定）。提示詞 `docs/prompts/2026-10-20-HD9-jma-snow-warning.md`
    **已實作（HD13 PR）**：`sources/cwa.py`（`dense_fog_for_airport`；`parse_obs`／`cwa_vis_m`／`cwa_wx` 把
    `O-A0003-001` 轉成 `taf.Metar`，`Metar.source = "cwa"`）、`assess.py`（`FOG_WARNING_KINDS`；沒有 TAF 的機場
    第一格 `by_metar`）、`build.station_metar`（AviationWeather 沒有才用氣象署的）、`airports.json` 的
    `cwaStation`、AI 提示詞（警報名稱「濃霧特報」；METAR 是氣象署的標「氣象署局屬站觀測」、`official.kind: "metar"`
    寫「METAR（觀測）」不寫「TAF（metar）」）。假資料（金門「陰有霧」能見度 0.3 km）跑出 RCBS 第一格
    `official.kind: "metar"`、`level: "high"`、`causes: ["fog"]`；`latest.json` 多約 1.8 KB。`cwa` 預算 45 秒不變
    （實測每報 1–5 秒，多一個請求）。和提示詞不一樣的地方：
    - **`O-A0003-001` 現在叫「氣象觀測站-10分鐘綜觀氣象資料」**（舊名「現在天氣觀測報告」），沒有數字的
      `Visibility`，只有 `VisibilityDescription`（公里的描述字串，文件只舉 `>30`）：數字照換、`>X` 是「以上」
      （≥ 10 公里記 9999）、`<1` 記 950 公尺（霧最多判到中）、區間取下限、看不懂 None。欄位名照 swagger 與
      資料標準說明文件 V1.05 寫，**合併後第一報要看 `-cwa-obs.json` 對一次**（特別是能見度字串的實際寫法）
    - 天氣現象照文件附表 2 全部對到 METAR 代碼（不只提示詞列的幾個）：霾 `HZ`、雹 `GR`、雷雹 `TSGR`、
      大雷雨 `+TSRA`、雨雪 `RASN`、陣雨雪 `SHRASN`、大雪 `+SN`、雷雪 `TSSN`、雪珠 `SG`、冰珠 `PL`、雷／雷聲 `TS`；
      「閃電」對不到放原文
    - 陣風 `GustInfo.PeakGustSpeed` 文件沒寫統計時段，**發生時間在觀測前 1 小時內才算**（防它是當日最大值），
      不算的也不寫進 `raw`；風向 990（不定）記 None（＝VRB）
    - **全部缺測的觀測（風、能見度、天氣都沒有）不撐起第一格**（`assess.metar_has_data`），提示詞沒寫；
      不然 `-99` 一整排會把第一格蓋成「官方低」
    - `raw` 的天氣寫氣象署原文（`陰有霧`，含雲量），不是只有「霧」
    - **改了一個既有測試** `test_metar_weather_not_counted_without_taf`：它的前提「沒 TAF＋中級警報＋METAR 霧
      → `wx` null」正是 HD13 要改的行為，改成「有 TAF、但第一格的時段都過去了」（HD7 的當作沒有 TAF，不走
      METAR 撐起）。`test_build.test_slot_shape` 的 `official.kind` 值域多 `metar`（宮古在 fixture 裡就會出現）；
      其他既有測試一個都沒改
    **HD17（Shawn 2026-10-20 定案）**：18:07Z 那報（HD13 合併後第一報）4 個 `bad_wording` 全是 `en/causes`、Gemini
    4 個 `http_504` 各卡 57 秒 → ① `causes`、`basis`、`agreement`、`slots` 是英文常用字，en 不當代號擋
    （`config.EN_PLAIN_WORDS`；中文三語照擋，其他代號四語照擋）；② `http_503`／`http_504` 同一個請求只重試一次，
    剩餘預算 ≥ 70 秒才重試（`config.RETRY_CODES`／`RETRY_MIN_LEFT_S`，`run.py` 兩個模型共用），重試也算一次呼叫、
    仍失敗 `detail` 加 `:retried`、`seconds` 兩次合計；其他錯誤照舊不重試；③ Gemini 維持 3 條並行（降回 2 條約 235 秒、
    撞 240 秒預算）。`latest.json` 欄位與錯誤代碼不變。提示詞 `docs/prompts/2026-10-20-HD17-wording-false-positive-504.md`
    **HD23（2026-10-20 定，Shawn 要先優化；29W 凍結前的 bug 等級止血，不動等級規則、投票、門檻）**：13:43Z 那報 Gemini
    9/20 ok、`http_504` 10、`http_429` 1，三個 504 重試後仍 504、各吃 114 秒（57＋57），AI 步驟 239.3 秒頂到 240 預算；
    另有幾個 504 是 0.3–3 秒就回（像 `global` 端點故障）→ ① **只有快失敗才重試**：第一次花不到 15 秒
    （`config.RETRY_FAST_FAIL_S`）才重試，15 秒以上才回的不重試、`detail` 標 `:slow`；② **單次逾時每模型各自**
    `config.TIMEOUT_S = {"claude": 60, "gemini": 45}`，`RETRY_MIN_LEFT_S` 跟著是逾時＋10（Claude 70、Gemini 55）；
    ③ **同一報 Gemini 在主要區域連續 3 次 `http_503`／`http_504`／`timeout`（`FALLBACK_AFTER`）就切備援區域**
    （`GOOGLE_CLOUD_LOCATION_FALLBACK`，沒設是 `us`、空字串＝關掉；`run.Regions`，備援 client 要用才建、同一把服務帳號）；
    備援回 `http_404` 或連續 2 次失敗（`FALLBACK_GIVE_UP`；`bad_format`／`bad_wording`／`refusal` 不算）就退回主要、
    這一報不再切；用備援失敗的 `detail` 加 `:fallback`，`sources.ai` 多 `geminiLocation`（最後送出的請求用的區域）；
    ④ **預算守門**：剩不到該模型逾時＋5 秒（`SEND_MIN_LEFT_S`：Claude 65、Gemini 50）就不送新請求、記 `timeout`。
    用 13:43Z 的秒數重算（3 條並行、依送出順序；原本重算 239.2 秒對得上實際）：改後約 163 秒；那報成功與失敗交錯，
    連續 3 次只在最後的快 504 尾段才會到，備援幫不上多少，省下的 76 秒主要來自 ①②。提示詞
    `docs/prompts/2026-10-20-HD23-gemini-504.md`
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
  - **多模式投票（2026-10-19 Shawn 定案；階段號碼待 Duado spec 第 16 節補）**：模式層改投票——每個模式一票、權重相同，
    某等級的票（等級 ≥ 它的模式數）≥ 分母一半就成立、取成立的最高等級；分母＝該格有資料的模式；只有 1 個就它決定、
    分母 < 2 標 `thin`。**IFS 系集只投「高」**（`p49Kt` ≥ 30% 投高、否則投低；判中時不算分母）。沒有陣風的模式
    （AIFS、AIGFS）用 10 米平均風 × 1.4 估算陣風、標 `gustEstimated`、網頁與短評寫「估算陣風」，係數一個月後檢討。
    三類各自投、再和風取最高；官方層照舊優先。欄位：不動 `model.ec`／`gfs`／`agreement`，新增 `model.models[]`、
    `model.vote`、頂層 `models`，`model.level` 改由投票決定（清單在 `docs/worklog/2026-10-19.md`「待網頁配合」）。
    分支：**HD14** 投票框架＋AIFS＋AIGFS（5 票，`docs/prompts/2026-10-19-HD14-model-vote.md`）→ **HD15** WeatherNext 3
    （Shawn 申請 allowlist、寫信問 Google 能否公開展示，核准後再開）→ **HD16** Open-Meteo 的 ICON＋JMA（免費版；
    Shawn 判斷目前非商業——HongThai 與 Duado 都沒收費、沒廣告。**一旦收費、訂閱或放廣告，必須改買 Open-Meteo 商業方案或
    拿掉這兩個模式；網頁要標註 Open-Meteo（CC BY 4.0）**；注意免費版每日 10,000／每月 300,000 次上限）。
    AIGEFS 不做。查證結果（授權、取得方式、變數、下載量）在 `docs/worklog/2026-10-19.md`「待決定」。
    **2026-10-20 19:04 改定**：HD16 改成 Open-Meteo 三票——ICON、JMA GSM、**Google WeatherNext 2 系集**（`wn2-ens`，64 成員，
    比照 IFS 系集只投高：成員 10 米風 × G ≥ 49 節的比例 ≥ 30%），10/21 上線成 8 票；Open-Meteo 失敗那報自動退回沒有這三票、
    整報不壞；`Model.voting` 旁觀開關（不算分母、不投票，網頁標「旁觀」）；WN2 路徑不經 Open-Meteo 做（逐點 API 太重）。
    HD15 WeatherNext 3：10/20 19:04 已送 allowlist 申請（BigQuery、GCS Zarr、WN2 Zarr、WN2 Mean Zarr），雲端先照文件用 mock
    做好掛著；上線前要讀完 GDM 即時資料條款，不能公開顯示就只用 1 小時前以後的資料（CC BY 4.0）做報告比對。
    提示詞 `docs/prompts/2026-10-20-HD16-openmeteo-models.md`、`docs/prompts/2026-10-20-HD15-weathernext3.md`。
    **HD15 條款結論（2026-10-20 Shawn 確認照雲端）**：GDM 即時資料條款——挑點、挑時段、乘係數都算「未修改的即時資料」不能
    公開；日本是限制國家（11 個日本機場、日本使用者）；`data` 分支公開、存即時資料等於公開。所以 **Google 書面同意（含日本
    機場與日本使用者）之前，WN3 只做報告比對**（`WN3_MODE=report-only`：每報抓起報 ≤ 現在 − 121 小時那一報、全是 CC BY 4.0，
    存 `events/<id>/wn3/` 與路徑檔），不進 `latest.json`、不旁觀、不投票。`observe`／`WN3_VOTING` 開關寫好了，同意後再切。
    匿名讀歷史 Zarr 不行（401／403），連 CC BY 4.0 的歷史也要等核准。
    **HD16 已實作（HD16 PR）**：8 票（`icon`、`jma`、`wn2-ens` 接在 `aigfs` 後面）、`Model.voting` 旁觀開關、
    暴風雪特別警報 `32`。**授權條件（定案第 7 點）：(a) 一旦 HongThai 或 Duado 收費、訂閱或放廣告，必須改買
    Open-Meteo 商業方案或拿掉這三個模式；(b) 網頁與資料來源標「Open-Meteo（CC BY 4.0）・DWD ICON・JMA・
    Google WeatherNext 2」**；WN2 的授權來源查不到記在 README「已知的保守假設」。和提示詞不一樣、或提示詞沒寫死的地方：
    - **ICON global 在 Open-Meteo 也沒有能見度**（2026-10-20 實抓全是 `null`，JMA 也沒有）→ 霧的分母還是只有
      GFS（提示詞寫「ICON 有能見度 → 分母變 2」）。程式照樣會讀，哪天有值了自動投（最高到中）
    - JMA GSM 沒有陣風 → `jma` 是 `gust_estimated`（`config.MODELS` 寫死；Open-Meteo 之後給陣風要改這裡）
    - 起報時間：Open-Meteo 有 metadata API（`last_run_initialisation_time`），抓完資料後問（每個 5 秒逾時）；問不到 `runs.*` 是
      `null`、`sources.openmeteo.runError` 記原因，資料照用（不是提示詞說的「推算」）
    - **系集只抓 `wind_speed_10m`**（提示詞的網址多帶風向、雨量）：免費版使用條款另有**每分鐘 600 次**的上限，
      照提示詞 3 個變數的系集請求一個就是 979.2 次（64 成員 × 3 ÷ 10 × 51）；WN2 只投風的高、不算側風、不投雨，
      用不到另外兩個。只抓風速是 326.4 次，加預報 71.4 一報 **397.8**、一天 4 報約 **1,591** < 5,000，所以 WN2
      51 個機場全抓（沒做「只抓 20 個」）；`sources.openmeteo.calls` 與 timing 那行的 `calls` 記每報的數
    - WN2 的高門檻用 `modelHighGustKt`（48 節，機場可覆寫），提示詞寫「49 節」是沿用 `p49Kt` 的名字；成員
      沒值的不算分母；`windKt` 是 64 個成員格內最大風的中位數（偶數個取中間兩個的平均），`gustKt`＝它 × G
    - 一格的換算：ICON 陣風取 (from, to] 小時的「前一小時最大陣風」最大、`windKt` 是同一小時的平均風；JMA 同
      AIFS（[from, to] 小時最大平均風 × G）；雨量 (from, to] 逐時加總。型態：凍雨碼 66／67 → `freezing_rain`、
      **56／57 → `freezing_drizzle`**（提示詞只寫凍雨碼，兩個等級規則一樣）；降雪公分 ÷ 0.7 換水當量
    - 部分失敗：任何一個資料請求失敗就整個 `openmeteo` 失敗（三票都沒有），不做「預報成功、系集失敗」的半套
    - `latest.json` 多約 **790 KB**（2,214 → 3,023 KB；gzip 142 → 174 KB），原始快照一報約 1.2 MB（不縮排；
      zlib 後約 190 KB）——每天 `data` 分支多約 3 MB（history）＋5 MB（raw），要省再說
    - `models[].voting` 要經 Shawn 轉 Duado（網頁標「旁觀，不投票」）；其他要轉的欄位見 README「輸出」HD16 段
    **HD24 已實作（HD24 PR，只加欄位）**：`slots[].model.vote.mediumTotal`（判中的分母＝`_pool(..., "medium")` 的長度，
    不含只投高的 `ifs-ens`、`wn2-ens` 與旁觀模式；接在 `medium` 後面）、頂層 `models[].votesOnlyHigh`
    （`Model.votes_only_high`）。票數、規則、其他欄位一個字都不改；`slots[].model.models[]` 不加。`latest.json`
    多約 16 KB（15:04Z 那報重算 3,178 → 3,195 KB）
    **HD15 已實作（HD15 PR，待 allowlist 核准）**：`sources/wn3.py`（BigQuery `weathernext_3_0_0_0p1deg` 一個查詢、
    失敗退 GCS 統計 Zarr；服務帳號同 Gemini，不加 secret）、`wn3report.py`（事件檔＋補報）、`tracks.grid_field`
    （找中心吃任何經緯網格，GRIB 三個模式也改經過它、結果不變）、`BUDGET_S["wn3"]` 120（總和 1785，`build.yml`
    32／42 分鐘）。**讀完 GDM 即時資料條款的結論：不能公開即時數字**（取點、挑時間、乘 G 都算「未修改」；看得
    出原始數字的加值只能給特定對象；日本是限制國家）→ **`WN3_MODE` 預設 `report-only`**：`latest.json` 沒有 WN3
    （只有事件期間的 `sources.wn3`），build 在事件期間抓**起報 ≤ 現在 − 121 小時**那一報（最後一個有效時間也
    過了 1 小時 → CC BY 4.0）寫 `history/events/<id>/wn3/<起報>.json` 與 `tracks/<起報>-wn3.json`；期間最後 5 天
    靠 `events` 的 `backfill-tracks` 補（也補 WN3）。`observe`（Google 書面同意公開、而且涵蓋日本後才切）才進
    `models[]`，`voting` 預設 False、`WN3_VOTING=1` 才投。兩個開關是環境變數（Actions repo Variables）。和提示詞
    不一樣、或提示詞沒寫死的地方：
    - **`report-only` 不是「每報抓即時資料、只存 history」**：`data` 分支是公開的，存即時資料就等於公開分享，
      所以改成只抓已經過去的那一報（提示詞第 4 點本來就說「只用 1 小時前以前的資料」）
    - **歷史資料匿名讀不到**（401／403），補報也要核准、用服務帳號
    - 風用 **p50**（不是平均），平均與 p90 另存；`windKtP90` 是格內最大 p90 平均風、不乘 G
    - 沒有降水型態 → `ptype` 一律 null（不投雪）；不用 2 米溫度猜
    - 成員路徑 `<報>-wn3-ens.json` **不做**：原始 Zarr 一個 chunk 是一個成員一個 6 小時一張全球，一報上百 GB
    - BigQuery 每個查詢 `maximum_bytes_billed` 8 GB（每月免費 1 TB ÷ 124 報），超過就退 Zarr；表依日分割、叢集
      欄位文件沒寫，沒有叢集時一報可能近 1 TB——**核准後第一報看 `sources.wn3.estimateBytes`／`bytesBilled`**
    - Zarr 備援只讀每 6 小時的風、沒有雨量（一報約 2.7 GB 未壓縮，若 Google 有分片會小很多）
    - BigQuery 的資料集名要 Shawn 訂閱 Analytics Hub 時取 `weathernext_3`（或設 Variable `WN3_BQ_TABLE`）
    **HD18（2026-10-20 定案，Shawn 確認 12 條）：估算陣風的係數改成每個機場自己算**——G＝陣風÷10 米平均風，用 IFS（`10fg`÷
    √(u²+v²)）與 GFS（`GUST`÷10 米風速）各自的資料、同一模式同一機場同一格自己比自己（拿 AIFS／AIGFS 去比 HRES 陣風不公平：
    颱風路線不同時同一格本來就差很多，而且 GFS 自己的陣風也只有 IFS 的 0.76、IFS 陣風偏高不能當標準答案）；最近 30 天、
    每報每格、IFS＋GFS 合併取中位數；只用平均風 ≥ 10 節的格；夾 1.2～2.0；樣本 < 40 → 全機場合併 → 這一報全體中位數 →
    1.4 保底；`models[]` 加 `windKt`、`gustFactor`、`gustFactorBasis`；樣本存 `data` 分支 `history/gustfactor/<YYYY-MM>.jsonl`
    （IFS、GFS 分開記，因為 `10fg` 是時段最大、`GUST` 是時間點值，30 天後比較兩者再決定要不要只用一個）；30 天後用
    `tools/gust_factor_report.py` 對 METAR 驗證，AI 模式仍系統性偏低再加第二層修正。提示詞
    `docs/prompts/2026-10-20-HD18-gust-factor.md`，排在 HD14 之後
    **HD18 已實作（HD18 PR）**；和提示詞不一樣、或提示詞沒寫死的地方：
    - 首報的判斷：提示詞同時寫「樣本 < 40 → 全機場合併」與「首報 `basis: "run"`」，首報時全機場合併就是
      這一報、通常 ≥ 40。實作成「30 天窗裡除了這一報沒有別的報」就一律 `run`（`history/gustfactor/`
      還沒有、或停了 30 天以上都算），第二報起才照 `airport30d` → `all30d` → `run` → `default`
    - 新模組 `src/hongthai/gustfactor.py`（樣本、30 天窗、中位數、寫檔）；`build.gust_factors` 失敗只 log、
      全部用 1.4 `default`。`history/gustfactor/latest.json` 多一個 `run`（只算這一報的 `g`／`n`／`nIfs`／
      `nGfs`），`all`／`run` 的 `g` 是夾過的中位數
    - 樣本用的陣風與平均風都先取一位小數（和 `latest.json` 的數字一樣，之後可以從 history 重算），比例兩位小數；
      AIFS／AIGFS 的 `gustKt`＝一位小數的 `windKt` × G（`_rescore` 重算結果一樣）。AIFS／AIGFS 的 `windKt` 是
      格頭尾兩點大的那個（估算陣風本來就取大的）
    - 沿用 AIFS／AIGFS 時側風也要跟著換：估算陣風的側風和 G 成正比，照「新 G ÷ 舊 G」換算（舊 G 從抄來的
      `gustFactor`；HD18 以前的那筆沒有 `windKt`／`gustFactor`，當 1.4、平均風用舊估算陣風倒推）。
      `REUSE_FIELDS` 改成（位置, `runs` 鍵, 欄位），`models[]` 那筆寫成 `models.<id>`，IFS、GFS 的 `windKt`
      也一起抄
    - AI 短評的規則說明原本寫死「× 1.4」，改成「× 這個機場的係數（歐洲、美國模式 30 天陣風÷平均風的中位數，
      1.2–2.0）」
    - `latest.json` 多約 **280 KB**（2,148 KB；拿掉三個鍵 1,868 KB；gzip 104 → 118 KB），提示詞估 100–150 KB
    - 2026-10-20 實際跑一報（IFS／GFS 都是 19 日 18Z，首報 `run`）：IFS 中位數 1.69（352 個）、GFS 1.29
      （440 個）、合併 **1.48**（792 個）——GFS÷IFS＝0.76，和定案背景講的一樣。同樣抓 19 日 00／06／12Z 算：合併 1.43（767）、1.44（755）、1.44（783），
      IFS 1.64–1.69、GFS 1.26–1.29，一報一報很穩。首報三個機場：桃園 26 個樣本、關島 11、羽田 23，G 都是
      1.48（`run`）。四報合起來看：桃園 IFS 2.17／GFS 1.75／合併 **1.95**（100 個）、關島 1.62（41）、羽田
      1.41（102）——桃園比全體高很多，第二報起會換成 `airport30d`，合併後要看一下桃園的估算陣風
    - GFS 弱風時 `GUST` 可以比 10 米風小（fixture 桃園 5.4 對 8.0 節）；樣本只收 ≥ 10 節，不影響
    **HD19（2026-10-20 11:24 定案）：G 只用 IFS 的樣本**——HD18 首報 IFS 中位數約 1.65、GFS 約 1.27，定義不同已明顯；每格
    看的是 6 小時內最大陣風、和 `10fg` 一致，颱風季不想讓 AI 模式再偏低一個月。GFS 樣本照存、報表照分開印，30 天後檢討。
    提示詞 `docs/prompts/2026-10-20-HD19-gust-factor-ifs-only.md`
    **HD19 已實作（HD19 PR）**：**HD19 起 G 只用 IFS，GFS 樣本照存、30 天後檢討**。`gustfactor.summary` 的 `g`／`n`
    只看 IFS（`G_SOURCE = "ifs"`），`compute` 的三個門檻跟著用 IFS 的 `n`；`nIfs`、`nGfs` 照寫；
    `history/gustfactor/latest.json` 多 `"source": "ifs"`；`<YYYY-MM>.jsonl` 格式不變。提示詞沒寫、順手改的：
    AI 短評規則說明的「係數是歐洲模式、美國模式最近 30 天…」改成只寫歐洲模式（`ai/prompt.py`）；
    `test_build` 兩個 HD18 案例的 G 由合併的 1.6 改成 IFS 的 1.5（沿用 AIFS 那個把抄來的 `windKt` 改 32 節，
    保住 48 節剛好「高」的邊界）
    **HD14 已實作（HD14 PR）**；和提示詞不一樣的地方：
    - AIFS 的 `tp`／`sf` 單位是 **mm**（kg m⁻²），不是提示詞寫的 m（cfgrib `GRIB_units` 實測）；`ptype` 的
      「沒降水」是 6 小時總降水 < 0.1 mm（GRIB 打包雜訊約 0.01 mm）
    - AIFS 21 個步長加開始步長實測 66 MB／55 秒（提示詞估 50 MB）；AWS 鏡像那時連 `.index` 都回 503，落到
      ECMWF 入口。AIGFS 51 MB／38 秒，路徑是 `aigfs.<日期>/<HH>/model/atmos/grib2/aigfs.t<HH>z.sfc.f<FFF>.grib2`；
      NOMADS 沒有 `filter_aigfs`，不做備援
    - IFS 那票的雨＝`model.ec.rain`（HRES 雨量**或系集 24 小時雨量機率**，同 HD8），系集那筆本身不投雨
      （提示詞只寫「系集不投雨」，沒提 `p24hRain50`；照舊保留在 IFS 的票裡，要拿掉再說）
    - `vote.medium` 是「等級 ≥ 中、不含系集」的數（同判中那一輪的分母）
    - `latest.json` 從 1,091 KB 變 3,276 KB（`indent=1`；gzip 68 → 154 KB），比提示詞估的 +400–500 KB 大很多；
      `data` 分支每份 history 也一樣大（一天 4 份約 13 MB）。要省的話可以考慮 history／latest 改不縮排
      （不縮排 1.93 MB），格式決定留給主對話
    - 用 2349Z 那報重算：模式層 1020 格裡 83 格變低、1 格變高；高 114 → 61、中 72 → 84。主因是 AIFS 這次的
      颱風風速偏低（桃園 10/23 平均風 18–19 節 → 估算 26 節，同格 HRES 陣風 50–62 節）、系集投低也算進「高」的分母
    **贊助（2026-10-21 Shawn 定案）**：照 Open-Meteo 條款，自願捐款（tip jar）屬於非商業；網頁頁尾連到 duado.app/support（Ko-fi，
    只收單次自由贊助）。之後**不能**開 Ko-fi 的 Memberships 或月費、**不能**放廣告或贊助商 logo，否則要改買 Open-Meteo 商業方案
  - **颱風 29W（CHAMPI，薔琵）實測驗證（2026-10-20 Shawn 定案 8 條＋補充）**：AI 模式與物理模式路線分歧大（ECMWF、GFS、
    系集、AIGFS 往西打台灣華南；AIFS、WeatherNext、AIGEFS 在台灣東邊轉向往沖繩日本），拿這顆完整驗證。
    (1) 10/19 起每報 `latest.json` 永久存 `data` 分支 `history/events/29W/`；(2) 真相：METAR 每小時（最大陣風、平均風）、
    實際停飛（flights、`history/cancellations/`）、JTWC 最佳路徑，**JMA（RSMC Tokyo）最佳路徑當備案、兩份都有就並列**，
    期間先存 JMA／JTWC 即時現報當暫時真相；(3) **凍結：報告出來前不改等級規則、投票、門檻，只修 bug**；G 切 `airport30d`
    照常、切換時間記日誌；(4) 26 個機場（台灣 10、OKA／MMY／ISG、KOJ／FUK、FOC／XMN／PVG／SHA、HKG、**MFM（10/20 加，有航班真相）**、KIX／NGO／HND／NRT／SDJ）；
    (5) 報告：八個系統（五個模式、規則燈、Claude、Gemini）、陣風誤差與偏差／等級命中誤報漏報／路徑誤差，依提前時間
    0–24／24–48／48–72／72–96／96–120 小時分開（系集不算陣風、AI 燈只算等級）；(6) 路徑：IFS 與系集用 ECMWF 開放資料的
    颱風路徑產品（`type: tf`），GFS／AIGFS／AIFS 從海平面氣壓場找中心，存 `history/events/29W/tracks/`，過去的報能補就補。
    分三支：**HD20** 保存＋每小時 METAR／現報＋凍結（`docs/prompts/2026-10-20-HD20-29w-capture.md`）→ **HD21** 路徑抽取 →
    **HD22** 報告工具（颱風過後；JTWC `bwp292026.dat` 與 JMA 最佳路徑由 Shawn 附檔）
  - 還沒排進階段的：FNV3／WeatherNext Cyclones 颱風路徑（授權是實驗性條款、商用待確認，所以排後面）、
    日本機場（JMA bosai JSON 非正式）、華南與馬尼拉（只能爬網頁）、推播（要接進 App，屬 Duado 的規格）
- 等級叫「風險」不叫「機率」，等用實際停飛紀錄回測校準後才改。停飛紀錄沒有現成的，從第一天起從航班狀態
  自己累積（`data` 分支；H6 起只存每 6 小時格的取消／延誤統計，不存原始航班資料）
- 保守假設都在 `assess.py` 與 `airports.json` 的門檻，改之前先跟 Shawn 確認；單位一律用節（HD2 起）
- 隱私：這個 repo 不碰任何個資；公開 repo，程式裡不能有金鑰

## 29W 驗證期凍結（2026-10-22 12:00 台灣時間起；2026-10-20 19:04 Shawn 改定起點）

- **10/22 12:00 系統定版**，之後只修 bug，直到 29W 離開所有範圍機場（或轉溫帶氣旋）後 24 小時、初版報告出來為止；
  不改等級規則、投票方式、門檻。估算陣風係數兩天後自動切 `airport30d` 是既定行為，照常，切換時間記日誌
- **截止（2026-10-24 12:09 Shawn 定案，取代上一條的「離開後 24 小時」；12:49 補 AI 窗）**：浦東影響結束就收，日本不延長
  - 預報：報告只算到 **10/25 14:00 之後的第一報**（台灣 16:25，08:25Z）
  - 實測：`events.json` 的 29W `to` 由 10-28 改 **10-26**，METAR、颱風現報、航班（含 TDX）存到 10/26 當天結束
    （台灣 24:00＝16:00Z）；多存一天是為了讓截止前幾報落在 10/25 晚上～10/26 的預報時段有實測可對（薔琵那時經過九州附近，
    日本那幾格「預報低、實際也低」也算對）
  - 26 個機場不變，日本那幾格照常算
  - 報告工具 **HD36**：`--until`（預報算到哪一報）與 `--truth-until`（實測時間窗，例如 `2026-10-26T24:00+08:00`）分開，
    報告寫明兩個截止時間與仍然沒有實測的筆數（不算命中也不算誤報）；只改報告工具，凍結期間可以合併。
    **已實作**（README「事件保存 › 驗證報告」）；和提示詞不一樣的地方：模式路徑也跟 `--until`（只收留下的報用過的
    起報）、規則燈每報每機場的預測仍取整個 0–120 小時（窗只截實測）、時間要寫時區、航班 `asOf` 早於窗尾的窗以前算
    「窗還沒結束」，現在照 min(T, asOf) 截短
  - AI 兩燈每報每機場的窗截到實測截止（截止前任一格停飛＝有停飛、都沒有＝沒停飛），報告寫明截短幾個窗、附「只算完整窗」對照；
    規則燈每格照舊（提示詞 `docs/prompts/2026-10-24-HD36-report-until.md`）
  - 報告工具 **HD37**（只改報告工具，凍結期間可以合併）：(b) 的停飛實測，`cancellations/` 沒有的機場改用 TDX 逐班紀錄
    （`flights/`，29W 多台中、台南、花蓮、台東、澎湖、金門、馬祖南竿）；實測的最後時間每個機場各一個（逐班機場用
    TDX 整批最新的 `t`，審查 #106 改）；表定少於 4 班的格
    標「班次少」另外列（Shawn 2026-10-25 00:35 定案，規則照判）；`加班`／`轉降`／`預計HH:MM到站` 在報告裡重新分類
    （不改存檔）。**已實作**（README「事件保存 › 驗證報告」）；和提示詞不一樣的地方：窗裡的格都沒有航班列（逐班紀錄
    開始之前的報）不當成「沒停飛」、另計 `windowNoFlights`；每報每機場的「班次少」定義成結果靠班次少的格決定的窗；
    `預計HH:MM出發` 也算（資料裡有）（提示詞 `docs/prompts/2026-10-25-HD37-report-flights-truth.md`）
  - 時程：10/25 16:25 那報出來後 Shawn 附 JTWC `bwp292026.dat`（即時版）→ 初版先用到 10/25 為止的實測跑 →
    **初版出來就解除凍結**（約 10/25 晚上～10/26，不等定稿）→ 10/27 用補齊到 10/26 的實測重跑定稿
- 定版前（10/20–10/22 中午）排進去的：HD9（JMA 大雪警報，10/20 上線）、HD16（Open-Meteo ICON＋JMA＋WeatherNext 2 系集，8 票，
  10/21 上線）、暴風雪特別警報；網頁 HW6 10/21 同步。報告依版本分開算：10/22 12:00 前是 5 票版、之後是 8 票版；各模式自己照常。
  HD24（`vote.mediumTotal`、`models[].votesOnlyHigh`）只加欄位、不改票數，不影響報告的版本切分
- WeatherNext 3（HD15）趕不上，核准後先以「旁觀模式」（`voting: false`）進 `models[]` 與路徑檔、不投票，解凍後再投。
  **HD15 讀完條款後改成預設 `report-only`**（即時數字不能公開）：只存 5 天前那一報（CC BY 4.0）給報告比對，
  要進 `models[]` 得先拿到 Google 書面同意（上面 HD15 已實作）
- Google Maps Platform Weather API 查過（2026-10-20）：欄位齊、每月約 8 美元，但 Maps Service Terms B.21.1 禁止用在以提供天氣
  資訊為主要目的的產品、逐時預報值只能快取 1 小時——**不能當票、不能存 history，不接**
- HD9（JMA 大雪警報）只加雪的警報，29W 期間不影響風的等級（10–11 月沒有大雪警報，上線不會改變任何現在的等級）
- **HD27（JMA 暴風、大雨警報＋氣象署陸上強風特報）只列出、不改等級**：六種全部 `level: "low"`，低的警報不撐起
  官方層，所以任何一格的 `level`、`causes` 都不變，只有 `warnings[]` 多列；不影響報告的版本切分。升級與否 29W 報告後談
- **HD29（中國氣象局、韓國氣象廳、PAGASA 經 WMO SWIC）只列出、不改等級**：新種類（`cma_*`、`kma_*`、`pagasa_*`）
  全部 `level: "low"`，任何一格的 `level`、`causes` 都不變；`latest.json` 只多 `airports[].warningSources`（新欄位）、
  `sources.swic`、三個 `source` 值，21 個機場 `official.warnings` 變 `true`。不影響報告的版本切分；等級（調查報告 5.3 節的
  建議）29W 報告後再定
- 保存（HD20）：`events.json` 的 29W（台灣日期 10-19～10-26（10/24 由 10-28 提前）、26 個機場）期間每報快照、每小時 METAR 與
  JMA／JTWC 現報都在 `data` 分支 `history/events/29W/`（README「事件保存」）；之後的颱風在 `events.json` 加一筆
- **HD31 每小時逐班航班紀錄（10/23 起）**：`events` 的 `hourly` 第四件事，桃園、松山、高雄、香港、澳門逐班存
  `history/events/29W/flights/<表定 UTC 日期>.jsonl`（只在狀態、分類、預計／實際時間有變化時寫；解析與分類沿用
  `cancellations.py`），是 29W 報告「實際停飛」的真相資料；香港用 `backfill-flights` 補 10-19 起（合併後 Shawn 手動跑
  一次），其他四個只有當天補不到。只多存資料，不改 `latest.json`、等級、投票、`build.py` 的輸出，凍結期間可以合併
- **HD32 TDX 台灣機場航班存檔**：同一個 `flights/` 另外存 TDX（交通部運輸資料流通服務平臺）航空即時航班，
  `airports.json` 地區 `taiwan` 的十個機場一次請求拿（`/v2/Air/FIDS/Airport`＋`$filter`，每小時 token＋資料 2 個請求），
  `source: "tdx"`；桃園、松山、高雄和原本的來源各存各的（去重鍵含 `source`），之後比對兩邊一致性。要 Actions secrets
  `TDX_CLIENT_ID`／`TDX_CLIENT_SECRET`（Shawn 註冊 TDX 基礎會員後設；沒設就跳過，log 記「TDX 未設定」）。基礎會員
  每月 3 點、每金鑰每分鐘 5 次；資料量設好 secret 後實測補進 README。只多存資料，凍結期間可以合併
- **HD33a 新模式回補（只存資料＋報告工具，凍結期間可以合併）**：UKMO、GEM、ARPEGE、CMA GRAPES 經 Open-Meteo
  Previous Runs API 回補 29W 期間的逐時預報到 `history/events/29W/backfill/openmeteo-<模式>.jsonl`（`events` workflow 的
  `backfill-openmeteo` 填事件 id；合併後 Shawn 手動跑一次、10/27 定稿前再跑一次），`tools/report_29w.py` 有回補檔時
  (a) 多四列「（旁觀・回補）」、(b) 多一張每格各模式的風等級（快照 8 個模式的 `levels.wind` 與回補四個並列）對停飛實測；
  沒有回補檔時報告與 JSON 一字不差。不改 `latest.json`、等級、投票、AI、網頁（旁觀進 `latest.json` 是 HD33b）。
  和提示詞不一樣的地方：(a) GEM Global 的代號照文件是 `cmc_gem_gdps`（不是 `gem_global`）；(b) Open-Meteo 的
  `previous_dayN` 是提前 24N～24N+23 小時，照提示詞「起報＝validAt 減 N 天的 00Z」對 HD22 的切法落在第 N 段
  （day1 → 24–48，不是 0–24），所以多存 `previous_day0` 給 0–24 段，day5（120 小時以後）照存不算；起報用格開始時間減
  N 天（一格裡的小時同一個起報）；(c) (from, to] 6 個小時都有的格才算；(d) `events.yml` 沒有 `task` 選項，加的是
  字串輸入 `backfill-openmeteo`（空白＝不跑）；(e) **UKMO 是 CC BY-SA 4.0**（衍生產品要相同授權），回補檔與用到 UKMO
  數字的報告要標，HD33b 把 UKMO 放進 `latest.json` 前要先決定怎麼標
- 排程（**HD25**）只動排程與資料保存，**不改規則**：Cloudflare 排程 Worker（`cloudflare/trigger/`）當主鬧鐘、GitHub
  cron 留著當備援，build 同時段已出過就跳過（`timing/` 記 `skip`）；`events` 的 METAR 往回 6 小時、`backfill-metar`
  補 10-19 起的缺口（AviationWeather，金門、馬祖補不到）。等級規則、投票、門檻、`latest.json` 欄位都沒動，
  不影響報告的版本切分；部署與 token 見 `docs/cloudflare-trigger.md`
- 路徑抽取（**HD21 已實作**，定案第 6 點）：`history/events/29W/tracks/<起報>-<模式>.json`，IFS／系集用 ECMWF
  `type: tf`（BUFR、`eccodes` 解析，不加 `pdbufr`），GFS／AIGFS／AIFS 從海平面氣壓找中心；build 的來源 `tracks`
  （預算 150 秒，總和 1530 秒，`build.yml` 那步 28、job 38 分鐘），`latest.json` 只多 `sources.tracks`；過去的報
  用 `events` workflow 的 `backfill-tracks` 補（合併後 Shawn 手動跑一次）。和提示詞不一樣的地方：
  (a) ECMWF 把 29W 編成 `36W`，比對實際靠名稱 `CHAMPI`；(b) 起點多一個備案——同一報 ECMWF 路徑產品裡那顆的
  觀測位置（`seed.source: "ecmwf-tf"`），排在 `events.json` 的 `seed` 之後；HD20 上線（10-20 06Z）前的報
  沒有 JMA／JTWC 現報，不靠這個就補不到；`events.json` 的 `seed` 也要在起報前後 3 小時內才用；
  (c) 起點的現報取離起報時間**最近**的（不是窗內最新的）；(d) 找中心的檔多 `stop`（停止原因）；
  (e) 有模式抽不出來時 `sources.tracks` 是 `ok: false`、`error: "partial"`（其他照寫）

- **HD24（10/20 23:27，Shawn 看 HW6 上線頁後）**：只加 `vote.mediumTotal`（判中的分母，不含只投高的系集）與頂層 `models[].votesOnlyHigh`，
  不改票數與規則，凍結前合併；網頁 HW7 用它寫「6 個模式中 3 個認為中以上」

- **HD25（10/21 10:02）**：GitHub 排程延遲 3–5 小時、整點 cron 常被跳過 → Cloudflare 排程 Worker 當主鬧鐘、GitHub cron 當備援、
  build 同時段已出過就跳過；METAR 往回 6 小時並補缺口。只動排程與資料保存，不改規則與 `latest.json`，凍結前合併

- **HD26（10/21 11:25）**：AI 提示快取與 token 紀錄，**只改送法與紀錄，不改提示與參數**（提示文字、順序、模型、
  `effort`／`thinking_level`、溫度、`max_tokens` 一個字都不動，AI 的答案不應該因此改變；`latest.json` 不加欄位），
  凍結前合併。Claude 的 `system` 加 `cache_control`（Opus 5.5 最小 512 token）；Gemini 靠隱含快取（Gemini 4 最小
  4,096 token，`SYSTEM` 不到，大概不會命中，先記數字）；Claude 每報第一個機場先單獨評完再開線（`config.WARMUP`；Gemini 照舊直接開線）；戰績每次呼叫記 `usage`、
  `timing/` 的 `ai` 那行記合計與 `costUsd`；`tools/ai_cost.py` 看命中率與費用（README「AI 對決」）。
  省錢的做法（沿用評論、每天 2 次、Gemini 上限、規則移進快取前綴）在 10/21 日誌「待決定」，颱風報告後談

- **HD27（10/22 01:36）**：日本氣象廳暴風、大雨警報只列出（low），不改任何等級，凍結前合併；升級與否 29W 報告後談

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
- HD13（金門、馬祖的霧）要轉給 Duado 的三個小東西（主對話寫進 `docs/worklog/2026-10-19.md`）：
  `warnings[].kind` 多 `cwa_dense_fog`（中、算 `fog`）；`airports[].metar.source: "cwa"`（氣象署局屬站觀測，
  AviationWeather 的沒有這個鍵）；`slots[].official.kind` 多 `metar`（沒有 TAF 的機場第一格由 METAR 撐起，
  `wx` 是物件）
- HD16（Open-Meteo 三票）要經 Shawn 轉給 Duado 總指揮的（只加值，`schema` 維持 `1`）：頂層 `models[]` 多
  `icon`、`jma`、`wn2-ens` 三筆、**每筆多 `voting`（布林，`false` 時網頁標「旁觀，不投票」）**；
  `slots[].model.models[]` 每格 8 筆、每筆多 `p49Kt`（只有 `wn2-ens` 有值：成員比例）；`vote.total` 最多 8；
  `runs.icon`／`runs.jma`／`runs.wn2-ens`；`sources.openmeteo`（`ok`、`seconds`、`bytes`、`calls`、失敗時
  `error`、`runError`）；`warnings[].kind` 多 `jma_snowstorm_emergency`（高、算 `snow`）。資料來源頁要標
  「Open-Meteo（CC BY 4.0）・DWD ICON・JMA・Google WeatherNext 2」。完整定義在 README「輸出」的 HD16 段
- HD9（JMA 大雪警報）要經 Shawn 轉給 Duado 的（只加值）：`warnings[].source` 多 `"jma"`、`kind` 多
  `jma_heavy_snow`（中）、`jma_heavy_snow_emergency`（高）、`jma_snowstorm`（低，只列出），都算 `snow`、一定有四語
  `text`；`sources.jma`；日本 8 個＋沖繩 3 個 `official.warnings` 變 `true`。網頁 `WARNING_KINDS` 已有
  `jma_heavy_snow`，另兩個沒有也照樣顯示（有 `text`）；資料來源頁要標日本氣象廳
- HD14（多模式投票）要經 Shawn 轉給 Duado 總指揮的：頂層 `models`（`[{id, name: {四語}}]`）、
  `slots[].model.models[]`（每格 5 筆，`gustEstimated: true` 時網頁寫「估算陣風」）、`slots[].model.vote`、
  `runs.aifs`／`runs.aigfs`、`sources.aifs`／`sources.aigfs`；`model.level` 改由投票決定，`model.ec`／`gfs`／
  `agreement` 不變。完整定義在 README「輸出」的 HD14 段；資料來源要標 ECMWF AIFS（CC BY 4.0）
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
  - `GOOGLE_CLOUD_LOCATION_FALLBACK`（HD23，選填、不是 secret）：Gemini 備援區域，沒設是 `us`；`build.yml` 沒帶這個
    變數，要關掉或換區得在那一步的 `env` 加（設成空字串＝關掉）
- AI 的金鑰 HongThai 專屬、各月上限 30 美元、不跟 Duado 共用；程式內另有每報 20 個機場的上限
  （`src/hongthai/ai/config.py`）。每日上限**開發期間不限**（`DAILY_CAP=0`，2026-10-19 定案，HD11），正式推廣前再評估；
  每報 20 個機場、不重試、180 秒預算不變；手動 Run workflow 也照常跑 AI

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
| 中央氣象署開放資料（`W-C0034-001`；HD8 起加 `W-C0033-001`；HD13 起加 `O-A0003-001`） | 颱風警報（台灣十個機場，每個機場一組警戒區關鍵字）；天氣特報（大豪雨、超大豪雨、濃霧）；金門、馬祖局屬站觀測（當 METAR） | 政府資料開放授權條款；要授權碼 |
| 香港天文台開放數據（warnsum） | 熱帶氣旋信號（香港）；HD8 起加暴雨警告信號、雷暴警告 | data.gov.hk 使用條款 |
| 澳門地球物理氣象局 SMG（`xml.smg.gov.mo`，data.gov.mo 資料集「熱帶氣旋信號」） | 熱帶氣旋信號（澳門） | 澳門政府數據開放平台使用條款（須註明平台與取得日期） |
| 航班狀態（香港機管局、桃園機場、松山／高雄／澳門見 README） | 算每 6 小時格的取消／延誤統計（不存原始資料），之後回測 | 各自條款，見 README |
| 芫荽 Iansui、Fraunces、Noto Sans TC（子集，`assets/fonts/`；HD1） | 分享預覽圖的字型 | SIL OFL 1.1（各附 `OFL-*.txt`） |
| Google WeatherNext 3（BigQuery／GCS Zarr，要 allowlist；HD15） | 預設只存 5 天前那一報的機場數字與颱風路徑（報告比對） | 1 小時以前：CC BY 4.0（© Google LLC）；1 小時內或未來：GDM 即時資料實驗條款（不能公開未修改數字、日本是限制國家），細節 README「WeatherNext 3 的條款」 |

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
  沒有陣風的模式（AIFS、AIGFS、JMA GSM）用估算陣風（平均風 × G）算側風（Shawn 2026-10-20 23:33 確認維持）；
  沒有風向時側風＝風速本身
- 所有機場先同一套（`config.py` 的 `Thresholds`），之後找到個別機場的作業標準再在 `airports.json` 覆寫
- HRES 的 10 米風只抓 00／06／12／18Z 的時間點（H10，減少下載量），每個 3 小時陣風區間配結束時間往後
  最近的那個時間點的風向（最多差 3 小時）
- 跑道方位用真北（風向都是真北）；所有跑道取最小側風（假設最好的那條跑道都能用，沒算跑道關閉、
  長度、機型限制）
- 目前生效的警報只套用到開始時間早於「現在 + 12 小時」的格（警報本身沒有預報時段）
- 氣象署警戒區是關鍵字比對（「東北部」也會比到「北部」），偏保守
- EC 系集機率是 24 小時窗，6 小時格取包住它的窗的最小值
- 0–30 小時以官方為準；METAR 只算進現在那一格的側風；完全沒有 TAF 的機場第一格可由 METAR 單獨撐起（HD13）
- **三類（雨、雪、霧）門檻先照 2026-10-19 定案上線，累積一個月紀錄再調**（HD8）；**霧的模式層只有 GFS**
  （ECMWF 開放資料沒有能見度；GFS 能見度大雨時也會很低，大雨格常常同時是霧）；**模式層的霧只到中**（HD10，
  依據是模式層時同級的雨排在霧前面）；**金門馬祖沒有 TAF**（AviationWeather 沒有這兩站），HD13 起第一格用
  氣象署局屬站觀測、前 12 小時看濃霧特報，之後的格霧只有 GFS；局屬站不在跑道旁，能見度又是描述字串（`<1`
  只能判到中）
- 低的警報（紅雨、雷暴、天文台 1 號信號）不會自己撐起官方層（HD8）
- 已經過去的 TAF 時段不算（HD7，2026-10-19，`docs/prompts/2026-10-19-HD7-taf-past-periods.md`）：TAF 各時段
  只算結束時間在產出時間之後的，只影響第一格；第一格的 TAF 時段全部過去時當作沒有 TAF（有警報走「只有警報」
  的路、METAR 側風照算，沒有警報退回模式）。起因是關島 10/19 03:57Z 那報第一格被 02–03Z 的 TEMPO 判高
- 2026-10-19 HD7 前的第一格官方層可能含已過去的 TEMPO
  （HD7 合併後第一份的 `generatedAt`：**2026-10-19T05:25:00Z**，台北 13:25）。`history/*.json` 不重算；回看戰績
  （`history/ai/`、`history/cancellations/`）時 `run` 在 05:25Z 之前的第一格要打折看。實際上 HD7 合併後第一報只有
  GUM 第一格 high → low，其他 50 個機場第一格沒變，`run_cap` 4 個，沒有預期中的一次性大量

### 來源逾時與沿用（H7，2026-10-18 build #4 被 ECMWF 429 卡到被砍之後）

- 每個來源有時間預算（`build.py` 的 `BUDGET_S`：ecmwf 300（H10 起，原 240）、gfs 180、aifs 180、aigfs 120
  （HD14）、openmeteo 90（HD16）、taf 45、hko 30、smg 30、cwa 45、nws 30（HD3）、jma 45（HD9）、flights 120、
  ai 240（HD12 起，原 180，HD5）、og 60（HD1）、tracks 150（HD21，只在事件期間）秒，總和 1665 秒＝27.75 分鐘），
  超過記 `error: "timeout"` 繼續跑下一個；Actions 那一步 30 分鐘、job 40 分鐘（HD16 前 28／38、HD21 前 25／35、
  HD14 前 20／30、HD12 前 18／28、HD5 前 15／25）
- ECMWF 重試最多 3 次、間隔 10 秒、不照 Retry-After；找最新一報先問入口、下載先試 AWS 鏡像
  （→ 入口 → Google；AWS 下載不重試，S3 的 503 Slow Down 一來就換），`sources.ecmwf.mirror` 記實際來源。`ecmwf-opendata` 最低 0.3.34（有重試參數）
- GFS（H10）：先 AWS 開放資料鏡像（`.idx`＋HTTP `Range` 只抓三筆），失敗才 NOMADS（2026-10-18 12:42Z 起
  NOMADS 對 Actions 回 403）；`sources.gfs.mirror` 與 timing 的 gfs 那行記 `aws`／`nomads`
- ECMWF HRES（H10）：每個步長只有一個陣風參數（`10fg` 或 `10fg3`，不能只抓 `10fg3`）；`10u`／`10v`
  只抓 6 小時整的步長，一報從約 112 MB 降到約 82 MB（目標 70 MB 沒達到，見 PR 說明）
- `ecmwf`／`gfs`／`aifs`／`aigfs` 失敗時沿用「最近一份有該模式資料」的同機場同格 `model.ec`／`model.gfs`
  （AIFS、AIGFS 是 `model.models[]` 同 `id` 那筆的數字，HD14），等級與投票照常算。**`openmeteo`（HD16）不沿用**：
  失敗那報 ICON、JMA GSM、WN2 三筆是 `null`、不算分母。
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
  NWS 是 HD3 起）；`<HHMM>Z-cwa-hazards.json` 是氣象署天氣特報 `W-C0033-001`（HD8 起）；
  `<HHMM>Z-cwa-obs.json` 是金門、馬祖的局屬站觀測 `O-A0003-001`（HD13 起）
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
  不存短評；`history/ai/calls-<YYYY-MM-DD>.json`：每個模型今天（UTC）呼叫了幾次（每日上限用；開發期間不限、照常記，評估用量用）。
  11/18 拿戰績對 `history/cancellations/` 回看誰事前比較準

GitHub Pages（`public/`）只放 `latest.json` 與**最近 7 天**的 `history/<時間>.json`（H9 起，一份約 515 KB；HD3 起約 642 KB，2026-10-18 實測；
`build.py` 的 `PAGES_HISTORY_DAYS`，Shawn 確認中），以及分享預覽圖 `og/<iata 小寫>.png`（HD1，每報重畫，
不留歷史），不放原始快照與航班統計。`data` 分支的 `history/<時間>.json` 照舊全部保留；`og/` 不進 `data` 分支。

## 《氣象法》（2026-10-21 定案）

- 第 17、18 條：全國預報由氣象署發布；未經許可不能發布預報，颱風、豪雨預報有許可也不能發；第 24 條先命停止、限期改善，不改才罰
- HongThai 的燈號與 AI 評論照常（Shawn：賣點），已寄詢問信，等氣象署書面回覆；網頁加氣象署 Q&A 第 16 題標準字樣、每句註明出處
- **AI 評論之後要逐句附出處**（29W 報告後的 HD）；資料端新增對外文字時，不要把 HongThai 的產出叫「預報」
