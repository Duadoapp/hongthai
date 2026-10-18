# HongThai

桃園（RCTP／TPE）與香港（VHHH／HKG）兩個機場未來 5 天的**強風停飛風險**等級。
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
| 模式（0–120 小時） | ECMWF 系集「10 米陣風 ≥ 10／15／25 m/s 機率」、ECMWF HRES 10 米陣風、GFS 地面陣風 | EC ≥ 25 m/s 機率 ≥ 30%、或 HRES／GFS 陣風 ≥ 25 m/s → 高；EC ≥ 15 m/s 機率 ≥ 50%、或任一模式陣風 ≥ 15 m/s → 中；其他低 |
| 官方（0–30 小時） | TAF、香港天文台熱帶氣旋信號、中央氣象署颱風警報 | 天文台 8 號以上 → 高、3 號 → 中；氣象署陸上颱風警報且桃園在警戒區 → 高、海上警報 → 中；TAF 陣風 ≥ 45 節（或平均風 ≥ 35 節）→ 高、陣風 ≥ 30 節 → 中 |

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

整個流程約 1.5 分鐘（ECMWF 約 60 MB、GFS 21 個不到 1 KB 的小檔），下載大小與耗時印在 log。

### 檔案

- `airports.json`：機場（ICAO、IATA、時區、四語名稱、座標、門檻、看哪個官方警報）
- `confirmed.json`：人工填的已確認停飛時段，例如
  `[{"airport": "VHHH", "from": "2026-10-20T00:00:00Z", "to": "2026-10-20T12:00:00Z", "note": {"zh-TW": "機管局公告…", "en": "…"}}]`
- `src/hongthai/sources/`：各資料來源（每個 `fetch()` 回 dataclass，失敗丟自己的例外）
- `src/hongthai/assess.py`：判讀（純函式）
- `src/hongthai/build.py`：組 JSON、寫檔、失敗處理

### 輸出

- GitHub Pages（`public/`）：`latest.json`、`history/<YYYYMMDDTHHMM>Z.json`（歷次結果）
- `data` 分支（Actions 自動推）：同樣的結果，加上原始快照
  `history/raw/<日期>/<HHMM>Z-{taf,metar,hko,cwa}.json` 與航班快照
  `history/flights/<日期>/<機場>-<HHMM>.json.gz`（之後回測用）

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
          "official": { "windKt": 25, "gustKt": 38, "kind": "tempo", "level": "medium", "warnings": [] },
          "model": { "ec": { "p10": 0.92, "p15": 0.55, "p25": 0.08, "hresGustMs": 17.4 }, "gfs": { "gustMs": 15.1 }, "level": "medium", "agreement": "agree" },
          "gap": false
        }
      ],
      "confirmed": [ { "from": "…", "to": "…", "note": { "zh-TW": "…", "en": "…" } } ]
    }
  ]
}
```

規格以外加的欄位與值（網頁可以忽略）：

- `runs.ecmwfEns`：系集機率那一報（只有 00／12Z 有，可能比 HRES 早一報）
- `sources.<名稱>.seconds`、`bytes`；`sources.ecmwf.ensembleOk`／`ensembleError`（只有系集失敗時）；
  `sources.flights`
- `warnings[].code`（天文台信號代碼，例如 `TC8NE`）、`warnings[].detail`（氣象署警戒區原文）
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
| [ECMWF 開放資料](https://www.ecmwf.int/en/forecasts/datasets/open-data) | HRES 10 米陣風（`10fg`／`10fg3`）、系集陣風機率（`10fgg10`／`10fgg15`／`10fgg25`） | CC BY 4.0，© ECMWF |
| [NOAA GFS](https://nomads.ncep.noaa.gov/)（NOMADS GRIB filter） | 地面陣風 `GUST` | 美國政府公有領域 |
| [AviationWeather.gov Data API](https://aviationweather.gov/data/api/) | TAF、METAR | 美國政府公有領域 |
| [香港天文台開放數據](https://www.hko.gov.hk/en/weatherAPI/doc/files/HKO_Open_Data_API_Documentation.pdf)（data.gov.hk） | 天氣警告摘要（熱帶氣旋信號） | [data.gov.hk 使用條款](https://data.gov.hk/tc/terms-and-conditions) |
| [中央氣象署開放資料平台](https://opendata.cwa.gov.tw/)（`W-C0034-001` 颱風警報） | 海上／陸上颱風警報與警戒區 | [政府資料開放授權條款](https://data.gov.tw/license) |
| [香港機管局航班資訊](https://data.gov.hk/tc-data/dataset/aahk-team1-flight-info)（data.gov.hk） | 航班狀態快照（只存檔） | data.gov.hk 使用條款 |
| [桃園國際機場即時航班](https://data.gov.tw/dataset/26194)（data.gov.tw） | 航班狀態快照（只存檔） | 政府資料開放授權條款 |

程式碼以 [MIT](LICENSE) 授權。
