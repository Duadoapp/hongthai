"""單位換算。HD2（2026-10-19）起等級規則、log 與輸出的新欄位一律用節；m/s 只留在既有欄位。"""

from __future__ import annotations

KT_PER_MS = 3600 / 1852  # 1 m/s ≈ 1.943844 節


def ms_to_kt(v: float | None) -> float | None:
    return None if v is None else v * KT_PER_MS


def kt_to_ms(v: float | None) -> float | None:
    return None if v is None else v / KT_PER_MS
