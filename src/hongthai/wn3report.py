"""WeatherNext 3 的事件檔、補報與隱形旁觀（HD15、HD15b）：
`history/events/<id>/wn3/<起報 YYYYMMDDTHHMM>Z.json`，給颱風過後的報告（HD22）比對陣風、等級與路徑。

四個模式（`config.WN3_MODE`，README「資料來源與授權」）：

- `vote`（預設，HD43）：同 `private` 抓最新的主報、整份寫進私人 bucket（`observe_vote`），另外把
  逐時數字存 `points/<起報>.json`；這一報的資料交給 build 投票（日本、南韓以外），公開的檔只有
  `{"id": "wn3", "valuesHidden": true}`。同一報之後的 build 從 `points/` 讀（不查 BigQuery），
  最新一報還查不到時用私人 bucket 裡前一報的
- `private`（HD15b）：build 每報抓**最新的主報**（`wn3.latest_run`），照事件檔的格式算
  每格（含 `levels`／`level`），整份只寫進**私人 bucket**（`observe_private`、`wn3private`）；
  `latest.json` 只有 `sources.wn3` 的中繼資料（起報、`via`、掃描量、秒數），不放任何預報值或
  等級、不投票。起報超過 121 小時後每天搬進 `data` 分支（`wn3private.archive`）
- `report-only`：build 只抓「最後一個有效時間已經過了 1 小時」的那一報——起報
  `report_run(now)`＝`floor_6h(現在 − 121 小時)`，提前 1–120 小時全部在 1 小時以前，資料是
  **CC BY 4.0**（不是即時資料的實驗條款），所以可以放進公開的 `data` 分支。只有那一報的起報時間
  落在事件期間（台灣日期）才抓；同一報寫過就跳過。`latest.json` 沒有 WN3（`sources.wn3` 除外）
- `observe`：build 每報抓最新一報進 `models[]`（`build.py`），事件期間也寫這個檔與路徑

檔案格式（不縮排，51 個機場約 100 KB）：

    {"model": "wn3", "run", "mode", "via": "bigquery"|"zarr", "license", "attribution",
     ["clippedAt",] "airports": {"<ICAO>": [{"from", "to", "leadHours", <models[] 那筆的欄位>}]}}

每格從起報起算（`[run + 6k, run + 6k + 6]`，k＝0–19；`leadHours` 是格結束的提前時間），欄位同
`slots[].model.models[]` 的 `wn3` 那筆（`assess.model_entry`）：`windKt`（p50）、估算 `gustKt`、
`gustFactor`、`crosswindKt`、`rain6hMm`、`ptype`（一律 null）、`windKtP90`、`levels`、`level`。
G 用寫檔那一報的（build）或 `history/gustfactor/latest.json` 的（補報）。

補報（`backfill`，`python -m hongthai.events backfill-tracks` 一起跑；HD15b 改）：事件期間每個
主報（00／06／12／18Z，起報 ≤ `wn3.latest_run(now)`）都補，但**公開寫進 `data` 分支的只留有效
時間已經過了 1 小時的部分**：每格的 `to` ≤ 現在 − 1 小時（`clip_time`）才寫，路徑檔的點
`validAt` ≤ 同一個時間；查詢也只查到那個時間（BigQuery 的 `hours`、Zarr 的氣壓步長），之後的
數值不會下載。截過的檔多 `clippedAt`（截到哪個時間），路徑檔的 `stop` 從 `end` 改成
`clipped`；`license`、`attribution` 一律是 CC BY 4.0 的。下次補的時候能多寫幾格（`clippedAt`
之後又有格過了 1 小時）就重抓、覆寫兩個檔；整報 120 小時都寫了（沒有 `clippedAt`）而且有路徑檔
的不再抓。第一報就是 `http_403`／`no_credentials`（還沒核准）就停，不連打 40 次。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from pathlib import Path

from . import assess, tracks, wn3private
from .config import WN3_MODEL, Airport, Event
from .events import TAIPEI, active, event_dir
from .sources import wn3
from .timeutil import floor_6h, iso, parse_time
from .wn3private import ATTRIBUTION_CC, LICENSE_CC, report_path

log = logging.getLogger("hongthai")

REPORT_LAG = wn3private.PUBLIC_LAG
# 有效時間要過了這麼久才算 CC BY 4.0（條款「less than 1 hour ago and the future」是即時資料）
CLIP_LAG = timedelta(hours=1)
SLOTS = wn3.SPAN_H // wn3.STEP_H
# 即時資料（observe）的固定標註（GDM 即時資料條款 Section 4(b) 原文）
ATTRIBUTION_RT = (
    "Google WeatherNext 3 via Google BigQuery / Google Cloud Storage. © 2024-6 Google LLC, whose "
    "machine learning models were used to create the experimental data made available under the "
    f"following licence terms {wn3.TERMS_URL}. This data is intended for experimental modelling "
    "only and is not intended, validated, or approved for real world use."
)
STOP_CODES = frozenset({"http_401", "http_403", "no_credentials"})
VIA_NAMES = {"bigquery": "Google BigQuery", "zarr": "Google Cloud Storage"}
# GDM 即時資料條款 Section 4(b) 的固定標註原文（README「WeatherNext 3 的條款」）
ATTRIBUTION_4B = (
    "© 2024-6 Google LLC, whose machine learning models were used to create the experimental data "
    f"made available under the following licence terms {wn3.TERMS_URL}. This data is intended for "
    "experimental modelling only and is not intended, validated, or approved for real world use."
)


def attribution(via: str) -> str:
    """`sources.wn3.attribution`（HD43）：Section 4(b) 原文＋實際的取得管道（`Wn3Data.via`）。"""
    return f"Google WeatherNext 3 via {VIA_NAMES.get(via, VIA_NAMES['zarr'])}. {ATTRIBUTION_4B}"


def report_run(now: datetime) -> datetime:
    """`report-only` 這一報要抓的起報時間：提前 120 小時的有效時間也在 1 小時以前。"""
    return floor_6h(now - REPORT_LAG)


def report_window(run: datetime) -> tuple[datetime, datetime]:
    return run, run + timedelta(hours=wn3.SPAN_H)


def clip_time(now: datetime) -> datetime:
    """公開的檔截到這個時間（現在 − 1 小時，取到分）：格的 `to`、路徑點的 `validAt` 要 ≤ 它。"""
    return (now - CLIP_LAG).replace(second=0, microsecond=0)


def public_slots(run: datetime, clip: datetime | None) -> int:
    """`run` 那報截到 `clip` 時能寫幾格（0–20；`clip` 是 None＝不截，20 格）。"""
    if clip is None:
        return SLOTS
    n = (clip - run) // timedelta(hours=wn3.STEP_H)
    return max(0, min(SLOTS, int(n)))


def _written_slots(path: Path) -> int:
    """已經寫的檔有幾格：沒有 `clippedAt` 是 20 格（整報）；沒有檔或讀不了是 0。"""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    if not isinstance(doc, dict) or not isinstance(doc.get("run"), str):
        return 0
    clipped = doc.get("clippedAt")
    if not clipped:
        return SLOTS
    run, at = parse_time(doc["run"]), parse_time(clipped)
    return 0 if run is None or at is None else public_slots(run, at)


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
    clip: datetime | None = None,
) -> dict:
    """`clip`：只寫 `to` ≤ 這個時間的格（補抓，HD15b）；真的截掉格時多 `clippedAt`。"""
    run = data.run
    n = public_slots(run, clip)
    slots = [
        (run + timedelta(hours=h), run + timedelta(hours=h + wn3.STEP_H))
        for h in range(0, n * wn3.STEP_H, wn3.STEP_H)
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
    realtime = mode in ("observe", "private", "vote")
    doc = {
        "model": "wn3",
        "run": iso(run),
        "mode": mode,
        "via": data.via,
        "license": wn3.TERMS_URL if realtime else LICENSE_CC,
        "attribution": ATTRIBUTION_RT if realtime else ATTRIBUTION_CC,
    }
    if n < SLOTS:
        doc["clippedAt"] = iso(clip)
    doc["airports"] = out
    return doc


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


def public_track(
    d: Path,
    e: Event,
    data: wn3.Wn3Data,
    dl: tracks.Downloads,
    clip: datetime | None,
) -> dict | None:
    """補抓的路徑檔（HD15b）：同 `tracks.mslp_doc`，但只用有效時間 ≤ `clip` 的氣壓、點的 `validAt`
    ≤ `clip`；截過的多 `clippedAt`、`stop` 的 `end` 改 `clipped`；一律標 CC BY 4.0。找不到起點回
    None；沒有氣壓丟 `TracksError`。"""
    run = data.run
    seed = tracks.find_seed(d, run, e, lambda: tracks.observed_seed(dl, e, run))
    if seed is None:
        return None
    last = run + timedelta(hours=wn3.SPAN_H)
    last = last if clip is None else min(last, clip)
    fields = {t: f for t, f in grid_fields(data).items() if t <= last}
    doc = tracks.mslp_doc("wn3", run, seed, _need(fields, data))
    if public_slots(run, clip) < SLOTS:
        doc["points"] = [p for p in doc["points"] if (parse_time(p["validAt"]) or run) <= clip]
        if doc["stop"] == "end":
            doc["stop"] = "clipped"
        doc["clippedAt"] = iso(clip)
    doc["license"], doc["attribution"] = LICENSE_CC, ATTRIBUTION_CC
    return doc


def backfill(
    history: Path,
    events: Sequence[Event],
    airports: Sequence[Airport],
    since: datetime,
    now: datetime,
    workdir: Path,
    fetch: Callable[..., wn3.Wn3Data] = wn3.fetch,
) -> dict[str, Wn3Result]:
    """補事件期間的報（HD15b）：`since` 以後、起報 ≤ `wn3.latest_run(now)` 的每個主報，公開的只寫到
    `clip_time(now)`（查詢也只查到那裡）。事件檔與路徑檔都已經寫到現在能寫的格數就跳過；能多寫幾格
    （或少了路徑檔）就重抓、覆寫兩個檔。"""
    factors = saved_factors(history)
    clip = clip_time(now)
    dl = tracks.Downloads(workdir)
    out: dict[str, Wn3Result] = {}
    for e in events:
        res = Wn3Result()
        out[e.id] = res
        d = event_dir(history, e)
        for run in event_runs(e, since, wn3.latest_run(now)):
            n = public_slots(run, clip)
            rp, tp = report_path(d, run), tracks.track_path(d, run, "wn3")
            if n == 0 or min(_written_slots(rp), _written_slots(tp)) >= n:
                res.skipped += 1
                continue
            try:
                end = run + timedelta(hours=n * wn3.STEP_H)
                data = fetch(airports, run, run, end, mslp=True)
            except wn3.Wn3Error as err:
                log.warning("WeatherNext 3 %s 補不到（%s）：%s", iso(run), err.code, err)
                res.failed.append(f"wn3@{iso(run)}")
                if err.code in STOP_CODES:
                    log.warning("WeatherNext 3 還沒核准或沒有憑證，不再往下補")
                    return out
                continue
            write_report(rp, report_doc(data, airports, factors, "report-only", clip))
            res.written.append(rp)
            log.info("事件 %s：WeatherNext 3 %s → %s（%d 格）", e.id, iso(run), rp, n)
            try:
                doc = public_track(d, e, data, dl, clip)
            except Exception as err:  # 路徑抽不出來不擋事件檔與下一報
                log.warning("事件 %s：wn3 %s 的路徑抽不出來：%s", e.id, iso(run), err)
                res.failed.append(f"wn3@{iso(run)}")
                continue
            if doc is None:
                log.warning("事件 %s：wn3 %s 找不到起點（沒有現報），不寫路徑", e.id, iso(run))
                continue
            tracks.write_doc(tp, doc)
            res.written.append(tp)
    return out


@dataclass
class PrivateResult:
    """隱形旁觀／投票這一報（HD15b、HD43）：`stored` 是 `written`（查了、寫進私人 bucket）、
    `exists`（已經有了，沒查 BigQuery；`private` 時 `data` 是 None，`vote` 時是從 `points/` 讀的）或
    `previous`（`vote`：最新一報查不到，用私人 bucket 裡前一報的，`latest_error` 是查詢的錯誤碼）。
    `queried`：這一報真的查了 BigQuery／Zarr（`sources.wn3` 才放掃描量）。"""

    run: datetime
    stored: str
    data: wn3.Wn3Data | None = None
    queried: bool = False
    latest_error: str | None = None


def observe_private(
    airports: Sequence[Airport],
    now: datetime,
    factors: dict[str, assess.GustFactor],
    bucket: wn3private.Bucket | None = None,
    fetch: Callable[..., wn3.Wn3Data] | None = None,
) -> PrivateResult:
    """`private` 模式（HD15b）：最新的主報（`wn3.latest_run`，還沒發布就退一報）→ 事件檔格式
    （0–120 小時、含 `levels`／`level`）→ 私人 bucket `observe/<起報>.json`。同一個起報已經在
    bucket 裡就跳過（不查 BigQuery）；退一報時那一報已經有了也不退。查詢的終點是 `latest.json` 最後
    一格的結束（HD15c 的等級檔要 20 格都有資料），事件檔照樣只有起報起 120 小時。不記任何預報值。"""
    bucket = bucket or wn3private.Bucket.from_env()
    fetch = fetch or wn3.fetch
    run = wn3.latest_run(now)
    if bucket.exists(wn3private.object_name(run)):
        log.info("WeatherNext 3 隱形旁觀：%s 已經在私人 bucket，不再查", iso(run))
        return PrivateResult(run, "exists")
    prev = run - timedelta(hours=wn3.STEP_H)
    retry = not bucket.exists(wn3private.object_name(prev))
    # 退一報時那一報也要 0–120 小時：起點放前一報（這一報的提前時間照樣從 1 小時起）
    start = prev if retry else run
    # 終點也蓋住 `latest.json` 那 20 格（HD15c 的等級檔用；`floor_6h(now)` ≥ 這一報的起報）
    end = floor_6h(now) + timedelta(hours=wn3.SPAN_H)
    data = fetch(airports, run, start, end, mslp=False, retry_previous=retry)
    doc = report_doc(data, airports, factors, "private")
    stored = "written" if bucket.put_json(wn3private.object_name(data.run), doc) else "exists"
    log.info("WeatherNext 3 隱形旁觀：%s → 私人 bucket（%s）", iso(data.run), stored)
    return PrivateResult(data.run, stored, data, queried=True)


# ---- 投票（HD43 `vote`）----


def points_doc(data: wn3.Wn3Data) -> dict:
    """投票用的逐時數字（只進私人 bucket `points/`）：每小時一列
    `[有效時間, p50, 平均, p90, 風向, 雨量, 溫度]`（同 `Wn3Hour`）。"""
    return {
        "model": "wn3",
        "run": iso(data.run),
        "via": data.via,
        "airports": {
            icao: [
                [
                    iso(h.valid),
                    h.wind_kt,
                    h.wind_mean_kt,
                    h.wind_p90_kt,
                    h.wdir,
                    h.precip_mm,
                    h.temp2m_c,
                ]
                for h in hours
            ]
            for icao, hours in data.points.items()
        },
    }


def _opt(v: object) -> float | None:
    return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else None


def data_from_points(doc: dict, run: datetime) -> wn3.Wn3Data:
    """`points_doc` → `Wn3Data`（沒有掃描量）；格式不對丟 `PrivateError("gcs_bad_points")`
    （訊息不放內容）。"""
    try:
        if doc.get("model") != "wn3" or doc.get("run") != iso(run):
            raise ValueError("model／run 對不上")
        points: dict[str, list[wn3.Wn3Hour]] = {}
        for icao, rows in (doc.get("airports") or {}).items():
            hours = []
            for row in rows:
                valid = parse_time(row[0])
                if valid is None:
                    raise ValueError("沒有時間")
                hours.append(wn3.Wn3Hour(valid, *(_opt(v) for v in row[1:7])))
            points[str(icao)] = hours
        via = doc.get("via") if doc.get("via") in VIA_NAMES else "zarr"
    except (AttributeError, TypeError, ValueError, IndexError) as e:
        raise wn3private.PrivateError(
            f"私人 bucket 的 WeatherNext 3 {iso(run)} 逐時檔格式不對", "gcs_bad_points"
        ) from e
    return wn3.Wn3Data(run, points, str(via))


def load_points(bucket: wn3private.Bucket, run: datetime) -> wn3.Wn3Data:
    return data_from_points(bucket.get_json(wn3private.points_name(run)), run)


def observe_vote(
    airports: Sequence[Airport],
    now: datetime,
    factors: dict[str, assess.GustFactor],
    bucket: wn3private.Bucket | None = None,
    fetch: Callable[..., wn3.Wn3Data] | None = None,
) -> PrivateResult:
    """`vote` 模式（HD43）：最新的主報（`wn3.latest_run`）的逐時數字給 build 投票。

    - 私人 bucket 已經有這一報的 `points/` → 讀回來（不查 BigQuery）
    - 沒有 → 照 `observe_private` 查（前一報也沒有 `points/` 時，這一報還沒發布可以退一報）、
      整份事件檔格式寫 `observe/`（已經有就不寫）、逐時數字寫 `points/`
    - 查不到、但前一報有 `points/` → 用前一報的（`stored: "previous"`）
    日誌只印起報、`stored`、錯誤碼，不印任何預報值或等級。"""
    bucket = bucket or wn3private.Bucket.from_env()
    fetch = fetch or wn3.fetch
    run = wn3.latest_run(now)
    if bucket.exists(wn3private.points_name(run)):
        data = load_points(bucket, run)
        log.info("WeatherNext 3 投票：%s 從私人 bucket 讀（不再查）", iso(run))
        return PrivateResult(run, "exists", data)
    prev = run - timedelta(hours=wn3.STEP_H)
    have_prev = bucket.exists(wn3private.points_name(prev))
    start = run if have_prev else prev
    end = floor_6h(now) + timedelta(hours=wn3.SPAN_H)  # 蓋住 `latest.json` 那 20 格
    try:
        data = fetch(airports, run, start, end, mslp=False, retry_previous=not have_prev)
    except wn3.Wn3Error as e:
        if not have_prev:
            raise
        log.warning(
            "WeatherNext 3 投票：%s 查不到（%s），用私人 bucket 裡前一報 %s",
            iso(run),
            e.code,
            iso(prev),
        )
        return PrivateResult(prev, "previous", load_points(bucket, prev), latest_error=e.code)
    doc = report_doc(data, airports, factors, "vote")
    stored = "written" if bucket.put_json(wn3private.object_name(data.run), doc) else "exists"
    bucket.put_json(wn3private.points_name(data.run), points_doc(data))
    log.info("WeatherNext 3 投票：%s → 私人 bucket（%s）", iso(data.run), stored)
    return PrivateResult(data.run, "written", data, queried=True)


def targets(mode: str, now: datetime, events: Sequence[Event]) -> tuple[datetime, list[Event]]:
    """build 這一報要抓哪一報、寫進哪些事件：`observe` 是最新一報與現在期間內的事件；
    `report-only` 是 `report_run(now)` 與那一報起報時間在期間內的事件。"""
    if mode == "observe":
        return wn3.latest_run(now), active(events, now)
    run = report_run(now)
    return run, active(events, run)
