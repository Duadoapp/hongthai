"""美國國家氣象局（NWS）api.weather.gov 的警報：關島的颱風／熱帶風暴警報與守視（HD3）。

`https://api.weather.gov/alerts/active?zone=GUZ001`（美國政府公有領域、GeoJSON、不用金鑰，要帶
User-Agent）。`zone` 可以逗號分隔帶多個，一次請求。

查過的結果（2026-10-18 實測）：
- 關島：`/zones?area=GU` 有 `GUZ001`（public／fire，名稱 Guam，`cwa` 是 GUM＝NWS 關島分處 Tiyan）；
  `/points/13.485,144.7973`（PGUM）的 `forecastZone` 就是 `GUZ001`。`/alerts?zone=GUZ001` 查得到
  超強颱風 Champi（29W）期間的 `Typhoon Warning`（10-16 發布、10-18 解除，同一個 VTEC
  `PGUM.TY.W.4029`，每次更新 `messageType` 是 `Update`、解除是 `Cancel`）與 `Typhoon Watch`
- 帛琉：`/zones?area=PW` 有 `PWZ001`–`PWZ008`（PTRO 在 Airai＝`PWZ003`；`cwa` 是 `PQW`，
  `/offices/PQW` 回 404；zone 2026-04-16 才生效），但 `/alerts?area=PW` 自 2026-04-01 起一筆都沒有，
  Champi 期間也沒有；TC 本地聲明（HLS）的地點只有 `PQ2`（關島與北馬里亞納）。看不出 NWS 會在這個
  端點發帛琉的颱風警報，所以帛琉先不接（`warningSources: []`），之後看到再接

只看 `event` 是下面四種的（其他如 Wind Advisory、Flood Watch 不算）。對等級（Shawn 2026-10-19
定案）：Warning 是確定會有（Tropical Storm Warning＝36 小時內持續 34–63 節，等同天文台 8 號），
Watch 是可能會有：
- Typhoon Warning、Tropical Storm Warning → 高
- Typhoon Watch、Tropical Storm Watch → 中

`status` 不是 `Actual`（演習、測試）或 `messageType` 是 `Cancel`（解除的那一則，會在 active 裡掛到
它自己的 `expires`）的不算。同一個 zone 同一種事件有好幾則時取 `sent` 最新的。`issuedAt` 是那一則的
`sent`（NWS 每次更新都重發一則，所以是最近一次更新的時間）。

四語文字：英文用 NWS 的 `headline`，中文三語用固定句型（例如「颱風警報生效中（美國國家氣象局）」）；
`detail` 放 `parameters.NWSheadline`（例如 `TYPHOON WARNING REMAINS IN EFFECT`）。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..timeutil import iso, parse_time
from . import SourceError, http_get

URL = "https://api.weather.gov/alerts/active"

# NWS 的 event → (kind, 等級)
EVENTS = {
    "Typhoon Warning": ("typhoon_warning", "high"),
    "Tropical Storm Warning": ("ts_warning", "high"),
    "Typhoon Watch": ("typhoon_watch", "medium"),
    "Tropical Storm Watch": ("ts_watch", "medium"),
}
_NAMES = {  # kind → zh-TW、zh-HK、zh-CN
    "typhoon_warning": ("颱風警報", "颱風警告", "台风警报"),
    "ts_warning": ("熱帶風暴警報", "熱帶風暴警告", "热带风暴警报"),
    "typhoon_watch": ("颱風警戒", "颱風戒備", "台风警戒"),
    "ts_watch": ("熱帶風暴警戒", "熱帶風暴戒備", "热带风暴警戒"),
}
_LEVELS = ("low", "medium", "high")


class NwsError(SourceError):
    pass


@dataclass
class NwsAlert:
    zones: tuple[str, ...]  # 這則警報涵蓋的 zone（`geocode.UGC`）
    kind: str  # typhoon_warning／typhoon_watch／ts_warning／ts_watch
    level: str
    code: str  # NWS 的 event，例如 Typhoon Warning
    text: dict[str, str]
    issued_at: str | None
    detail: str


@dataclass
class NwsData:
    alerts: list[NwsAlert]
    raw: dict[str, object]


def text_for(kind: str, headline: str) -> dict[str, str]:
    tw, hk, cn = _NAMES[kind]
    return {
        "zh-TW": f"{tw}生效中（美國國家氣象局）",
        "zh-HK": f"{hk}生效中（美國國家氣象局）",
        "zh-CN": f"{cn}生效中（美国国家气象局）",
        "en": headline,
    }


def _zones(p: dict) -> tuple[str, ...]:
    ugc = (p.get("geocode") or {}).get("UGC") or []
    if not ugc:  # 沒有 geocode 時從 affectedZones 的網址取最後一段
        ugc = [str(z).rstrip("/").rsplit("/", 1)[-1] for z in p.get("affectedZones") or []]
    return tuple(str(z).upper() for z in ugc)


def parse_alerts(doc: dict) -> list[NwsAlert]:
    """`/alerts/active` 的回應 → 颱風／熱帶風暴的警報與守視（其他事件、解除、演習都不要）。"""
    feats = doc.get("features") if isinstance(doc, dict) else None
    if not isinstance(feats, list):
        raise NwsError("NWS 回傳沒有 features", "bad_format")
    out = []
    for f in feats:
        p = (f or {}).get("properties") if isinstance(f, dict) else None
        if not isinstance(p, dict):
            continue
        event = p.get("event") or ""
        if event not in EVENTS or p.get("status") != "Actual" or p.get("messageType") == "Cancel":
            continue
        kind, level = EVENTS[event]
        try:
            issued = iso(parse_time(p.get("sent")))
        except ValueError:
            issued = None
        headline = p.get("headline") or event
        detail = "; ".join((p.get("parameters") or {}).get("NWSheadline") or [])
        out.append(
            NwsAlert(_zones(p), kind, level, event, text_for(kind, headline), issued, detail)
        )
    return out


def for_zone(alerts: list[NwsAlert], zone: str) -> list[NwsAlert]:
    """某個 zone 生效中的警報；同一種取 `sent` 最新的，等級高的排前面。"""
    latest: dict[str, NwsAlert] = {}
    for a in alerts:
        if zone.upper() not in a.zones:
            continue
        old = latest.get(a.kind)
        if old is None or (a.issued_at or "") > (old.issued_at or ""):
            latest[a.kind] = a
    return sorted(latest.values(), key=lambda a: (-_LEVELS.index(a.level), a.kind))


def fetch(zones: list[str]) -> NwsData:
    """一次請求查所有 zone（`airports.json` 的 `nwsZone`）。沒有 zone 是設定錯了，丟 `no_zone`。"""
    zones = sorted({z.upper() for z in zones if z})
    if not zones:
        raise NwsError("沒有機場設 nwsZone，NWS 不知道要查哪裡", "no_zone")
    r = http_get(
        URL,
        params={"zone": ",".join(zones)},
        headers={"Accept": "application/geo+json"},
        error=NwsError,
    )
    try:
        doc = r.json()
    except ValueError as e:
        raise NwsError("NWS 回傳不是 JSON", "bad_json") from e
    return NwsData(parse_alerts(doc), doc)
