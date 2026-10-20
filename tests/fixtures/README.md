# tests/fixtures

測試用的小樣本。

真實回應（2026-10-18 抓的，去掉多餘欄位）：
- `taf.json`、`metar.json`：AviationWeather.gov Data API
- `hko_warnsum_fire_{tc,en,sc}.json`：天文台 warnsum（當時只有黃色火災危險警告）
- `cwa_w-c0034-001_cancel.json`：氣象署 W-C0034-001（最近一筆是「解除颱風警報」）
- `gfs_tw_f006.grb2`、`gfs_hkmo_f006.grb2`：NOMADS GRIB filter 的 GFS 地面陣風＋10 米風（00Z f006），
  台灣（桃園、松山、高雄）與港澳兩個框
- `ecmwf_oper_subregion.grib2`、`ecmwf_ep_subregion.grib2`：ECMWF 開放資料的 HRES 陣風
  （`10fg`／`10fg3`）＋10 米風（`10u`／`10v`，同一報 2026-10-17 18Z、同樣步長，後加）與系集機率
  （`10fgg10/15/25`），從全球檔裁成 22–26°N、113–122°E
- `taf.json`、`metar.json` 後面三筆（RCSS、RCKH、VMMC）是 2026-10-18 04:50Z 抓的
- `taf.json` 再後面四筆（ZSPD、ROAH、RJTT、RKSI）與 `metar.json` 再後面五筆（同四站＋ROMY，宮古只有 METAR）
  是 H9 一次請求 41 站時（2026-10-18 17:1xZ）抓的；ZSPD 是 `MPS` 的 TAF
- `aifs_pus_subregion.grib2`（HD14）：ECMWF AIFS Single 2026-10-19 18Z 步長 6／12／18 的 `10u`、`10v`、`2t`、
  `tp`、`sf`；`aigfs_pus_f006.grib2`、`aigfs_pus_f012.grib2`：NOAA AIGFS 2026-10-19 12Z 地面檔的 `UGRD`／`VGRD`
  （10 米）、`TMP`（2 米）與兩筆 `APCP`（f006 都是 `0-6 hour acc`；f012 是 `6-12` 與 `0-12`）。都是全球檔
  用 eccodes 逐筆裁成 33.5–36.5°N、127.5–130.5°E（釜山附近，那時有雨）
- `gfs_all_f120.grb2`：NOMADS 一個框（HD3 換成 51 個機場的框：6.37–43.77°N、102.99–145.80°E，2026-10-18 12Z
  f120，GUST＋10 米風，113 KB；H9 原本是 41 個機場的框、約 64 KB），51 個機場都在框內
- `nws_alerts_active_guz001_none.json`：NWS `/alerts/active?zone=GUZ001`（2026-10-18 17:53Z，關島當時只有
  Wind Advisory、Flood Watch、Rip Current Statement、High Surf Advisory，沒有颱風的；`description`／`instruction`
  截到 300 字、去掉 `expiredReferences`）
- `smg_{c,e}_typhoon_none.xml`：SMG 熱帶氣旋信號 XML（當時沒有信號）
- `tsa_intl_departure.json`、`khh_intdep.json`、`mfm_departure_en.json`：松山、高雄、澳門航班（各前 5 筆）
- `hkg_arrival.json`：香港機管局航班資訊（每天只留 3 筆）
- `tpe_flights_big5.txt`：桃園機場即時航班（Big5，前 5 行）
- 上面五個航班檔後面加的幾筆（H6，測取消／延誤統計）是 2026-10-18 08:5xZ 抓的真實資料：
  松山 3 筆「延誤Delayed」共掛（`Master` 1／2／3）；高雄 3 筆（「延遲」兩筆、「登機」但晚 61 分一筆）；
  澳門 6 筆（`CANCELLED`、`DELAY UNTIL …`、`RESCHEDULE …`、`0`、`CHECK-IN … OPEN AT …`）；
  香港 10/18 那組加 2 筆（`Cancelled`、`Est at 00:30 (19/10/2026)`）；桃園 9 行（延遲共掛、晚 90 分、
  取消共掛、出發取消、晚 55 分的三個班號共掛）

真實內容、轉回 XML 格式：
- `smg_c_typhoon_{sig3,sig1_pending3,cancel}.xml`：2026 年颱風紅霞（2612）期間 SMG 的真實報告
  （3 號風球生效、1 號生效並預告改發 3 號、取消），取自公開存檔
  [Mark-MTR/weather-warnings-archive](https://github.com/Mark-MTR/weather-warnings-archive)（MIT；存的是 SMG 網站後端
  `new-api.smg.gov.mo` 把同一份 XML 轉成的 JSON），照 `c_typhoon.xml` 的元素順序轉回 XML。8 號以上沒有真實樣本，
  測試裡把 3 號的 `Inforce` 改成 `8ne`

真實警報、組成 active 的格式：
- `nws_alerts_active_guz001_typhoon.json`：超強颱風 Champi（29W）期間 `/alerts?zone=GUZ001` 的三則真實警報——
  Typhoon Warning 更新（2026-10-18 15:01 ChST）、Typhoon Watch 更新（10-16 08:50 ChST，涵蓋 GUZ001 與北馬
  MPZ001–003）、Typhoon Warning 解除（10-18 17:51 ChST，`messageType: Cancel`）——加上上面那份的 Flood Watch，
  包成 `/alerts/active` 的 FeatureCollection（同時生效的組合是拼的；欄位同上截短）

合成樣本（目前沒有颱風，照真實格式改出來）：
- `hko_warnsum_tc8ne_{tc,en,sc}.json`：依天文台 API 文件的回應範例格式，8 號東北信號
- `cwa_w-c0034-001_land.json`、`cwa_w-c0034-001_sea.json`：把真實的解除警報改成生效中的
  海上陸上／海上颱風警報

HD8（新天氣種類）：
- `taf_metar_wx_20261018.json`：`data` 分支的真實快照片段（只留解析用到的欄位）——TAF VVTS（2026-10-18 18:15Z，
  `TEMPO … 1200 +TSRA BKN015`）、RCTP（04:22Z，TEMPO 只有風、`visib` 是空字串）；METAR RJFK（22:30Z，
  `9999 BCFG FEW001`）、PGUM（18:15Z，`10SM BKN017 OVC022`）
- `cwa_w-c0033-001_heavy_rain.json`：**照平台文件組的格式，不是真實回應**（沒有授權碼抓不到）——金門縣大豪雨
  ＋濃霧、連江縣豪雨、高雄市超大豪雨（`hazards` 是物件）、臺北市已結束的大豪雨、臺中市沒有特報

HD13（金門、馬祖的霧）：
- `cwa_w-c0033-001_dense_fog.json`：`data` 分支 `history/raw/2026-10-19/0656Z-cwa-hazards.json` 的**真實回應**，
  只把金門縣的 `hazards` 換成一則濃霧特報（台灣時間 10/18 15:00–10/20 12:00；當時沒有濃霧特報）
- `cwa_o-a0003-001_obs.json`：**照平台 API 文件與資料標準說明文件 V1.05 組的格式，不是真實回應**（沒有授權碼
  抓不到）——金門 467110「陰有霧」能見度 `0.3`、風 090° 1.5 m/s、陣風 3.2 m/s（20 分鐘前）；馬祖 467990
  能見度 `-99`、風向 990、風速 `X`、陣風 12.0 m/s（13 小時前，不算）；臺北 466920（沒要的站，會被濾掉）

事件保存（HD20，2026-10-20 06Z 前後抓的真實回應，去掉沒用的欄位）：
- `events_metar_hours2.json`：AviationWeather `metar?…&hours=2` 25 站裡挑 RCTP、ROMY、VHHH、RJFF、ZSPD 的
  10 筆（半小時一報的站有兩三筆；RJFF 05:00Z 有陣風）
- `jma_targettc.json`、`jma_tc2636_specifications.json`：JMA bosai 的 `targetTc.json` 與 29W（`TC2636`）
  的 `specifications.json`（留 title、實況與前兩個預報點；拿掉 `galeWarning`、`stormWarning`、
  `probabilityCircleRadius`、`position.dm`）
- `jtwc_wp2926.tcw`：JTWC 29W 第 23 報（`WTPN52 PGTW 200300`，CRLF；拿掉風半徑的 `QUADRANT` 行，
  結尾的歷史路徑只留最後 3 行）

颱風路徑（HD21，2026-10-20 08Z 前後抓的 00Z 那報真實檔，用 eccodes 裁小）：
- `ecmwf_tf_oper_2026102000.bufr`：ECMWF 開放資料 `20261020000000-360h-oper-tf.bufr`（HRES 路徑產品，
  原檔 42,726 bytes、15 個 storm）只留 `36W CHAMPI`（29W）與 `21E TRUDY`（東太平洋）兩個訊息
- `ecmwf_tf_enfo_2026102000.bufr`：同一報的 `…-enfo-tf.bufr`（系集，原檔 1,252,262 bytes、56 個 storm）
  只留 `36W CHAMPI` 的成員 40–51（12 個，51 是控制報）與 `70W`（新生的擾動，沒有觀測位置）的成員 1–3
  （`extractSubsetIntervalStart`／`End`＋`doExtractSubsets`）

JMA 大雪警報（HD9）：
- `jma_r8_016000_none.json`、`jma_r8_474000_none.json`：JMA `bosai/warning/data/r8/016000.json`（石狩・空知・後志
  地方，新千歲的千歳市在裡面）與 `474000.json`（八重山地方，石垣）2026-10-20 10Z 的**真實回應**，原樣沒刪；當時
  沒有大雪、暴風雪警報（千歳市是濃霧注意報 `20`）
- `jma_r8_016000_snow.json`：拿上面那份改的**合成樣本**——風的電文（VPWW58）千歳市改暴風雪警報 `02`、札幌市改風雪
  注意報 `13`，另加三筆雪的電文（VPWW60，2026-12-10）：舊的那筆（札幌、惠庭大雪警報 `06`，千歳大雪注意報 `12`）、
  新的那筆（札幌大雪特別警報 `36`、千歳大雪警報 `06`、江別大雪＋風雪注意報、惠庭解除）、`infoType: 取消` 的那筆
  （千歳解除，不算）

HD16（Open-Meteo）：
- `openmeteo_forecast_3.json`：`api.open-meteo.com/v1/forecast` 一次 51 個機場的真實回應（2026-10-20 11:17Z，
  `models=icon_global,jma_gsm`、7 個逐時變數、`forecast_days=6`、`wind_speed_unit=kn`、`timezone=UTC`），
  只留桃園、石垣（29W 經過，ICON 陣風到 148.5 節）、新千歲三筆（照這個順序）；JMA 的陣風與兩個模式的
  能見度全是 null
- `openmeteo_ensemble_3x8.json`：`ensemble-api.open-meteo.com/v1/ensemble` 同時間的真實回應
  （`models=google_weathernext2_ensemble`、`temporal_resolution=native`），同樣三個機場、只留成員 0
  （不帶後綴的鍵）到 `member07` 共 8 個成員
