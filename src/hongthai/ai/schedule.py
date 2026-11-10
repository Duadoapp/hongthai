"""哪幾報要請 AI 評、不評的那報怎麼出（HD50，Shawn 2026-11-11 00:51 定案）。

- **哪一報要評**（`decide`，純函式）：用「時段」判斷——`build.slot_of` 算出這一報屬於
  `build.SLOTS` 的哪一個（≤ 開始時間最近的那個；排程晚到、Worker 與 GitHub 都觸發、手動按的
  都用同一套），再看它的 UTC 小時在 `config.SCHEDULE` 的哪一組：
  - `always`（01:05Z，台灣早上 09:05 那報）：評，原因 `morning`
  - `typhoonHigh`（13:05Z，台灣 21:05 那報）：**有颱風**（`has_typhoon`：這一報的
    `typhoons.json` 的 `storms` 有還沒結束的；減弱或結束的已經搬到 `ended`、範圍外的在
    `outOfRange`，都不算）**而且有高**（`has_high`：任一機場的規則燈綜合等級——5 天內最高，
    `select.max_level`，AI 選機場用的同一個——是 `high` 以上；`confirmed` 比 `high` 高，也算）
    才評，原因 `typhoon_high`
  - 其他時段：不評，原因 `off_schedule`
  - 手動 build 的 `--ai`（`build.yml` 的 `workflow_dispatch` 輸入 `ai`）：`auto` 照上面；
    `on` 一律評（`forced`）、`off` 一律不評（`disabled`）。排程與 Worker 觸發都是 `auto`
- **`ai.schedule`**（`latest.json` 頂層 `ai` 多的欄位，`plan`）：
  `{"evaluated", "reason", "nextSlot"}`；`nextSlot` 是這一報的時段之後下一個照平常規則
  （`always`）會評的時段（ISO；`always` 是空的時是 `null`）
- **不評的那報**（`carry_over`）：每個機場沿用上一份 `latest.json` 的 `ai`（兩顆燈的
  `status`、`level`、`comment`、`sentences`、`model` 與原本的 `evaluatedAt`），但：
  - 上一份沒有、那個機場上一份沒有 `ai`、`evaluatedAt` 是 `null`（兩顆都 `error`，沒有時間
    就不能判斷新舊）或超過 `CARRY_MAX_AGE_H`（26）小時：兩顆燈 `error: "off_schedule"`、
    `evaluatedAt: null`
  - 上一份那顆是 `skipped`（「沒看到明顯風險」）或等級比這一報的規則燈低（`confirmed` 當
    `high` 比），而這一報規則燈是中以上：那顆改 `error: "stale"`
  - 上一份那顆是 `error`：照樣沿用（含 `error` 代碼）
  - 處理完兩顆都是 `error` 時 `evaluatedAt` 是 `null`（同 `run.airport_ai`）"""

from __future__ import annotations

import copy
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from ..timeutil import iso, parse_time
from . import select, usage
from .config import CARRY_MAX_AGE_H, KEYS, SCHEDULE
from .run import error, top_level

MODES = ("auto", "on", "off")
MORNING, TYPHOON_HIGH, OFF_SCHEDULE, FORCED, DISABLED = (
    "morning",
    "typhoon_high",
    "off_schedule",
    "forced",
    "disabled",
)
STALE = "stale"
LIGHTS = ("ok", "skipped", "error")


def has_typhoon(typhoons: dict | None) -> bool:
    """這一報的 `typhoons.json` 有還沒結束的颱風：`storms` 裡有一顆（有 `ended` 標記的不算）。"""
    storms = typhoons.get("storms") if isinstance(typhoons, dict) else None
    if not isinstance(storms, list):
        return False
    return any(isinstance(s, dict) and not s.get("ended") for s in storms)


def has_high(latest: dict) -> bool:
    """任一機場的規則燈綜合等級（5 天內最高，`select.max_level`）是 `high` 以上。"""
    high = select.RANK["high"]
    return any(
        select.RANK.get(select.max_level(a)[0] or "", -1) >= high
        for a in latest.get("airports") or []
        if isinstance(a, dict)
    )


def decide(slot: datetime, mode: str, latest: dict, typhoons: dict | None) -> tuple[bool, str]:
    """這一報要不要評 →（要不要, 原因）。`slot` 是這一報的時段（`build.slot_of`，UTC）。"""
    if mode == "off":
        return False, DISABLED
    if mode == "on":
        return True, FORCED
    hour = slot.astimezone(UTC).hour
    if hour in SCHEDULE.get("always", ()):
        return True, MORNING
    if hour in SCHEDULE.get("typhoonHigh", ()) and has_typhoon(typhoons) and has_high(latest):
        return True, TYPHOON_HIGH
    return False, OFF_SCHEDULE


def next_slot(slot: datetime, slots: Iterable[tuple[int, int]]) -> datetime | None:
    """`slot` 之後下一個照平常規則（`SCHEDULE["always"]`）會評的時段；`slots` 是 `build.SLOTS`。"""
    always = [(h, m) for h, m in slots if h in SCHEDULE.get("always", ())]
    day = slot.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    after = [
        t
        for t in (day + timedelta(days=d, hours=h, minutes=m) for d in (0, 1) for h, m in always)
        if t > slot
    ]
    return min(after, default=None)


def plan(
    slot: datetime,
    mode: str,
    latest: dict,
    typhoons: dict | None,
    slots: Iterable[tuple[int, int]],
) -> dict:
    """`latest.json` 頂層的 `ai.schedule`。"""
    evaluated, reason = decide(slot, mode, latest, typhoons)
    return {"evaluated": evaluated, "reason": reason, "nextSlot": iso(next_slot(slot, slots))}


# ---- 不評的那報：沿用上一份 ----


def _time(value: object) -> datetime | None:
    try:
        return parse_time(value) if isinstance(value, str) else None
    except ValueError:
        return None


def carry_light(key: str, old: object, rule: str | None) -> dict:
    """一顆燈：上一份那顆 `old`、這一報規則燈的綜合等級 `rule`（`select.max_level`）。"""
    if not isinstance(old, dict) or old.get("status") not in LIGHTS:
        return error(key, OFF_SCHEDULE)
    if old["status"] == "error":
        light = copy.deepcopy(old)
        light.setdefault("error", OFF_SCHEDULE)
        return light
    now_rank = min(select.RANK.get(rule or "", -1), select.RANK["high"])  # AI 沒有 confirmed
    if now_rank >= select.RANK["medium"]:
        old_rank = select.RANK.get(old.get("level") or "", -1)
        if old["status"] == "skipped" or old_rank < now_rank:
            return error(key, STALE)
    return copy.deepcopy(old)


def carry_airport(airport: dict, old: object, run_at: datetime) -> dict:
    """一個機場的 `ai`：`old` 是上一份同機場的 `ai`（沒有是 None）。"""
    evaluated = _time(old.get("evaluatedAt")) if isinstance(old, dict) else None
    if (
        not isinstance(old, dict)
        or evaluated is None
        or run_at - evaluated > timedelta(hours=CARRY_MAX_AGE_H)
    ):
        return {"evaluatedAt": None, **{k: error(k, OFF_SCHEDULE) for k in KEYS}}
    rule, _ = select.max_level(airport)
    lights = {k: carry_light(k, old.get(k), rule) for k in KEYS}
    all_error = all(lights[k]["status"] == "error" for k in KEYS)
    return {"evaluatedAt": None if all_error else iso(evaluated), **lights}


def carry_over(latest: dict, prev: dict | None) -> dict[str, dict]:
    """每個機場的 `ai`（`{icao: airports[].ai}`），沿用上一份 `prev`。"""
    run_at = _time(latest.get("generatedAt"))
    old: dict[object, object] = {}
    if isinstance(prev, dict) and isinstance(prev.get("airports"), list):
        old = {a.get("icao"): a.get("ai") for a in prev["airports"] if isinstance(a, dict)}
    out = {}
    for a in latest["airports"]:
        icao = a["icao"]
        if run_at is None:
            out[icao] = {"evaluatedAt": None, **{k: error(k, OFF_SCHEDULE) for k in KEYS}}
        else:
            out[icao] = carry_airport(a, old.get(icao), run_at)
    return out


def skipped_result(latest: dict, prev: dict | None, sched: dict) -> dict:
    """不評的那報，形狀同 `run.Duel.result()`：每個機場沿用上一份（`carry_over`）、`sources.ai` 是
    `{"ok": true, "calls": 全 0, "skipped": 原因}`（`off_schedule`／`disabled`）、`usage` 與
    `costUsd` 是 0。不呼叫任何模型、不寫戰績與每日次數檔。"""
    totals = {k: usage.total(k, []) for k in KEYS}
    return {
        "ai": {**top_level(), "schedule": sched},
        "airports": carry_over(latest, prev),
        "source": {"ok": True, "calls": dict.fromkeys(KEYS, 0), "skipped": sched["reason"]},
        "usage": totals,
        "costUsd": dict.fromkeys(KEYS, 0.0),
        "errorMessages": dict.fromkeys(KEYS),
    }
