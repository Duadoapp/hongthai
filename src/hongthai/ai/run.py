"""AI 對決的整個流程：選機場 → 兩個模型平行評 → `latest.json` 的 `ai` 欄位與對決戰績。

- 兩個模型各一條執行緒同時跑，每個模型再用 `ThreadPoolExecutor` 並行評各機場（`PARALLEL`：
  Claude 4 條、Gemini 2 條）
- 每日上限：`history/ai/calls-<YYYY-MM-DD>.json`（UTC 日期，`{"claude": n, "gemini": n}`）記每個模型
  今天呼叫了幾次；到 `DAILY_CAP` 之後的機場記 `error: "daily_cap"`、不呼叫。每次呼叫（成功或失敗）
  都算一次，開始呼叫前就先記。`DAILY_CAP` 是 0（或負數）代表不限：不檢查、不會有 `daily_cap`，
  次數檔照常累加（開發期間，HD11）
- 沒被選的機場：兩顆燈 `status: "skipped"`、`level: "low"`、`comment` 固定四語（`NO_RISK`）
- 符合條件但排在 `MAX_AIRPORTS` 之後的機場：兩顆燈 `status: "error"`、`error: "run_cap"`
  （不能寫「沒看到明顯風險」，那些機場可能是中級）
- 時間預算（`budget_s`，`build.BUDGET_S["ai"]`）：每次請求的逾時取 `TIMEOUT_S` 與剩下時間的小者；
  `build` 那邊超過預算時呼叫 `result(timed_out=True)`，還沒評完的機場記 `error: "timeout"`，排隊中的
  不再呼叫，已經送出的請求最晚在預算到時結束，回來的結果不再採用
- 對決戰績：`history/ai/<YYYY-MM-DD>.json`（UTC 日期，一天一檔），每機場每跑次一筆，同一跑次同一
  機場新的覆蓋舊的（同 `cancellations.store` 的寫法）；只存等級與格，不存短評全文。呼叫失敗的
  那顆多一個 `detail`：`<代碼>:<stop_reason>:<輸出 token 數>[:<標記>]`（`AiError.trace()`，
  不記內容；HD6）
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from types import ModuleType

from . import claude, gemini, prompt, select
from .config import (
    DAILY_CAP,
    DISCLAIMER,
    KEYS,
    MAX_AIRPORTS,
    MODELS,
    NO_RISK,
    PARALLEL,
    TIMEOUT_S,
)
from .parse import AiError

log = logging.getLogger("hongthai")

EVALUATORS: dict[str, ModuleType] = {"claude": claude, "gemini": gemini}


def top_level() -> dict:
    """`latest.json` 頂層的 `ai`。"""
    return {"disclaimer": dict(DISCLAIMER), "models": dict(MODELS)}


def skipped(key: str) -> dict:
    return {"status": "skipped", "level": "low", "comment": dict(NO_RISK), "model": MODELS[key]}


def error(key: str, code: str) -> dict:
    return {"status": "error", "level": None, "comment": None, "model": MODELS[key], "error": code}


def ok(key: str, result: dict) -> dict:
    return {
        "status": "ok",
        "level": result["level"],
        "comment": result["comment"],
        "model": MODELS[key],
    }


def airport_ai(lights: dict[str, dict], run: str) -> dict:
    """`airports[].ai`：兩顆都 `error` 時 `evaluatedAt` 是 `null`，其他（含 `skipped`）是
    這一報的時間。"""
    all_error = all(lights[k]["status"] == "error" for k in KEYS)
    return {"evaluatedAt": None if all_error else run, **{k: lights[k] for k in KEYS}}


# ---- 每日上限 ----


def calls_path(history: Path, now: datetime) -> Path:
    return history / "ai" / f"calls-{now:%Y-%m-%d}.json"


def load_calls(history: Path, now: datetime) -> dict[str, int]:
    path = calls_path(history, now)
    try:
        old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, ValueError):
        log.warning("%s 讀不了，當作今天還沒呼叫", path)
        old = {}
    old = old if isinstance(old, dict) else {}
    return {k: v if isinstance(v := old.get(k), int) and v >= 0 else 0 for k in KEYS}


# ---- 對決戰績 ----


def _outcome(light: dict, detail: str | None) -> dict:
    out = {"status": light["status"], "level": light["level"]}
    return {**out, "detail": detail} if detail else out


def record(
    airport: dict,
    run: str,
    selected: str | None,
    lights: dict[str, dict],
    details: dict[str, str | None] | None = None,
) -> dict:
    """戰績一筆；`details` 是各模型呼叫失敗的 `AiError.trace()`（沒有就不出現 `detail`）。"""
    details = details or {}
    best, first = select.max_level(airport)
    slots = [s for s in airport.get("slots") or [] if isinstance(s, dict)]
    return {
        "run": run,
        "airport": airport.get("icao"),
        "selected": selected,
        "rule": {"maxLevel": best, "firstFrom": first},
        **{k: _outcome(lights[k], details.get(k)) for k in KEYS},
        "slots": [{"from": s.get("from"), "level": s.get("level")} for s in slots],
    }


def merge_records(old: list, new: list[dict]) -> list[dict]:
    """同 `run`＋`airport` 新的覆蓋舊的，沒有的加；依 `run`、`airport` 排序。"""
    by_key = {
        (r.get("run"), r.get("airport")): r for r in old if isinstance(r, dict) and r.get("run")
    }
    for r in new:
        by_key[(r["run"], r["airport"])] = r
    return [by_key[k] for k in sorted(by_key, key=lambda k: (str(k[0]), str(k[1])))]


def store_records(history: Path, now: datetime, rows: list[dict]) -> Path:
    path = history / "ai" / f"{now:%Y-%m-%d}.json"
    try:
        old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    except ValueError:
        log.warning("%s 壞了，重寫", path)
        old = []
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(
        merge_records(old if isinstance(old, list) else [], rows), ensure_ascii=False, indent=2
    )
    path.write_text(body + "\n", encoding="utf-8")
    return path


# ---- 流程 ----


class Duel:
    """一報的 AI 對決。`run()` 在 `build._call` 的預算執行緒裡跑；超時時主執行緒呼叫
    `result(timed_out=True)`。`result()` 只算一次（之後回傳同一份），算的時候寫每日次數與戰績檔。"""

    def __init__(
        self,
        latest: dict,
        prev: dict | None,
        now: datetime,
        history: Path,
        *,
        budget_s: float | None = None,
        evaluators: dict[str, ModuleType] | None = None,
    ):
        self.latest = latest
        self.now = now
        self.history = history
        self.run_at = latest["generatedAt"]
        qualified = select.qualifying(latest, prev)
        self.selected = qualified[:MAX_AIRPORTS]
        self.overflow = {a.get("icao") for a, _ in qualified[MAX_AIRPORTS:]}
        self.evaluators = evaluators or EVALUATORS
        self.deadline = time.monotonic() + budget_s if budget_s else None
        self.calls = load_calls(history, now)  # 今天到目前為止（含這一報）
        self.made = dict.fromkeys(KEYS, 0)  # 這一報
        self.lights: dict[str, dict[str, dict]] = {k: {} for k in KEYS}
        self.details: dict[str, dict[str, str]] = {k: {} for k in KEYS}  # 呼叫失敗的 trace
        self.model_errors: dict[str, str] = {}  # 整個模型不能用（no_api_key）
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self._result: dict | None = None

    def run(self) -> dict:
        texts = {a["icao"]: prompt.airport_text(a, self.run_at) for a, _ in self.selected}
        with ThreadPoolExecutor(len(KEYS), thread_name_prefix="ai") as ex:
            for f in [ex.submit(self._run_model, k, texts) for k in KEYS]:
                f.result()
        return self.result()

    def _run_model(self, key: str, texts: dict[str, str]) -> None:
        mod = self.evaluators[key]
        try:
            client = mod.make_client()
        except AiError as e:
            log.warning("AI %s 不能用：%s", key, e)
            with self.lock:
                self.model_errors[key] = e.code
                for icao in texts:
                    self.lights[key][icao] = error(key, e.code)
            return
        with ThreadPoolExecutor(PARALLEL[key], thread_name_prefix=f"ai-{key}") as ex:
            for icao, text in texts.items():
                ex.submit(self._one, key, mod, client, icao, text)

    def _set(self, key: str, icao: str, light: dict, detail: str | None = None) -> None:
        with self.lock:
            if not self.stop.is_set():  # 超時之後回來的不採用
                self.lights[key][icao] = light
                if detail:
                    self.details[key][icao] = detail

    def _one(self, key: str, mod: ModuleType, client: object, icao: str, text: str) -> None:
        if self.stop.is_set():
            return
        timeout: float = TIMEOUT_S
        if self.deadline is not None:
            timeout = min(timeout, self.deadline - time.monotonic())
            if timeout < 0.1:  # 預算用完了，不送
                self._set(key, icao, error(key, "timeout"))
                return
        with self.lock:
            if DAILY_CAP > 0 and self.calls[key] >= DAILY_CAP:
                self.lights[key][icao] = error(key, "daily_cap")
                return
            self.calls[key] += 1
            self.made[key] += 1
        t0 = time.monotonic()
        detail = None
        try:
            light = ok(key, mod.evaluate(text, client=client, timeout=timeout))
            log.info("AI %s %s：%s（%.1f 秒）", key, icao, light["level"], time.monotonic() - t0)
        except AiError as e:
            detail = e.trace()
            log.warning(
                "AI %s %s 失敗：%s［%s］（%.1f 秒）", key, icao, e, detail, time.monotonic() - t0
            )
            light = error(key, e.code)
        except Exception:  # SDK 內部沒預期的錯：記成 network，不讓其他機場停掉
            log.exception("AI %s %s 失敗（沒預期的例外）", key, icao)
            light = error(key, "network")
        self._set(key, icao, light, detail)

    def result(self, timed_out: bool = False) -> dict:
        """`{"ai": 頂層, "airports": {icao: airports[].ai}, "source": sources.ai}`
        （`source` 不含 `seconds`，由 `build.run_ai` 補）。"""
        with self.lock:
            if self._result is not None:
                return self._result
            self.stop.set()
            missing = "timeout" if timed_out else "network"
            reasons = {a["icao"]: why for a, why in self.selected}
            airports: dict[str, dict] = {}
            rows = []
            for a in self.latest["airports"]:
                icao = a["icao"]
                if icao in reasons:
                    lights = {k: self.lights[k].get(icao) or error(k, missing) for k in KEYS}
                elif icao in self.overflow:
                    lights = {k: error(k, "run_cap") for k in KEYS}
                else:
                    lights = {k: skipped(k) for k in KEYS}
                airports[icao] = airport_ai(lights, self.run_at)
                details = {k: self.details[k].get(icao) for k in KEYS}
                rows.append(record(a, self.run_at, reasons.get(icao), lights, details))
            source = self._source(airports)
            self._result = {"ai": top_level(), "airports": airports, "source": source}
            calls = dict(self.calls)
        self._write(calls, rows)
        return self._result

    def _source(self, airports: dict[str, dict]) -> dict:
        errors: dict[str, str] = dict(self.model_errors)
        any_ok = False
        for k in KEYS:
            codes = Counter(
                ai[k]["error"]
                for icao, ai in airports.items()
                if ai[k]["status"] == "error" and ai[k]["error"] != "run_cap"
            )
            any_ok |= any(ai[k]["status"] == "ok" for ai in airports.values())
            if codes and k not in errors:
                errors[k] = codes.most_common(1)[0][0]
        src: dict[str, object] = {
            "ok": any_ok or (not self.selected and not errors),
            "calls": dict(self.made),
        }
        if errors:
            src["errors"] = errors
        if not src["ok"]:
            src["error"] = ",".join(f"{k}:{v}" for k, v in errors.items()) or "no_result"
        return src

    def _write(self, calls: dict[str, int], rows: list[dict]) -> None:
        try:  # 寫不了只 log：AI 的紀錄不能讓 build 失敗
            path = calls_path(self.history, self.now)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(calls, indent=2) + "\n", encoding="utf-8")
            store_records(self.history, self.now, rows)
        except OSError as e:
            log.warning("AI 紀錄寫不進 %s：%s", self.history / "ai", e)


def evaluate_all(
    latest: dict, prev: dict | None, now: datetime, history: Path, **kwargs: object
) -> dict:
    """選機場、兩個模型平行評，回傳 `Duel.result()`（沒有時間預算，`build` 用 `Duel` 本身）。"""
    return Duel(latest, prev, now, history, **kwargs).run()  # type: ignore[arg-type]


def fallback(latest: dict, code: str) -> dict:
    """整個 AI 步驟壞掉（程式錯）時的結果：每個機場兩顆都 `error`。"""
    airports = {
        a["icao"]: airport_ai({k: error(k, code) for k in KEYS}, latest["generatedAt"])
        for a in latest["airports"]
    }
    return {
        "ai": top_level(),
        "airports": airports,
        "source": {"ok": False, "error": code, "calls": dict.fromkeys(KEYS, 0)},
    }


def apply(latest: dict, result: dict, source: dict) -> None:
    """把 `result` 寫進 `latest`：頂層 `ai`、每個機場的 `ai`、`sources.ai`。"""
    latest["ai"] = result["ai"]
    for a in latest["airports"]:
        a["ai"] = result["airports"][a["icao"]]
    latest["sources"]["ai"] = source
