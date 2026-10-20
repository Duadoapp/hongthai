# HongThai

台灣、華東、華南・港澳、沖繩、日本、韓國、越南、菲律賓、關島・帛琉九個地區 51 個機場（下面「機場」）未來 5 天的
**停飛風險**等級：強風（含分跑道的側風），第五階段（HD8）起加大雨／雷雨、大雪／結冰、濃霧／低雲。
每天四次抓氣象資料，輸出一份 `latest.json`，用 GitHub Pages 發布：

<https://duadoapp.github.io/hongthai/latest.json>

給 [duado.app/hongthai/](https://duado.app/hongthai/) 的網頁讀（網頁在 Duado 那邊，不在這個 repo）。
JSON 格式是和網頁的契約，見下面「輸出」；欄位名稱與型別不能改，要加欄位可以。

> **免責**：這是用公開氣象資料自動算的參考資訊，預報有誤差。航班是否停飛以航空公司與機場公告為準，
> 依此做的任何決定由使用者自行負責。

## 機場

第三階段（H9，2026-10-19）起 41 個、分六個地區，HD3 再加三個地區十個機場，共 **51 個、九個地區**；
名單是 Shawn 指定的（台灣有定期直飛），ICAO／IATA 逐一對過 OurAirports（H9 的 41 個是 2026-10-18 的資料、
HD3 的 10 個是 2026-10-18 18Z 下載的，51 個都一致）。`latest.json` 的 `regions` 與 `airports[]` 照下表的順序：

| 地區 id | 地區 | 機場 |
| --- | --- | --- |
| `taiwan` | 台灣 | 桃園 RCTP/TPE、松山 RCSS/TSA、高雄 RCKH/KHH、台中 RCMQ/RMQ、台南 RCNN/TNN、花蓮 RCYU/HUN、台東 RCFN/TTT、澎湖 RCQC/MZG、金門 RCBS/KNH、馬祖南竿 RCFG/LZN |
| `east-china` | 華東 | 上海浦東 ZSPD/PVG、上海虹橋 ZSSS/SHA、杭州 ZSHC/HGH、寧波 ZSNB/NGB、溫州 ZSWZ/WNZ、福州 ZSFZ/FOC、廈門 ZSAM/XMN、泉州 ZSQZ/JJN |
| `south-china-hkmo` | 華南・港澳 | 潮汕 ZGOW/SWA、深圳 ZGSZ/SZX、廣州 ZGGG/CAN、香港 VHHH/HKG、澳門 VMMC/MFM、珠海 ZGSD/ZUH、海口 ZJHK/HAK、三亞 ZJSY/SYX |
| `okinawa` | 沖繩 | 那霸 ROAH/OKA、石垣 ROIG/ISG、宮古 ROMY/MMY |
| `japan` | 日本 | 鹿兒島 RJFK/KOJ、福岡 RJFF/FUK、關西 RJBB/KIX、中部 RJGG/NGO、羽田 RJTT/HND、成田 RJAA/NRT、新千歲 RJCC/CTS、仙台 RJSS/SDJ |
| `korea` | 韓國 | 濟州 RKPC/CJU、釜山 RKPK/PUS、仁川 RKSI/ICN、金浦 RKSS/GMP |
| `vietnam` | 越南 | 河內 VVNB/HAN、胡志明 VVTS/SGN、峴港 VVDN/DAD、芽莊（金蘭）VVCR/CXR、富國島 VVPQ/PQC |
| `philippines` | 菲律賓 | 馬尼拉 RPLL/MNL、宿霧 RPVM/CEB、克拉克 RPLC/CRK |
| `guam-palau` | 關島・帛琉 | 關島 PGUM/GUM、帛琉 PTRO/ROR |

- 51 個都用全球資料：ECMWF、GFS、TAF／METAR（有的話）、跑道側風
- 官方警報：台灣十個看中央氣象署、香港看天文台、澳門看 SMG、關島看美國國家氣象局（NWS，HD3）、日本 8 個
  與沖繩 3 個看日本氣象廳（JMA，HD9，目前只接大雪警報）；其他 27 個還沒接（韓國之後另外的 HD 補；中國官方
  颱風預警、越南、菲律賓先不接；帛琉 NWS 查不到，見下面「資料來源與授權」），`airports[].official.warnings`
  是 `false`、`warnings` 是 `[]`
- **沒有 TAF 的機場**（2026-10-18 實測 AviationWeather）：花蓮 RCYU、金門 RCBS、馬祖 RCFG、溫州 ZSWZ、
  泉州 ZSQZ、珠海 ZGSD、宮古 ROMY。這幾個 `taf: null`，官方層只剩 METAR 與警報：METAR 在 3 小時內時
  **第一格由 METAR 單獨撐起**（HD13，`official.kind: "metar"`），之後 0–30 小時沒有警報的格以模式為準。
  AviationWeather 只有宮古有 METAR；**金門、馬祖用中央氣象署局屬站觀測（`O-A0003-001`，金門 467110、
  馬祖 467990）當 METAR**（HD13，`metar.source: "cwa"`）；花蓮、溫州、泉州、珠海四個 METAR 也沒有
  （`metar: null`）。HD3 加的十個（越南、菲律賓、關島、帛琉）2026-10-18 18Z 一次請求 51 站實測都有 TAF 與 METAR
- 航班取消／延誤統計（`cancellations.py`）只有桃園、松山、高雄、香港、澳門五個機場有來源

## 怎麼算

時間軸從「現在往前取整到 00／06／12／18Z」起，每格 6 小時、共 20 格（120 小時）。

風速一律用**節**（HD2，2026-10-19 起；1 m/s = 1.943844 節）：等級規則、log、之後的 AI 短評與預覽圖都用節，
模式陣風解析完就換算成節。`latest.json` 既有的 m/s 欄位（`hresGustMs`、`gustMs`）照出，另加節的欄位。

| 層 | 資料 | 規則（初版，保守，之後用實際紀錄校準） |
| --- | --- | --- |
| 模式（0–120 小時） | ECMWF HRES（IFS）10 米陣風與 10 米風（風只抓 6 小時整的時間點）、GFS 地面陣風與 10 米風、ECMWF 系集「10 米陣風 ≥ 10／15／25 m/s（≈ 19.4／29.2／48.6 節）機率」、ECMWF AIFS Single 與 NOAA AIGFS 的 10 米風（HD14）；Open-Meteo 的 DWD ICON（陣風）、JMA GSM（10 米風）、Google WeatherNext 2 系集 64 個成員的 10 米風（HD16） | **八個模式投票**（HD14、HD16，下面「多模式投票」）：每個模式各自判——陣風（AIFS、AIGFS、JMA GSM、WeatherNext 2 用平均風 × 機場的係數估算）≥ 48 節高、≥ 37 節中；兩個系集只投高（IFS 系集陣風 ≥ 49 節機率 ≥ 30%、WeatherNext 2 估算陣風 ≥ 48 節的成員 ≥ 30% 投高、否則投低）。某一級的票（認為 ≥ 這一級的模式數）達到有資料模式數的一半就成立，取成立的最高 |
| 官方（0–30 小時） | TAF、METAR、香港天文台與澳門地球物理氣象局（SMG）熱帶氣旋信號、中央氣象署颱風警報、美國國家氣象局（NWS）關島的颱風／熱帶風暴警報與守視、日本氣象廳（JMA）日本與沖繩的大雪警報（HD9） | 天文台／SMG 8 號以上 → 高、3 號 → 中；氣象署陸上颱風警報且機場在警戒區 → 高、海上警報（或陸上但不在警戒區）→ 中；NWS Typhoon Warning、Tropical Storm Warning → 高，Typhoon Watch、Tropical Storm Watch → 中；JMA 大雪特別警報、暴風雪特別警報（HD16）→ 高、大雪警報 → 中、暴風雪警報低（只列出），算 `snow`；TAF 陣風 ≥ 48 節（或平均風 ≥ 35 節）→ 高、陣風 ≥ 37 節 → 中；TAF **只算產出時間之後還有效的時段**（HD7，見下面）；**沒有 TAF 的機場第一格可由 METAR（含氣象署觀測）單獨撐起**（HD13，見下面） |
| 側風（官方、模式各自） | TAF 各時段與 METAR 的風向風速；HRES、GFS、ICON 的 10 米風向配各自的陣風；AIFS、AIGFS、JMA GSM 的 10 米風向配估算陣風（WeatherNext 2 系集不算側風） | 含陣風側風 ≥ 33 節 → 高、≥ 27 節 → 中；和上面的陣風規則**取較高的等級**（模式層是每個模式各自取較高，再投票） |

- 門檻依據：陣風（TAF 與模式同一套）是桃園機場空橋規則——最大瞬間風速 37 節（蒲福 8 級）啟動空橋防護、
  48 節（10 級）空橋停用、55 節以上全部綁死；側風是窄體客機常見作業限制——737-800 濕跑道起飛約 27 節、
  乾跑道約 33 節。所有機場先用同一套，之後找到個別機場的作業標準再在 `airports.json` 覆寫
- NWS 的對等級（Shawn 2026-10-19 定案）：Warning 是確定會有（Tropical Storm Warning＝36 小時內持續
  34–63 節，等同天文台 8 號、也超過 TAF 平均風 ≥ 35 節＝高的規則），Watch 是可能會有
- 系集：ECMWF 開放資料的機率產品只有 ≥ 10／15／25 m/s，沒有 37 節的，所以系集只投「高」那一輪
  （`p49Kt` ≥ 30% 投高、否則投低；判中時不算分母，HD14）。`p29Kt` 只輸出、不進規則；
  `p37Kt` 一律 `null`（之後另一支 HD 用 GEFS 系集成員自己算）

- 側風分量＝含陣風的風速（有陣風用陣風，沒有用平均風）× |sin(風向 − 跑道方位)|，每條跑道兩個方向取小的，
  再取所有跑道裡**最小**的（還有一條能用就不算停飛）；風向可變（VRB）或沒有風向時側風＝風速本身
- HRES 的 10 米風只抓 00／06／12／18Z 的時間點（H10，減少下載量），每個陣風區間配**結束時間往後最近**
  的那個時間點的風向
- 0–30 小時以官方為準；官方與模式不同級標 `gap: true`
- 已經過去的 TAF 時段不算（HD7，2026-10-19）：TAF 的主時段、TEMPO、BECMG、PROB 都只算結束時間在產出時間
  之後的（跨過產出時間的照算），所以只影響第一格（現在所在的那格）。第一格的 TAF 時段全部已經過去時當作
  沒有 TAF：有警報就是「只有警報」的官方層（METAR 側風照算），沒有警報就退回模式
- 沒有 TAF 的機場（HD13，2026-10-19）：機場完全沒有 TAF（不是 HD7 那種「TAF 全部過去」）、METAR 在 3 小時內、
  而且風、能見度、雲幕、天氣至少有一樣 → **第一格**的官方層由 METAR 組成（`kind: "metar"`；`windKt`／`gustKt`／
  `crosswindKt`／`wx` 都從 METAR 來，風照 TAF 的陣風規則），警報照舊疊上去；之後的格照舊。用到的是金門、
  馬祖（氣象署觀測）與宮古；有 TAF 的機場完全不受影響
- `agreement`：HRES 與 GFS 的陣風落在同一級＝`agree`（HD14 起還是只看這兩個）
- `confirmed.json` 人工填的已確認停飛時段 → 該格 `level: "confirmed"`
- 門檻在 `airports.json`，細節（時間格怎麼對、警報套幾小時）寫在 `src/hongthai/assess.py` 開頭

### 多模式投票（HD14、HD16）

Shawn 2026-10-19 定案。模式層從「HRES、GFS 取較高（加系集撐高）」改成**投票**，官方層（TAF、METAR、警報）
照舊優先、`gap` 照舊（官方層等級和投票結果不同）：

- **八票**（`config.MODELS`，輸出順序）：`ifs`（ECMWF HRES）、`gfs`（NOAA GFS）、`ifs-ens`（ECMWF 系集）、
  `aifs`（ECMWF AIFS Single，AI 模式）、`aigfs`（NOAA AIGFS，AI 模式），HD16（2026-10-21 上線）加 `icon`
  （DWD ICON global）、`jma`（JMA GSM）、`wn2-ens`（Google WeatherNext 2 系集），後三個經 Open-Meteo
  （`src/hongthai/sources/openmeteo.py`）。每個模式一票、權重相同
- 每一類（`wind`、`rain`、`snow`、`fog`）各自投：某等級 L 的票＝這一類等級 ≥ L 的模式數，**票數 × 2 ≥
  分母就成立**，從高往低看，取成立的最高。分母＝這一格這一類**有資料**的模式；只有 1 個模式有資料就它決定
  （2 票裡 1 票也成立，和 HD14 以前兩個模式取較高一致）。四類的結果再取最高＝`model.level`
- **系集只投「高」**：`p49Kt` ≥ 30% 投高、否則投低；**判「中」時不算分母**（不然它永遠投低、把中的票拉下來）。
  所以系集單獨撐不起高（IFS 低、GFS 低、系集高 → 1 × 2 < 3 → 低）
- **WeatherNext 2 系集也只投「高」**（HD16，比照 IFS 系集）：64 個成員各自取格頭尾兩個時間點大的 10 米風 ×
  機場的 G＝估算陣風，≥ 48 節（`modelHighGustKt`）的成員比例（`models[].p49Kt`）≥ 30%（`ecP49High`）投高、
  否則投低，判中時不算分母；不投雨、雪、霧。那筆的 `windKt`／`gustKt` 是成員的中位數（估算）
- **沒有陣風的模式**（AIFS、AIGFS、HD16 起 JMA GSM）：10 米平均風 × **機場的係數 G**（HD18，下一段）估算
  陣風，標 `gustEstimated: true`，門檻同陣風；側風用估算陣風算。網頁與 AI 短評寫「估算陣風」。ICON 有自己
  的陣風（Open-Meteo 的「前一小時最大陣風」，一格取 6 個小時裡最大的）
- 雨：IFS（6 小時雨量，或系集 24 小時雨量 ≥ 50 mm 機率 ≥ 30%，就是 `model.ec.rain`）、GFS、AIFS、AIGFS、
  ICON、JMA GSM（逐時雨量加總，HD16）投；兩個系集不投雨
- 雪：**只有有降水型態的模式投**——IFS（`ptype`）、GFS（類別降水）、AIFS（6 小時降雪 ≥ 6 小時總降水的一半
  → `snow`，否則 `rain`，< 0.1 mm → `none`）、ICON 與 JMA GSM（HD16：格內有凍雨天氣碼 66／67 →
  `freezing_rain`、凍毛毛雨 56／57 → `freezing_drizzle`；否則降雪水當量（公分 ÷ 0.7）≥ 總降水的一半 → `snow`；
  其他同 AIFS）；AIGFS 沒有型態、不投（雪的分母不算它）。不用 2 米溫度猜型態
- 霧：只有 GFS 有能見度，**霧的分母永遠是 1**（GFS 說了算，最高到中，HD10）。Open-Meteo 的 ICON global、
  JMA GSM 能見度 2026-10-20 實抓全是 `null`（提示詞以為 ICON 有），所以 HD16 沒有改變霧的分母；哪天有值了
  會自動投（最高到中）
- **旁觀模式**（HD16，`Model.voting=False`）：照樣抓、照樣寫進 `models[]`（含 `levels`、`level`）與路徑檔，
  但**不算進任何一類的分母、不投票**（`vote.total` 不含它）；頂層 `models[].voting` 讓網頁標「旁觀，不投票」。
  HD16 的三票都投票，這個開關給 HD15 的 WeatherNext 3 與之後的新模式（先旁觀、累積紀錄再改成投票）
- **Open-Meteo 失敗或逾時**：這一報沒有這三票（三筆全 `null`、不算分母，其他照 5 票算），`sources.openmeteo.ok:
  false`＋`error`，整報照出；**也不沿用舊資料**（和 `ecmwf`／`gfs`／`aifs`／`aigfs` 的沿用不同：不想把 24 小時前
  的 WeatherNext 2 當今天的票）
- `causes`：依據是模式層時用**投票後**各類的等級排（同級 `wind`、`snow`、`rain`、`fog`）
- `model.vote`：`total`（風那一類的分母，含系集、不含旁觀模式）、`high`（投高的數）、`medium`（等級 ≥ 中的數，
  不含兩個系集，同判中的規則）、`low`（投低的數）、`level`（四類投票結果取最高，全無資料 `null`）、`thin`（風的分母 < 2）
- `model.ec`／`model.gfs`／`model.agreement` 欄位與值都不變（`ec.rain`、`gfs.fog` 等還是各自的等級）

### 估算陣風的係數（HD18、HD19）

Shawn 2026-10-20 定案，取代 HD14 的固定 1.4（`src/hongthai/gustfactor.py`）。拿 AIFS／AIGFS 去比同一格的
HRES 陣風不公平（颱風路線不同時同一格本來就差很多；GFS 自己的陣風也只有 IFS 的 0.76，IFS 陣風偏高、不能當
標準答案），所以改成**同一個模式自己的陣風 ÷ 平均風**：

- 定義：G＝陣風 ÷ 10 米平均風。IFS 用 HRES `10fg`（該格的 `hresGustKt`）÷ **格結束步長**的 √(u10²+v10²)；
  GFS 用 `GUST`（該格的 `gustKt`）÷ **同一時間點**（格內陣風最大那一點）的 10 米風速。同一模式、同一機場、
  同一格自己比自己，一格一個比例（兩位小數）
- **每個機場一個 G**：最近 **30 天**（`GUST_FACTOR_WINDOW_DAYS`）、每報每格的比例取**中位數**——**HD19 起
  只用 IFS 的樣本**（`gustfactor.G_SOURCE`；HD18 是 IFS 與 GFS 合在一起）；只收平均風 **≥ 10 節**的格
  （`GUST_FACTOR_MIN_WIND_KT`）；中位數夾在 **1.2～2.0**（`GUST_FACTOR_RANGE`，夾中位數、不夾樣本）
- **樣本不足的順序**（`gustFactorBasis`）：機場的 IFS 合格樣本 ≥ 40（`GUST_FACTOR_MIN_SAMPLES`）→
  `airport30d`；不然全部機場合併的 30 天 IFS 中位數（≥ 40）→ `all30d`；再不然這一報 IFS 的全體中位數（所有
  機場、所有格）→ `run`；這一報一個 ≥ 10 節的 IFS 格都沒有 → 固定 1.4（`GUST_FACTOR_DEFAULT`）→ `default`。**首報**（30 天窗裡
  只有這一報，例如 `history/gustfactor/` 還沒有）一律 `run`——那時「30 天」就是這一報，標 `airport30d`／
  `all30d` 會誤導
- `ecmwf`／`gfs` 失敗、沿用舊資料的那一報不寫新樣本（那個模式寫 `[]`），G 照 30 天窗算；AIFS／AIGFS 沿用
  舊數字時，用抄來的 `windKt` × **這一報**的 G 重算估算陣風（側風照新舊 G 的比例換算），不沿用舊 G
- **IFS 與 GFS 定義不同**：`10fg` 是時段內最大陣風（0–90 小時是前 1 小時、之後前 3／6 小時），`GUST` 是
  時間點的陣風。HD18 先合在一起取中位數；首報 IFS 中位數約 1.65、GFS 約 1.27，**HD19（Shawn 2026-10-20 定案）
  起只用 IFS**——每格看的是 6 小時內最大陣風，和 `10fg` 一致，颱風季不想讓 AI 模式再偏低一個月。**GFS 樣本
  照存**（`history/gustfactor/<YYYY-MM>.jsonl` 格式不變），報表照樣 IFS、GFS **分開印**，30 天後用
  `tools/gust_factor_report.py`（下面「怎麼跑」）一起檢討、對 METAR 驗證；AI 模式仍系統性偏低再加第二層修正
- `history/gustfactor/latest.json` 多 `"source": "ifs"`（G 用哪個模式的樣本；之後改回合併或改 GFS 改
  `G_SOURCE`，網頁不用動）；`n` 是 IFS 的樣本數（和門檻 40 比的是它），`nIfs`、`nGfs` 照寫（`nGfs` 只是備查）

### 新天氣種類（第五階段，HD8）

Shawn 2026-10-19 定案、**先求能跑**，門檻累積一個月紀錄再調。三類：`rain`（大雨＋雷雨）、`snow`（大雪＋
結冰）、`fog`（濃霧＋低雲幕）；颱風帶來的雨歸 `wind`（就是上面的規則）。**燈號還是一種「停飛風險」等級**：
每一層的等級＝風（陣風、側風、風的警報）與三類取最高，不是一種天氣一顆燈；種類只用在每格的 `causes`、
預覽圖小字與 AI 短評。原則：**貼近實際會停飛的情況，只會延誤的不升級、只寫進依據**。單位：雨量毫米、
能見度公尺、雲底呎、溫度 °C。

官方層（TAF 各時段與 METAR；只算 HD7 的「還有效且重疊」的時段；METAR 只進第一格、觀測 3 小時內，而且
該格要有 TAF，或由 METAR 撐起（HD13）——只有警報的格 `wx` 是 `null`）。每個時段各自判（雷雨和能見度要在同一個時段），一格取最高：

| 類 | 高 | 中 | 不升級（低） |
| --- | --- | --- | --- |
| `rain` | 冰雹：現象含 `GR`（TSGR、+TSGR、GR、SHGR） | `+TSRA`（`+TS` 開頭且含 RA）；或含 `TS` 且能見度 ≤ 1600 公尺 | TS、TSRA、SHRA、+SHRA |
| `snow` | `FZRA`、`FZDZ`、`PL`（任何強度）；`+SN`、`+SHSN` | `SN`／`SHSN`（不是 `-`／`+`）且能見度 ≤ 1600 公尺 | -SN；SN 但能見度 > 1600；FZFG 不走這裡 |
| `fog` | 能見度 < 400 公尺或雲底 ≤ 100 呎 | 能見度 < 1000 公尺或雲底 ≤ 200 呎 | 其他（任何原因的低能見度都算，FG／BR／FZFG／HZ／SN 都一樣；沒報不算） |

模式層（每格）：

| 類 | 高 | 中 | 資料 |
| --- | --- | --- | --- |
| `rain` | 6 小時雨量 ≥ 60 mm | ≥ 30 mm；IFS 另外看 EC 系集「24 小時雨量 ≥ 50 mm」機率 ≥ 30%（`p24hRain50`，24 小時窗取包住這格的最小值，同 `p49Kt`） | ECMWF `tp`（6 小時差）、`tpg50`；GFS `APCP` 6 小時那桶；HD14 起 AIFS `tp`（6 小時差）、AIGFS `APCP` |
| `snow` | 降水型態是雪（`snow`／`wet_snow`／`rain_snow`）且 6 小時水當量 ≥ 10 mm；凍雨類（`freezing_rain`／`freezing_drizzle`／`ice_pellets`）且 ≥ 1 mm | 雪且 ≥ 5 mm | ECMWF `ptype`、GFS 類別降水、AIFS 降雪比例（HD14）；各模式各自算（小雪不升級，和官方層一致） |
| `fog` | **沒有**（模式層的霧只到中，HD10） | GFS 能見度 < 1000 公尺（< 400 公尺也只是中） | **只有 GFS**（ECMWF 開放資料沒有能見度）；到高要官方層（TAF／METAR）真的報霧或低雲幕 |

- 一格的雨量、降水型態是「格結束時間」那個時間點的（EC 是 `tp` 的差、GFS 是前 6 小時那桶）；GFS 能見度
  取格頭尾兩個時間點的最小值。`model.agreement` **還是只看陣風**（值域不變）
- HD14 起每個模式各自判出三類的等級，模式層的結果是投票（上面「多模式投票」）；表裡的門檻不變

官方警報（新）：

| 來源 | 種類（`kind`） | 等級 |
| --- | --- | --- |
| 香港天文台 | 黑色暴雨警告信號 `rainstorm_black` | 中 |
| 香港天文台 | 紅色暴雨警告信號 `rainstorm_red`、雷暴警告 `thunderstorm` | 低：**只列出、不升級**（黃雨不列） |
| 中央氣象署 | 天氣特報「大豪雨」「超大豪雨」且機場的縣市在範圍 `cwa_heavy_rain` | 中（大雨、豪雨特報不算） |
| 中央氣象署 | 天氣特報「濃霧」且機場的縣市在範圍 `cwa_dense_fog`（HD13，台灣十個機場都適用） | 中 |
| 日本氣象廳 | 機場所在市町村的大雪警報 `jma_heavy_snow`（HD9，日本 8 個＋沖繩 3 個） | 中 |
| 日本氣象廳 | 大雪特別警報 `jma_heavy_snow_emergency`、暴風雪特別警報 `jma_snowstorm_emergency`（HD16） | 高 |
| 日本氣象廳 | 暴風雪警報 `jma_snowstorm` | 低：**只列出、不升級**（大雪注意報、風雪注意報不列） |

- 前三列算 `rain`、濃霧特報算 `fog`、JMA 四種算 `snow`，其他（颱風、熱帶氣旋信號）算 `wind`。**低的警報不會自己撐起官方層**：一格沒有
  TAF、只有低的警報時 `official` 是 `null`、退回模式；有 TAF 或有中以上的警報時照舊，
  `official.warnings[]` 列全部（含低的）。天文台 1 號信號也是低，HD8 起一樣照這條
- JMA 只接雪（HD9）：大雨、暴風、波浪等其他警報不接（風的警報留給之後；29W 驗證期間不能動到風的等級）；
  暴風雪特別警報（代碼 `32`）HD16 起接（Shawn 2026-10-20 19:04，和大雪特別警報同級）。澳門、韓國、越南、
  菲律賓這階段不加警報

`causes`（每格，主因在前）：從決定 `level` 的那一層（`basis` 是 `official` 看官方層、`model` 看模式層；
`confirmed` 看被它蓋掉的那一層——有官方層就是官方層）把等級 ≥ 中的種類列出：`wind`（陣風、側風或風的
警報）、`rain`、`snow`、`fog`。**等級高的在前，同級照 `wind`、`snow`、`fog`、`rain` 的固定順序**，第一個
就是主因；都低是 `[]`，`unknown` 是 `[]`。**依據是模式層時同級改成 `wind`、`snow`、`rain`、`fog`**（HD10：
模式層的霧只來自 GFS 能見度，模式的低能見度常是大雨造成的，主因寫雨）；官方層照原本的順序。`gap` 的定義不變
（官方與模式的 `level` 不同）。

#### 已知的保守假設與待校準的參數

都是初版，等有停飛紀錄回測後再調。HD2（2026-10-19）起的數字：

- **三類（雨、雪、霧）的門檻先照 2026-10-19 定案上線，累積一個月紀錄再調**（HD8，上面「新天氣種類」）
- **霧的模式層只有 GFS**（ECMWF 開放資料沒有能見度）。GFS 的能見度在大雨時也會掉得很低（2026-10-19 00Z
  那報花蓮 10/23 6 小時雨量 174 mm、能見度約 80 公尺），所以大雨格常常同時是 `fog`
- **模式層的霧只到中（HD10，2026-10-19 定案）**：GFS 能見度不準、又只有一個模式沒有對照（06:56Z 那報釜山
  10/20 12Z、18Z 只靠 GFS 能見度 308 公尺、幾乎沒雨就判高），所以 GFS 能見度 < 400 公尺也只是中；到高要官方層
  真的報霧或低雲幕。依據是模式層時同級的 `rain` 排在 `fog` 前面
- **金門 RCBS、馬祖 RCFG 沒有 TAF**（AviationWeather 沒有這兩站）。HD13 起霧的官方依據是氣象署局屬站觀測
  （第一格）與濃霧特報（中，前 12 小時的格）；之後的格還是只有 GFS 模式層（最高到中）。飛航服務總臺 AOAWS 有
  兩站的 METAR／SPECI，但是非正式介面，不接
- **氣象署觀測的能見度是「描述」字串**（公里，資料標準說明文件只給 `>30` 一個例子），`<1` 這種記 950 公尺
  （霧最多到中，要數字才看得出 < 400 公尺的高），區間取下限；局屬站不是機場跑道旁的觀測，和機場 METAR
  可能有落差。欄位名照文件寫，**合併後第一報要對一次** `history/raw/<日期>/<時間>-cwa-obs.json`
- AviationWeather 的能見度是法定英里，換回公尺是 × 1609 後換算到 50 公尺（公制 TAF 的 `1000`、`0400`、
  `1600`、`0800`、`1500`、`8000` 換得回原值）

- 陣風（模式與 TAF 同一套）：≥ 48 節高、≥ 37 節中；TAF 平均風 ≥ 35 節高
- **估算陣風係數**（HD14 固定 1.4，HD18 起每個機場 30 天的陣風÷平均風中位數，夾 1.2–2.0）：
  `10fg` 與 `GUST` 定義不同，HD18 先合併，**HD19 起只用 IFS**、GFS 樣本照存，**30 天後用
  `tools/gust_factor_report.py` 檢討**
- **模式層投票 ≥ 一半就成立**（HD14）：2 票 1 票、3 票 2 票、4 票 2 票、5 票 3 票、8 票 4 票（HD16）；系集
  只投高（判中時不算分母），所以系集單獨撐不起高（HD14 以前 `p49Kt` ≥ 30% 就是高）；霧的分母永遠是 1（只有 GFS）
- **WeatherNext 2 的授權不確定**（HD16）：Open-Meteo 免費版只限非商業；Open-Meteo 的 WeatherNext 頁沒列 Google
  額外限制，但 Google 對即時 WeatherNext 資料另有實驗條款，Open-Meteo 拿這份資料的授權來源查不到。HongThai、
  Duado 目前沒收費、沒廣告，先照 Open-Meteo 的 CC BY 4.0 用（下面「資料來源與授權」）
- **Open-Meteo 的起報時間**（HD16）：資料回應裡沒有，`runs.icon`／`runs.jma`／`runs.wn2-ens` 是抓完資料後問
  metadata API 的「最近一報」（`last_run_initialisation_time`）；剛好碰到換報的那幾分鐘可能和實際用到的資料差
  一報，問不到是 `null`（`sources.openmeteo.runError`）。ICON 06／18Z 那報只到 120 小時，最後幾格 Open-Meteo
  自動接前一報；JMA GSM 的逐時值是 Open-Meteo 從 3／6 小時內插的
- **WeatherNext 2 一天只有兩報**（Open-Meteo 只處理 00／12Z，00Z 那報約 11Z 才上 API），所以 01:05Z、08:25Z
  兩報用的是前一天 12Z、13:05Z／20:25Z 用的是當天 00Z
- 系集：陣風 ≥ 25 m/s（≈ 48.6 節，`p49Kt`）機率 ≥ 30% 投高；中級不用系集（沒有 37 節的機率）
- 側風：含陣風側風 ≥ 33 節高、≥ 27 節中；用陣風（不是平均風）算側風；沒有風向時側風＝風速本身
- 跑道方位用真北；所有跑道取最小側風（假設最好的那條都能用，沒算跑道關閉、長度、機型限制）；
  HD3 補上石垣之後 51 個機場都有跑道方位（沒有跑道方位的機場側風是 `null`，只看陣風）
- 中國機場的 TAF／METAR 風速是 `MPS`，AviationWeather 解碼成節時乘 2（實際 1.94），比實際高約 3%，偏保守
- 系集機率是 24 小時窗，6 小時格取包住它的窗的最小值；目前生效的警報只套到「現在 + 12 小時」以前開始的格
- **HD7 之前的第一格可能偏高**：2026-10-19 HD7 合併前，第一格的官方層把產出前就結束的 TAF 時段（例如
  關島 03:57Z 那報 02–03Z 的 TEMPO 陣風 46 節）也算進去。只影響第一格的 `official` 與 `level`；
  `history/*.json` 既有的檔案不重算、不改，回看戰績（`history/ai/`、`history/cancellations/`）時 `run` 在
  HD7 合併之前（第一份套用 HD7 的 `generatedAt` 是 2026-10-19T05:25:00Z）的，第一格要打折看

## 怎麼跑

需要 Python 3.12 以上。`eccodes` 的 pip 套件已附函式庫；Linux 也可以先裝 `libeccodes-dev`。

```sh
pip install ".[dev]"
python -m hongthai.build            # 產生 public/latest.json 與 data/（歷史紀錄）
pytest -q && ruff check . && ruff format --check .
```

估算陣風係數的驗證報表（HD18，30 天後用；純標準輸出、不改檔案）：

```sh
git worktree add ../hongthai-data data          # data 分支的 checkout
python tools/gust_factor_report.py ../hongthai-data            # 最近 30 天
python tools/gust_factor_report.py ../hongthai-data --days 7
```

印兩段：(1) 每份 `history/<時間>.json` 第一格（`generatedAt` 所在的格）IFS、GFS、AIFS、AIGFS 的 `gustKt`
對同一份 METAR（有陣風用陣風、沒有用平均風；只算觀測 3 小時內、METAR 平均風 ≥ 10 節的），每個模式的樣本數、
偏差中位數（模式 − METAR，節）、平均比值；(2) `history/gustfactor/` 每個機場 IFS、GFS 各自的中位數、合併
中位數與樣本數，最後一行全部機場合併（G 目前只用 IFS，HD19；GFS 與合併是對照）。

中央氣象署的資料需要授權碼，從環境變數 `CWA_API_KEY` 讀；沒設定時氣象署標
`sources.cwa.ok=false, error="no_api_key"`，其他照出。**不要把授權碼寫進程式或 repo。**

AI 對決（HD5，下面「AI 對決」）的金鑰也只從環境變數讀：

| 環境變數 | 內容 |
| --- | --- |
| `ANTHROPIC_API_KEY` | Claude Console「HongThai」Workspace 的金鑰 |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | GCP 服務帳號金鑰 **JSON 整份原文**（不是 base64；程式 `json.loads` 後直接用，不寫到磁碟） |
| `GOOGLE_CLOUD_PROJECT` | GCP 專案 ID |
| `GOOGLE_CLOUD_LOCATION` | `global`（Gemini 4 Argon 只開 global、us、eu） |

少任一個時那個模型記 `error: "no_api_key"`、不呼叫，另一個照跑；本機沒設就是兩個都 `no_api_key`，
其他照出。

整個流程約 4–5 分鐘（2026-10-18 實測 262 秒：ECMWF HRES 約 113 MB／90 秒、系集約 10 MB、GFS 兩個框
共 42 個 1–2 KB 的小檔約 110 秒、航班快照五個機場約 20 秒），下載大小與耗時印在 log，
也寫進 `data` 分支的 `history/timing/`（見下面「輸出」）。

H9（41 個機場）之後：
- ECMWF、GFS（AWS）都是全球檔抓點，下載量不變，只多解析幾個點。GRIB 取點改成所有點一次取
  （`grib.read_points` 向量化的 nearest）：GFS 一個步長的全球檔取 41 點約 0.2 秒（逐點取要 4.7 秒，
  21 個步長就是 100 秒），結果和逐點取一模一樣
- TAF、METAR 各一個請求帶 41 個 ICAO（網址不到 300 字元）
- GFS 的 NOMADS 備援改成一個框涵蓋全部機場（每個步長一個約 64 KB 的檔），見 `sources/gfs.py` 開頭
- 2026-10-18 17:26Z 本機實跑 41 個機場（沒設 `CWA_API_KEY`）：ecmwf 75.6 秒（AWS，92 MB）、gfs 24.7 秒
  （AWS，45 MB）、taf 0.6 秒、hko 4.3 秒、smg 16.9 秒、flights 36.4 秒，全部 158.7 秒；`latest.json` 515 KB

HD3（51 個機場）之後：
- TAF、METAR 各一個請求帶 51 個 ICAO（`ids` 254 字元）；NWS 一個請求（關島 `GUZ001`），約 12 KB
- GFS 的 NOMADS 備援框自動變大成北緯 6.37–43.77°、東經 102.99–145.80°（帛琉到新千歲、富國島到關島），
  2026-10-18 實測 12Z f120 一檔 113 KB（H9 約 64 KB），21 個步長約 2.4 MB，51 個機場都解析得到
- 2026-10-18 18:01Z 本機實跑 51 個機場（沒設 `CWA_API_KEY`）：ecmwf 89.1 秒（ECMWF 入口，93 MB）、gfs 26.0 秒
  （AWS，45 MB）、taf 3.3 秒、hko 4.1 秒、smg 25.9 秒、nws 0.6 秒、flights 70.9 秒，全部 219.9 秒；
  `latest.json` 642 KB（H9 是 515 KB）

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
| aifs（ECMWF AIFS Single，HD14；鏡像同 ecmwf） | 180 | 55（2026-10-20，66 MB，從 ECMWF 入口；AWS 回 503） |
| aigfs（NOAA AIGFS，HD14；只有 AWS） | 120 | 38（2026-10-20，51 MB） |
| openmeteo（ICON、JMA GSM、WeatherNext 2 系集，HD16；兩個請求、各 60 秒逾時、不重試） | 90 | 約 2–3（2026-10-20 雲端開發機，預報 632 KB／1.0 秒、系集 3 個變數時 1.6 MB／1.2 秒；只抓風速約 560 KB） |
| taf（含 METAR） | 45 | 幾秒 |
| hko、smg | 各 30 | 幾秒 |
| cwa | 45 | 幾秒 |
| nws（HD3，關島） | 30 | 不到 1 秒 |
| jma（HD9，日本與沖繩 11 個 office 各一個請求） | 45 | 8.6（2026-10-20，每個 0.5–1.0 秒、3–35 KB） |
| flights（抓＋統計＋寫檔） | 120 | 約 20 |
| ai（AI 對決，HD5；兩個模型平行，每報最多 20 個機場） | 240（HD12；原 180） | 約 111–117，HD11 後第一報 178（單次請求逾時 60 秒） |
| og（分享預覽圖 51 張，HD1；`publish()` 之後） | 60 | 約 3–6 |
| tracks（颱風路徑，HD21；只在事件期間、四個模式抓完之後） | 150 | 約 5–10（ECMWF 路徑產品約 1.3 MB＋解析三個模式的氣壓場；2026-10-20 雲端開發機） |

- 超過預算就記 `sources.<名稱> = {"ok": false, "error": "timeout", "seconds": <預算>}`，不等它、
  繼續下一個來源。被放棄的執行緒在背景跑到下一個請求或解析前就自己結束（不再解析 GRIB；
  GRIB 解析有全域鎖），程式結束時不等它
- 總和 1665 秒（27.75 分鐘；HD3 加 nws 30 秒、HD1 加 og 60 秒、HD5 加 ai 180 秒、HD12 ai 再加 60 秒、HD14 加
  aifs 180＋aigfs 120 秒、HD21 加 tracks 150 秒、HD9 加 jma 45 秒、HD16 加 openmeteo 90 秒），Actions「產生
  latest.json」那一步上限 30 分鐘、整個 job 40 分鐘（HD16 前 28／38、HD21 前 25／35、HD14 前是 20／30、
  HD12 前 18／28、HD5 前 15／25）。HD21 事件期間 gfs、aigfs、aifs
  多抓的海平面氣壓（每個步長約 1.0／1.0／0.5 MB，三個共約 52 MB）算在它們自己的預算裡
- ECMWF：重試最多 3 次、每次間隔 10 秒、不照伺服器的 Retry-After（`ecmwf-opendata` 預設是每 120 秒
  重試 500 次，2026-10-18 build #4 就是從頭 429 到被砍）。找最新一報先問 ECMWF 入口（失敗才問 AWS），
  下載先試 AWS 鏡像，那一報還沒同步到或失敗再回 ECMWF 入口，再失敗試 Google；實際從哪裡下載記在
  `sources.ecmwf.mirror`。從 AWS 下載不重試：S3 不收多段 range、一報要一百多個請求，2026-10-18
  實測約三成回 `503 Slow Down`，重試會把預算耗光，所以第一個 503 就換 ECMWF 入口
- `ecmwf`、`gfs`、`aifs`、`aigfs`（HD14）失敗（逾時、429 用盡、403、格式錯……）時沿用「最近一份有該模式資料」
  的結果同一機場、同一格的 `model.ec`／`model.gfs`（AIFS、AIGFS 是 `model.models[]` 同 `id` 那筆的數字），
  等級與投票照常算。哪一份（H10 起往前找）：`--archive` 的
  `history/<時間>.json` 由新到舊，第一份 `sources.<名稱>.ok` 是 `true`（自己也在沿用的不算）而且
  `runs.ecmwf`／`runs.gfs`／`runs.aifs`／`runs.aigfs` 離現在 24 小時內的；archive 裡找不到才退回上一份 `latest.json`（先找
  `--archive`，沒有就從 Pages 抓）。`sources.<名稱>.ok` 仍是 `false`，另加 `reusedFrom`（那一份的
  `generatedAt`），`runs` 是那一份的（舊預報的真實時次）。模式時次離現在超過 24 小時就不沿用
  （系集與 HRES 各自算），照缺資料處理。TAF、METAR、警報不沿用。HD18：`models[]` 的 `windKt` 一起抄，
  AIFS／AIGFS 的估算陣風用抄來的 `windKt` × 這一報的係數重算。**Open-Meteo（HD16）不沿用**（上面「多模式
  投票」）；別的模式沿用、重組 `models[]` 時，ICON、JMA GSM、WeatherNext 2 那三筆用這一報自己的數字

### 檔案

- `airports.json`（H9 起是 `{"regions": [...], "airports": [...]}`）：
  - `regions[]`：`id`、`name`（四語），照顯示順序
  - `airports[]`：照 `regions` 的順序、地區內照顯示順序（讀的時候會檢查，順序不對、ICAO 重複、`region` 不在
    `regions` 裡、`tz` 不是 IANA 時區、跑道方位不在 0–360 都會報錯）。每個機場：ICAO、IATA、`tz`、`region`、
    四語名稱（短名、不加「機場」）、座標（機場參考點；現有五個沿用，H9 的 36 個與 HD3 的 10 個取
    OurAirports）、跑道、看哪些官方警報、氣象署警戒區關鍵字、NWS zone、JMA 區域、氣象署局屬站站號（`cwaStation`，
    HD13：金門、馬祖沒有 METAR 時用這站的觀測）、門檻
  - `runways[].headings`：跑道兩個方向的**真北**方位（度）。提示詞寫的是磁方位，但 METAR／TAF 與模式的風向
    都是真北，用磁方位會差 3–5°，所以算側風用真北；磁方位（只有 AIP 的五個）記在 `runways[].magnetic` 備查
    （下面「跑道方位」）。`runways: []` 的機場側風是 `null`
  - `runwaySource`：跑道方位從哪裡來，`"aip"`（現有五個）、`"ourairports"`（其他 45 個）或 `"computed"`
    （石垣，用跑道兩端跑道頭座標算，HD3）；只在這裡，不進 `latest.json`
  - `warningSources`：`cwa`（台灣十個機場）、`hko`（香港）、`smg`（澳門）、`nws`（關島，HD3）、`jma`（日本 8 個
    與沖繩 3 個，HD9）；其他機場是 `[]`
  - `nwsZone`：看 NWS 警報的機場要有（HD3），NWS 的 zone 代碼，關島 `GUZ001`（`/points/13.485,144.7973`
    的 `forecastZone`）。`warningSources` 有 `nws` 但沒有 `nwsZone`（或格式不是 `GUZ001` 這種）讀的時候會報錯
  - `jmaArea`：看 JMA 警報的機場要有（HD9），`{"office", "class20", "name", "enName"}`：機場所在市町村在 JMA
    `area.json` 的代碼（`class20s`，7 碼）、它往上的都道府縣氣象台（`offices`，6 碼，警報 JSON 一個 office
    一個檔），以及那個市町村的日文名與 `enName`（警報文字用，每報不抓 `area.json`）。2026-10-20 查的：
    新千歲 千歳市 `016000`／`0122400`、仙台 名取市 `040000`／`0420700`、成田 成田市 `120000`／`1221100`、
    羽田 大田区 `130000`／`1311100`、中部 常滑市 `230000`／`2321600`、關西 泉佐野市 `270000`／`2721300`
    （人工島跨泉佐野市、田尻町、泉南市，航廈地址在泉佐野市；三個都在同一個 class15「泉州」）、福岡 福岡市
    `400000`／`4013000`、鹿兒島 霧島市 `460100`／`4621800`、那霸 那覇市 `471000`／`4720100`、宮古
    宮古島市 `473000`／`4721400`、石垣 石垣市 `474000`／`4720700`（11 個機場剛好 11 個 office）。
    `warningSources` 有 `jma` 但沒有 `jmaArea`、代碼位數不對或沒有 `name` 讀的時候會報錯
  - `cwaAreas`：氣象署警戒區關鍵字，每個台灣機場一組：桃園、松山「北部」「桃園」「臺北」「台北」「新北」；
    高雄「南部」「高雄」；台中「中部」「臺中」「台中」；台南「南部」「臺南」「台南」；花蓮「東部」「花蓮」；
    台東「東部」「臺東」「台東」；澎湖「澎湖」；金門「金門」；馬祖「馬祖」「連江」。對過 `W-C0034-001` 的
    用語：`areaDesc` 是「臺中市」「臺南市」「花蓮縣」「臺東縣」「澎湖縣」「金門縣」「連江縣」，警戒區文字寫
    「馬祖」，都比得到
  - `thresholds`：每個機場可覆寫的門檻，**省略就用預設**（目前 51 個都省略）。HD2 起全部用節；預設值在
    `src/hongthai/config.py` 的 `Thresholds`：
    `modelMediumGustKt`（37）、`modelHighGustKt`（48）、`tafMediumGustKt`（37）、`tafHighGustKt`（48）、
    `tafHighWindKt`（35）、`crosswindMediumKt`（27）、`crosswindHighKt`（33）、`ecP49High`（0.3，系集陣風
    ≥ 25 m/s 的機率）。HD2 以前的 m/s 鍵（`modelHighGustMs` 等）不再接受，讀到會報錯
- `confirmed.json`：人工填的已確認停飛時段，例如
  `[{"airport": "VHHH", "from": "2026-10-20T00:00:00Z", "to": "2026-10-20T12:00:00Z", "note": {"zh-TW": "機管局公告…", "en": "…"}}]`
- `events.json`：要完整保存、之後驗證的天氣事件（HD20，下面「事件保存」）
- `src/hongthai/sources/`：各資料來源（每個 `fetch()` 回 dataclass，失敗丟自己的例外）
- `src/hongthai/assess.py`：判讀（純函式）
- `src/hongthai/gustfactor.py`：估算陣風的係數（HD18，上面「估算陣風的係數」）；30 天後的驗證報表
  `tools/gust_factor_report.py`
- `src/hongthai/build.py`：組 JSON、寫檔、失敗處理
- `src/hongthai/events.py`：事件保存（HD20）：每報快照、一次性搬運、每小時 METAR 與颱風現報
  （`.github/workflows/events.yml`）；推 `data` 分支用 `tools/push_data.sh`（`build.yml` 也用）
- `src/hongthai/tracks.py`：颱風路徑抽取（HD21）：ECMWF 路徑產品（BUFR）與從海平面氣壓找中心
  （下面「事件保存」）
- `src/hongthai/og.py`：分享預覽圖（HD1，下面「分享預覽圖」）；字型子集在 `assets/fonts/`，
  重做腳本 `tools/make_font_subset.py`
- `src/hongthai/ai/`：AI 對決（HD5，下面「AI 對決」）；模型字串、免責四語、上限都在 `ai/config.py`

### 輸出

- `latest.json` 與 `history/<YYYYMMDDTHHMM>Z.json` 的 JSON 不縮排（HD14 起，檔案約 1.9 MB；HD18 後約 2.2 MB、
  HD16 後約 3.0 MB）；原始快照 `history/raw/` 照舊縮排（Open-Meteo 那份例外，不縮排）
- GitHub Pages（`public/`）：`latest.json`、`history/<YYYYMMDDTHHMM>Z.json`（歷次結果，**只放最近 7 天**：
  H9 起一份約 515 KB、HD3 起約 642 KB（2026-10-18 實測），`publish()` 只複製檔名時間（＝`generatedAt`）在 7 天內的，Pages 上更舊的刪掉；
  `data` 分支照舊全部保留）；每個機場一張分享預覽圖 `og/<iata 小寫>.png`（HD1，下面「分享預覽圖」，
  每報重畫、不進 `data` 分支）
- `data` 分支（Actions 自動推）：同樣的結果（全部，不限 7 天），加上原始快照
  `history/raw/<日期>/<HHMM>Z-{taf,metar,hko,cwa,smg,nws,jma,openmeteo}.json`（SMG 是 `{"c": XML, "e": XML}`；NWS 是
  `/alerts/active` 的原始回應，HD3 起；JMA 是 `{office 代碼: 警報 JSON}`，HD9 起；Open-Meteo 是
  `{"forecast": 預報回應, "ensemble": 系集回應}`，HD16 起，**不縮排**、一份約 1.2 MB（zlib 後約 190 KB）；氣象署天氣特報 `W-C0033-001` 是另一個檔 `<HHMM>Z-cwa-hazards.json`，
  HD8 起，`-cwa.json` 照舊是颱風警報；金門、馬祖的局屬站觀測 `O-A0003-001` 是 `<HHMM>Z-cwa-obs.json`，HD13 起）與航班的
  取消／延誤統計 `history/cancellations/<日期>.json`（之後回測「風險等級 vs 實際停飛」用；
  原始航班資料不存）、狀態對照表沒列的字串 `history/cancellations/unknown-statuses.json`、
  每次 build 的耗時紀錄 `history/timing/<YYYY-MM>.jsonl`，以及 AI 對決的戰績
  `history/ai/<YYYY-MM-DD>.json` 與每日呼叫次數 `history/ai/calls-<YYYY-MM-DD>.json`（HD5；每日上限開發期間不限，
  次數照常記，之後評估看實際用量；下面
  「AI 對決」），估算陣風係數的樣本 `history/gustfactor/<YYYY-MM>.jsonl` 與這一報的係數
  `history/gustfactor/latest.json`（HD18，格式在下面），事件保存 `history/events/<id>/`（HD20，每報快照、
  每小時 METAR、颱風現報；HD21 起多各模式每一報的颱風路徑 `history/events/<id>/tracks/`；下面「事件保存」）。這些都不進 GitHub Pages、不進 `latest.json`

`history/gustfactor/<YYYY-MM>.jsonl`（HD18）：一行一報一機場，IFS、GFS 分開記，只存合格（平均風 ≥ 10 節）
的比例、兩位小數、照格的順序，沒有的寫 `[]`（模式失敗、沿用舊資料的那一報也是 `[]`）；月份是 `run`
（＝那次的 `generatedAt`）的 UTC 月份：

```json
{"run": "2026-10-20T08:25:00Z", "icao": "RCTP", "ifs": [1.45, 1.52], "gfs": [1.31]}
```

`history/gustfactor/latest.json`：這一報算出的係數。`all` 是 30 天窗全部機場合併、`run` 是只算這一報
（`g` 是夾過的中位數，沒樣本時 `null`）；`airports.<icao>.n` 是那個機場 30 天的樣本數、`g`／`basis` 是實際
用的係數與依據：

```json
{"generatedAt": "2026-10-20T08:25:00Z",
 "window": {"from": "2026-09-20T08:25:00Z", "to": "2026-10-20T08:25:00Z"},
 "all": {"g": 1.47, "n": 1234, "nIfs": 640, "nGfs": 594},
 "run": {"g": 1.45, "n": 412, "nIfs": 210, "nGfs": 202},
 "airports": {"RCTP": {"g": 1.52, "n": 88, "nIfs": 44, "nGfs": 44, "basis": "airport30d"}}}
```

`history/timing/<YYYY-MM>.jsonl`：一行一筆 JSON，每個來源一跑完就 append（不等全部結束），所以
「產生 latest.json」被 Actions 砍掉時已經寫的行也會推上去。`run` 和那次的 `generatedAt` 相同：

```json
{"run": "2026-10-18T09:28:00Z", "source": "start", "ok": true, "seconds": 0, "commit": "a59b42d"}
{"run": "2026-10-18T09:28:00Z", "source": "ecmwf", "ok": false, "error": "timeout", "seconds": 240.0, "bytes": 0, "mirror": "aws"}
{"run": "2026-10-18T09:28:00Z", "source": "gfs", "ok": true, "error": null, "seconds": 108.3, "bytes": 61234, "mirror": "nomads"}
{"run": "2026-10-18T09:28:00Z", "source": "ai", "ok": true, "error": null, "seconds": 41.7, "bytes": 0, "calls": {"claude": 12, "gemini": 12}}
{"run": "2026-10-18T09:28:00Z", "source": "done", "ok": true, "seconds": 371.2}
```

- `source`：`start`、`ecmwf`、`gfs`、`taf`、`hko`、`cwa`、`smg`、`nws`（HD3 起）、`jma`（HD9 起）、`flights`、`ai`（HD5 起，
  AI 對決；`bytes` 是 0、`calls` 是這一報每個模型呼叫了幾次）、`og`（HD1 起，分享預覽圖；改發布上一份時
  也有）、`done`（照執行順序）
- `error`：和 `sources.<名稱>.error` 同一套代碼，成功是 `null`（`og` 有幾張畫不出來時是
  `"<IATA>:<例外類別>"`，多個用 `,` 接）；`bytes`：下載量（逾時的是到那時為止，
  ecmwf 只算下載完的檔；`og` 是畫出來的圖的總大小）；
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
  "runs": { "ecmwf": "2026-10-18T00:00:00Z", "ecmwfEns": "2026-10-18T00:00:00Z", "gfs": "2026-10-18T00:00:00Z", "aifs": "2026-10-18T00:00:00Z", "aigfs": "2026-10-17T18:00:00Z" },
  "sources": { "ecmwf": { "ok": true }, "gfs": { "ok": true }, "taf": { "ok": true }, "hko": { "ok": true }, "cwa": { "ok": false, "error": "no_api_key" }, "ai": { "ok": true, "seconds": 41.7, "calls": { "claude": 12, "gemini": 12 }, "errors": { "gemini": "bad_format" } } },
  "ai": {
    "disclaimer": { "zh-TW": "AI 評論僅供參考，以航空公司與機場公告為準", "zh-HK": "AI 評論僅供參考，以航空公司及機場公告為準", "zh-CN": "AI 评论仅供参考，以航空公司与机场公告为准", "en": "AI commentary is for reference only; follow airline and airport announcements." },
    "models": { "claude": "claude-opus-5-5", "gemini": "gemini-4-argon" }
  },
  "regions": [
    { "id": "taiwan", "name": { "zh-TW": "台灣", "zh-HK": "台灣", "zh-CN": "台湾", "en": "Taiwan" } },
    { "id": "east-china", "name": { "zh-TW": "華東", "zh-HK": "華東", "zh-CN": "华东", "en": "East China" } }
  ],
  "airports": [
    {
      "icao": "RCTP", "iata": "TPE", "tz": "Asia/Taipei",
      "name": { "zh-TW": "桃園", "zh-HK": "桃園", "zh-CN": "桃园", "en": "Taoyuan" },
      "region": "taiwan",
      "official": { "warnings": true },
      "warnings": [ { "source": "cwa", "kind": "typhoon_land", "level": "high", "text": { "zh-TW": "…", "zh-HK": "…", "zh-CN": "…", "en": "…" }, "issuedAt": "…" } ],
      "metar": { "observedAt": "…", "windDirDeg": 40, "windKt": 28, "gustKt": 41, "raw": "…" },
      "taf": { "issuedAt": "…", "validFrom": "…", "validTo": "…", "raw": "…" },
      "slots": [
        {
          "from": "2026-10-18T06:00:00Z", "to": "2026-10-18T12:00:00Z",
          "level": "medium", "basis": "official",
          "official": { "windKt": 25, "gustKt": 38, "kind": "tempo", "level": "medium", "crosswindKt": 21.4, "warnings": [] },
          "model": { "ec": { "p10": 0.92, "p15": 0.55, "p25": 0.08, "p29Kt": 0.55, "p37Kt": null, "p49Kt": 0.08, "hresGustMs": 19.4, "hresGustKt": 37.7, "crosswindKt": 26.1 }, "gfs": { "gustMs": 19.6, "gustKt": 38.1, "crosswindKt": 12.3 }, "level": "medium", "agreement": "agree" },
          "gap": false
        }
      ],
      "confirmed": [ { "from": "…", "to": "…", "note": { "zh-TW": "…", "en": "…" } } ],
      "ai": {
        "evaluatedAt": "2026-10-18T08:10:00Z",
        "claude": { "status": "ok", "level": "medium", "comment": { "zh-TW": "…", "zh-HK": "…", "zh-CN": "…", "en": "…" }, "model": "claude-opus-5-5" },
        "gemini": { "status": "error", "level": null, "comment": null, "model": "gemini-4-argon", "error": "bad_format" }
      }
    }
  ]
}
```

第二階段（2026-10-18）加的欄位（規格 16 節已補；網頁之後顯示在依據區，現在忽略也不會壞）：

- `slots[].official.crosswindKt`、`slots[].model.ec.crosswindKt`、`slots[].model.gfs.crosswindKt`：
  含陣風、所有跑道裡最小的側風分量（節，一位小數）；沒有風向時＝風速本身；沒資料或機場沒設跑道是 `null`
- `airports[]` 多三個機場（RCSS、RCKH、VMMC）；`warnings[].source` 多 `"smg"`（澳門信號，`kind: "tc_signal"`）
- `sources.smg`

第三階段（H9，2026-10-19）加的欄位（契約，要和 Duado spec 第 16 節一致；既有欄位不改）：

- 頂層 `regions`：陣列，照顯示順序，每個 `{ "id", "name": { "zh-TW", "zh-HK", "zh-CN", "en" } }`。六個：
  `taiwan` 台灣、`east-china` 華東、`south-china-hkmo` 華南・港澳、`okinawa` 沖繩、`japan` 日本、
  `korea` 韓國（HD3 加三個，見下面）
- `airports[].region`：地區 id；`airports[]` 照 `regions` 的順序排，同一地區的機場連在一起
- `airports[].official`：物件，目前只有 `{ "warnings": true|false }`——這個機場有沒有接官方警報來源
  （`airports.json` 的 `warningSources` 非空）。`false` 的機場網頁顯示「官方警報：尚未提供」，`warnings`
  一定是 `[]`。和每格的 `slots[].official`（官方層的判讀）是不同層
- `airports[]` 從 5 個變 41 個；沒有 TAF／METAR 的機場 `taf`／`metar` 是 `null`（見上面「機場」）

HD3（2026-10-19）加的（只加值、不加欄位，既有欄位不改名、不改型別；要進 Duado spec 第 16 節）：

- `regions` 加三個（接在 `korea` 之後，共九個）：`vietnam` 越南、`philippines` 菲律賓（zh-CN「菲律宾」）、
  `guam-palau` 關島・帛琉（zh-CN「关岛・帕劳」，en「Guam & Palau」）
- `airports[]` 從 41 個變 51 個（見上面「機場」）；關島 `official.warnings` 是 `true`，越南、菲律賓、帛琉是 `false`
- `warnings[].source` 多 `"nws"`（美國國家氣象局關島分處），`kind` 是 `typhoon_warning`／`typhoon_watch`／
  `ts_warning`／`ts_watch`，`code` 是 NWS 的 `event`（例如 `Typhoon Warning`），`detail` 是 NWS 的
  `NWSheadline`（例如 `TYPHOON WARNING REMAINS IN EFFECT`），`text.en` 是 NWS 的 `headline`、中文三語是固定
  句型（「颱風警報生效中（美國國家氣象局）」；zh-HK 用「警告」「戒備」），`issuedAt` 是那一則的 `sent`
  （NWS 每次更新都重發，所以是最近一次更新的時間）；`slots[].official.warnings` 裡是同一個 `kind`
- `sources.nws`

HD5（2026-10-19，AI 對決「三顆燈」，第四階段）加的欄位（照 Duado spec 第 16 節；既有欄位不改名、不改型別）：

- 頂層 `ai`：`{ "disclaimer": { 四語 }, "models": { "claude": "claude-opus-5-5", "gemini": "gemini-4-argon" } }`。
  免責四語是固定字串（`ai/config.py` 的 `DISCLAIMER`）；網頁燈的標題用 `models` 顯示模型名，鍵名
  `claude`／`gemini` 換模型版本也不改
- `airports[].ai`：`{ "evaluatedAt", "claude": <燈>, "gemini": <燈> }`，每個機場都有
  - `evaluatedAt`：這一報的時間（＝`generatedAt`）；兩顆燈都是 `error` 時 `null`（`skipped` 也填時間）
  - `<燈>`：`{ "status", "level", "comment", "model" }`，`error` 時多 `"error"`
    - `status: "ok"`：`level` 是 `low`／`medium`／`high`，`comment` 是四語短評（以 zh-TW 為準、其他三語是
      忠實翻譯，中文每語最多 300 字、en 最多 800 字；HD5 是四語都 400，HD6 放寬）
    - `status: "skipped"`（沒被選、不呼叫）：`level: "low"`，`comment` 固定四語「沒看到明顯風險」
      （zh-HK「未見明顯風險」、zh-CN「未见明显风险」、en「No notable risk seen」）
    - `status: "error"`：`level: null`、`comment: null`，`error` 是代碼：`no_api_key`（沒設金鑰）、`timeout`
      （單次請求 60 秒或整個 AI 步驟 240 秒到了）、`bad_format`（回應不是規定的 JSON、等級不對、四語有缺、
      超過字數上限、被 `max_tokens` 截斷）、`http_<碼>`（API 回錯誤，例如 `http_429`；`http_504` 是 Vertex
      閘道逾時，`http_503`／`http_504` 重試一次仍失敗才記，其他碼不重試，HD17）、`network`、
      `daily_cap`（那個模型今天已經呼叫到每日上限；目前 `DAILY_CAP=0` 不限，不會出現）；**規格以外多三個**：`run_cap`（符合條件但排在這一報前 20 個
      之後，沒評；不寫「沒看到明顯風險」，因為可能是中級）、`refusal`（模型拒答或被安全過濾擋下）、
      `bad_wording`（HD6：格式對但短評用字違規，見「AI 對決」的「用字規則與檢查」）
- `sources.ai`：`{ "ok": <兩個模型至少一個有成功>, "seconds", "calls": { "claude": n, "gemini": n },
  "errors": { "<模型>": "<代碼>" } }`；`calls` 是這一報的呼叫次數，`errors` 只列有失敗的模型（那個模型
  最多的代碼，`run_cap` 不算），沒有就不出現。這一報沒有要評的機場、金鑰也都在時 `ok: true`。
  `ok: false` 時照其他來源的慣例多一個 `error`（`"claude:no_api_key,gemini:no_api_key"` 這種）

HD8（2026-10-19，第五階段新天氣種類；欄位名定案，Shawn 轉給 Duado 寫進 spec 第 16 節；`schema` 維持 `1`，
既有欄位不改名、不改型別、不拿掉）：

- `slots[].causes`：字串陣列，`wind`／`rain`／`snow`／`fog` 裡等級 ≥ 中的，主因在前（規則見上面「新天氣
  種類」）；都低或 `unknown` 是 `[]`
- `slots[].official.wx`：有 TAF 的格是物件，只有警報的格是 `null`：
  `{"phenomena": ["+TSRA", "BR"], "visibilityM": 800, "ceilingFt": 200, "rain": "medium", "snow": "low", "fog": "medium"}`
  - `phenomena`：該格有效時段（含第一格的 METAR）所有天氣現象，去重、照出現順序
  - `visibilityM`：最小能見度（公尺，`9999`＝10 公里以上）；`ceilingFt`：最低雲幕（BKN／OVC 或垂直能見度，
    呎）；沒報是 `null`
  - `rain`／`snow`／`fog`：官方層三類的等級，永遠是字串（`low`／`medium`／`high`）
  - `official.level` 是風與三類取最高；`official.kind` 照舊是風的時段種類
- `slots[].model.ec` 多：`rain6hMm`（6 小時雨量 mm，一位小數或 `null`）、`ptype`（降水型態：`none`／`rain`／
  `freezing_rain`／`snow`／`wet_snow`／`rain_snow`／`ice_pellets`／`freezing_drizzle`，其他代碼 `other`；
  沒資料 `null`）、`p24hRain25`／`p24hRain50`（系集 24 小時雨量 ≥ 25／50 mm 的機率，0–1 或 `null`，同 `p10`）、
  `temp2mC`（2 米溫度 °C，一位小數或 `null`，只是參考、不進規則）、`rain`／`snow`（EC 自己的等級字串或 `null`）
- `slots[].model.gfs` 多：`rain6hMm`、`ptype`（同上的值域）、`visibilityM`（整數公尺或 `null`）、
  `rain`／`snow`／`fog`（GFS 自己的等級字串或 `null`）
- `model.level` 是風與三類取最高；`model.agreement` 還是只看陣風
- `airports[].warnings[]`／`slots[].official.warnings`：`kind` 多 `rainstorm_black`、`rainstorm_red`、
  `thunderstorm`（`source: "hko"`，`code` 是 `WRAINB`／`WRAINR`／`WTS`；文字是天文台三語，zh-TW＝zh-HK）、
  `cwa_heavy_rain`（`source: "cwa"`，`detail` 是特報字樣「大豪雨」／「超大豪雨」；四語是固定句型
  「中央氣象署大豪雨特報，金門在特報範圍」）
- `airports[].taf`、`airports[].metar` 各多 `visibilityM`（整數公尺或 `null`）、`wx`（字串陣列）、`ceilingFt`
  （整數呎或 `null`）；METAR 是觀測值，TAF 是主時段的（涵蓋現在的那個主時段，沒有就第一個還沒結束的）
- `sources.cwa.heavyRainOk: false`＋`heavyRainError`：天氣特報那個請求失敗時才有（颱風警報照常，`ok`
  不受影響）
- 大小：2026-10-19 用 `data` 分支 05:25Z 的快照＋06:20Z 抓的模式實測，`latest.json`（不含 AI 欄位）從
  640 KB 變 1,019 KB（多約 380 KB，`indent=1` 每個新鍵一行）；gzip 後 45 KB（Pages 回應是壓縮過的）

HD13（2026-10-19，金門、馬祖的霧；`schema` 維持 `1`，既有欄位不改名、不改型別）：

- `airports[].metar` 多 `source: "cwa"`：金門、馬祖 AviationWeather 沒有 METAR，改用氣象署局屬站觀測
  （`O-A0003-001`）填同樣的欄位（`windKt`／`gustKt` 由 m/s 換成節，`visibilityM` 由公里描述換算，`wx` 是
  對到的 METAR 代碼，`ceilingFt` 永遠 `null`，`raw` 是 `CWA 467110 2026-10-19T12:00Z 能見度 0.5 km 陰有霧
  風 090° 3 m/s`）。AviationWeather 的 METAR **沒有** `source` 這個鍵
- `slots[].official.kind` 多一個值 `metar`（值域：`main`／`tempo`／`prob30`／`prob40`／`warning`／`metar`）：
  沒有 TAF 的機場第一格由 METAR 撐起（上面「怎麼算」）；這種格的 `wx` 是物件（只有 METAR 一筆）
- `airports[].warnings[]`／`slots[].official.warnings`：`kind` 多 `cwa_dense_fog`（`source: "cwa"`、`level:
  "medium"`、`detail: "濃霧"`；四語「中央氣象署濃霧特報，金門在特報範圍」／zh-CN「中央气象署浓雾特报，金门在
  特报范围」／en「CWA dense fog advisory; Kinmen is in the advisory area」），算 `fog`
- `sources.cwa.obsOk: false`＋`obsError`：局屬站觀測那個請求失敗時才有（颱風警報、特報照常）
- 大小：兩個機場的 `metar` 從 `null` 變物件、第一格多一個官方層，`latest.json` 多約 1–2 KB

HD9（2026-10-20，JMA 大雪警報；只加值，`schema` 維持 `1`，既有欄位不改名、不改型別）：

- 日本 8 個（新千歲、仙台、成田、羽田、中部、關西、福岡、鹿兒島）與沖繩 3 個（那霸、宮古、石垣）的
  `official.warnings` 從 `false` 變 `true`（沖繩實務上不會有大雪警報，接了網頁才不用寫「尚未提供」）
- `airports[].warnings[]`／`slots[].official.warnings`：`source` 多 `"jma"`，`kind` 多 `jma_heavy_snow`（中）、
  `jma_heavy_snow_emergency`（高）、`jma_snowstorm`（低，只列出），都算 `snow`；`code` 是 JMA 的警報種類代碼
  （`06`、`36`、`02`），沒有 `detail`；四語「日本氣象廳大雪警報（千歳市）」／zh-CN「日本气象厅大雪警报（千歳市）」
  ／en「JMA heavy snow warning (Chitose)」（特別警報「大雪特別警報」／`heavy snow emergency warning`，
  暴風雪「暴風雪警報」／`snowstorm warning`；市町村名用 JMA 的日文漢字原樣、en 用 `enName` 去掉 City／Town），
  `issuedAt` 是那一報的 `reportDatetime`
- `sources.jma`（`ok`、`seconds`；失敗時 `error`，其他來源不受影響）

HD14（2026-10-20，多模式投票；欄位定案，Shawn 轉給 Duado；`schema` 維持 `1`。**`model.ec`、`model.gfs`、
`model.agreement` 不改名、不改型別、不拿掉，值也照舊算**；`model.level` 改由投票決定）：

- 頂層 `models`：`[{"id": "ifs", "name": {四語}}, …]`，照 `config.MODELS` 的順序（`ifs`、`gfs`、`ifs-ens`、
  `aifs`、`aigfs`；HD16 加 `icon`、`jma`、`wn2-ens`，之後 `wn3`）。四語名：歐洲中期預報中心 IFS／ECMWF IFS、美國 GFS／NOAA GFS、
  歐洲系集／ECMWF ensemble、歐洲 AI 模式 AIFS／ECMWF AIFS、美國 AI 模式 AIGFS／NOAA AIGFS（zh-HK 同 zh-TW、
  zh-CN 簡體）。每格不放名稱，用 `id` 對
- `slots[].model.models[]`：照頂層 `models` 的順序、每個模式一筆，**該模式這一報沒資料時也出現**（數字、
  `levels`、`level` 全是 `null`）：
  `{"id": "aifs", "run": "2026-10-19T12:00:00Z", "gustKt": 31.2, "gustEstimated": true, "crosswindKt": 18.4,
  "rain6hMm": 3.1, "ptype": "rain", "visibilityM": null, "levels": {"wind": "low", "rain": "low", "snow": "low",
  "fog": null}, "level": "low"}`
  - `run`：那個模式的時次（ISO 或 `null`；`ifs` 同 `runs.ecmwf`、`ifs-ens` 同 `runs.ecmwfEns`）
  - `gustKt`：陣風（節，一位小數）；`gustEstimated`：`true`＝用 10 米平均風 × 係數估算（AIFS、AIGFS；
    HD18 起係數是每個機場自己的，見下面 HD18），
    `false`＝模式自己的陣風（IFS、GFS），`gustKt` 是 `null` 時也是 `null`。網頁要寫「估算陣風」
  - `crosswindKt`（節，含陣風或估算陣風）、`rain6hMm`（mm）、`ptype`（值域同 `model.ec.ptype`；AIGFS 永遠
    `null`）、`visibilityM`（只有 GFS）
  - `levels`：這個模式四類各自的等級（`low`／`medium`／`high`／`null`＝這個模式這一類沒資料、不投）；
    `level`：四類取最高
  - `ifs-ens`（系集）那筆數字全是 `null`，只有 `levels.wind`（`p49Kt` ≥ 30% `high`、否則 `low`）
- `slots[].model.vote`：`{"total": 5, "high": 2, "medium": 3, "low": 1, "level": "high", "thin": false}`。
  票數都是「風」那一類的：`total` 分母（有風的資料的模式數，含系集）、`high` 投高的數、`medium` 等級 ≥ 中
  的數（**不含系集**，同判中的規則）、`low` 投低的數；`level` 是四類投票結果取最高（全無資料 `null`，
  ＝`model.level`）；`thin`：風的分母 < 2
- 頂層 `runs.aifs`、`runs.aigfs`（ISO 或 `null`）；`sources.aifs`、`sources.aigfs`（`ok`、`seconds`、`bytes`、
  `mirror`、失敗時 `error`、沿用時 `reusedFrom`，同 `ecmwf`／`gfs`）。`aifs.mirror` 是 `"aws"`／`"ecmwf"`／
  `"google"`，`aigfs.mirror` 永遠是 `"aws"`
- 大小：用 `data` 分支 `history/20261019T2349Z.json` 加 2026-10-20 01:1xZ 抓的 AIFS（18Z）、AIGFS（12Z）重算，
  `latest.json` 從 1,091 KB 變 **3,276 KB**（多約 2.2 MB，`indent=1` 每個鍵一行、每格 5 筆 × 約 17 行）；
  gzip 後 68 KB → 154 KB（Pages 回應是壓縮過的）。提示詞估的是多 400–500 KB，實際多很多

HD18（2026-10-20，估算陣風的係數改成每個機場自己算；`schema` 維持 `1`，**既有欄位不改名、不改型別**）——
`slots[].model.models[]` 每筆多三個鍵：

- `windKt`：10 米平均風（節，一位小數；沒資料 `null`）。`ifs`＝格結束步長的 `10u`／`10v`（和風向同一個
  時間點）、`gfs`＝格內陣風最大那一點的、`aifs`／`aigfs`＝估算陣風用的那個（格頭尾兩點大的）、`ifs-ens` 永遠
  `null`
- `gustFactor`：估算陣風用的係數（兩位小數，1.2–2.0；保底 1.4）；`gustFactorBasis`：`"airport30d"`（這個機場
  30 天）、`"all30d"`（全部機場 30 天）、`"run"`（這一報全體）、`"default"`（固定 1.4）。只有估算陣風、而且
  `gustKt` 有值的那幾筆（`aifs`、`aigfs`）有，其他是 `null`。`gustKt`＝`windKt` × `gustFactor`（一位小數）
- 大小：2026-10-20 雲端開發機實際跑一報（模式全是 18Z，51 個機場）：`latest.json`（不縮排）2,148 KB，拿掉這
  三個鍵是 1,868 KB，**多約 280 KB**（gzip 後 104 → 118 KB）。提示詞估 100–150 KB；每格 5 筆 × 三個鍵約
  55 bytes × 20 格 × 51 個機場就是 280 KB

HD16（2026-10-20，Open-Meteo 三票、旁觀開關、暴風雪特別警報；`schema` 維持 `1`，**只加值，既有欄位不改名、
不改型別**；要經 Shawn 轉給 Duado 總指揮）：

- 頂層 `models[]` 多三筆（照順序接在 `aigfs` 後面）：`icon` 德國 ICON／德國 ICON／德国 ICON／DWD ICON、`jma`
  日本 GSM／JMA GSM、`wn2-ens` Google WeatherNext 2 系集／Google WeatherNext 2 ensemble；**每筆多 `voting`**
  （布林；`false` 是旁觀模式，網頁標「旁觀，不投票」。目前八筆都是 `true`）
- `slots[].model.models[]` 每格 8 筆，每筆多 `p49Kt`：只有 `wn2-ens` 那筆有值（64 個成員裡估算陣風 ≥ 48 節的
  比例，0–1、兩位小數），其他筆一律 `null`（IFS 系集的機率照舊在 `model.ec.p49Kt`）。
  - `icon`：`gustKt` 是自己的陣風（`gustEstimated: false`）、`windKt` 是同一小時的平均風；有雨量、型態，沒有
    能見度（Open-Meteo 給 `null`）
  - `jma`：估算陣風（`gustEstimated: true`、`gustFactor`／`gustFactorBasis`）；有雨量、型態，沒有能見度
  - `wn2-ens`：`windKt`／`gustKt` 是成員中位數的平均風與估算陣風（`gustEstimated: true`、有 `gustFactor`）、
    `crosswindKt`／`rain6hMm`／`ptype`／`visibilityM` 永遠 `null`；`levels.wind` 只有 `high`／`low`，其他三類
    `null`
  - Open-Meteo 失敗那一報三筆的數字、`levels`、`level` 全是 `null`（不沿用）
- `slots[].model.vote`：`total` 最多 8（旁觀模式不算）
- 頂層 `runs.icon`、`runs.jma`、`runs.wn2-ens`（ISO 或 `null`；Open-Meteo metadata 的最近一報）
- `sources.openmeteo`：`ok`、`seconds`、`bytes`、`calls`（這一報的加權呼叫次數，51 個機場 397.8）；失敗時
  `error`（`timeout`、`http_429`、`network`、`bad_format`……），沒有 `reusedFrom`；metadata 問不到時多
  `runError`（例如 `"wn2-ens:timeout"`，資料照用）
- `warnings[].kind` 多 `jma_snowstorm_emergency`（高、算 `snow`，`code` `32`）；四語「日本氣象廳暴風雪特別警報
  （千歳市）」／「日本气象厅暴风雪特别警报（千歳市）」／「JMA snowstorm emergency warning (Chitose)」
- 資料來源頁要標「Open-Meteo（CC BY 4.0）・DWD ICON・JMA・Google WeatherNext 2」（下面「資料來源與授權」）
- 大小：用 Pages 上 2026-10-20 05:55Z 那報加 11:17Z 抓的 Open-Meteo 重算，`latest.json`（不縮排）2,214 KB →
  **3,023 KB（多約 790 KB）**；gzip 後 142 → 174 KB。每格多 3 筆（各約 240 bytes）× 1,020 格，加上既有 5 筆
  多 `p49Kt`

規格以外加的欄位與值（網頁可以忽略）：

- HD2（2026-10-19）加的節欄位（要進 Duado spec 第 16 節；舊欄位全部照出、型別不變）：
  - `slots[].model.ec.hresGustKt`、`slots[].model.gfs.gustKt`：模式陣風（節，一位小數）；
    `hresGustMs`／`gustMs` 照舊是 m/s
  - `slots[].model.ec.p29Kt`、`p37Kt`、`p49Kt`：系集「陣風 ≥ 29／37／49 節」的機率（0–1）。實際對應的
    門檻：`p29Kt` 就是 `p15`（≥ 15 m/s ≈ 29.2 節）、`p49Kt` 就是 `p25`（≥ 25 m/s ≈ 48.6 節）；
    `p37Kt` 目前沒有來源（ECMWF 開放資料沒有 ≥ 19 m/s 的機率），一律 `null`，保留給之後用 GEFS 系集成員
    自己算

- `runs.ecmwfEns`：系集機率那一報（只有 00／12Z 有，可能比 HRES 早一報）
- `sources.<名稱>.seconds`、`bytes`；`sources.ecmwf.ensembleOk`／`ensembleError`（只有系集失敗時）；
  `sources.flights`
- `sources.<名稱>.error` 多一個值 `"timeout"`：超過時間預算被放棄（這時 `seconds` 是預算）
- `sources.ecmwf.mirror`：HRES 實際從哪裡下載，`"aws"`／`"ecmwf"`／`"google"`
- `sources.gfs.mirror`（H10）：GFS 最後從哪裡下載，`"aws"`（AWS 開放資料鏡像）／`"nomads"`
- `sources.ecmwf.reusedFrom`、`sources.gfs.reusedFrom`：這次失敗、模式資料沿用之前的結果時，抄的
  那一份的 `generatedAt`（`ok` 仍是 `false`，網頁照樣顯示「這次沒讀到」）
- `sources.tracks`（HD21）：颱風路徑抽取，**只在 `events.json` 有事件在期間內時才有**：
  `{"ok", "seconds", "bytes"}`；有模式抽不出來時 `ok: false`、`error: "partial"`（其他模式照寫），超時
  `error: "timeout"`。路徑本身不進 `latest.json`（在 `data` 分支，下面「事件保存」）
- `sources.flights.statsError`：航班取消／延誤統計算不出來或寫檔失敗時才有，`"<機場>:<訊息>"`
  （多個用 `; ` 接）；不影響 `latest.json` 其他內容
- `warnings[].code`（天文台／SMG 信號代碼，例如 `TC8NE`、`TC3`）、`warnings[].detail`（氣象署警戒區原文、
  SMG 的說明原文）
- `official.warnings`（這格套用了哪些警報）；只有警報、沒有 TAF 的格 `official.kind` 是 `"warning"`
  （HD8 起只有中以上的警報才會撐起這種格）
- 官方與模式都沒資料的格：`level: "unknown"`、`basis: "none"`、`model.level: null`；
  `agreement` 在少一個模式時是 `null`
- TAF 沒涵蓋、也沒有警報的 0–30 小時格：`official: null`、`basis: "model"`

## 事件保存（HD20）

颱風 29W（CHAMPI，薔琵）的 AI 模式與物理模式路線分歧很大，Shawn 2026-10-20 定案拿這顆完整驗證：期間內
每一報、每小時的機場觀測與颱風位置都永久存在 `data` 分支的 `history/events/<id>/`，颱風過後用報告工具
（HD22）算誤差。驗證報告出來前規則凍結（`docs/ORCHESTRATOR.md`「29W 驗證期凍結」）。

- **`events.json`**（repo 根目錄）：一個事件一筆；`from`／`to` 是**台灣日期**（含兩端）。之後其他颱風
  加一筆就好：

  ```json
  {"events": [{"id": "29W", "name": "CHAMPI（薔琵）", "from": "2026-10-19", "to": "2026-10-28",
    "airports": ["RCTP", "…25 個"], "jma": {"tcId": "TC2636"}, "jtwc": {"id": "wp2926"}}]}
  ```

  `jma.tcId` 是 JMA bosai 的颱風代號（29W 是 `TC2636`，號數是 2630；`targetTc.json` 查得到），
  `jtwc.id` 是 JTWC 警報的檔名（`wp2926`）。29W 的 25 個機場：台灣全部 10 個、那霸、宮古、石垣、鹿兒島、
  福岡、福州、廈門、浦東、虹橋、香港、關西、中部、羽田、成田、仙台
- **每報快照**：`build.py` 寫完 `history/<時間>.json` 後，`generatedAt` 在期間內就原樣再存一份
  `history/events/<id>/<YYYYMMDDTHHMM>Z.json`（同一份內容，git 裡是同一個 blob、不多佔空間）。
  期間開始時已經過去的報，在 Actions 手動跑 `events` workflow、勾 `backfill` 搬一次（已存在的跳過；
  本機是 `python -m hongthai.events backfill --archive data`）
- **每小時**（`.github/workflows/events.yml`，每小時 07 分；期間外 `python -m hongthai.events hourly`
  印一行就結束）：三件事分開 try，失敗只記 log
  1. 機場觀測 `metar/<YYYY-MM-DD>.jsonl`（觀測時間的 UTC 日期）：AviationWeather 一次請求全部站、
     `hours=3`（半小時一報的機場兩筆都拿到、排程晚了也補得回來）；金門、馬祖用氣象署 `O-A0003-001`
     （HD13，`CWA_API_KEY`）。一站一筆觀測一行，同一站同一 `observedAt` 已經有就不寫：

     ```json
     {"t": "2026-10-20T06:07:00Z", "icao": "RJFF", "observedAt": "2026-10-20T05:00:00Z",
      "windDirDeg": 210, "windKt": 12, "gustKt": 22, "visibilityM": 9999, "wx": [],
      "raw": "METAR RJFF 200500Z 21012G22KT …", "source": "aviationweather", "type": "METAR"}
     ```

     `t` 是抓的時間；`source` 是 `aviationweather` 或 `cwa`；`type` 是 `METAR`／`SPECI`（氣象署的是 `null`）
  2. JMA 現報 `position/jma-<YYYY-MM-DD>.jsonl`：`https://www.jma.go.jp/bosai/typhoon/data/targetTc.json`
     確認颱風還在，再讀 `…/data/<tcId>/specifications.json`（實況＋各預報點；非正式介面）
  3. JTWC 現報 `position/jtwc-<YYYY-MM-DD>.jsonl`：`https://www.metoc.navy.mil/jtwc/products/<id>.tcw`
     （文字警報，`T000 159N 1356E 130` 這種行＋本文的陣風與中心氣壓）；原文另存
     `position/raw/jtwc-<YYYYMMDDTHHMM>Z.txt`（有新的一報或解析不出來時才存）

  颱風位置一行一點（日期是**發布時間**的 UTC 日期；同一來源同一 `issuedAt`＋`validAt` 已經有就不寫）：

  ```json
  {"t": "2026-10-20T06:07:00Z", "issuedAt": "2026-10-20T03:45:00Z", "kind": "analysis",
   "leadHours": 0, "validAt": "2026-10-20T03:00:00Z", "lat": 16.2, "lon": 134.9,
   "pressureHpa": 945, "windKt": 100, "gustKt": 140, "source": "jma", "raw": {…}}
  ```

  `kind` 是 `analysis`（現報）或 `forecast`；`windKt` 是最大平均風——**JMA 是 10 分鐘平均、JTWC 是
  1 分鐘平均**，不能直接比；JTWC 只有現報有 `pressureHpa`，另有 `warning`（警報編號）；`raw` 是 JMA 的
  原始那筆、JTWC 的 `T` 行原文。正式最佳路徑之後在 HD22 換
- **颱風路徑**（HD21，`src/hongthai/tracks.py`）`tracks/<起報 YYYYMMDDTHHMM>Z-<模式>.json`：每個模式
  每一報抽一次（已經有的跳過），颱風過後對最佳路徑算每個提前時間的距離誤差（HD22）。主 build 裡是來源
  `tracks`（模式都抓完後跑、預算 150 秒；`latest.json` 只多 `sources.tracks`，期間外不跑），兩種做法：
  - **IFS（`ifs`）、IFS 系集（`ifs-ens`）**：ECMWF 開放資料自帶的颱風路徑產品，不自己找中心。請求是
    `stream="oper"`／`"enfo"`、`type="tf"`、`step=360`（00／12Z）或 `144`（06／18Z），BUFR，用 `eccodes`
    解析；00Z 那報 oper 42,726 bytes、enfo 1,252,262 bytes。用這一報 HRES 的時次（系集的路徑產品四個時次
    都有）。只留事件那顆：`stormIdentifier` 等於 JTWC 編號（`wp2926` → `29W`）或名稱等於事件名稱的英文
    （`CHAMPI`）——**ECMWF 把 29W 叫 `36W`**，實際靠名稱比到；都比不到就取離 JMA／JTWC 現報 300 公里內最近的。

    ```json
    {"model": "ifs-ens", "run": "2026-10-20T00:00:00Z",
     "storm": {"id": "36W", "name": "CHAMPI", "matchedBy": "name", "observed": {"lat": 16.0, "lon": 135.6}},
     "members": [{"member": 1, "points": [{"validAt": "2026-10-20T00:00:00Z", "lat": 16.1, "lon": 135.1,
                                           "pressureHpa": 953.0, "windKt": 119.0}, …]}, …],
     "mean": [{"validAt": "2026-10-20T00:00:00Z", "lat": 16.0, "lon": 135.5, "n": 51}, …]}
    ```

    `members` 的 HRES 只有一個（`member: 0`）；系集 51 個（1–50、51 是控制報）。起報那一刻的點是 ECMWF 的
    分析位置，`observed` 是發布中心的觀測位置；`pressureHpa` 是中心氣壓、`windKt` 是 10 米最大風（節）。
    `mean` 是系集每個時間點有點的成員的**中位數位置**（經緯各取中位數），成員少於 10 個的時間點不寫；
    HRES 的 `mean` 是空的。產品裡沒有這顆時 `storm: null`、`members: []`（照寫，表示那報找過了）。系集一報
    約 110–140 KB
  - **GFS、AIGFS、AIFS**：事件期間三個來源多抓海平面氣壓（GFS、AIGFS 的 `PRMSL:mean sea level`、AIFS 的
    `msl`；步長和原本一樣，起報後第一個 6 小時格起 120 小時、每 6 小時），從氣壓場找中心：
    1. 起點：起報時間前後 3 小時內 JTWC、再 JMA 的現報（`position/` 的 `analysis`，離起報時間最近的）；
       都沒有就用 `events.json` 可以加的 `"seed": {"lat", "lon", "at"}`（`at` 也要在 3 小時內）；再沒有就用
       同一報 ECMWF 路徑產品裡那顆的觀測位置（`ecmwf-tf`；HD20 上線前的報沒有現報，補過去的報靠這個）；
       都沒有就跳過這報、記 log
    2. 第一個步長在起點 ±4° 的方框找海平面氣壓最小值；之後每步在上一步中心 ±3° 的方框找（6 小時移動上限
       約 330 公里）；格點 0.25°、不內插
    3. 停止（這步起不再追）：最小值 > 1005 hPa（`weak`）、方框裡最小點在邊界上（`edge`）、中心跨出北緯
       0–40°／東經 100–180°（`domain`）、步長不連續（`gap`）；追到最後一個步長是 `end`

    ```json
    {"model": "gfs", "run": "2026-10-20T00:00:00Z",
     "seed": {"lat": 16.0, "lon": 135.6, "at": "2026-10-20T00:00:00Z", "source": "ecmwf-tf"},
     "points": [{"validAt": "2026-10-20T00:00:00Z", "lat": 16.25, "lon": 135.75, "mslpHpa": 924.0},
                {"validAt": "2026-10-20T06:00:00Z", "lat": 16.75, "lon": 134.25, "mslpHpa": 921.8}, …],
     "stop": "weak"}
    ```

    `seed.source` 是 `jtwc`／`jma`／`events.json`／`ecmwf-tf`。一報約 1.7 KB
  - **補過去的報**：Actions 手動跑 `events` workflow、勾 `backfill-tracks`（本機
    `python -m hongthai.events backfill-tracks --archive data --from 2026-10-19T00:00Z`）：讀 `--from` 以後
    每份快照 `history/events/<id>/<時間>.json` 的 `runs`，每個模式每個時次只抽一次（已經有的跳過；IFS／系集
    用 `runs.ecmwf` 與 `runs.ecmwfEns`），步長照那一報 build 時的（最早引用它的那份快照的 6 小時格起 120
    小時）。GFS、AIGFS 從 AWS 重抓海平面氣壓（留 30 天）、IFS、AIFS 從 ECMWF 開放資料抓（約 4 天，拿不到
    記 log）。2026-10-20 08:30Z 在雲端開發機對 `data` 分支實跑：21 份快照 → 22 份路徑（10-18 12Z 到 10-20
    00Z，IFS／系集各 6、GFS 6、AIGFS 2、AIFS 2），下載 190,933,455 bytes、175 秒
- **推 `data` 分支**：每小時和每天四次的主 build 可能同時推，兩邊都用 `tools/push_data.sh`：commit 後
  `git pull --rebase origin data` 再推，失敗重試 3 次（間隔 20 秒）。兩邊寫的檔不重疊，不會衝突
- 實際停飛照舊用 `history/cancellations/`（不用另外存）

## AI 對決

HD5（第四階段，Shawn 2026-10-18／19 定案）：每個機場三顆燈——**規則**（現有等級）、**Claude**
（`claude-opus-5-5`）、**Gemini**（`gemini-4-argon`，Vertex AI）。兩個 AI 各自讀該機場的全部數據，
給自己的等級（低／中／高）與一段短評，像評論員；數據照舊全部保留給讀者。程式在 `src/hongthai/ai/`。

- **只評哪些機場**（`ai/select.py`）：未來 5 天任一格 `level` 是中／高／已確認，或和上一份 `latest.json`
  同機場同 `from` 的格 `level` 不同（「等級有變」，`unknown` 和 `low` 互換也算）。依「5 天內最高等級
  （已確認 > 高 > 中 > 低）、再依第一個達到那級的格早的」排序，**每報最多評 20 個**；其他機場兩顆 AI 燈
  直接寫「沒看到明顯風險」、不呼叫（`skipped`）；符合條件但排在 20 個之後的記 `error: "run_cap"`
- **給模型看什麼**（`ai/prompt.py`）：那個機場的精簡文字（不丟整段 JSON）——機場名、時區、METAR、TAF 原文、
  生效中的警報、已確認停飛，20 格每格的當地時段、等級、依據、官方（TAF 平均風／陣風、側風、警報）、
  模式（EC／GFS 陣風、側風、`p29Kt`／`p49Kt`）、一致性、落差，單位一律節、機率用百分比；最後附規則燈的
  門檻（37／48 節、側風 27／33 節、`p49Kt` 30%）。系統提示全文在 `ai/prompt.py` 的 `SYSTEM`。
  HD8 起每格多給 `causes`、官方層 `wx`（現象、能見度、雲底、三類等級）、模式層的雨量／降水型態／
  `p24hRain50`／GFS 能見度，METAR 多給能見度、天氣、雲底，規則說明加三類的門檻；系統提示加「短評第一句
  要點出主因天氣（強風／側風、大雨／雷雨、大雪／結冰、濃霧／低雲）」，用字對照加 zh-CN 浓雾、能见度、云底、
  结冰、米、英尺（zh-HK 同台灣寫法），內部代號多 `ptype`、`rain6hMm`、`visibilityM`、`ceilingFt`、`causes`、
  `p24hRain25`、`p24hRain50`、`APCP`、`CSNOW`、`CFRZR`，簡繁抽查多「霧／雾」「見／见」
- **規則**：AI 只能根據給它的數據講，不能用其他知識或外部資訊、不能自己估機率；短評 zh-TW 60–120 字，說明
  依據哪幾格、哪些數字，只講風險判讀、不給乘客建議；**一次輸出四語，以 zh-TW 為準，zh-HK、zh-CN、en 是
  忠實翻譯，內容完全一樣、不得增減**，zh-HK、zh-CN 用當地用語。回應一定要是
  `{"level", "comment": {四語}}` 的 JSON，不然記 `bad_format`（外面包了 ``` 或前後多了說明文字時，取第一個
  `{` 到最後一個 `}` 之間再解析，HD6）；字數上限中文每語 300 字、en 800 字（`config.MAX_COMMENT_CHARS`）
- **免責**：頂層 `ai.disclaimer`「AI 評論僅供參考，以航空公司與機場公告為準」（四語）
- **保險**（`ai/config.py`）：每報最多評 20 個機場；每天（UTC）每個模型的呼叫上限 `DAILY_CAP` **開發期間不限**
  （`DAILY_CAP=0`，2026-10-19 定案，HD11；手動 Run workflow 也照常跑 AI），正式推廣前再評估，恢復時改成 80 之類的
  數字即可，超過的記 `daily_cap`；`history/ai/calls-<日期>.json` 照常記每個模型今天呼叫幾次（成功失敗都算）；
  另有 Anthropic workspace 每月 30 美元硬上限、GCP 30 美元預算警示（在平台上設）；格式不對、逾時、API 錯誤都記 `error`、**不重試**（兩個 SDK
  的自動重試都關掉；唯一例外是 `http_503`／`http_504` 重試一次，見下一條）；單次請求逾時 60 秒；整個 AI 步驟預算 240 秒（`BUDGET_S["ai"]`；HD12 前 180 秒，
  HD11 後第一報 178.2 秒頂到預算），兩個模型**平行**呼叫、每個模型的並行數 Claude 4 條、Gemini 3 條
  （`config.PARALLEL`；HD6 時 4 條撞過 429、降到 2；HD12 升回 3 再觀察，若 429 回來就降回 2），超過的機場記
  `timeout`。AI 失敗不影響 `latest.json` 其他內容
- **`http_503`／`http_504` 只重試一次**（HD17，Shawn 2026-10-20 定案；`ai/run.py`，`config.RETRY_CODES`）：
  閘道沒回應（Vertex 閘道逾時）不是模型回了壞東西、也不計費，所以同一個請求、不改內容再送一次；只在**剩餘預算
  ≥ 70 秒**（`config.RETRY_MIN_LEFT_S`，一次請求逾時 60 秒）時重試，不夠就照舊記 `http_504`。重試也算一次呼叫
  （`sources.ai.calls`、次數檔都加 1；`DAILY_CAP` 恢復後到上限也不重試）。重試成功就是 `ok`；重試仍失敗記第二次的
  代碼、戰績 `detail` 後面加 `:retried`（例如 `"http_504:-:-:retried"`），`seconds` 是兩次合計。`http_429`、
  `http_400`、`bad_format`、`bad_wording`、`refusal`、`timeout` 都**不重試**。程式兩個模型共用，Claude 的 5xx 很少見，
  但一樣適用。起因是 2026-10-19T18:07Z 那報（HD13 合併後第一報）：Gemini 4 個 `http_504`（RCFG、RCKH、ROIG、
  ZSQZ），每個都卡 57 秒才回，依字母順序 3 條並行時 RCFG／RCKH、ROIG／ZSQZ 幾乎同時送，偏向是負載相關（前一報是
  2 個）。Gemini 20 筆共約 470 秒，3 條並行約 157 秒；降回 2 條會到 235 秒、撞 240 秒預算，所以**維持 3 條並行**，
  改成 504 重試一次
- **模型參數**：Claude 用官方 `anthropic` SDK（Messages API），`max_tokens` 3000（HD6；HD5 是 1200）、
  `effort: "low"`；**不送 `temperature`**——Opus 5.5 不接受取樣參數（送了回 400），思考也關不掉、思考的
  token 算在 `max_tokens` 裡，所以用 `low` 留空間給四語短評；沒開 server-side fallback（換別的模型回答，
  戰績會記錯人）。Gemini 用 `google-genai` SDK（`vertexai=True`、`location` 用 `GOOGLE_CLOUD_LOCATION`、
  服務帳號憑證），`max_output_tokens` 3000、`temperature` 0.3、`response_mime_type: application/json`、
  `thinking_config` 的 `thinking_level: LOW`、`include_thoughts: false`（HD6）——Gemini 4 的思考關不掉、
  **送 `thinking_budget` 回 400**、不支援 `MINIMAL`，`LOW` 是能設的最低；思考的 token 也很可能算在
  `max_output_tokens` 裡
- **第一次實跑（2026-10-19T03:57Z）與 HD6 的修正**：`bad_format` Claude 9/20、Gemini 17/20。成功的 13 則
  en 短評長度 318–400 字（關島剛好 400）、中文 127–192 字——en 被 HD5 的 400 字上限擋下應是大宗，所以 en
  放寬到 800、中文 300；另外 `max_tokens` 加到 3000、Gemini 思考設最低，防思考吃掉輸出上限而被截斷。
  之後失敗的原因直接看戰績檔的 `detail`（見下面「對決戰績」）
- **Gemini 的 `http_429`**：`gemini-4-argon` 走 `global` endpoint 的 Standard PayGo，**沒有可以在 GCP
  申請提高的每專案每分鐘請求數配額**：吞吐量是**組織層級的用量級距（usage tier）**，依整個組織過去 30 天
  在 Vertex AI（Agent Platform）的花費自動調整（Tier 1：花費 10–250 美元，Pro／Argon 優先吞吐量
  500,000 TPM；Tier 2：250–2,000 美元，1,000,000 TPM；以上類推），超過的流量有空閒容量時照樣服務，
  忙的時候先被節流回 429——**429 不代表撞到固定配額**，是當下資源競爭。新專案花費很少，大概還在 Tier 1
  以下，所以 Gemini 降成 2 條並行、讓請求不要一次擠進去（HD12 升回 3 條再觀察）。Shawn 要做的：在 GCP 控制台
  「Vertex AI（Agent Platform）→ Dashboard」看組織目前的級距（要專案的 `roles/aiplatform.viewer` 與帳單帳戶的
  `roles/billing.viewer`）；要更多只能找 Google Cloud 業務談 Custom Tier，或改買 Priority PayGo／
  Provisioned Throughput——**以我們每天幾十到一兩百次的量都不值得**，先觀察 2 條並行後還有沒有 429。
  「IAM 與管理 → 配額與系統限制」裡 `aiplatform.googleapis.com` 的
  `global_generate_content_requests_per_minute_per_project_per_base_model` 這類配額，文件寫的是 Gemini Omni、
  Lyria 這些生成媒體模型用的，不是 Argon 文字生成。來源：
  [Standard PayGo](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/standard-paygo)、
  [Troubleshooting error code 429](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/deploy/error-code-429)、
  [Quotas and system limits](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/models/quotas)
- **用字規則與檢查**（HD6，產品負責人 2026-10-19 定案；規則寫在系統提示的「用字」那段，檢查在
  `ai/parse.py` 的 `check_wording`，詞表集中在 `ai/config.py`，之後要加詞只改那裡）：
  1. **不出現內部代號**：`p29Kt`、`p49Kt`、`EC`、`GFS`、`HRES`、`TAF`、`METAR`、`crosswindKt`、`gustKt`、
     `basis`、`agreement` 等欄位名或縮寫都不寫（`causes`、`basis`、`agreement`、`slots` 在 en 是常用字，例外，HD17），改成白話——「歐洲模式」「美國模式」、「陣風超過 49 節的機率
     56%」、「機場預報（TAF）」第一次可以括號附原名、之後只寫「機場預報」，「機場觀測」（METAR）同樣；
     側風、陣風、平均風直接用中文；數字照抄資料
  2. **四語照 Duado 的語系規則**：zh-TW 台灣用語；zh-HK 書面語加香港用語、不用粵語口語（颱風警報 →
     颱風警告，只有香港天文台的熱帶氣旋警告信號才寫「信號」；飯店 → 酒店、計程車 → 的士、公車 → 巴士…）；
     zh-CN 簡體加大陸用語（台风、侧风、阵风、机场预报、信号、节；機率 → 概率、資料 → 数据，HD7）；
     en 自然英文，時間寫 `10/19 12:00–13:00` 或 `12–13 h local`、不寫「時」；四語內容完全一樣，只換用語
  3. **不寫英文等級字**：不出現「高（high）」；中文「低／中／高」，英文 Low／Medium／High
  4. **叫法一致**：中文三語統一「停飛風險」（zh-CN「停飞风险」）；英文統一 disruption risk

  格式檢查通過後再檢查用字，不過就記 `error: "bad_wording"`（不採用、不重試，和其他錯誤一樣）：
  - 四語任一語出現內部代號（`config.FORBIDDEN_TOKENS`：`p29Kt`、`p49Kt`、`p37Kt`、`p10`、`p15`、`p25`、
    `HRES`、`GFS`、`EC`、`crosswindKt`、`gustKt`、`hresGustKt`、`basis`、`agreement`、`slots`、
    `latest.json`）；大小寫不分、整字比對（前後不能是英文字母、數字、底線，所以「EC陣風」抓得到、
    `ECMWF`、`TAFF` 不算）。**英文常用字例外**（HD17，`config.EN_PLAIN_WORDS`）：`causes`、`basis`、`agreement`、
    `slots` 在 en 不擋（"strong wind causes…"、"on the basis of"、"models are in agreement"、"afternoon slots"），
    中文三語照擋（中文短評裡出現這些英文字只會是抄欄位名）；其他代號四語都照擋。起因是 18:07Z 那報 4 個
    `bad_wording` 全是 `en/causes`（Claude RCYU、Gemini RCFN／RCTP／ROMY）——HD8 把 `causes` 當代號擋、整字
    比對又不分大小寫，英文寫 "causes" 當動詞就被擋，是檢查誤判、不是模型用字問題
  - `TAF`／`METAR` 可以在括號裡出現一次（「機場預報（TAF）」「airport forecast (TAF)」），沒括號或第二次以上算違規
  - 中文三語出現「（high）」「(medium)」這類英文等級字
  - zh-HK 出現粵語口語字：喺、嘅、咗、嚟、啱啱、唔、佢、冇、咁
  - zh-CN 有繁體常見字（颱 風 機 場 預 報 節 側 陣）；zh-TW、zh-HK 有簡體常見字（风 机 场 预 报 节 侧 阵）
  - zh-CN 用了台灣用語（HD7，`config.ZH_CN_TAIWAN_TERMS`：机率、资料；要寫「概率」「数据」）；zh-TW、zh-HK
    不受這條影響（本來就寫「機率」「資料」）
  - 中文三語裡有一語寫「停飛／停飞」、又有一語寫「航班取消」；en 寫 cancellation risk 或 suspension risk
  - en 有任何中日文字或全形字（Unicode `\u3000–\u30ff`、`\u3400–\u4dbf`、`\u4e00–\u9fff`、`\uff00–\uffef`）

  log 會寫是哪一語、哪個詞（例如 `zh-HK：粵語口語「喺」`、`en 含中日文字「時」`、`zh-CN 用了台灣用語：机率`）。第一次實跑抓到的四則
  （MZG 滿是代號、NRT 的 zh-HK 用了「喺、同、啱啱」、MMY 寫「高（high）」、TNN zh-CN「航班取消风险」
  zh-TW 卻是「停飛風險」）和 GUM 的 en「10/19 12–13 時」都在 `tests/test_ai.py` 當案例；HD6 後第二次實跑
  （04:39Z）Gemini 的 zh-CN「资料」「机率」（PGUM）也是（HD7）
- **金鑰**：見上面「怎麼跑」的四個環境變數；HongThai 專屬（各月上限 30 美元、不跟 Duado 共用），只放 Actions secrets
- **對決戰績**（`data` 分支 `history/ai/<YYYY-MM-DD>.json`，UTC 日期一天一檔；不進 Pages、不進 `latest.json`）：
  每報每個機場一筆，同一跑次同一機場新的覆蓋舊的（同 `cancellations` 的寫法），依 `run`、`airport` 排序。
  只存等級與格，不存短評全文（短評在 `history/<時間>.json` 裡）。11/18 拿來對 `history/cancellations/`
  回看規則、Claude、Gemini 誰事前比較準：

```json
{ "run": "2026-10-19T02:15:00Z", "airport": "RCKH", "selected": "level",
  "rule": { "maxLevel": "high", "firstFrom": "2026-10-23T00:00:00Z" },
  "claude": { "status": "ok", "level": "high", "seconds": 21.7 },
  "gemini": { "status": "ok", "level": "medium", "seconds": 34.2 },
  "slots": [ { "from": "2026-10-19T00:00:00Z", "level": "low" } ] }
```

- `selected`：被選的原因 `"level"`／`"changed"`，沒被選（含 `run_cap`）是 `null`；`rule.maxLevel` 是 5 天內最高
  等級（全部 `unknown` 是 `null`）、`firstFrom` 是第一個達到那級的格；`slots` 是 20 格的 `from` 與 `level`
- `claude`／`gemini` 呼叫失敗時多一個 `detail`（HD6，不記短評內容；`latest.json` 不加）：
  `"<代碼>:<stop_reason>:<輸出 token 數>[:<標記>]"`，例如 `"bad_format:max_tokens:3000"`（被截斷）、
  `"bad_format:end_turn:1650:en_too_long"`、`"bad_wording:STOP:700+900:zh-HK/喺"`、`"http_429:-:-"`（沒拿到
  回應的欄位寫 `-`）。Claude 的 token 數是 `usage.output_tokens`（含思考）；Gemini 是
  `candidates_token_count`，有思考時寫成 `<回答>+<思考>`（`thoughts_token_count`）。標記是解析失敗的種類
  （`not_json`、`not_object`、`level`、`no_comment`、`missing_<語>`、`<語>_too_long`）或用字違規的
  `<語>/<詞>`。`daily_cap`、`run_cap`、`no_api_key`、`timeout`（預算到了沒送）沒呼叫，不寫 `detail`。
  log 也印同一串（`AI gemini RCKH 失敗：bad_wording: zh-HK：粵語口語「喺」［bad_wording:STOP:700+900:zh-HK/喺］`）
- `claude`／`gemini` 真的送出的呼叫（成功、失敗都算）多一個 `seconds`（HD12，`latest.json` 不加）：從送出到
  收到回應或出錯花幾秒，一位小數，例如 `{ "status": "ok", "level": "high", "seconds": 23.4 }`、
  `{ "status": "error", "level": null, "detail": "http_504:-:-", "seconds": 57.2 }`；`http_503`／`http_504` 重試過的
  是兩次合計（HD17）。`skipped`、`run_cap`、
  `daily_cap`、`no_api_key`、`timeout`（預算到了沒送）沒送出，不寫 `seconds`；送出後預算先到、結果不採用的
  （記 `timeout`）也不寫

## 分享預覽圖

HD1（規格 Duado #374，預設值 Shawn 2026-10-19 拍板）：每報 build 跑完，用 Pillow 畫每個機場一張
**1200×630** 的 PNG，發布在

`https://duadoapp.github.io/hongthai/og/<iata 小寫>.png`（例如 <https://duadoapp.github.io/hongthai/og/tpe.png>）

Duado 用 Pages Function 轉送這張圖當分享預覽卡，`latest.json` 沒有加欄位。程式在 `src/hongthai/og.py`。

- 內容（Duado 晨光風格：底色 `#EDF1F4`、文字 `#263038`，大圓角色塊，不用框線與陰影，不做深色版；
  不放 logo、地圖）：
  - 左上 IATA 大字（Fraunces opsz 144，160 px），其下機場名 zh-TW（芫荽 56 px）與 en（Fraunces 36 px）
  - 右上燈號：300×110、圓角 28 的色塊，裡面寫等級字。顏色：低 `#C2DCC6`、中 `#F3E3A5`、高 `#F7C9A9`、
    已確認 `#263038`（字用 `#EDF1F4`）、資料不足 `#D8DEE3`（`og.LEVEL_COLORS`）
  - 色塊下一行小字；左下「更新 2026-10-19 02:15（當地時間）」（機場時區的 `generatedAt`）；
    右下「HongThai　機場停飛風險」與「duado.app/hongthai」
  - 時間軸（HD4，網頁時間軸的縮小版）：機場名下方、更新時間上方，未來 5 天 20 格照 `slots` 的順序各一個
    小圓角色塊（高 28、圓角 8、間隔 6，寬度依可用空間算、最多 48；色塊裡不寫字），顏色和燈號同一套
    （`og.LEVEL_COLORS`；沒有等級當資料不足）。寬度和左側文字區對齊；三顆燈時左側太窄，改放到燈號
    下方整排橫跨（1200 − 2×64 以內）。每天第一格下方標當地日期 `M/D`（Fraunces 20 px）：一格的日期以
    它的 `from` 換成機場當地時間為準，第一格一定標（就算不是當地那天的第一格），之後當地日期變了就標，
    最多 6 個；兩個標籤太近時後一個往右推、超出時間軸右邊就往左收。不標時刻
- 燈號是這個機場**未來 5 天（20 格）裡最高的等級**，小字寫第一個達到那個等級的格的當地日期時段：
  - 「最高：高　10/23 14–20 時」；結束在當地午夜寫「18–24 時」；跨午夜寫兩個日期「10/23 20 時–10/24 02 時」
    （UTC+8 的機場每天有一格這樣）
  - 那格有 `causes` 時後面接主因（HD8，`causes[0]`）：「最高：高　10/23 08–14 時・強風」，`wind` 強風、
    `rain` 大雨、`snow` 大雪、`fog` 濃霧（`og.CAUSE_TEXT`）；`causes` 是空的就不加
  - 全部低：「未來 5 天：低」
  - 有 `confirmed` 的格（視為高）：色塊「已確認」、小字「已確認停飛　<第一個已確認的格>」
  - 全部 `unknown`：色塊與小字都是「資料不足」；有的格 `unknown`、有的有等級時只看有等級的
- 三顆燈（HD5，`og.lights_for`）：機場的 `ai` 兩顆都是 `skipped` 或 `error` 時照舊一顆規則燈（不畫標籤）；
  任一顆 `ok` 時畫三顆，標籤「規則」「Claude」「Gemini」：規則燈同上（等級與小字），AI 燈畫模型的等級，
  短評不畫、小字留空；`error` 的那顆用資料不足色塊寫「資料不足」，`skipped` 的用低。色塊並排、寬度自動縮，
  時間軸移到燈號下方整排。**AI 兩顆都失敗（`error`）時仍是一顆規則燈**（例如 2026-10-19T03:57Z 那報的
  高雄，兩顆都 `bad_format`；同一報關島的 Claude 是 `ok`，就是三顆）
- PNG 用固定調色盤（品牌色＋反鋸齒的中間色）＋`optimize=True`：每張約 17–20 KB，51 張約 0.9 MB；
  本機畫 51 張約 3.5 秒（HD4 加了時間軸後，2026-10-19 用 Pages 上 19:02Z 那份 `latest.json` 實測
  943 KB、3.5 秒；HD1 時是 893 KB、3.2 秒）
- 在 `publish()` 之後、Pages 上傳之前畫（`build.draw_og`），寫到 `public/og/`；整次 build 失敗改發布上一份
  `latest.json` 時，也用那一份畫。畫圖失敗只 log、不讓 build 失敗；預算 60 秒（`BUDGET_S["og"]`）；
  `history/timing/` 多一行 `source: "og"`（`ok`、`seconds`、`bytes` 是全部圖的總大小）
- 字型（`assets/fonts/`，都是 SIL OFL 1.1，只放子集，各附 `OFL-*.txt`）：ASCII 與數字用 **Fraunces**
  （SOFT 100、wght 600 的靜態檔，兩個子集：IATA 大字用 opsz 144 的 `Fraunces-Soft600-Display.subset.ttf`，
  其他小字用 opsz 9 的 `Fraunces-Soft600.subset.ttf`，授權檔共用），其他字用 **芫荽 Iansui**，芫荽缺的字才用 **Noto Sans TC**（目前一個都沒缺）。
  Pillow 不會自動補字，所以逐字分段、各段用自己的字型畫。來源、版本、子集大小見 `assets/fonts/README.md`
- **加了機場或改了機場名之後要重做子集**：`python tools/make_font_subset.py`（下載完整字型到暫存目錄、
  取子集寫回 `assets/fonts/`）。沒重做的話 `tests/test_og.py` 的涵蓋檢查會紅

## 發布設定（產品負責人要做的）

1. **Settings → Pages → Build and deployment → Source** 選 **GitHub Actions**
2. **Settings → Secrets and variables → Actions → New repository secret**：名稱 `CWA_API_KEY`，
   值是中央氣象署開放資料平台的授權碼（<https://opendata.cwa.gov.tw> 免費註冊後在「取得授權碼」）
3. AI 對決（HD5）：同一頁再新增四個 secret——`ANTHROPIC_API_KEY`、`GOOGLE_SERVICE_ACCOUNT_JSON`（服務帳號
   金鑰 JSON 整份原文）、`GOOGLE_CLOUD_PROJECT`、`GOOGLE_CLOUD_LOCATION`（`global`）。2026-10-19 已放好
4. **Actions → build → Run workflow** 手動跑一次，然後開
   <https://duadoapp.github.io/hongthai/latest.json> 確認

之後每天 UTC 01:05、08:25、13:05、20:25（台北／香港 09:05、16:25、21:05、04:25）自動跑。

## 資料來源與授權

| 來源 | 內容 | 授權 |
| --- | --- | --- |
| [ECMWF 開放資料](https://www.ecmwf.int/en/forecasts/datasets/open-data)（經 AWS／Google 鏡像） | HRES 10 米陣風（`10fg`／`10fg3`）與 10 米風（`10u`／`10v`）、系集陣風機率（`10fgg10`／`10fgg15`／`10fgg25`）；HD8 起 HRES 總降水 `tp`、降水型態 `ptype`、2 米溫度 `2t`，系集 24 小時雨量機率 `tpg25`／`tpg50` | CC BY 4.0，© ECMWF |
| NOAA GFS（[AWS 開放資料鏡像 `noaa-gfs-bdp-pds`](https://registry.opendata.aws/noaa-gfs-bdp-pds/)，[NOMADS](https://nomads.ncep.noaa.gov/) 備援） | 地面陣風 `GUST`、10 米風 `UGRD`／`VGRD`；HD8 起 6 小時降水 `APCP`、類別降水 `CRAIN`／`CFRZR`／`CICEP`／`CSNOW`、地面能見度 `VIS` | 美國政府公有領域 |
| [ECMWF AIFS Single](https://www.ecmwf.int/en/forecasts/datasets/open-data)（ECMWF 開放資料，經 AWS／Google 鏡像；HD14） | AI 模式的 10 米風 `10u`／`10v`、總降水 `tp`、降雪 `sf`、2 米溫度 `2t`（每 6 小時） | CC BY 4.0，© ECMWF |
| NOAA AIGFS（[AWS 開放資料 `noaa-nws-graphcastgfs-pds`](https://registry.opendata.aws/noaa-nws-graphcastgfs-pds/)；HD14） | AI 模式的 10 米風 `UGRD`／`VGRD`、6 小時降水 `APCP`、2 米溫度 `TMP` | 美國政府公有領域 |
| [Open-Meteo](https://open-meteo.com/)（[預報 API](https://open-meteo.com/en/docs) `models=icon_global,jma_gsm`、[系集 API](https://open-meteo.com/en/docs/ensemble-api) `models=google_weathernext2_ensemble`；HD16） | DWD ICON global 與 JMA GSM 的逐時 10 米風、風向、陣風（ICON）、雨量、降雪、天氣碼；Google WeatherNext 2 系集 64 個成員的 10 米風（6 小時一點） | **CC BY 4.0**（Open-Meteo 的資料授權；原始模式 © DWD、JMA、Google）。**免費版只限非商業**、每日 10,000／每月 300,000 次（加權）：**一旦 HongThai 或 Duado 收費、訂閱或放廣告，必須改買 Open-Meteo 商業方案或拿掉這三個模式**。網頁與資料來源標「Open-Meteo（CC BY 4.0）・DWD ICON・JMA・Google WeatherNext 2」。Google 對即時 WeatherNext 資料另有實驗條款，Open-Meteo 的授權來源查不到（上面「已知的保守假設」） |
| [AviationWeather.gov Data API](https://aviationweather.gov/data/api/) | TAF、METAR | 美國政府公有領域 |
| [OurAirports](https://ourairports.com/data/)（`airports.csv`、`runways.csv`） | 新增 46 個機場（H9 的 36 個、HD3 的 10 個）的座標與跑道真北方位、ICAO／IATA 核對 | 公有領域（Unlicense） |
| [OpenStreetMap](https://www.openstreetmap.org/way/114511749)（跑道 way 114511749 的兩端座標，HD3） | 石垣跑道真北方位（用座標算出的一個數字） | © OpenStreetMap contributors，[ODbL](https://www.openstreetmap.org/copyright) |
| [美國國家氣象局 api.weather.gov](https://www.weather.gov/documentation/services-web-api)（`/alerts/active?zone=GUZ001`，HD3） | 關島的颱風／熱帶風暴警報與守視（NWS 關島分處 Tiyan 發布） | 美國政府公有領域 |
| [日本氣象廳防災資訊](https://www.jma.go.jp/bosai/warning/)（JMA 網頁用的 JSON `bosai/warning/data/r8/<office>.json`、`bosai/common/const/area.json`，**非正式介面**；HD9） | 日本與沖繩 11 個機場所在市町村的大雪警報、大雪特別警報、暴風雪警報 | [氣象廳網站利用規約](https://www.jma.go.jp/jma/kishou/info/coment.html)：公共データ利用規約（第 1.0 版，PDL 1.0），註明出處「出典：気象庁ホームページ」即可使用與再發布 |
| [香港天文台開放數據](https://www.hko.gov.hk/en/weatherAPI/doc/files/HKO_Open_Data_API_Documentation.pdf)（data.gov.hk） | 天氣警告摘要（熱帶氣旋信號；HD8 起加暴雨警告信號 `WRAIN`、雷暴警告 `WTS`，同一個請求） | [data.gov.hk 使用條款](https://data.gov.hk/tc/terms-and-conditions) |
| [中央氣象署開放資料平台](https://opendata.cwa.gov.tw/)（`W-C0034-001` 颱風警報；HD8 起加 `W-C0033-001` 天氣特報；HD13 起加 `O-A0003-001` 氣象觀測站-10分鐘綜觀氣象資料） | 海上／陸上颱風警報與警戒區（台灣十個機場）；各縣市目前的天氣特報（只用大豪雨、超大豪雨、濃霧）；金門 467110、馬祖 467990 局屬站的能見度、天氣、風（當這兩個機場的 METAR） | [政府資料開放授權條款](https://data.gov.tw/license) |
| [澳門地球物理氣象局 XML](https://xml.smg.gov.mo/)（`c_typhoon.xml`／`e_typhoon.xml`；data.gov.mo 資料集[「熱帶氣旋信號」](https://data.gov.mo/Detail?id=15044781-1752-4f98-b87e-508208d70408)） | 熱帶氣旋信號 | [澳門政府數據開放平台使用條款](https://data.gov.mo/)：免費使用與再發布，須註明「澳門特別行政區政府數據開放平台」與取得日期 |
| [香港機管局航班資訊](https://data.gov.hk/tc-data/dataset/aahk-team1-flight-info)（data.gov.hk） | 算每 6 小時格的取消／延誤統計（不存原始資料） | data.gov.hk 使用條款 |
| [桃園國際機場即時航班](https://data.gov.tw/dataset/26194)（data.gov.tw） | 算每 6 小時格的取消／延誤統計（不存原始資料） | 政府資料開放授權條款 |
| 松山機場即時航班（data.gov.tw [37242](https://data.gov.tw/dataset/37242)／[37248](https://data.gov.tw/dataset/37248)／[37317](https://data.gov.tw/dataset/37317)／[37319](https://data.gov.tw/dataset/37319)） | 算每 6 小時格的取消／延誤統計（不存原始資料） | 政府資料開放授權條款 |
| 高雄機場即時航班（data.gov.tw [33656](https://data.gov.tw/dataset/33656)／[33655](https://data.gov.tw/dataset/33655)／[33651](https://data.gov.tw/dataset/33651)／[33649](https://data.gov.tw/dataset/33649)） | 算每 6 小時格的取消／延誤統計（不存原始資料） | 政府資料開放授權條款 |
| 澳門民航局航班資訊（data.gov.mo [離港（英文）](https://data.gov.mo/Detail?id=f910cf2e-5e30-45c3-9e62-3eb6bf912db3)／[抵港（英文）](https://data.gov.mo/Detail?id=44b62bd1-6c84-421f-b571-52ab184c7df3)） | 算每 6 小時格的取消／延誤統計（不存原始資料） | 澳門政府數據開放平台使用條款 |
| [芫荽 Iansui](https://github.com/ButTaiwan/iansui)（子集，`assets/fonts/`；HD1） | 分享預覽圖的中文字 | [SIL OFL 1.1](assets/fonts/OFL-Iansui.txt) |
| [Fraunces](https://github.com/undercasetype/Fraunces)（SOFT 100、wght 600 靜態檔的子集；HD1） | 分享預覽圖的英文與數字 | [SIL OFL 1.1](assets/fonts/OFL-Fraunces.txt) |
| [Noto Sans TC](https://fonts.google.com/noto/specimen/Noto+Sans+TC)（Google Fonts，子集；HD1） | 分享預覽圖：芫荽缺字時的備援 | [SIL OFL 1.1](assets/fonts/OFL-NotoSansTC.txt) |

HD8 新參數（2026-10-19 查 ECMWF 18Z oper／12Z enfo ep 的 index 與 GFS 00Z 的 `.idx`，實測下載量）：
- ECMWF HRES：`tp`、`ptype`、`2t` 和 `10u`／`10v` 同一個請求、只抓 6 小時整的步長（多抓第一格的開始步長來算
  6 小時雨量）；每個步長約 0.9、0.95、0.66 MB。HRES 的 index **沒有能見度**（`vis`），所以 EC 不算霧。
  `ptype` 代碼照 [ECMWF 參數 260015](https://codes.ecmwf.int/grib/param-db/260015)。系集 `tpg25`／`tpg50`
  每個窗約 0.07–0.15 MB。實測（AWS 鏡像，06:20Z）：陣風 52.7 MB／17 秒、風＋降水 85.6 MB／91 秒
  （H10 時只有風 29.6 MB）、系集 12.8 MB／42 秒，**共 151.0 MB、165.6 秒**（H10 時約 92 MB；預算 300 秒）
- GFS：`.idx` 裡 `APCP:surface` 有兩筆（`<fh−6>-<fh> hour acc` 那桶與從起報累積的），類別降水有瞬時與
  `ave` 兩種，所以要比對時效字串（`gfs.IDX_FIELDS`／`IDX_OPTIONAL`）；f000 沒有 `APCP`。每個步長多約
  1.24 MB，實測（AWS，00Z）**73.8 MB、53.8 秒**（H10 時約 50 MB；預算 180 秒）。這幾筆找不到時只 log、
  陣風照抓
- 氣象署天氣特報用 `W-C0033-001`（各縣市目前的特報，用 `cwaAreas` 比縣市名），不用 `W-C0033-002`（每則特報
  的影響區域，名稱是另一套）；沒有授權碼沒辦法實抓，格式照平台文件寫、原始回應存
  `history/raw/<日期>/<時間>-cwa-hazards.json`，第一次實跑後要對一次（2026-10-19 06:56Z 第一報對過，格式相符）
- 局屬站觀測（HD13）用 `O-A0003-001`「氣象觀測站-10分鐘綜觀氣象資料」（舊名「現在天氣觀測報告」），參數
  `StationId=467110,467990`；欄位照 [平台 API 文件](https://opendata.cwa.gov.tw/apidoc/v1)（swagger 的
  `WeatherElement` 列舉：`Weather`、`VisibilityDescription`、`WindDirection`、`WindSpeed`、`GustInfo`…）與
  [資料標準說明文件 V1.05](https://opendata.cwa.gov.tw/opendatadoc/Observation/O-A0003-001.pdf)（路徑
  `//Station/WeatherElement/...`、缺測 `-99`／`X`、風向不定 `990`、天氣描述附表 2）寫。沒有授權碼沒辦法實抓，
  原始回應存 `history/raw/<日期>/<時間>-cwa-obs.json`，合併後第一報要對一次

HD14 新模式（2026-10-20 實測，細節在 `src/hongthai/sources/aifs.py`、`aigfs.py` 開頭）：
- AIFS Single：`ecmwf-opendata` 的 `Client(model="aifs-single")`，`stream="oper"`、`type="fc"`、0.25°；
  一天 4 報、每 6 小時一個步長；`tp`／`sf` 從起報累積、**單位是 mm（kg m⁻²），不是 HRES 的 m**。沒有陣風、
  降水型態、能見度。AWS 鏡像 `ecmwf-forecasts` 有 `aifs-single/` 路徑，鏡像順序同 HRES。21 個步長加第一格
  的開始步長 66 MB，從 ECMWF 入口 55 秒（AWS 當時連 `.index` 都回 503 Slow Down）
- AIGFS：`aigfs.<YYYYMMDD>/<HH>/model/atmos/grib2/aigfs.t<HH>z.sfc.f<FFF>.grib2`（地面檔，約 8 MB；旁邊有
  `.idx`，另有約 70 MB 的氣壓層檔 `pres` 不用）；一天 4 報、每 6 小時到 384 小時，起報後約 7.5 小時出齊。
  用 `.idx` 的 byte 範圍只抓 `UGRD`／`VGRD:10 m`、`TMP:2 m`、`APCP` 一筆（有「前 6 小時」那桶就用它，沒有
  就用從起報累積的那筆相減），每個步長 3 個 `Range` 請求、約 2.4 MB，21 個步長 51 MB、38 秒。NOMADS
  `/pub/data/nccf/com/aigfs/prod/` 有同樣的檔，但沒有 `filter_aigfs` 裁區 CGI，**不做備援**（AWS 失敗就沿用）

HD16 Open-Meteo（2026-10-20 11:17Z 實抓，細節在 `src/hongthai/sources/openmeteo.py` 開頭）：
- 兩個請求、各一次帶 51 個機場的座標：預報 `api.open-meteo.com/v1/forecast?models=icon_global,jma_gsm&hourly=
  wind_speed_10m,wind_direction_10m,wind_gusts_10m,precipitation,snowfall,visibility,weather_code&forecast_days=6
  &wind_speed_unit=kn&timezone=UTC` 632,290 bytes、1.0 秒；系集 `ensemble-api.open-meteo.com/v1/ensemble?models=
  google_weathernext2_ensemble&hourly=wind_speed_10m&forecast_days=6&temporal_resolution=native
  &wind_speed_unit=kn&timezone=UTC`：實抓時照提示詞多帶 `wind_direction_10m,precipitation`，1,635,607 bytes、
  1.2 秒；只要風速約 561 KB。**系集只要風速**：WN2 只投風的高、不算側風、不投雨，而且 3 個變數會超過每分鐘上限
- **加權呼叫次數**（文件 API 頁「equivalent to N calls」的公式：`max(1, 變數數 × 模式數（系集是成員數）÷ 10 ×
  max(1, 天數 ÷ 14)) × 座標數`）：預報 1.4 × 51 ＝ 71.4、系集 6.4 × 51 ＝ 326.4，**一報 397.8、一天 4 報約
  1,591**（每月約 4.9 萬）。免費版上限是**每分鐘 600**、每小時 5,000、每日 10,000、每月 300,000（使用條款）：
  照提示詞抓系集 3 個變數是 19.2 × 51 ＝ 979.2，一個請求就超過每分鐘 600，所以只抓風速。沒超過提示詞的
  每日 5,000，WeatherNext 2 也是 51 個機場全抓
- JMA GSM 沒有陣風（`wind_gusts_10m_jma_gsm` 全是 `null`、單位 `undefined`）→ 估算；ICON global、JMA GSM 都沒有
  能見度。系集的成員 0 是不帶後綴的 `wind_speed_10m`，其他 `_member01`…`_member63`
- 起報時間用 metadata API（`api.open-meteo.com/data/dwd_icon/static/meta.json`、`…/jma_gsm/…`、
  `ensemble-api.open-meteo.com/data/google_weathernext2_ensemble/static/meta.json` 的
  `last_run_initialisation_time`）。11:21Z 查：ICON 06Z（09:26Z 上 API）、WeatherNext 2 00Z（11:02Z 上 API）
- 雲端開發機連 Open-Meteo 時 TLS 建立約四成在 30 秒後被斷（curl、`requests` 都一樣、和請求大小無關，像是開發機
  出口的問題；當天測試時也照提示詞的 3 變數系集打了幾次，每次 979 次加權，超過每分鐘上限）。Actions 上沒試過，
  **合併後前幾報要看 `sources.openmeteo`**：常常 `network` 失敗的話，考慮只對連線失敗（請求沒到 API、不算次數）
  重試一次

NWS（關島、帛琉，HD3，2026-10-18 查）：
- 關島：`/zones?area=GU` 有 `GUZ001`（public／fire，名稱 Guam，`cwa` 是 GUM＝NWS 關島分處）；PGUM 的
  `/points/13.485,144.7973` 的 `forecastZone` 是 `GUZ001`。`/alerts?zone=GUZ001` 查得到超強颱風 Champi（29W）
  期間的 `Typhoon Watch`（10-15 起）與 `Typhoon Warning`（10-16 發布、10-18 17:51 ChST 解除，每次更新
  `messageType` 是 `Update`、解除是 `Cancel`），格式和美國本土一樣 → **接了**（`src/hongthai/sources/nws.py`）
- 帛琉：`/zones?area=PW` 有 `PWZ001`–`PWZ008`（PTRO 在 Airai＝`PWZ003`；`cwa` 是 `PQW`，但 `/offices/PQW`
  回 404，`/points/7.367,134.5441` 回 500；zone 2026-04-16 才生效）。`/alerts?area=PW` 自 2026-04-01 起
  一筆警報都沒有（`/alerts/active?zone=PWZ003` 是空的 FeatureCollection），Champi 期間也沒有；TC 本地聲明
  （HLS）的地點只有 `PQ2`（關島與北馬里亞納）。看不出 NWS 會在這個端點發帛琉的颱風警報 → **先不接**
  （`warningSources: []`，`official.warnings: false`），之後看到帛琉的警報再接（加 `nwsZone: "PWZ003"`）

JMA（日本與沖繩，HD9，2026-10-20 實抓；細節在 `src/hongthai/sources/jma.py` 開頭）：
- 舊的 `bosai/warning/data/warning/<office>.json` 停在 2026-05-28（`Last-Modified` 同一天）：JMA 那天換成新的
  防災氣象資訊（令和 8 年，多了「危險警報」），網頁改讀 `bosai/warning/data/r8/<office>.json`。新格式最上層
  是 list，每筆是一種電文（`dataTypeCode` VPWW55 大雨、56 土砂災害、57 高潮、58 風、59 波浪、61 雷・濃霧等；
  雪的那種 10 月還沒出現，所以不看 `dataTypeCode`，每種電文取最新一報再合起來找），每筆
  `warning.class20Items[]` 是 `{"areaCode": <市町村代碼>, "kinds": [{"code", "status"}]}`
- 警報種類代碼照 JMA 警報頁 JS 的對照表（`elem`／`level`）：大雪 注意報 `12`、警報 `06`、特別警報 `36`；
  暴風雪 注意報（風雪）`13`、警報 `02`、特別警報 `32`；暴風 `05`／`35`、大雨特別警報 `33`。提示詞印象中的
  「大雪特別警報 33、暴風雪警報 05」是舊制的記錯，以這份為準
- `status` 有 `発表`、`継続`、`解除`、`発表警報・注意報はなし`；不是後兩種就算生效中。`infoType` 是 `取消` 的那筆不算
- 2026-10-20 10Z 一次實抓 11 個 office 共 8.6 秒，沒有任何機場有大雪或暴風雪警報（千歲市當時是濃霧注意報）

航班：澳門機場官網只有伺服器端產生的 HTML（不爬），改用 data.gov.mo 上民航局的開放 API；它要一個
`Authorization: APPCODE …` 標頭，值是平台發給所有匿名使用者的公開共用碼，程式每次從資料集說明 API 取，
不寫進程式也不存檔。細節在 `src/hongthai/sources/flights.py` 開頭。

### 跑道方位

現有五個機場（`runwaySource: "aip"`）2026-10-18 查各地 AIP 的 AD 2.12（跑道物理特性）。METAR／TAF 與模式的
風向都是真北，所以 `headings` 用真北：

| 機場 | 跑道 | 真北（`headings`） | 磁方位（`magnetic`） | 來源 |
| --- | --- | --- | --- | --- |
| 桃園 RCTP | 05L/23R、05R/23L | 049.1° / 229.1° | 054° / 234°（真北＋磁偏 5°W 換算） | 臺灣 AIP AIRAC AMDT 04/26（2026-10-01 生效）AD 2 RCTP，[ais.caa.gov.tw](https://ais.caa.gov.tw/) |
| 松山 RCSS | 10/28 | 092.2° / 272.2° | 097° / 277°（磁偏 5°W 換算） | 同上 AD 2 RCSS |
| 高雄 RCKH | 09/27 | 091.9° / 271.9° | 096° / 276°（磁偏 4°W 換算） | 同上 AD 2 RCKH |
| 香港 VHHH | 07L/25R、07C/25C、07R/25L | 070.9° / 250.9° | 073.9° / 253.9°（AIP 原值） | 香港 eAIP AMDT 10/26（2026-10-01 生效）[VH-AD-2-VHHH](https://www.ais.gov.hk/) |
| 澳門 VMMC | 16/34 | 161.2° / 341.2°（AIP 只給整數 161°，小數由跑道頭座標算） | 164° / 344°（AIP 原值） | 澳門 AIP Part 3（AD），[aacm.gov.mo](https://www.aacm.gov.mo/en/industry-page/DataCompilation/AIP) |

台灣 AIP 只列真北方位；同方位的平行跑道記一組。

H9 的其餘 36 個（`runwaySource: "ourairports"`；石垣 HD3 改成 `"computed"`）取自 OurAirports `runways.csv`（2026-10-18 下載）的
`le_heading_degT`／`he_heading_degT`（真北），抽查上海浦東、羽田、仁川、那霸、台中五個的跑道號碼和
維基百科一致。整理規則：
- 關閉的跑道（`closed=1`）不要；比該機場最長跑道短一半以上的不要（仙台 12/30，1,200 m，客機不用）
- 方位差 1° 以內的平行跑道記一組（例如浦東 16L/34R、16R/34L、17L/35R、17R/35L 都是 162°）
- 沒有方位、但有兩端跑道頭座標的，用座標算真北方位（溫州 03/21、廣州 01L/19R、珠海 05/23、海口 10/28、
  福岡 16R/34L）；兩端方位對不起來的也改用座標（羽田 05/23 寫 57°／223°，座標算是 042.4°）
- 方位與座標都沒有的跑道不要（浦東 15/33，其他跑道還有）；整個機場都沒有的 `runways: []`（H9 時的石垣，
  HD3 補上了，見下面）

HD3 的十個（2026-10-18 18Z 下載的 OurAirports）照同樣的規則：
- 平行跑道併組：河內 11L/29R、11R/29L（107°）、胡志明 07L/25R、07R/25L（069°）、峴港 17L/35R、17R/35L（172°）、
  富國島 10L/28R、10R/28L（096°）、關島 06L/24R、06R/24L（065°）、宿霧 04L/22R（044°）、04R/22L（045°）記一組，
  方位取最長那條（04R/22L）的；芽莊 02R/20L 沒有方位，用跑道頭座標算是 018.7°，和 02L/20R 的 019° 差不到
  1°，併成一組 019°
- 馬尼拉 06/24（060.3°，3,737 m）與 13/31（134.8°，2,258 m）是兩組（13/31 比最長跑道的一半長）
- 克拉克 02L/20R 關閉（`closed=1`），只留 02R/20L（021.1°）；帛琉只有一條 09/27（091°）
- 有方位的也都用跑道頭座標驗算過，差都在 1° 以內

石垣（`runwaySource: "computed"`，HD3）：新石垣機場只有一條跑道 04/22（2,000 m）。日本 AIP（AIS Japan）要註冊
登入，沙盒連不上（`aisjapan.mlit.go.jp` 被擋），所以用 OpenStreetMap 跑道 way 114511749（2026-03-23 版）兩端
節點的座標算：南端 24.3891577°N 124.2393589°E、北端 24.4037497°N 124.2508788°E，兩端距離 1,998 m（和跑道長
2,000 m 吻合），大圓起始方位 04 向 035.7°、22 向 215.7°（真北）。磁方位沒有官方數字，省略：

| 機場 | 跑道 | 真北（`headings`） | 磁方位（`magnetic`） | 來源 |
| --- | --- | --- | --- | --- |
| 石垣 ROIG | 04/22 | 035.7° / 215.7° | （省略） | OpenStreetMap way 114511749 兩端座標算（大圓起始方位，兩個方向各算一次） |

程式碼以 [MIT](LICENSE) 授權。
