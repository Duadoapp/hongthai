"""事件保存（HD20，Shawn 2026-10-20 定案）：颱風 29W（CHAMPI）期間完整保存每一報與「真相」，
之後拿來驗證（路徑抽取 HD21、報告工具 HD22）。這支只保存，不改任何等級規則。

事件設定在 repo 根目錄的 `events.json`（`config.load_events`）；期間 `from`～`to` 是**台灣日期**
（含兩端，`active`）。資料都在 `data` 分支的 `history/events/<id>/`：

- `<YYYYMMDDTHHMM>Z.json`：每報的 `latest.json`（`build.py` 寫完 `history/<時間>.json` 後
  原樣複製，`snapshot`；同一份內容，git 裡是同一個 blob、不多佔空間）。`generatedAt` 在期間內
  的報才存。期間開始前已經過去的報用 `python -m hongthai.events backfill --archive data`
  一次搬進來（`backfill`，已存在的跳過）
- `metar/<YYYY-MM-DD>.jsonl`（日期是觀測時間的 UTC 日期）：每小時抓一次（`hourly`），
  一站一筆觀測一行 `{"t", "icao", "observedAt", "windDirDeg", "windKt", "gustKt",
  "visibilityM", "wx", "raw", "source", "type"}`；`t` 是抓的時間、`source` 是
  `"aviationweather"` 或 `"cwa"`（金門、馬祖用氣象署局屬站觀測，HD13）、`type` 是
  `METAR`／`SPECI`（氣象署的是 null）。同一站同一 `observedAt` 已經有就不寫。
  `python -m hongthai.events backfill-metar --archive data --from <UTC 時間>`（HD25，
  `backfill_metar`）把 AviationWeather 還有的觀測補進來（同一個去重鍵、已有的不覆蓋），補進來
  的行多 `"backfill": "aviationweather"`；金門、馬祖（氣象署 `O-A0003-001` 只有現在）補不到，
  只記 log
- `position/jma-<YYYY-MM-DD>.jsonl`、`position/jtwc-<YYYY-MM-DD>.jsonl`（日期是
  **發布時間**的 UTC 日期）：颱風現報與各預報點，一行一點 `{"t", "issuedAt",
  "kind": "analysis"|"forecast", "leadHours", "validAt", "lat", "lon", "pressureHpa",
  "windKt", "gustKt", "source", "raw"}`。同一來源同一 `issuedAt`＋`validAt` 已經有就不寫
  （每小時抓、但 JMA／JTWC 每 3／6 小時才更新）。JTWC 的行多一個 `warning`（警報編號）；
  `raw` 是 JMA 的原始那筆物件、JTWC 的 `T` 行原文
- `position/raw/jtwc-<YYYYMMDDTHHMM>Z.txt`：JTWC 警報原文（時間是抓的時間），有新的一報
  （寫了新的行）或解析不出來時才存，同一報不重複存
- `tracks/<起報 YYYYMMDDTHHMM>Z-<模式>.json`：各模式每一報的颱風路徑（HD21，`tracks.py`；build 每報
  寫，過去的報用 `python -m hongthai.events backfill-tracks --archive data --from <UTC 時間>` 補：
  讀 `from` 以後每份快照的 `runs`，每個模式每個時次只抽一次，已經有的跳過）
- `wn3/<起報 YYYYMMDDTHHMM>Z.json`：WeatherNext 3 每格的數字（HD15，`wn3report.py`）；
  `backfill-tracks` 也補 WN3（事件期間 `from` 以後、起報 ≤ 現在 − 121 小時的主報，事件檔＋
  路徑檔），要 Google 憑證
- `flights/<YYYY-MM-DD>.jsonl`（HD31，日期是**表定時間**的 UTC 日期）：每小時抓桃園、松山、
  高雄、香港、澳門五個航班來源（`sources/flights.py`，事件的 `airports` 有的才寫），逐班一行
  （格式與規則見 `flights_log.py`；解析、共掛、分類沿用 `cancellations.py`）；同一班的狀態、分類、
  預計／實際時間和最後一行一樣就不寫。原始回應不存。
  `python -m hongthai.events backfill-flights --archive data --from <日期>`（`backfill_flights`）：
  香港 `past?date=` 從 `--from` 到今天（香港日期）每天查一次補進來（行多 `"backfill": true`，同一班
  同狀態不重寫）；其他四個來源只有當天，補不到，只記 log。
  HD32：同一個檔另外存 TDX（交通部運輸資料流通服務平臺）的航空即時航班（`sources/tdx.py`），
  `airports.json` 地區 `taiwan` 的十個機場（事件的 `airports` 有的才寫）一次請求拿，`source: "tdx"`
  （`flights_log.tdx_rows`）；桃園、松山、高雄和原本的來源各存各的（去重鍵含 `source`）。要
  `TDX_CLIENT_ID`、`TDX_CLIENT_SECRET`，沒設就跳過（記一行「TDX 未設定」）；沒有補過去的功能

來源（2026-10-20 實抓）：
- METAR：AviationWeather `metar?ids=<25 站>&format=json&hours=6`（`hours` 讓半小時一報的
  機場兩筆都拿到、排程晚了也補得回來；HD25 從 3 改 6：GitHub 排程曾經 18 小時只跑 4 次）；
  欄位解碼同 `sources/taf.py`。AviationWeather 的限制（2026-10-21 文件＋實測）：資料庫保留
  30 天；`hours` 本身沒有上限（720 也收），但**每次最多回 400 筆**（超過只給最新的 400 筆），
  所以補缺口每站分開、每次 72 小時，用 `date`（結束時間）＋`hours` 指定區間
  （`[date − hours, date]`，含兩端）。金門、馬祖用氣象署
  `O-A0003-001`（`CWA_API_KEY`）
- JMA：`https://www.jma.go.jp/bosai/typhoon/data/targetTc.json`（目前的颱風：
  `tropicalCyclone` 是代號 `TC2636`、`typhoonNumber` 是號數 `2630`）→
  `…/data/<代號>/specifications.json`：第一筆 `part: "title"`（`issue.UTC`），之後每筆一個
  時間點：`advancedHours`（0＝實況）、`validtime.UTC`、`position.deg`（[緯, 經]）、
  `pressure`（hPa，字串）、`maximumWind.sustained.kt`／`maximumWind.gust.kt`（字串；JMA 的
  平均風是 **10 分鐘**平均）。非正式介面，失敗只記 log
- JTWC：`https://www.metoc.navy.mil/jtwc/products/<id>.tcw`（文字警報，CRLF）：第一行
  `WTPN52 PGTW 200300`（發布 日時分 Z）、第三行 `2026102000 29W CHAMPI 023 …`（基準時間、
  警報編號）、`T000 159N 1356E 130 …`（`T<小時>` 緯經×10、最大**1 分鐘**平均風節）、本文
  `200000Z --- NEAR 15.9N 135.6E` 下面的 `MAX SUSTAINED WINDS - 130 KT, GUSTS 160 KT`
  （陣風）與 `MINIMUM CENTRAL PRESSURE AT 200000Z IS 929 MB`（只有實況）

每小時四件事（METAR、JMA、JTWC、航班〔HD31〕）分開 try，失敗只記 log、不算整個失敗
（`hourly` 一律回 0）。航班的 TDX（HD32）再另外 try：token 或請求失敗只記 log，不影響原本五個來源。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shutil
import sys
import time
from collections import defaultdict
from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from . import flights_log
from .config import Airport, Event, load_airports, load_events
from .sources import SourceError, cwa, flights, http_get, taf, tdx
from .timeutil import iso, parse_time, utcnow

log = logging.getLogger("hongthai")

TAIPEI = ZoneInfo("Asia/Taipei")
METAR_HOURS = 6
# 補缺口（HD25）：AviationWeather 每次最多回 400 筆；一站半小時一報＋SPECI，72 小時約 150 筆
AW_MAX_ENTRIES = 400
BACKFILL_WINDOW_H = 72
BACKFILL_PAUSE_S = 1.0  # 請求之間停一下（AviationWeather 每分鐘最多 100 次）
JMA_TARGET_URL = "https://www.jma.go.jp/bosai/typhoon/data/targetTc.json"
JMA_SPEC_URL = "https://www.jma.go.jp/bosai/typhoon/data/{tc}/specifications.json"
JTWC_URL = "https://www.metoc.navy.mil/jtwc/products/{id}.tcw"
_STAMP = "%Y%m%dT%H%MZ"


def tw_date(t: datetime) -> date:
    return t.astimezone(TAIPEI).date()


def active(events: Iterable[Event], t: datetime) -> list[Event]:
    """`t` 的台灣日期落在 `from`～`to`（含兩端）的事件。"""
    d = tw_date(t)
    return [e for e in events if e.start <= d <= e.end]


def event_dir(history: Path, e: Event) -> Path:
    return history / "events" / e.id


def _stamp_time(name: str) -> datetime | None:
    try:
        return datetime.strptime(name, _STAMP).replace(tzinfo=UTC)
    except ValueError:
        return None


# ---- 每報快照 ----


def snapshot(history: Path, events: Iterable[Event], now: datetime, src: Path) -> list[Path]:
    """`build.py` 寫完 `history/<時間>.json`（`src`）後呼叫：`now` 在期間內的事件各複製一份。"""
    out = []
    for e in active(events, now):
        dst = event_dir(history, e) / src.name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        out.append(dst)
    return out


def backfill(history: Path, events: Iterable[Event]) -> dict[str, int]:
    """`history/<時間>.json` 裡時間在事件期間內的報複製進 `events/<id>/`（已存在的跳過）。
    回傳每個事件新複製了幾份。"""
    files = []
    for p in history.glob("*.json"):
        t = _stamp_time(p.stem)
        if t is not None:
            files.append((t, p))
    out = {}
    for e in events:
        n = 0
        for t, p in sorted(files):
            dst = event_dir(history, e) / p.name
            if not e.start <= tw_date(t) <= e.end or dst.exists():
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, dst)
            n += 1
        out[e.id] = n
    return out


# ---- jsonl：去重追加 ----


def append_new(
    path_of: Callable[[dict], Path], rows: Iterable[dict], key: Callable[[dict], tuple]
) -> int:
    """每行依 `path_of` 分檔追加；同一檔裡 `key` 已經有的不寫。回傳寫了幾行。"""
    seen: dict[Path, set[tuple]] = {}
    n = 0
    for row in rows:
        p = path_of(row)
        if p not in seen:
            seen[p] = set()
            if p.exists():
                for line in p.read_text(encoding="utf-8").splitlines():
                    try:
                        seen[p].add(key(json.loads(line)))
                    except (ValueError, KeyError, TypeError, AttributeError):
                        continue  # 壞掉的行不擋新的
        k = key(row)
        if k in seen[p]:
            continue
        seen[p].add(k)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        n += 1
    return n


def _day(t: str | None, fallback: datetime) -> str:
    d = parse_time(t) if t else None
    return f"{d or fallback:%Y-%m-%d}"


# ---- METAR ----


def metar_row(icao: str, m: taf.Metar, fetched: datetime, kind: str | None) -> dict:
    return {
        "t": iso(fetched),
        "icao": icao,
        "observedAt": iso(m.observed),
        "windDirDeg": m.wdir,
        "windKt": m.wind_kt,
        "gustKt": m.gust_kt,
        "visibilityM": m.vis_m,
        "wx": list(m.wx),
        "raw": m.raw,
        "source": m.source or "aviationweather",
        "type": kind,
    }


def metar_rows(
    aw: list, obs: dict[str, taf.Metar], icaos: Iterable[str], fetched: datetime
) -> list[dict]:
    """AviationWeather 的回應（每筆觀測一行，不像 `taf.parse_metars` 只留最新的）＋氣象署觀測
    （ICAO → `Metar`）→ 行；只收 `icaos` 裡的站。"""
    want = set(icaos)
    rows = []
    for item in aw:
        if not isinstance(item, dict) or item.get("icaoId") not in want:
            continue
        for icao, m in taf.parse_metars([item]).items():
            rows.append(metar_row(icao, m, fetched, item.get("metarType")))
    for icao, m in obs.items():
        if icao in want:
            rows.append(metar_row(icao, m, fetched, None))
    return rows


def store_metars(d: Path, rows: list[dict], fetched: datetime) -> int:
    return append_new(
        lambda r: d / "metar" / f"{_day(r['observedAt'], fetched)}.jsonl",
        rows,
        lambda r: (r["icao"], r["observedAt"]),
    )


def _aw_metars(params: dict) -> list:
    """AviationWeather `metar`（`format=json`）的回應；204 或空的回 []。"""
    r = http_get(taf.METAR_URL, params={**params, "format": "json"}, error=taf.TafError)
    aw = [] if r.status_code == 204 or not r.content.strip() else r.json()
    if not isinstance(aw, list):
        raise taf.TafError("AviationWeather 回傳格式不對", "bad_format")
    return aw


def fetch_metars(
    e: Event, airports: list[Airport], api_key: str | None, fetched: datetime
) -> list[dict]:
    """AviationWeather 一次請求全部站；有 `cwaStation` 的機場（金門、馬祖）另抓氣象署觀測。
    兩邊分開 try，一邊失敗另一邊照寫。"""
    aw: list = []
    try:
        aw = _aw_metars({"ids": ",".join(e.airports), "hours": METAR_HOURS})
    except (SourceError, ValueError) as ex:
        log.warning("事件 %s：AviationWeather METAR 失敗：%s", e.id, ex)
        aw = []
    by_station = {a.cwa_station: a.icao for a in airports if a.cwa_station and a.icao in e.airports}
    obs: dict[str, taf.Metar] = {}
    if by_station and not api_key:
        log.warning("事件 %s：沒有 CWA_API_KEY，金門、馬祖的觀測不抓", e.id)
    elif by_station:
        try:
            stations = tuple(by_station)
            raw = cwa.fetch_obs(api_key or "", stations)
            obs = {by_station[s]: m for s, m in cwa.parse_obs(raw, stations).items()}
        except (SourceError, ValueError, AttributeError) as ex:
            log.warning("事件 %s：氣象署觀測失敗：%s", e.id, ex)
    return metar_rows(aw, obs, e.airports, fetched)


def metar_coverage(d: Path) -> dict[str, dict[str, int]]:
    """`metar/*.jsonl` 每站每天（UTC）有觀測的小時數（同一小時幾筆都算 1）。"""
    hours: dict[str, dict[str, set[int]]] = {}
    for p in sorted((d / "metar").glob("*.jsonl")):
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
                t = parse_time(row["observedAt"])
                icao = row["icao"]
            except (ValueError, KeyError, TypeError, AttributeError):
                continue
            if t is not None and isinstance(icao, str):
                hours.setdefault(icao, {}).setdefault(f"{t:%Y-%m-%d}", set()).add(t.hour)
    return {i: {day: len(h) for day, h in sorted(days.items())} for i, days in hours.items()}


def backfill_metar(
    history: Path,
    events: list[Event],
    airports: list[Airport],
    since: datetime,
    now: datetime,
    pause: Callable[[float], None] = time.sleep,
) -> dict[str, dict[str, int | None]]:
    """`backfill-metar`（HD25）：期間和 `since`～`now` 重疊的每個事件，AviationWeather 的站
    一站一站、每次 `BACKFILL_WINDOW_H` 小時往回抓，期間內的觀測補進 `metar/<日期>.jsonl`
    （`store_metars`，已有的不覆蓋），每行多 `"backfill": "aviationweather"`。回傳每個事件
    每站補了幾行（失敗是 None）；有 `cwaStation` 的（金門、馬祖）跳過、記 log。"""
    cwa_only = {a.icao for a in airports if a.cwa_station}
    out: dict[str, dict[str, int | None]] = {}
    first = True
    for e in events:
        start = max(since, datetime.combine(e.start, datetime.min.time(), TAIPEI).astimezone(UTC))
        end = min(now, datetime.combine(e.end + timedelta(days=1), datetime.min.time(), TAIPEI))
        if start >= end:
            continue
        d = event_dir(history, e)
        res: dict[str, int | None] = {}
        for icao in e.airports:
            if icao in cwa_only:
                log.warning(
                    "事件 %s：%s 是氣象署局屬站觀測（O-A0003-001 只有現在），補不到", e.id, icao
                )
                continue
            n = 0
            hi = end
            try:
                while hi > start:
                    hours = min(BACKFILL_WINDOW_H, -(-int((hi - start).total_seconds()) // 3600))
                    if not first:
                        pause(BACKFILL_PAUSE_S)
                    first = False
                    aw = _aw_metars({"ids": icao, "date": iso(hi), "hours": hours})
                    if len(aw) >= AW_MAX_ENTRIES:
                        log.warning(
                            "事件 %s：%s 到 %s 回了 %d 筆，可能被截掉", e.id, icao, iso(hi), len(aw)
                        )
                    rows = []
                    for r in metar_rows(aw, {}, [icao], now):
                        t = parse_time(r["observedAt"])
                        if t is not None and start <= t <= end:
                            rows.append({**r, "backfill": "aviationweather"})
                    n += store_metars(d, rows, now)
                    hi -= timedelta(hours=hours)
                res[icao] = n
            except (SourceError, ValueError) as ex:
                log.warning("事件 %s：%s 補 METAR 失敗（已補 %d 行）：%s", e.id, icao, n, ex)
                res[icao] = None
        out[e.id] = res
    return out


def _print_coverage(
    icaos: Iterable[str], before: dict[str, dict[str, int]], after: dict[str, dict[str, int]]
) -> None:
    days = sorted({day for c in (before, after) for v in c.values() for day in v})
    print("每站每天（UTC）有觀測的小時數，補之前→之後：")
    print("站    " + "  ".join(f"{day[5:]:>9}" for day in days))
    for icao in icaos:
        cells = (
            f"{before.get(icao, {}).get(day, 0):>4}→{after.get(icao, {}).get(day, 0):<4}"
            for day in days
        )
        print(f"{icao}  " + "  ".join(cells))


# ---- 颱風現報 ----


def _num(v) -> float | None:
    if isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def parse_jma(spec: list, fetched: datetime) -> list[dict]:
    """JMA bosai `specifications.json` → 實況與各預報點的行（格式見模組說明）。"""
    title = next((p for p in spec if isinstance(p, dict) and p.get("part") == "title"), {})
    issued = (title.get("issue") or {}).get("UTC")
    rows = []
    for p in spec:
        if not isinstance(p, dict) or p.get("part") == "title":
            continue
        pos = (p.get("position") or {}).get("deg") or [None, None]
        wind = p.get("maximumWind") or {}
        lead = p.get("advancedHours")
        rows.append(
            {
                "t": iso(fetched),
                "issuedAt": iso(parse_time(issued)) if issued else None,
                "kind": "analysis" if lead == 0 else "forecast",
                "leadHours": lead,
                "validAt": iso(parse_time((p.get("validtime") or {}).get("UTC"))),
                "lat": _num(pos[0]),
                "lon": _num(pos[1]),
                "pressureHpa": _num(p.get("pressure")),
                "windKt": _num((wind.get("sustained") or {}).get("kt")),
                "gustKt": _num((wind.get("gust") or {}).get("kt")),
                "source": "jma",
                "raw": p,
            }
        )
    return rows


_JTWC_HEAD = re.compile(r"^WT\w+ PGTW (\d{2})(\d{2})(\d{2})")
_JTWC_BASE = re.compile(r"^(\d{10}) +\w+ +\S+ +(\d+)")
_JTWC_T = re.compile(r"^T(\d{3}) (\d+)([NS]) (\d+)([EW]) (\d+)")
_JTWC_POS = re.compile(r"(\d{6})Z --- (?:NEAR )?(\d+\.\d)([NS]) (\d+\.\d)([EW])")
_JTWC_WIND = re.compile(r"MAX SUSTAINED WINDS - (\d+) KT, GUSTS (\d+) KT")
_JTWC_MSLP = re.compile(r"MINIMUM CENTRAL PRESSURE AT \d{6}Z IS (\d+) MB")


def _signed(v: float, hemi: str) -> float:
    return -v if hemi in ("S", "W") else v


def _ddhhmm(dd: str, hh: str, mm: str, near: datetime) -> datetime:
    """`DDHHMM` 補上年月：取最接近 `near` 的那個月（跨月時往前或往後一個月）。"""
    best = None
    for months in (-1, 0, 1):
        y, m = divmod(near.year * 12 + near.month - 1 + months, 12)
        try:
            t = datetime(y, m + 1, int(dd), int(hh), int(mm), tzinfo=UTC)
        except ValueError:
            continue
        if best is None or abs(t - near) < abs(best - near):
            best = t
    if best is None:
        raise ValueError(f"看不懂的時間 {dd}{hh}{mm}")
    return best


def parse_jtwc(text: str, fetched: datetime) -> list[dict]:
    """JTWC `.tcw` 文字警報 → 實況與各預報點的行；看不懂（沒有基準時間行）回空的。"""
    lines = [ln.rstrip() for ln in text.replace("\r", "").split("\n")]
    base = issued = None
    warning = None
    for ln in lines[:5]:
        if base is None and (m := _JTWC_BASE.match(ln)):
            base = datetime.strptime(m.group(1), "%Y%m%d%H").replace(tzinfo=UTC)
            warning = int(m.group(2))
    if base is None:
        return []
    for ln in lines[:2]:
        if m := _JTWC_HEAD.match(ln):
            issued = _ddhhmm(*m.groups(), near=base)
    gusts: dict[tuple[float, float], float] = {}
    pos = None
    for ln in lines:
        if m := _JTWC_POS.search(ln):
            pos = (
                _signed(float(m.group(2)), m.group(3)),
                _signed(float(m.group(4)), m.group(5)),
            )
        elif (m := _JTWC_WIND.search(ln)) and pos is not None:
            gusts.setdefault(pos, float(m.group(2)))
            pos = None
    mslp = _JTWC_MSLP.search(text)
    rows = []
    for ln in lines:
        m = _JTWC_T.match(ln)
        if not m:
            continue
        lead = int(m.group(1))
        lat = _signed(int(m.group(2)) / 10, m.group(3))
        lon = _signed(int(m.group(4)) / 10, m.group(5))
        rows.append(
            {
                "t": iso(fetched),
                "issuedAt": iso(issued),
                "kind": "analysis" if lead == 0 else "forecast",
                "leadHours": lead,
                "validAt": iso(base + timedelta(hours=lead)),
                "lat": lat,
                "lon": lon,
                "pressureHpa": float(mslp.group(1)) if mslp and lead == 0 else None,
                "windKt": float(m.group(6)),
                "gustKt": gusts.get((lat, lon)),
                "source": "jtwc",
                "warning": warning,
                "raw": ln,
            }
        )
    return rows


def store_positions(d: Path, source: str, rows: list[dict], fetched: datetime) -> int:
    return append_new(
        lambda r: d / "position" / f"{source}-{_day(r['issuedAt'], fetched)}.jsonl",
        rows,
        lambda r: (r["issuedAt"], r["validAt"]),
    )


def fetch_jma(e: Event, fetched: datetime) -> list[dict]:
    if not e.jma_tc_id:
        return []
    target = http_get(JMA_TARGET_URL).json()
    ids = (
        [t.get("tropicalCyclone") for t in target if isinstance(t, dict)]
        if isinstance(target, list)
        else []
    )
    if e.jma_tc_id not in ids:
        log.warning("事件 %s：JMA 目前的颱風 %s 沒有 %s", e.id, ids, e.jma_tc_id)
        return []
    spec = http_get(JMA_SPEC_URL.format(tc=e.jma_tc_id)).json()
    return parse_jma(spec if isinstance(spec, list) else [], fetched)


def fetch_jtwc(e: Event, d: Path, fetched: datetime) -> int:
    """抓、解析、寫行；有新的一報或解析不出來時存原文。回傳寫了幾行。"""
    if not e.jtwc_id:
        return 0
    r = http_get(JTWC_URL.format(id=e.jtwc_id), retries=2)
    text = r.content.decode("utf-8", errors="replace")
    rows = parse_jtwc(text, fetched)
    n = store_positions(d, "jtwc", rows, fetched)
    if n or not rows:
        if not rows:
            log.warning("事件 %s：JTWC 原文解析不出位置，只存原文", e.id)
        raw = d / "position" / "raw" / f"jtwc-{fetched:{_STAMP}}.txt"
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_text(text, encoding="utf-8")
    return n


# ---- 航班（HD31） ----

FLIGHT_FETCHERS = ("VHHH", "RCTP", "RCSS", "RCKH", "VMMC")  # `flights.fetch` 的五個機場
HKG = "VHHH"


def store_flights(d: Path, rows: list[dict]) -> int:
    """依表定時間的 UTC 日期分檔，只追加和同一班最後一行不同的（`flights_log.changed`）。"""
    by_day: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_day[flights_log.day_of(r)].append(r)
    n = 0
    for day, day_rows in sorted(by_day.items()):
        p = d / "flights" / f"{day}.jsonl"
        old = p.read_text(encoding="utf-8").splitlines() if p.exists() else []
        new = flights_log.changed(old, day_rows)
        if not new:
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in new)
        n += len(new)
    return n


def _tz(airports: list[Airport]) -> dict[str, str]:
    return {a.icao: a.tz for a in airports}


def fetch_flights(
    e: Event, airports: list[Airport], fetched: datetime, d: Path
) -> dict[str, int | None]:
    """抓五個來源（`flights.fetch`，各自 try）、逐班寫進 `flights/`；回傳每個機場寫了幾行
    （抓不到或解析失敗是 None）。事件的 `airports` 沒有的機場不寫。"""
    want = [a for a in FLIGHT_FETCHERS if a in e.airports]
    if not want:
        return {}
    data = flights.fetch(fetched)
    tz = _tz(airports)
    out: dict[str, int | None] = {}
    for icao in want:
        if icao not in data.snapshots:
            log.warning("事件 %s：航班 %s 抓不到（%s）", e.id, icao, data.errors.get(icao))
            out[icao] = None
            continue
        try:
            rows = flights_log.rows_of(icao, data.snapshots[icao], tz[icao], fetched)
            out[icao] = store_flights(d, rows)
        except Exception:  # 一個機場的格式變了不擋其他機場
            log.exception("事件 %s：航班 %s 解析或寫檔失敗", e.id, icao)
            out[icao] = None
    log.info(
        "事件 %s：航班 " + "、".join(f"{k} {'失敗' if v is None else v}" for k, v in out.items()),
        e.id,
    )
    return out


def backfill_flights(
    history: Path,
    events: list[Event],
    airports: list[Airport],
    since: date,
    now: datetime,
    pause: Callable[[float], None] = time.sleep,
) -> dict[str, dict]:
    """`backfill-flights`（HD31）：期間和 `since`～今天（香港日期）重疊的每個事件，香港
    `past?date=` 每天查出發、抵達各一次；全部的組接在一起再逐班轉換（同一班在相鄰兩天的回應各有
    一份時只留較新的，`flights_log.hkg_freshest`），補進 `flights/`（行多 `"backfill": true`；同一班
    同狀態不重寫）。回傳每個事件 `{"days": {日期: 那天回應裡的班數，失敗是 None}, "flights": 合併後
    的班數, "written": 寫了幾行}`。其他四個來源只有當天，補不到，只記 log。"""
    tz = _tz(airports)[HKG]
    today = now.astimezone(ZoneInfo(tz)).date()
    out: dict[str, dict] = {}
    first = True
    for e in events:
        start, end = max(since, e.start), min(today, e.end)
        if HKG not in e.airports or start > end:
            continue
        others = [a for a in FLIGHT_FETCHERS if a != HKG and a in e.airports]
        if others:
            log.warning("事件 %s：%s 的航班資料只有當天，補不到", e.id, "、".join(others))
        days: dict[str, int | None] = {}
        merged: dict[str, list] = {"departure": [], "arrival": []}
        day = start
        while day <= end:
            try:
                payload: dict[str, list] = {}
                for name, arrival in (("departure", False), ("arrival", True)):
                    if not first:
                        pause(BACKFILL_PAUSE_S)
                    first = False
                    payload[name] = flights.fetch_hkg_groups(day, arrival)
                days[f"{day}"] = len(flights_log.rows_of(HKG, payload, tz, now))
                for name, groups in payload.items():
                    merged[name].extend(groups)
            except (SourceError, ValueError) as ex:
                log.warning("事件 %s：香港 %s 的航班補不到：%s", e.id, day, ex)
                days[f"{day}"] = None
            day += timedelta(days=1)
        rows = [{**r, "backfill": True} for r in flights_log.rows_of(HKG, merged, tz, now)]
        written = store_flights(event_dir(history, e), rows)
        out[e.id] = {"days": days, "flights": len(rows), "written": written}
    return out


TDX_REGION = "taiwan"  # HD32：TDX 查 `airports.json` 這個地區的機場


def fetch_tdx_flights(
    e: Event, airports: list[Airport], fetched: datetime, d: Path, client: tdx.Client
) -> dict[str, int | None]:
    """HD32：TDX 一次請求拿事件裡的台灣機場，逐班寫進 `flights/`（`source: "tdx"`）；回傳每個機場
    寫了幾行（TDX 沒回那個機場或解析失敗是 None）。token 或請求失敗丟 `tdx.TdxError`。"""
    want = [a for a in airports if a.region == TDX_REGION and a.icao in e.airports]
    if not want:
        return {}
    data = client.fids(a.iata for a in want)
    out: dict[str, int | None] = {}
    for a in want:
        if a.iata not in data:
            out[a.icao] = None
            continue
        try:
            rows = flights_log.tdx_rows(a.icao, data[a.iata], a.tz, fetched)
            out[a.icao] = store_flights(d, rows)
        except Exception:  # 一個機場的格式怪不擋其他機場
            log.exception("事件 %s：TDX 航班 %s 解析或寫檔失敗", e.id, a.icao)
            out[a.icao] = None
    summary = "、".join(f"{k} {'失敗' if v is None else v}" for k, v in out.items())
    log.info("事件 %s：TDX 航班 %s", e.id, summary)
    return out


# ---- 每小時 ----


def hourly(
    history: Path,
    events: list[Event],
    airports: list[Airport],
    api_key: str | None,
    now: datetime,
    tdx_client: tdx.Client | None = None,
) -> dict[str, dict[str, int | None]]:
    """期間內的每個事件做四件事，各自 try；回傳每件寫了幾行（失敗是 None；航班是五個機場的
    合計，個別機場失敗只 log）。有 `tdx_client`（HD32）時航班另外存 TDX，`tdx` 是 TDX 各機場的
    合計（token 或請求失敗是 None，只 log）；沒有就沒有 `tdx` 這個鍵。"""
    out: dict[str, dict[str, int | None]] = {}
    for e in active(events, now):
        d = event_dir(history, e)
        res: dict[str, int | None] = {}
        try:
            res["metar"] = store_metars(d, fetch_metars(e, airports, api_key, now), now)
        except Exception:  # 保險：一件失敗不擋其他兩件
            log.exception("事件 %s：METAR 失敗", e.id)
            res["metar"] = None
        try:
            res["jma"] = store_positions(d, "jma", fetch_jma(e, now), now)
        except Exception:
            log.exception("事件 %s：JMA 現報失敗", e.id)
            res["jma"] = None
        try:
            res["jtwc"] = fetch_jtwc(e, d, now)
        except Exception:
            log.exception("事件 %s：JTWC 現報失敗（Actions 可能被擋）", e.id)
            res["jtwc"] = None
        try:
            res["flights"] = sum(v or 0 for v in fetch_flights(e, airports, now, d).values())
        except Exception:
            log.exception("事件 %s：航班失敗", e.id)
            res["flights"] = None
        if tdx_client is not None:
            try:
                written = fetch_tdx_flights(e, airports, now, d, tdx_client)
                res["tdx"] = sum(v or 0 for v in written.values())
            except SourceError as ex:
                log.warning("事件 %s：TDX 航班失敗：%s", e.id, ex)
                res["tdx"] = None
            except Exception:
                log.exception("事件 %s：TDX 航班失敗", e.id)
                res["tdx"] = None
        out[e.id] = res
    return out


def _backfill_tracks(
    history: Path,
    events: list[Event],
    since: datetime,
    airports: list[Airport] | None = None,
    now: datetime | None = None,
) -> int:
    """`backfill-tracks`（HD21）：要 eccodes，所以這裡才載入 `tracks`（`hourly` 只裝 requests）。
    HD15：接著補 WeatherNext 3（`wn3report.backfill`：起報 ≤ 現在 − 121 小時、CC BY 4.0 的那幾報，
    事件檔＋路徑）；沒有 Google 憑證或還沒核准只印一行。"""
    import tempfile
    import time

    from . import tracks, wn3report

    logging.getLogger("multiurl").setLevel(logging.WARNING)
    logging.getLogger("ecmwf").setLevel(logging.WARNING)
    t0 = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="hongthai-tracks-") as tmp:
        result = tracks.backfill_tracks(history, events, since, Path(tmp))
    for eid, res in result.items():
        print(
            f"{eid}：寫了 {len(res.written)} 份、已經有 {res.skipped}、沒有起點 {res.no_seed}、"
            f"失敗 {len(res.failed)}（{'、'.join(res.failed) or '無'}）；下載 {res.bytes:,} bytes，"
            f"{time.monotonic() - t0:.0f} 秒"
        )
        for p in res.written:
            print(f"  {p.name}")
    if airports is None:
        return 0
    with tempfile.TemporaryDirectory(prefix="hongthai-wn3-") as tmp:
        wn = wn3report.backfill(history, events, airports, since, now or utcnow(), Path(tmp))
    for eid, r in wn.items():
        print(
            f"{eid} WeatherNext 3：寫了 {len(r.written)} 份、已經有 {r.skipped}、"
            f"失敗 {len(r.failed)}（{'、'.join(r.failed) or '無'}）"
        )
        for p in r.written:
            print(f"  {p.name}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m hongthai.events", description=__doc__)
    ap.add_argument(
        "command",
        choices=("hourly", "backfill", "backfill-tracks", "backfill-metar", "backfill-flights"),
    )
    ap.add_argument("--archive", type=Path, default=Path("data"))
    ap.add_argument(
        "--from",
        dest="since",
        default="2026-10-19T00:00Z",
        help="backfill-tracks：這個時間（UTC）以後的快照；backfill-metar：這個時間以後的觀測；"
        "backfill-flights：這一天（香港日期，只看前 10 個字）起",
    )
    ap.add_argument("--events", type=Path, default=Path("events.json"))
    ap.add_argument("--airports", type=Path, default=Path("airports.json"))
    args = ap.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stderr
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    events = load_events(args.events)
    history = args.archive / "history"
    if args.command == "backfill-tracks":
        return _backfill_tracks(
            history, events, parse_time(args.since) or utcnow(), load_airports(args.airports)
        )
    if args.command == "backfill-metar":
        since = parse_time(args.since) or utcnow()
        dirs = {e.id: event_dir(history, e) for e in events}
        before = {eid: metar_coverage(d) for eid, d in dirs.items()}
        result = backfill_metar(history, events, load_airports(args.airports), since, utcnow())
        for e in events:
            if (res := result.get(e.id)) is None:
                continue
            print(
                f"{e.id}：補了 {sum(v or 0 for v in res.values())} 行；失敗 "
                + ("、".join(k for k, v in res.items() if v is None) or "無")
            )
            _print_coverage(e.airports, before[e.id], metar_coverage(dirs[e.id]))
        return 0
    if args.command == "backfill-flights":
        since_day = date.fromisoformat(args.since[:10])
        airports = load_airports(args.airports)
        result = backfill_flights(history, events, airports, since_day, utcnow())
        for eid, res in result.items():
            days = res["days"]
            ok = sum(v is not None for v in days.values())
            print(
                f"{eid}：香港補了 {ok} 天、{res['flights']} 班、寫了 {res['written']} 行；失敗 "
                + ("、".join(day for day, v in days.items() if v is None) or "無")
            )
            for day, v in days.items():
                print(f"  {day}：" + ("失敗" if v is None else f"回應裡 {v} 班"))
        return 0
    if args.command == "backfill":
        for eid, n in backfill(history, events).items():
            total = len(list((history / "events" / eid).glob("*.json")))
            print(f"{eid}：新搬 {n} 份，共 {total} 份快照")
        return 0
    now = utcnow().replace(second=0, microsecond=0)
    if not active(events, now):
        print(f"{tw_date(now)}（台灣）沒有期間內的事件")
        return 0
    result = hourly(
        history,
        events,
        load_airports(args.airports),
        os.environ.get("CWA_API_KEY"),
        now,
        tdx.Client.from_env(),
    )
    for eid, res in result.items():
        print(f"{eid}：" + "、".join(f"{k} {'失敗' if v is None else v}" for k, v in res.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
