"""颱風地圖的資料 `typhoons.json`（HD34）：**只轉載官方路徑與暴風圈，不計算**。

抓取與解析在 `sources/typhoon.py`（氣象署 `W-C0034-005`、日本氣象廳 bosai）；這裡決定每顆用
哪一份、算不算在範圍內、資料舊不舊，組成 GitHub Pages 的 `typhoons.json`（只放最新一份；`data`
分支根目錄也存一份，整個 build 失敗改發布上一份時一起發布）。網頁（Duado HW15）只在
`active: true` 時畫地圖。

- **選哪一份**（Shawn 2026-10-25，`choose`）：**以颱風為單位、中途不換**。氣象署那份的過去路徑或
  目前位置曾經落在「台灣附近」`TAIWAN_NEAR`（北緯 18–30、東經 112–130，和地圖框 `BOUNDS` 分開）
  的，這顆整個生命期都用氣象署；從頭到尾沒進過的用日本氣象廳（WMO 西北太平洋區域專責氣象中心）。
  沒用的那份記在 `others`（不畫兩條）。補充規則：
  - **上一份 `typhoons.json` 這顆已經是 `cwa`** 的一律維持 `cwa`、不切回 `jma`：這一報氣象署有這顆
    就用這一報的；這一報氣象署沒有這顆（氣象署整個失敗，或成功但沒列這顆而日本氣象廳還有）就沿用
    上一份那筆（`stale` 照這一報的時間重算、記 `reusedFrom`，`others` 換成這一報日本氣象廳的）。
    氣象署成功、兩邊都沒有這顆了才拿掉（颱風結束）
  - 只有一邊有的：只有日本氣象廳有（例如氣象署失敗、上一份也不是 `cwa`）就用日本氣象廳；只有氣象署
    有、從沒進過台灣附近（日本氣象廳沒發）就用氣象署——有官方資料就畫
  - 怎麼找上一份的同一顆（`_previous_entry`）：`id` 相同，或上一份那筆的來源代號（`sourceId`）、
    `others` 的代號和這一報任一邊的代號相同
  怎麼算同一顆（`same_storm`，照順序）：
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
  沒有上一份就是 `active: false`、`storms: []`。只有一個失敗時照另一個出（上一份是 `cwa` 的照上面
  的規則沿用）
- 任何失敗只 log，不影響 `latest.json`（`build.write_typhoons`）

格式（`schema` 1）：`{"schema", "generatedAt", "active",
"bounds": {"south", "north", "west", "east"},
"sources": {"cwa": {"ok"[, "error"]}, "jma": {"ok"[, "error"]}}, "storms": [...],
"outOfRange": [{"id", "source"}][, "reusedFrom"]}`；每顆 `{"id", "name": {四語},
"source": "cwa"|"jma", "sourceId", "issuedAt", "url", "stale",
"others": [{"source", "id", "issuedAt", "url"}], "past": [...], "now", "forecast": [...]
[, "reusedFrom"]}`
（點的格式見 `sources/typhoon.py`）。`id` 是國際編號（`2630`），沒有編號的是
`cwa-td21`／`jma-TC2637`；`sourceId` 是那個來源自己的代號（氣象署 `ty30`／`td21`、JMA
`TC2636`），下一報認上一份的同一顆用。`name`：氣象署給中文、英文，JMA 只給英文；照 `sources/cwa.py`
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
# 「台灣附近」（Shawn 2026-10-25）：氣象署那份的過去路徑或目前位置進過這裡的颱風整個生命期用氣象署
TAIWAN_NEAR = {"south": 18, "north": 30, "west": 112, "east": 130}
STALE_HOURS = 12
MATCH_KM = 300
MATCH_HOURS = 6
PAGES = {"cwa": CWA_PAGE, "jma": JMA_PAGE}


def in_bounds(lat: float, lon: float, box: dict = BOUNDS) -> bool:
    return box["south"] <= lat <= box["north"] and box["west"] <= lon <= box["east"]


def _in_range(now: dict | None, forecast: list[dict]) -> bool:
    pts = ([now] if now else []) + forecast
    return any(in_bounds(p["lat"], p["lon"]) for p in pts)


def in_range(s: Storm) -> bool:
    """目前位置或任一預報點在 `BOUNDS` 內（過去路徑不算）。"""
    return _in_range(s.now, s.forecast)


def near_taiwan(s: Storm) -> bool:
    """過去路徑或目前位置曾經落在 `TAIWAN_NEAR` 內（預報點不算）。"""
    pts = s.past + ([s.now] if s.now else [])
    return any(in_bounds(p["lat"], p["lon"], TAIWAN_NEAR) for p in pts)


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
        "sourceId": s.key,
        "issuedAt": iso(s.issued_at),
        "url": PAGES[s.source],
        "stale": _stale(iso(s.issued_at), now),
        "others": [_other(o) for o in others],
        "past": s.past,
        "now": s.now,
        "forecast": s.forecast,
    }


Pair = tuple[Storm | None, Storm | None]  # （氣象署那份, 日本氣象廳那份）


def pair_up(cwa: list[Storm], jma: list[Storm]) -> list[Pair]:
    """每顆一筆（氣象署那份, 日本氣象廳那份），沒有的是 None；配對用 `same_storm`。"""
    out: list[list[Storm | None]] = [[c, None] for c in cwa]
    for j in jma:
        hit = next((p for p in out if p[1] is None and same_storm(p[0], j)), None)  # type: ignore[arg-type]
        if hit is not None:
            hit[1] = j
        else:
            out.append([None, j])
    return [(c, j) for c, j in out]


def _codes(c: Storm | None, j: Storm | None) -> set[tuple[str, str]]:
    return {(s.source, s.key) for s in (c, j) if s is not None}


def _previous_entry(prev: list[dict], c: Storm | None, j: Storm | None) -> dict | None:
    """上一份 `storms` 裡的同一顆（`id` 相同，或來源代號相同）。"""
    ids = {storm_id(s) for s in (c, j) if s is not None}
    codes = _codes(c, j)
    for e in prev:
        mine = {(e.get("source"), e.get("sourceId"))}
        mine |= {
            (o.get("source"), o.get("id")) for o in e.get("others") or [] if isinstance(o, dict)
        }
        if e.get("id") in ids or mine & codes:
            return e
    return None


def choose(
    c: Storm | None, j: Storm | None, prev: dict | None, cwa_ok: bool
) -> tuple[Storm | dict, list[Storm]] | None:
    """這顆用哪一份（規則見模組說明）：回傳（用的那份或要沿用的上一份那筆, 沒用的那份）；
    沒有資料可用回 None。"""
    sticky = prev is not None and prev.get("source") == "cwa"
    if c is not None and (sticky or near_taiwan(c) or j is None):
        return c, [j] if j is not None else []
    if sticky and (j is not None or not cwa_ok):
        return prev, [j] if j is not None else []  # type: ignore[return-value]
    if j is not None:
        return j, [c] if c is not None else []
    return None


def _reuse(entry: dict, others: list[Storm], now: datetime, generated: object) -> dict:
    """上一份那筆照原樣沿用：`stale` 重算、`others` 換成這一報的、記 `reusedFrom`。"""
    return {
        **entry,
        "stale": _stale(entry.get("issuedAt"), now),
        "others": [_other(o) for o in others],
        "reusedFrom": entry.get("reusedFrom") or generated,
    }


def build(
    cwa: TyphoonData | None,
    jma: TyphoonData | None,
    status: dict[str, dict],
    now: datetime,
    previous: dict | None = None,
) -> dict:
    """組 `typhoons.json`。`cwa`／`jma` 是 None 表示那個來源失敗（原因在 `status`，`build._call` 的
    `sources.cwaTyphoon`／`jmaTyphoon`）。`previous` 是上一份 `typhoons.json`（沒有是 None）。"""
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
    prev_storms = previous.get("storms") if isinstance(previous, dict) else None
    prev_storms = (
        [e for e in prev_storms if isinstance(e, dict)] if isinstance(prev_storms, list) else []
    )
    generated = previous.get("generatedAt") if isinstance(previous, dict) else None
    if cwa is None and jma is None:
        if prev_storms:
            doc["storms"] = [{**e, "stale": _stale(e.get("issuedAt"), now)} for e in prev_storms]
            doc["reusedFrom"] = generated
            doc["active"] = True
        return doc
    used: list[int] = []
    picked: list[tuple[Storm | dict, list[Storm]]] = []
    for c, j in pair_up(cwa.storms if cwa else [], jma.storms if jma else []):
        prev = _previous_entry(prev_storms, c, j)
        if prev is not None:
            used.append(id(prev))
        res = choose(c, j, prev, cwa is not None)
        if res is not None:
            picked.append(res)
    if cwa is None:  # 氣象署失敗、這一報兩邊都沒有的 `cwa` 那筆也沿用（不知道是不是結束了）
        picked += [(e, []) for e in prev_storms if e.get("source") == "cwa" and id(e) not in used]
    for s, others in picked:
        if isinstance(s, dict):
            entry = _reuse(s, others, now, generated)
            ok = _in_range(entry.get("now"), entry.get("forecast") or [])
            sid, src = entry.get("id"), entry.get("source")
        else:
            entry, ok, sid, src = storm_json(s, now, others), in_range(s), storm_id(s), s.source
        if ok:
            doc["storms"].append(entry)
        else:
            doc["outOfRange"].append({"id": sid, "source": src})
    doc["active"] = bool(doc["storms"])
    return doc


def read_previous(archive: Path) -> dict | None:
    try:
        doc = json.loads((archive / FILENAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None
