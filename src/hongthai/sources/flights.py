"""航班狀態快照（只存檔、不算等級，之後回測用）。抓不到就跳過。

- 香港機管局（data.gov.hk「航班資訊」）：
  `https://www.hongkongairport.com/flightinfo-rest/rest/flights/past?date=YYYY-MM-DD&lang=en&cargo=false&arrival=false|true`
  回傳 `[{"date", "arrival", "cargo", "list": [{"time", "flight": [...], "status", ...}]}]`，
  會帶前一天與當天兩組。
- 桃園機場（data.gov.tw 資料集 26194「桃園國際機場即時航班」）：資源只有 CSV，沒有 JSON；
  實際檔案是 `https://www.taoyuan-airport.com/uploads/flightx/a_flight_v4.txt`（Big5 編碼、
  逗號分隔、沒有標題列，每 5 分鐘更新）。存成 JSON 時欄位名稱照資料集說明的順序。

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

from ..timeutil import iso
from . import SourceError, http_get

log = logging.getLogger("hongthai")

HKG_URL = "https://www.hongkongairport.com/flightinfo-rest/rest/flights/past"
TPE_URL = "https://www.taoyuan-airport.com/uploads/flightx/a_flight_v4.txt"
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
    for airport, fn in (("VHHH", lambda: fetch_hkg(now)), ("RCTP", fetch_tpe)):
        try:
            path = write_snapshot(history_dir, airport, now, fn())
            log.info("航班快照 %s → %s（%d bytes）", airport, path, path.stat().st_size)
            result[airport] = None
        except (SourceError, ValueError, OSError) as e:
            log.warning("航班快照 %s 跳過：%s", airport, e)
            result[airport] = getattr(e, "code", e.__class__.__name__)
    return result
