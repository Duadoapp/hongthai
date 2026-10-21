"""AI 對決的 token 用量、快取命中率與估計費用（HD26），讀戰績 `history/ai/` 每筆的 `usage`。

在 repo 根目錄跑（`data` 是 `data` 分支的 checkout，底下有 `history/`）：

    python -m tools.ai_cost --archive data --from 2026-10-21 [--to 2026-10-31] \\
      [--json [ai-cost.json]]

印每天、每報、每家：呼叫數（真的送出的，`usage` 欄位存在；其中有回應的 `usage` 不是 null）、
每次有回應的呼叫平均 input／output／思考／快取讀寫 token、快取命中率、估計費用（美元）。
`--json` 不給路徑時 JSON 印在標準輸出（不印表），給路徑時寫檔（給之後畫圖）。純讀、只用標準
函式庫，不用裝 numpy／eccodes。

- 命中率是整段期間的合計算的（不是每次平均）：Claude
  `cacheRead ÷ (input + cacheRead + cacheWrite)`（`input_tokens` 不含快取讀寫）、Gemini
  `cacheRead ÷ input`（`prompt_token_count` 含快取命中的部分）
- 費用用 `src/hongthai/ai/config.py` 的 `PRICES`，依戰績檔的日期（UTC）取單價（Gemini 到
  11/30 是促銷價）；有回應的呼叫裡只要有一次算不出來（單價是 `None`、`input`／`output` 缺），
  那一組的費用就是 `null`
- HD26 之前的戰績沒有 `usage`，不算（呼叫數是 0）
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from hongthai.ai.usage import FIELDS, cost_usd, hit_rate, total  # noqa: E402

KEYS = tuple(FIELDS)
DAY_FILE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.json$")


def load(archive: Path, since: str, until: str | None) -> list[tuple[str, dict]]:
    """`[(日期, 戰績一筆)]`，依日期、`run`、`airport`；壞掉的檔跳過（印在 stderr）。"""
    out: list[tuple[str, dict]] = []
    folder = archive / "history" / "ai"
    for p in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        m = DAY_FILE.match(p.name)
        if not m or m.group(1) < since or (until and m.group(1) > until):
            continue
        try:
            rows = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            print(f"{p} 讀不了：{e}", file=sys.stderr)
            continue
        out += (
            [(m.group(1), r) for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
        )
    return out


def stats(key: str, items: list[tuple[str, dict]]) -> dict:
    """一組（某天／某報／全部）某一家的數字；`items` 是 `[(日期, 戰績一筆)]`。"""
    sent = [(day, r[key]["usage"]) for day, r in items if "usage" in (r.get(key) or {})]
    got = [(day, u) for day, u in sent if isinstance(u, dict)]
    tot = total(key, (u for _, u in got))
    n = tot["calls"]
    costs = [cost_usd(key, u, day) for day, u in got]
    cost = None if any(c is None for c in costs) else round(sum(c for c in costs if c), 6)
    return {
        "calls": len(sent),
        "responded": n,
        "avg": {f: None if tot[f] is None or not n else round(tot[f] / n, 1) for f in FIELDS[key]},
        "total": {f: tot[f] for f in FIELDS[key]},
        "hitRate": None if (h := hit_rate(key, tot)) is None else round(h, 4),
        "costUsd": cost,
        "costPerCallUsd": None if cost is None or not n else round(cost / n, 6),
    }


def summarize(items: list[tuple[str, dict]]) -> dict:
    days: dict[str, list[tuple[str, dict]]] = {}
    for day, r in items:
        days.setdefault(day, []).append((day, r))
    out_days = []
    for day, rows in sorted(days.items()):
        runs: dict[str, list[tuple[str, dict]]] = {}
        for item in rows:
            runs.setdefault(str(item[1].get("run")), []).append(item)
        out_days.append(
            {
                "day": day,
                **{k: stats(k, rows) for k in KEYS},
                "runs": [
                    {"run": run, **{k: stats(k, rs) for k in KEYS}}
                    for run, rs in sorted(runs.items())
                ],
            }
        )
    return {
        "formula": {
            "claudeHitRate": "cacheRead / (input + cacheRead + cacheWrite)",
            "geminiHitRate": "cacheRead / input",
        },
        "days": out_days,
        "total": {k: stats(k, items) for k in KEYS},
    }


def _num(v: float | None, fmt: str = "{:.0f}") -> str:
    return "-" if v is None else fmt.format(v)


def line(key: str, s: dict) -> str:
    avg = " ".join(f"{f} {_num(s['avg'][f])}" for f in FIELDS[key])
    hit = _num(None if s["hitRate"] is None else s["hitRate"] * 100, "{:.1f}%")
    return (
        f"{key:<7}呼叫 {s['calls']}（有回應 {s['responded']}）  平均 {avg}  命中 {hit}  "
        f"US${_num(s['costUsd'], '{:.4f}')}（每次 US${_num(s['costPerCallUsd'], '{:.4f}')}）"
    )


def render(res: dict) -> str:
    out = [
        "命中率：Claude cacheRead ÷ (input + cacheRead + cacheWrite)；Gemini cacheRead ÷ input",
        "",
    ]
    for d in res["days"]:
        out.append(d["day"])
        out += [f"  {line(k, d[k])}" for k in KEYS]
        for r in d["runs"]:
            out.append(f"  {r['run']}")
            out += [f"    {line(k, r[k])}" for k in KEYS]
        out.append("")
    out.append("合計")
    out += [f"  {line(k, res['total'][k])}" for k in KEYS]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m tools.ai_cost", description=__doc__.splitlines()[0]
    )
    ap.add_argument("--archive", type=Path, default=Path("data"), help="data 分支的 checkout")
    ap.add_argument("--from", dest="since", default="2026-10-21", help="從哪天（UTC，含）")
    ap.add_argument("--to", dest="until", help="到哪天（UTC，含）；不給是到最新")
    ap.add_argument(
        "--json", nargs="?", const="-", help="JSON；不給路徑印在標準輸出（不印表），給路徑寫檔"
    )
    args = ap.parse_args(argv)
    res = summarize(load(args.archive, args.since, args.until))
    body = json.dumps(res, ensure_ascii=False, indent=2)
    if args.json == "-":
        print(body)
        return 0
    if args.json:
        Path(args.json).write_text(body + "\n", encoding="utf-8")
    print(render(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
