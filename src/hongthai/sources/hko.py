"""香港天文台開放數據（data.gov.hk）：天氣警告摘要裡的熱帶氣旋警告信號。

`https://data.weather.gov.hk/weatherAPI/opendata/weather.php?dataType=warnsum&lang=tc|en|sc`

依天文台 Open Data API 文件（warnsum）：最上層是 `{警告代碼: {...}}`，熱帶氣旋信號的鍵是
`WTCSGNL`，`code` 是 `TC1`、`TC3`、`TC8NE`／`TC8SE`／`TC8NW`／`TC8SW`、`TC9`、`TC10`
（或 `CANCEL`），`type` 是信號名稱（例如 `Strong Wind Signal No. 3`），`actionCode` 有
`ISSUE`、`CANCEL` 等；沒有任何警告時回 `{}`。繁中的文字拿來當 zh-TW 與 zh-HK。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..timeutil import iso, parse_time
from . import SourceError, http_get

URL = "https://data.weather.gov.hk/weatherAPI/opendata/weather.php"
LANGS = {"tc": ("zh-TW", "zh-HK"), "en": ("en",), "sc": ("zh-CN",)}


class HkoError(SourceError):
    pass


@dataclass
class HkoSignal:
    code: str
    level: str
    text: dict[str, str]
    issued_at: str | None


@dataclass
class HkoData:
    signal: HkoSignal | None
    raw: dict[str, object]


def signal_level(code: str) -> str | None:
    """TC8 以上（8 號四個方向、9、10）高，3 號中，1 號低。"""
    c = code.upper()
    if c.startswith("TC8") or c in ("TC9", "TC10"):
        return "high"
    if c == "TC3":
        return "medium"
    if c == "TC1":
        return "low"
    return None


def parse_signal(by_lang: dict[str, dict]) -> HkoSignal | None:
    """`by_lang` 是 `{"tc": warnsum, "en": warnsum, "sc": warnsum}`；沒有生效中的信號回 None。"""
    base = (by_lang.get("en") or by_lang.get("tc") or {}).get("WTCSGNL")
    if not base:
        return None
    code = (base.get("code") or "").upper()
    if (base.get("actionCode") or "").upper() == "CANCEL" or code == "CANCEL":
        return None
    level = signal_level(code)
    if level is None:
        return None
    text: dict[str, str] = {}
    for lang, keys in LANGS.items():
        w = (by_lang.get(lang) or {}).get("WTCSGNL") or {}
        label = w.get("type") or w.get("name") or code
        for k in keys:
            text[k] = label
    return HkoSignal(code, level, text, iso(parse_time(base.get("issueTime"))))


def fetch() -> HkoData:
    by_lang: dict[str, dict] = {}
    for lang in LANGS:
        r = http_get(URL, params={"dataType": "warnsum", "lang": lang}, error=HkoError)
        try:
            data = r.json()
        except ValueError as e:
            raise HkoError(f"天文台回傳不是 JSON（{lang}）", "bad_json") from e
        if not isinstance(data, dict):
            raise HkoError("天文台回傳格式不對", "bad_format")
        by_lang[lang] = data
    return HkoData(parse_signal(by_lang), by_lang)
