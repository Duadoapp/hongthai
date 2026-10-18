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
_NORTH_LAND = re.compile(r"北部(?!海面)")


class CwaError(SourceError):
    pass


@dataclass
class CwaWarning:
    kind: str  # typhoon_land／typhoon_sea
    level: str
    in_zone: bool  # 桃園在（陸上）警戒區
    text: dict[str, str]
    detail: str  # 原文的警戒區域及事項（只有繁中）
    issued_at: str | None


@dataclass
class CwaData:
    warnings: list[CwaWarning]
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


def taoyuan_in_zone(info: dict) -> bool:
    """陸上警戒區含桃園。

    陸上的 areaDesc 有「桃園」，或警戒區文字有「桃園」或「北部」（不算「北部海面」）。
    """
    for a in info.get("area") or []:
        desc = a.get("areaDesc", "") if isinstance(a, dict) else ""
        if "桃園" in desc and not _SEA_AREA.search(desc):
            return True
    zone = _sections(info).get("警戒區域及事項", "")
    return "桃園" in zone or bool(_NORTH_LAND.search(zone))


def _text(land: bool, in_zone: bool, zh_name: str, en_name: str) -> dict[str, str]:
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
            t["zh-TW"] += "，桃園在警戒區"
            t["zh-HK"] += "，桃園在警戒區"
            t["zh-CN"] += "，桃园在警戒区"
            t["en"] += "; Taoyuan is in the warning area"
        return t
    return {
        "zh-TW": f"中央氣象署海上颱風警報{zh}",
        "zh-HK": f"中央氣象署海上颱風警報{zh}",
        "zh-CN": f"中央气象署海上台风警报{cn}",
        "en": f"CWA sea typhoon warning{en}",
    }


def parse_warnings(data: dict, now: datetime) -> list[CwaWarning]:
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
        land = headline == HEADLINE_LAND
        in_zone = land and taoyuan_in_zone(info)
        zh_name, en_name = _typhoon_names(info)
        out.append(
            CwaWarning(
                kind="typhoon_land" if land else "typhoon_sea",
                level="high" if in_zone else "medium",
                in_zone=in_zone,
                text=_text(land, in_zone, zh_name, en_name),
                detail=_sections(info).get("警戒區域及事項", ""),
                issued_at=iso(parse_time(info.get("effective") or info.get("onset"))),
            )
        )
    return out


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
    return CwaData(parse_warnings(data, now), data)
