"""WeatherNext 3 的事件檔與補報（HD15）：`history/events/<id>/wn3/<起報 YYYYMMDDTHHMM>Z.json`，
給颱風過後的報告（HD22）比對陣風、等級與路徑。

兩個模式（`config.WN3_MODE`，README「資料來源與授權」）：

- `report-only`（預設）：build 只抓「最後一個有效時間已經過了 1 小時」的那一報——起報
  `report_run(now)`＝`floor_6h(現在 − 121 小時)`，提前 1–120 小時全部在 1 小時以前，資料是
  **CC BY 4.0**（不是即時資料的實驗條款），所以可以放進公開的 `data` 分支。只有那一報的起報時間
  落在事件期間（台灣日期）才抓；同一報寫過就跳過。`latest.json` 沒有 WN3（`sources.wn3` 除外）
- `observe`：build 每報抓最新一報進 `models[]`（`build.py`），事件期間也寫這個檔與路徑

檔案格式（不縮排，51 個機場約 100 KB）：

    {"model": "wn3", "run", "mode", "via": "bigquery"|"zarr", "license", "attribution",
     "airports": {"<ICAO>": [{"from", "to", "leadHours", <models[] 那筆的欄位>}]}}

每格從起報起算（`[run + 6k, run + 6k + 6]`，k＝0–19；`leadHours` 是格結束的提前時間），欄位同
`slots[].model.models[]` 的 `wn3` 那筆（`assess.model_entry`）：`windKt`（p50）、估算 `gustKt`、
`gustFactor`、`crosswindKt`、`rain6hMm`、`ptype`（一律 null）、`windKtP90`、`levels`、`level`。
G 用寫檔那一報的（build）或 `history/gustfactor/latest.json` 的（補報）。

補報（`backfill`，`python -m hongthai.events backfill-tracks` 一起跑）：事件期間每個主報
（00／06／12／18Z）起報 ≤ `report_run(now)` 的，沒有事件檔或路徑檔就抓（BigQuery＋Zarr 氣壓）、
寫兩個檔。第一報就是 `http_403`／`no_credentials`（還沒核准）就停，不連打 40 次。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from pathlib import Path

from . import assess, tracks
from .config import WN3_MODEL, Airport, Event
from .events import TAIPEI, active, event_dir
from .sources import wn3
from .timeutil import floor_6h, iso

log = logging.getLogger("hongthai")

REPORT_LAG = timedelta(hours=wn3.SPAN_H + 1)
LICENSE_CC = "CC BY 4.0"
ATTRIBUTION_CC = "Google WeatherNext 3, © 2026 Google LLC, CC BY 4.0"
# 即時資料（observe）的固定標註（GDM 即時資料條款 Section 4(b) 原文）
ATTRIBUTION_RT = (
    "Google WeatherNext 3 via Google BigQuery / Google Cloud Storage. © 2024-6 Google LLC, whose "
    "machine learning models were used to create the experimental data made available under the "
    f"following licence terms {wn3.TERMS_URL}. This data is intended for experimental modelling "
    "only and is not intended, validated, or approved for real world use."
)
STOP_CODES = frozenset({"http_401", "http_403", "no_credentials"})


def report_run(now: datetime) -> datetime:
    """`report-only` 這一報要抓的起報時間：提前 120 小時的有效時間也在 1 小時以前。"""
    return floor_6h(now - REPORT_LAG)


def report_window(run: datetime) -> tuple[datetime, datetime]:
    return run, run + timedelta(hours=wn3.SPAN_H)


def report_path(d: Path, run: datetime) -> Path:
    return d / "wn3" / f"{run:%Y%m%dT%H%M}Z.json"


def saved_factors(history: Path) -> dict[str, assess.GustFactor]:
    """`history/gustfactor/latest.json` 的每機場 G（補報用）；讀不了回空的（全部 1.4）。"""
    try:
        doc = json.loads((history / "gustfactor" / "latest.json").read_text(encoding="utf-8"))
        out = {}
        for icao, a in (doc.get("airports") or {}).items():
            g = a.get("g")
            if isinstance(g, int | float) and not isinstance(g, bool):
                out[icao] = assess.GustFactor(float(g), str(a.get("basis") or "default"))
        return out
    except (OSError, ValueError, AttributeError):
        return {}


def report_doc(
    data: wn3.Wn3Data,
    airports: Sequence[Airport],
    factors: dict[str, assess.GustFactor],
    mode: str,
) -> dict:
    run = data.run
    slots = [
        (run + timedelta(hours=h), run + timedelta(hours=h + wn3.STEP_H))
        for h in range(0, wn3.SPAN_H, wn3.STEP_H)
    ]
    out: dict[str, list[dict]] = {}
    for a in airports:
        f = factors.get(a.icao, assess.DEFAULT_GUST_FACTOR)
        rows = []
        for start, end in slots:
            src = assess.wn3_for_slot(data.points.get(a.icao), start, end, a.runways, f)
            entry = assess.model_entry(WN3_MODEL, {}, {}, src, {}, a.thresholds)
            entry.pop("id")
            entry.pop("run")
            rows.append(
                {
                    "from": iso(start),
                    "to": iso(end),
                    "leadHours": int((end - run).total_seconds() // 3600),
                    **entry,
                }
            )
        out[a.icao] = rows
    realtime = mode == "observe"
    return {
        "model": "wn3",
        "run": iso(run),
        "mode": mode,
        "via": data.via,
        "license": wn3.TERMS_URL if realtime else LICENSE_CC,
        "attribution": ATTRIBUTION_RT if realtime else ATTRIBUTION_CC,
        "airports": out,
    }


def write_report(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(doc, ensure_ascii=False, separators=(",", ":"))
    path.write_text(text + "\n", encoding="utf-8")


def grid_fields(data: wn3.Wn3Data) -> dict[datetime, tracks.Field]:
    return {t: tracks.grid_field(g.lats, g.lons, g.values) for t, g in sorted(data.mslp.items())}


@dataclass
class Wn3Result:
    written: list[Path] = field(default_factory=list)
    skipped: int = 0
    failed: list[str] = field(default_factory=list)


def write_event_files(
    history: Path,
    events: Sequence[Event],
    data: wn3.Wn3Data,
    airports: Sequence[Airport],
    factors: dict[str, assess.GustFactor],
    mode: str,
    workdir: Path,
    with_tracks: bool = True,
) -> Wn3Result:
    """每個事件寫 `wn3/<起報>.json`（已經有就跳過）；`with_tracks`：也抽路徑
    （`tracks/<起報>-wn3.json`；`observe` 的 build 交給來源 `tracks` 抽，這裡不抽）。"""
    res = Wn3Result()
    doc = report_doc(data, airports, factors, mode)
    fields = grid_fields(data) if with_tracks and data.mslp else {}
    tr = tracks.TracksResult()
    dl = tracks.Downloads(workdir)
    for e in events:
        d = event_dir(history, e)
        path = report_path(d, data.run)
        if path.exists():
            res.skipped += 1
        else:
            write_report(path, doc)
            res.written.append(path)
            log.info("事件 %s：WeatherNext 3 → %s", e.id, path)
        if with_tracks:
            tracks._job(tr, d, e, "wn3", data.run, dl, lambda: _need(fields, data))
    res.written += tr.written
    res.skipped += tr.skipped
    res.failed += tr.failed
    return res


def _need(fields: dict[datetime, tracks.Field], data: wn3.Wn3Data) -> dict:
    if not fields:
        raise tracks.TracksError(
            f"WeatherNext 3 {iso(data.run)} 沒有海平面氣壓（{data.mslp_error}）", "no_mslp"
        )
    return fields


def event_runs(e: Event, since: datetime, until: datetime) -> list[datetime]:
    """事件期間（台灣日期 `from` 00:00～`to` 24:00）裡、[since, until] 的主報。"""
    lo = datetime.combine(e.start, time(0), TAIPEI).astimezone(UTC)
    hi = datetime.combine(e.end + timedelta(days=1), time(0), TAIPEI).astimezone(UTC)
    t = floor_6h(max(lo, since))
    if t < max(lo, since):
        t += timedelta(hours=wn3.STEP_H)
    out = []
    while t < hi and t <= until:
        out.append(t)
        t += timedelta(hours=wn3.STEP_H)
    return out


def backfill(
    history: Path,
    events: Sequence[Event],
    airports: Sequence[Airport],
    since: datetime,
    now: datetime,
    workdir: Path,
    fetch: Callable[..., wn3.Wn3Data] = wn3.fetch,
) -> dict[str, Wn3Result]:
    """補過去的報（CC BY 4.0 的部分，起報 ≤ `report_run(now)`）；已經有兩個檔的跳過。"""
    factors = saved_factors(history)
    out: dict[str, Wn3Result] = {}
    for e in events:
        res = Wn3Result()
        out[e.id] = res
        d = event_dir(history, e)
        for run in event_runs(e, since, report_run(now)):
            if report_path(d, run).exists() and tracks.track_path(d, run, "wn3").exists():
                res.skipped += 1
                continue
            try:
                data = fetch(airports, run, *report_window(run), mslp=True)
            except wn3.Wn3Error as err:
                log.warning("WeatherNext 3 %s 補不到（%s）：%s", iso(run), err.code, err)
                res.failed.append(f"wn3@{iso(run)}")
                if err.code in STOP_CODES:
                    log.warning("WeatherNext 3 還沒核准或沒有憑證，不再往下補")
                    return out
                continue
            r = write_event_files(
                history, [e], data, airports, factors, "report-only", workdir, with_tracks=True
            )
            res.written += r.written
            res.skipped += r.skipped
            res.failed += r.failed
    return out


def targets(mode: str, now: datetime, events: Sequence[Event]) -> tuple[datetime, list[Event]]:
    """build 這一報要抓哪一報、寫進哪些事件：`observe` 是最新一報與現在期間內的事件；
    `report-only` 是 `report_run(now)` 與那一報起報時間在期間內的事件。"""
    if mode == "observe":
        return wn3.latest_run(now), active(events, now)
    run = report_run(now)
    return run, active(events, run)
