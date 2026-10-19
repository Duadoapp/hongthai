# HD14：多模式投票——模式層改成投票，加 ECMWF AIFS Single 與 NOAA AIGFS（5 票）

模型：Opus，強度高。改的面廣：新來源 `src/hongthai/sources/aifs.py`、`sources/aigfs.py`、`grib.py`（共用）、`assess.py`
（投票）、`config.py`（模式清單、係數）、`build.py`（輸出、沿用、timing、預算）、`.github/workflows/build.yml`（上限）、
`ai/prompt.py`／`ai/config.py`（短評吃 `models[]`、「估算陣風」）、測試、README、`docs/ORCHESTRATOR.md`。
**`latest.json` 既有欄位不改名、不改型別、不拿掉**：`model.ec`、`model.gfs`、`model.agreement` 原樣保留（值也照舊算），
只加 `model.models[]`、`model.vote`、頂層 `runs.aifs`／`runs.aigfs`、`sources.aifs`／`sources.aigfs`。`model.level` 改由投票決定。

先讀 `docs/ORCHESTRATOR.md`「多模式投票」那段、`src/hongthai/assess.py` 全部（開頭 docstring、`ec_for_slot`、`gfs_for_slot`、
`model_levels`、`model_level`、`fill_model_wx`、`slot_causes`）、`sources/ecmwf.py`（`ecmwf-opendata` 的用法、AWS 鏡像、
`wind_steps`）、`sources/gfs.py`（`.idx` 位元組範圍、`IDX_FIELDS`／`IDX_OPTIONAL`、NOMADS 備援）、`grib.py`、`build.py`
（`REUSE_FIELDS`、`_rescore`、`BUDGET_S`、`_call`、`runs`／`sources`／`timing` 怎麼寫）、`ai/prompt.py` 的 `airport_text`、
`tests/test_assess.py`、`tests/test_build.py`、README「怎麼算」「輸出」「資料來源」。

## 0. 定案（Shawn 2026-10-19，不要改）

- 模式層改**投票**：每個模式一票、權重相同。某等級 L 的票＝「等級 ≥ L」的模式數，**≥ 分母一半就成立**（2 票裡 1 票也成立，
  和現在兩模式取較高一致），取成立的最高等級。分母＝該格**有資料**的模式。只有 1 個模式有資料就它決定；分母 < 2 →
  `vote.thin: true`
- 第一批 5 票：**IFS**（現有 HRES）、**GFS**（現有）、**IFS 系集**（現有 `p49Kt`）、**AIFS Single**（新）、**AIGFS**（新）。
  AIGEFS、WeatherNext 2 不做；WeatherNext 3（HD15）、Open-Meteo 的 ICON＋JMA（HD16）之後各一支
- **IFS 系集只參加「高」的投票**：`p49Kt ≥ ecP49High`（30%）投高、否則投低；**判「中」時它不算分母**（不然它永遠投低、把中
  級的票數拉下來）
- **沒有陣風的模式**（AIFS、AIGFS）：10 米平均風 × **1.4** 估算陣風（`config.GUST_FACTOR = 1.4`，可調），標 `gustEstimated: true`；
  網頁與短評寫「估算陣風」；係數累積一個月再檢討。側風用平均風（同現有做法：有陣風用陣風、沒有用平均風——這裡用估算陣風）
- 三類（雨、雪、霧）各自投票、再和風取最高；`causes` 照舊（模式層同級順序 wind、snow、rain、fog）
- 官方層（TAF、METAR、警報）照舊優先，投票只取代模式層；`gap` 照舊
- 欄位：不動 `model.ec`／`gfs`／`agreement`；新增 `model.models[]`、`model.vote`

主對話補的細節（Shawn 沒另外定、照這樣做）：
- **雪的投票只讓有降水型態的模式參加**：IFS（`ptype`）、GFS（類別降水）、AIFS（有 `sf` 降雪量：6 小時降雪 ≥ 6 小時總降水的
  一半 → `ptype: "snow"`，否則 `rain`，沒降水 `none`）；AIGFS 沒有型態、不投雪（雪的分母不算它）。不要用 2 米溫度猜型態
- **霧**只有 GFS 有能見度（照 HD8／HD10），所以霧的分母永遠是 1、`thin` 會是 true——這是預期的
- 雨：五個模式裡 IFS 系集不投雨（它只投「高」的風）；AIFS、AIGFS 投雨（6 小時雨量門檻同現有 `modelRain*`）
- 模式 `id`：`ifs`、`gfs`、`ifs-ens`、`aifs`、`aigfs`（之後 `wn3`、`icon`、`jma`）

## 1. 新來源

### 1a. ECMWF AIFS Single（`sources/aifs.py`）
- `ecmwf-opendata` 的 `Client` 支援 `model="aifs-single"`（查套件文件／原始碼確認參數名），`stream="oper"`、`type="fc"`、
  `resol="0p25"`；參數 `10u`、`10v`、`tp`、`2t`、`sf`（降雪量，累積，m）；**6 小時步長**到 120 小時（第一格開始步長也要，算
  6 小時雨量差）。一天 4 報（00／06／12／18Z）。`latest()`／下載的鏡像順序、重試、`Cancelled`、`budget` 全部**沿用 `ecmwf.py`
  的寫法**（能共用就抽成共用函式，不要複製一份）；AWS 鏡像 `ecmwf-forecasts` 有沒有 `aifs-single` 路徑請實際確認，沒有就
  `ecmwf` → `google`
- 解析：`grib.read_points` 讀 51 個點；每個 6 小時步長一筆 `AifsStep(valid, wind_kt, wdir, rain6h_mm, snow6h_mm, temp2m_c)`；
  陣風＝`wind_kt × GUST_FACTOR`（在 `assess` 算、不在來源算）
- `history/raw` 不存 GRIB（同 ECMWF）；`timing` 一行 `source: "aifs"`（`ok`、`seconds`、`bytes`、`mirror`）；`runs.aifs`
- 預算 `BUDGET_S["aifs"] = 180`；估 50 MB、40–60 秒。**實測回報**

### 1b. NOAA AIGFS（`sources/aigfs.py`）
- AWS 開放資料 `noaa-nws-graphcastgfs-pds`（公有領域）：**正式 AIGFS 的路徑與檔名要先用 `aws s3 ls --no-sign-request` 查**
  （2026-05 起正式 AIGFS 在這個 bucket；舊的實驗版在 `graphcast.YYYYMMDD/HH/forecast_13_levels/`，檔名像
  `graphcastgfs.t00z.pgrb2.0p25.f006`，每個 GRIB2 有 `.idx`）。查到的路徑寫進模組開頭說明。NOMADS 備援：
  `/pub/data/nccf/com/aigfs/prod/`（有沒有 `filter_aigfs` 裁區 CGI 也查一下，沒有就不做備援、只 log）
- `.idx` 位元組範圍抓 `UGRD:10 m above ground`、`VGRD:10 m above ground`、`APCP:surface`（累積方式照 `.idx` 的字樣判斷：是
  「0-6 hour acc」每步重置、還是從起報累積，**兩種都要能算出 6 小時雨量**）、`TMP:2 m above ground`；**沿用 `gfs.py` 的
  `byte_ranges`／`_fetch_aws` 寫法**（抽共用）；6 小時步長到 120 小時；一天 4 報
- 一筆 `AigfsStep(valid, wind_kt, wdir, rain6h_mm, temp2m_c)`；`timing` `source: "aigfs"`；`runs.aigfs`；預算
  `BUDGET_S["aigfs"] = 120`；估 55 MB、40 秒。**實測回報**

### 1c. 沿用（H7）
- `REUSE_FIELDS` 加 `aifs`、`aigfs`（從最近一份 ok 的 history 抄 `models[]` 裡對應那筆的數字；`ok` 維持 false＋`reusedFrom`），
  `_rescore` 重算投票、`model.level`、`causes`、`gap`

## 2. 投票（`assess.py`、`config.py`）

- `config.MODELS`：有序清單 `[{"id": "ifs", "name": {四語}}, {"id": "gfs", …}, {"id": "ifs-ens", …}, {"id": "aifs", …},
  {"id": "aigfs", …}]`，四語名：IFS「歐洲中期預報中心 IFS／ECMWF IFS」、GFS「美國 GFS／NOAA GFS」、IFS 系集「歐洲系集／
  ECMWF ensemble」、AIFS「歐洲 AI 模式 AIFS／ECMWF AIFS」、AIGFS「美國 AI 模式 AIGFS／NOAA AIGFS」（zh-HK 同 zh-TW、
  zh-CN 簡體）。之後加模式只改這裡＋一個來源檔
- 每格先把每個模式整理成一筆 `ModelSlot`：`gustKt`（IFS／GFS 實際、AIFS／AIGFS 估算）、`gustEstimated`、`crosswindKt`、
  `rain6hMm`、`ptype`、`visibilityM`、`levels: {wind, rain, snow, fog}`（各自可 None＝這個模式這一類沒資料）、`level`（四類取最高）。
  IFS 系集那筆：`levels.wind` 只有 `high`／`low`（`p49Kt` 門檻），其他三類 None；數字欄位 null
- `vote(levels: list[str | None])`：分母＝非 None 的數；對 L in (high, medium, low)：票數＝等級 ≥ L 的數，票數 × 2 ≥ 分母 → 成立；
  取成立的最高；分母 0 → None。**判 medium 時把 IFS 系集排除在分母外**（實作：IFS 系集的 `levels.wind` 在 medium 那一輪視為
  None；寫成清楚的規則、不要硬編 id——例如 `ModelSlot.votes_only_high: bool`）
- 四類各投一次 → `model.vote = {"total": <風那一類的分母>, "high": <投高的數>, "medium": <等級 ≥ 中的數>, "low": <投低的數>,
  "level": <四類投票結果取最高>, "thin": <風的分母 < 2>}`；`model.level = vote.level`；`model.agreement` 照舊只看 IFS 與
  GFS 的陣風；`gap` 照舊
- `fill_model_wx`、`model_levels` 改成由 `models[]` 推導；`model.ec`／`model.gfs` 的 `rain`／`snow`／`fog` 欄位值照舊
- `slot_causes`：依據是模式層時用**投票後**各類的等級排序（同級 wind、snow、rain、fog）

## 3. 輸出（`build.py`；欄位定案，Shawn 轉給 Duado）

- `slots[].model.models[]`：照 `config.MODELS` 順序，每筆 `{"id": "aifs", "run": "2026-10-19T12:00:00Z", "gustKt": 31.2,
  "gustEstimated": true, "crosswindKt": 18.4, "rain6hMm": 3.1, "ptype": "rain", "visibilityM": null,
  "levels": {"wind": "low", "rain": "low", "snow": "low", "fog": null}, "level": "low"}`；該模式這一報沒資料時仍出現，數字全 null、
  `levels` 全 null、`level` null。`name` **不放在每格**（太肥），放頂層 `models: [{id, name:{四語}}]`（新頂層欄位，照
  `config.MODELS`）
- `slots[].model.vote`：見第 2 節，`level` 可 null（全無資料）
- 頂層 `runs.aifs`、`runs.aigfs`（ISO 時間或 null）；`sources.aifs`、`sources.aigfs`（`ok`、`seconds`、`bytes`、`mirror`、`error`、
  `reusedFrom` 同 ecmwf／gfs 的寫法）
- `schema` 維持 1。`latest.json` 預估多 400–500 KB（每格 5 筆 `models[]`），回報實際大小；`history/*.json` 自然帶

## 4. 預算與 workflow

- `BUDGET_S` 加 `aifs: 180`、`aigfs: 120`，總和 1080 → 1380 秒（23 分鐘）；`.github/workflows/build.yml`「產生 latest.json」
  `timeout-minutes` 20 → **25**、job 30 → **35**；README「時間預算」表與總和、`build.py` 註解、ORCHESTRATOR「來源逾時與沿用」同步
- 來源是一個接一個跑的，整趟會多約 2 分鐘；回報合併後第一報的 `timing` 總秒數

## 5. 預覽圖與 AI 短評

- `og.py` 不用改（等級與 `causes` 照舊）
- `ai/prompt.py`：`airport_text` 每格的模式那段改成列 `models[]`（每個模式一行：名稱、陣風（估算的標「估」）、側風、雨量、型態、
  等級）加一句「投票：5 個模式中 3 個認為高 → 高」；「說明」那段補：估算陣風要寫「估算陣風」（en "estimated gust"）、投票句
  可以寫進短評（「五個模式中三個認為高」）、模式名用白話（歐洲 AI 模式、美國 AI 模式）
- `ai/config.py`：`FORBIDDEN_TOKENS` 加 `gustEstimated`、`AIGFS`、`AIFS`（整字；模式要用白話名）；用字對照 zh-CN「估算→估算、
  模式→模式、投票→投票」不用加；測試一則用了 `AIFS` 的短評 → `bad_wording`

## 6. 測試與文件

- `tests/test_vote.py`（新）：分母 2 票 1 高 1 低 → 高（和現在取較高一致）；3 票 1 高 2 中 → 中（高 1×2 < 3；中 3×2 ≥ 3）；
  4 票 2 高 → 高；IFS 系集投低不拉低「中」（3 個模式 2 中 1 低＋系集低 → 中）；系集 p49 ≥ 30% 單獨撐高（IFS 低、GFS 低、
  系集高 → 3 票 1 高：1×2 < 3 → 不成立 → 低；寫清楚這是規則的結果）；只有 1 個模式 → 它決定、`thin`；全無 → None；
  雪的分母不含 AIGFS；霧分母 1
- `tests/test_assess.py`：`models[]` 每筆的數字與 `levels`；AIFS 估算陣風 31 節 × 1.4 → 43.4 → `medium`、`gustEstimated`；
  `model.ec`／`gfs`／`agreement` 既有測試**一個都不能變**（它們的值照舊）；`causes` 用投票後的等級
- `tests/test_sources_*.py`：AIFS `sf`／`tp` 差值與 `ptype`；AIGFS `.idx` 兩種累積方式都算得出 6 小時雨量；沿用兩個新來源
- `tests/test_build.py`：頂層 `models`、`runs.aifs`／`aigfs`、`sources.aifs`／`aigfs`；`_rescore` 重算投票
- README：「怎麼算」模式那列改寫成投票（含系集只投高、估算陣風、雪的分母、霧分母 1）、「輸出」加第 3 節欄位、「資料來源」加
  AIFS（CC BY 4.0）與 AIGFS（公有領域）、「已知的保守假設」加「估算陣風係數 1.4、一個月後檢討」「投票 ≥ 一半成立」；
  `docs/ORCHESTRATOR.md`「多模式投票」那條補「已實作（HD14 PR）」與和提示詞不一樣的地方

## 回報時要附

- AIFS 與 AIGFS 實際的路徑／檔名、參數、大小、秒數；鏡像順序
- 用 `data` 分支最近一份的 history 加上新抓的兩個模式跑一遍：挑 10 格列 `models[]` 五筆的等級與 `vote`，和原本 `model.level`
  的對照（變高／變低的格各幾個）
- `latest.json` 大小；合併後第一報的 `timing` 總秒數（主對話看）

本機 `ruff check .`、`ruff format --check .`、`pytest -q` 全過才推，盡量一次推完。
開 PR 之後：`gh pr checks --watch` 等 CI，紅了自己修並推到同一個分支（最多三輪），全綠時告訴我；
不要自己合併，我會先請主對話審查。
