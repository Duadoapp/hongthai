"""航班狀態快照（只存檔、不算等級，之後回測用）。抓不到就跳過。

- 香港機管局（data.gov.hk「航班資訊」）：
  `https://www.hongkongairport.com/flightinfo-rest/rest/flights/past?date=YYYY-MM-DD&lang=en&cargo=false&arrival=false|true`
  回傳 `[{"date", "arrival", "cargo", "list": [{"time", "flight": [...], "status", ...}]}]`，
  會帶前一天與當天兩組。
- 桃園機場（data.gov.tw 資料集 26194「桃園國際機場即時航班」）：資源只有 CSV，沒有 JSON；
  實際檔案是 `https://www.taoyuan-airport.com/uploads/flightx/a_flight_v4.txt`（Big5 編碼、
  逗號分隔、沒有標題列，每 5 分鐘更新）。存成 JSON 時欄位名稱照資料集說明的順序。
- 松山機場（data.gov.tw 資料集 37242／37248／37317／37319，國際／國內 × 出發／抵達）：
  `https://www.tsa.gov.tw/api/publicDataArea/GetFormaterData?id=<uuid>`，UTF-8 JSON 陣列，只有當天，
  約每分鐘更新（實測 2026-10-18 各 37–52 筆）
- 高雄機場（data.gov.tw 資料集 33656／33655／33651／33649）：
  `https://www.kia.gov.tw/Announce/NewsArea/InstantSchedule_{INTDEP|INTARR|DOMDEP|DOMARR}.json`，
  UTF-8 JSON 陣列，只有當天、沒有日期欄位，約每 5 分鐘更新
- 澳門機場：機場網站只有伺服器端產生的 HTML（不爬）；改用澳門政府數據開放平台（data.gov.mo）
  民航局的「航班資訊」開放 API：`https://aacm.apigateway.data.gov.mo/api/open/list{Arrival|Departure}Flight/ENGLISH`。
  閘道要 `Authorization: APPCODE <appCode>` 標頭，appCode 是平台給所有匿名使用者的公開共用碼，
  每次執行從資料集說明 API（`https://api.data.gov.mo/datadir/detail/<資料集 id>` 的 `data.appCode`）
  取得，不寫進程式、不存進快照。回傳是 JSON 陣列（文件範例包成 `{"data": "<字串>"}`，兩種都接）

存成 `history/flights/<YYYY-MM-DD>/<airport>-<HHMM>.json.gz`（UTC 日期與時間；gzip 是因為
桃園一份就 500 KB 以上，一年下來太大）。
"""

from __future__ import annotations

import gzip
import json
import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from ..timeutil import iso
from . import NonStrictTLSAdapter, SourceError, http_get

log = logging.getLogger("hongthai")

HKG_URL = "https://www.hongkongairport.com/flightinfo-rest/rest/flights/past"
TPE_URL = "https://www.taoyuan-airport.com/uploads/flightx/a_flight_v4.txt"
TSA_URL = "https://www.tsa.gov.tw/api/publicDataArea/GetFormaterData"
TSA_FEEDS = {  # data.gov.tw 資料集 37242／37248／37317／37319
    "intlDeparture": "42879f51-f47f-4d26-8b2b-5535c652cbde",
    "intlArrival": "7dc1379a-9485-4491-866d-fc4f9590ffcf",
    "domDeparture": "c0f7d5b4-ba73-46d2-8485-6595c64c4e17",
    "domArrival": "3057d52f-7a71-49e1-a0d4-87ffa3449a6a",
}
KHH_URL = "https://www.kia.gov.tw/Announce/NewsArea/InstantSchedule_{}.json"
KHH_FEEDS = {
    "intlDeparture": "INTDEP",
    "intlArrival": "INTARR",
    "domDeparture": "DOMDEP",
    "domArrival": "DOMARR",
}
MFM_URL = "https://aacm.apigateway.data.gov.mo/api/open/list{}Flight/ENGLISH"
MFM_DATASET = "f910cf2e-5e30-45c3-9e62-3eb6bf912db3"  # 民航局「離港航班資訊（英文）」
MFM_DETAIL_URL = "https://api.data.gov.mo/datadir/detail/"
TPE_COLUMNS = [
    "terminal",
    "kind",  # A＝抵達、D＝出發
    "airlineCode",
    "airlineName",
    "flightNo",
    "gate",
    "scheduledDate",
    "scheduledTime",
    "estimatedDate",
    "estimatedTime",
    "airportCode",
    "airportEn",
    "airportZh",
    "status",
    "aircraft",
]


class FlightsError(SourceError):
    pass


def parse_tpe(raw: bytes) -> list[dict[str, object]]:
    text = raw.decode("big5", errors="replace")
    rows = []
    for line in text.splitlines():
        if not line.strip():
            continue
        cells = [c.strip() for c in line.split(",")]
        row: dict[str, object] = dict(zip(TPE_COLUMNS, cells, strict=False))
        if len(cells) > len(TPE_COLUMNS):
            row["extra"] = cells[len(TPE_COLUMNS) :]
        rows.append(row)
    return rows


def fetch_hkg(now: datetime) -> dict[str, object]:
    date = now.astimezone(ZoneInfo("Asia/Hong_Kong")).strftime("%Y-%m-%d")
    out: dict[str, object] = {}
    for arrival in ("false", "true"):
        params = {"date": date, "lang": "en", "cargo": "false", "arrival": arrival}
        r = http_get(HKG_URL, params=params, retries=2, error=FlightsError)
        out["arrival" if arrival == "true" else "departure"] = r.json()
    return out


def fetch_tpe() -> dict[str, object]:
    r = http_get(TPE_URL, retries=2, error=FlightsError)
    return {"columns": TPE_COLUMNS, "rows": parse_tpe(r.content)}


def _json(r) -> object:
    try:
        return r.json()
    except ValueError as e:
        raise FlightsError(f"{r.url} 回傳不是 JSON", "bad_json") from e


def fetch_tsa() -> dict[str, object]:
    return {
        name: _json(http_get(TSA_URL, params={"id": uuid}, retries=3, error=FlightsError))
        for name, uuid in TSA_FEEDS.items()
    }


def fetch_khh() -> dict[str, object]:
    # kia.gov.tw 的憑證和氣象署一樣缺 Subject Key Identifier，Python 3.13 起的 strict 模式會擋
    session = requests.Session()
    session.mount("https://www.kia.gov.tw/", NonStrictTLSAdapter())
    return {
        name: _json(http_get(KHH_URL.format(code), session=session, retries=3, error=FlightsError))
        for name, code in KHH_FEEDS.items()
    }


def parse_mfm(data: object) -> list:
    """澳門民航局 API：實際回 JSON 陣列；文件範例是 `{"data": "<JSON 字串>"}`。"""
    if isinstance(data, dict) and "data" in data:
        data = data["data"]
        if isinstance(data, str):
            data = json.loads(data)
    if not isinstance(data, list):
        raise FlightsError("澳門航班回傳格式不對", "bad_format")
    return data


def mfm_app_code() -> str:
    r = http_get(MFM_DETAIL_URL + MFM_DATASET, retries=2, error=FlightsError)
    code = ((_json(r) or {}).get("data") or {}).get("appCode")
    if not code:
        raise FlightsError("data.gov.mo 沒有給 appCode", "no_app_code")
    return code


def fetch_mfm() -> dict[str, object]:
    headers = {"Authorization": f"APPCODE {mfm_app_code()}"}
    out: dict[str, object] = {}
    for name, kind in (("departure", "Departure"), ("arrival", "Arrival")):
        r = http_get(MFM_URL.format(kind), headers=headers, retries=2, error=FlightsError)
        out[name] = parse_mfm(_json(r))
    return out


def write_snapshot(root: Path, airport: str, now: datetime, payload: dict) -> Path:
    path = root / "flights" / f"{now:%Y-%m-%d}" / f"{airport}-{now:%H%M}.json.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {"airport": airport, "fetchedAt": iso(now), **payload}
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(body, f, ensure_ascii=False, separators=(",", ":"))
    return path


def fetch_and_store(history_dir: Path, now: datetime) -> dict[str, str | None]:
    """每個機場各抓一次；回傳 `{機場: None（成功）或錯誤代碼}`。"""
    result: dict[str, str | None] = {}
    sources = (
        ("VHHH", lambda: fetch_hkg(now)),
        ("RCTP", fetch_tpe),
        ("RCSS", fetch_tsa),
        ("RCKH", fetch_khh),
        ("VMMC", fetch_mfm),
    )
    for airport, fn in sources:
        try:
            path = write_snapshot(history_dir, airport, now, fn())
            log.info("航班快照 %s → %s（%d bytes）", airport, path, path.stat().st_size)
            result[airport] = None
        except (SourceError, ValueError, OSError) as e:
            log.warning("航班快照 %s 跳過：%s", airport, e)
            result[airport] = getattr(e, "code", e.__class__.__name__)
    return result
