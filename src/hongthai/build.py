"""組 `latest.json` 與 `history/`，寫到發布目錄。`python -m hongthai.build` 執行。

目錄：
- `--archive`（預設 `data/`，Actions 裡是 `data` 分支的 checkout）：長期保存
  - `latest.json`、`history/<YYYYMMDDTHHMM>Z.json`（每次的結果）
  - `history/raw/<YYYY-MM-DD>/<HHMM>Z-<來源>.json`（TAF、METAR、天文台、氣象署、SMG 原始回應；
    SMG 是 XML，存成 `{語言: XML 原文}` 的 JSON）
  - `history/cancellations/<YYYY-MM-DD>.json`（每機場每 6 小時格的航班取消／延誤統計，日期是格的
    UTC 日期；合併規則見 `cancellations.py`。原始航班資料不存）
  - `history/timing/<YYYY-MM>.jsonl`（每次 build 每個來源的耗時，一行一筆，見 `Timing`）
  - `history/cancellations/unknown-statuses.json`（航班狀態對照表沒列的字串與次數，見
    `cancellations.store_unknown`）
- `--out`（預設 `public/`，GitHub Pages 發布的內容）：`latest.json` 與 `history/*.json`
  （只放結果，不放原始快照與航班統計）

失敗處理：單一來源失敗記在 `sources.<名稱>`，其他照出。整個流程失敗（例外沒接到）時不產生新的
`latest.json`，改用上一份（先找 `--archive` 裡的，沒有就從 Pages 網址抓）重新發布，並回傳非 0。

時間預算（H7）：每個來源（含航班）在 daemon 執行緒裡跑，最多等 `BUDGET_S` 秒；超過就記
`sources.<名稱> = {"ok": false, "error": "timeout", "seconds": <預算>}`、不等它，繼續下一個來源
（被放棄的執行緒怎麼收尾見 `budget.py`）。

模式沿用（H7；H10 改成往前找）：`ecmwf` 或 `gfs` 失敗時，從「最近一份有該模式資料」的結果把
同一機場、同一 `from` 的 `model.ec`／`model.gfs` 抄過來，等級照常算（`reuse_models`）。哪一份由
`find_reuse_source` 找：`--archive` 的 `history/<時間>.json` 由新到舊，第一份 `sources.<名稱>.ok` 是
`true`（自己也在沿用的不算）而且 `runs.<鍵>` 離現在 `REUSE_MAX_AGE`（24 小時）內的；archive 裡找不到
才退回上一份 `latest.json`（`previous_latest`，H7 的做法）。`sources.<名稱>.ok` 維持 `false`，另加
`reusedFrom`（那一份的 `generatedAt`）；`runs` 用那一份的（舊預報的真實時次）。模式時次超過 24 小時
就不沿用（系集與 HRES 各自判斷），所以連續失敗時 24 小時後自然停掉。TAF、METAR、警報不沿用。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
import tempfile
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import requests

from . import assess, budget, cancellations
from .config import Airport, ConfirmedPeriod, Thresholds, load_airports, load_confirmed
from .sources import cwa, ecmwf, flights, gfs, hko, smg, taf
from .timeutil import floor_6h, iso, parse_time, slot_bounds, utcnow

log = logging.getLogger("hongthai")

SCHEMA = 1
PAGES_URL = "https://duadoapp.github.io/hongthai/latest.json"
SOURCE_NAMES = ("ecmwf", "gfs", "taf", "hko", "cwa", "smg")

# 每個來源的時間預算（秒）。2026-10-18 實測：ecmwf 約 90–240（入口 0.5–1.4 MB/s；H10 起 HRES
# 一報約 82 MB＋系集約 10 MB）、gfs 約 110（NOMADS）、flights 約 20、其他幾秒。
# 總和 750 秒（12.5 分鐘），`build.yml` 那一步的上限是 15 分鐘。
BUDGET_S: dict[str, float] = {
    "ecmwf": 300,  # HRES＋系集，含鏡像切換
    "gfs": 180,
    "taf": 45,  # TAF 與 METAR 同一個來源，各一個請求
    "hko": 30,
    "smg": 30,
    "cwa": 45,
    "flights": 120,  # 抓＋統計＋寫檔
}

REUSE_MAX_AGE = timedelta(hours=24)
# 模式來源 → (`model` 裡的鍵, [(`runs` 的鍵, 那一報決定的欄位)])；系集與 HRES 的時次各自判斷期限
REUSE_FIELDS: dict[str, tuple[str, tuple[tuple[str, tuple[str, ...]], ...]]] = {
    "ecmwf": (
        "ec",
        (("ecmwf", ("hresGustMs", "crosswindKt")), ("ecmwfEns", ("p10", "p15", "p25"))),
    ),
    "gfs": ("gfs", (("gfs", ("gustMs", "crosswindKt")),)),
}


def _dump(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


class Timing:
    """`history/timing/<YYYY-MM>.jsonl`：每個來源一跑完就 append 一行並關檔，不等全部結束。

    `build.yml` 的「推 data 分支」是 `if: always()`，所以「產生 latest.json」被 Actions 砍掉時，
    已經寫進去的行也會推上去；沒有 `done` 那行就表示那次被砍了。欄位名固定（主對話直接看這個檔）：
    - 開始：`{"run", "source": "start", "ok": true, "seconds": 0, "commit"}`
    - 每個來源：`{"run", "source", "ok", "error", "seconds", "bytes"}`，ecmwf 與 gfs 多 `mirror`
    - 結束：`{"run", "source": "done", "ok": <有沒有產出 latest.json>, "seconds": <總秒數>}`
    """

    def __init__(self, archive: Path, now: datetime):
        self.path = archive / "history" / "timing" / f"{now:%Y-%m}.jsonl"
        self.run = iso(now)

    def write(self, **fields: object) -> None:
        line = json.dumps({"run": self.run, **fields}, ensure_ascii=False)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError as e:  # 耗時紀錄寫不了不能讓 build 失敗
            log.warning("耗時紀錄寫不進 %s：%s", self.path, e)

    def source(self, name: str, st: dict, ctx: budget.Context) -> None:
        fields: dict[str, object] = {
            "source": name,
            "ok": st["ok"],
            "error": None if st["ok"] else st.get("error"),
            "seconds": st["seconds"],
            "bytes": st.get("bytes", ctx.bytes),
        }
        if name in ("ecmwf", "gfs"):
            fields["mirror"] = st.get("mirror", ctx.notes.get("mirror"))
        self.write(**fields)


def _call(
    name: str,
    fn: Callable[[], object],
    status: dict,
    timing: Timing | None = None,
    extra: Callable[[object], dict] | None = None,
) -> object | None:
    """在 `BUDGET_S[name]` 秒內跑一個來源；失敗或超時記成 `ok=false`＋原因，回傳 None。

    成功時 `extra(結果)` 回傳的欄位併進 `sources.<名稱>`。跑完立刻寫一行耗時紀錄。
    """
    limit = BUDGET_S[name]
    out = budget.run(name, fn, limit)
    result = None
    if out.timed_out:
        log.warning("來源 %s 超過 %s 秒的預算，放棄、繼續下一個", name, limit)
        status[name] = {"ok": False, "error": "timeout", "seconds": float(limit)}
    elif out.error is not None:
        e = out.error
        code = getattr(e, "code", None) or e.__class__.__name__
        log.warning(
            "來源 %s 失敗（%s）：%s",
            name,
            code,
            e,
            exc_info=None if hasattr(e, "code") else (type(e), e, e.__traceback__),
        )
        status[name] = {"ok": False, "error": code, "seconds": round(out.seconds, 1)}
    else:
        result = out.result
        status[name] = {"ok": True, "seconds": round(out.seconds, 1)}
        if extra is not None:
            status[name].update(extra(result))
    if timing is not None:
        timing.source(name, status[name], out.context)
    return result


def _ecmwf_extra(ec: ecmwf.EcmwfData) -> dict:
    d: dict[str, object] = {}
    if ec.ens_error:
        d["ensembleOk"] = False
        d["ensembleError"] = ec.ens_error
    d["bytes"] = ec.bytes_downloaded
    if ec.mirror:
        d["mirror"] = ec.mirror
    return d


def _gfs_extra(g: gfs.GfsData) -> dict:
    d: dict[str, object] = {"bytes": g.bytes_downloaded}
    if g.mirror:
        d["mirror"] = g.mirror
    return d


def _is_num(v: object) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool)


def _rescore(slot: dict, th: Thresholds) -> None:
    """模式值換掉之後重算模式層等級、一致性、落差與整格等級（和 `assess.assess_slots` 同一套規則；
    官方層與已確認不受模式影響，維持原樣）。"""
    m = slot["model"]
    m["level"] = assess.model_level(m["ec"], m["gfs"], th)
    m["agreement"] = assess.agreement(m["ec"], m["gfs"], th)
    if slot["basis"] in ("model", "none"):
        slot["level"], slot["basis"] = (m["level"], "model") if m["level"] else ("unknown", "none")
    off = slot["official"]
    slot["gap"] = off is not None and m["level"] is not None and off["level"] != m["level"]


def _run_time(doc: dict, run_key: str) -> datetime | None:
    runs = doc.get("runs") if isinstance(doc.get("runs"), dict) else {}
    run = runs.get(run_key)
    try:
        return parse_time(run) if isinstance(run, str) else None
    except ValueError:
        return None


def _history_files(archive: Path) -> list[tuple[datetime, Path]]:
    """`history/<YYYYMMDDTHHMM>Z.json`，由新到舊（檔名不是這個格式的跳過）。"""
    out = []
    for p in (archive / "history").glob("*.json"):
        try:
            t = datetime.strptime(p.stem, "%Y%m%dT%H%MZ").replace(tzinfo=UTC)
        except ValueError:
            continue
        out.append((t, p))
    return sorted(out, reverse=True)


def find_reuse_source(archive: Path, name: str, now: datetime) -> dict | None:
    """由新到舊找第一份 `sources.<name>.ok` 是 `true`、`runs.<主要的鍵>` 在 24 小時內的結果。

    主要的鍵是 `REUSE_FIELDS[name]` 的第一個（ecmwf 是 HRES 的 `ecmwf`，gfs 是 `gfs`）。
    一份結果的 `runs` 不會晚於它的 `generatedAt`，所以檔名早於 `now - REUSE_MAX_AGE` 就不用
    再往前找。
    """
    run_key = REUSE_FIELDS[name][1][0][0]
    for t, p in _history_files(archive):
        if t >= now:
            continue
        if now - t > REUSE_MAX_AGE:
            break
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            log.warning("歷史結果 %s 讀不了，跳過", p)
            continue
        if not isinstance(doc, dict) or not isinstance(doc.get("generatedAt"), str):
            continue
        sources = doc.get("sources")
        src = sources.get(name) if isinstance(sources, dict) else None
        if not isinstance(src, dict) or src.get("ok") is not True:
            continue
        run_t = _run_time(doc, run_key)
        if run_t is not None and now - run_t <= REUSE_MAX_AGE:
            return doc
    return None


def reuse_models(
    latest: dict,
    prev: dict[str, dict | None],
    failed: list[str],
    now: datetime,
    airports: list[Airport],
) -> None:
    """失敗的模式來源（`ecmwf`／`gfs`）從 `prev[來源名稱]` 那一份抄同一機場、同一 `from` 的值。

    每個來源可以抄不同份（`find_reuse_source` 各自找）。`runs.<鍵>` 離 `now` 超過 `REUSE_MAX_AGE`
    的那一報不抄（系集與 HRES 各自判斷）；有抄到的才把 `runs` 換成那一份的、在 `sources.<名稱>` 加
    `reusedFrom`。`ok`／`error` 不動。
    """

    def slots_of(doc: dict) -> dict[tuple[object, object], dict]:
        out: dict[tuple[object, object], dict] = {}
        for a in doc.get("airports") or []:
            for s in (a.get("slots") or []) if isinstance(a, dict) else []:
                if isinstance(s, dict) and isinstance(s.get("model"), dict):
                    out[(a.get("icao"), s.get("from"))] = s["model"]
        return out

    # 先算好要改什麼，再一次套用（上一份格式怪也不會改到一半）
    updates: list[tuple[str, dict, str, str, float]] = []
    runs: dict[str, str] = {}
    reused_from: dict[str, str] = {}
    for name in failed:
        doc = prev.get(name)
        if not isinstance(doc, dict) or not isinstance(doc.get("generatedAt"), str):
            continue
        prev_slots = slots_of(doc)
        key, parts = REUSE_FIELDS[name]
        for run_key, fields in parts:
            run_t = _run_time(doc, run_key)
            if run_t is None or now - run_t > REUSE_MAX_AGE:
                log.info(
                    "%s 那份的 runs.%s 超過 24 小時或沒有，不沿用", doc["generatedAt"], run_key
                )
                continue
            n = 0
            for a in latest["airports"]:
                for s in a["slots"]:
                    old = prev_slots.get((a["icao"], s["from"]), {}).get(key)
                    if not isinstance(old, dict):
                        continue
                    for f in fields:
                        if _is_num(old.get(f)):
                            updates.append((a["icao"], s, key, f, old[f]))
                            n += 1
            if n:
                runs[run_key] = iso(run_t)
                reused_from[name] = doc["generatedAt"]
    if not updates:
        return

    th = {a.icao: a.thresholds for a in airports}
    touched: dict[int, tuple[dict, str]] = {}
    for icao, s, key, f, v in updates:
        s["model"][key][f] = v
        touched[id(s)] = (s, icao)
    for s, icao in touched.values():
        _rescore(s, th[icao])
    latest["runs"].update(runs)
    for name, generated_at in reused_from.items():
        latest["sources"][name]["reusedFrom"] = generated_at
        log.info("%s 失敗，沿用 %s 那份的模式資料（runs：%s）", name, generated_at, runs)


def collect_warnings(
    airport: Airport,
    hko_data: hko.HkoData | None,
    cwa_data: cwa.CwaData | None,
    smg_data: smg.SmgData | None = None,
) -> list[assess.ActiveWarning]:
    out: list[assess.ActiveWarning] = []
    if "hko" in airport.warning_sources and hko_data and hko_data.signal:
        s = hko_data.signal
        out.append(assess.ActiveWarning("hko", "tc_signal", s.level, s.text, s.issued_at, s.code))
    if "smg" in airport.warning_sources and smg_data and smg_data.signal:
        s = smg_data.signal
        out.append(
            assess.ActiveWarning(
                "smg", "tc_signal", s.level, s.text, s.issued_at, s.code, s.detail or None
            )
        )
    if "cwa" in airport.warning_sources and cwa_data:
        for w in cwa.for_airport(cwa_data.bulletins, airport.cwa_areas, airport.name):
            out.append(
                assess.ActiveWarning(
                    "cwa", w.kind, w.level, w.text, w.issued_at, detail=w.detail or None
                )
            )
    return out


def warning_json(w: assess.ActiveWarning) -> dict:
    d: dict[str, object] = {
        "source": w.source,
        "kind": w.kind,
        "level": w.level,
        "text": w.text,
        "issuedAt": w.issued_at,
    }
    if w.code:
        d["code"] = w.code
    if w.detail:
        d["detail"] = w.detail
    return d


def metar_json(m: taf.Metar | None) -> dict | None:
    if m is None:
        return None
    return {
        "observedAt": iso(m.observed),
        "windDirDeg": m.wdir,
        "windKt": m.wind_kt,
        "gustKt": m.gust_kt,
        "raw": m.raw,
    }


def taf_json(t: taf.TafInfo | None) -> dict | None:
    if t is None:
        return None
    return {
        "issuedAt": iso(t.issued),
        "validFrom": iso(t.valid_from),
        "validTo": iso(t.valid_to),
        "raw": t.raw,
    }


def confirmed_json(c: ConfirmedPeriod) -> dict:
    return {"from": iso(c.start), "to": iso(c.end), "note": c.note}


def assemble(
    *,
    now: datetime,
    airports: list[Airport],
    confirmed: list[ConfirmedPeriod],
    status: dict,
    ec: ecmwf.EcmwfData | None,
    gf: gfs.GfsData | None,
    tf: taf.TafData | None,
    hk: hko.HkoData | None,
    cw: cwa.CwaData | None,
    sm: smg.SmgData | None = None,
) -> dict:
    """純組裝：各來源結果（失敗的是 None）→ `latest.json` 的 dict。"""
    slots = slot_bounds(now)
    window_start, window_end = slots[0][0], slots[-1][1]
    out_airports = []
    for a in airports:
        warns = collect_warnings(a, hk, cw, sm)
        mine = [c for c in confirmed if c.airport == a.icao]
        taf_info = tf.tafs.get(a.icao) if tf else None
        metar = tf.metars.get(a.icao) if tf else None
        slot_list = assess.assess_slots(
            now=now,
            slots=slots,
            thresholds=a.thresholds,
            ec=ec.points.get(a.icao) if ec else None,
            gfs=gf.points.get(a.icao) if gf else None,
            taf_periods=taf_info.periods if taf_info else None,
            warnings=warns,
            confirmed=mine,
            runways=a.runways,
            metar=metar,
        )
        out_airports.append(
            {
                "icao": a.icao,
                "iata": a.iata,
                "tz": a.tz,
                "name": a.name,
                "warnings": [warning_json(w) for w in warns],
                "metar": metar_json(metar),
                "taf": taf_json(taf_info),
                "slots": slot_list,
                "confirmed": [
                    confirmed_json(c) for c in mine if c.start < window_end and c.end > window_start
                ],
            }
        )
    return {
        "schema": SCHEMA,
        "generatedAt": iso(now),
        "runs": {
            "ecmwf": iso(ec.run) if ec else None,
            "ecmwfEns": iso(ec.ens_run) if ec else None,
            "gfs": iso(gf.run) if gf else None,
        },
        "sources": {
            **{n: status.get(n, {"ok": False, "error": "skipped"}) for n in SOURCE_NAMES},
            **{k: v for k, v in status.items() if k not in SOURCE_NAMES},
        },
        "airports": out_airports,
    }


def flight_stats(
    fl: flights.FlightsData, airports: list[Airport], now: datetime, history: Path
) -> dict:
    """航班 → 每 6 小時格的取消／延誤統計，合併寫進 `history/cancellations/`；看不懂的狀態字串
    合併進 `history/cancellations/unknown-statuses.json`。

    回傳 `sources.flights`：抓不到的機場照舊記在 `error`；統計或寫檔失敗只 log、記在
    `statsError`，不讓 build 失敗。
    """
    out: dict[str, object] = {"ok": True}
    if fl.errors:
        out = {"ok": False, "error": ",".join(f"{k}:{v}" for k, v in fl.errors.items())}
    tz = {a.icao: a.tz for a in airports}
    stats: list[dict] = []
    unknown = {}
    errors: dict[str, str] = {}
    for icao, payload in fl.snapshots.items():
        try:
            parsed = cancellations.flights_of(icao, payload, tz[icao], now)
            stats += cancellations.slot_stats(icao, parsed, now)
            unknown[icao] = cancellations.unknown_statuses(parsed)
        except Exception as e:  # 某個機場格式突然變了，其他照算
            log.warning("航班統計 %s 失敗：%s", icao, e, exc_info=True)
            errors[icao] = f"{e.__class__.__name__}: {e}"[:120]
    budget.check_cancelled()  # 超過預算被放棄了就不寫檔
    try:
        for p in cancellations.store(history, stats):
            log.info("航班統計 → %s", p)
        cancellations.store_unknown(history, unknown, now)
    except (OSError, ValueError, KeyError, TypeError) as e:
        log.warning("航班統計寫檔失敗：%s", e, exc_info=True)
        errors["store"] = f"{e.__class__.__name__}: {e}"[:120]
    if errors:
        out["statsError"] = "; ".join(f"{k}:{v}" for k, v in errors.items())
    return out


def run(
    *,
    now: datetime,
    archive: Path,
    airports_path: Path,
    confirmed_path: Path,
    api_key: str | None,
    workdir: Path,
    pages_url: str = PAGES_URL,
    timing: Timing | None = None,
) -> dict:
    airports = load_airports(airports_path)
    confirmed = load_confirmed(confirmed_path)
    slot0 = floor_6h(now)
    status: dict[str, dict] = {}
    history = archive / "history"

    ec = _call(
        "ecmwf",
        lambda: ecmwf.fetch(airports, slot0, workdir / "ecmwf"),
        status,
        timing,
        _ecmwf_extra,
    )
    gf = _call(
        "gfs",
        lambda: gfs.fetch(airports, now, slot0, workdir / "gfs"),
        status,
        timing,
        _gfs_extra,
    )
    tf = _call("taf", lambda: taf.fetch(airports), status, timing)
    hk = _call("hko", hko.fetch, status, timing)
    cw = _call("cwa", lambda: cwa.fetch(api_key, now), status, timing)
    sm = _call("smg", smg.fetch, status, timing)
    _call(
        "flights",
        lambda: flight_stats(flights.fetch(now), airports, now, history),
        status,
        timing,
        lambda r: r,
    )

    latest = assemble(
        now=now,
        airports=airports,
        confirmed=confirmed,
        status=status,
        ec=ec,
        gf=gf,
        tf=tf,
        hk=hk,
        cw=cw,
        sm=sm,
    )
    failed = [n for n, d in (("ecmwf", ec), ("gfs", gf)) if d is None]
    if failed:
        sources: dict[str, dict | None] = {n: find_reuse_source(archive, n, now) for n in failed}
        if any(d is None for d in sources.values()):
            prev = previous_latest(archive, pages_url)  # archive 裡找不到的退回上一份（H7 的做法）
            sources = {n: d if d is not None else prev for n, d in sources.items()}
        reuse_models(latest, sources, failed, now, airports)

    stamp = f"{now:%Y%m%dT%H%M}Z"
    raw_dir = history / "raw" / f"{now:%Y-%m-%d}"
    if tf is not None:
        _dump(raw_dir / f"{now:%H%M}Z-taf.json", tf.raw["taf"])
        _dump(raw_dir / f"{now:%H%M}Z-metar.json", tf.raw["metar"])
    if hk is not None:
        _dump(raw_dir / f"{now:%H%M}Z-hko.json", hk.raw)
    if cw is not None:
        _dump(raw_dir / f"{now:%H%M}Z-cwa.json", cw.raw)
    if sm is not None:
        _dump(raw_dir / f"{now:%H%M}Z-smg.json", sm.raw)
    _dump(history / f"{stamp}.json", latest)
    _dump(archive / "latest.json", latest)
    return latest


def publish(out: Path, archive: Path, latest: dict | None) -> None:
    """把 latest 與歷次結果（`history/*.json`，不含 raw／cancellations）放進發布目錄。"""
    out.mkdir(parents=True, exist_ok=True)
    if latest is not None:
        _dump(out / "latest.json", latest)
    hist_out = out / "history"
    hist_out.mkdir(parents=True, exist_ok=True)
    for p in sorted((archive / "history").glob("*.json")):
        shutil.copy2(p, hist_out / p.name)


def previous_latest(archive: Path, pages_url: str) -> dict | None:
    p = archive / "latest.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            log.warning("archive 的 latest.json 壞了")
    try:
        r = requests.get(pages_url, timeout=30)
        r.raise_for_status()
        return r.json()
    except (requests.RequestException, ValueError) as e:
        log.error("從 Pages 抓上一份 latest.json 也失敗：%s", e)
        return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m hongthai.build", description=__doc__)
    ap.add_argument("--out", type=Path, default=Path("public"))
    ap.add_argument("--archive", type=Path, default=Path("data"))
    ap.add_argument("--airports", type=Path, default=Path("airports.json"))
    ap.add_argument("--confirmed", type=Path, default=Path("confirmed.json"))
    ap.add_argument("--pages-url", default=PAGES_URL)
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stderr
    )
    for noisy in ("urllib3", "multiurl", "ecmwf", "cfgrib"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    t0 = time.monotonic()
    now = utcnow().replace(second=0, microsecond=0)
    timing = Timing(args.archive, now)
    commit = (os.environ.get("GITHUB_SHA") or "")[:7] or None
    timing.write(source="start", ok=True, seconds=0, commit=commit)
    produced = False
    try:
        # 超時被放棄的來源執行緒可能還在往暫存目錄寫檔，清不乾淨就算了
        with tempfile.TemporaryDirectory(prefix="hongthai-", ignore_cleanup_errors=True) as tmp:
            latest = run(
                now=now,
                archive=args.archive,
                airports_path=args.airports,
                confirmed_path=args.confirmed,
                api_key=os.environ.get("CWA_API_KEY") or None,
                workdir=Path(tmp),
                pages_url=args.pages_url,
                timing=timing,
            )
        produced = True
        publish(args.out, args.archive, latest)
        ok = {k: v.get("ok") for k, v in latest["sources"].items()}
        log.info("完成，%.1f 秒；來源：%s", time.monotonic() - t0, ok)
        return 0
    except Exception:
        log.exception("整個流程失敗，改發布上一份 latest.json")
        prev = previous_latest(args.archive, args.pages_url)
        if prev is None:
            return 2
        publish(args.out, args.archive, prev)
        return 1
    finally:
        # 被放棄的來源執行緒是 daemon，不 join，程式照常結束
        timing.write(source="done", ok=produced, seconds=round(time.monotonic() - t0, 1))


if __name__ == "__main__":
    sys.exit(main())
