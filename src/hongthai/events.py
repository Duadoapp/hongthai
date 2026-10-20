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
  `METAR`／`SPECI`（氣象署的是 null）。同一站同一 `observedAt` 已經有就不寫
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

來源（2026-10-20 實抓）：
- METAR：AviationWeather `metar?ids=<25 站>&format=json&hours=3`（`hours` 讓半小時一報的
  機場兩筆都拿到、排程晚了也補得回來）；欄位解碼同 `sources/taf.py`。金門、馬祖用氣象署
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

每小時三件事（METAR、JMA、JTWC）分開 try，失敗只記 log、不算整個失敗（`hourly` 一律回 0）。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shutil
import sys
from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import Airport, Event, load_airports, load_events
from .sources import SourceError, cwa, http_get, taf
from .timeutil import iso, parse_time, utcnow

log = logging.getLogger("hongthai")

TAIPEI = ZoneInfo("Asia/Taipei")
METAR_HOURS = 3
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


def fetch_metars(
    e: Event, airports: list[Airport], api_key: str | None, fetched: datetime
) -> list[dict]:
    """AviationWeather 一次請求全部站；有 `cwaStation` 的機場（金門、馬祖）另抓氣象署觀測。
    兩邊分開 try，一邊失敗另一邊照寫。"""
    aw: list = []
    try:
        r = http_get(
            taf.METAR_URL,
            params={"ids": ",".join(e.airports), "format": "json", "hours": METAR_HOURS},
            error=taf.TafError,
        )
        aw = [] if r.status_code == 204 or not r.content.strip() else r.json()
        if not isinstance(aw, list):
            raise taf.TafError("AviationWeather 回傳格式不對", "bad_format")
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


# ---- 每小時 ----


def hourly(
    history: Path,
    events: list[Event],
    airports: list[Airport],
    api_key: str | None,
    now: datetime,
) -> dict[str, dict[str, int | None]]:
    """期間內的每個事件做三件事，各自 try；回傳每件寫了幾行（失敗是 None）。"""
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
    ap.add_argument("command", choices=("hourly", "backfill", "backfill-tracks"))
    ap.add_argument("--archive", type=Path, default=Path("data"))
    ap.add_argument(
        "--from",
        dest="since",
        default="2026-10-19T00:00Z",
        help="backfill-tracks：這個時間（UTC）以後的快照",
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
        history, events, load_airports(args.airports), os.environ.get("CWA_API_KEY"), now
    )
    for eid, res in result.items():
        print(f"{eid}：" + "、".join(f"{k} {'失敗' if v is None else v}" for k, v in res.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
