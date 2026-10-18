"""讀 `airports.json` 與 `confirmed.json`。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .timeutil import parse_time


@dataclass(frozen=True)
class Thresholds:
    model_high_gust_ms: float = 25
    model_medium_gust_ms: float = 15
    ec_p25_high: float = 0.3
    ec_p15_medium: float = 0.5
    taf_high_gust_kt: float = 45
    taf_high_wind_kt: float = 35
    taf_medium_gust_kt: float = 30


@dataclass(frozen=True)
class Airport:
    icao: str
    iata: str
    tz: str
    name: dict[str, str]
    lat: float
    lon: float
    warning_sources: tuple[str, ...]
    thresholds: Thresholds


@dataclass(frozen=True)
class ConfirmedPeriod:
    airport: str
    start: datetime
    end: datetime
    note: dict[str, str]


_THRESHOLD_KEYS = {
    "modelHighGustMs": "model_high_gust_ms",
    "modelMediumGustMs": "model_medium_gust_ms",
    "ecP25High": "ec_p25_high",
    "ecP15Medium": "ec_p15_medium",
    "tafHighGustKt": "taf_high_gust_kt",
    "tafHighWindKt": "taf_high_wind_kt",
    "tafMediumGustKt": "taf_medium_gust_kt",
}


def load_airports(path: str | Path) -> list[Airport]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    airports = []
    for a in raw:
        th = {_THRESHOLD_KEYS[k]: v for k, v in a.get("thresholds", {}).items()}
        airports.append(
            Airport(
                icao=a["icao"],
                iata=a["iata"],
                tz=a["tz"],
                name=dict(a["name"]),
                lat=float(a["lat"]),
                lon=float(a["lon"]),
                warning_sources=tuple(a.get("warningSources", [])),
                thresholds=Thresholds(**th),
            )
        )
    return airports


def load_confirmed(path: str | Path) -> list[ConfirmedPeriod]:
    """人工填的已確認停飛時段。格式：

    [{"airport": "VHHH", "from": "2026-10-20T00:00:00Z", "to": "2026-10-20T12:00:00Z",
      "note": {"zh-TW": "…", "en": "…"}}]
    """
    p = Path(path)
    if not p.exists():
        return []
    raw = json.loads(p.read_text(encoding="utf-8"))
    out = []
    for c in raw:
        start, end = parse_time(c["from"]), parse_time(c["to"])
        if start is None or end is None or end <= start:
            raise ValueError(f"confirmed.json 時段不正確：{c}")
        out.append(ConfirmedPeriod(c["airport"], start, end, dict(c.get("note", {}))))
    return out
