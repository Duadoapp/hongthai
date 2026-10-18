"""組 `latest.json` 與 `history/`，寫到發布目錄。`python -m hongthai.build` 執行。

目錄：
- `--archive`（預設 `data/`，Actions 裡是 `data` 分支的 checkout）：長期保存
  - `latest.json`、`history/<YYYYMMDDTHHMM>Z.json`（每次的結果）
  - `history/raw/<YYYY-MM-DD>/<HHMM>Z-<來源>.json`（TAF、METAR、天文台、氣象署、SMG 原始回應；
    SMG 是 XML，存成 `{語言: XML 原文}` 的 JSON）
  - `history/cancellations/<YYYY-MM-DD>.json`（每機場每 6 小時格的航班取消／延誤統計，日期是格的
    UTC 日期；合併規則見 `cancellations.py`。原始航班資料不存）
- `--out`（預設 `public/`，GitHub Pages 發布的內容）：`latest.json` 與 `history/*.json`
  （只放結果，不放原始快照與航班統計）

失敗處理：單一來源失敗記在 `sources.<名稱>`，其他照出。整個流程失敗（例外沒接到）時不產生新的
`latest.json`，改用上一份（先找 `--archive` 裡的，沒有就從 Pages 網址抓）重新發布，並回傳非 0。
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
from datetime import datetime
from pathlib import Path

import requests

from . import assess, cancellations
from .config import Airport, ConfirmedPeriod, load_airports, load_confirmed
from .sources import cwa, ecmwf, flights, gfs, hko, smg, taf
from .timeutil import floor_6h, iso, slot_bounds, utcnow

log = logging.getLogger("hongthai")

SCHEMA = 1
PAGES_URL = "https://duadoapp.github.io/hongthai/latest.json"
SOURCE_NAMES = ("ecmwf", "gfs", "taf", "hko", "cwa", "smg")


def _dump(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def _call(name: str, fn: Callable[[], object], status: dict) -> object | None:
    """跑一個來源；失敗記成 `ok=false`＋原因，回傳 None。"""
    t0 = time.monotonic()
    try:
        result = fn()
        status[name] = {"ok": True}
        return result
    except Exception as e:  # 任何來源出事都不能讓整份輸出失敗
        code = getattr(e, "code", None) or e.__class__.__name__
        log.warning("來源 %s 失敗（%s）：%s", name, code, e, exc_info=not hasattr(e, "code"))
        status[name] = {"ok": False, "error": code}
        return None
    finally:
        if name in status:
            status[name]["seconds"] = round(time.monotonic() - t0, 1)


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
    """航班 → 每 6 小時格的取消／延誤統計，合併寫進 `history/cancellations/`。

    回傳 `sources.flights`：抓不到的機場照舊記在 `error`；統計或寫檔失敗只 log、記在
    `statsError`，不讓 build 失敗。
    """
    out: dict[str, object] = {"ok": True}
    if fl.errors:
        out = {"ok": False, "error": ",".join(f"{k}:{v}" for k, v in fl.errors.items())}
    tz = {a.icao: a.tz for a in airports}
    stats: list[dict] = []
    errors: dict[str, str] = {}
    for icao, payload in fl.snapshots.items():
        try:
            stats += cancellations.airport_stats(icao, payload, tz[icao], now)
        except Exception as e:  # 某個機場格式突然變了，其他照算
            log.warning("航班統計 %s 失敗：%s", icao, e, exc_info=True)
            errors[icao] = f"{e.__class__.__name__}: {e}"[:120]
    try:
        for p in cancellations.store(history, stats):
            log.info("航班統計 → %s", p)
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
) -> dict:
    airports = load_airports(airports_path)
    confirmed = load_confirmed(confirmed_path)
    slot0 = floor_6h(now)
    status: dict[str, dict] = {}

    ec = _call("ecmwf", lambda: ecmwf.fetch(airports, slot0, workdir / "ecmwf"), status)
    if ec is not None:
        if ec.ens_error:
            status["ecmwf"]["ensembleOk"] = False
            status["ecmwf"]["ensembleError"] = ec.ens_error
        status["ecmwf"]["bytes"] = ec.bytes_downloaded
    gf = _call("gfs", lambda: gfs.fetch(airports, now, slot0, workdir / "gfs"), status)
    if gf is not None:
        status["gfs"]["bytes"] = gf.bytes_downloaded
    tf = _call("taf", lambda: taf.fetch(airports), status)
    hk = _call("hko", hko.fetch, status)
    cw = _call("cwa", lambda: cwa.fetch(api_key, now), status)
    sm = _call("smg", smg.fetch, status)

    history = archive / "history"
    status["flights"] = flight_stats(flights.fetch(now), airports, now, history)

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
    try:
        with tempfile.TemporaryDirectory(prefix="hongthai-") as tmp:
            latest = run(
                now=now,
                archive=args.archive,
                airports_path=args.airports,
                confirmed_path=args.confirmed,
                api_key=os.environ.get("CWA_API_KEY") or None,
                workdir=Path(tmp),
            )
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


if __name__ == "__main__":
    sys.exit(main())
