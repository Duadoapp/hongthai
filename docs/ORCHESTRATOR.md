# HongThai 主對話須知

給之後接手這個 repo 的 Claude 主對話（HongThai 專用對話）讀的一頁。先讀這份，再讀 `README.md`。
這份不放任何金鑰或個資。

## 這個 repo 做什麼

用公開氣象資料，每天四次算五個機場（桃園 RCTP、松山 RCSS、高雄 RCKH、香港 VHHH、澳門 VMMC）
未來 120 小時、每 6 小時一格的**強風停飛風險**（低／中／高），輸出一份 `latest.json` 發布在
GitHub Pages：<https://duadoapp.github.io/hongthai/latest.json>。

- 只產資料。網頁 <https://duado.app/hongthai/> 在 Duado 的私人 repo（`site/hongthai/`），不在這裡
- 程式：`src/hongthai/`（`sources/` 各資料來源、`assess.py` 判讀、`build.py` 組 JSON 與失敗處理）
- 設定：`airports.json`（機場、跑道、門檻、看哪些官方警報）、`confirmed.json`（人工填的已確認停飛）

## 和產品負責人（Shawn）合作的方式

- 回覆一律繁體中文（台灣）用語；叫他 Shawn
- 問他問題：一次最多 5 題、每題一行、附你的建議。他答完，先把「題目＋他的答案」整理成清單給他確認，
  確認後才寫進文件。還沒定案的寫進 `docs/worklog/<日期>.md` 的「待決定」（對話會被壓縮，文件不會）
- 給他的指令一律完整可貼（他用 Windows cmd）。這個 repo 幾乎沒有本機指令：部署是 Actions，
  他只在 GitHub 網頁按 Run workflow、設 Secrets
- 每個功能一個 PR。主對話寫提示詞放 `docs/prompts/<日期>-<代號>-<名稱>.md`（只放文字，不放截圖內容、
  個資、金鑰），開新的雲端對話貼「照 docs/prompts/<檔名> 做」。提示詞最後都要有
  「開 PR 之後：gh pr checks --watch 等 CI，紅了自己修到綠（最多三輪）」
- 主對話審 PR 不等 CI：他給號碼就審，審完回「可以合併」，他再開 auto-merge
  - 已設（2026-10-18）：`main` 的 ruleset 要求 PR、必要檢查 `ci`、禁止 force push；Allow auto-merge 已開。
    `ci.yml` 的 job 名稱就是 `ci`（必要檢查比對的是 job 名稱，不是 workflow 名稱），不要改名
  - 雲端對話用不了 GitHub GraphQL，這類操作走 REST
- 金鑰（`CWA_API_KEY` 等）只由他自己放進 Actions secrets，不貼進對話、PR、截圖；程式只從環境變數讀

## 已經做過的決定（不要重問）

- 名稱 HongThai，只放 duado.app/hongthai/ 網頁、不進 App；網頁在 Duado 私人 repo（`site/hongthai/`），
  本 repo 只產資料
- `latest.json` 的格式是和網頁的契約，以 Duado `docs/spec.md` 第 16 節為準：既有欄位不改名、不改型別，
  只能加；要改就兩邊同時改，先跟 Duado 的主對話說（經 Shawn 轉）
- 分階段：
  - 第一階段（PR #1）：桃園、香港
  - 第二階段（H4）：側風分跑道、松山／高雄／澳門
  - 第三階段（還沒排）：FNV3／WeatherNext Cyclones 颱風路徑（授權是實驗性條款、商用待確認，所以排後面）、
    日本機場（JMA bosai JSON 非正式）、華南與馬尼拉（只能爬網頁）、推播（要接進 App，屬 Duado 的規格）
- 等級叫「風險」不叫「機率」，等用實際停飛紀錄回測校準後才改。停飛紀錄沒有現成的，從第一天起每天存
  航班快照（`data` 分支）自己累積
- 保守假設都在 `assess.py` 與 `airports.json` 的門檻，改之前先跟 Shawn 確認
- 隱私：這個 repo 不碰任何個資；公開 repo，程式裡不能有金鑰

## 和 Duado 的分工

- 這個 repo 的改動由 HongThai 專用對話負責；duado.app/hongthai/ 網頁與 JSON 契約由 Duado 的主對話負責
- 需要網頁配合（例如顯示側風數字）時，把要加的欄位與意思寫清楚，Shawn 會轉給 Duado 那邊
- 目前待網頁配合：每格的 `official.crosswindKt`、`model.ec.crosswindKt`、`model.gfs.crosswindKt`
  （節；含陣風、所有跑道裡最小的側風分量；沒有風向時＝風速本身；`null`＝沒資料或沒設跑道）
  要加進網頁的「依據」區；澳門的警報 `source` 是 `"smg"`

## 流程

1. 主對話寫提示詞（`docs/prompts/…`）→ 雲端對話實作、開 PR 到 `main`
2. `ci`（`.github/workflows/ci.yml`）：ruff check、ruff format --check、pytest；全部不連網（用 `tests/fixtures/`）
3. 主對話審 PR → 回 Shawn「可以合併」→ Shawn 合併（或開 auto-merge）
4. `build`（`.github/workflows/build.yml`）排程每天 UTC 01:05、08:25、13:05、20:25 跑
   `python -m hongthai.build`，結果推 `data` 分支、發布 GitHub Pages
5. 改了來源或格式的 PR，合併後請 Shawn 到 **Actions → build → Run workflow** 手動跑一次，
   然後開 latest.json 確認

Shawn 要做的手動步驟（一次性，PR #1 時列過）：Settings → Pages 的 Source 選 GitHub Actions；
Settings → Secrets and variables → Actions 新增 `CWA_API_KEY`（氣象署開放資料平台授權碼）。

## 資料來源與授權

| 來源 | 用途 | 授權 |
| --- | --- | --- |
| ECMWF 開放資料 | HRES 10 米陣風與 10 米風（側風的風向）、系集陣風機率 | CC BY 4.0（要標示 © ECMWF） |
| NOAA GFS（NOMADS GRIB filter） | 地面陣風、10 米風 | 美國政府公有領域 |
| AviationWeather.gov Data API | 五個機場的 TAF、METAR | 美國政府公有領域 |
| 中央氣象署開放資料（`W-C0034-001`） | 颱風警報（桃園、松山、高雄） | 政府資料開放授權條款；要授權碼 |
| 香港天文台開放數據（warnsum） | 熱帶氣旋信號（香港） | data.gov.hk 使用條款 |
| 澳門地球物理氣象局 SMG（`xml.smg.gov.mo`，data.gov.mo 資料集「熱帶氣旋信號」） | 熱帶氣旋信號（澳門） | 澳門政府數據開放平台使用條款（須註明平台與取得日期） |
| 航班快照（香港機管局、桃園機場、松山／高雄見 README） | 只存檔，之後回測 | 各自條款，見 README |

## `latest.json` 是契約

- 以 Duado `docs/spec.md` 第 16 節為準；README 的「輸出」有範例與「規格以外加的欄位」清單
- 既有欄位不改名、不改型別，只能加。改格式要兩邊一起改，先經 Shawn 跟 Duado 主對話說
- `tests/test_build.py` 是契約測試：加欄位時一起更新

## 等級規則在哪

- `src/hongthai/assess.py`：所有規則與本 repo 自己的約定（開頭的 docstring 寫齊了）
- `airports.json` 的 `thresholds`：每個機場可覆寫的門檻（預設值在 `src/hongthai/config.py` 的 `Thresholds`）
- 官方警報對機場：`airports.json` 的 `warningSources`（`cwa`／`hko`／`smg`）與 `cwaAreas`（氣象署警戒區關鍵字）

## 已知的保守假設與待校準的參數

都是初版，等有停飛紀錄回測後再調（調之前先跟 Shawn 確認）：

- 模式陣風：≥ 25 m/s 高、≥ 15 m/s 中；EC 系集 ≥ 25 m/s 機率 ≥ 30% 高、≥ 15 m/s 機率 ≥ 50% 中
- TAF：陣風 ≥ 45 節或平均風 ≥ 35 節高、陣風 ≥ 30 節中
- 側風：含陣風側風 ≥ 35 節高、≥ 25 節中；用陣風（不是平均風）算側風；沒有風向時側風＝風速本身
- 跑道方位用真北（風向都是真北）；所有跑道取最小側風（假設最好的那條跑道都能用，沒算跑道關閉、
  長度、機型限制）
- 目前生效的警報只套用到開始時間早於「現在 + 12 小時」的格（警報本身沒有預報時段）
- 氣象署警戒區是關鍵字比對（「東北部」也會比到「北部」），偏保守
- EC 系集機率是 24 小時窗，6 小時格取包住它的窗的最小值
- 0–30 小時以官方為準；METAR 只算進現在那一格的側風

## `data` 分支

Actions 自動推，不要手動改。內容：

- `latest.json`、`history/<YYYYMMDDTHHMM>Z.json`：每次的結果
- `history/raw/<日期>/<HHMM>Z-{taf,metar,hko,cwa,smg}.json`：官方來源原始回應（SMG 是 XML 原文包在 JSON 裡）
- `history/flights/<日期>/<機場>-<HHMM>.json.gz`：航班快照（之後回測停飛用）

GitHub Pages（`public/`）只放 `latest.json` 與 `history/*.json`，不放原始快照與航班。
