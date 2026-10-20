"""中央氣象署開放資料平台：颱風警報。

注意：提示詞寫的 `W-C0034-005` 依平台的 API 文件（`https://opendata.cwa.gov.tw/apidoc/v1`）
是「颱風消息與警報-熱帶氣旋路徑」；**颱風警報是 `W-C0034-001`**（「颱風消息與警報-颱風警報」），
所以用後者。

`GET https://opendata.cwa.gov.tw/api/v1/rest/datastore/W-C0034-001`，授權碼放 `Authorization`
標頭（只從環境變數 `CWA_API_KEY` 讀，不放 repo）。回傳是 CAP 格式轉的 JSON：
`records.info[]`，每筆有 `headline`（`海上颱風警報`／`海上陸上颱風警報`／`解除颱風警報`）、
`urgency`、`effective`、`expires`、`description.section[]`（`title`／`value`，其中
`警戒區域及事項` 是警戒區文字）、`description["typhoon-info"]`（颱風名稱）、
`area[].areaDesc`（縣市或海面名稱）。

警戒區判斷每個機場一組關鍵字（`airports.json` 的 `cwaAreas`，例如桃園、松山是「北部」「桃園」
「臺北」「台北」「新北」，高雄是「南部」「高雄」）：陸上的 `areaDesc` 含任一關鍵字（海面、海峽、
海域不算），或警戒區文字含任一關鍵字（後面接「海面」的不算，例如「北部海面」）。關鍵字是字串比對，
「東北部」也會比到「北部」——偏保守。

豪雨特報（HD8）：天氣特報有兩個資料集，`W-C0033-001`「各別縣市地區目前之天氣警特報情形」
（每個縣市一筆、列出目前生效的特報）與 `W-C0033-002`「各別天氣警特報之內容及所影響之區域」
（每則特報一筆、影響區域用另一套區域名稱，見平台文件附錄 B）。機場已經有一組縣市關鍵字
（`cwaAreas`），所以用 **`W-C0033-001`**（`HAZARD_URL`，同一把授權碼，多一個請求）：
`records.location[]` 每筆 `locationName`（縣市名，例如「金門縣」「連江縣」）與
`hazardConditions.hazards[]`，每則 `info.phenomena`（大雨、豪雨、大豪雨、超大豪雨、濃霧、
陸上強風…）、`info.significance`（特報）、`validTime.startTime`／`endTime`。
- 縣市名含機場任一個 `cwaAreas` 關鍵字、`phenomena` 是「大豪雨」或「超大豪雨」才產生
  `cwa_heavy_rain`（中，`detail` 是那個字樣）；大雨、豪雨特報不算（Shawn 2026-10-19 定案）。
  `endTime` 已過的不算
- 這個資料集的回應格式是照平台 API 文件與資料集說明寫的（沒有授權碼不能實抓），解析寫得寬鬆：
  `hazards` 是物件或陣列都行、找不到 `info` 就在那一層找 `phenomena`。原始回應存在
  `history/raw/<日期>/<時間>-cwa-hazards.json`，第一次實跑後對一次
- 特報的時間沒寫時區時當台灣時間（UTC+8，`_tw_time`）
- 和颱風警報分開 try：特報失敗只記 `sources.cwa.heavyRainOk: false`＋`heavyRainError`，颱風警報照常

濃霧特報（HD13，Shawn 2026-10-19）：同一個 `W-C0033-001` 回應（2026-10-19 06:56Z 第一次實抓，
格式和上面寫的一樣：`hazards` 是陣列、時間是沒有時區的 `2026-10-15 16:23:00`），`phenomena`
含「濃霧」、縣市名含機場任一個 `cwaAreas` 關鍵字 → `cwa_dense_fog`（中，`detail` 是「濃霧」），
台灣十個機場都適用。同一報同一機場只出一則

局屬站觀測當 METAR 用（HD13，只有金門 467110、馬祖 467990，`airports.json` 的 `cwaStation`）：
AviationWeather 沒有這兩站的 TAF／METAR。資料集 **`O-A0003-001`「氣象觀測站-10分鐘綜觀氣象資料」**
（舊名「現在天氣觀測報告」；`OBS_URL`，同一把授權碼，每報多一個請求），照平台 API 文件
（`https://opendata.cwa.gov.tw/apidoc/v1` 的 swagger）與資料標準說明文件 V1.05
（`https://opendata.cwa.gov.tw/opendatadoc/Observation/O-A0003-001.pdf`）寫，沒有授權碼不能實抓：
- 參數 `StationId`（可以多個，逗號隔開）；回傳 `records.Station[]`，每站 `StationId`、
  `ObsTime.DateTime`（`2026-10-19T20:00:00+08:00`）、`WeatherElement` 底下 `Weather`（天氣描述
  ＝雲量晴／多雲／陰＋天氣現象「有霧」「有靄」「有雷雨」…，文件附表 2）、`VisibilityDescription`
  （能見度描述，公里的特定字串，文件的例子是 `>30`）、`WindDirection`（度，990＝風向不定）、
  `WindSpeed`（m/s）、`GustInfo.PeakGustSpeed`（最大瞬間風，m/s）與
  `GustInfo.Occurred_at.DateTime`
- 缺測：`-99`（缺值或資料異常）、`X`（儀器故障）與其他負值、看不懂的都記 None；990 的風向記 None
  （＝VRB，側風取風速本身）
- 能見度（`cwa_vis_m`）：數字（`0.5`）× 1000、四捨五入到 50 公尺；`>30` 這種「以上」記 9999（10 公里
  以上也記 9999）；`<1` 這種「以下」記比它少 50 公尺（950，霧至少算到中）；區間（`2-5`）取下限。
  文件只給了 `>30` 一個例子，其他寫法是照這幾種猜的、寫得寬鬆，看不懂記 None
- 天氣現象（`cwa_wx`）：去掉雲量與「有」，照附表 2 對到 METAR 代碼——霧 `FG`、靄 `BR`、
  霾 `HZ`、雨 `RA`、陣雨 `SHRA`、雷雨 `TSRA`、大雷雨 `+TSRA`、雹 `GR`、雷雹 `TSGR`、
  大雷雹 `+TSGR`、雨雪 `RASN`、陣雨雪 `SHRASN`、大雪 `+SN`、雷雪 `TSSN`、雪珠 `SG`、冰珠 `PL`、
  雷／雷聲 `TS`（毛毛雨 `DZ`、雪 `SN` 不在附表 2，留著）；對不到的放原文（去掉「有」，例如
  「閃電」），「-」與只有雲量的是空的
- 陣風：`PeakGustSpeed` 的發生時間在觀測前 1 小時內才算（`GUST_MAX_AGE`；文件沒寫它統計的時段，
  防它是當日最大值），沒寫發生時間的照算（偏保守）；不算的也不寫進 `raw`
- `raw` 是 `CWA 467110 2026-10-19T12:00Z 能見度 0.5 km 陰有霧 風 090° 3 m/s`；`source` 是 `"cwa"`
- 和颱風警報、特報分開 try：失敗只記 `sources.cwa.obsOk: false`＋`obsError`。原始回應存在
  `history/raw/<日期>/<時間>-cwa-obs.json`，合併後第一報對一次欄位名
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from math import floor
from zoneinfo import ZoneInfo

import requests

from ..timeutil import iso, parse_time
from ..units import ms_to_kt
from . import NonStrictTLSAdapter, SourceError, http_get
from .taf import VIS_PLUS_M, VIS_STEP_M, Metar

URL = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/W-C0034-001"
TAIPEI = ZoneInfo("Asia/Taipei")
HAZARD_URL = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/W-C0033-001"
HEAVY_RAIN = ("大豪雨", "超大豪雨")  # 「超大豪雨」也含「大豪雨」，比對用 `in`
HEAVY_RAIN_EN = {"大豪雨": "torrential rain", "超大豪雨": "extremely torrential rain"}
DENSE_FOG = "濃霧"
OBS_URL = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/O-A0003-001"
GUST_MAX_AGE = timedelta(hours=1)
VRB_DIR = 990  # 風向不定
SKY = ("多雲", "晴", "陰")  # 天氣描述開頭的雲量
# 天氣現象 → METAR 代碼；長的在前（比對用 `in`，「大雷雨」要先於「雷雨」「雨」）
WX_CODES = (
    ("大雷雹", "+TSGR"),
    ("雷雹", "TSGR"),
    ("大雷雨", "+TSRA"),
    ("雷雨", "TSRA"),
    ("雷雪", "TSSN"),
    ("陣雨雪", "SHRASN"),
    ("雨雪", "RASN"),
    ("陣雨", "SHRA"),
    ("毛毛雨", "DZ"),
    ("大雪", "+SN"),
    ("雪珠", "SG"),
    ("冰珠", "PL"),
    ("雪", "SN"),
    ("雹", "GR"),
    ("霧", "FG"),
    ("靄", "BR"),
    ("霾", "HZ"),
    ("雷聲", "TS"),
    ("雨", "RA"),
    ("雷", "TS"),
)
HEADLINE_SEA = "海上颱風警報"
HEADLINE_LAND = "海上陸上颱風警報"
STALE_AFTER = timedelta(hours=6)  # 過了 expires 6 小時還沒更新就當作過期
_SEA_AREA = re.compile(r"海面|海峽|海域")
TAOYUAN_AREAS = ("北部", "桃園", "臺北", "台北", "新北")
TAOYUAN_NAME = {"zh-TW": "桃園", "zh-HK": "桃園", "zh-CN": "桃园", "en": "Taoyuan"}


class CwaError(SourceError):
    pass


@dataclass
class CwaBulletin:
    """一則生效中的颱風警報（還沒對到機場）。"""

    land: bool  # 海上陸上颱風警報
    zh_name: str
    en_name: str
    area_descs: list[str]
    zone: str  # 原文的警戒區域及事項（只有繁中）
    issued_at: str | None


@dataclass
class CwaWarning:
    """對到某個機場的警報。"""

    kind: str  # typhoon_land／typhoon_sea／cwa_heavy_rain／cwa_dense_fog
    level: str
    in_zone: bool  # 機場在（陸上）警戒區
    text: dict[str, str]
    detail: str  # 原文的警戒區域及事項（只有繁中）
    issued_at: str | None


@dataclass
class CwaHazard:
    """一個縣市生效中的一則天氣特報（`W-C0033-001`，HD8）。"""

    location: str
    phenomena: str
    start: str | None
    end: str | None


@dataclass
class CwaData:
    bulletins: list[CwaBulletin]
    raw: object
    hazards: list[CwaHazard] = field(default_factory=list)
    hazards_raw: object = None
    hazards_error: str | None = None  # 特報那個請求失敗的代碼（颱風警報照常）
    obs: dict[str, Metar] = field(default_factory=dict)  # 站號 → 局屬站觀測（HD13）
    obs_raw: object = None
    obs_error: str | None = None  # 觀測那個請求失敗的代碼（颱風警報、特報照常）


def _sections(info: dict) -> dict[str, str]:
    desc = info.get("description") or {}
    secs = desc.get("section") if isinstance(desc, dict) else None
    return {s.get("title", ""): s.get("value", "") for s in secs or [] if isinstance(s, dict)}


def _typhoon_names(info: dict) -> tuple[str, str]:
    """回傳（中文名, 英文名），找不到給空字串。"""
    desc = info.get("description") or {}
    for ti in desc.get("typhoon-info") or [] if isinstance(desc, dict) else []:
        for s in ti.get("section") or []:
            if s.get("typhoon_name") or s.get("cwa_typhoon_name"):
                return s.get("cwa_typhoon_name", ""), (s.get("typhoon_name") or "").title()
    return "", ""


def _area_descs(info: dict) -> list[str]:
    return [a.get("areaDesc", "") for a in info.get("area") or [] if isinstance(a, dict)]


def in_zone(area_descs: list[str], zone: str, keywords: tuple[str, ...]) -> bool:
    """陸上警戒區含這組關鍵字的任一個（見模組說明）。"""
    for desc in area_descs:
        if not _SEA_AREA.search(desc) and any(k in desc for k in keywords):
            return True
    return any(re.search(re.escape(k) + r"(?!海面)", zone) for k in keywords)


def taoyuan_in_zone(info: dict) -> bool:
    """陸上警戒區含桃園（第一階段的介面，留給測試與相容）。"""
    zone = _sections(info).get("警戒區域及事項", "")
    return in_zone(_area_descs(info), zone, TAOYUAN_AREAS)


def _text(
    land: bool, in_zone: bool, zh_name: str, en_name: str, place: dict[str, str]
) -> dict[str, str]:
    zh = f"（{zh_name}颱風）" if zh_name else ""
    en = f" (Typhoon {en_name})" if en_name else ""
    cn = f"（{en_name}）" if en_name else ""
    if land:
        t = {
            "zh-TW": f"中央氣象署海上陸上颱風警報{zh}",
            "zh-HK": f"中央氣象署海上陸上颱風警報{zh}",
            "zh-CN": f"中央气象署海上陆上台风警报{cn}",
            "en": f"CWA sea and land typhoon warning{en}",
        }
        if in_zone:
            t["zh-TW"] += f"，{place['zh-TW']}在警戒區"
            t["zh-HK"] += f"，{place['zh-HK']}在警戒區"
            t["zh-CN"] += f"，{place['zh-CN']}在警戒区"
            t["en"] += f"; {place['en']} is in the warning area"
        return t
    return {
        "zh-TW": f"中央氣象署海上颱風警報{zh}",
        "zh-HK": f"中央氣象署海上颱風警報{zh}",
        "zh-CN": f"中央气象署海上台风警报{cn}",
        "en": f"CWA sea typhoon warning{en}",
    }


def parse_bulletins(data: dict, now: datetime) -> list[CwaBulletin]:
    records = data.get("records") or {}
    infos = records.get("info") if isinstance(records, dict) else None
    if infos is None:
        raise CwaError("氣象署回傳沒有 records.info", "bad_format")
    if isinstance(infos, dict):
        infos = [infos]
    out = []
    for info in infos:
        headline = (info.get("headline") or "").strip()
        if headline not in (HEADLINE_SEA, HEADLINE_LAND):
            continue
        if (info.get("urgency") or "") == "Past":
            continue
        expires = parse_time(info.get("expires"))
        if expires is not None and expires + STALE_AFTER < now:
            continue
        zh_name, en_name = _typhoon_names(info)
        out.append(
            CwaBulletin(
                land=headline == HEADLINE_LAND,
                zh_name=zh_name,
                en_name=en_name,
                area_descs=_area_descs(info),
                zone=_sections(info).get("警戒區域及事項", ""),
                issued_at=iso(parse_time(info.get("effective") or info.get("onset"))),
            )
        )
    return out


def for_airport(
    bulletins: list[CwaBulletin], keywords: tuple[str, ...], place: dict[str, str]
) -> list[CwaWarning]:
    """把警報對到一個機場：陸上警報且機場在警戒區 → 高，其他（海上、或陸上但不在警戒區）→ 中。"""
    out = []
    for b in bulletins:
        hit = b.land and in_zone(b.area_descs, b.zone, keywords)
        out.append(
            CwaWarning(
                kind="typhoon_land" if b.land else "typhoon_sea",
                level="high" if hit else "medium",
                in_zone=hit,
                text=_text(b.land, hit, b.zh_name, b.en_name, place),
                detail=b.zone,
                issued_at=b.issued_at,
            )
        )
    return out


def parse_warnings(
    data: dict,
    now: datetime,
    keywords: tuple[str, ...] = TAOYUAN_AREAS,
    place: dict[str, str] = TAOYUAN_NAME,
) -> list[CwaWarning]:
    """`parse_bulletins` ＋ `for_airport`（預設桃園）。"""
    return for_airport(parse_bulletins(data, now), keywords, place)


def _as_list(v) -> list:
    if isinstance(v, list):
        return v
    return [v] if isinstance(v, dict) else []


def _tw_time(v) -> datetime | None:
    """沒有時區的時間字串當台灣時間；有時區或 epoch 照 `parse_time`。"""
    if isinstance(v, str) and v.strip():
        try:
            t = datetime.fromisoformat(v.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        if t.tzinfo is None:
            t = t.replace(tzinfo=TAIPEI)
        return t.astimezone(UTC)
    return parse_time(v) if isinstance(v, int | float) else None


def parse_hazards(data: dict, now: datetime) -> list[CwaHazard]:
    """`W-C0033-001` → 每個縣市生效中的特報（格式見模組說明；`endTime` 已過的不算）。"""
    records = data.get("records") or {}
    locations = records.get("location") if isinstance(records, dict) else None
    if locations is None:
        raise CwaError("氣象署特報回傳沒有 records.location", "bad_format")
    out = []
    for loc in _as_list(locations):
        name = loc.get("locationName") or ""
        cond = loc.get("hazardConditions") or {}
        hazards = cond.get("hazards") if isinstance(cond, dict) else cond
        for h in _as_list(hazards):
            info = h.get("info") if isinstance(h.get("info"), dict) else h
            phen = (info.get("phenomena") or "").strip()
            vt = h.get("validTime") if isinstance(h.get("validTime"), dict) else {}
            end = _tw_time(vt.get("endTime"))
            if not phen or (end is not None and end < now):
                continue
            out.append(CwaHazard(name, phen, iso(_tw_time(vt.get("startTime"))), iso(end)))
    return out


def heavy_rain_for_airport(
    hazards: list[CwaHazard], keywords: tuple[str, ...], place: dict[str, str]
) -> list[CwaWarning]:
    """大豪雨以上特報、縣市名含機場的關鍵字 → `cwa_heavy_rain`（中）。同一種字樣只出一則。"""
    out: list[CwaWarning] = []
    seen: set[str] = set()
    for h in hazards:
        if not any(k in h.phenomena for k in HEAVY_RAIN) or h.phenomena in seen:
            continue
        if not any(k in h.location for k in keywords):
            continue
        seen.add(h.phenomena)
        en = HEAVY_RAIN_EN.get(h.phenomena, "torrential rain")
        out.append(
            CwaWarning(
                kind="cwa_heavy_rain",
                level="medium",
                in_zone=True,
                text={
                    "zh-TW": f"中央氣象署{h.phenomena}特報，{place['zh-TW']}在特報範圍",
                    "zh-HK": f"中央氣象署{h.phenomena}特報，{place['zh-HK']}在特報範圍",
                    "zh-CN": f"中央气象署{h.phenomena}特报，{place['zh-CN']}在特报范围",
                    "en": f"CWA {en} advisory; {place['en']} is in the advisory area",
                },
                detail=h.phenomena,
                issued_at=h.start,
            )
        )
    return out


def dense_fog_for_airport(
    hazards: list[CwaHazard], keywords: tuple[str, ...], place: dict[str, str]
) -> list[CwaWarning]:
    """濃霧特報、縣市名含機場的關鍵字 → `cwa_dense_fog`（中，HD13）。同一個機場只出一則。"""
    for h in hazards:
        if DENSE_FOG in h.phenomena and any(k in h.location for k in keywords):
            return [
                CwaWarning(
                    kind="cwa_dense_fog",
                    level="medium",
                    in_zone=True,
                    text={
                        "zh-TW": f"中央氣象署濃霧特報，{place['zh-TW']}在特報範圍",
                        "zh-HK": f"中央氣象署濃霧特報，{place['zh-HK']}在特報範圍",
                        "zh-CN": f"中央气象署浓雾特报，{place['zh-CN']}在特报范围",
                        "en": f"CWA dense fog advisory; {place['en']} is in the advisory area",
                    },
                    detail=DENSE_FOG,
                    issued_at=h.start,
                )
            ]
    return []


# ---- 局屬站觀測（HD13）----


def _obs_num(v) -> float | None:
    """觀測值：數字或數字字串；負值（-99 缺值等）、`X`（儀器故障）與看不懂的回 None。"""
    if isinstance(v, bool):
        return None
    if isinstance(v, str):
        try:
            v = float(v.strip())
        except ValueError:
            return None
    if not isinstance(v, int | float) or v < 0:
        return None
    return float(v)


def _km_to_m(km: float) -> int:
    m = floor(km * 1000 / VIS_STEP_M + 0.5) * VIS_STEP_M
    return VIS_PLUS_M if m >= 10000 else m


def cwa_vis_m(desc) -> int | None:
    """`VisibilityDescription`（公里）→ 公尺（規則見模組說明）。"""
    if isinstance(desc, int | float) and not isinstance(desc, bool):
        return None if desc < 0 else _km_to_m(desc)
    if not isinstance(desc, str):
        return None
    t = desc.strip().replace("km", "").replace("公里", "").replace(" ", "")
    t = t.replace("＞", ">").replace("＜", "<").replace("～", "-").replace("~", "-")
    if t.startswith(">"):
        km = _obs_num(t[1:].lstrip("="))
        return None if km is None else _km_to_m(km)
    if t.startswith("<"):
        km = _obs_num(t[1:].lstrip("="))
        return None if km is None or km <= 0 else max(_km_to_m(km) - VIS_STEP_M, 0)
    lo, sep, _ = t.partition("-")
    if sep and lo:  # 區間取下限（「-99」的 lo 是空字串，不會進來）
        km = _obs_num(lo)
        return None if km is None else _km_to_m(km)
    km = _obs_num(t)
    return None if km is None else _km_to_m(km)


def cwa_wx(weather) -> tuple[str, ...]:
    """`Weather`（雲量＋天氣現象）→ METAR 天氣代碼；對不到的放原文（見模組說明）。"""
    if not isinstance(weather, str):
        return ()
    t = weather.strip()
    for sky in SKY:
        t = t.removeprefix(sky)
    t = t.removeprefix("有").strip()
    if not t or t in ("-", "-99", "X"):
        return ()
    for zh, code in WX_CODES:
        if zh in t:
            return (code,)
    return (t,)


def _obs_raw(
    sid: str,
    observed: datetime | None,
    vis: object,
    weather: object,
    el: dict,
    gust_ms: float | None,
) -> str:
    parts = ["CWA", sid]
    if observed is not None:
        parts.append(f"{observed:%Y-%m-%dT%H:%MZ}")
    if isinstance(vis, str | int | float) and str(vis).strip() and str(vis).strip() != "-99":
        parts += ["能見度", str(vis).strip(), "km"]
    if isinstance(weather, str) and weather.strip() and weather.strip() != "-99":
        parts.append(weather.strip())
    spd = _obs_num(el.get("WindSpeed"))
    if spd is not None:
        wd = _obs_num(el.get("WindDirection"))
        d = "不定" if wd is None or wd == VRB_DIR else f"{round(wd):03d}°"
        parts += ["風", d, f"{spd:g} m/s"]
    if gust_ms is not None:
        parts += ["陣風", f"{gust_ms:g} m/s"]
    return " ".join(parts)


def _gust_ms(el: dict, observed: datetime | None) -> float | None:
    """最大瞬間風（m/s）；發生在觀測前超過 `GUST_MAX_AGE` 的不算。"""
    gust = el.get("GustInfo") if isinstance(el.get("GustInfo"), dict) else {}
    g = _obs_num(gust.get("PeakGustSpeed"))
    occ = gust.get("Occurred_at") if isinstance(gust.get("Occurred_at"), dict) else {}
    at = _tw_time(occ.get("DateTime"))
    if g is None or (at is not None and observed is not None and observed - at > GUST_MAX_AGE):
        return None
    return g


def parse_obs(data: dict, stations: tuple[str, ...] = ()) -> dict[str, Metar]:
    """`O-A0003-001` → 站號 → `Metar`（`stations` 空的時候全收；同一站多筆取觀測時間最新的）。"""
    records = data.get("records") or {}
    rows = records.get("Station") if isinstance(records, dict) else None
    if rows is None and isinstance(records, dict):
        rows = records.get("station")
    if rows is None:
        raise CwaError("氣象署觀測回傳沒有 records.Station", "bad_format")
    out: dict[str, Metar] = {}
    for st in _as_list(rows):
        sid = str(st.get("StationId") or "")
        if not sid or (stations and sid not in stations):
            continue
        obs_time = st.get("ObsTime")
        observed = _tw_time(obs_time.get("DateTime") if isinstance(obs_time, dict) else obs_time)
        el = st.get("WeatherElement") if isinstance(st.get("WeatherElement"), dict) else {}
        vis = el.get("VisibilityDescription", el.get("Visibility"))
        wd = _obs_num(el.get("WindDirection"))
        spd = _obs_num(el.get("WindSpeed"))
        gust = _gust_ms(el, observed)
        metar = Metar(
            observed=observed,
            wdir=None if wd is None or wd == VRB_DIR else round(wd) % 360,
            wind_kt=None if spd is None else round(ms_to_kt(spd), 1),
            gust_kt=None if gust is None else round(ms_to_kt(gust), 1),
            raw=_obs_raw(sid, observed, vis, el.get("Weather"), el, gust),
            vis_m=cwa_vis_m(vis),
            wx=cwa_wx(el.get("Weather")),
            source="cwa",
        )
        prev = out.get(sid)
        if prev is None or (observed and prev.observed and observed > prev.observed):
            out[sid] = metar
    return out


def fetch(api_key: str | None, now: datetime, stations: tuple[str, ...] = ()) -> CwaData:
    if not api_key:
        raise CwaError("沒有設定 CWA_API_KEY", "no_api_key")
    session = requests.Session()
    session.mount("https://opendata.cwa.gov.tw/", NonStrictTLSAdapter())
    r = http_get(URL, session=session, headers={"Authorization": api_key}, error=CwaError)
    try:
        data = r.json()
    except ValueError as e:
        raise CwaError("氣象署回傳不是 JSON", "bad_json") from e
    if str(data.get("success")).lower() != "true":
        raise CwaError("氣象署回傳 success 不是 true", "api_error")
    out = CwaData(parse_bulletins(data, now), data)
    try:  # 特報和颱風警報分開：這裡失敗只記代碼
        r = http_get(
            HAZARD_URL, session=session, headers={"Authorization": api_key}, error=CwaError
        )
        hz = r.json()
        if str(hz.get("success")).lower() != "true":
            raise CwaError("氣象署特報回傳 success 不是 true", "api_error")
        out.hazards_raw = hz
        out.hazards = parse_hazards(hz, now)
    except (CwaError, ValueError, AttributeError) as e:
        out.hazards_error = getattr(e, "code", None) if isinstance(e, CwaError) else "bad_json"
    if not stations:
        return out
    try:  # 局屬站觀測（HD13）也分開：失敗只記代碼
        out.obs_raw = fetch_obs(api_key, stations, session)
        out.obs = parse_obs(out.obs_raw, stations)
    except (CwaError, ValueError, AttributeError) as e:
        out.obs_error = getattr(e, "code", None) if isinstance(e, CwaError) else "bad_json"
    return out


def fetch_obs(
    api_key: str, stations: tuple[str, ...], session: requests.Session | None = None
) -> dict:
    """局屬站觀測 `O-A0003-001` 的原始回應（解析用 `parse_obs`）。`fetch` 與每小時的事件保存
    （HD20，`events.py`）共用；失敗丟 `CwaError`（不是 JSON 時是 `ValueError`）。"""
    if session is None:
        session = requests.Session()
        session.mount("https://opendata.cwa.gov.tw/", NonStrictTLSAdapter())
    r = http_get(
        OBS_URL,
        session=session,
        params={"StationId": ",".join(stations)},
        headers={"Authorization": api_key},
        error=CwaError,
    )
    ob = r.json()
    if str(ob.get("success")).lower() != "true":
        raise CwaError("氣象署觀測回傳 success 不是 true", "api_error")
    return ob
