# tests/fixtures

測試用的小樣本。

真實回應（2026-10-18 抓的，去掉多餘欄位）：
- `taf.json`、`metar.json`：AviationWeather.gov Data API
- `hko_warnsum_fire_{tc,en,sc}.json`：天文台 warnsum（當時只有黃色火災危險警告）
- `cwa_w-c0034-001_cancel.json`：氣象署 W-C0034-001（最近一筆是「解除颱風警報」）
- `gfs_subregion_f006.grb2`：NOMADS GRIB filter 的 GFS 地面陣風，桃園＋香港小範圍
- `ecmwf_oper_subregion.grib2`、`ecmwf_ep_subregion.grib2`：ECMWF 開放資料的 HRES 陣風
  （`10fg`／`10fg3`）與系集機率（`10fgg10/15/25`），從全球檔裁成 22–26°N、113–122°E
- `hkg_arrival.json`：香港機管局航班資訊（每天只留 3 筆）
- `tpe_flights_big5.txt`：桃園機場即時航班（Big5，前 5 行）

合成樣本（目前沒有颱風，照真實格式改出來）：
- `hko_warnsum_tc8ne_{tc,en,sc}.json`：依天文台 API 文件的回應範例格式，8 號東北信號
- `cwa_w-c0034-001_land.json`、`cwa_w-c0034-001_sea.json`：把真實的解除警報改成生效中的
  海上陸上／海上颱風警報
