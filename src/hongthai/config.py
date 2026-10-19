"""讀 `airports.json` 與 `confirmed.json`。

`airports.json`（H9 起）是 `{"regions": [...], "airports": [...]}`：`regions` 是地區（顯示順序），
`airports` 照地區順序排、地區內照顯示順序。讀的時候檢查：ICAO 唯一、地區 id 唯一、每個機場的
`region` 在 `regions` 裡、`airports` 依 `regions` 的順序分段（同一地區的機場連在一起）、`tz` 是
合法的 IANA 時區、跑道方位在 0–360、看 NWS 警報（`warningSources` 有 `nws`，HD3）的機場有合法的
`nwsZone`（例如 `GUZ001`）。不對就丟 `ValueError`。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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
    # 第五階段天氣種類（HD8，2026-10-19 定案；先上線、累積一個月紀錄再調）。
    # 能見度公尺、雲底呎、雨量毫米
    taf_rain_medium_vis_m: float = 1600  # TS 且能見度 ≤ 這個 → 中
    taf_snow_medium_vis_m: float = 1600  # SN（不是 -SN／+SN）且能見度 ≤ 這個 → 中
    fog_medium_vis_m: float = 1000  # 能見度 < 這個 → 中（官方與 GFS 同一組）
    fog_high_vis_m: float = 400  # 能見度 < 這個 → 高；只用在官方層，模式層的霧封頂在中（HD10）
    fog_medium_ceiling_ft: float = 200  # 雲底 ≤ 這個 → 中
    fog_high_ceiling_ft: float = 100  # 雲底 ≤ 這個 → 高；只用在官方層，模式層的霧封頂在中（HD10）
    model_rain_medium_mm6h: float = 30
    model_rain_high_mm6h: float = 60
    ec_p24h_rain50_medium: float = 0.3  # 系集 24 小時雨量 ≥ 50 mm 的機率
    model_snow_medium_mm6h: float = 5  # 降雪（水當量）
    model_snow_high_mm6h: float = 10
    model_freezing_rain_high_mm6h: float = 1


@dataclass(frozen=True)
class Runway:
    """一條跑道（實體跑道，同方位的平行跑道記一組）；`headings` 是兩個方向的方位（度，真北）。"""

    id: str
    headings: tuple[float, ...]


@dataclass(frozen=True)
class Region:
    """地區（H9）：`id` 是 `latest.json` 的契約（和 Duado spec 第 16 節一致），`name` 四語。"""

    id: str
    name: dict[str, str]


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
    region: str = ""  # 地區 id（`Region.id`）
    nws_zone: str = ""  # NWS 的 zone（`airports.json` 的 `nwsZone`，HD3），例如關島 GUZ001
    # 氣象署局屬站站號（`airports.json` 的 `cwaStation`，HD13）：AviationWeather 沒有 METAR 時
    # 用這站的觀測（金門 467110、馬祖 467990）
    cwa_station: str | None = None


@dataclass(frozen=True)
class ConfirmedPeriod:
    airport: str
    start: datetime
    end: datetime
    note: dict[str, str]


_NWS_ZONE = re.compile(r"^[A-Z]{2}Z\d{3}$")

_THRESHOLD_KEYS = {
    "modelMediumGustKt": "model_medium_gust_kt",
    "modelHighGustKt": "model_high_gust_kt",
    "tafMediumGustKt": "taf_medium_gust_kt",
    "tafHighGustKt": "taf_high_gust_kt",
    "tafHighWindKt": "taf_high_wind_kt",
    "crosswindMediumKt": "crosswind_medium_kt",
    "crosswindHighKt": "crosswind_high_kt",
    "ecP49High": "ec_p49_high",
    "tafRainMediumVisM": "taf_rain_medium_vis_m",
    "tafSnowMediumVisM": "taf_snow_medium_vis_m",
    "fogMediumVisM": "fog_medium_vis_m",
    "fogHighVisM": "fog_high_vis_m",
    "fogMediumCeilingFt": "fog_medium_ceiling_ft",
    "fogHighCeilingFt": "fog_high_ceiling_ft",
    "modelRainMediumMm6h": "model_rain_medium_mm6h",
    "modelRainHighMm6h": "model_rain_high_mm6h",
    "ecP24hRain50Medium": "ec_p24h_rain50_medium",
    "modelSnowMediumMm6h": "model_snow_medium_mm6h",
    "modelSnowHighMm6h": "model_snow_high_mm6h",
    "modelFreezingRainHighMm6h": "model_freezing_rain_high_mm6h",
}


def _thresholds(icao: str, raw: dict) -> Thresholds:
    """`airports.json` 的 `thresholds`；HD2 以前的 m/s 鍵（`modelHighGustMs` 等）不再接受。"""
    unknown = sorted(set(raw) - set(_THRESHOLD_KEYS))
    if unknown:
        raise ValueError(f"airports.json {icao} 的 thresholds 有不認得的鍵：{', '.join(unknown)}")
    return Thresholds(**{_THRESHOLD_KEYS[k]: v for k, v in raw.items()})


def _raw(path: str | Path) -> dict:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not {"regions", "airports"} <= set(raw):
        raise ValueError('airports.json 要是 {"regions": [...], "airports": [...]}')
    return raw


def _regions(raw: dict) -> list[Region]:
    return [Region(r["id"], dict(r["name"])) for r in raw["regions"]]


def load_regions(path: str | Path) -> list[Region]:
    return _regions(_raw(path))


def load_airports(path: str | Path) -> list[Airport]:
    raw = _raw(path)
    airports = []
    for a in raw["airports"]:
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
                region=a["region"],
                nws_zone=a.get("nwsZone", ""),
                cwa_station=a.get("cwaStation") or None,
            )
        )
    _check(_regions(raw), airports)
    return airports


def _check(regions: list[Region], airports: list[Airport]) -> None:
    ids = [r.id for r in regions]
    if len(set(ids)) != len(ids):
        raise ValueError(f"airports.json 的地區 id 重複：{ids}")
    icaos = [a.icao for a in airports]
    dup = sorted({i for i in icaos if icaos.count(i) > 1})
    if dup:
        raise ValueError(f"airports.json 的 ICAO 重複：{', '.join(dup)}")
    for a in airports:
        if a.region not in ids:
            raise ValueError(f"airports.json {a.icao} 的 region {a.region!r} 不在 regions 裡")
        try:
            ZoneInfo(a.tz)
        except (ZoneInfoNotFoundError, ValueError) as e:
            raise ValueError(f"airports.json {a.icao} 的 tz {a.tz!r} 不是 IANA 時區") from e
        for r in a.runways:
            if not r.headings or not all(0 <= h <= 360 for h in r.headings):
                raise ValueError(
                    f"airports.json {a.icao} 跑道 {r.id} 的方位不在 0–360：{r.headings}"
                )
        if "nws" in a.warning_sources and not _NWS_ZONE.match(a.nws_zone):
            raise ValueError(
                f"airports.json {a.icao} 看 NWS 警報但 nwsZone {a.nws_zone!r} 不是 zone 代碼"
                "（例如 GUZ001）"
            )
    # 照地區順序分段：機場的地區順序不能往回跳
    order = [ids.index(a.region) for a in airports]
    if order != sorted(order):
        raise ValueError("airports.json 的 airports 要照 regions 的順序排（同一地區連在一起）")


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
