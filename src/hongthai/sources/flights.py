"""航班狀態（不算等級，之後回測用）。抓不到就跳過。

- 香港機管局（data.gov.hk「航班資訊」）：
  `https://www.hongkongairport.com/flightinfo-rest/rest/flights/past?date=YYYY-MM-DD&lang=en&cargo=false&arrival=false|true`
  回傳 `[{"date", "arrival", "cargo", "list": [{"time", "flight": [...], "status", ...}]}]`；
  `date` 那天的一組是整天的表，另外可能帶前後一天還沒結束的幾班。香港當地的昨天和今天各查一次
  （晚上的班機在隔天的跑次才有最後的狀態；昨天的抓不到就只用今天的），兩次的組接在一起，
  重複的班機由統計那邊去重
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
  取得，不寫進程式、不存檔。回傳是 JSON 陣列（文件範例包成 `{"data": "<字串>"}`，兩種都接）

原始資料不存檔：`cancellations.py` 算成每 6 小時格的取消／延誤統計，存 `history/cancellations/`。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests

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


@dataclass
class FlightsData:
    snapshots: dict[str, dict]  # 機場 → 該機場 `fetch_*` 的回傳
    errors: dict[str, str]  # 抓不到的機場 → 錯誤代碼


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


def fetch_hkg_groups(day: date, arrival: bool) -> list:
    """香港 `past?date=` 一天、一個方向的組（HD31 的 backfill 也用）。"""
    params = {
        "date": f"{day:%Y-%m-%d}",
        "lang": "en",
        "cargo": "false",
        "arrival": "true" if arrival else "false",
    }
    groups = _json(http_get(HKG_URL, params=params, retries=2, error=FlightsError))
    if not isinstance(groups, list):
        raise FlightsError("香港航班回傳格式不對", "bad_format")
    return groups


def fetch_hkg(now: datetime) -> dict[str, list]:
    today = now.astimezone(ZoneInfo("Asia/Hong_Kong")).date()
    out: dict[str, list] = {"departure": [], "arrival": []}
    for day in (today - timedelta(days=1), today):
        for arrival in ("false", "true"):
            try:
                groups = fetch_hkg_groups(day, arrival == "true")
            except FlightsError as e:
                if day == today:
                    raise
                log.warning("香港航班 %s 抓不到，只用今天的：%s", day, e)
                continue
            out["arrival" if arrival == "true" else "departure"].extend(groups)
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


def fetch(now: datetime) -> FlightsData:
    """每個機場各抓一次；抓不到的記在 `errors`，其他照回。"""
    data = FlightsData({}, {})
    sources = (
        ("VHHH", lambda: fetch_hkg(now)),
        ("RCTP", fetch_tpe),
        ("RCSS", fetch_tsa),
        ("RCKH", fetch_khh),
        ("VMMC", fetch_mfm),
    )
    for airport, fn in sources:
        try:
            data.snapshots[airport] = fn()
            log.info("航班 %s 抓到了", airport)
        except (SourceError, ValueError, OSError) as e:
            log.warning("航班 %s 跳過：%s", airport, e)
            data.errors[airport] = getattr(e, "code", None) or e.__class__.__name__
    return data
