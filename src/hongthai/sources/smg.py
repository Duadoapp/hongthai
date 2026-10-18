"""澳門地球物理氣象局（SMG）開放資料：熱帶氣旋信號（data.gov.mo 資料集「熱帶氣旋信號」）。

`https://xml.smg.gov.mo/c_typhoon.xml`（中文）、`e_typhoon.xml`（英文）；葡文 `p_typhoon.xml` 不用。

格式（實測 2026-10-18，加上 2026 年 7–9 月三次 1／3 號風球的存檔）：
`TyphoonWarning/Custom/TropicalCyclone` 只有一個，欄位
- `Status`：0＝沒有警告、1＝現正懸掛、2＝除下、3＝沒有警告下的預報（只有 1 算生效）
- `Inforce`：目前的信號，`1`、`3`、`8NE`／`8SE`／`8SW`／`8NW`、`9`、`10`（沒有時 `0` 或 `-`；
  8 號以上的寫法取自 SMG 網站程式，還沒實際看過，所以比對時不分大小寫）；`Warncode` 同值
- `Action`：`INFORCE`／`CANCEL`／`NIL`
- `SignalChangedAt`：這個信號發出的時間；`IssuedAt`：這一則報告的時間（都是澳門時間，GMT+8）
- `InforceChange`／`IssuedAtChange`：預告要改發的信號與時間（沒有預告時是空的）
- `Name`：例如 `強烈熱帶風暴"紅霞"(2612)`；`Description`：說明文字（有換行與「(… 更新)」）

等級同天文台：8 號以上高、3 號中、1 號低。預告要改發更高的信號時取較高的（保守）。
四語文字用固定的信號名稱組（SMG 的中文叫「X號風球」），zh-CN 自己寫簡體；原文 `Description`
放在 `detail`。
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from ..timeutil import iso
from . import SourceError, http_get

URL = "https://xml.smg.gov.mo/{}_typhoon.xml"
LANGS = ("c", "e")
MACAU_TZ = timezone(timedelta(hours=8))

_NUM_ZH = {"1": "一", "3": "三", "8": "八", "9": "九", "10": "十"}
_DIR = {  # 方向：繁中、簡中、英文
    "NE": ("東北", "东北", "NE"),
    "SE": ("東南", "东南", "SE"),
    "SW": ("西南", "西南", "SW"),
    "NW": ("西北", "西北", "NW"),
}
_LEVELS = ("low", "medium", "high")
_CODE = re.compile(r"^(1|3|8(NE|SE|SW|NW)|9|10)$")


class SmgError(SourceError):
    pass


@dataclass
class SmgSignal:
    code: str  # TC1／TC3／TC8NE…／TC9／TC10（和天文台同一種寫法）
    level: str
    text: dict[str, str]
    issued_at: str | None
    detail: str  # 原文 Description（中文）


@dataclass
class SmgData:
    signal: SmgSignal | None
    raw: dict[str, str]  # {語言: XML 原文}


def normalize(inforce: str | None) -> str | None:
    """`Inforce` → `1`、`3`、`8NE`…、`9`、`10`；不是信號（`0`、`-`、`NIL`、空的）回 None。"""
    c = (inforce or "").strip().upper()
    return c if _CODE.match(c) else None


def signal_level(code: str) -> str:
    if code.startswith("8") or code in ("9", "10"):
        return "high"
    return "medium" if code == "3" else "low"


def names(code: str) -> dict[str, str]:
    """信號的四語名稱，例如 8NE → 八號東北風球／Signal No. 8 NE。"""
    num = code[:-2] if code[-2:] in _DIR else code
    tw, cn, en = _DIR.get(code[len(num) :], ("", "", ""))
    zh = _NUM_ZH[num]
    return {
        "zh-TW": f"{zh}號{tw}風球",
        "zh-HK": f"{zh}號{tw}風球",
        "zh-CN": f"{zh}号{cn}风球",
        "en": f"Tropical Cyclone Signal No. {num}" + (f" {en}" if en else ""),
    }


def _macau_time(v: str | None) -> datetime | None:
    """`2026-07-25 18:00`（澳門時間，可能帶 ` GMT+8`）→ UTC。"""
    m = re.match(r"^\s*(\d{4}-\d\d-\d\d \d\d:\d\d)", v or "")
    if not m:
        return None
    return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M").replace(tzinfo=MACAU_TZ)


def _fields(xml_text: str) -> dict[str, str]:
    try:
        root = ET.fromstring(xml_text.encode("utf-8"))
    except ET.ParseError as e:
        raise SmgError(f"SMG XML 解析失敗：{e}", "bad_xml") from e
    tc = root.find("Custom/TropicalCyclone")
    if tc is None:
        raise SmgError("SMG XML 沒有 Custom/TropicalCyclone", "bad_format")
    return {child.tag: (child.text or "").strip() for child in tc}


def parse_signal(by_lang: dict[str, str]) -> SmgSignal | None:
    """`by_lang` 是 `{"c": XML, "e": XML}`；沒有生效中的信號回 None。中文為準。"""
    f = _fields(by_lang.get("c") or by_lang["e"])
    if f.get("Status") != "1" or f.get("Action", "").upper() == "CANCEL":
        return None
    code = normalize(f.get("Inforce")) or normalize(f.get("Warncode"))
    if code is None:
        return None
    level = signal_level(code)
    prefix = {"zh-TW": "澳門", "zh-HK": "澳門", "zh-CN": "澳门", "en": "Macao "}
    text = {k: prefix[k] + v for k, v in names(code).items()}

    pending = normalize(f.get("InforceChange"))
    if pending and pending != code:
        p_names = names(pending)
        at = _macau_time(f.get("IssuedAtChange"))
        hhmm = f"{at:%m-%d %H:%M}" if at else ""
        text["zh-TW"] += f"；預告{hhmm}改發{p_names['zh-TW']}"
        text["zh-HK"] += f"；預告{hhmm}改發{p_names['zh-HK']}"
        text["zh-CN"] += f"；预告{hhmm}改发{p_names['zh-CN']}"
        text["en"] += f"; {p_names['en']} expected" + (f" at {hhmm} (Macao time)" if at else "")
        level = max(level, signal_level(pending), key=_LEVELS.index)

    issued = _macau_time(f.get("SignalChangedAt")) or _macau_time(f.get("IssuedAt"))
    return SmgSignal(f"TC{code}", level, text, iso(issued), f.get("Description", ""))


def fetch() -> SmgData:
    raw: dict[str, str] = {}
    for lang in LANGS:
        r = http_get(URL.format(lang), error=SmgError)
        r.encoding = "utf-8"
        raw[lang] = r.text
    return SmgData(parse_signal(raw), raw)
