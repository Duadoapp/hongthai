# HD3：再加三個地區、十個機場；補石垣的跑道；評估關島、帛琉的官方警報

模型：Opus，強度高。建立在 H9（41 個機場）之上，`latest.json` 既有欄位不改名、不改型別；地區與機場的
結構照 H9 做出來的機制加，不要另起一套。

先讀 `docs/ORCHESTRATOR.md`（階段清單、資料來源與授權）、`README.md`（機場清單、跑道方位、哪些沒有 TAF）、
`airports.json`、`src/hongthai/config.py`（`load_airports` 的檢查）、`src/hongthai/sources/hko.py`／`cwa.py`／`smg.py`
（官方警報怎麼接）、`src/hongthai/build.py`（`collect_warnings`）、`src/hongthai/assess.py`（警報對等級）。

## 1. 三個新地區、十個機場（Shawn 指定，標準是台灣有定期直飛；ICAO／IATA 逐一對 OurAirports 核對）

接在 `korea` 之後，共 9 個地區、51 個機場：

| 地區 id | zh-TW | zh-HK | zh-CN | en | 機場 |
| --- | --- | --- | --- | --- | --- |
| `vietnam` | 越南 | 越南 | 越南 | Vietnam | 河內 VVNB/HAN、胡志明 VVTS/SGN、峴港 VVDN/DAD、芽莊（金蘭）VVCR/CXR、富國島 VVPQ/PQC |
| `philippines` | 菲律賓 | 菲律賓 | 菲律宾 | Philippines | 馬尼拉 RPLL/MNL、宿霧 RPVM/CEB、克拉克 RPLC/CRK |
| `guam-palau` | 關島・帛琉 | 關島・帛琉 | 关岛・帕劳 | Guam & Palau | 關島 PGUM/GUM、帛琉 PTRO/ROR |

- 時區：越南 `Asia/Ho_Chi_Minh`、菲律賓 `Asia/Manila`、關島 `Pacific/Guam`、帛琉 `Pacific/Palau`
- 四語名稱照 H9 的風格（短名、不加「機場」）：`河內`／`河内`／`Hanoi`、`胡志明`／`胡志明`／`Ho Chi Minh City`、
  `峴港`／`岘港`／`Da Nang`、`芽莊`／`芽庄`／`Nha Trang (Cam Ranh)`、`富國島`／`富国岛`／`Phu Quoc`、
  `馬尼拉`／`马尼拉`／`Manila`、`宿霧`／`宿雾`／`Cebu`、`克拉克`／`克拉克`／`Clark`、`關島`／`关岛`／`Guam`、
  `帛琉`／`帕劳`／`Palau`（zh-HK 和 zh-TW 同，除了 zh-HK 慣用字不同的）
- 座標、跑道：OurAirports（`runwaySource: "ourairports"`），照 H9 的規則（平行跑道併組、關閉的不算、短於最長跑道
  一半的不算、沒方位用跑道頭座標算）；沒有的 `runways: []` 並在回報裡說
- `warningSources`：越南、菲律賓 `[]`（`official.warnings: false`，Shawn 定案先不接）；關島、帛琉見第 3 節
- `regions` 與 `airports[]` 順序照上表；`config.load_airports` 的檢查、README 機場清單、ORCHESTRATOR
  「這個 repo 做什麼」改成 51 個、九個地區
- TAF／METAR：一次請求加到 51 站；哪些沒有 TAF 實測後寫進 README 那張表
- GFS 的 NOMADS 備援框由機場座標算，會自動變大（富國島到關島、帛琉到仙台），確認一個框的檔案大小還可以
  （估約 100 KB 以內）

## 2. 補石垣（ROIG）的跑道

H9 時 OurAirports 沒有石垣的跑道方位，側風一直是 `null`；石垣是颱風最常直撲的機場之一，要補。新石垣機場只有
一條跑道 04/22。來源順序：
1. 日本 AIP（AIS Japan，<https://aisjapan.mlit.go.jp/>）AD 2 ROIG 的 AD 2.12「跑道物理特性」真北方位（TRUE BRG）。
   網站要免費註冊才看得到；沙盒登不進去就用第 2 個
2. 用跑道兩端跑道頭座標算真北方位（OpenStreetMap 或維基百科的跑道資料），`runwaySource` 記 `"computed"`，
   README「跑道方位」表加一列說明來源與算法

`airports.json` 的石垣改成 `runways: [{"id": "04/22", "headings": [<真北>, <真北+180>], "magnetic": [...]}]`，
磁方位沒有就省略。回報裡貼算出來的數字與來源。

## 3. 關島、帛琉的官方颱風警報（評估＋能接就接）

兩個都在美國國家氣象局關島分處（NWS WFO Guam，GUM）的範圍。先查：
- `api.weather.gov`（公有領域、JSON、不用金鑰）的 alerts 端點是否涵蓋關島：`/alerts/active?zone=<關島的 zone>`
  （WFO GUM 的 zone 代碼以 `GU` 開頭，請從 `/zones?area=GU` 之類的端點查出 PGUM 所在的 zone），以及帛琉
  （`/zones?area=PW`，或 WFO GUM 的產品裡是否有帛琉的 TC 警報）
- 若 alerts 端點有關島，接成新的來源 `src/hongthai/sources/nws.py`：抓 `/alerts/active?zone=...`，只看
  `event` 是 Typhoon Warning／Typhoon Watch／Tropical Storm Warning／Tropical Storm Watch 的；對等級：
  Typhoon Warning → 高，Typhoon Watch／Tropical Storm Warning → 中，Tropical Storm Watch → 中
  （和 HKO 8 號＝高、3 號＝中的精神一致；這是主對話先定的預設，Shawn 會確認）。`warnings[].source` 用 `"nws"`、
  `kind` 用 `typhoon_warning`／`typhoon_watch`／`ts_warning`／`ts_watch`，`code` 放 NWS 的 `event`，
  `text` 四語（英文用 NWS `headline`，中文三語由程式用固定句型翻，例如「颱風警報生效中」）。
  `sources.nws`、`history/raw/<日期>/<HHMM>Z-nws.json`、時間預算 30 秒、timing 一行，都照現有來源的樣子
- 帛琉查得到就一起接（`warningSources: ["nws"]`），查不到就 `[]`，**把查的結果（端點、回應、結論）寫進 README
  「資料來源與授權」與 ORCHESTRATOR**，不要只寫在 PR
- 測試不連網：alerts 的 fixture（找一份真實的 NWS alerts JSON，沒有颱風時就用「無警報」的回應，再手寫一份
  Typhoon Warning 的）、對等級、沒有 zone 時的錯誤

## 4. 文件與測試

- README：機場清單加三個地區、沒有 TAF 的機場、跑道方位表、資料來源加 NWS；ORCHESTRATOR 同步；
  `docs/ORCHESTRATOR.md`「已經做過的決定」的機場數字改成 51
- `tests/test_build.py`：`airports.json` 檢查（51 個、九個地區、順序）、`official.warnings` 對應；
  `tests/test_sources.py`：NWS
- 不要動 `assess.py` 的門檻與等級規則（警報對等級的對照表除外）、`cancellations.py`、`flights.py`

## 回報時要附

- ICAO／IATA 核對結果、沒有 TAF／METAR 的機場、沒有跑道資料的機場
- 石垣跑道的方位與來源
- NWS：關島、帛琉各自查到什麼、接了沒有
- `latest.json` 大小、本機跑一次的 `history/timing/` 那幾行

本機 `ruff check .`、`ruff format --check .`、`pytest -q` 全過才推，盡量一次推完。
開 PR 之後：`gh pr checks --watch` 等 CI，紅了自己修到綠（最多三輪），全綠時告訴我；
不要自己合併，我會先請主對話審查。
