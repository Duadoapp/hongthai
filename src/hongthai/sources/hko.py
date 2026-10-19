"""香港天文台開放數據（data.gov.hk）：天氣警告摘要裡的熱帶氣旋警告信號；HD8 起加暴雨
警告信號與雷暴警告。

`https://data.weather.gov.hk/weatherAPI/opendata/weather.php?dataType=warnsum&lang=tc|en|sc`

依天文台 Open Data API 文件（warnsum）：最上層是 `{警告代碼: {...}}`，熱帶氣旋信號的鍵是
`WTCSGNL`，`code` 是 `TC1`、`TC3`、`TC8NE`／`TC8SE`／`TC8NW`／`TC8SW`、`TC9`、`TC10`
（或 `CANCEL`），`type` 是信號名稱（例如 `Strong Wind Signal No. 3`），`actionCode` 有
`ISSUE`、`CANCEL` 等；沒有任何警告時回 `{}`。繁中的文字拿來當 zh-TW 與 zh-HK。

暴雨與雷暴（HD8，同一次請求，不多打）：暴雨警告信號的鍵是 `WRAIN`，`code` 是
`WRAINA`（黃）、`WRAINR`（紅）、`WRAINB`（黑），`type` 是顏色（「黑色」／`Black`）；雷暴警告的
鍵是 `WTS`（`code` `WTS`）。等級（Shawn 2026-10-19 定案）：黑雨 `rainstorm_black` 中；紅雨
`rainstorm_red`、雷暴 `thunderstorm` 低、**只列出**（低的警報不會自己撐起官方層，見
`assess.py`）；黃雨不在定案的種類裡，不產生警報。文字是「顏色＋名稱」（「黑色暴雨警告信號」
「Black Rainstorm Warning Signal」），沒有就用 `WARNING_TEXT` 的固定字。
"""

from __future__ import annotations

from dataclasses import dataclass, field

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
class HkoWarning:
    """暴雨警告信號或雷暴警告（HD8）。"""

    kind: str  # rainstorm_black／rainstorm_red／thunderstorm
    code: str
    level: str
    text: dict[str, str]
    issued_at: str | None


@dataclass
class HkoData:
    signal: HkoSignal | None
    raw: dict[str, object]
    warnings: list[HkoWarning] = field(default_factory=list)


# warnsum 的鍵 → {code: (kind, level)}
WARNING_CODES = {
    "WRAIN": {"WRAINB": ("rainstorm_black", "medium"), "WRAINR": ("rainstorm_red", "low")},
    "WTS": {"WTS": ("thunderstorm", "low")},
}
WARNING_TEXT = {
    "WRAINB": {
        "zh-TW": "黑色暴雨警告信號",
        "zh-HK": "黑色暴雨警告信號",
        "zh-CN": "黑色暴雨警告信号",
        "en": "Black Rainstorm Warning Signal",
    },
    "WRAINR": {
        "zh-TW": "紅色暴雨警告信號",
        "zh-HK": "紅色暴雨警告信號",
        "zh-CN": "红色暴雨警告信号",
        "en": "Red Rainstorm Warning Signal",
    },
    "WTS": {
        "zh-TW": "雷暴警告",
        "zh-HK": "雷暴警告",
        "zh-CN": "雷暴警告",
        "en": "Thunderstorm Warning",
    },
}


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


def parse_warnings(by_lang: dict[str, dict]) -> list[HkoWarning]:
    """黑雨、紅雨、雷暴警告（`WARNING_CODES`）；取消的、黃雨、看不懂的代碼不算。"""
    out = []
    for key, codes in WARNING_CODES.items():
        base = (by_lang.get("en") or by_lang.get("tc") or {}).get(key)
        if not isinstance(base, dict):
            continue
        code = (base.get("code") or "").upper()
        if (base.get("actionCode") or "").upper() == "CANCEL" or code not in codes:
            continue
        kind, level = codes[code]
        text = dict(WARNING_TEXT[code])
        for lang, keys in LANGS.items():
            w = (by_lang.get(lang) or {}).get(key) or {}
            name = w.get("name") or ""
            color = w.get("type") or ""
            if name:
                label = f"{color} {name}" if lang == "en" and color else f"{color}{name}"
                for k in keys:
                    text[k] = label
        out.append(HkoWarning(kind, code, level, text, iso(parse_time(base.get("issueTime")))))
    return out


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
    return HkoData(parse_signal(by_lang), by_lang, parse_warnings(by_lang))
