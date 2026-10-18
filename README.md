# HongThai

桃園（RCTP／TPE）、松山（RCSS／TSA）、高雄（RCKH／KHH）、香港（VHHH／HKG）、澳門（VMMC／MFM）
五個機場未來 5 天的**強風停飛風險**等級（含分跑道的側風）。
每天四次抓氣象資料，輸出一份 `latest.json`，用 GitHub Pages 發布：

<https://duadoapp.github.io/hongthai/latest.json>

給 [duado.app/hongthai/](https://duado.app/hongthai/) 的網頁讀（網頁在 Duado 那邊，不在這個 repo）。
JSON 格式是和網頁的契約，見下面「輸出」；欄位名稱與型別不能改，要加欄位可以。

> **免責**：這是用公開氣象資料自動算的參考資訊，預報有誤差。航班是否停飛以航空公司與機場公告為準，
> 依此做的任何決定由使用者自行負責。

## 怎麼算

時間軸從「現在往前取整到 00／06／12／18Z」起，每格 6 小時、共 20 格（120 小時）。

| 層 | 資料 | 規則（初版，保守，之後用實際紀錄校準） |
| --- | --- | --- |
| 模式（0–120 小時） | ECMWF 系集「10 米陣風 ≥ 10／15／25 m/s 機率」、ECMWF HRES 10 米陣風與 10 米風（風只抓 6 小時整的時間點）、GFS 地面陣風與 10 米風 | EC ≥ 25 m/s 機率 ≥ 30%、或 HRES／GFS 陣風 ≥ 25 m/s → 高；EC ≥ 15 m/s 機率 ≥ 50%、或任一模式陣風 ≥ 15 m/s → 中；其他低 |
| 官方（0–30 小時） | TAF、METAR、香港天文台與澳門地球物理氣象局（SMG）熱帶氣旋信號、中央氣象署颱風警報 | 天文台／SMG 8 號以上 → 高、3 號 → 中；氣象署陸上颱風警報且機場在警戒區 → 高、海上警報（或陸上但不在警戒區）→ 中；TAF 陣風 ≥ 45 節（或平均風 ≥ 35 節）→ 高、陣風 ≥ 30 節 → 中 |
| 側風（官方、模式各自） | TAF 各時段與 METAR 的風向風速；HRES、GFS 的 10 米風向配各自的陣風 | 含陣風側風 ≥ 35 節 → 高、≥ 25 節 → 中；和上面的陣風規則**取較高的等級** |

- 側風分量＝含陣風的風速（有陣風用陣風，沒有用平均風）× |sin(風向 − 跑道方位)|，每條跑道兩個方向取小的，
  再取所有跑道裡**最小**的（還有一條能用就不算停飛）；風向可變（VRB）或沒有風向時側風＝風速本身
- HRES 的 10 米風只抓 00／06／12／18Z 的時間點（H10，減少下載量），每個陣風區間配**結束時間往後最近**
  的那個時間點的風向
- 0–30 小時以官方為準；官方與模式不同級標 `gap: true`
- `agreement`：HRES 與 GFS 的陣風落在同一級＝`agree`
- `confirmed.json` 人工填的已確認停飛時段 → 該格 `level: "confirmed"`
- 門檻在 `airports.json`，細節（時間格怎麼對、警報套幾小時）寫在 `src/hongthai/assess.py` 開頭

## 怎麼跑

需要 Python 3.12 以上。`eccodes` 的 pip 套件已附函式庫；Linux 也可以先裝 `libeccodes-dev`。

```sh
pip install ".[dev]"
python -m hongthai.build            # 產生 public/latest.json 與 data/（歷史紀錄）
pytest -q && ruff check . && ruff format --check .
```

中央氣象署的資料需要授權碼，從環境變數 `CWA_API_KEY` 讀；沒設定時氣象署標
`sources.cwa.ok=false, error="no_api_key"`，其他照出。**不要把授權碼寫進程式或 repo。**

整個流程約 4–5 分鐘（2026-10-18 實測 262 秒：ECMWF HRES 約 113 MB／90 秒、系集約 10 MB、GFS 兩個框
共 42 個 1–2 KB 的小檔約 110 秒、航班快照五個機場約 20 秒），下載大小與耗時印在 log，
也寫進 `data` 分支的 `history/timing/`（見下面「輸出」）。

H10（2026-10-18）之後：
- ECMWF HRES 一報約 82 MB（原本約 112 MB）：陣風每個步長只有一個參數（0–90 小時 `10fg`、93–144 小時
  `10fg3`、150 小時以後 `10fg`），全部步長都抓；`10u`／`10v` 只抓 6 小時整的步長，分兩個請求下載。
  ECMWF 入口實測 0.5–1.4 MB/s，所以預算放寬到 300 秒
- GFS 改從 AWS 開放資料鏡像（`noaa-gfs-bdp-pds`）抓：每個步長先讀 `.idx`，用 HTTP `Range` 只抓
  `GUST`、`UGRD`、`VGRD` 三筆（全球 0.25°，每個步長約 2.5 MB、21 個步長共約 50 MB）；AWS 失敗才退回
  NOMADS GRIB filter（2026-10-18 12:42Z 起 NOMADS 對 Actions 回 403）。從哪裡抓的記在 `sources.gfs.mirror`

#### 時間預算與逾時（H7）

每個來源在自己的執行緒裡跑，有各自的時間預算（秒，`src/hongthai/build.py` 開頭的 `BUDGET_S`）：

| 來源 | 預算 | 2026-10-18 實測 |
| --- | --- | --- |
| ecmwf（HRES＋系集，含鏡像切換） | 300 | 約 90–240（入口速度不穩；H10 前 HRES 約 112 MB，之後約 82 MB）＋10 |
| gfs（AWS 鏡像，NOMADS 備援） | 180 | 約 110（NOMADS）|
| taf（含 METAR） | 45 | 幾秒 |
| hko、smg | 各 30 | 幾秒 |
| cwa | 45 | 幾秒 |
| flights（抓＋統計＋寫檔） | 120 | 約 20 |

- 超過預算就記 `sources.<名稱> = {"ok": false, "error": "timeout", "seconds": <預算>}`，不等它、
  繼續下一個來源。被放棄的執行緒在背景跑到下一個請求或解析前就自己結束（不再解析 GRIB；
  GRIB 解析有全域鎖），程式結束時不等它
- 總和 750 秒（12.5 分鐘），Actions「產生 latest.json」那一步上限 15 分鐘、整個 job 25 分鐘
- ECMWF：重試最多 3 次、每次間隔 10 秒、不照伺服器的 Retry-After（`ecmwf-opendata` 預設是每 120 秒
  重試 500 次，2026-10-18 build #4 就是從頭 429 到被砍）。找最新一報先問 ECMWF 入口（失敗才問 AWS），
  下載先試 AWS 鏡像，那一報還沒同步到或失敗再回 ECMWF 入口，再失敗試 Google；實際從哪裡下載記在
  `sources.ecmwf.mirror`。從 AWS 下載不重試：S3 不收多段 range、一報要一百多個請求，2026-10-18
  實測約三成回 `503 Slow Down`，重試會把預算耗光，所以第一個 503 就換 ECMWF 入口
- `ecmwf` 或 `gfs` 失敗（逾時、429 用盡、403、格式錯……）時沿用「最近一份有該模式資料」的結果
  同一機場、同一格的 `model.ec`／`model.gfs`，等級照常算。哪一份（H10 起往前找）：`--archive` 的
  `history/<時間>.json` 由新到舊，第一份 `sources.<名稱>.ok` 是 `true`（自己也在沿用的不算）而且
  `runs.ecmwf`／`runs.gfs` 離現在 24 小時內的；archive 裡找不到才退回上一份 `latest.json`（先找
  `--archive`，沒有就從 Pages 抓）。`sources.<名稱>.ok` 仍是 `false`，另加 `reusedFrom`（那一份的
  `generatedAt`），`runs` 是那一份的（舊預報的真實時次）。模式時次離現在超過 24 小時就不沿用
  （系集與 HRES 各自算），照缺資料處理。TAF、METAR、警報不沿用

### 檔案

- `airports.json`：機場（ICAO、IATA、時區、四語名稱、座標、跑道、門檻、看哪些官方警報、氣象署警戒區關鍵字）
  - `runways[].headings`：跑道兩個方向的**真北**方位（度）。提示詞寫的是磁方位，但 METAR／TAF 與模式的風向
    都是真北，用磁方位會差 3–5°，所以算側風用真北；磁方位記在 `runways[].magnetic` 備查（下面「跑道方位」）
  - `warningSources`：`cwa`（台灣三個機場）、`hko`（香港）、`smg`（澳門）
  - `cwaAreas`：氣象署警戒區關鍵字，桃園、松山是「北部」「桃園」「臺北」「台北」「新北」，高雄是「南部」「高雄」
  - `thresholds`：每個機場可覆寫的門檻，含側風 `crosswindMediumKt`（25）、`crosswindHighKt`（35）
- `confirmed.json`：人工填的已確認停飛時段，例如
  `[{"airport": "VHHH", "from": "2026-10-20T00:00:00Z", "to": "2026-10-20T12:00:00Z", "note": {"zh-TW": "機管局公告…", "en": "…"}}]`
- `src/hongthai/sources/`：各資料來源（每個 `fetch()` 回 dataclass，失敗丟自己的例外）
- `src/hongthai/assess.py`：判讀（純函式）
- `src/hongthai/build.py`：組 JSON、寫檔、失敗處理

### 輸出

- GitHub Pages（`public/`）：`latest.json`、`history/<YYYYMMDDTHHMM>Z.json`（歷次結果）
- `data` 分支（Actions 自動推）：同樣的結果，加上原始快照
  `history/raw/<日期>/<HHMM>Z-{taf,metar,hko,cwa,smg}.json`（SMG 是 `{"c": XML, "e": XML}`）與航班的
  取消／延誤統計 `history/cancellations/<日期>.json`（之後回測「風險等級 vs 實際停飛」用；
  原始航班資料不存）、狀態對照表沒列的字串 `history/cancellations/unknown-statuses.json`，以及
  每次 build 的耗時紀錄 `history/timing/<YYYY-MM>.jsonl`。這些都不進 GitHub Pages、不進 `latest.json`

`history/timing/<YYYY-MM>.jsonl`：一行一筆 JSON，每個來源一跑完就 append（不等全部結束），所以
「產生 latest.json」被 Actions 砍掉時已經寫的行也會推上去。`run` 和那次的 `generatedAt` 相同：

```json
{"run": "2026-10-18T09:28:00Z", "source": "start", "ok": true, "seconds": 0, "commit": "a59b42d"}
{"run": "2026-10-18T09:28:00Z", "source": "ecmwf", "ok": false, "error": "timeout", "seconds": 240.0, "bytes": 0, "mirror": "aws"}
{"run": "2026-10-18T09:28:00Z", "source": "gfs", "ok": true, "error": null, "seconds": 108.3, "bytes": 61234, "mirror": "nomads"}
{"run": "2026-10-18T09:28:00Z", "source": "done", "ok": true, "seconds": 371.2}
```

- `source`：`start`、`ecmwf`、`gfs`、`taf`、`hko`、`cwa`、`smg`、`flights`、`done`（照執行順序）
- `error`：和 `sources.<名稱>.error` 同一套代碼，成功是 `null`；`bytes`：下載量（逾時的是到那時為止，
  ecmwf 只算下載完的檔）；
  `mirror`：ecmwf 與 gfs 有（gfs 是 H10 起），實際下載（逾時或失敗時是最後在試）的 source，
  還沒開始是 `null`；ecmwf 是 `aws`／`ecmwf`／`google`，gfs 是 `aws`／`nomads`
- `start` 的 `commit` 是 `GITHUB_SHA` 前 7 碼（本機跑是 `null`）；`done` 的 `ok` 是這次有沒有產出新的
  `latest.json`。**沒有 `done` 那行就表示那次被砍了**

`history/cancellations/<日期>.json`：日期是格的 UTC 日期，一天一個檔，內容是陣列、依 `airport`、`from`
排序（兩個空白縮排）。每個元素是一個機場的一個 UTC 6 小時格（和 `latest.json` 一樣對齊 00／06／12／18Z）：

```json
{
  "airport": "RCTP",
  "from": "2026-10-18T06:00:00Z",
  "to": "2026-10-18T12:00:00Z",
  "asOf": "2026-10-18T13:05:00Z",
  "dep": { "total": 118, "cancelled": 2, "delayed": 7, "other": 0 },
  "arr": { "total": 121, "cancelled": 1, "delayed": 9, "other": 0 }
}
```

- 依**表定**時間歸格（當地時間用 `airports.json` 的 `tz` 轉 UTC）；出發、抵達分開；不含貨機；
  共掛班號與重複的列只算一班
- `cancelled`：狀態是取消；`delayed`：狀態是延誤，或預計／實際時間比表定晚 60 分鐘以上（取消的不重複算）；
  `other`：看不懂的狀態（仍算進 `total`，log 印出字串，並記進 `unknown-statuses.json`）。三者互斥，
  其餘是正常或還沒有狀態
- `asOf`：算出這筆的跑次時間
- 合併：每次 build 把算出來的格合併進對應日期的檔（一次可能動到兩三個日期）。同 `airport`＋`from`
  已有紀錄時新的覆蓋舊的，但新的 `dep.total + arr.total` 比舊的少就留舊的（來源換日後看不到前一天的班機，
  不能把昨天的統計洗成 0）；沒有的就加
- 各機場的狀態用語對照表、共掛怎麼認、沒有日期的時間怎麼補，寫在 `src/hongthai/cancellations.py` 開頭

`history/cancellations/unknown-statuses.json`（H10）：每次 build 把各機場對照表沒列的狀態字串合併進來，
讓主對話看得到要補哪些用語。只存狀態字串與次數，不存班號、時間、航點：

```json
{ "VMMC": { "SOME STATUS": { "count": 3, "firstSeen": "2026-10-18T14:33:00Z", "lastSeen": "2026-10-18T20:25:00Z" } } }
```

- `count`：累計每次 build 看到幾班（同一班在多次 build 都看到會重複算）；`firstSeen`／`lastSeen`：
  第一次與最近一次看到的 build 時間。這次都看得懂也會建出檔（`{}`）

`latest.json` 範例（時間一律 UTC ISO 8601 加 `Z`）：

```json
{
  "schema": 1,
  "generatedAt": "2026-10-18T08:10:00Z",
  "runs": { "ecmwf": "2026-10-18T00:00:00Z", "ecmwfEns": "2026-10-18T00:00:00Z", "gfs": "2026-10-18T00:00:00Z" },
  "sources": { "ecmwf": { "ok": true }, "gfs": { "ok": true }, "taf": { "ok": true }, "hko": { "ok": true }, "cwa": { "ok": false, "error": "no_api_key" } },
  "airports": [
    {
      "icao": "RCTP", "iata": "TPE", "tz": "Asia/Taipei",
      "name": { "zh-TW": "桃園", "zh-HK": "桃園", "zh-CN": "桃园", "en": "Taoyuan" },
      "warnings": [ { "source": "cwa", "kind": "typhoon_land", "level": "high", "text": { "zh-TW": "…", "zh-HK": "…", "zh-CN": "…", "en": "…" }, "issuedAt": "…" } ],
      "metar": { "observedAt": "…", "windDirDeg": 40, "windKt": 28, "gustKt": 41, "raw": "…" },
      "taf": { "issuedAt": "…", "validFrom": "…", "validTo": "…", "raw": "…" },
      "slots": [
        {
          "from": "2026-10-18T06:00:00Z", "to": "2026-10-18T12:00:00Z",
          "level": "medium", "basis": "official",
          "official": { "windKt": 25, "gustKt": 38, "kind": "tempo", "level": "medium", "crosswindKt": 21.4, "warnings": [] },
          "model": { "ec": { "p10": 0.92, "p15": 0.55, "p25": 0.08, "hresGustMs": 17.4, "crosswindKt": 26.1 }, "gfs": { "gustMs": 15.1, "crosswindKt": 12.3 }, "level": "medium", "agreement": "agree" },
          "gap": false
        }
      ],
      "confirmed": [ { "from": "…", "to": "…", "note": { "zh-TW": "…", "en": "…" } } ]
    }
  ]
}
```

第二階段（2026-10-18）加的欄位（規格 16 節已補；網頁之後顯示在依據區，現在忽略也不會壞）：

- `slots[].official.crosswindKt`、`slots[].model.ec.crosswindKt`、`slots[].model.gfs.crosswindKt`：
  含陣風、所有跑道裡最小的側風分量（節，一位小數）；沒有風向時＝風速本身；沒資料或機場沒設跑道是 `null`
- `airports[]` 多三個機場（RCSS、RCKH、VMMC）；`warnings[].source` 多 `"smg"`（澳門信號，`kind: "tc_signal"`）
- `sources.smg`

規格以外加的欄位與值（網頁可以忽略）：

- `runs.ecmwfEns`：系集機率那一報（只有 00／12Z 有，可能比 HRES 早一報）
- `sources.<名稱>.seconds`、`bytes`；`sources.ecmwf.ensembleOk`／`ensembleError`（只有系集失敗時）；
  `sources.flights`
- `sources.<名稱>.error` 多一個值 `"timeout"`：超過時間預算被放棄（這時 `seconds` 是預算）
- `sources.ecmwf.mirror`：HRES 實際從哪裡下載，`"aws"`／`"ecmwf"`／`"google"`
- `sources.gfs.mirror`（H10）：GFS 最後從哪裡下載，`"aws"`（AWS 開放資料鏡像）／`"nomads"`
- `sources.ecmwf.reusedFrom`、`sources.gfs.reusedFrom`：這次失敗、模式資料沿用之前的結果時，抄的
  那一份的 `generatedAt`（`ok` 仍是 `false`，網頁照樣顯示「這次沒讀到」）
- `sources.flights.statsError`：航班取消／延誤統計算不出來或寫檔失敗時才有，`"<機場>:<訊息>"`
  （多個用 `; ` 接）；不影響 `latest.json` 其他內容
- `warnings[].code`（天文台／SMG 信號代碼，例如 `TC8NE`、`TC3`）、`warnings[].detail`（氣象署警戒區原文、
  SMG 的說明原文）
- `official.warnings`（這格套用了哪些警報）；只有警報、沒有 TAF 的格 `official.kind` 是 `"warning"`
- 官方與模式都沒資料的格：`level: "unknown"`、`basis: "none"`、`model.level: null`；
  `agreement` 在少一個模式時是 `null`
- TAF 沒涵蓋、也沒有警報的 0–30 小時格：`official: null`、`basis: "model"`

## 發布設定（產品負責人要做的）

1. **Settings → Pages → Build and deployment → Source** 選 **GitHub Actions**
2. **Settings → Secrets and variables → Actions → New repository secret**：名稱 `CWA_API_KEY`，
   值是中央氣象署開放資料平台的授權碼（<https://opendata.cwa.gov.tw> 免費註冊後在「取得授權碼」）
3. **Actions → build → Run workflow** 手動跑一次，然後開
   <https://duadoapp.github.io/hongthai/latest.json> 確認

之後每天 UTC 01:05、08:25、13:05、20:25（台北／香港 09:05、16:25、21:05、04:25）自動跑。

## 資料來源與授權

| 來源 | 內容 | 授權 |
| --- | --- | --- |
| [ECMWF 開放資料](https://www.ecmwf.int/en/forecasts/datasets/open-data)（經 AWS／Google 鏡像） | HRES 10 米陣風（`10fg`／`10fg3`）與 10 米風（`10u`／`10v`）、系集陣風機率（`10fgg10`／`10fgg15`／`10fgg25`） | CC BY 4.0，© ECMWF |
| NOAA GFS（[AWS 開放資料鏡像 `noaa-gfs-bdp-pds`](https://registry.opendata.aws/noaa-gfs-bdp-pds/)，[NOMADS](https://nomads.ncep.noaa.gov/) 備援） | 地面陣風 `GUST`、10 米風 `UGRD`／`VGRD` | 美國政府公有領域 |
| [AviationWeather.gov Data API](https://aviationweather.gov/data/api/) | TAF、METAR | 美國政府公有領域 |
| [香港天文台開放數據](https://www.hko.gov.hk/en/weatherAPI/doc/files/HKO_Open_Data_API_Documentation.pdf)（data.gov.hk） | 天氣警告摘要（熱帶氣旋信號） | [data.gov.hk 使用條款](https://data.gov.hk/tc/terms-and-conditions) |
| [中央氣象署開放資料平台](https://opendata.cwa.gov.tw/)（`W-C0034-001` 颱風警報） | 海上／陸上颱風警報與警戒區 | [政府資料開放授權條款](https://data.gov.tw/license) |
| [澳門地球物理氣象局 XML](https://xml.smg.gov.mo/)（`c_typhoon.xml`／`e_typhoon.xml`；data.gov.mo 資料集[「熱帶氣旋信號」](https://data.gov.mo/Detail?id=15044781-1752-4f98-b87e-508208d70408)） | 熱帶氣旋信號 | [澳門政府數據開放平台使用條款](https://data.gov.mo/)：免費使用與再發布，須註明「澳門特別行政區政府數據開放平台」與取得日期 |
| [香港機管局航班資訊](https://data.gov.hk/tc-data/dataset/aahk-team1-flight-info)（data.gov.hk） | 算每 6 小時格的取消／延誤統計（不存原始資料） | data.gov.hk 使用條款 |
| [桃園國際機場即時航班](https://data.gov.tw/dataset/26194)（data.gov.tw） | 算每 6 小時格的取消／延誤統計（不存原始資料） | 政府資料開放授權條款 |
| 松山機場即時航班（data.gov.tw [37242](https://data.gov.tw/dataset/37242)／[37248](https://data.gov.tw/dataset/37248)／[37317](https://data.gov.tw/dataset/37317)／[37319](https://data.gov.tw/dataset/37319)） | 算每 6 小時格的取消／延誤統計（不存原始資料） | 政府資料開放授權條款 |
| 高雄機場即時航班（data.gov.tw [33656](https://data.gov.tw/dataset/33656)／[33655](https://data.gov.tw/dataset/33655)／[33651](https://data.gov.tw/dataset/33651)／[33649](https://data.gov.tw/dataset/33649)） | 算每 6 小時格的取消／延誤統計（不存原始資料） | 政府資料開放授權條款 |
| 澳門民航局航班資訊（data.gov.mo [離港（英文）](https://data.gov.mo/Detail?id=f910cf2e-5e30-45c3-9e62-3eb6bf912db3)／[抵港（英文）](https://data.gov.mo/Detail?id=44b62bd1-6c84-421f-b571-52ab184c7df3)） | 算每 6 小時格的取消／延誤統計（不存原始資料） | 澳門政府數據開放平台使用條款 |

航班：澳門機場官網只有伺服器端產生的 HTML（不爬），改用 data.gov.mo 上民航局的開放 API；它要一個
`Authorization: APPCODE …` 標頭，值是平台發給所有匿名使用者的公開共用碼，程式每次從資料集說明 API 取，
不寫進程式也不存檔。細節在 `src/hongthai/sources/flights.py` 開頭。

### 跑道方位

2026-10-18 查各地 AIP 的 AD 2.12（跑道物理特性）。METAR／TAF 與模式的風向都是真北，所以 `headings` 用真北：

| 機場 | 跑道 | 真北（`headings`） | 磁方位（`magnetic`） | 來源 |
| --- | --- | --- | --- | --- |
| 桃園 RCTP | 05L/23R、05R/23L | 049.1° / 229.1° | 054° / 234°（真北＋磁偏 5°W 換算） | 臺灣 AIP AIRAC AMDT 04/26（2026-10-01 生效）AD 2 RCTP，[ais.caa.gov.tw](https://ais.caa.gov.tw/) |
| 松山 RCSS | 10/28 | 092.2° / 272.2° | 097° / 277°（磁偏 5°W 換算） | 同上 AD 2 RCSS |
| 高雄 RCKH | 09/27 | 091.9° / 271.9° | 096° / 276°（磁偏 4°W 換算） | 同上 AD 2 RCKH |
| 香港 VHHH | 07L/25R、07C/25C、07R/25L | 070.9° / 250.9° | 073.9° / 253.9°（AIP 原值） | 香港 eAIP AMDT 10/26（2026-10-01 生效）[VH-AD-2-VHHH](https://www.ais.gov.hk/) |
| 澳門 VMMC | 16/34 | 161.2° / 341.2°（AIP 只給整數 161°，小數由跑道頭座標算） | 164° / 344°（AIP 原值） | 澳門 AIP Part 3（AD），[aacm.gov.mo](https://www.aacm.gov.mo/en/industry-page/DataCompilation/AIP) |

台灣 AIP 只列真北方位；同方位的平行跑道記一組。

程式碼以 [MIT](LICENSE) 授權。
