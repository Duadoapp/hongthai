# HD28 調查：中國、韓國、菲律賓、越南、帛琉的官方警報從哪裡拿

實測時間：2026-10-21 17:50–18:10 UTC（台灣時間 10/22 01:50–02:10），超強颱風 Champi（29W，菲律賓叫 Rosal）在呂宋島東北方
（PAGASA 22:43 報：19.5N 127.6E，往西北走，預測 10/24 到巴丹群島以北約 650 公里）。提示詞 `docs/prompts/2026-10-22-HD28-cap-warnings-survey.md`。

**只連線、寫報告，沒有改任何程式與設定**；沒有申請帳號或金鑰，沒有碰任何驗證碼或 WAF。每個網址最多打兩三次。
實測樣本在 `docs/surveys/samples/2026-10-22-cap/`（共約 320 KB）。

**和提示詞背景不一樣的地方**（以 `airports.json` 為準）：

- 中國大陸沒有官方警報的機場是 **14 個**（華東 8：PVG、SHA、HGH、NGB、WNZ、FOC、XMN、JJN；華南 6：SWA、SZX、CAN、ZUH、HAK、SYX），不是 15 個
- 越南是 **5 個**（HAN、SGN、DAD、CXR、PQC 都沒有 `warningSources`）
- 韓國 4、菲律賓 3、帛琉 1 和提示詞一樣，合計 **27 個機場**
- 「從 GitHub Actions 的網路試一次」沒做：要加 workflow 才能跑，提示詞不准動 `.github/workflows/`。下面所有秒數都是這台雲端機器
  （經過代理）量的

---

## 1. 總表

✅ 能用、⚠️ 能用但有坑、❌ 不能用或沒資料、❔ 這台連不上，沒驗證

| 國家（機場） | SWIC JSON（`severeweather.wmo.int`） | WIS2（MQTT） | 原始 CAP feed | 其他 |
| --- | --- | --- | --- | --- |
| 中國（14） | ✅ `json/wmo_all.json`＋各則 CAP XML；匿名、CAP 1.2 XML（英文＋簡中兩個 `info`）；延遲 6–19 分鐘（中位數 11）；地區是 12 碼行政區碼（CPEAS） | ❌ 見 WIS2 一節 | ❔ 登錄表的 `www.12379.cn/rss/china_rss.xml` 這台連不上；IFRC 改抓 SWIC 的 `v2/cap-alerts/cn-cma-xx/rss.xml`（✅ 只涵蓋最近約 12 小時、500 則上限） | 中國氣象局網頁有 WAF，不碰 |
| 韓國（4） | ✅ 同一個檔（`mid` 095），英文 CAP、有多邊形；延遲 0–10 分鐘 | ❌ | ❔ `www.weather.go.kr/w/rss/cap/warning.do`（登錄表與 IFRC 都列這條）這台連不上，整個 `weather.go.kr` 都連不上 | 公共資料入口網 API 要金鑰（沒申請） |
| 菲律賓（3） | ✅ 同一個檔（`mid` 021）；延遲 1–3 分鐘 | ❌ | ✅ `publicalert.pagasa.dost.gov.ph/feeds/`（Atom、19 KB、約 2 秒、**CC BY 4.0**），CAP 有風球號數參數 | — |
| 越南（5） | ❌ SWIC 狀態「開發／測試中」，現在 0 則 | ❌ | ❔ `smartalert.nchmf.gov.vn/smartalert/capfeed.php`（IFRC 列為使用中）這台連不上；IFRC 收到的最後一則是 2024-12-03 | — |
| 帛琉（ROR） | ❌ 帛琉不是 WMO 會員，SWIC 沒有 | ❌ | ⚠️ 已在用的 `api.weather.gov`：陸地 zone `PWZ001`–`008` 至今 0 則；海上 `PMZ161`（Koror Palau Coastal Waters）**現在有** Small Craft Advisory，但沒有任何熱帶氣旋警報紀錄 | 登錄表寫的 `PMZ153` 其實是天寧島海域，資料過時 |

授權一句話：**SWIC**「free for re-use by media or other websites」，要註明各國發布機關；**PAGASA** CC BY 4.0；
**NWS** 美國政府公有領域；**WIS2** 資料集是 `recommended`，條款回頭指向各發布機關。原文在第 3 節。

---

## 2. SWIC（WMO 惡劣天氣資訊中心，香港天文台代管）

### 2.1 資料在哪（Playwright 開首頁、記網路請求）

首頁載入時打的資料檔（樣本 `swic/`）：

| 網址 | 內容 | 大小、秒數 |
| --- | --- | --- |
| `https://severeweather.wmo.int/json/wmo_all.json` | **全世界生效中的 CAP 警報清單**：`{itemCount, lastUpdated, items[]}`，每則 `id`、`event`、`headline`、`sent`、`expires`、`effective`（UTC，`YYYY-MM-DD HH:MM:SS`）、`areaDesc`、`mid`（會員代碼）、`s`／`u`／`c`（severity／urgency／certainty 的數字）、`url`（美國那幾則叫 `capURL`）＝ CAP 檔相對路徑 | 879 KB、0.6 秒（CloudFront；1998 則）|
| `https://severeweather.wmo.int/v2/cap-alerts/<url>` | 各則 CAP 1.2 XML 原文（SWIC 轉存的副本） | 3–10 KB、0.6–1 秒 |
| `json/wmo_member.json` | 會員代碼表：中國 `001`、韓國 `095`、菲律賓 `021`、越南 `082`、美國 `093`、香港 `002`、澳門 `072`、日本 `068` | 76 KB |
| `json/cap-status.json` | 各國 CAP 進度（1 完成、2 開發／測試中、3 未開始，對照在首頁的 `showCAPstatus`）：中、韓、菲、美、港 1；**越南 2**、澳門 2、日本 3 | 4 KB |
| `json/tc_inforce.json` | 生效中的熱帶氣旋（CHAMPI 2630、`same` 欄位串起 JMA、CMA 等各中心的編號） | 0.6 KB |
| `f/wfs?…typeName=local_postgis:postgis_geojsons…` | GeoServer WFS：每則警報的多邊形（GeoJSON），可用 CQL 篩 | 看條件 |

`wmo_all.json` 的 `Last-Modified` 觀察到 17:51:14、18:07:14（UTC）兩次，大約幾分鐘重產一次；CloudFront 快取（`age` 159 秒）。
這幾個都是網頁自己用的檔，**沒有公開文件、不保證不改**（和 JMA bosai JSON 同一種性質）。

**延遲**：拿 WFS 的 `url` 欄位（看起來是 SWIC 收進來的時間，香港時間）對 `wmo_all.json` 的 `sent` 算：
中國 199 則 6.0–19.1 分鐘（中位數 10.7）、韓國 6 則 0–10 分鐘、菲律賓 7 則 0.8–3 分鐘；`wmo_all.json` 本身再晚幾分鐘。
中國 RSS 那則（思茅 01:51 CST 發）在 RSS 的 `pubDate` 是 18:02Z，也是約 11 分鐘。每小時、每 6 小時跑的批次完全夠用。

### 2.2 WFS 的坑（不建議當主要管道）

- 查得到「點落在多邊形裡」：`cql_filter=row_type NOT IN ('POINT','BOUNDARY') AND INTERSECTS(wkb_geometry,POINT(<緯度> <經度>))`。
  **座標順序是緯度在前**（WFS 1.1.0＋EPSG:4326），寫成經度在前查不到；`MULTIPOINT` 也能用
- 會回**已過期**的警報與同一則的好幾塊多邊形（巴丹群島那一點回 20 筆，其實是 4 則、兩則已過期）
- **時間欄位錯 8 小時**：PAGASA 那則 CAP `sent` 22:43:05+08:00＝14:43:05Z，WFS 寫 `06:43:05Z`；`expires` 也一樣。要用 CAP 原文的時間
- 多邊形很粗、沿海機場會漏：溫州氣象台的大風黃色預警（龍灣區）正在生效，**溫州機場（WNZ）卻在 SWIC 的龍灣區多邊形外面約 5 公里**
  （多邊形只有 49 個頂點，機場在海邊）。用 27 個機場查一次，結果 0 筆，就是這個原因加上其他機場現在真的沒警報
- 東經 100–135、北緯 5–40 範圍抓一次就 53 MB、7 秒，太大

### 2.3 中國（`mid` 001，中國氣象局 CMA）

- **內容**：現在全國 342 則（`swic2data.json` 說 453，差的應是解除電文）。事件名：gale（大風）163、Frost、Icy Road、thunder、
  Dense fog、cold wave、Blizzard、Rainstorm…；這次沒看到颱風預警（Champi 還沒進中國的範圍），**颱風的 `event` 英文寫法這次沒驗證到**
  （照 CMA 預警信號應是 typhoon，藍黃橙紅四級）
- **等級**：`headline` 帶顏色與級別（「yellow warning … [Level III/Severe]」），`severity` 對應：藍 Minor、黃 Moderate、橙 Severe、紅 Extreme
  （廣德黃色大霧 Moderate、普安橙色大霧 `s: 3`）
- **語言**：每則 CAP 兩個 `info`：`en-US` 與 `zh-CN`（簡中原文：「温州市气象台发布大风黄色预警[Ⅲ级/较重]」）。沒有繁中，zh-TW／zh-HK 要自己轉或用固定句型
- **地區**：**沒有多邊形**，只有 `geocode`（`valueName` 是 `CPEAS Geographic Code`，12 碼，前 6 碼是 GB/T 2260 縣級代碼；例：海濱街道 `330303003000`）。
  SWIC 的多邊形是它自己用前 6 碼（WFS 的 `gc`）配的縣界
- **發布單位**：`id` 前 6 碼是**發布台**的行政區碼（`330300…`＝溫州市氣象台），不是警報範圍；市台會替轄下的區縣發
- **樣本**：`swic/cap/cn-wenzhou-gale-yellow.xml`、`swic/cap/cn-guangde-dense-fog-yellow.xml`、`swic/wfs-capurl-wenzhou-longwan.json`、
  `swic/cn-cma-xx-rss-excerpt.xml`
- **RSS**（`v2/cap-alerts/cn-cma-xx/rss.xml`，IFRC Alert Hub 也是抓這條）：523 KB、7.6 秒、固定 500 則，這次只涵蓋 06:04Z–18:02Z（約 12 小時），
  含解除電文。溫州那則是 01:35Z 發、有效到 10/24，**已經不在 RSS 裡**，所以「現在生效什麼」要看 `wmo_all.json`，RSS 不夠
- **怎麼對到機場**：建議照 `cwaAreas` 的做法，每個機場在 `airports.json` 寫縣級代碼，CAP 的 `geocode` 前 6 碼相同、或是整個地市／省的代碼
  （尾碼補零，例如 `330300`、`310000`）就算涵蓋。下表的代碼是我依行政區劃查的，**要再核對**：

  | 機場 | 所在區縣 | 代碼（待核） |
  | --- | --- | --- |
  | PVG | 上海市浦東新區 | 310115 |
  | SHA | 上海市長寧區、閔行區（跨兩區） | 310105、310112 |
  | HGH | 杭州市蕭山區 | 330109 |
  | NGB | 寧波市海曙區 | 330203 |
  | WNZ | 溫州市龍灣區 | 330303 |
  | FOC | 福州市長樂區 | 350112 |
  | XMN | 廈門市湖里區 | 350206 |
  | JJN | 泉州市晉江市 | 350582 |
  | SWA | 揭陽市（榕城區或揭東區，要查） | 445202／445203 |
  | SZX | 深圳市寶安區 | 440306 |
  | CAN | 廣州市白雲區、花都區（跨兩區） | 440111、440114 |
  | ZUH | 珠海市金灣區 | 440404 |
  | HAK | 海口市美蘭區 | 460108 |
  | SYX | 三亞市天涯區 | 460204 |

  坑：有些預警只發到**鄉鎮街道**（溫州那則只有海濱街道），用縣級比對會偏保守（同區其他街道的預警也算到機場）；
  要更準就得每個機場寫到鄉鎮（9 碼），但機場跨好幾個街道、行政區又常調整，建議先用縣級
- **請求數**：`wmo_all.json` 一次＋只對發布台前 4 碼落在 13 個地市（3101、3301、3302、3303、3501、3502、3505、4452、4403、4401、4404、4601、4602）
  的那幾則抓 CAP 原文（這次是 3 則：溫州、北侖、象山）

### 2.4 韓國（`mid` 095，氣象廳 KMA）

- **內容**：現在 6 則，全是英文：`StrongWind Advisory Change`（黑山島、紅島）、`Wind Wave Advisory`（海上）。事件名的寫法是
  `<種類> Advisory|Warning`，後面接 `Change`／`Clear`（IFRC 歷史裡還有 `HeavyRain Advisory`、`StrongWind Warning Change`、
  `Wind Wave Warning Change`、`ColdWave Advisory`、`Wind Wave Advisory Clear`）。KMA 的特報種類有颱風、強風、豪雨、大雪、風浪、暴風海嘯、
  乾燥、寒波、黃沙、酷暑；**颱風的英文 `event` 這次沒看到實例**（推測是 `Typhoon Advisory`／`Typhoon Warning`），**沒有濃霧特報**
- **地區**：CAP 有**多邊形**（`<polygon>` 緯度,經度）＋英文 `areaDesc`；`msgType` 會用 `Update`、`references` 串前一則；`parameter` 裡有 `t6`
  （全國現行特報一覽）
- **語言**：SWIC 只有英文（`kr-kma-weather-en`），沒有韓文、中文
- **怎麼對到機場**：點落在多邊形裡，但要加一點緩衝（仁川在永宗島填海地、濟州在海邊，會遇到和溫州一樣的問題）；或用 `areaDesc`
  （例如 Incheon、Seoul、Busan、Jeju-do northern）比對，名稱要等看到實例再定
- **原始 feed**：`https://www.weather.go.kr/w/rss/cap/warning.do`（WMO 登錄表、IFRC 都列），這台連線被重設（`weather.go.kr` 整站都是），
  GitHub Actions 能不能連要等接的時候試
- **公共資料入口網**（沒申請，只記怎麼申請）：data.go.kr 的「기상청_기상특보 조회서비스」（`apis.data.go.kr/1360000/WthrWrnInfoService`）
  要用 data.go.kr 帳號申請 serviceKey，一般是免費、開發帳號自動核准、每日有呼叫次數上限（**這次沒查到官方頁面確認上限與授權條款**）。
  SWIC 已經拿得到，建議先不申請
- **樣本**：`swic/cap/kr-strongwind-advisory-change.xml`

### 2.5 菲律賓（`mid` 021，PAGASA）

- **內容**：現在 7 則：`Tropical Cyclone Warning : Super Typhoon Rosal (CHAMPI) Signal #1`／`#2`（巴丹、卡加延、伊莎貝拉、北伊羅戈、阿帕堯）、
  `General Flood Advisory (Moderate)`。PAGASA 自己的 feed 還有分區的 GFA（General Flood Advisory）
- **風球號數**：PAGASA 原始 CAP 的 `parameter` 有 `Public Storm Warning Signal Level`（1–5）；`headline` 也有 `Signal #2`。
  Signal #2＝「62–88 km/h（34–47 節）、24 小時內」
- **地區**：`geocode` 的 `SAME` 是 PSGC 9 碼省碼（巴丹 `020900000`、卡加延 `021500000`），一則可以有好幾省；SWIC 另配了多邊形
- **怎麼對到機場**（代碼待核）：MNL 在馬尼拉大都會第 4 區（帕賽／帕拉納克）`137600000`、CEB 在拉普拉普市（高度都市化市，`072226000`；
  宿霧省 `072200000`）、CRK 在邦板牙省 `035400000`（馬巴拉卡特市）。PAGASA 有時寫「the northern portion of …」，只寫省碼時會偏保守
- **原始 feed**：`https://publicalert.pagasa.dost.gov.ph/feeds/`，Atom、匿名、19 KB、約 2 秒，51 則（10/15 以來），
  每則連到 `output/wcp/<uuid>.cap`（10 KB、約 2 秒）；`<rights>` 寫 CC BY 4.0。和 SWIC 那份是同一則（SWIC 版本的 `severity` 寫法略有不同，
  以原始為準）
- **樣本**：`pagasa/feeds.atom`、`pagasa/89aaa5d5-b8ab-419f-83ef-7ba6266947f0.cap`（Signal #1 原文）、`swic/cap/ph-tcws2-batanes.xml`（SWIC 版 Signal #2）

### 2.6 越南（`mid` 082，水文氣象總局 NCHMF）

- SWIC：`cap-status` 是 2（開發／測試中），`wmo_all.json` 0 則
- 原始 feed：IFRC Alert Hub 列 `https://smartalert.nchmf.gov.vn/smartalert/capfeed.php`（Atom、每 10 分鐘抓一次、狀態 Active），
  這台連線被重設（`nchmf.gov.vn` 首頁可以連）
- IFRC 的 `historicalAlerts` 越南共 47 則，**最後一則是 2024-12-03**，之後沒有新的；有 `Typhoon warning`、`Severe tropical storm warning`、
  `Tropical storm warning`、`Tropical depression warning`、`Strong wind warning`、`Heavy rain warning`，語言 `en-VN`，地區是省名英文（無聲調）連寫
  （「Da Nang, Quang Binh, Quang Nam, Quang Ngai…」）或海域（「North Bien Dong sea」）
- 坑：越南 2025 年併省（例如坚江併入安江，富國島就換省名；峴港併廣南；胡志明市併平陽、巴地頭頓），舊名單會對不上
- **樣本**：`ifrc/historical-vnm-last12.json`
- 結論：**現在沒有一條驗證得到、還在更新的路**

### 2.7 帛琉（ROR）

- 帛琉不是 WMO 會員，SWIC 沒有。WMO 登錄表把「Palau Weather Service Office」登在美國底下，feed 是舊的
  `alerts.weather.gov/cap/wwaatmget.php?x=PMZ153`（這台被代理擋，502；NWS 舊 CAP 網址已經換成 `api.weather.gov`），而 **`PMZ153` 是天寧島海域**，登錄資料過時
- `api.weather.gov`（現在關島用的那一支）：
  - `/zones?area=PW`：`PWC004`（Airai，county）…、`PWZ001`–`PWZ008`（public／fire）
  - `/alerts/active?area=PW`、`/alerts?area=PW&start=2026-06-01`：**0 則**（和 HD3 查的一樣）
  - `/alerts?zone=PMZ161`（Koror Palau Coastal Waters）：**4 則 Small Craft Advisory**（10/19 起，最新 10/21 05:02 ChST），
    同一則也涵蓋雅浦海域 `PMZ171`；2024 年起沒有任何 Tropical Storm／Typhoon Watch／Warning
- 結論：NWS 關島分處確實在發帛琉的海上產品，但**陸地警報（PWZ）從沒出現過**。要不要先把 ROR 接上 `nws`（`nwsZone: "PWZ003"`，
  不多打請求，因為 `zone` 可以逗號串在關島那一個請求裡）等它哪天出現，見第 5 節
- **樣本**：`nws/alerts-zone-PMZ161.json`、`nws/zones-area-PW.json`

### 2.8 29W 期間現在生效中的警報（拿來驗證涵蓋範圍）

| 國家 | 生效中（和 29W 有關的） | 我們的機場有沒有中 |
| --- | --- | --- |
| 中國 | 浙江沿海一整排大風黃色預警：溫州市台（龍灣區，到 10/24）、蒼南、平陽、洞頭、瑞安、龍港、樂清、台州各區縣、舟山四區縣、寧波北侖、象山、永康；廣東惠東暴雨黃色 | **WNZ 用縣級代碼會中**（溫州大風黃色）；用 SWIC 多邊形不會中。NGB（海曙）不中（北侖、象山是別區）。其他 12 個沒有 |
| 韓國 | 黑山島強風特報、南海／東海風浪特報（海上） | 沒有 |
| 菲律賓 | Signal #2 巴丹；Signal #1 北伊羅戈、阿帕堯、卡加延、伊莎貝拉（＋前一報的卡坦端內斯）；卡加延谷地 GFA | 沒有（MNL、CEB、CRK 都不在） |
| 越南 | 拿不到 | — |
| 帛琉 | PMZ161 Small Craft Advisory（海上，不是颱風） | 不算 |

Champi 預測往北北西走向東海，接下來幾天浙江、福建、上海很可能發颱風預警，**正好是華東 8 個機場**。

---

## 3. 授權（原文照錄）

**SWIC 使用須知**（`https://severeweather.wmo.int/note.html`）：

> The information on Severe Weather Information Centre (SWIC) website is based on advisories issued by Regional Specialized
> Meteorological Centres (RSMCs), Tropical Cyclone Warning Centres (TCWCs), and official warnings issued by NMHSs for their
> respective countries or regions. The information is free for re-use by media or other websites. When doing so, it should be
> indicated that they are issued by the respective Tropical Cyclone RSMCs, TCWCs or NMHSs.

同一頁也寫：

> If no warning is found on land on the SWIC map, it may be due to other reasons apart from no warning is in effect for that area.
> The reasons include but not limited to (i) warnings are issued but not made available in / not comply with CAP format; and
> (ii) CAP feeds published are not accessible.

（所以「SWIC 沒有警報」不能當成「官方沒有警報」，網頁文字要寫清楚。）

**WIS2 資料集**（Global Discovery Catalogue 的 `urn:wmo:md:hk-hko-swic:recommended.weather.advisories-warnings`，`wmo:dataPolicy: recommended`）`rights`：

> SWIC is the centralised platform aggregating the authoritative warnings and advisories in Common Alerting Protocol (CAP) format
> issued by the alerting authorities worldwide. The Register of Alerting Authorities provides the records of such authoritative
> sources. Users should refer to the respective alerting authorities about the copyright information of the CAP data.

**PAGASA feed** `<rights>`：

> Copyright, Philippine Atmospheric Geophysical and Astronomical Services Administration. Licensed under CC BY 4.0.

**SWIC 的中國 RSS**（`cn-cma-xx/rss.xml`）頻道寫 `<copyright>public domain</copyright>`，看起來是 feed 模板的預設值，不建議當成 CMA 的授權依據。

**NWS**：美國政府公有領域（已在用）。

**KMA、CMA、NCHMF 自己的條款這次沒查到**（KMA 網站連不上；CMA 只走 SWIC）。中國另有《氣象災害預警信號發布與傳播辦法》要求轉播預警
要及時、準確、註明發布單位，轉載時照 SWIC 的要求標發布台即可，但**要不要另外查中國法規**，見第 5 節。

**建議標示**（資料來源頁與 `warnings[].text`）：「中國氣象局（經 WMO 惡劣天氣資訊中心 SWIC）」、「韓國氣象廳（經 WMO SWIC）」、
「菲律賓大氣地球物理天文管理局 PAGASA（CC BY 4.0）」；中國的最好寫到發布台（CAP 的 `sender`／`headline` 有，例如「溫州市氣象台」）。

---

## 4. WIS2 與其他管道

- **WIS2**：Global Discovery Catalogue（加拿大 `wis2-gdc.weather.gc.ca`、德國 `wis2.dwd.de/gdc`、中國 `gdc.wis.cma.cn` 三個都查得到，0.5–2.5 秒）
  只有 MQTT 通知連結：`mqtts://everyone:everyone@<broker>:8883`、topic
  `origin/a/wis2/hk-hko-swic/data/recommended/weather/advisories-warnings`，broker 有 cn-cma（`gb.wis.cma.cn`）、fr-meteofrance
  （`globalbroker.meteo.fr`）、br-inmet、us-noaa-nws（`wis2globalbroker.nws.noaa.gov`）。**沒有 HTTP 的資料清單或最近 24 小時的補抓介面**
  - 這台用 paho-mqtt 經代理連 meteo.fr 與 NOAA 的 8883，TLS 握手被斷（代理只轉 HTTPS），**沒收到通知樣本**
  - Global Cache：WIS2 規則是 Global Cache 只快取 `core` 資料，`recommended` 要回發布者下載（2023 ET-W2AT 會議紀錄寫明 recommended 不快取；
    WMO 文件有一處寫「core 與部分 recommended」，有點矛盾，沒查到最新版的明文）。所以通知的 `canonical` 連結應該就是指回
    `severeweather.wmo.int`，**等於繞一圈回到 SWIC**
  - 我們是每小時、每 6 小時的批次，要用 MQTT 得一直掛著訂閱（或另外架一個常駐的收件程式），不划算。**不建議走 WIS2**
- **IFRC Alert Hub**：公開 GraphQL `https://alerthub-api.ifrc.org/graphql/`（匿名，`public { feeds { … } }` 列 183 個 feed），
  是找各國原始網址最好的地方（樣本 `ifrc/feeds-chn-kor-phl-vnm-usa.json`）。它自己也有警報資料，但內容就是轉抓上面這幾條，沒有多拿到什麼；
  GitHub 寫的 `cap-aggregator.azurewebsites.net/feeds/` 這台被代理擋
- **cap-sources.s3.amazonaws.com**（Alert-Hub.org 的舊鏡像）：`kr-kma-en`、`vn-nchmf-en`、`pw-wso-en`、`cn-mem-zh` 等目錄都在，
  但 rss 全停在 2018-12-06，已經沒在更新
- **Google Public Alerts**：`google.org/publicalerts` 與來源清單頁都 404，已經下架
- **WMO 警報機關登錄表**（`alertingauthority.wmo.int/rss.xml`，254 KB）：各國 CAP feed 網址的官方登錄，但有些過時（帛琉 `PMZ153`、中國 `12379.cn` 是 http）

---

## 5. 建議

### 5.1 先接哪幾國、走哪條路

1. **中國（14 個機場）＋韓國（4 個）＋菲律賓（3 個）一起接 SWIC**，新來源 `sources/swic.py`、`warningSources: ["swic"]`。
   Champi 接下來幾天最可能影響的就是華東 8 個機場，中國最值得先做
2. **菲律賓改走 PAGASA 原始 feed 也可以**（授權最清楚、延遲一樣短、有風球號數參數）；但 SWIC 一個請求就同時有三國，
   先統一走 SWIC，PAGASA 當備援或之後再換，由主對話決定
3. **越南先不接**：SWIC 沒有，原始 feed 這台連不上、IFRC 兩年沒收到新的。可以等越南在 SWIC 的狀態變成 1，或在 GitHub Actions 上試一次
   `smartalert.nchmf.gov.vn` 再說
4. **帛琉維持不接**，或只把 ROR 接上 `nws`（`nwsZone: "PWZ003"`，和關島同一個請求、只多一個 zone），等哪天 NWS 發帛琉的陸地颱風警報自然會收到；
   代價是 `official.warnings` 會變 `true`，網頁就不再顯示「官方警報：尚未提供」，但實際上可能永遠沒有警報。**待定**

### 5.2 接進管線的做法（草案）

- `sources/swic.py`：
  1. GET `https://severeweather.wmo.int/json/wmo_all.json`（一次，約 0.9 MB），只留 `mid` 是 `001`、`095`、`021` 的
  2. 先用 `event` 篩種類（白名單，見 5.3），中國再用 `id` 前 4 碼篩 13 個地市（14 個機場）
  3. 剩下的逐則抓 `https://severeweather.wmo.int/v2/cap-alerts/<url>`（中國這次 3 則、韓國 6、菲律賓 7；颱風期間估 10–40 則），
     同一個 URL 一報只抓一次；可以平行
  4. 用 CAP 原文判斷：`status` 是 `Actual`、`msgType` 不是 `Cancel`、`expires` 在產出時間之後；中國的解除電文（headline「lifts」、`msgType` 要再確認）不算；
     同一機場同一種取 `sent` 最新的（和 `nws.py` 一樣）
  5. 對機場：中國用 `geocode` 前 6 碼（新欄位，例如 `cmaAreas: ["330303"]`，地市／省級代碼也算涵蓋）；韓國用 CAP `<polygon>`＋緩衝
     （例如 5 公里，新欄位或直接用機場座標）；菲律賓用 `SAME` 省碼（`psgcAreas`）
  6. 原始回應另存 `history/raw/<日期>/<時間>-swic.json`（`wmo_all.json` 摘錄＋抓過的 CAP），和氣象署的做法一樣
- **不建議**用 WFS 的 `INTERSECTS`：時間欄位錯、多邊形粗、會回過期的
- `BUDGET_S["swic"]`：`wmo_all.json` 0.6–1 秒＋CAP 每則 0.6–1 秒，平時 5–15 秒、颱風期間 40 則平行抓約 10–20 秒，**建議 45 秒**（和 `cwa`、`jma` 一樣）；
  總預算多 45 秒
- `latest.json`：`warnings[].source` 多 `"swic"`（或分成 `"cma"`、`"kma"`、`"pagasa"`，比較好標示來源，**待定**），`sources.swic`；
  14＋4＋3 個機場 `official.warnings` 變 `true`。這是契約的加值改動，要經 Shawn 轉給 Duado
- 網頁「依據」要寫「中國氣象局（經 WMO SWIC）」等，並註明 SWIC 沒有不代表官方沒發（第 3 節原文）

### 5.3 kind 命名與等級（**等級待定**，由主對話與產品負責人定）

照現有的 `cwa_dense_fog`、`jma_heavy_snow` 命名：

| 國家 | 事件 | kind（建議） | 等級建議（待定） | 類別 |
| --- | --- | --- | --- | --- |
| 中國 | 台風 紅／橙 | `cma_typhoon_red`、`cma_typhoon_orange` | 高 | wind |
| 中國 | 台風 黃 | `cma_typhoon_yellow` | 中 | wind |
| 中國 | 台風 藍 | `cma_typhoon_blue` | 低（只列出） | wind |
| 中國 | 大風 橙／紅 | `cma_gale_orange`、`cma_gale_red` | 中 | wind |
| 中國 | 大風 黃（這次溫州就是這個） | `cma_gale_yellow` | 低（只列出）；藍色不列 | wind |
| 中國 | 暴雨 紅／橙 | `cma_rainstorm_red`、`cma_rainstorm_orange` | 中（比照天文台黑雨）／低 | rain |
| 中國 | 大霧 紅／橙 | `cma_fog_red`、`cma_fog_orange` | 中（比照氣象署濃霧特報） | fog |
| 韓國 | 颱風警報／注意報 | `kma_typhoon_warning`、`kma_typhoon_advisory` | 高／中（比照 NWS 的 Warning／Watch） | wind |
| 韓國 | 強風警報／注意報 | `kma_strong_wind_warning`、`kma_strong_wind_advisory` | 中／低 | wind |
| 韓國 | 豪雨警報 | `kma_heavy_rain_warning` | 中 | rain |
| 韓國 | 大雪警報 | `kma_heavy_snow_warning` | 中（比照 JMA 大雪警報） | snow |
| 菲律賓 | 風球 #3–#5 | `pagasa_tcws_3`…`pagasa_tcws_5` | 高 | wind |
| 菲律賓 | 風球 #2（34–47 節） | `pagasa_tcws_2` | 高或中（天文台 8 號是高，#2 的風速在 8 號範圍內） | wind |
| 菲律賓 | 風球 #1 | `pagasa_tcws_1` | 低（比照天文台 1 號） | wind |
| 菲律賓 | 豪雨警報（紅） | `pagasa_rainfall_red` | 中；這次沒看到實例，`event` 寫法待確認 | rain |

韓國沒有濃霧特報；中國的寒潮、霜凍、道路結冰、沙塵暴、森林火險先不接。`text` 中文三語照 `nws.py` 用固定句型（例如「大風黃色預警生效中（溫州市氣象台）」），
英文可用 CAP 的英文 `headline`；中國有簡中原文可放 `detail`。

---

## 6. 要產品負責人或主對話決定的事

1. **要不要接、接哪幾國**：建議中國＋韓國＋菲律賓一起走 SWIC（第 5.1 節）
2. **SWIC 是網頁內部用的 JSON**（沒有文件、可能改格式），能不能接受？（JMA bosai 也是這樣，先例已有）
3. **中國的授權**：SWIC 明說可再使用、要註明發布機關；要不要另外查中國對轉載氣象預警的法規（例如《氣象災害預警信號發布與傳播辦法》），
   還是以 SWIC 的須知為準
4. **等級**（第 5.3 節全部待定），尤其：中國大風黃色要不要列出、菲律賓風球 #2 算高還是中
5. **`source` 要一個 `"swic"` 還是分成 `"cma"`／`"kma"`／`"pagasa"`**（網頁「依據」區的標示）
6. **對機場的粒度**：中國用縣級代碼（偏保守，這次 WNZ 會中）還是鄉鎮級；第 2.3 節的代碼表要核對（尤其 SWA）
7. **帛琉**要不要先接 `nws`（`PWZ003`）讓 `official.warnings` 變 `true`（第 5.1 節第 4 點）
8. **越南**：要不要在 GitHub Actions 上試一次 `smartalert.nchmf.gov.vn`、`weather.go.kr`（這台連不上，要開一個暫時的 workflow 或在下一個實作 PR 裡試）
9. **韓國公共資料入口網的金鑰**：SWIC 拿得到就不申請（建議）；要的話由 Shawn 申請

---

## 樣本檔（`docs/surveys/samples/2026-10-22-cap/`）

| 檔案 | 內容 |
| --- | --- |
| `swic/wmo_all-cn-kr-ph.json` | `wmo_all.json` 摘錄（中、韓、菲 355 則），2026-10-21 17:52Z |
| `swic/wmo_member-excerpt.json`、`swic/cap-status-excerpt.json`、`swic/tc_inforce.json` | 會員代碼、CAP 進度、生效中的熱帶氣旋 |
| `swic/cap/cn-wenzhou-gale-yellow.xml` | 溫州市氣象台大風黃色預警（龍灣區海濱街道，WNZ） |
| `swic/cap/cn-guangde-dense-fog-yellow.xml` | 廣德市氣象台大霧黃色預警（中英兩個 `info`） |
| `swic/cap/kr-strongwind-advisory-change.xml` | KMA 強風注意報變更（有多邊形） |
| `swic/cap/ph-tcws2-batanes.xml` | PAGASA 風球 #2 巴丹（SWIC 副本） |
| `swic/wfs-capurl-wenzhou-longwan.json` | WFS 回的龍灣區多邊形（WNZ 在外面約 5 公里） |
| `swic/cn-cma-xx-rss-excerpt.xml` | 中國 RSS 前 20 則（原檔 500 則） |
| `pagasa/feeds.atom`、`pagasa/89aaa5d5-….cap` | PAGASA 原始 Atom feed 與風球 #1 原文（有 `Public Storm Warning Signal Level`） |
| `wis2/gdc-urn-wmo-md-hk-hko-swic-advisories-warnings.json` | WIS2 Global Discovery Catalogue 的資料集中繼資料 |
| `ifrc/feeds-chn-kor-phl-vnm-usa.json`、`ifrc/historical-vnm-last12.json` | IFRC Alert Hub 的 feed 清單與越南最後 12 則 |
| `nws/alerts-zone-PMZ161.json`、`nws/zones-area-PW.json` | 帛琉海域的 NWS 警報、帛琉的 zone 清單 |
