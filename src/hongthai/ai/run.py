"""AI 對決的整個流程：選機場 → 兩個模型平行評 → `latest.json` 的 `ai` 欄位與對決戰績。

- 兩個模型各一條執行緒同時跑，每個模型再用 `ThreadPoolExecutor` 並行評各機場（`PARALLEL`：
  Claude 4 條、Gemini 3 條）
- 每日上限：`history/ai/calls-<YYYY-MM-DD>.json`（UTC 日期，`{"claude": n, "gemini": n}`）記每個模型
  今天呼叫了幾次；到 `DAILY_CAP` 之後的機場記 `error: "daily_cap"`、不呼叫。每次呼叫（成功或失敗）
  都算一次，開始呼叫前就先記。`DAILY_CAP` 是 0（或負數）代表不限：不檢查、不會有 `daily_cap`，
  次數檔照常累加（開發期間，HD11）
- 沒被選的機場：兩顆燈 `status: "skipped"`、`level: "low"`、`comment` 固定四語（`NO_RISK`）
- 符合條件但排在 `MAX_AIRPORTS` 之後的機場：兩顆燈 `status: "error"`、`error: "run_cap"`
  （不能寫「沒看到明顯風險」，那些機場可能是中級）
- 時間預算（`budget_s`，`build.BUDGET_S["ai"]`）：單次請求逾時每模型各自（`TIMEOUT_S`：
  Claude 60、Gemini 45 秒，HD23），取它與剩下時間的小者；剩下時間不到該模型逾時＋5 秒
  （`SEND_MIN_LEFT_S`）就不再送新請求、記 `error: "timeout"`（HD23；以前是不到 0.1 秒才不送）。
  `build` 那邊超過預算時呼叫 `result(timed_out=True)`，還沒評完的機場記 `error: "timeout"`，
  排隊中的不再呼叫，已經送出的請求最晚在預算到時結束，回來的結果不再採用
- 對決戰績：`history/ai/<YYYY-MM-DD>.json`（UTC 日期，一天一檔），每機場每跑次一筆，同一跑次同一
  機場新的覆蓋舊的（同 `cancellations.store` 的寫法）；只存等級與格，不存短評全文。呼叫失敗的
  那顆多一個 `detail`：`<代碼>:<stop_reason>:<輸出 token 數>[:<標記>]`（`AiError.trace()`，
  不記內容；HD6）。真的送出的呼叫（成功或失敗）多一個 `seconds`：從送出到收到或出錯，一位小數
  （HD12）；`skipped`、`run_cap`、`daily_cap`、`no_api_key` 與預算到了沒送的 `timeout` 沒有
- 重試（HD17、HD23）：`http_503`／`http_504`（`RETRY_CODES`，閘道沒回應）同一個請求重試一次，
  只在第一次**花不到 `RETRY_FAST_FAIL_S`（15 秒）就失敗**、剩餘預算 ≥ `RETRY_MIN_LEFT_S`
  （該模型逾時＋10 秒）、沒到每日上限時；重試也算一次呼叫（次數檔、`calls` 都加 1）。重試仍失敗
  記第二次的錯誤、`detail` 後面加 `:retried`；`seconds` 是兩次合計。等了 15 秒以上才回的
  （閘道逾時）不重試，`detail` 後面加 `:slow`。其他錯誤都不重試
- 備援區域（HD23，`Regions`）：模組有 `locations()` 的模型（Gemini）記這一報主要區域連續幾次
  `FALLBACK_CODES`（`http_503`／`http_504`／`timeout`；成功或其他錯誤歸零），到
  `FALLBACK_AFTER`（3）次之後的請求（含重試）改用備援區域的 client（第一次要用時才建立，
  同一把服務帳號）；備援回 `http_404` 或連續 `FALLBACK_GIVE_UP`（2）次失敗（`CONTENT_ERRORS`
  不算）就不再用、退回主要區域。用備援失敗的 `detail` 最後加 `:fallback`；`sources.ai` 多
  `<模型>Location`（`geminiLocation`：這一報最後送出的請求用的區域）
- 提示快取（HD26）：`WARMUP` 是 `True` 的模型（Claude）**第一個機場先單獨評完**（寫進快取），
  再開 `PARALLEL` 條線評其他的；第一個失敗也照樣開線。Gemini 照舊直接開線。只改送出的順序，
  每個機場送的內容不變
- token 紀錄（HD26，`ai/usage.py`）：戰績每筆真的送出的呼叫多 `usage`（有回應的那次的 token 數，
  沒拿到回應是 `null`；重試過的是第二次的）；`result()["usage"]` 是各模型這一報的合計（加
  `calls`：有回應的次數）、`result()["costUsd"]` 是估計費用，`build.run_ai` 寫進 `timing/` 的 `ai`
  那行，`latest.json` 不加
- 錯誤訊息（HD30）：HTTP、逾時、網路錯誤時 API 回的錯誤訊息（`AiError.message`，清理過、≤ 200 字）；
  戰績那筆失敗的模型多 `message`（重試過的是第二次的）；`result()["errorMessages"]` 是各模型這一報
  **第一則**錯誤的 `message`（含重試前那次；沒有是 `None`），只進 `timing/` 的 `ai` 那行
- WeatherNext 3（HD43）：日本、南韓以外、這一報有 WN3 資料的機場，精簡文字多「多模式綜合」那段
  （`prompt.multi_lines`）。回應通過格式與用字後再查 `parse.check_wn3`：寫出 WN3 的名字或它獨有的
  數字（`parse.Wn3Leak`）→ **同一段文字重生一次**；再違規 → **拿掉那段重生**（`src` 不能再用
  `multi`）；第三次的結果照一般的流程（還是違規就是 `bad_wording`、標記 `wn3/…`）。重生也算一次呼叫
  （次數檔、`calls`、時間預算同 HD17 的重試）；被丟掉那次的 token 數加進 `usage` 合計。
  `sources.ai` 多 `wn3Retries`（各模型因 WN3 重生幾次）、`wn3Dropped`（其中拿掉那段的次數），
  只記次數、**不記違規的內容**；這一報沒有機場有那段時沒有這兩個鍵。提示詞（含 WN3 數值）不存檔
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import ModuleType

from . import claude, gemini, prompt, select, usage
from .config import (
    CONTENT_ERRORS,
    DAILY_CAP,
    DISCLAIMER,
    FALLBACK_AFTER,
    FALLBACK_CODES,
    FALLBACK_GIVE_UP,
    KEYS,
    MAX_AIRPORTS,
    MODELS,
    NO_RISK,
    PARALLEL,
    RETRY_CODES,
    RETRY_FAST_FAIL_S,
    RETRY_MIN_LEFT_S,
    SEND_MIN_LEFT_S,
    TIMEOUT_S,
    WARMUP,
)
from .parse import AiError, Wn3Leak, check_wn3

log = logging.getLogger("hongthai")

EVALUATORS: dict[str, ModuleType] = {"claude": claude, "gemini": gemini}


@dataclass(frozen=True)
class Wn3Input:
    """一個機場的多模式綜合那段（HD43）：`numbers` 是那段獨有的整數，`plain` 是拿掉那段的
    精簡文字。"""

    numbers: frozenset[int]
    plain: str


def top_level() -> dict:
    """`latest.json` 頂層的 `ai`。"""
    return {"disclaimer": dict(DISCLAIMER), "models": dict(MODELS)}


def skipped(key: str) -> dict:
    return {
        "status": "skipped",
        "level": "low",
        "comment": dict(NO_RISK),
        "model": MODELS[key],
        "sentences": None,
    }


def error(key: str, code: str) -> dict:
    return {
        "status": "error",
        "level": None,
        "comment": None,
        "model": MODELS[key],
        "error": code,
        "sentences": None,
    }


def ok(key: str, result: dict) -> dict:
    """`sentences`（HD40）是四語逐句短評與來源代號；`comment` 是同一語的句子接起來。"""
    return {
        "status": "ok",
        "level": result["level"],
        "comment": result["comment"],
        "model": MODELS[key],
        "sentences": result["sentences"],
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


_UNSENT = object()  # 沒送出的呼叫：戰績不寫 `usage`（送出但沒回應是 `None`、寫 `null`）


def _outcome(
    light: dict, detail: str | None, seconds: float | None, used: object, message: str | None
) -> dict:
    out = {"status": light["status"], "level": light["level"]}
    if detail:
        out["detail"] = detail
    if message:  # HD30
        out["message"] = message
    if seconds is not None:
        out["seconds"] = seconds
    if used is not _UNSENT:
        out["usage"] = used
    return out


def record(
    airport: dict,
    run: str,
    selected: str | None,
    lights: dict[str, dict],
    details: dict[str, str | None] | None = None,
    seconds: dict[str, float | None] | None = None,
    usages: dict[str, dict | None] | None = None,
    messages: dict[str, str | None] | None = None,
) -> dict:
    """戰績一筆；`details` 是各模型呼叫失敗的 `AiError.trace()`（沒有就不出現 `detail`），
    `seconds` 是各模型那次呼叫花的秒數（沒送出就不出現 `seconds`，HD12），`usages` 是那次的
    token 數（沒送出的模型不在裡面、不出現 `usage`；送出但沒回應是 `None`，HD26），`messages`
    是失敗時的 `AiError.message`（沒有就不出現 `message`，HD30）。"""
    details = details or {}
    seconds = seconds or {}
    usages = usages or {}
    messages = messages or {}
    best, first = select.max_level(airport)
    slots = [s for s in airport.get("slots") or [] if isinstance(s, dict)]
    return {
        "run": run,
        "airport": airport.get("icao"),
        "selected": selected,
        "rule": {"maxLevel": best, "firstFrom": first},
        **{
            k: _outcome(
                lights[k], details.get(k), seconds.get(k), usages.get(k, _UNSENT), messages.get(k)
            )
            for k in KEYS
        },
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


# ---- 備援區域（HD23）----


class Regions:
    """一個模型這一報的主要／備援區域。模組有 `locations()`（→ `(主要, 備援或 None)`）且
    `make_client(location)` 收區域的才有備援（Gemini）；沒有的只記不切。"""

    def __init__(self, key: str, mod: ModuleType, client: object):
        self.key, self.mod, self.client = key, mod, client
        locs = getattr(mod, "locations", None)
        self.primary, self.backup = locs() if locs else (None, None)
        self.backup_client: object | None = None
        self.on_backup = False
        self.done = self.backup is None  # 備援不能用（沒開、已經放棄）
        self.streak = 0  # 主要區域連續 `FALLBACK_CODES` 幾次
        self.fails = 0  # 備援連續失敗幾次
        self.last: str | None = None  # 這一報最後送出的請求用的區域
        self.lock = threading.Lock()

    def pick(self) -> tuple[object, bool]:
        """要送一次請求：（client, 是不是備援）。"""
        with self.lock:
            if self.on_backup and self.backup_client is None:
                try:  # 第一次要用才建立
                    self.backup_client = self.mod.make_client(self.backup)
                except Exception as e:  # 建不了就退回主要區域，不讓這一報停掉
                    self._give_up(f"建不了 client：{e}")
            use = self.on_backup
            self.last = self.backup if use else self.primary
            return (self.backup_client if use else self.client), use

    def note(self, backup: bool, code: str | None) -> None:
        """一次請求的結果（`code` 是錯誤代碼，成功是 `None`）。"""
        with self.lock:
            if self.done or backup != self.on_backup:  # 切換前後還在路上的不算
                return
            if backup:
                if code is None or code in CONTENT_ERRORS:
                    self.fails = 0
                elif code == "http_404":  # 模型不在這一區
                    self._give_up(code)
                else:
                    self.fails += 1
                    if self.fails >= FALLBACK_GIVE_UP:
                        self._give_up(f"連續 {self.fails} 次失敗（{code}）")
            elif code in FALLBACK_CODES:
                self.streak += 1
                if self.streak >= FALLBACK_AFTER:
                    log.warning(
                        "AI %s %s 連續 %d 次 %s，之後改用備援區域 %s",
                        self.key,
                        self.primary,
                        self.streak,
                        code,
                        self.backup,
                    )
                    self.on_backup = True
            else:
                self.streak = 0

    def _give_up(self, why: str) -> None:
        log.warning(
            "AI %s 備援區域 %s 不再用（%s），退回 %s", self.key, self.backup, why, self.primary
        )
        self.on_backup, self.done = False, True


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
        self.seconds: dict[str, dict[str, float]] = {k: {} for k in KEYS}  # 送出的呼叫花幾秒
        self.usage: dict[str, dict[str, dict | None]] = {k: {} for k in KEYS}  # 送出的呼叫（HD26）
        self.messages: dict[str, dict[str, str]] = {k: {} for k in KEYS}  # 失敗的錯誤訊息（HD30）
        self.first_message: dict[str, str] = {}  # 各模型這一報第一則錯誤訊息（HD30）
        self.model_errors: dict[str, str] = {}  # 整個模型不能用（no_api_key）
        self.regions: dict[str, Regions] = {}  # 有呼叫的模型（HD23）
        self.wn3: dict[str, Wn3Input] = {}  # HD43：有多模式綜合那段的機場
        self.wn3_retries = dict.fromkeys(KEYS, 0)
        self.wn3_dropped = dict.fromkeys(KEYS, 0)
        self.dropped_usage: dict[str, list[dict | None]] = {k: [] for k in KEYS}  # 重生前那次
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self._result: dict | None = None

    def run(self) -> dict:
        texts = {a["icao"]: prompt.airport_text(a, self.run_at) for a, _ in self.selected}
        for a, _ in self.selected:  # HD43
            if prompt.has_blend(a):
                self.wn3[a["icao"]] = Wn3Input(
                    prompt.wn3_numbers(a, self.run_at),
                    prompt.airport_text(a, self.run_at, wn3=False),
                )
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
        self.regions[key] = Regions(key, mod, client)
        items = list(texts.items())
        # 第一個先單獨評完，把系統提示寫進快取（HD26，只有 Claude）；失敗也照樣開線
        if items and WARMUP.get(key):
            self._one(key, mod, *items.pop(0))
        with ThreadPoolExecutor(PARALLEL[key], thread_name_prefix=f"ai-{key}") as ex:
            for icao, text in items:
                ex.submit(self._one, key, mod, icao, text)

    def _set(
        self,
        key: str,
        icao: str,
        light: dict,
        detail: str | None = None,
        seconds: float | None = None,
        used: dict | None = None,
        message: str | None = None,
    ) -> None:
        with self.lock:
            if not self.stop.is_set():  # 超時之後回來的不採用
                self.lights[key][icao] = light
                if detail:
                    self.details[key][icao] = detail
                if message:
                    self.messages[key][icao] = message
                if seconds is not None:  # 真的送出的才有 `seconds` 與 `usage`
                    self.seconds[key][icao] = round(seconds, 1)
                    self.usage[key][icao] = used

    def _one(self, key: str, mod: ModuleType, icao: str, text: str) -> None:
        if self.stop.is_set():
            return
        timeout: float = TIMEOUT_S[key]
        if self.deadline is not None:
            left = self.deadline - time.monotonic()
            if left < SEND_MIN_LEFT_S[key]:  # 剩不到一次請求＋5 秒，不送（HD23）
                self._set(key, icao, error(key, "timeout"))
                return
            timeout = min(timeout, left)
        if not self._count(key):
            with self.lock:
                self.lights[key][icao] = error(key, "daily_cap")
            return
        t0 = time.monotonic()
        wn3 = self.wn3.get(icao)
        numbers = wn3.numbers if wn3 else None
        light, err, backup, used, tag = self._try(key, mod, icao, text, numbers, timeout)
        rounds = 0  # HD43：WN3 違規重生的次數（最多兩次：照原文、拿掉那段）
        while wn3 is not None and isinstance(err, Wn3Leak) and rounds < 2:
            retry = self._retry_timeout(key)
            if retry is None:
                break
            rounds += 1
            with self.lock:
                self.wn3_retries[key] += 1
                self.dropped_usage[key].append(used)
                if rounds == 2:
                    self.wn3_dropped[key] += 1
            if rounds == 2:
                text, numbers = wn3.plain, None
            log.info(
                "AI %s %s 違規（%s），%s",
                key,
                icao,
                err.tag,
                "拿掉多模式綜合重生" if rounds == 2 else "重生",
            )
            light, err, backup, used, tag = self._try(key, mod, icao, text, numbers, retry)
        detail = f"{err.trace()}{tag}{':fallback' if backup else ''}" if err else None
        message = err.message if err else None
        seconds = time.monotonic() - t0  # 重試、重生時是全部合計
        self._set(key, icao, light, detail, seconds, used, message)

    def _try(
        self,
        key: str,
        mod: ModuleType,
        icao: str,
        text: str,
        numbers: frozenset[int] | None,
        timeout: float,
    ) -> tuple[dict, AiError | None, bool, dict | None, str]:
        """送一次（閘道快失敗時同一個請求重試一次，HD17、HD23）→（燈, `AiError`, 備援, `usage`,
        `detail` 的尾巴 `:slow`／`:retried`）。"""
        t0 = time.monotonic()
        light, err, backup, used = self._send(key, mod, icao, text, timeout, numbers)
        tag = ""
        if err and err.code in RETRY_CODES:  # 閘道沒回應（HD17）
            if time.monotonic() - t0 >= RETRY_FAST_FAIL_S:  # 閘道逾時：重試只會再卡一次（HD23）
                tag = ":slow"
            elif (retry := self._retry_timeout(key)) is not None:  # 快失敗：同一個請求重試一次
                log.info("AI %s %s %s，重試一次", key, icao, err.code)
                light, err, backup, used = self._send(key, mod, icao, text, retry, numbers)
                tag = ":retried"
        return light, err, backup, used, tag

    def _send(
        self,
        key: str,
        mod: ModuleType,
        icao: str,
        text: str,
        timeout: float,
        numbers: frozenset[int] | None = None,
    ) -> tuple[dict, AiError | None, bool, dict | None]:
        """選區域、送一次、記結果 →（燈, 失敗時的 `AiError`, 是不是用備援區域, `usage`）。"""
        regions = self.regions[key]
        client, backup = regions.pick()
        light, err, used = self._call(key, mod, client, icao, text, timeout, backup, numbers)
        regions.note(backup, light.get("error"))
        return light, err, backup, used

    def _count(self, key: str) -> bool:
        """要送一次請求：沒到每日上限就記一次、回 `True`。"""
        with self.lock:
            if DAILY_CAP > 0 and self.calls[key] >= DAILY_CAP:
                return False
            self.calls[key] += 1
            self.made[key] += 1
            return True

    def _retry_timeout(self, key: str) -> float | None:
        """重試這次的逾時；超時了、剩餘預算不到 `RETRY_MIN_LEFT_S`（該模型逾時＋10 秒）或到每日
        上限 → `None`（不重試）。"""
        if self.stop.is_set():
            return None
        timeout: float = TIMEOUT_S[key]
        if self.deadline is not None:
            left = self.deadline - time.monotonic()
            if left < RETRY_MIN_LEFT_S[key]:
                return None
            timeout = min(timeout, left)
        return timeout if self._count(key) else None

    def _call(
        self,
        key: str,
        mod: ModuleType,
        client: object,
        icao: str,
        text: str,
        timeout: float,
        backup: bool = False,
        numbers: frozenset[int] | None = None,
    ) -> tuple[dict, AiError | None, dict | None]:
        """送一次請求 → (燈, 失敗時的 `AiError`, `usage`：沒拿到回應是 `None`)。`numbers`：多模式
        綜合那段獨有的整數（HD43；None＝這次沒有那段，`check_wn3`）。"""
        t0 = time.monotonic()
        where = f"（備援 {self.regions[key].backup}）" if backup else ""
        try:
            res = mod.evaluate(text, client=client, timeout=timeout)
            try:
                check_wn3(res["sentences"], numbers)
            except AiError as e:
                e.usage = res.get("usage")
                raise
            light = ok(key, res)
            log.info(
                "AI %s %s%s：%s（%.1f 秒）", key, icao, where, light["level"], time.monotonic() - t0
            )
            return light, None, res.get("usage")
        except AiError as e:
            # HD43：有多模式綜合那段的機場，回應內容的錯（`bad_format` 會帶回應的前 80 字）只印
            # 代碼，免得模型寫出的 WN3 數字進到公開的 Actions 日誌
            hide = icao in self.wn3 and e.code in CONTENT_ERRORS
            log.warning(
                "AI %s %s%s 失敗：%s［%s］（%.1f 秒）",
                key,
                icao,
                where,
                e.code if hide else e,
                e.trace(),
                time.monotonic() - t0,
            )
            if e.message:
                with self.lock:
                    if not self.stop.is_set():
                        self.first_message.setdefault(key, e.message)
            return error(key, e.code), e, e.usage
        except Exception:  # SDK 內部沒預期的錯：記成 network，不讓其他機場停掉
            log.exception("AI %s %s 失敗（沒預期的例外）", key, icao)
            return error(key, "network"), None, None

    def result(self, timed_out: bool = False) -> dict:
        """`{"ai": 頂層, "airports": {icao: airports[].ai}, "source": sources.ai, "usage",
        "costUsd", "errorMessages"}`（`source` 不含 `seconds`，由 `build.run_ai` 補；`usage`、
        `costUsd`、`errorMessages` 只進 `timing/`，HD26、HD30）。"""
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
                seconds = {k: self.seconds[k].get(icao) for k in KEYS}
                used = {k: self.usage[k][icao] for k in KEYS if icao in self.usage[k]}
                messages = {k: self.messages[k].get(icao) for k in KEYS}
                rows.append(
                    record(
                        a, self.run_at, reasons.get(icao), lights, details, seconds, used, messages
                    )
                )
            source = self._source(airports)
            totals = {
                k: usage.total(k, [*self.usage[k].values(), *self.dropped_usage[k]]) for k in KEYS
            }
            day = f"{self.now:%Y-%m-%d}"
            self._result = {
                "ai": top_level(),
                "airports": airports,
                "source": source,
                "usage": totals,
                "costUsd": {k: usage.cost_usd(k, totals[k], day) for k in KEYS},
                "errorMessages": {k: self.first_message.get(k) for k in KEYS},
            }
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
        if self.wn3:  # HD43：只記次數
            src["wn3Retries"] = dict(self.wn3_retries)
            src["wn3Dropped"] = dict(self.wn3_dropped)
        for k, r in self.regions.items():  # HD23：`geminiLocation`
            if r.last:
                src[f"{k}Location"] = r.last
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
