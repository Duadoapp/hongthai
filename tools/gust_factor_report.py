"""估算陣風係數的驗證報表（HD18）：30 天後看估算陣風準不準、IFS 與 GFS 的係數差多少。

在 repo 根目錄跑 `python tools/gust_factor_report.py <data 分支的 checkout>`
（`--days` 改天數，預設 30）。純標準輸出、不改任何檔案。印兩段：

1. 模式陣風對 METAR：`history/<時間>.json` 每一份的**第一格**（`generatedAt` 所在的格）裡
   IFS、GFS、AIFS、AIGFS 的 `gustKt`（AIFS、AIGFS 是估算）對同一份 `airports[].metar` 的
   「有陣風用陣風、沒有用平均風」。只算 METAR 觀測離 `generatedAt` 3 小時內、而且 METAR 平均風
   ≥ 10 節的。每個模式印樣本數、偏差（模式 − METAR，節）的中位數、比值（模式 ÷ METAR）的平均
2. `history/gustfactor/` 的樣本：每個機場 IFS、GFS 各自的中位數與合併中位數（沒夾 1.2–2.0）、
   樣本數，最後一行全部機場合併。窗是最新那一報往前 `--days` 天
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, median

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from hongthai.gustfactor import load_window  # noqa: E402
from hongthai.timeutil import parse_time  # noqa: E402

REPORT_MODELS = ("ifs", "gfs", "aifs", "aigfs")
METAR_MAX_AGE = timedelta(hours=3)
METAR_MIN_WIND_KT = 10


def history_files(history: Path, days: int) -> list[tuple[datetime, Path]]:
    """`history/<YYYYMMDDTHHMM>Z.json`，最新那份往前 `days` 天，由舊到新。"""
    files = []
    for p in history.glob("*.json"):
        try:
            t = datetime.strptime(p.stem, "%Y%m%dT%H%MZ")
        except ValueError:
            continue
        files.append((t, p))
    if not files:
        return []
    newest = max(t for t, _ in files)
    return sorted((t, p) for t, p in files if newest - t <= timedelta(days=days))


def _num(v: object) -> float | None:
    return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else None


def first_slot(slots: list, now: datetime) -> dict | None:
    for s in slots:
        start, end = parse_time(s.get("from")), parse_time(s.get("to"))
        if start is not None and end is not None and start <= now < end:
            return s
    return None


def metar_pairs(doc: dict) -> list[tuple[str, float, float]]:
    """一份結果 → （模式, 模式陣風, METAR 的值）。"""
    now = parse_time(doc.get("generatedAt"))
    if now is None:
        return []
    out = []
    for a in doc.get("airports") or []:
        m = a.get("metar") or {}
        obs, wind, gust = (
            parse_time(m.get("observedAt")),
            _num(m.get("windKt")),
            _num(m.get("gustKt")),
        )
        if obs is None or abs(now - obs) > METAR_MAX_AGE or wind is None:
            continue
        if wind < METAR_MIN_WIND_KT:
            continue
        target = gust if gust is not None else wind
        slot = first_slot(a.get("slots") or [], now)
        for e in ((slot or {}).get("model") or {}).get("models") or []:
            g = _num(e.get("gustKt"))
            if e.get("id") in REPORT_MODELS and g is not None:
                out.append((e["id"], g, target))
    return out


def report_metar(data: Path, days: int) -> None:
    files = history_files(data / "history", days)
    pairs: dict[str, list[tuple[float, float]]] = {m: [] for m in REPORT_MODELS}
    for _, p in files:
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for mid, g, target in metar_pairs(doc):
            pairs[mid].append((g, target))
    span = f"{files[0][0]:%Y-%m-%d %H:%M}Z – {files[-1][0]:%Y-%m-%d %H:%M}Z" if files else "沒有"
    print(f"== 模式陣風對 METAR（{len(files)} 份結果，{span}；METAR 3 小時內、平均風 ≥ 10 節）==")
    print(f"{'模式':<8}{'樣本':>6}{'偏差中位數(節)':>16}{'平均比值':>10}")
    for mid in REPORT_MODELS:
        ps = pairs[mid]
        if not ps:
            print(f"{mid:<8}{0:>6}{'-':>16}{'-':>10}")
            continue
        bias = median(g - t for g, t in ps)
        ratio = mean(g / t for g, t in ps)
        print(f"{mid:<8}{len(ps):>6}{bias:>16.1f}{ratio:>10.2f}")


def _med(values: list[float]) -> str:
    return f"{median(values):.2f}" if values else "-"


def report_samples(data: Path, days: int) -> None:
    history = data / "history"
    runs = []
    for p in (history / "gustfactor").glob("*.jsonl"):
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                runs.append(parse_time(json.loads(line)["run"]))
            except (ValueError, KeyError, TypeError):
                continue
    runs = [t for t in runs if t is not None]
    print()
    if not runs:
        print("== history/gustfactor/ 沒有樣本 ==")
        return
    until = max(runs)
    rows = load_window(history, until, days)
    since = until - timedelta(days=days)
    print(
        f"== 陣風÷平均風樣本（{since:%Y-%m-%d %H:%M}Z – {until:%Y-%m-%d %H:%M}Z，{len(rows)} 行）=="
    )
    print(
        f"{'機場':<6}{'IFS 中位數':>12}{'nIFS':>7}{'GFS 中位數':>12}{'nGFS':>7}{'合併':>8}{'n':>7}"
    )
    by: dict[str, tuple[list[float], list[float]]] = {}
    for r in rows:
        ifs, gfs = by.setdefault(r["icao"], ([], []))
        ifs += [v for v in r["ifs"] if _num(v) is not None]
        gfs += [v for v in r["gfs"] if _num(v) is not None]
    all_ifs: list[float] = []
    all_gfs: list[float] = []
    for icao in sorted(by):
        ifs, gfs = by[icao]
        all_ifs += ifs
        all_gfs += gfs
        print(
            f"{icao:<6}{_med(ifs):>12}{len(ifs):>7}{_med(gfs):>12}{len(gfs):>7}"
            f"{_med(ifs + gfs):>8}{len(ifs) + len(gfs):>7}"
        )
    print(
        f"{'全部':<6}{_med(all_ifs):>12}{len(all_ifs):>7}{_med(all_gfs):>12}{len(all_gfs):>7}"
        f"{_med(all_ifs + all_gfs):>8}{len(all_ifs) + len(all_gfs):>7}"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("data", type=Path, help="data 分支的 checkout（底下有 history/）")
    ap.add_argument("--days", type=int, default=30)
    args = ap.parse_args(argv)
    report_metar(args.data, args.days)
    report_samples(args.data, args.days)
    return 0


if __name__ == "__main__":
    sys.exit(main())
