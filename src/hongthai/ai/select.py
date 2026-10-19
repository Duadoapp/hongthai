"""要請 AI 評哪些機場（Shawn 2026-10-18／19 定案）。

- 未來 5 天（20 格）任一格 `level` 是 `medium`／`high`／`confirmed` → 原因 `"level"`
- 不然，和上一份 `latest.json` 同機場同 `from` 的格比，任一格 `level` 不同 → 原因 `"changed"`
  （兩個原因都符合時記 `"level"`；沒有上一份就沒有「有變」）
- 排序：5 天內最高等級（confirmed > high > medium > low，`unknown` 最低）高的在前，同級的再依
  「第一個達到那級的格」早的在前，再同就照 `airports[]` 的順序；取前 `MAX_AIRPORTS` 個
"""

from __future__ import annotations

from .config import MAX_AIRPORTS

RANK = {"low": 0, "medium": 1, "high": 2, "confirmed": 3}
RISKY = ("medium", "high", "confirmed")


def _slots(airport: dict) -> list[dict]:
    return [s for s in airport.get("slots") or [] if isinstance(s, dict)]


def max_level(airport: dict) -> tuple[str | None, str | None]:
    """（5 天內最高等級，第一個達到那級的格的 `from`）；全部 `unknown` 或沒有格時是
    (None, None)。"""
    best, first = None, None
    for s in _slots(airport):
        lv = s.get("level")
        if lv in RANK and (best is None or RANK[lv] > RANK[best]):
            best, first = lv, s.get("from")
    return best, first


def _prev_levels(prev: dict | None) -> dict[tuple[object, object], object]:
    out: dict[tuple[object, object], object] = {}
    if not isinstance(prev, dict):
        return out
    for a in prev.get("airports") or []:
        if isinstance(a, dict):
            for s in _slots(a):
                out[(a.get("icao"), s.get("from"))] = s.get("level")
    return out


def reason(airport: dict, prev_levels: dict[tuple[object, object], object]) -> str | None:
    slots = _slots(airport)
    if any(s.get("level") in RISKY for s in slots):
        return "level"
    for s in slots:
        key = (airport.get("icao"), s.get("from"))
        if key in prev_levels and prev_levels[key] != s.get("level"):
            return "changed"
    return None


def qualifying(latest: dict, prev: dict | None) -> list[tuple[dict, str]]:
    """所有符合條件的機場（排好序、不截斷）：[(airport, 原因)]。"""
    prev_levels = _prev_levels(prev)
    found = []
    for i, a in enumerate(x for x in latest.get("airports") or [] if isinstance(x, dict)):
        why = reason(a, prev_levels)
        if why is None:
            continue
        best, _ = max_level(a)
        slots = _slots(a)
        first = next((j for j, s in enumerate(slots) if s.get("level") == best), len(slots))
        found.append(((-RANK.get(best, -1), first, i), a, why))
    found.sort(key=lambda t: t[0])
    return [(a, why) for _, a, why in found]


def candidates(latest: dict, prev: dict | None) -> list[tuple[dict, str]]:
    """要請 AI 評的機場：前 `MAX_AIRPORTS` 個 [(airport, `"level"`／`"changed"`)]。"""
    return qualifying(latest, prev)[:MAX_AIRPORTS]
