"""遠期關注（HD42，Shawn 2026-10-27 21:28–21:37 定案）：三套系集第 6–15 天「陣風達 49／29 節」的
成員比例。

`python -m hongthai.longrange` 執行（`.github/workflows/longrange.yml`，每天一次）；**不進
`latest.json`、不給 AI、不參與投票**，0–5 天的燈號照舊。

三套分開列、不合併：
- 歐洲系集 `ifsEns`（ECMWF ENS，51 個成員）：開放資料現成的陣風機率 `10fgg15`（≥ 15 m/s）、`10fgg25`
  （≥ 25 m/s），取機場最近格點（同 `latest.json` 的 `p29Kt`／`p49Kt`，`sources/ecmwf.py` 的
  `fetch_longrange`）
- 美國系集 `gefs`（NOAA GEFS，31 個成員，`sources/gefs.py`）：0.5° 的地面陣風 `GUST`；每個成員每個
  窗取窗內（含頭尾）6 小時整時間點的最大值，數達門檻的成員比例。b 檔沒有陣風時用 10 米風 × G
  估算（`estimated: true`）
- Google WN2 系集 `wn2Ens`（WeatherNext 2，64 個成員，經 Open-Meteo，`sources/openmeteo.py` 的
  `fetch_longrange`）：只有 10 米平均風 → 每個成員每個窗取窗內（含頭尾）最大的平均風（一位小數）
  × 機場的 G ＝ 估算陣風（`estimated: true`，同 `assess.ensemble_for_slot`）

門檻：三套一律用歐洲系集機率產品的門檻 **25 m/s（48.6 節，`p49`）與 15 m/s（29.2 節，`p29`）**，
陣風取一位小數後比（`THRESHOLDS_KT`）。名稱照 `latest.json` 的 `p49Kt`／`p29Kt`。

窗（`windows`）：三套用同一組 UTC 24 小時窗，對齊歐洲系集機率產品 00Z 起報的提前 120–144、
144–168…336–360 小時，也就是**第 6–15 天的 00Z–24Z**。基準日 `base` 是「現在減 `BASE_LAG_H`
小時」那天的 00Z（11:47Z 排程跑時就是當天；半夜手動跑時是前一天，那時當天 00Z 的系集還沒出）。
每套各自找最新出齊的一報、`runs` 各自記：
- 歐洲系集：最新出到 360 小時的 00／12Z（`window_steps` 把窗換成這一報的步長；換不過去的窗是
  null）
- GEFS：從基準日 00Z 往回找出齊的（`gefs.find_run`）
- WN2：Open-Meteo 當下最新的一報（`start_date`／`end_date` 是窗的日期），起報時間問 metadata

失敗：每套在自己的時間預算（`BUDGET_S`）內跑，失敗或超時那套 `null`、其他照出（`sources.<套>`
記 `ok: false` 與原因）。三套都失敗、或整個流程出例外 → 沿用上一份（`--archive` 的
`longrange.json`，沒有就從 Pages 抓），加 `stale: true`、`staleAt`、`staleErrors` 後寫回
`--archive`（不寫 `history/`），回傳 1。

輸出（`--archive`，Actions 裡是 `data` 分支）：
- `longrange.json`：只放最新一份；**`build.py` 的 `publish` 每報複製到 GitHub Pages**（同
  `typhoons.json`），所以 Pages 上的會在下一次 build（13:05Z）後更新
- `history/longrange/<基準日>.json`：每天一份（同一天再跑覆寫），之後對照準不準

格式（不縮排）：
    {"schema": 1, "generatedAt", "stale": false, "base": "<基準日>",
     "runs": {"ifsEns", "gefs", "wn2Ens"},
     "sources": {"ifsEns": {"ok", "error", "seconds", "bytes", "mirror"},
                 "gefs": {"ok", "error", "seconds", "bytes", "files", "missing", "estimated"},
                 "wn2Ens": {"ok", "error", "seconds", "bytes", "calls", "metaError"}},
     "thresholds": {"p29Kt": 29.2, "p49Kt": 48.6, "p29Ms": 15, "p49Ms": 25},
     "gustFactor": {"generatedAt", "airports": {"<ICAO>": G}},
     "windows": [{"day": 6, "from", "to"} × 10],
     "airports": {"<ICAO>": [{"from", "to",
         "ifsEns": {"p29", "p49", "members": 51},
         "gefs": {"p29", "p49", "members": <有值的成員數>, "estimated": bool},
         "wn2Ens": {"p29", "p49", "members": <有值的成員數>, "estimated": true}} × 10]}}

比例 0–1、兩位小數；那套失敗、這一報沒涵蓋那個窗、或沒有任何成員有值時是 `null`。51 個機場都寫。
`gustFactor` 是 `history/gustfactor/latest.json`（build 每報算的 G，`gustfactor.py`）；沒有那個檔或
那個機場時用 `GUST_FACTOR_DEFAULT`。網頁怎麼顯示（任一套 `p49` ≥ 20% 那天才顯示）由 HW22 決定，
資料端每天每個機場都存。
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import tempfile
import time
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from pathlib import Path

import requests

from . import budget
from .assess import _round, estimated_gust
from .config import GUST_FACTOR_DEFAULT, Airport, load_airports
from .sources import ecmwf, gefs, openmeteo
from .sources.ecmwf import ProbWindow
from .sources.gefs import MemberPoint
from .sources.openmeteo import EnsStep, member_winds
from .timeutil import iso, utcnow
from .units import ms_to_kt

log = logging.getLogger("hongthai")

SCHEMA = 1
FILENAME = "longrange.json"
HISTORY_DIR = Path("history") / "longrange"
PAGES_URL = "https://duadoapp.github.io/hongthai/longrange.json"
FIRST_DAY = 6
DAYS = 10
BASE_LAG_H = 8  # 歐洲系集 00Z 的機率產品約 08:00Z 出爐
SOURCES = ("ifsEns", "gefs", "wn2Ens")
IFS_MEMBERS = 51
THRESHOLDS_MS = {"p29": 15, "p49": 25}
THRESHOLDS_KT = {k: round(ms_to_kt(v) or 0.0, 1) for k, v in THRESHOLDS_MS.items()}
# 每套的時間預算（秒）。2026-10-27 雲端開發機實測：GEFS 一個窗 155 個檔 14 秒、27 MB
BUDGET_S: dict[str, float] = {"ifsEns": 300, "gefs": 900, "wn2Ens": 120}

Window = tuple[datetime, datetime]


class AllFailed(RuntimeError):
    """三套都失敗；`sources` 是各套的 `sources.<套>`。"""

    def __init__(self, sources: dict[str, dict]):
        super().__init__(f"三套系集都失敗：{ {k: v.get('error') for k, v in sources.items()} }")
        self.sources = sources


def base_of(now: datetime) -> datetime:
    """基準日：`now − BASE_LAG_H` 小時那天的 00Z。"""
    t = now - timedelta(hours=BASE_LAG_H)
    return t.replace(hour=0, minute=0, second=0, microsecond=0)


def windows_of(base: datetime) -> list[Window]:
    """第 6–15 天（基準日 00Z 起報的提前 120–144…336–360 小時）的 10 個 24 小時窗。"""
    return [
        (base + timedelta(days=FIRST_DAY - 1 + i), base + timedelta(days=FIRST_DAY + i))
        for i in range(DAYS)
    ]


def _share(gusts: Sequence[float]) -> dict:
    """成員的陣風（節，已取一位小數）→ 達門檻的比例（兩位小數）與成員數。"""
    n = len(gusts)
    return {
        **{k: round(sum(g >= kt for g in gusts) / n, 2) for k, kt in THRESHOLDS_KT.items()},
        "members": n,
    }


def ifs_entry(windows: Sequence[ProbWindow] | None, start: datetime, end: datetime) -> dict | None:
    """歐洲系集：同一個窗的 `10fgg15`／`10fgg25`（已經是 0–1）；沒有這個窗或兩個都沒值是 None。"""
    w = next((w for w in windows or [] if w.start == start and w.end == end), None)
    if w is None or (w.p15 is None and w.p25 is None):
        return None
    return {"p29": _round(w.p15, 2), "p49": _round(w.p25, 2), "members": IFS_MEMBERS}


def gefs_entry(members: Sequence[Sequence[MemberPoint]] | None, start: datetime, end: datetime):
    """GEFS：每個成員取窗內（含頭尾）陣風的最大值（一位小數）；沒有任何成員有值是 None。"""
    gusts: list[float] = []
    estimated = False
    for pts in members or []:
        inside = [p for p in pts if start <= p.valid <= end and p.gust_kt is not None]
        if inside:
            gusts.append(round(max(p.gust_kt for p in inside), 1))  # type: ignore[type-var]
            estimated = estimated or any(p.estimated for p in inside)
    return {**_share(gusts), "estimated": estimated} if gusts else None


def wn2_entry(steps: Sequence[EnsStep] | None, start: datetime, end: datetime, g: float):
    """WN2 系集：每個成員取窗內（含頭尾）最大的 10 米風（一位小數）× G
    （`assess.estimated_gust`）。"""
    winds = member_winds([s for s in steps or [] if start <= s.valid <= end])
    gusts = [estimated_gust(round(w, 1), g) or 0.0 for w in winds]
    return {**_share(gusts), "estimated": True} if gusts else None


def load_gust_factors(archive: Path) -> tuple[str | None, dict[str, float]]:
    """`history/gustfactor/latest.json`（build 每報寫）→（它的 `generatedAt`, icao → G）；
    讀不到是空的。"""
    path = archive / "history" / "gustfactor" / "latest.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        airports = doc.get("airports") or {}
        g = {
            icao: float(v["g"])
            for icao, v in airports.items()
            if isinstance(v, dict) and isinstance(v.get("g"), int | float)
        }
        return doc.get("generatedAt"), g
    except (OSError, ValueError, AttributeError) as e:
        log.warning("讀不到陣風係數 %s（%s），一律用 %s", path, e, GUST_FACTOR_DEFAULT)
        return None, {}


def assemble(
    now: datetime,
    base: datetime,
    windows: Sequence[Window],
    airports: Sequence[Airport],
    results: dict[str, object],
    sources: dict[str, dict],
    factors: dict[str, float],
    factors_at: str | None = None,
) -> dict:
    """三套的結果（失敗的是 None）→ `longrange.json`。"""
    ifs = results.get("ifsEns")
    gf = results.get("gefs")
    wn2 = results.get("wn2Ens")
    runs = {
        "ifsEns": iso(ifs.run) if isinstance(ifs, ecmwf.LongRangeData) else None,
        "gefs": iso(gf.run) if isinstance(gf, gefs.GefsData) else None,
        "wn2Ens": iso(wn2.run) if isinstance(wn2, openmeteo.LongRangeEnsemble) else None,
    }
    g_of = {a.icao: factors.get(a.icao, GUST_FACTOR_DEFAULT) for a in airports}
    out: dict[str, list[dict]] = {}
    for a in airports:
        rows = []
        for start, end in windows:
            rows.append(
                {
                    "from": iso(start),
                    "to": iso(end),
                    "ifsEns": ifs_entry(ifs.points.get(a.icao), start, end)
                    if isinstance(ifs, ecmwf.LongRangeData)
                    else None,
                    "gefs": gefs_entry(gf.points.get(a.icao), start, end)
                    if isinstance(gf, gefs.GefsData)
                    else None,
                    "wn2Ens": wn2_entry(wn2.ensemble.get(a.icao), start, end, g_of[a.icao])
                    if isinstance(wn2, openmeteo.LongRangeEnsemble)
                    else None,
                }
            )
        out[a.icao] = rows
    return {
        "schema": SCHEMA,
        "generatedAt": iso(now),
        "stale": False,
        "base": base.strftime("%Y-%m-%d"),
        "runs": runs,
        "sources": sources,
        "thresholds": {
            "p29Kt": THRESHOLDS_KT["p29"],
            "p49Kt": THRESHOLDS_KT["p49"],
            "p29Ms": THRESHOLDS_MS["p29"],
            "p49Ms": THRESHOLDS_MS["p49"],
        },
        "gustFactor": {"generatedAt": factors_at, "airports": g_of},
        "windows": [
            {"day": FIRST_DAY + i, "from": iso(s), "to": iso(e)} for i, (s, e) in enumerate(windows)
        ],
        "airports": out,
    }


def _ifs_extra(d: ecmwf.LongRangeData) -> dict:
    return {"bytes": d.bytes_downloaded, "mirror": d.mirror}


def _gefs_extra(d: gefs.GefsData) -> dict:
    return {
        "bytes": d.bytes_downloaded,
        "files": d.files,
        "missing": d.missing,
        "estimated": d.estimated,
    }


def _wn2_extra(d: openmeteo.LongRangeEnsemble) -> dict:
    return {"bytes": d.bytes_downloaded, "calls": d.calls, "metaError": d.meta_error}


def _call(
    name: str, fn: Callable[[], object], extra: Callable, sources: dict[str, dict]
) -> object | None:
    """在 `BUDGET_S[name]` 秒內跑一套；失敗或超時記 `ok: false`＋原因、回傳 None
    （同 `build._call`）。"""
    out = budget.run(name, fn, BUDGET_S[name])
    if out.timed_out:
        log.warning("遠期 %s 超過 %s 秒的預算，放棄", name, BUDGET_S[name])
        sources[name] = {
            "ok": False,
            "error": "timeout",
            "seconds": float(BUDGET_S[name]),
            "bytes": out.context.bytes,
        }
        return None
    if out.error is not None:
        e = out.error
        code = getattr(e, "code", None) or e.__class__.__name__
        log.warning(
            "遠期 %s 失敗（%s）：%s",
            name,
            code,
            e,
            exc_info=None if hasattr(e, "code") else (type(e), e, e.__traceback__),
        )
        sources[name] = {
            "ok": False,
            "error": code,
            "seconds": round(out.seconds, 1),
            "bytes": out.context.bytes,
        }
        return None
    sources[name] = {"ok": True, "error": None, "seconds": round(out.seconds, 1)}
    sources[name].update(extra(out.result))
    return out.result


def run(now: datetime, archive: Path, airports: list[Airport], workdir: Path) -> dict:
    """抓三套、組 `longrange.json`；三套都失敗丟 `AllFailed`（呼叫端改沿用上一份）。"""
    base = base_of(now)
    windows = windows_of(base)
    factors_at, factors = load_gust_factors(archive)
    g_of = {a.icao: factors.get(a.icao, GUST_FACTOR_DEFAULT) for a in airports}
    sources: dict[str, dict] = {}
    results: dict[str, object] = {}
    results["ifsEns"] = _call(
        "ifsEns",
        lambda: ecmwf.fetch_longrange(airports, windows, workdir / "ecmwf"),
        _ifs_extra,
        sources,
    )
    results["gefs"] = _call(
        "gefs",
        lambda: gefs.fetch(airports, base, windows, workdir / "gefs", g_of),
        _gefs_extra,
        sources,
    )
    start, end = windows[0][0].date(), windows[-1][1].date()
    results["wn2Ens"] = _call(
        "wn2Ens",
        lambda: openmeteo.fetch_longrange(airports, start, end),
        _wn2_extra,
        sources,
    )
    if all(results[k] is None for k in SOURCES):
        raise AllFailed(sources)
    doc = assemble(now, base, windows, airports, results, sources, factors, factors_at)
    doc["sources"] = {k: sources[k] for k in SOURCES}
    return doc


def _dump(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(doc, ensure_ascii=False, separators=(",", ":"))
    path.write_text(text + "\n", encoding="utf-8")


def write(archive: Path, doc: dict, history: bool = True) -> None:
    """`--archive` 的 `longrange.json`；`history` 時另存 `history/longrange/<基準日>.json`。"""
    _dump(archive / FILENAME, doc)
    if history:
        _dump(archive / HISTORY_DIR / f"{doc['base']}.json", doc)


def previous(archive: Path, pages_url: str = PAGES_URL) -> dict | None:
    """上一份：先 `--archive` 的，沒有（或壞了）再從 Pages 抓。"""
    path = archive / FILENAME
    if path.exists():
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(doc, dict):
                return doc
        except ValueError:
            log.warning("archive 的 %s 壞了", FILENAME)
    try:
        r = requests.get(pages_url, timeout=30)
        r.raise_for_status()
        doc = r.json()
        return doc if isinstance(doc, dict) else None
    except (requests.RequestException, ValueError) as e:
        log.error("從 Pages 抓上一份 %s 也失敗：%s", FILENAME, e)
        return None


def mark_stale(prev: dict, now: datetime, errors: dict[str, str | None]) -> dict:
    """沿用上一份：內容不動，加 `stale`、`staleAt`（這次失敗的時間）、`staleErrors`
    （這次各套的錯誤）。"""
    return {**prev, "stale": True, "staleAt": iso(now), "staleErrors": errors}


def watch_list(doc: dict, min_p49: float = 0.2) -> list[tuple[str, str, dict[str, float]]]:
    """任一套 `p49` ≥ `min_p49` 的（機場, 窗的開始, {套: p49}），印 log 與回報用。"""
    out = []
    for icao, rows in (doc.get("airports") or {}).items():
        for row in rows:
            hits = {
                k: row[k]["p49"]
                for k in SOURCES
                if isinstance(row.get(k), dict) and (row[k].get("p49") or 0) >= min_p49
            }
            if hits:
                out.append((icao, row["from"], hits))
    return out


class _QuietGefs(logging.Filter):
    """GEFS 每天 2,542 個請求，`http_get` 每個成功的都印一行；只留 `gefs.fetch` 的總結那行
    （失敗的 WARNING 照印）。"""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args if isinstance(record.args, tuple) else ()
        return not (
            record.levelno <= logging.INFO
            and str(record.msg).startswith("GET %s")
            and bool(args)
            and gefs.S3_URL.removeprefix("https://") in str(args[0])
        )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m hongthai.longrange", description=__doc__)
    ap.add_argument("--archive", type=Path, default=Path("data"))
    ap.add_argument("--airports", type=Path, default=Path("airports.json"))
    ap.add_argument("--pages-url", default=PAGES_URL)
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stderr
    )
    for noisy in ("urllib3", "multiurl", "ecmwf", "cfgrib"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    log.addFilter(_QuietGefs())

    t0 = time.monotonic()
    now = utcnow().replace(second=0, microsecond=0)
    errors: dict[str, str | None]
    try:
        airports = load_airports(args.airports)
        # 超時被放棄的來源執行緒可能還在往暫存目錄寫檔，清不乾淨就算了
        with tempfile.TemporaryDirectory(prefix="hongthai-lr-", ignore_cleanup_errors=True) as tmp:
            doc = run(now, args.archive, airports, Path(tmp))
        write(args.archive, doc)
        for icao, start, hits in watch_list(doc):
            log.info("遠期關注 %s %s：%s", icao, start[:10], hits)
        log.info(
            "完成，%.1f 秒；來源：%s",
            time.monotonic() - t0,
            {k: v.get("ok") for k, v in doc["sources"].items()},
        )
        return 0
    except Exception as e:
        log.exception("遠期關注整個失敗，沿用上一份 %s", FILENAME)
        if isinstance(e, AllFailed):
            errors = {k: v.get("error") for k, v in e.sources.items()}
        else:
            errors = {"all": getattr(e, "code", None) or e.__class__.__name__}
        prev = previous(args.archive, args.pages_url)
        if prev is None:
            return 2
        write(args.archive, mark_stale(prev, now, errors), history=False)
        return 1


if __name__ == "__main__":
    sys.exit(main())
