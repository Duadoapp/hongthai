"""AviationWeather.gov Data API 的 TAF 與 METAR（JSON，已解碼）。

- `https://aviationweather.gov/api/data/taf?ids=RCTP,VHHH&format=json`
- `https://aviationweather.gov/api/data/metar?ids=RCTP,VHHH&format=json`

TAF 用回傳裡的 `fcsts`：每段有 `timeFrom`／`timeTo`（epoch 秒）、`fcstChange`（null＝主時段，
`FM`、`BECMG`、`TEMPO`）、`probability`（30／40）、`wdir`、`wspd`、`wgst`（節）。
沒有陣風時 `wgst` 是 null；`wdir` 可能是 `"VRB"`。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from ..config import Airport
from ..timeutil import parse_time
from . import SourceError, http_get

TAF_URL = "https://aviationweather.gov/api/data/taf"
METAR_URL = "https://aviationweather.gov/api/data/metar"


class TafError(SourceError):
    pass


@dataclass
class TafPeriod:
    start: datetime
    end: datetime
    kind: str  # main／tempo／prob30／prob40
    wdir: int | None
    wind_kt: float | None
    gust_kt: float | None


@dataclass
class TafInfo:
    issued: datetime | None
    valid_from: datetime | None
    valid_to: datetime | None
    raw: str
    periods: list[TafPeriod] = field(default_factory=list)


@dataclass
class Metar:
    observed: datetime | None
    wdir: int | None
    wind_kt: float | None
    gust_kt: float | None
    raw: str


@dataclass
class TafData:
    tafs: dict[str, TafInfo]
    metars: dict[str, Metar]
    raw: dict[str, object]


def _num(v) -> int | float | None:
    if isinstance(v, bool) or not isinstance(v, int | float):
        return None
    return v


def _dir(v) -> int | None:
    """`"VRB"` 之類的非數字回 None。"""
    if isinstance(v, bool) or not isinstance(v, int | float):
        return None
    return int(v)


def period_kind(f: dict) -> str:
    prob = f.get("probability")
    if prob:
        return f"prob{int(prob)}"
    if (f.get("fcstChange") or "").upper() == "TEMPO":
        return "tempo"
    return "main"


def parse_tafs(data: list[dict]) -> dict[str, TafInfo]:
    """同一站有多份時取最新發布的。"""
    out: dict[str, TafInfo] = {}
    for t in data:
        icao = t.get("icaoId")
        if not icao:
            continue
        info = TafInfo(
            issued=parse_time(t.get("issueTime")),
            valid_from=parse_time(t.get("validTimeFrom")),
            valid_to=parse_time(t.get("validTimeTo")),
            raw=t.get("rawTAF", ""),
        )
        for f in t.get("fcsts") or []:
            start, end = parse_time(f.get("timeFrom")), parse_time(f.get("timeTo"))
            if start is None or end is None:
                continue
            info.periods.append(
                TafPeriod(
                    start,
                    end,
                    period_kind(f),
                    _dir(f.get("wdir")),
                    _num(f.get("wspd")),
                    _num(f.get("wgst")),
                )
            )
        prev = out.get(icao)
        if prev is None or (info.issued and prev.issued and info.issued > prev.issued):
            out[icao] = info
    return out


def parse_metars(data: list[dict]) -> dict[str, Metar]:
    out: dict[str, Metar] = {}
    for m in data:
        icao = m.get("icaoId")
        if not icao:
            continue
        metar = Metar(
            observed=parse_time(m.get("obsTime")) or parse_time(m.get("reportTime")),
            wdir=_dir(m.get("wdir")),
            wind_kt=_num(m.get("wspd")),
            gust_kt=_num(m.get("wgst")),
            raw=m.get("rawOb", ""),
        )
        prev = out.get(icao)
        if prev is None or (metar.observed and prev.observed and metar.observed > prev.observed):
            out[icao] = metar
    return out


def fetch(airports: list[Airport]) -> TafData:
    ids = ",".join(a.icao for a in airports)
    try:
        taf_json = http_get(TAF_URL, params={"ids": ids, "format": "json"}, error=TafError).json()
        metar_json = http_get(
            METAR_URL, params={"ids": ids, "format": "json"}, error=TafError
        ).json()
    except ValueError as e:
        raise TafError(f"AviationWeather 回傳不是 JSON：{e}", "bad_json") from e
    if not isinstance(taf_json, list) or not isinstance(metar_json, list):
        raise TafError("AviationWeather 回傳格式不對", "bad_format")
    return TafData(
        parse_tafs(taf_json), parse_metars(metar_json), {"taf": taf_json, "metar": metar_json}
    )
