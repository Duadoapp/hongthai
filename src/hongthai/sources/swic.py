"""WMO 惡劣天氣資訊中心（SWIC，香港天文台代 WMO 經營）轉存的 CAP 警報：中國氣象局、韓國氣象廳、
菲律賓 PAGASA（HD29，**只列出、不升級**：每種都是 `low`）。

調查報告 `docs/surveys/2026-10-22-cap-warnings.md`（HD28），樣本在
`docs/surveys/samples/2026-10-22-cap/`。

- 清單 `https://severeweather.wmo.int/json/wmo_all.json`（SWIC 網頁自己用的檔，沒有公開文件；
  約 0.9 MB、全世界生效中的 CAP 警報，每則 `id`、`event`、`headline`、`sent`、`expires`（UTC，
  `YYYY-MM-DD HH:MM:SS`）、`mid`（會員代碼）、`url`＝CAP 原文的相對路徑），一報抓一次，只留
  中國 `001`、韓國 `095`、菲律賓 `021`
- 先用清單的 `event` 篩種類，中國再用 `id` 前 6 碼（發布台的行政區碼）篩到我們機場的地市
  （前 4 碼）、所在省的省台（`xx0000`）與全國（`000000`／`100000`，沒驗證過，寬一點）
- 剩下的逐則抓 CAP 原文（`https://severeweather.wmo.int/v2/cap-alerts/<url>`，CAP 1.2 XML），
  同一個 URL 一報只抓一次、最多 4 條平行（`WORKERS`）；清單逾時 20 秒、每則 10 秒。單則抓不到
  只跳過那一則（記在 `sources.swic.capErrors`），清單抓不到才算整個來源失敗
- 用原文判斷：`status` 是 `Actual`、`expires` 在產出時間之後（沒有 `expires` 用清單的）。
  `msgType` 是 `Cancel`、中國的解除電文（headline 含「解除」／"lift"）、韓國事件名結尾是
  Clear／Release 的**不列**；不收的顏色、等級（大風藍色、豪雨注意報）也不列。這幾種都拿來
  蓋掉同一機場同一類較舊的那則（見下）

對機場（`airports.json`）：
- 中國：`cmaAreas`（機場所在的縣級代碼，GB/T 2260 前 6 碼）。CAP 的 `geocode`（CPEAS 12 碼）
  前 6 碼等於其中一個，或是那個縣所屬的地市（`xxxx00`）、省（`xx0000`）就算涵蓋。有些預警只發
  到鄉鎮街道，用縣級比對偏保守
- 韓國：CAP 的 `<polygon>`（緯度,經度）；機場座標在多邊形裡或離邊界 5 公里內（`KR_BUFFER_KM`，
  仁川、濟州在海邊，SWIC 的多邊形很粗）
- 菲律賓：`psgcAreas`（PSGC 9 碼）。CAP 的 `SAME` 等於其中一個就算

種類（照報告 5.3 節的命名，等級 29W 報告後再定，現在全部 `low`）：
- 中國：颱風 紅／橙／黃／藍 `cma_typhoon_<顏色>`、大風 紅／橙／黃 `cma_gale_<顏色>`（藍色不收）、
  暴雨 紅／橙 `cma_rainstorm_<顏色>`、大霧 紅／橙 `cma_fog_<顏色>`。種類看簡中 `info` 的
  `event`（台风、大风、暴雨、大雾）、顏色看簡中 headline（沒有簡中退回英文 `event` 與
  headline）。**颱風的 `event` 這次沒有實例**（英文照 CMA 預警信號猜 `typhoon`）
- 韓國：事件名是 `<種類> Advisory|Warning`，後面可能接 Change／Issue／Clear／Release
  （樣本 `StrongWind Advisory Change`），空白不算、大小寫不分。颱風警報／注意報
  `kma_typhoon_warning`／`_advisory`、強風警報／注意報 `kma_strong_wind_*`、豪雨警報
  `kma_heavy_rain_warning`、大雪警報 `kma_heavy_snow_warning`（豪雨、大雪的注意報不收）。
  **颱風、大雪的 `event` 這次沒有實例**（`Typhoon Warning`、`HeavySnow Warning` 是照強風、
  豪雨的寫法猜的）
- 菲律賓：`Tropical Cyclone Warning`，號數看 `parameter` 的 `Public Storm Warning Signal Level`
  （沒有就看 headline 的 `Signal #2`）→ `pagasa_tcws_<1–5>`；豪雨紅色 `pagasa_rainfall_red`：
  **沒有樣本**，照 PAGASA 的 Heavy Rainfall Warning 猜：`event` 或 headline 含
  `Rainfall Warning`、而且 headline 有 `Red` 這個字

同一機場同一類（中國同一種預警不分顏色、韓國同一種特報不分警報／注意報、菲律賓風球不分號數）取
`sent` 最新的那則：升級、降級後舊的那則還掛在清單裡到它自己的 `expires` 也不會重複列；最新的是
解除就不列。`issuedAt` 是那則的 `sent`。

四語文字：
- 中國：簡中 headline 當 zh-CN，zh-TW 用 OpenCC `s2twp`（再把「釋出」改回「發布」：`s2twp`
  照軟體用語把「发布」轉成「釋出」）、zh-HK 用 `s2hk`，en 用英文 headline；結尾加
  「（中國氣象局，經 WMO SWIC）」／"(CMA via WMO SWIC)"。`detail` 是簡中 headline
- 韓國、菲律賓：中文三語用固定句型，括號裡是機場名稱（例「韓國氣象廳強風注意報（濟州，經 WMO
  SWIC）」），en 用 CAP 的英文 headline 加 "(KMA via WMO SWIC)"／"(PAGASA via WMO SWIC)"；
  `detail` 是英文 headline

SWIC 使用須知：可以再使用，要註明由相應機關發布；SWIC 沒有警報不代表官方沒發（可能是 CAP 格式
或 feed 的問題）。
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from functools import cache
from math import cos, hypot, radians

from .. import budget
from ..config import Airport
from ..timeutil import iso, parse_time
from . import SourceError, http_get

URL = "https://severeweather.wmo.int/json/wmo_all.json"
CAP_URL = "https://severeweather.wmo.int/v2/cap-alerts/{url}"
LIST_TIMEOUT = 20
CAP_TIMEOUT = 10
WORKERS = 4
KR_BUFFER_KM = 5.0
MIDS = {"001": "cma", "095": "kma", "021": "pagasa"}  # SWIC 會員代碼 → `warnings[].source`
SOURCES = frozenset(MIDS.values())
NATIONAL_PREFIXES = frozenset({"000000", "100000"})

_NS = {"cap": "urn:oasis:names:tc:emergency:cap:1.2"}
LEVEL = "low"  # HD29：全部只列出

# ---- 中國 ----
CN_TYPES_ZH = {"台风": "typhoon", "大风": "gale", "暴雨": "rainstorm", "大雾": "fog"}
CN_TYPES_EN = {
    "typhoon": "typhoon",
    "gale": "gale",
    "rainstorm": "rainstorm",
    "dense fog": "fog",
    "heavy fog": "fog",
    "fog": "fog",
}
CN_COLORS_ZH = {"红色": "red", "橙色": "orange", "黄色": "yellow", "蓝色": "blue"}
CN_COLORS = {  # 種類 → 收的顏色
    "typhoon": ("red", "orange", "yellow", "blue"),
    "gale": ("red", "orange", "yellow"),
    "rainstorm": ("red", "orange"),
    "fog": ("red", "orange"),
}
_EN_COLOR = re.compile(r"\b(red|orange|yellow|blue)\b", re.I)
_CN_NAMES = {  # 種類 → zh-TW／zh-HK、zh-CN、en（沒有簡中或英文 info 時的固定句型）
    "typhoon": ("颱風", "台风", "typhoon"),
    "gale": ("大風", "大风", "gale"),
    "rainstorm": ("暴雨", "暴雨", "rainstorm"),
    "fog": ("大霧", "大雾", "fog"),
}
_COLOR_NAMES = {  # 顏色 → zh-TW／zh-HK、zh-CN
    "red": ("紅色", "红色"),
    "orange": ("橙色", "橙色"),
    "yellow": ("黃色", "黄色"),
    "blue": ("藍色", "蓝色"),
}
_TW_FIXES = (("釋出", "發布"),)

# ---- 韓國 ----
_KR_EVENT = re.compile(
    r"^\s*(?P<type>.+?)\s+(?P<grade>advisory|warning)(?:\s+(?P<action>\w+))?\s*$", re.I
)
KR_TYPES = {  # 事件名去空白、小寫 → (kind 中段, 收的等級)
    "typhoon": ("typhoon", ("warning", "advisory")),
    "strongwind": ("strong_wind", ("warning", "advisory")),
    "heavyrain": ("heavy_rain", ("warning",)),
    "heavysnow": ("heavy_snow", ("warning",)),
}
KR_RELEASE = frozenset({"clear", "release", "cancel", "lift", "lifted"})
_KR_NAMES = {  # kind → zh-TW／zh-HK、zh-CN
    "kma_typhoon_warning": ("颱風警報", "台风警报"),
    "kma_typhoon_advisory": ("颱風注意報", "台风注意报"),
    "kma_strong_wind_warning": ("強風警報", "强风警报"),
    "kma_strong_wind_advisory": ("強風注意報", "强风注意报"),
    "kma_heavy_rain_warning": ("豪雨警報", "豪雨警报"),
    "kma_heavy_snow_warning": ("大雪警報", "大雪警报"),
}

# ---- 菲律賓 ----
PH_SIGNAL_PARAM = "Public Storm Warning Signal Level"
_PH_SIGNAL = re.compile(r"Signal\s*(?:No\.?\s*|#\s*)(\d)", re.I)
_PH_RED = re.compile(r"\bred\b", re.I)

KINDS: dict[str, str] = {  # kind → 等級（HD29 全部 low）
    **{f"cma_typhoon_{c}": LEVEL for c in CN_COLORS["typhoon"]},
    **{f"cma_gale_{c}": LEVEL for c in CN_COLORS["gale"]},
    **{f"cma_rainstorm_{c}": LEVEL for c in CN_COLORS["rainstorm"]},
    **{f"cma_fog_{c}": LEVEL for c in CN_COLORS["fog"]},
    **dict.fromkeys(_KR_NAMES, LEVEL),
    **{f"pagasa_tcws_{n}": LEVEL for n in range(1, 6)},
    "pagasa_rainfall_red": LEVEL,
}


class SwicError(SourceError):
    pass


@dataclass
class SwicAlert:
    """一則 CAP 解析後的結果。`kind` 是 None 的（解除、Cancel、Clear、不收的顏色或等級）不列，
    只拿來蓋掉同一類較舊的。"""

    source: str  # cma／kma／pagasa
    family: str  # 同一類（取最新那則用），例如 cma_gale、kma_strong_wind、pagasa_tcws
    kind: str | None
    code: str  # CAP 的 event（中國用英文 info 的）
    headline_en: str
    headline_zh: str  # 中國簡中 info 的 headline；韓國、菲律賓空字串
    issued_at: str | None
    areas: tuple[str, ...] = ()  # 中國 CPEAS 12 碼、菲律賓 SAME
    polygons: tuple[tuple[tuple[float, float], ...], ...] = ()  # 韓國，(緯度, 經度)
    url: str = ""


@dataclass
class SwicWarning:
    source: str
    kind: str
    level: str
    code: str
    text: dict[str, str]
    issued_at: str | None
    detail: str


@dataclass
class SwicData:
    alerts: list[SwicAlert]
    raw: dict[str, object]
    caps: int  # 這報抓了幾則 CAP
    cap_errors: dict[str, str] = field(default_factory=dict)  # url → 原因


# ---- 清單 ----


def _cn_kind(t: str | None, color: str | None) -> str | None:
    if t is None or color is None or color not in CN_COLORS[t]:
        return None
    return f"cma_{t}_{color}"


def _cn_lift(headline_zh: str, headline_en: str) -> bool:
    return "解除" in headline_zh or "lift" in headline_en.lower()


def cn_prefixes(airports: list[Airport]) -> tuple[frozenset[str], frozenset[str]]:
    """中國機場的 (地市前 4 碼, 發布台前 6 碼也要抓的省台與全國)。"""
    areas = {c for a in airports if "cma" in a.warning_sources for c in a.cma_areas}
    cities = frozenset(c[:4] for c in areas)
    return cities, frozenset({c[:2] + "0000" for c in areas} | NATIONAL_PREFIXES)


def _wanted(item: dict, cities: frozenset[str], issuers: frozenset[str], now: datetime) -> bool:
    """清單的一則要不要抓 CAP 原文（只看清單裡的欄位，寧寬勿漏；真正的判斷在原文）。"""
    source = MIDS.get(str(item.get("mid") or ""))
    if source is None or not _url(item):
        return False
    try:
        expires = parse_time(str(item.get("expires") or "") or None)
    except ValueError:
        expires = None
    if expires is not None and expires <= now:
        return False
    event = str(item.get("event") or "").strip()
    headline = str(item.get("headline") or "")
    if source == "cma":
        issuer = str(item.get("id") or "")[:6]
        if issuer[:4] not in cities and issuer not in issuers:
            return False
        # 顏色不篩：不收的顏色也要抓（降級時蓋掉較舊的，見 `parse_cap`）
        return event.lower() in CN_TYPES_EN
    if source == "kma":
        m = _KR_EVENT.match(event)
        return m is not None and re.sub(r"\s+", "", m["type"]).lower() in KR_TYPES
    low = f"{event} {headline}".lower()
    return "tropical cyclone warning" in low or "rainfall warning" in low


def _url(item: dict) -> str:
    return str(item.get("url") or item.get("capURL") or "")


# ---- CAP 原文 ----


def _text(el: ET.Element | None, path: str) -> str:
    if el is None:
        return ""
    found = el.find(path, _NS)
    return (found.text or "").strip() if found is not None and found.text else ""


def _polygon(s: str) -> tuple[tuple[float, float], ...]:
    pts = []
    for pair in s.split():
        try:
            lat, lon = (float(v) for v in pair.split(","))
        except ValueError:
            continue
        pts.append((lat, lon))
    return tuple(pts) if len(pts) >= 3 else ()


def parse_cap(xml: str | bytes, source: str, now: datetime, url: str = "") -> SwicAlert | None:
    """一則 CAP 原文 → `SwicAlert`；不是我們要的種類、不是 Actual、已經過期的回 None。"""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as e:
        raise SwicError(f"SWIC CAP {url} 不是 XML", "bad_xml") from e
    if _text(root, "cap:status") != "Actual":
        return None
    cancel = _text(root, "cap:msgType") == "Cancel"
    try:
        issued = iso(parse_time(_text(root, "cap:sent") or None))
    except ValueError:
        issued = None
    infos = root.findall("cap:info", _NS)
    if not infos:
        return None
    by_lang: dict[str, ET.Element] = {}
    for info in infos:
        by_lang.setdefault(_text(info, "cap:language").lower(), info)
    en = next((i for lang, i in by_lang.items() if lang.startswith("en")), None)
    zh = next((i for lang, i in by_lang.items() if lang.startswith("zh")), None)
    first = en if en is not None else infos[0]
    expires = []
    for info in infos:
        try:
            t = parse_time(_text(info, "cap:expires") or None)
        except ValueError:
            t = None
        if t is not None:
            expires.append(t)
    if expires and max(expires) <= now:
        return None
    areas, polygons = [], []
    for info in infos:
        for area in info.findall("cap:area", _NS):
            for gc in area.findall("cap:geocode", _NS):
                v = _text(gc, "cap:value")
                if v and v not in areas:
                    areas.append(v)
            for p in area.findall("cap:polygon", _NS):
                poly = _polygon(p.text or "")
                if poly and poly not in polygons:
                    polygons.append(poly)
    event = _text(first, "cap:event")
    headline_en = _text(first, "cap:headline") or event
    if source == "cma":
        headline_zh = _text(zh, "cap:headline")
        t = CN_TYPES_ZH.get(_text(zh, "cap:event")) or CN_TYPES_EN.get(event.lower())
        if t is None:
            return None
        color = next((c for zc, c in CN_COLORS_ZH.items() if zc in headline_zh), None)
        if color is None:
            m = _EN_COLOR.search(headline_en)
            color = m.group(1).lower() if m else None
        # 不收的顏色（例如大風藍色）也留著：降級成它時拿來蓋掉較舊的黃色
        kind = None if cancel or _cn_lift(headline_zh, headline_en) else _cn_kind(t, color)
        code = event or _text(zh, "cap:event")
        return SwicAlert(
            source, f"cma_{t}", kind, code, headline_en, headline_zh, issued, tuple(areas), (), url
        )
    if source == "kma":
        m = _KR_EVENT.match(event)
        if m is None:
            return None
        spec = KR_TYPES.get(re.sub(r"\s+", "", m["type"]).lower())
        if spec is None:
            return None
        mid, grades = spec
        grade = m["grade"].lower()
        release = cancel or (m["action"] or "").lower() in KR_RELEASE
        # 不收的等級（豪雨、大雪注意報）也留著：降級成它時拿來蓋掉較舊的警報
        kind = None if release or grade not in grades else f"kma_{mid}_{grade}"
        return SwicAlert(
            source, f"kma_{mid}", kind, event, headline_en, "", issued, (), tuple(polygons), url
        )
    # 菲律賓
    low = f"{event} {headline_en}".lower()
    if "tropical cyclone warning" in low:
        params = {
            _text(p, "cap:valueName"): _text(p, "cap:value")
            for info in infos
            for p in info.findall("cap:parameter", _NS)
        }
        level = params.get(PH_SIGNAL_PARAM, "")
        if not level.isdigit():
            m = _PH_SIGNAL.search(headline_en)
            level = m.group(1) if m else ""
        n = int(level) if level.isdigit() else 0
        if not 1 <= n <= 5 and not cancel:
            return None
        kind = None if cancel else f"pagasa_tcws_{n}"
        return SwicAlert(
            source, "pagasa_tcws", kind, event, headline_en, "", issued, tuple(areas), (), url
        )
    if "rainfall warning" in low and (cancel or _PH_RED.search(headline_en)):
        kind = None if cancel else "pagasa_rainfall_red"
        return SwicAlert(
            source, "pagasa_rainfall", kind, event, headline_en, "", issued, tuple(areas), (), url
        )
    return None


# ---- 對機場 ----


def cn_covers(code: str, areas: tuple[str, ...]) -> bool:
    """CAP 的 CPEAS 代碼（取前 6 碼）有沒有涵蓋這些縣級代碼：同一個縣，或是它的地市、省。"""
    c = code[:6]
    if len(c) < 6 or not c.isdigit():
        return False
    for a in areas:
        if c == a or (c[4:] == "00" and c[:4] == a[:4]) or (c[2:] == "0000" and c[:2] == a[:2]):
            return True
    return False


def _inside(lat: float, lon: float, poly: tuple[tuple[float, float], ...]) -> bool:
    hit = False
    j = len(poly) - 1
    for i in range(len(poly)):
        yi, xi = poly[i]
        yj, xj = poly[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            hit = not hit
        j = i
    return hit


def distance_km(lat: float, lon: float, poly: tuple[tuple[float, float], ...]) -> float:
    """機場到多邊形的距離（公里）；在裡面是 0。小範圍用等距圓柱投影近似就夠。"""
    if _inside(lat, lon, poly):
        return 0.0
    kx, ky = 111.32 * cos(radians(lat)), 110.574

    def xy(p: tuple[float, float]) -> tuple[float, float]:
        return (p[1] - lon) * kx, (p[0] - lat) * ky

    best = float("inf")
    for a, b in zip(poly, poly[1:] + poly[:1], strict=True):
        (x1, y1), (x2, y2) = xy(a), xy(b)
        dx, dy = x2 - x1, y2 - y1
        seg = dx * dx + dy * dy
        t = 0.0 if seg == 0 else max(0.0, min(1.0, -(x1 * dx + y1 * dy) / seg))
        best = min(best, hypot(x1 + t * dx, y1 + t * dy))
    return best


def covers(alert: SwicAlert, airport: Airport) -> bool:
    if alert.source == "cma":
        return any(cn_covers(c, airport.cma_areas) for c in alert.areas)
    if alert.source == "kma":
        return any(distance_km(airport.lat, airport.lon, p) <= KR_BUFFER_KM for p in alert.polygons)
    return any(c in airport.psgc_areas for c in alert.areas)


@cache
def _opencc(config: str):
    import opencc

    return opencc.OpenCC(config)


def to_tw(s: str) -> str:
    out = _opencc("s2twp").convert(s)
    for a, b in _TW_FIXES:
        out = out.replace(a, b)
    return out


def to_hk(s: str) -> str:
    return _opencc("s2hk").convert(s)


def text_for(alert: SwicAlert, airport: Airport) -> dict[str, str]:
    kind = alert.kind or ""
    if alert.source == "cma":
        _, t, color = kind.split("_", 2)
        tw, cn, en = _CN_NAMES[t]
        ctw, ccn = _COLOR_NAMES[color]
        zh = alert.headline_zh
        return {
            "zh-TW": f"{to_tw(zh) if zh else f'{tw}{ctw}預警'}（中國氣象局，經 WMO SWIC）",
            "zh-HK": f"{to_hk(zh) if zh else f'{tw}{ctw}預警'}（中國氣象局，經 WMO SWIC）",
            "zh-CN": f"{zh or f'{cn}{ccn}预警'}（中国气象局，经 WMO SWIC）",
            "en": f"{alert.headline_en or f'{color} {en} warning'} (CMA via WMO SWIC)",
        }
    name = airport.name
    if alert.source == "kma":
        tw, cn = _KR_NAMES[kind]
        return {
            "zh-TW": f"韓國氣象廳{tw}（{name['zh-TW']}，經 WMO SWIC）",
            "zh-HK": f"韓國氣象廳{tw}（{name['zh-HK']}，經 WMO SWIC）",
            "zh-CN": f"韩国气象厅{cn}（{name['zh-CN']}，经 WMO SWIC）",
            "en": f"{alert.headline_en} (KMA via WMO SWIC)",
        }
    if kind == "pagasa_rainfall_red":
        tw, hk, cn = "豪雨紅色警報", "暴雨紅色警告", "暴雨红色警报"
    else:
        n = kind.rsplit("_", 1)[-1]
        tw = hk = f"熱帶氣旋 {n} 號風球"
        cn = f"热带气旋 {n} 号风球"
    return {
        "zh-TW": f"菲律賓 PAGASA {tw}（{name['zh-TW']}，經 WMO SWIC）",
        "zh-HK": f"菲律賓 PAGASA {hk}（{name['zh-HK']}，經 WMO SWIC）",
        "zh-CN": f"菲律宾 PAGASA {cn}（{name['zh-CN']}，经 WMO SWIC）",
        "en": f"{alert.headline_en} (PAGASA via WMO SWIC)",
    }


def for_airport(alerts: list[SwicAlert], airport: Airport) -> list[SwicWarning]:
    """機場生效中的警報（只看 `warningSources` 有的 cma／kma／pagasa）；同一類取 `sent` 最新的，
    最新的是解除就不列。"""
    latest: dict[str, SwicAlert] = {}
    for a in alerts:
        if a.source not in airport.warning_sources or not covers(a, airport):
            continue
        old = latest.get(a.family)
        if old is None or (a.issued_at or "") > (old.issued_at or ""):
            latest[a.family] = a
    out = []
    for a in latest.values():
        if a.kind is None:
            continue
        detail = a.headline_zh or a.headline_en
        out.append(
            SwicWarning(
                a.source, a.kind, KINDS[a.kind], a.code, text_for(a, airport), a.issued_at, detail
            )
        )
    return sorted(out, key=lambda w: (w.source, w.kind))


# ---- 抓 ----


def _fetch_cap(url: str) -> bytes:
    r = http_get(
        CAP_URL.format(url=url.lstrip("/")),
        error=SwicError,
        timeout=CAP_TIMEOUT,
        retries=2,
        backoff=1.0,
    )
    return r.content


def fetch(airports: list[Airport], now: datetime) -> SwicData:
    """抓清單一次＋要的 CAP 原文（`airports` 是 `warningSources` 有 cma／kma／pagasa 的機場）。"""
    mine = [a for a in airports if SOURCES & set(a.warning_sources)]
    if not mine:
        raise SwicError("沒有機場看 cma／kma／pagasa，SWIC 不知道要查誰", "no_area")
    r = http_get(URL, error=SwicError, timeout=LIST_TIMEOUT, retries=2)
    try:
        doc = r.json()
    except ValueError as e:
        raise SwicError("SWIC 清單不是 JSON", "bad_json") from e
    items = doc.get("items") if isinstance(doc, dict) else None
    if not isinstance(items, list):
        raise SwicError("SWIC 清單沒有 items", "bad_format")
    used = {s for a in mine for s in a.warning_sources} & SOURCES
    mids = {m for m, s in MIDS.items() if s in used}
    ours = [i for i in items if isinstance(i, dict) and str(i.get("mid") or "") in mids]
    cities, issuers = cn_prefixes(mine)
    urls: dict[str, str] = {}  # url → source（同一個 URL 一報只抓一次）
    for item in ours:
        if _wanted(item, cities, issuers, now):
            urls.setdefault(_url(item), MIDS[str(item["mid"])])
    ctx = budget.context()

    def job(url: str) -> tuple[str, bytes | None, str | None]:
        budget.attach(ctx)
        try:
            return url, _fetch_cap(url), None
        except SwicError as e:
            return url, None, e.code

    caps: dict[str, str] = {}
    errors: dict[str, str] = {}
    alerts: list[SwicAlert] = []
    with ThreadPoolExecutor(WORKERS, thread_name_prefix="swic") as ex:
        results = list(ex.map(job, urls))
    for url, content, err in results:
        if content is None:
            errors[url] = err or "error"
            continue
        caps[url] = content.decode("utf-8", errors="replace")
        try:
            alert = parse_cap(content, urls[url], now, url)
        except SwicError as e:
            errors[url] = e.code
            continue
        if alert is not None:
            alerts.append(alert)
    raw = {
        "wmoAll": {
            "itemCount": doc.get("itemCount"),
            "lastUpdated": doc.get("lastUpdated"),
            "items": ours,
        },
        "caps": caps,
        "capErrors": errors,
    }
    return SwicData(alerts, raw, len(urls), errors)
