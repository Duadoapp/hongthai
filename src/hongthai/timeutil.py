"""時間工具：一律用帶時區的 UTC datetime，輸出 ISO 8601 加 `Z`。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

SLOT_HOURS = 6
SLOT_COUNT = 20  # 20 格 × 6 小時 = 120 小時


def utcnow() -> datetime:
    return datetime.now(UTC)


def floor_6h(t: datetime) -> datetime:
    """往前取整到 00／06／12／18Z。"""
    t = t.astimezone(UTC)
    return t.replace(hour=t.hour - t.hour % SLOT_HOURS, minute=0, second=0, microsecond=0)


def slot_bounds(now: datetime, count: int = SLOT_COUNT) -> list[tuple[datetime, datetime]]:
    """從現在往前取整的那一格起，連續 `count` 格 6 小時時段。"""
    start = floor_6h(now)
    step = timedelta(hours=SLOT_HOURS)
    return [(start + i * step, start + (i + 1) * step) for i in range(count)]


def iso(t: datetime | None) -> str | None:
    """UTC ISO 8601，秒為單位，結尾 `Z`。"""
    if t is None:
        return None
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_time(value: str | int | float | None) -> datetime | None:
    """把 ISO 字串（含時區或 Z）或 epoch 秒轉成 UTC datetime；空值回 None。"""
    if value is None or value == "":
        return None
    if isinstance(value, int | float):
        return datetime.fromtimestamp(value, UTC)
    t = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if t.tzinfo is None:
        t = t.replace(tzinfo=UTC)
    return t.astimezone(UTC)


def hours_between(a: datetime, b: datetime) -> float:
    return (b - a).total_seconds() / 3600
