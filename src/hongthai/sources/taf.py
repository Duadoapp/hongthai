"""AviationWeather.gov Data API 的 TAF 與 METAR（JSON，已解碼）。

- `https://aviationweather.gov/api/data/taf?ids=RCTP,VHHH&format=json`
- `https://aviationweather.gov/api/data/metar?ids=RCTP,VHHH&format=json`

TAF 用回傳裡的 `fcsts`：每段有 `timeFrom`／`timeTo`（epoch 秒）、`fcstChange`（null＝主時段，
`FM`、`BECMG`、`TEMPO`）、`probability`（30／40）、`wdir`、`wspd`、`wgst`（節）。
沒有陣風時 `wgst` 是 null；`wdir` 可能是 `"VRB"`。

H9（41 個機場）起一次請求帶全部 ICAO（`ids` 逗號分隔；HD3 的 51 個是 254 字元，網址約 330 字元）。
沒有 TAF 或 METAR 的站回應裡就沒有那一站（該機場 `taf`／`metar` 是 null）；一站都沒有時 API 回
`204`、內容是空的，當成空陣列。2026-10-18 實測沒有 TAF 的：花蓮 RCYU、金門 RCBS、馬祖 RCFG、
溫州 ZSWZ、泉州 ZSQZ、珠海 ZGSD、宮古 ROMY（宮古有 METAR，其他六個 METAR 也沒有）。

中國機場的 TAF／METAR 風速用 `MPS`，API 解碼成節時是乘 2（3 MPS → 6 節，實際 5.8 節），
比實際高約 3%，偏保守，先不修正。

能見度、天氣現象、雲底（HD8，2026-10-19 用 `data` 分支的快照核對）：
- `visib` 是**法定英里**：數字（公制 TAF 的 `8000` 解碼成 `4.97`、`1500` 成 `0.93`），或字串 `"6+"`
  （公制的 `9999` 也是這個）、`"10+"`（美國站的 `P6SM`／`10SM` 以上）；TEMPO 沒報能見度時是空字串
  `""`。換成公尺：× 1609 後四捨五入到最接近的 50 公尺（公制 TAF 的 1000／0400／1600 換得回
  原值）；「以上」（`+` 結尾、`P` 開頭）記 **9999**；
  `"1/2"`、`"1 1/2"`、`"M1/4"`（`M`＝少於，照數字記）也看得懂；空的或看不懂的記 None（沒報）
- `wxString`：例如 `+TSRA`、`TSRA BR`、`-SHRA BR`、`NSW`，空白隔開、可能 null；拆開、原樣大寫
- 雲幕（`ceiling_ft`）：`clouds[]` 裡 `cover` 是 BKN／OVC（AviationWeather 垂直能見度用 `OVX`）
  的最低 `base`（呎），和 `vertVis` 取小；都沒有記 None
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from math import floor

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
    vis_m: int | None = None  # 公尺；「以上」記 9999（HD8）
    wx: tuple[str, ...] = ()  # 天氣現象，例如 ("+TSRA", "BR")
    ceiling_ft: int | None = None  # BKN／OVC 最低雲底或垂直能見度（呎）


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
    vis_m: int | None = None
    wx: tuple[str, ...] = ()
    ceiling_ft: int | None = None


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


SM_TO_M = 1609
VIS_PLUS_M = 9999  # 「6+」「10+」這種「以上」
CEILING_COVERS = ("BKN", "OVC", "OVX")


def _miles(text: str) -> float | None:
    """`"2"`、`"0.5"`、`"1/2"`、`"1 1/2"` → 英里；看不懂回 None。"""
    total = 0.0
    for part in text.split():
        if "/" in part:
            a, _, b = part.partition("/")
            try:
                total += float(a) / float(b)
            except (ValueError, ZeroDivisionError):
                return None
        else:
            try:
                total += float(part)
            except ValueError:
                return None
    return total if text.split() else None


VIS_STEP_M = 50


def _to_m(miles: float) -> int:
    """英里 → 公尺，四捨五入到最接近的 50 公尺（0.62 英里 → 1000、0.25 → 400、0.5 → 800）。"""
    return floor(miles * SM_TO_M / VIS_STEP_M + 0.5) * VIS_STEP_M


def vis_m(v) -> int | None:
    """AviationWeather 的 `visib`（法定英里）→ 公尺（見模組說明）。"""
    if isinstance(v, bool):
        return None
    if isinstance(v, int | float):
        return _to_m(v)
    if not isinstance(v, str):
        return None
    t = v.strip().upper().removesuffix("SM").strip()
    if not t:
        return None
    if t.endswith("+") or t.startswith("P"):
        return VIS_PLUS_M
    miles = _miles(t.removeprefix("M"))
    return None if miles is None else _to_m(miles)


def wx_tokens(v) -> tuple[str, ...]:
    return tuple(v.upper().split()) if isinstance(v, str) else ()


def ceiling_ft(clouds, vert_vis) -> int | None:
    """BKN／OVC（含 OVX）最低的 `base` 與 `vertVis` 取小。"""
    bases = [
        int(c["base"])
        for c in clouds or []
        if isinstance(c, dict)
        and str(c.get("cover") or "").upper() in CEILING_COVERS
        and _num(c.get("base")) is not None
    ]
    if _num(vert_vis) is not None:
        bases.append(int(vert_vis))
    return min(bases, default=None)


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
                    vis_m(f.get("visib")),
                    wx_tokens(f.get("wxString")),
                    ceiling_ft(f.get("clouds"), f.get("vertVis")),
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
            vis_m=vis_m(m.get("visib")),
            wx=wx_tokens(m.get("wxString")),
            ceiling_ft=ceiling_ft(m.get("clouds"), m.get("vertVis")),
        )
        prev = out.get(icao)
        if prev is None or (metar.observed and prev.observed and metar.observed > prev.observed):
            out[icao] = metar
    return out


def _get_json(url: str, ids: str) -> object:
    r = http_get(url, params={"ids": ids, "format": "json"}, error=TafError)
    if r.status_code == 204 or not r.content.strip():  # 一站都沒有資料
        return []
    return r.json()


def fetch(airports: list[Airport]) -> TafData:
    ids = ",".join(a.icao for a in airports)
    try:
        taf_json = _get_json(TAF_URL, ids)
        metar_json = _get_json(METAR_URL, ids)
    except ValueError as e:
        raise TafError(f"AviationWeather 回傳不是 JSON：{e}", "bad_json") from e
    if not isinstance(taf_json, list) or not isinstance(metar_json, list):
        raise TafError("AviationWeather 回傳格式不對", "bad_format")
    return TafData(
        parse_tafs(taf_json), parse_metars(metar_json), {"taf": taf_json, "metar": metar_json}
    )
