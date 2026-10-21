"""日本氣象廳（JMA）防災 JSON 的警報：日本與沖繩機場的大雪警報（HD9）、暴風雪特別警報（HD16）、
暴風與大雨警報（HD27，只列出）。

JMA bosai 的 JSON（JMA 網頁自己用的，非正式介面但穩定、不用金鑰，日本政府公有）：
- 警報 `https://www.jma.go.jp/bosai/warning/data/r8/<office 代碼>.json`，一個都道府縣氣象台
  （`area.json` 的 `offices`）一個檔
- 區域表 `https://www.jma.go.jp/bosai/common/const/area.json`（`class20s` 是市町村），只在設定
  `airports.json` 的 `jmaArea` 時查一次，每報不抓

查過的結果（2026-10-20 實抓）：
- 舊的 `bosai/warning/data/warning/<office>.json`（`areaTypes[].areas[].warnings[]`）停在
  2026-05-28：JMA 那天換成新的防災氣象資訊（令和 8 年，危險警報等），網頁改讀 `data/r8/`。
  新格式最上層是 list，每筆是一種電文（`dataTypeCode`：VPWW55 大雨、VPWW56 土砂災害、VPWW57 高潮、
  VPWW58 風、VPWW59 波浪、VPWW61 雷・濃霧・乾燥等；雪的那種 10 月還沒出現過，所以不看
  `dataTypeCode`，每筆都找），每筆有 `reportDatetime`、`infoType`（発表／訂正／取消）與
  `warning.class10Items`／`class20Items`，每列 `{"areaCode", "kinds": [{"code", "status"}]}`
- 警報種類代碼照 JMA 警報頁的 JS（`elem`／`level` 對照表）：大雪 注意報 `12`、警報 `06`、
  特別警報 `36`；暴風雪（`wind_snow`）注意報（風雪）`13`、警報 `02`、特別警報 `32`。
  （暴風 `05`／`35`、大雨特別警報 `33`；舊制以為的「大雪特別警報 33、暴風雪警報 05」是錯的）
- `status`：発表、継続、解除、発表警報・注意報はなし（沒有 `code`）。降級時（警報→注意報）代碼是
  降級後的種類，所以只要代碼對、狀態不是解除／なし就算生效中

接四種：大雪警報 → 中、大雪特別警報 → 高、暴風雪警報 → 低（只列出）（Shawn 2026-10-19 定案）；
暴風雪特別警報 `32` → 高（HD16，Shawn 2026-10-20 19:04，和大雪特別警報同級），都算 `snow`。
注意報（大雪 12、風雪 13）不列。

HD27（Shawn 2026-10-22 01:35，颱風 29W）：暴風、大雨警報**只列出（low）、不升級**。
2026-10-22 再抓一次警報頁的 JS 對照表核對：
- 暴風（`wind`）：注意報（強風）`15`、警報 `05`、特別警報 `35`（沒有危険警報這一級）
  → 接 `05` `jma_storm`、`35` `jma_storm_emergency`，算 `wind`
- 大雨（`rain`，r8 新制分レベル２–５）：注意報 `10`（レベル２）、警報 `03`（レベル３）、
  危険警報 `43`（レベル４）、特別警報 `33`（レベル５）→ 接 `03` `jma_heavy_rain`、
  `43` `jma_heavy_rain_danger`、`33` `jma_heavy_rain_emergency`，算 `rain`。2026-10-21
  17:22Z 那報 11 個 office 的大雨電文（VPWW55）只看得到 `10`（解除）與「なし」，
  `03`／`43`／`33` 是照 JS 的表
- 注意報、波浪（`07` 警報、`16` 注意報）、高潮、洪水（氾濫）、土砂災害都不接。29W 期間沖繩的警報地圖
  紅色是波浪警報 `07`（VPWW59「高波に警戒」），這支照提示詞不接

每種電文（`dataTypeCode`）只看 `reportDatetime` 最新的那一筆（新的一報整份取代舊的；`infoType`
是取消的那筆不算），再把各種電文合起來；同一個代碼出現在好幾種電文時取最新那筆的狀態。
`issuedAt` 是那筆的 `reportDatetime`。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config import JmaArea
from ..timeutil import iso, parse_time
from . import SourceError, http_get

URL = "https://www.jma.go.jp/bosai/warning/data/r8/{office}.json"

# JMA 的警報種類代碼 → (kind, 等級)
CODES = {
    "06": ("jma_heavy_snow", "medium"),
    "36": ("jma_heavy_snow_emergency", "high"),
    "02": ("jma_snowstorm", "low"),
    "32": ("jma_snowstorm_emergency", "high"),  # HD16
    # HD27：暴風、大雨只列出
    "05": ("jma_storm", "low"),
    "35": ("jma_storm_emergency", "low"),
    "03": ("jma_heavy_rain", "low"),
    "43": ("jma_heavy_rain_danger", "low"),
    "33": ("jma_heavy_rain_emergency", "low"),
}
_NAMES = {  # kind → zh-TW／zh-HK、zh-CN、en
    "jma_heavy_snow": ("大雪警報", "大雪警报", "heavy snow warning"),
    "jma_heavy_snow_emergency": ("大雪特別警報", "大雪特别警报", "heavy snow emergency warning"),
    "jma_snowstorm": ("暴風雪警報", "暴风雪警报", "snowstorm warning"),
    "jma_snowstorm_emergency": ("暴風雪特別警報", "暴风雪特别警报", "snowstorm emergency warning"),
    "jma_storm": ("暴風警報", "暴风警报", "storm warning"),
    "jma_storm_emergency": ("暴風特別警報", "暴风特别警报", "storm emergency warning"),
    "jma_heavy_rain": ("大雨警報", "大雨警报", "heavy rain warning"),
    "jma_heavy_rain_danger": ("大雨危險警報", "大雨危险警报", "heavy rain danger warning"),
    "jma_heavy_rain_emergency": ("大雨特別警報", "大雨特别警报", "heavy rain emergency warning"),
}
INACTIVE = frozenset({"解除", "発表警報・注意報はなし"})
_EN_SUFFIXES = (" City", " Town", " Village")
_LEVELS = ("low", "medium", "high")


class JmaError(SourceError):
    pass


@dataclass
class JmaWarning:
    kind: str  # `CODES` 的 kind（大雪、暴風雪、HD27 的暴風、大雨）
    level: str
    code: str  # JMA 的警報種類代碼，例如 06
    text: dict[str, str]
    issued_at: str | None


@dataclass
class JmaData:
    warnings: dict[str, list[JmaWarning]]  # class20 → 生效中的警報
    raw: dict[str, object]  # office → 原始回應


def en_name(name: str) -> str:
    """`area.json` 的 `enName` 拿掉 City／Town／Village（`Chitose City` → `Chitose`）。"""
    for s in _EN_SUFFIXES:
        if name.endswith(s):
            return name[: -len(s)]
    return name


def text_for(kind: str, area: JmaArea) -> dict[str, str]:
    tw, cn, en = _NAMES[kind]
    return {
        "zh-TW": f"日本氣象廳{tw}（{area.name}）",
        "zh-HK": f"日本氣象廳{tw}（{area.name}）",
        "zh-CN": f"日本气象厅{cn}（{area.name}）",
        "en": f"JMA {en} ({en_name(area.en_name) or area.name})",
    }


def parse_area(doc: object, area: JmaArea) -> list[JmaWarning]:
    """一個 office 的回應 → `area.class20` 那一列生效中的警報（`CODES`），等級高的在前。"""
    if not isinstance(doc, list):
        raise JmaError(f"JMA {area.office} 回傳不是電文的 list", "bad_format")
    reports: dict[str, tuple[str, dict]] = {}  # dataTypeCode → (reportDatetime, 那一筆)
    for report in doc:
        if not isinstance(report, dict) or report.get("infoType") == "取消":
            continue
        try:
            issued = iso(parse_time(report.get("reportDatetime"))) or ""
        except ValueError:
            issued = ""
        kind = str(report.get("dataTypeCode") or "")
        if kind not in reports or issued >= reports[kind][0]:
            reports[kind] = (issued, report)
    latest: dict[str, tuple[str, str]] = {}  # code → (reportDatetime, status)
    for issued, report in reports.values():
        rows = (report.get("warning") or {}).get("class20Items") or []
        for row in rows:
            if not isinstance(row, dict) or row.get("areaCode") != area.class20:
                continue
            for k in row.get("kinds") or []:
                code = k.get("code") if isinstance(k, dict) else None
                if code not in CODES:
                    continue
                if code not in latest or issued >= latest[code][0]:
                    latest[code] = (issued, k.get("status") or "")
    out = []
    for code, (issued, status) in latest.items():
        if status in INACTIVE:
            continue
        kind, level = CODES[code]
        out.append(JmaWarning(kind, level, code, text_for(kind, area), issued or None))
    return sorted(out, key=lambda w: (-_LEVELS.index(w.level), w.kind))


def fetch(areas: list[JmaArea]) -> JmaData:
    """依 office 去重、一個 office 一個請求（`airports.json` 的 `jmaArea`）。"""
    offices = sorted({a.office for a in areas})
    if not offices:
        raise JmaError("沒有機場設 jmaArea，JMA 不知道要查哪裡", "no_area")
    raw: dict[str, object] = {}
    for office in offices:
        r = http_get(URL.format(office=office), error=JmaError)
        try:
            raw[office] = r.json()
        except ValueError as e:
            raise JmaError(f"JMA {office} 回傳不是 JSON", "bad_json") from e
    return JmaData({a.class20: parse_area(raw[a.office], a) for a in areas}, raw)
