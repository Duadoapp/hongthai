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
- `smg_{c,e}_typhoon_none.xml`：SMG 熱帶氣旋信號 XML（當時沒有信號）
- `tsa_intl_departure.json`、`khh_intdep.json`、`mfm_departure_en.json`：松山、高雄、澳門航班（各前 5 筆）
- `hkg_arrival.json`：香港機管局航班資訊（每天只留 3 筆）
- `tpe_flights_big5.txt`：桃園機場即時航班（Big5，前 5 行）

真實內容、轉回 XML 格式：
- `smg_c_typhoon_{sig3,sig1_pending3,cancel}.xml`：2026 年颱風紅霞（2612）期間 SMG 的真實報告
  （3 號風球生效、1 號生效並預告改發 3 號、取消），取自公開存檔
  [Mark-MTR/weather-warnings-archive](https://github.com/Mark-MTR/weather-warnings-archive)（MIT；存的是 SMG 網站後端
  `new-api.smg.gov.mo` 把同一份 XML 轉成的 JSON），照 `c_typhoon.xml` 的元素順序轉回 XML。8 號以上沒有真實樣本，
  測試裡把 3 號的 `Inforce` 改成 `8ne`

合成樣本（目前沒有颱風，照真實格式改出來）：
- `hko_warnsum_tc8ne_{tc,en,sc}.json`：依天文台 API 文件的回應範例格式，8 號東北信號
- `cwa_w-c0034-001_land.json`、`cwa_w-c0034-001_sea.json`：把真實的解除警報改成生效中的
  海上陸上／海上颱風警報
