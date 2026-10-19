# HD8：第五階段——新天氣種類（大雨／雷雨、大雪／結冰、濃霧）

模型：Opus，強度高。這是第五階段的主體，改的面很廣：`src/hongthai/sources/taf.py`（能見度、天氣現象、雲底）、
`sources/ecmwf.py`／`sources/gfs.py`／`grib.py`（多抓降水、降水型態、溫度、能見度）、`sources/hko.py`／`sources/cwa.py`
（暴雨、雷暴、豪雨特報）、`assess.py`（三類新規則、`causes`）、`config.py`（門檻）、`build.py`（輸出）、`og.py`
（燈號小字加主因）、`ai/prompt.py`／`ai/config.py`（短評要說出天氣種類、用字對照）、測試、README、ORCHESTRATOR。
**`latest.json` 既有欄位不改名、不改型別、不拿掉；只加本文列的欄位**，欄位名照本文（Shawn 會轉給 Duado 寫進 spec）。
硬期限：12 月北海道下雪前上線，所以**先求能跑、門檻之後用一個月紀錄再調**。

先讀 `docs/ORCHESTRATOR.md`「已經做過的決定」第五階段那段與「已知的保守假設」、`src/hongthai/assess.py` 全部（開頭
docstring 是規則說明）、`sources/taf.py`、`sources/ecmwf.py` 開頭說明與 `fetch`、`sources/gfs.py` 開頭說明與 `IDX_FIELDS`、
`grib.py`、`sources/hko.py`、`sources/cwa.py`、`og.py` 的 `rule_light`、`ai/prompt.py` 的 `SYSTEM` 與 `airport_text`、
`tests/test_assess.py`、README「怎麼算」「輸出」。`data` 分支（`git fetch origin data`）有原始快照：
`history/raw/<日期>/<時間>-taf.json`（AviationWeather 回傳原文，看 `visib`、`wxString`、`clouds`、`vertVis` 長什麼樣）、
`-hko.json`、`-cwa.json`。

## 0. 定案（Shawn 2026-10-19，不要改）

- 三類：`rain`（大雨＋雷雨）、`snow`（大雪＋結冰）、`fog`（濃霧＋低雲幕）。**燈號維持「停飛風險」一種等級**，不是一種
  天氣一顆燈；種類只用在依據（`causes`）、預覽圖小字與 AI 短評。颱風帶來的雨歸 `wind`（也就是現有規則），不另算
- 原則：**貼近實際會停飛的情況，只會延誤的不升級、只寫進依據**
- 官方層（TAF／METAR）門檻：
  - `rain`：單純 TS、TSRA、SHRA 不升級；**+TSRA**，或 **TS 且能見度 ≤ 1600 公尺** → 中；**TSGR／GR（冰雹）** → 高
  - `snow`：-SN 不升級；**SN 且能見度 ≤ 1600 公尺** → 中（SN 但能見度 > 1600 不升級）；**+SN** → 高；
    **FZRA／FZDZ／PL** → 高；FZFG 不走 snow，走 fog 的能見度門檻
  - `fog`：**能見度 < 1000 公尺或雲底 ≤ 200 呎** → 中；**能見度 < 400 公尺或雲底 ≤ 100 呎** → 高（任何原因的低能見度
    都算，FG／BR／FZFG／HZ／SN 造成的都一樣）；METAR 只套第一格（同現在的側風規則）
- 模式層（先照這套上線）：`rain` HRES 6 小時雨量 ≥ 30 mm 或系集 24 小時 ≥ 50 mm 的機率 ≥ 30% → 中、6 小時 ≥ 60 mm
  → 高；`snow` 降水型態是雪且 6 小時水當量 ≥ 5 mm → 中、≥ 10 mm → 高，型態是凍雨且 ≥ 1 mm → 高（小雪不升級，和官方層
  一致）；`fog` 只有 GFS 能見度 < 1000 公尺 → 中、< 400 公尺 → 高
- 官方警報加：天文台**黑雨 → 中**，紅雨、雷暴警告**不升級、只列出**；氣象署**大豪雨以上特報**（大豪雨、超大豪雨）且機場
  在範圍 → 中（大雨、豪雨特報不算）。JMA 大雪警報**另開 HD9**，這支不做；澳門、韓國、越南、菲律賓這階段不加
- 單位：雨量毫米、能見度公尺、雲底呎、溫度 °C（ORCHESTRATOR 早就定的）

## 1. TAF／METAR 多解析三樣（`sources/taf.py`）

AviationWeather 的 `fcsts[]` 與 METAR 回傳已經解碼好：`visib`（**法定英里**，數字或字串 `"6+"`／`"10+"`；公制 TAF 的
`9999` 會變 `"6+"`、`0800` 會變 `0.5` 之類，請用 `data` 分支的快照核對）、`wxString`（例如 `+SHRA`、`TSRA`、`FZFG`、
`-SN BR`，可能多個用空白隔開、可能 null）、`clouds[]`（`cover`：FEW／SCT／BKN／OVC／CLR…，`base` 呎）、`vertVis`（呎）。

- `TafPeriod` 與 `Metar` 各加 `vis_m: int | None`（公尺，1 法定英里＝1609 公尺，四捨五入到整數；`"6+"`／`"10+"`
  這種「以上」記 **9999**）、`wx: tuple[str, ...]`（`wxString` 拆開、原樣大寫，沒有就空 tuple）、`ceiling_ft: int | None`
  （BKN／OVC 裡最低的 `base`，或 `vertVis`，兩者取小；沒有就 None）
- 現有欄位、現有測試全部不動；`history/raw` 的格式不變（本來就是原文）

## 2. 模式層多抓（`sources/ecmwf.py`、`sources/gfs.py`、`grib.py`）

**先在本機（或雲端對話裡）確認參數真的在，再寫程式**；確認不到的（例如 ECMWF 開放資料真的沒有能見度）就照本文的備案，
並把查到的寫進 README「資料來源」。

ECMWF 開放資料（HRES `oper`）：
- 多抓 `tp`（總降水，累積自起報，單位 m → 換成 mm；6 小時雨量＝`tp(step) − tp(step − 6)`）、`ptype`（降水型態，瞬時：
  0 無、1 雨、3 凍雨、5 雪、6 濕雪、7 雨雪混合、8 冰粒、12 凍毛毛雨——以 ECMWF 文件為準，雲端查一次寫進程式註解）、
  `2t`（2 米溫度，K → °C）。**三個都只抓 6 小時整的步長**（和 `10u`／`10v` 一樣用 `wind_steps`，H10 的省下載量原則），
  一格用「格結束時間那個步長」的 `tp` 差值、`ptype`、`2t`
- 系集（`enfo`／`ep`）多抓 `tpg25`、`tpg50`（24 小時總降水 ≥ 25／50 mm 的機率；和 `10fgg*` 同一套 24 小時窗、同一個
  `ens_windows`）；`ProbWindow` 加 `tp25`、`tp50`
- `GustInterval`（或另開一個 6 小時的 dataclass，你決定，但 `EcmwfPoint` 要能給 `assess` 每格一組
  `rain6hMm`／`ptype`／`temp2mC`）
- 預估多 40–50 MB（每個參數每步長約 0.7–0.9 MB × 21 步 × 3）；ECMWF 的預算是 300 秒，目前約 100 秒。**實測回報總秒數
  與 bytes；超過 200 秒就只抓 `tp`＋`ptype`、`2t` 不抓**（溫度只是參考，不進規則）

GFS（AWS `noaa-gfs-bdp-pds`，`.idx` 位元組範圍）：
- `IDX_FIELDS` 多 `APCP:surface`（6 小時累積——GFS 在 6 小時整的檔裡 APCP 是「前 6 小時」的桶，`.idx` 的字樣像
  `APCP:surface:0-6 hour acc fcst`／`6-12 hour acc fcst`，請用 `.idx` 實際字串比對，f000 沒有）、`CSNOW:surface`、
  `CFRZR:surface`、`CICEP:surface`、`CRAIN:surface`（類別 0／1，瞬時）、`VIS:surface`（公尺）。kg/m² ＝ mm
- `GustPoint` 加 `rain6h_mm`、`ptype`（由四個類別合成：CFRZR → `freezing_rain`、CICEP → `ice_pellets`、CSNOW → `snow`、
  CRAIN → `rain`、都 0 → `none`；優先順序照這個，凍雨最嚴重）、`vis_m`
- NOMADS 備援的 `var_*` 一起加。預估多 30–40 MB；GFS 預算 180 秒，目前約 40 秒

## 3. 規則（`assess.py`、`config.py`）

`Thresholds` 加（`airports.json` 的 `thresholds` 可覆寫，鍵名用 camelCase 同現有的）：
`tafRainMediumVisM: 1600`、`tafSnowMediumVisM: 1600`、`fogMediumVisM: 1000`、`fogHighVisM: 400`、`fogMediumCeilingFt: 200`、
`fogHighCeilingFt: 100`、`modelRainMediumMm6h: 30`、`modelRainHighMm6h: 60`、`ecP24hRain50Medium: 0.3`、
`modelSnowMediumMm6h: 5`、`modelSnowHighMm6h: 10`、`modelFreezingRainHighMm6h: 1`。模式的霧用同一組 `fog*VisM`。

官方層，每格（只算 HD7 定義的「還有效且重疊」的時段，METAR 只進第一格、觀測 3 小時內、且該格本來有官方資料）：
- `rain`：任一時段 `wx` 含 `GR`（TSGR、+TSGR、GR、SHGR）→ 高；含 `+TSRA`（或 `+TS` 開頭且含 RA）→ 中；含 `TS` 且該時段
  `vis_m ≤ tafRainMediumVisM` → 中；其他 → 低
- `snow`：含 `FZRA`、`FZDZ`、`PL`（任何強度）→ 高；含 `+SN`（含 `+SHSN`）→ 高；含 `SN`（不是 `-SN`、不是 `+SN`，含 `SHSN`）
  且 `vis_m ≤ tafSnowMediumVisM` → 中；其他 → 低。`FZFG` 不在這裡
- `fog`：該時段 `vis_m < fogHighVisM` 或 `ceiling_ft ≤ fogHighCeilingFt` → 高；`vis_m < fogMediumVisM` 或
  `ceiling_ft ≤ fogMediumCeilingFt` → 中；其他 → 低。`vis_m` 是 None（沒報）不算
- 一格的 `official.level` ＝ 現有（陣風、側風、警報）與 `rain`／`snow`／`fog` 三個等級取最高；`official.kind` 維持現在的意思
  （風的時段種類），不要動
- 警報：天文台黑雨 `rainstorm_black`（`level: "medium"`）、紅雨 `rainstorm_red`、雷暴 `thunderstorm`（這兩個
  `level: "low"`，**只列出**）；氣象署 `cwa_heavy_rain`（大豪雨、超大豪雨，`level: "medium"`）。**`level: "low"` 的警報
  不會自己撐起官方層**：一格只有「低」的警報、沒有 TAF 時，`official` 維持 `null`、退回模式（不然黑雨以外的雷暴警告會把
  模式層蓋掉）；有 TAF 或有中以上警報時照現在的邏輯，`official.warnings[]` 列全部（含低的）

模式層，每格：
- `rain`：EC `rain6hMm ≥ modelRainHighMm6h` 或 GFS `rain6hMm ≥ modelRainHighMm6h` → 高；EC 或 GFS `≥ modelRainMediumMm6h`，
  或 EC 系集 `p24hRain50 ≥ ecP24hRain50Medium`（24 小時窗對 6 小時格取包住它的窗的最小值，同 `p49Kt` 的做法）→ 中
- `snow`：EC `ptype` 是 `snow`／`wet_snow`／`rain_snow` 且 `rain6hMm ≥ modelSnowHighMm6h` → 高、`≥ modelSnowMediumMm6h` → 中；
  `ptype` 是 `freezing_rain`／`freezing_drizzle`／`ice_pellets` 且 `rain6hMm ≥ modelFreezingRainHighMm6h` → 高。GFS 同一套
  （`ptype` 來自類別欄位）。EC 與 GFS 取較高
- `fog`：只有 GFS `vis_m`，套 `fog*VisM`；EC 沒有能見度所以不算
- `model.level` ＝ 現有陣風／側風與三類取最高；**`model.agreement` 維持只看陣風**（不改它的值域；README 寫清楚
  「一致性只看風」）

`causes`（每格）：從決定 `level` 的那一層（`basis` 是 `official` 就看官方層、`model` 就看模式層）把等級 ≥ 中的種類列出，
`wind`（陣風或側風達中以上）、`rain`、`snow`、`fog`；**依該種類的等級高的在前，同級照 `wind`、`snow`、`fog`、`rain` 的固定
順序**，第一個就是主因；都沒有（低）→ `[]`；`basis` 是 `confirmed` 時照它蓋掉前那一層算；`unknown` → `[]`。`gap` 的定義
不變（官方與模式的 `level` 不同）。

## 4. 輸出（`build.py`；欄位名定案，Shawn 轉給 Duado）

- `slots[].causes`：字串陣列（見上）
- `slots[].official.wx`：有 TAF 時是物件，`{"phenomena": ["+TSRA", "BR"], "visibilityM": 800, "ceilingFt": 200,
  "rain": "low", "snow": "low", "fog": "medium"}`——`phenomena` 是該格有效時段（含第一格的 METAR）所有 `wx` 去重、照出現
  順序；`visibilityM` 是最小能見度（9999＝以上）、`ceilingFt` 最低雲底，沒報就 `null`；三個等級永遠是字串。
  官方層只有警報（沒 TAF）時 `wx` 是 `null`
- `slots[].model.ec` 多 `rain6hMm`（數字一位小數或 `null`）、`ptype`（字串：`none`／`rain`／`freezing_rain`／`snow`／
  `wet_snow`／`rain_snow`／`ice_pellets`／`freezing_drizzle`，其他代碼 `other`；沒資料 `null`）、`p24hRain25`、`p24hRain50`
  （0–1 或 `null`，同 `p10`）、`temp2mC`（一位小數或 `null`）、`rain`／`snow`（等級字串或 `null`）
- `slots[].model.gfs` 多 `rain6hMm`、`ptype`（同上的值域）、`visibilityM`（整數公尺或 `null`）、`rain`／`snow`／`fog`
  （等級字串或 `null`）
- `airports[].official.warnings` 與 `airports[].warnings[]`：`kind` 多 `rainstorm_black`、`rainstorm_red`、`thunderstorm`
  （`source: "hko"`，`code` 放 `WRAINB`／`WRAINR`／`WTS` 之類的原代碼）、`cwa_heavy_rain`（`source: "cwa"`，`detail` 放
  特報等級字樣）；四語 `text` 照 HKO 三語＋英文、CWA 的中文用三語寫法（同現有颱風警報的做法）
- `airports[].taf`、`airports[].metar` 各多 `visibilityM`、`wx`（字串陣列）、`ceilingFt`（METAR 是觀測值；TAF 是主時段的）
- `schema` 維持 `1`（只加欄位）。`latest.json` 大概會多 100–150 KB，回報實際大小
- `history/*.json` 自然帶新欄位；`cancellations`、`history/ai/` 戰績格式不變

## 5. 來源：天文台暴雨／雷暴、氣象署豪雨特報（`sources/hko.py`、`sources/cwa.py`）

- 天文台 `warnsum` 同一次請求裡的 `WRAIN`（`code` `WRAINA`／`WRAINR`／`WRAINB`）與 `WTS`；只有黑雨是中，其餘低。
  `hko` 的預算 30 秒不變（沒多請求）
- 氣象署天氣特報：平台的「天氣特報」資料集（`W-C0033-001` 各別縣市目前之天氣警特報、或 `W-C0033-002` 各別特報內容與
  影響區域——**看文件挑一個**，寫進程式開頭說明），同一把 `CWA_API_KEY`；用 `airports.json` 既有的 `cwaAreas` 關鍵字比對
  縣市名；只有「大豪雨」「超大豪雨」才產生警報（`detail` 記字樣）。`cwa` 預算 45 秒夠（多一個請求）；失敗時豪雨這部分
  記 error、不影響颱風警報那條（分開 try）
- 兩者都進 `history/raw/<日期>/<時間>-hko.json`／`-cwa.json`（看現有怎麼存就怎麼存）

## 6. 預覽圖與 AI 短評（`og.py`、`ai/`）

- `og.rule_light` 的小字：最高等級那格 `causes[0]` 對應的中文接在後面，`wind` 強風、`rain` 大雨、`snow` 大雪、`fog` 濃霧
  （「最高：高　10/23 08–14 時・強風」，用全形間隔號「・」）；`causes` 空時不加；全部低時維持「未來 5 天：低」。
  字型子集要有這幾個字（芫荽子集加「強雨雪濃霧・」，看 `tools/make_font_subset.py`），涵蓋測試一起更新
- `ai/prompt.py`：`airport_text` 每格多給 `causes`、官方層 `wx`（現象、能見度、雲底）、模式層的雨量／型態／能見度（給模型看
  的標籤維持代號；「說明」那段補一句「短評要說出主要是哪種天氣造成：強風／側風、大雨／雷雨、大雪／結冰、濃霧／低雲」）。
  `SYSTEM` 規則加一條「短評第一句要點出主因天氣」；「用字」對照表補：zh-CN 濃霧→浓雾、能見度→能见度、雲底→云底、
  結冰→结冰、冰雹→冰雹、雷雨→雷雨、大雪→大雪；zh-HK 同台灣寫法
- `ai/config.py`：`TRADITIONAL_CHARS` 加「霧」「見」，`SIMPLIFIED_CHARS` 加「雾」「见」；`FORBIDDEN_TOKENS` 加 `ptype`、
  `rain6hMm`、`visibilityM`、`ceilingFt`、`causes`、`p24hRain25`、`p24hRain50`、`APCP`、`CSNOW`、`CFRZR`
- 選機場（`select.py`）、每日上限、戰績格式不變

## 7. 金門、馬祖（這階段最重要的霧案例）——先查、回報、不要硬做

`RCBS`（金門）、`RCFG`（馬祖）在 AviationWeather **沒有 TAF 也沒有 METAR**（H9 實測），所以它們的霧目前只會有 GFS
的模式層。請花最多 30 分鐘查：(a) NOAA `tgftp.nws.noaa.gov/data/observations/metar/stations/RCBS.TXT`、
`.../forecasts/taf/stations/RCBS.TXT` 有沒有；(b) 氣象署開放資料哪個資料集有金門、馬祖的**能見度**觀測（例如局屬站
現在天氣觀測報告 `O-A0003-001` 有沒有能見度欄位；金門站、馬祖站的站號）。**只回報結果、附文件連結，不實作**，主對話會
決定要不要開一支接進來。

## 8. 測試與文件

- `tests/test_taf.py`（或現有放 TAF 的檔）：`visib` 數字／`"6+"`／`"10+"`／`0.5` 的換算、`wxString` 拆分、雲底取最低
  BKN／OVC 與 `vertVis`；用 `data` 分支真實快照的幾段當 fixture
- `tests/test_assess.py`：三類官方層各等級至少一個案例（+TSRA 中、TSGR 高、TS 且 1600 公尺 中、TSRA 不升級；SN 1600 中、
  -SN 不升級、+SN 高、FZRA 高；能見度 800 中、300 高、雲底 200 中、100 高、FZFG 走 fog）；模式層三類各等級；
  `causes` 的排序（同級固定順序、主因在前、`confirmed`、`unknown`）；低的警報不撐起官方層；`official.level` 與風的規則取
  最高；既有的風測試一個都不能改結果
- `tests/test_og.py`：小字有「・濃霧」等；字型涵蓋
- `tests/test_ai.py`：`airport_text` 有 `causes` 與 wx；新代號進 `bad_wording`；「浓雾」「见」的簡繁檢查
- README：「怎麼算」加三類的表（官方、模式、警報、`causes`）、「輸出」加第 4 節的欄位、「資料來源」加 ECMWF／GFS 新參數與
  天文台／氣象署新資料集、「已知的保守假設」加「三類門檻先照 2026-10-19 定案上線，累積一個月再調」「霧的模式層只有
  GFS」「金門馬祖沒有 TAF／METAR」。`docs/ORCHESTRATOR.md` 第五階段那條補「已實作（HD8 PR）」與和提示詞不一樣的地方

## 回報時要附

- ECMWF／GFS 實際多抓的參數清單、每個的大小與總秒數；參數不存在時用了什麼備案
- 用 `data` 分支最近一份的原始快照跑一遍：哪些機場哪些格因為新規則升級、`causes` 長什麼樣（至少列 10 格）；如果一個都沒有
  升級，用測試 fixture 造一個霧與一個雪的例子貼出來
- 第 7 節金門、馬祖的查證結果
- `latest.json` 的新大小；`og/tpe.png` 一張的小字

本機 `ruff check .`、`ruff format --check .`、`pytest -q` 全過才推，盡量一次推完。
開 PR 之後：`gh pr checks --watch` 等 CI，紅了自己修並推到同一個分支（最多三輪），全綠時告訴我；
不要自己合併，我會先請主對話審查。
