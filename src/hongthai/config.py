"""讀 `airports.json` 與 `confirmed.json`。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .timeutil import parse_time


@dataclass(frozen=True)
class Thresholds:
    """等級門檻，風速一律用節（HD2，2026-10-19）。依據寫在 `assess.py` 開頭。"""

    model_medium_gust_kt: float = 37
    model_high_gust_kt: float = 48
    taf_medium_gust_kt: float = 37
    taf_high_gust_kt: float = 48
    taf_high_wind_kt: float = 35
    crosswind_medium_kt: float = 27
    crosswind_high_kt: float = 33
    ec_p49_high: float = 0.3  # 系集陣風 ≥ 25 m/s（≈ 48.6 節）的機率


@dataclass(frozen=True)
class Runway:
    """一條跑道（實體跑道，同方位的平行跑道記一組）；`headings` 是兩個方向的方位（度，真北）。"""

    id: str
    headings: tuple[float, ...]


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
    runways: tuple[Runway, ...] = ()
    cwa_areas: tuple[str, ...] = ()  # 氣象署警戒區關鍵字（`airports.json` 的 `cwaAreas`）


@dataclass(frozen=True)
class ConfirmedPeriod:
    airport: str
    start: datetime
    end: datetime
    note: dict[str, str]


_THRESHOLD_KEYS = {
    "modelMediumGustKt": "model_medium_gust_kt",
    "modelHighGustKt": "model_high_gust_kt",
    "tafMediumGustKt": "taf_medium_gust_kt",
    "tafHighGustKt": "taf_high_gust_kt",
    "tafHighWindKt": "taf_high_wind_kt",
    "crosswindMediumKt": "crosswind_medium_kt",
    "crosswindHighKt": "crosswind_high_kt",
    "ecP49High": "ec_p49_high",
}


def _thresholds(icao: str, raw: dict) -> Thresholds:
    """`airports.json` 的 `thresholds`；HD2 以前的 m/s 鍵（`modelHighGustMs` 等）不再接受。"""
    unknown = sorted(set(raw) - set(_THRESHOLD_KEYS))
    if unknown:
        raise ValueError(f"airports.json {icao} 的 thresholds 有不認得的鍵：{', '.join(unknown)}")
    return Thresholds(**{_THRESHOLD_KEYS[k]: v for k, v in raw.items()})


def load_airports(path: str | Path) -> list[Airport]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    airports = []
    for a in raw:
        airports.append(
            Airport(
                icao=a["icao"],
                iata=a["iata"],
                tz=a["tz"],
                name=dict(a["name"]),
                lat=float(a["lat"]),
                lon=float(a["lon"]),
                warning_sources=tuple(a.get("warningSources", [])),
                thresholds=_thresholds(a["icao"], a.get("thresholds", {})),
                runways=tuple(
                    Runway(r["id"], tuple(float(h) for h in r["headings"]))
                    for r in a.get("runways", [])
                ),
                cwa_areas=tuple(a.get("cwaAreas", [])),
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
