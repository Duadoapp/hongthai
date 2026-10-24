"""颱風地圖的資料 `typhoons.json`（HD34）：**只轉載官方路徑與暴風圈，不計算**。

抓取與解析在 `sources/typhoon.py`（氣象署 `W-C0034-005`、日本氣象廳 bosai）；這裡決定每顆用
哪一份、算不算在範圍內、資料舊不舊，組成 GitHub Pages 的 `typhoons.json`（只放最新一份；`data`
分支根目錄也存一份，整個 build 失敗改發布上一份時一起發布）。網頁（Duado HW15）只在
`active: true` 時畫地圖。

- **選哪一份**：每顆熱帶氣旋，氣象署有就用氣象署，沒有才用日本氣象廳；兩邊都有時只放氣象署
  那份，日本氣象廳那份記在 `others`（不畫兩條）。怎麼算同一顆（`same_storm`，照順序）：
  1. 兩邊都有國際編號（氣象署 `year`＋`cwb_ty_no`、JMA `typhoonNumber`，例如 `2630`）：
     編號相同才算
  2. 兩邊都有英文名：名稱相同（不分大小寫、忽略非英數字，`IN-FA` ＝ `In-fa`）才算
  3. 其他（熱帶性低氣壓沒有編號也沒有名字）：目前位置相距 `MATCH_KM` 公里內、定位時間相差
     `MATCH_HOURS` 小時內才算（只拿來配對，不輸出）
- **範圍**（`in_range`）：目前位置或任一預報點落在 `BOUNDS`（51 個機場的經緯度外擴 5 度，往外
  取到 0.1 度；`tests/test_typhoons.py` 檢查和 `airports.json` 一致）內才算；過去路徑不算。
  範圍外的不放進 `storms`，只在 `outOfRange` 記編號與來源
- **資料舊**：`issuedAt` 早於產生時間 `STALE_HOURS`（12）小時就 `stale: true`
- 兩個來源都失敗時沿用上一份的 `storms`（`stale` 照這一報的時間重算，另記 `reusedFrom`）；
  沒有上一份就是 `active: false`、`storms: []`。只有一個失敗時照另一個出（氣象署失敗時，
  台灣附近的颱風改用日本氣象廳那份）
- 任何失敗只 log，不影響 `latest.json`（`build.write_typhoons`）

格式（`schema` 1）：`{"schema", "generatedAt", "active",
"bounds": {"south", "north", "west", "east"},
"sources": {"cwa": {"ok"[, "error"]}, "jma": {"ok"[, "error"]}}, "storms": [...],
"outOfRange": [{"id", "source"}][, "reusedFrom"]}`；每顆 `{"id", "name": {四語},
"source": "cwa"|"jma", "issuedAt", "url", "stale",
"others": [{"source", "id", "issuedAt", "url"}], "past": [...], "now", "forecast": [...]}`
（點的格式見 `sources/typhoon.py`）。`id` 是國際編號（`2630`），沒有編號的是
`cwa-td21`／`jma-TC2637`。`name`：氣象署給中文、英文，JMA 只給英文；照 `sources/cwa.py`
颱風警報的寫法，zh-TW／zh-HK 用中文名、zh-CN 與 en 用英文名，缺中文用英文，都缺用 `TD21`
（氣象署熱帶性低氣壓編號）或 JMA 代號。
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta
from math import asin, cos, radians, sin, sqrt
from pathlib import Path

from .sources.typhoon import CWA_PAGE, JMA_PAGE, Storm, TyphoonData
from .timeutil import iso, parse_time

log = logging.getLogger("hongthai")

SCHEMA = 1
FILENAME = "typhoons.json"
# 51 個機場（airports.json）的緯度 7.367–42.7748、經度 103.9935–144.7973，外擴 5 度、往外取到 0.1 度
BOUNDS = {"south": 2.3, "north": 47.8, "west": 98.9, "east": 149.8}
MARGIN_DEG = 5
STALE_HOURS = 12
MATCH_KM = 300
MATCH_HOURS = 6
PAGES = {"cwa": CWA_PAGE, "jma": JMA_PAGE}


def in_bounds(lat: float, lon: float) -> bool:
    return BOUNDS["south"] <= lat <= BOUNDS["north"] and BOUNDS["west"] <= lon <= BOUNDS["east"]


def in_range(s: Storm) -> bool:
    """目前位置或任一預報點在 `BOUNDS` 內（過去路徑不算）。"""
    pts = ([s.now] if s.now else []) + s.forecast
    return any(in_bounds(p["lat"], p["lon"]) for p in pts)


def _name_key(name: str) -> str:
    return re.sub(r"[^0-9A-Z]", "", name.upper())


def _km(a: dict, b: dict) -> float:
    lat1, lon1, lat2, lon2 = map(radians, (a["lat"], a["lon"], b["lat"], b["lon"]))
    h = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371 * asin(sqrt(h))


def same_storm(c: Storm, j: Storm) -> bool:
    """氣象署那顆 `c` 和日本氣象廳那顆 `j` 是不是同一顆（規則見模組說明）。"""
    if c.number and j.number:
        return c.number == j.number
    if _name_key(c.name_en) and _name_key(j.name_en):
        return _name_key(c.name_en) == _name_key(j.name_en)
    if not (c.now and j.now and c.now["time"] and j.now["time"]):
        return False
    dt = abs(parse_time(c.now["time"]) - parse_time(j.now["time"]))
    return dt <= timedelta(hours=MATCH_HOURS) and _km(c.now, j.now) <= MATCH_KM


def storm_id(s: Storm) -> str:
    return s.number or f"{s.source}-{s.key}"


def names(s: Storm) -> dict[str, str]:
    fallback = s.key.upper() if s.source == "cwa" else s.key
    en = s.name_en or fallback
    zh = s.name_zh or en
    return {"zh-TW": zh, "zh-HK": zh, "zh-CN": en, "en": en}


def _stale(issued: str | None, now: datetime) -> bool:
    t = parse_time(issued) if issued else None
    return t is None or now - t > timedelta(hours=STALE_HOURS)


def _other(s: Storm) -> dict:
    return {
        "source": s.source,
        "id": s.key,
        "issuedAt": iso(s.issued_at),
        "url": PAGES[s.source],
    }


def storm_json(s: Storm, now: datetime, others: list[Storm]) -> dict:
    return {
        "id": storm_id(s),
        "name": names(s),
        "source": s.source,
        "issuedAt": iso(s.issued_at),
        "url": PAGES[s.source],
        "stale": _stale(iso(s.issued_at), now),
        "others": [_other(o) for o in others],
        "past": s.past,
        "now": s.now,
        "forecast": s.forecast,
    }


def select(cwa: list[Storm], jma: list[Storm]) -> list[tuple[Storm, list[Storm]]]:
    """每顆一筆（用的那份, 另一邊同一顆的）：氣象署全部，加上對不到氣象署的日本氣象廳。"""
    out: list[tuple[Storm, list[Storm]]] = [(c, []) for c in cwa]
    for j in jma:
        hit = next(
            (pair for pair in out if pair[0].source == "cwa" and same_storm(pair[0], j)), None
        )
        if hit is not None:
            hit[1].append(j)
        else:
            out.append((j, []))
    return out


def build(
    cwa: TyphoonData | None,
    jma: TyphoonData | None,
    status: dict[str, dict],
    now: datetime,
    previous: dict | None = None,
) -> dict:
    """組 `typhoons.json`。`cwa`／`jma` 是 None 表示那個來源失敗（原因在 `status`，`build._call` 的
    `sources.cwaTyphoon`／`jmaTyphoon`）。"""
    sources = {}
    for name, key in (("cwa", "cwaTyphoon"), ("jma", "jmaTyphoon")):
        st = status.get(key) or {"ok": False, "error": "skipped"}
        sources[name] = {"ok": bool(st.get("ok"))} | (
            {} if st.get("ok") else {"error": st.get("error")}
        )
    doc: dict = {
        "schema": SCHEMA,
        "generatedAt": iso(now),
        "active": False,
        "bounds": dict(BOUNDS),
        "sources": sources,
        "storms": [],
        "outOfRange": [],
    }
    if cwa is None and jma is None:
        prev_storms = previous.get("storms") if isinstance(previous, dict) else None
        if isinstance(prev_storms, list) and prev_storms:
            doc["storms"] = [
                {**s, "stale": _stale(s.get("issuedAt"), now)}
                for s in prev_storms
                if isinstance(s, dict)
            ]
            doc["reusedFrom"] = previous.get("generatedAt")
            doc["active"] = bool(doc["storms"])
        return doc
    pairs = select(cwa.storms if cwa else [], jma.storms if jma else [])
    for s, others in pairs:
        if in_range(s):
            doc["storms"].append(storm_json(s, now, others))
        else:
            doc["outOfRange"].append({"id": storm_id(s), "source": s.source})
    doc["active"] = bool(doc["storms"])
    return doc


def read_previous(archive: Path) -> dict | None:
    try:
        doc = json.loads((archive / FILENAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None
