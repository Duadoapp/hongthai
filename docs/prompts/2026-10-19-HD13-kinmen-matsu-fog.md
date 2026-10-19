# HD13：金門、馬祖的霧——氣象署濃霧特報＋氣象署局屬站觀測當 METAR 用

模型：Opus，強度中。改 `src/hongthai/sources/cwa.py`（濃霧特報、局屬站觀測）、`src/hongthai/assess.py`（觀測單獨撐起第一格）、
`src/hongthai/build.py`、`airports.json`（兩站站號）、測試、README、`docs/ORCHESTRATOR.md`。
`latest.json` 既有欄位不改名、不改型別；只加本文列的兩個小東西（`warnings[].kind` 一個新值、`metar.source`）。

先讀 `docs/ORCHESTRATOR.md` 第五階段那段（HD8／HD10）、`src/hongthai/sources/cwa.py`（HD8 的 `W-C0033-001` 特報：`parse_hazards`、
`heavy_rain_for_airport`）、`src/hongthai/sources/taf.py`（`Metar`）、`src/hongthai/assess.py`（`metar_fresh`、`official_wx`、
`assess_slots` 裡「低的警報不撐起官方層」那段）、`src/hongthai/build.py`（`metar_json`、`_warnings_for`）、`tests/test_sources_hd8.py`。
`data` 分支 `history/raw/2026-10-19/0656Z-cwa-hazards.json` 是特報的真實回應。

## 背景與定案（Shawn 2026-10-19：「金馬照建議」）

金門（RCBS）、馬祖南竿（RCFG）最常因霧停飛，但 AviationWeather **沒有這兩站的 TAF／METAR**，HD8 上線後它們的霧只有 GFS
模式層（HD10 後最高只到中）。HD8 查到的來源：飛航服務總臺 AOAWS 有兩站 METAR／SPECI 但是非正式介面（不接）；
**氣象署開放資料 `O-A0003-001`（現在天氣觀測報告，有人氣象站）有金門 467110、馬祖 467990 的能見度**，同一把 `CWA_API_KEY`；
另外 HD8 已經在抓的 `W-C0033-001` 特報裡有「**濃霧**」這個 `phenomena`。主對話的建議（Shawn 同意）：

1. **濃霧特報 → 警報 `cwa_dense_fog`，等級「中」**，算 `fog`；縣市名含機場 `cwaAreas` 任一關鍵字就套（台灣十個機場都適用，
   不只金馬）。不用多打一次（同一個回應）
2. **局屬站觀測當 METAR 用**（只有金門、馬祖）：`airports.json` 給兩站 `cwaStation`（`467110`、`467990`），每報多打一次
   `O-A0003-001`（`StationId` 篩那兩站），把觀測時間、風向、風速（m/s → 節）、陣風、**能見度**（公里 → 公尺）、天氣現象
   （「霧」「靄」「雨」這類中文 → 對應 METAR 代碼 `FG`／`BR`／`RA`，對不到就原文）填進 `Metar`，`raw` 寫成
   `CWA 467110 2026-10-19T12:00Z 能見度 0.5 km 霧 風 090° 3 m/s`；`airports[].metar` 多 `source: "cwa"`（AviationWeather 的
   不加這個鍵）。欄位名要以第一次實抓的回應為準（本機沒金鑰）——程式先照文件寫、解析寫寬鬆，**合併後第一報對一次**，原文存
   `history/raw/<日期>/<時間>-cwa-obs.json`
3. **觀測可以單獨撐起第一格的官方層**（只限「這個機場沒有 TAF」的情況）：現在 METAR 只在該格本來有 TAF 或中以上警報時才算；
   改成——機場沒有 TAF、METAR 在 3 小時內 → 第一格 `official` 由 METAR 組成（`kind: "metar"`，新值；`windKt`／`gustKt`／
   `crosswindKt`／`wx` 都從 METAR 來），之後的格照舊退回模式。有 TAF 的機場完全不受影響。這條也會讓宮古（MMY，有 METAR
   沒 TAF）第一格有官方層，是預期的；花蓮等六個沒 METAR 的機場不變
4. AOAWS 不接；JMA 大雪警報仍是 HD9

## 要做的

### 1. 濃霧特報（`sources/cwa.py`、`build.py`）
- `parse_hazards` 不用改（已經把所有 `phenomena` 都收進來）；加 `dense_fog_for_airport(hazards, keywords, place)`，`phenomena`
  含「濃霧」→ `CwaWarning(kind="cwa_dense_fog", level="medium", detail="濃霧", text 四語：「中央氣象署濃霧特報，金門在特報
  範圍」／zh-CN「中央气象署浓雾特报，…」／en「CWA dense fog advisory; Kinmen is in the advisory area」)`
- `assess.RAIN_WARNING_KINDS` 旁邊加 `FOG_WARNING_KINDS = {"cwa_dense_fog"}`，`warning_cause` 回 `fog`；官方層的 `fog` 等級要把
  這類警報算進去（同 `rain` 的寫法）
- `build._warnings_for` 把它和 `cwa_heavy_rain` 一起加進去；同一報同一機場同種特報只出一則

### 2. 局屬站觀測（`sources/cwa.py`、`config.py`、`airports.json`、`build.py`）
- `airports.json`：RCBS 加 `"cwaStation": "467110"`，RCFG 加 `"cwaStation": "467990"`；`config.Airport` 加 `cwa_station: str | None`
- `cwa.fetch` 多一段（和特報一樣分開 try、失敗只記 `sources.cwa.obsOk: false`＋`obsError`，不影響颱風警報與特報）：
  `GET https://opendata.cwa.gov.tw/api/v1/rest/datastore/O-A0003-001?StationId=467110,467990`（參數名以文件為準），回傳
  `records.Station[]`，每站 `StationId`、`ObsTime.DateTime`、`WeatherElement`（`Weather`、`VisibilityDescription` 或 `Visibility`、
  `WindDirection`、`WindSpeed`、`PeakGust...`——**欄位名以文件與第一次實抓為準**，缺的記 None，-99 之類的缺測值記 None）
- 轉成 `taf.Metar`（`observed` 用台灣時間轉 UTC；`vis_m` 公里 × 1000、換算到 50 公尺；`wx` 由中文對照：霧→`FG`、靄→`BR`、
  雨→`RA`、雷雨→`TSRA`、陣雨→`SHRA`、毛毛雨→`DZ`，其他原文；`ceiling_ft` None）；`build` 在 AviationWeather 沒有該站 METAR 時
  用它（有的話仍用 AviationWeather）；`metar_json` 多 `source: "cwa"`
- 原文存 `history/raw/<日期>/<時間>-cwa-obs.json`；`cwa` 的預算 45 秒夠（多一個請求），不夠就 60

### 3. 觀測單獨撐起第一格（`assess.py`）
- `assess_slots`：`taf_periods` 是 None 或空、`metar_fresh`、且這格是第一格 → `official = {"windKt": metar.wind_kt,
  "gustKt": metar.gust_kt, "kind": "metar", "level": taf_level(...)（用 METAR 的風）, "crosswindKt": metar_xw, "wx": official_wx([metar])}`，
  警報照舊疊上去；等級＝風、側風、三類、警報取最高。模組 docstring「官方」那條改寫
- `official.kind` 多一個值 `metar`（要轉給 Duado：`main`／`tempo`／`prob30`／`prob40`／`warning`／`metar`）

### 4. 測試與文件
- `tests/test_sources_hd8.py`（或新檔）：濃霧特報 fixture（照 `0656Z-cwa-hazards.json` 的格式，`phenomena` 寫「濃霧」、
  `locationName` 「金門縣」）→ RCBS 有 `cwa_dense_fog`、RCTP 沒有；觀測 fixture → `Metar` 的 `vis_m`／`wx`／風；缺測值 → None
- `tests/test_assess.py`：沒 TAF＋METAR 能見度 300 公尺 → 第一格 `official.kind == "metar"`、`level high`、`causes ["fog"]`；
  沒 TAF＋METAR 4 小時前 → 第一格退回模式；有 TAF 的機場行為不變（既有測試一個都不能改）；濃霧特報＋沒 TAF 沒 METAR →
  第一格 `official.kind == "warning"`、`medium`、`causes ["fog"]`
- README「資料來源」加 `O-A0003-001` 與濃霧特報、「怎麼算」官方那列補「沒有 TAF 的機場第一格可由 METAR（含氣象署觀測）單獨
  撐起」、「輸出」補 `metar.source`、`official.kind: "metar"`、`warnings[].kind: "cwa_dense_fog"`；`docs/ORCHESTRATOR.md`
  第五階段補「已實作（HD13 PR）」與和提示詞不一樣的地方；「待網頁配合」要轉給 Duado 的三個小東西寫進
  `docs/worklog/2026-10-19.md`（主對話會補，雲端不用動日誌）

## 回報時要附

- `O-A0003-001` 實際用的參數與欄位名（文件連結）；沒金鑰抓不到就說明程式照哪一版文件寫
- 假資料跑出的 RCBS 第一格 `official`（含 `wx`）與 `causes`
- `latest.json` 大小變化（應該幾乎不變）

本機 `ruff check .`、`ruff format --check .`、`pytest -q` 全過才推，盡量一次推完。
開 PR 之後：`gh pr checks --watch` 等 CI，紅了自己修並推到同一個分支（最多三輪），全綠時告訴我；
不要自己合併，我會先請主對話審查。
