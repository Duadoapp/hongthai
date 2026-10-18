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
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

import requests

from ..timeutil import iso, parse_time
from . import NonStrictTLSAdapter, SourceError, http_get

URL = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/W-C0034-001"
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

    kind: str  # typhoon_land／typhoon_sea
    level: str
    in_zone: bool  # 機場在（陸上）警戒區
    text: dict[str, str]
    detail: str  # 原文的警戒區域及事項（只有繁中）
    issued_at: str | None


@dataclass
class CwaData:
    bulletins: list[CwaBulletin]
    raw: object


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


def fetch(api_key: str | None, now: datetime) -> CwaData:
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
    return CwaData(parse_bulletins(data, now), data)
