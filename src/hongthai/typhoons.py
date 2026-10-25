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
  - 怎麼找上一份的同一顆（`_previous_entry`，HD34b）：上一份那筆和這一報都有英文名時**只比
    英文名**（不同就不是，`others` 不看：HD34 時氣象署編號被當國際編號，薔琵的 `others` 配成氣象署
    煙花 `ty30`）；有一邊沒有英文名（熱帶性低氣壓）才看國際編號 `id` 相同，或上一份那筆的來源代號
    （`sourceId`）、`others` 的代號和這一報任一邊相同（氣象署命名後代號從 `td33` 變 `ty29`，要靠
    `others` 裡日本氣象廳的代號認）
  怎麼算同一顆（`same_storm`，HD34b 改）：氣象署的 `CwaTyNo` 是氣象署自己的編號、和國際編號不同號
  （2026-10-25 薔琵氣象署 29、國際 2630），所以**不比編號**：
  1. 兩邊都有英文名：名稱相同（不分大小寫、忽略非英數字，`IN-FA` ＝ `In-fa`）才算
  2. 其他（有一邊沒有英文名，例如熱帶性低氣壓）：目前位置相距 `MATCH_KM` 公里內、定位時間相差
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
（點的格式見 `sources/typhoon.py`）。`id`（網頁 HW15 拿來當鍵，`storm_id`）照順序：
1. 國際編號（`2630`）：只有日本氣象廳的 `typhoonNumber` 有；這顆用氣象署那份時也拿配到的日本
   氣象廳那份的
2. 這一報沒有國際編號（日本氣象廳沒列這顆或還沒編號）、上一份同一顆的 `id` 是國際編號：沿用
   （編號不會收回）
3. 都沒有：`<來源>-<代號>`，用的那份是氣象署就是 `cwa-ty29`／`cwa-td33`、日本氣象廳是
   `jma-TC2637`
`sourceId` 是那個來源自己的代號（氣象署 `ty29`／`td33`、JMA `TC2636`），下一報認上一份的同一顆
用。`name`：氣象署給中文、英文，JMA 只給英文；照 `sources/cwa.py` 颱風警報的寫法，zh-TW／zh-HK
用中文名、zh-CN 與 en 用英文名，缺中文用英文，都缺用 `TD33`（氣象署熱帶性低氣壓編號）或 JMA 代號。
用日本氣象廳那份時，`others` 裡配到的氣象署那份有中文名就借來給 zh-TW／zh-HK（2026-10-26）。
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
    """氣象署那顆 `c` 和日本氣象廳那顆 `j` 是不是同一顆（規則見模組說明；不比編號）。"""
    if _name_key(c.name_en) and _name_key(j.name_en):
        return _name_key(c.name_en) == _name_key(j.name_en)
    if not (c.now and j.now and c.now["time"] and j.now["time"]):
        return False
    dt = abs(parse_time(c.now["time"]) - parse_time(j.now["time"]))
    return dt <= timedelta(hours=MATCH_HOURS) and _km(c.now, j.now) <= MATCH_KM


def _is_number(v: object) -> bool:
    return isinstance(v, str) and v.isdigit()


def storm_id(s: Storm | dict, c: Storm | None, j: Storm | None, prev: dict | None) -> str:
    """這顆的 `id`（規則見模組說明）：`s` 是用的那份（或要沿用的上一份那筆），`c`／`j` 是這一報
    兩邊的，`prev` 是上一份的同一顆。"""
    number = next((x.number for x in (j, c) if x is not None and x.number), None)
    if number:
        return number
    if prev is not None and _is_number(prev.get("id")):
        return prev["id"]
    if isinstance(s, dict):
        return str(s.get("id"))
    return f"{s.source}-{s.key}"


def names(s: Storm, others: list[Storm] | tuple[Storm, ...] = ()) -> dict[str, str]:
    """四語名稱。用日本氣象廳那份（只有英文名）時，配到的氣象署那份有中文名就借來給 zh-TW／zh-HK
    （Shawn 2026-10-26：只借名字，路徑、暴風圈、`source` 照用日本氣象廳的）。"""
    fallback = s.key.upper() if s.source == "cwa" else s.key
    en = s.name_en or fallback
    borrowed = next((o.name_zh for o in others if o.source == "cwa" and o.name_zh), "")
    zh = s.name_zh or borrowed or en
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


def storm_json(s: Storm, sid: str, now: datetime, others: list[Storm]) -> dict:
    return {
        "id": sid,
        "name": names(s, others),
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


def _entry_name(e: dict) -> str:
    """上一份那筆的英文名（`_name_key` 過）；`names` 沒英文名時補的 `TD33`／JMA 代號不算。"""
    name = e.get("name")
    en = name.get("en") if isinstance(name, dict) else None
    sid = e.get("sourceId")
    if not isinstance(en, str) or (isinstance(sid, str) and en in (sid, sid.upper())):
        return ""
    return _name_key(en)


def _previous_entry(prev: list[dict], c: Storm | None, j: Storm | None) -> dict | None:
    """上一份 `storms` 裡的同一顆（規則見模組說明：英文名都有時只比英文名）。"""
    name = next((_name_key(s.name_en) for s in (c, j) if s is not None and s.name_en), "")
    numbers = {s.number for s in (c, j) if s is not None and s.number}
    codes = {(s.source, s.key) for s in (c, j) if s is not None}
    for e in prev:
        prev_name = _entry_name(e)
        if name and prev_name:
            if name == prev_name:
                return e
            continue
        mine = {(e.get("source"), e.get("sourceId"))}
        mine |= {
            (o.get("source"), o.get("id")) for o in e.get("others") or [] if isinstance(o, dict)
        }
        if e.get("id") in numbers or mine & codes:
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
    picked: list[tuple[Storm | dict, list[Storm], str]] = []
    for c, j in pair_up(cwa.storms if cwa else [], jma.storms if jma else []):
        prev = _previous_entry(prev_storms, c, j)
        if prev is not None:
            used.append(id(prev))
        res = choose(c, j, prev, cwa is not None)
        if res is not None:
            picked.append((*res, storm_id(res[0], c, j, prev)))
    if cwa is None:  # 氣象署失敗、這一報兩邊都沒有的 `cwa` 那筆也沿用（不知道是不是結束了）
        picked += [
            (e, [], str(e.get("id")))
            for e in prev_storms
            if e.get("source") == "cwa" and id(e) not in used
        ]
    for s, others, sid in picked:
        if isinstance(s, dict):
            entry = {**_reuse(s, others, now, generated), "id": sid}
            ok = _in_range(entry.get("now"), entry.get("forecast") or [])
            src = entry.get("source")
        else:
            entry, ok, src = storm_json(s, sid, now, others), in_range(s), s.source
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
