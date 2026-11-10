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

`--breakdown`（HD47）：一次呼叫的輸入拆成幾段各佔多少 token，與快取前綴、改排序前後的估計

    python -m tools.ai_cost --archive data --from 2026-11-01 --to 2026-11-09 --breakdown \
      [--calibrate-as before|after] [--json [path]]

- 用 `data` 分支每報的快照（`history/<YYYYMMDDTHHMMZ>.json`，公開的 `latest.json`）照
  `ai/prompt.py` 重建每一次有回應的呼叫送出的文字。公開的快照沒有 WeatherNext 3 的數值
  （`valuesHidden`），多模式綜合那段用**別的模式的數字當佔位**重建，只為了數長度；**提示詞全文不存檔、
  不印**，只印各段的 token 數。這個模式要裝 `requirements.txt`（`ai/prompt.py` 用到 `assess`）
- token 數是估計：文字切成「片」（一個中日文字、一串英文字母、一個數字、一段空白或一個符號各算
  一片），每家一個係數＝實際 token 合計 ÷ 片數合計（Claude：`input + cacheRead + cacheWrite`；
  Gemini：`input`；系統提示也算在內），用同一段期間有回應的呼叫校準，印出樣本數與每次的誤差
  （變異係數）。
  `--calibrate-as` 是那段期間實際送出的排法：`before`（HD47 之前：規則燈說明在最後、模式明細列每個
  欄位，預設）或 `after`（HD47 之後）
- 「改之前／之後」用同一個係數估：Claude 照 `run.py` 的送法模擬每報的快取（第一報寫入、共用前綴
  每一種各先評一個），輸出 token 用實際的平均；Gemini 沒有快取（共用前綴不到 4,096 token）
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from hongthai.ai.usage import FIELDS, cost_usd, hit_rate, price, total  # noqa: E402

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


# ---- `--breakdown`（HD47）----

_CJK = "\u3000-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uff00-\uffef"
PIECE = re.compile(rf"[{_CJK}]|[A-Za-z]+|\d|\s+|[^\sA-Za-z\d]")
LAYOUTS = ("before", "after")
# Gemini 4 隱含快取的最小長度（HD26 查的文件）
GEMINI_MIN_CACHE = 4096


def pieces(text: str) -> int:
    """估 token 用的「片」數（見模組說明）。"""
    return len(PIECE.findall(text))


def snapshot_name(run: str) -> str:
    """`2026-11-09T01:06:00Z` → `20261109T0106Z.json`。"""
    return f"{run[:4]}{run[5:7]}{run[8:10]}T{run[11:13]}{run[14:16]}Z.json"


def with_placeholder_blend(airport: dict) -> dict:
    """公開快照裡 WN3 那筆只有 `valuesHidden`：換成同一格別的模式（估算陣風的 AI 模式）的數字當
    佔位，只為了重建多模式綜合那段的長度（不是真的 WN3 數值）。"""
    import copy

    a = copy.deepcopy(airport)
    for s in a.get("slots") or []:
        entries = (s.get("model") or {}).get("models") or []
        src = next(
            (e for e in entries if e.get("gustEstimated") and e.get("level") is not None), None
        )
        for i, e in enumerate(entries):
            if e.get("valuesHidden") and src is not None:
                entries[i] = {**src, "id": e.get("id")}
    return a


def _system_segments(system: str) -> dict[str, str]:
    """系統提示拆成：開頭與 JSON 格式、規則、來源代號、用字。"""
    out = {"system:intro": [], "system:rules": [], "system:sources": [], "system:wording": []}
    cur = "system:intro"
    for ln in system.split("\n"):
        if ln.startswith("規則："):
            cur = "system:rules"
        elif ln.startswith("來源代號"):
            cur = "system:sources"
        elif ln.startswith("用字："):
            cur = "system:wording"
        elif ln.startswith("不要在 JSON 外面"):
            cur = "system:intro"
        out[cur].append(ln)
    return {k: "\n".join(v) for k, v in out.items()}


def segment_pieces(text: str) -> dict[str, int]:
    """一個機場的文字（`prompt.airport_text`，兩種排法都可以）各段的片數。段名：`header`、
    `metar`、`taf`、`warning`、`confirmed`、`slot:<代號>`（每格那行 `｜` 隔開的各段，`slot:time` 是
    時段）、`model:<模式>`（每格的模式明細）、`multi`（多模式綜合）、`rules`（規則燈說明，HD47 起是
    共用前綴）、`reminders`（最後的提醒）。"""
    out: dict[str, int] = {}

    def add(k: str, n: int) -> None:
        out[k] = out.get(k, 0) + n

    cur = "header"
    for ln in text.split("\n"):
        n = pieces(ln) + 1  # 換行
        if ln.startswith(("機場：", "資料時間：", "每格（")):
            add("header", n)
            continue
        if ln.startswith("提醒："):
            add("reminders", n)
            continue
        if re.match(r"^\d+\. ", ln):
            cur = "slot"
            for part in ln.split("｜"):
                m = re.match(r"^\s*\[([\w-]+)\]", part)
                add(f"slot:{m.group(1) if m else 'time'}", pieces(part) + 1)
            continue
        m = re.match(r"^  - \[([\w-]+)\]", ln)
        if m:
            add(f"model:{m.group(1)}", n)
            continue
        m = re.match(r"^\[([\w-]+)\]", ln)
        if m:
            cur = "rules" if ln.startswith("[rule] 規則燈") else m.group(1)
        add(cur, n)
    return out


def _texts(airport: dict, run: str) -> dict[str, object]:
    """兩種排法的文字（`before`：HD47 之前，模式明細不省略欄位）。"""
    from unittest import mock

    from hongthai.ai import prompt

    a = with_placeholder_blend(airport)
    after = prompt.airport_text(a, run)
    with mock.patch.object(prompt, "empty_fields", lambda slots: {}):
        before = prompt.airport_text(a, run)
    return {"before": before, "after": after}


def collect(archive: Path, items: list[tuple[str, dict]]) -> list[dict]:
    """每一次有回應的呼叫（任一家）→ `{"run", "day", "airport", "usage": {家: usage},
    "seg": {排法: {段: 片數}}, "shared": {排法: 共用前綴片數}, "variant"}`；找不到快照的跳過。"""
    snaps: dict[str, dict | None] = {}
    out = []
    for day, r in items:
        used = {k: r[k]["usage"] for k in KEYS if isinstance((r.get(k) or {}).get("usage"), dict)}
        run = r.get("run")
        if not used or not isinstance(run, str):
            continue
        if run not in snaps:
            f = archive / "history" / snapshot_name(run)
            try:
                snaps[run] = json.loads(f.read_text(encoding="utf-8")) if f.exists() else None
            except (OSError, ValueError):
                snaps[run] = None
        snap = snaps[run]
        a = next(
            (x for x in (snap or {}).get("airports") or [] if x.get("icao") == r.get("airport")),
            None,
        )
        if a is None:
            continue
        texts = _texts(a, run)
        out.append(
            {
                "run": run,
                "day": day,
                "airport": r.get("airport"),
                "usage": used,
                "seg": {k: segment_pieces(str(t)) for k, t in texts.items()},
                "shared": pieces(texts["after"].shared) + 1,  # type: ignore[attr-defined]
                "variant": texts["after"].shared,  # type: ignore[attr-defined]
            }
        )
    return out


def _actual_tokens(key: str, u: dict) -> int | None:
    n = [
        u.get(f) for f in (("input", "cacheRead", "cacheWrite") if key == "claude" else ("input",))
    ]
    if not isinstance(n[0], int):
        return None
    return sum(x for x in n if isinstance(x, int))


def calibrate(key: str, calls: list[dict], system_pieces: int, layout: str) -> dict:
    """每家的係數（token／片）與誤差。"""
    pairs = []
    for c in calls:
        u = c["usage"].get(key)
        tok = _actual_tokens(key, u) if u else None
        if tok:
            pairs.append((tok, system_pieces + sum(c["seg"][layout].values())))
    if not pairs:
        return {"n": 0, "k": None, "cv": None}
    k = sum(t for t, _ in pairs) / sum(p for _, p in pairs)
    errs = [t / (p * k) - 1 for t, p in pairs]
    cv = (sum(e * e for e in errs) / len(errs)) ** 0.5
    return {"n": len(pairs), "k": round(k, 4), "cv": round(cv, 4)}


def _cost(key: str, day: str, inp: float, out: float, read: float = 0, write: float = 0) -> float:
    p = price(key, day) or {}
    total_usd = inp * (p.get("input") or 0) + out * (p.get("output") or 0)
    total_usd += read * (p.get("cacheRead") or 0) + write * (p.get("cacheWrite") or 0)
    return total_usd / 1_000_000


def simulate(key: str, calls: list[dict], k: float, system_pieces: int, layout: str) -> dict:
    """估計每次的 token 與費用、命中率。Claude：`before` 只有系統提示進快取、每報第一個寫入；
    `after` 系統提示＋共用前綴（每一種各先評一個寫入）。Gemini 不快取。輸出 token 用實際的。"""
    sys_tok = system_pieces * k
    runs: dict[str, list[dict]] = {}
    for c in calls:
        if isinstance(c["usage"].get(key), dict):
            runs.setdefault(c["run"], []).append(c)
    agg = {"input": 0.0, "cacheRead": 0.0, "cacheWrite": 0.0, "output": 0.0, "usd": 0.0, "n": 0}
    for rs in runs.values():
        warm: set[str] = set()
        sys_cached = False
        for c in rs:
            u = c["usage"][key]
            out = (u.get("output") or 0) + (u.get("thinking") or 0)
            body = sum(c["seg"][layout].values()) * k
            read = write = 0.0
            if key == "claude":
                shared = c["shared"] * k if layout == "after" else 0.0
                own = body - shared
                if layout == "after" and c["variant"] in warm:
                    read = sys_tok + shared
                elif sys_cached:
                    read, write = sys_tok, shared
                else:
                    write = sys_tok + shared
                sys_cached = True
                if layout == "after":
                    warm.add(c["variant"])
                inp = own
            else:
                inp = sys_tok + body
            agg["input"] += inp
            agg["cacheRead"] += read
            agg["cacheWrite"] += write
            agg["output"] += out
            agg["usd"] += _cost(key, c["day"], inp, out, read, write)
            agg["n"] += 1
    n = agg["n"] or 1
    whole = agg["input"] + agg["cacheRead"] + agg["cacheWrite"]
    return {
        "calls": agg["n"],
        "avg": {f: round(agg[f] / n) for f in ("input", "cacheRead", "cacheWrite", "output")},
        "hitRate": round(agg["cacheRead"] / whole, 4) if whole else None,
        "costPerCallUsd": round(agg["usd"] / n, 5),
        "costUsd": round(agg["usd"], 4),
    }


def breakdown(archive: Path, items: list[tuple[str, dict]], calibrate_as: str = "before") -> dict:
    from hongthai.ai.prompt import SYSTEM

    calls = collect(archive, items)
    sys_seg = {k: pieces(v) + 1 for k, v in _system_segments(SYSTEM).items()}
    sys_pieces = pieces(SYSTEM)
    res: dict = {"calls": len(calls), "calibrateAs": calibrate_as, "models": {}}
    for key in KEYS:
        cal = calibrate(key, calls, sys_pieces, calibrate_as)
        mine = [c for c in calls if isinstance(c["usage"].get(key), dict)]
        entry: dict = {"calibration": cal}
        if cal["k"] and mine:
            k = cal["k"]
            for layout in LAYOUTS:
                segs: dict[str, float] = {s: v * k * len(mine) for s, v in sys_seg.items()}
                for c in mine:
                    for s, v in c["seg"][layout].items():
                        segs[s] = segs.get(s, 0) + v * k
                whole = sum(segs.values())
                shared = {*sys_seg, *(("rules",) if layout == "after" else ())}
                entry[layout] = {
                    "segments": [
                        {
                            "segment": s,
                            "avgTokens": round(v / len(mine)),
                            "share": round(v / whole, 4),
                            "shared": s in shared,
                        }
                        for s, v in sorted(segs.items(), key=lambda kv: -kv[1])
                    ],
                    "avgTokens": round(whole / len(mine)),
                    "sharedTokens": round(sum(segs[s] for s in shared if s in segs) / len(mine)),
                    "estimate": simulate(key, calls, k, sys_pieces, layout),
                }
            entry["actual"] = stats(
                key, [(c["day"], {key: {"usage": c["usage"][key]}}) for c in mine]
            )
            entry["systemTokens"] = round(sys_pieces * k)
            entry["sharedPrefixTokens"] = {
                "before": round(sys_pieces * k),
                "after": round((sys_pieces + max(c["shared"] for c in mine)) * k),
            }
        res["models"][key] = entry
    return res


SEGMENT_TEXT = {
    "system:intro": "系統提示：開頭與 JSON 格式",
    "system:rules": "系統提示：規則 1–11",
    "system:sources": "系統提示：來源代號說明",
    "system:wording": "系統提示：用字",
    "header": "機場名、資料時間、每格標題",
    "metar": "METAR",
    "taf": "TAF 原文",
    "warning": "生效中的警報",
    "confirmed": "已確認停飛",
    "rules": "規則燈怎麼算（門檻說明）",
    "reminders": "最後的提醒",
    "multi": "多模式綜合（WN3，佔位重建）",
}


def _segment_text(s: str) -> str:
    if s in SEGMENT_TEXT:
        return SEGMENT_TEXT[s]
    kind, _, code = s.partition(":")
    return {"slot": f"每格：[{code}] 段", "model": f"每格模式明細：[{code}]"}.get(kind, s)


def render_breakdown(res: dict) -> str:
    out = [
        f"重建 {res['calls']} 次呼叫（校準用的排法：{res['calibrateAs']}）；token 是估計，"
        "見 `python -m tools.ai_cost --help` 的說明",
        "",
    ]
    for key, e in res["models"].items():
        cal = e["calibration"]
        out.append(
            f"{key}：係數 {cal['k']} token／片（{cal['n']} 次，誤差 {_num(cal['cv'], '{:.1%}')}）"
        )
        if "before" not in e:
            out.append("")
            continue
        out.append(
            f"  系統提示約 {e['systemTokens']} token；快取前綴 改之前 "
            f"{e['sharedPrefixTokens']['before']}、改之後 {e['sharedPrefixTokens']['after']} token"
            + (f"（隱含快取最小 {GEMINI_MIN_CACHE}）" if key == "gemini" else "")
        )
        for layout, name in (("before", "改之前"), ("after", "改之後")):
            b = e[layout]
            out.append(
                f"  {name}：每次約 {b['avgTokens']} token，其中每個機場都一樣的 {b['sharedTokens']}"
                f"（{b['sharedTokens'] / b['avgTokens']:.1%}）"
            )
            for seg in b["segments"]:
                mark = "共用" if seg["shared"] else "    "
                name = _segment_text(seg["segment"])
                out.append(f"    {mark} {seg['avgTokens']:>6}  {seg['share']:>6.1%}  {name}")
            est = b["estimate"]
            a = est["avg"]
            hit = _num(None if est["hitRate"] is None else est["hitRate"] * 100, "{:.1f}%")
            out.append(
                f"    估計：input {a['input']} cacheRead {a['cacheRead']} "
                f"cacheWrite {a['cacheWrite']} output {a['output']}  命中 {hit}  "
                f"每次 US${est['costPerCallUsd']:.4f}"
            )
        out.append(f"  實際（改之前）：{line(key, e['actual'])}")
        out.append("")
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
    ap.add_argument(
        "--breakdown",
        action="store_true",
        help="各段 token 佔比與快取前綴（HD47；要裝 requirements.txt）",
    )
    ap.add_argument(
        "--calibrate-as",
        choices=LAYOUTS,
        default="before",
        help="--breakdown 校準時，那段期間實際送出的排法（HD47 之前 before、之後 after）",
    )
    args = ap.parse_args(argv)
    items = load(args.archive, args.since, args.until)
    if args.breakdown:
        bd = breakdown(args.archive, items, args.calibrate_as)
        if args.json == "-":
            print(json.dumps(bd, ensure_ascii=False, indent=2))
            return 0
        if args.json:
            Path(args.json).write_text(json.dumps(bd, ensure_ascii=False, indent=2) + "\n")
        print(render_breakdown(bd))
        return 0
    res = summarize(items)
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
