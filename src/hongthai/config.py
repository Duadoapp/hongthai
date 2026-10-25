"""讀 `airports.json`、`confirmed.json` 與 `events.json`。

`airports.json`（H9 起）是 `{"regions": [...], "airports": [...]}`：`regions` 是地區（顯示順序），
`airports` 照地區順序排、地區內照顯示順序。讀的時候檢查：ICAO 唯一、地區 id 唯一、每個機場的
`region` 在 `regions` 裡、`airports` 依 `regions` 的順序分段（同一地區的機場連在一起）、`tz` 是
合法的 IANA 時區、跑道方位在 0–360、看 NWS 警報（`warningSources` 有 `nws`，HD3）的機場有合法的
`nwsZone`（例如 `GUZ001`）、看 JMA 警報（`warningSources` 有 `jma`，HD9）的機場有合法的 `jmaArea`
（office 6 碼、class20 7 碼、有日文名）。不對就丟 `ValueError`。
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .timeutil import parse_time


@dataclass(frozen=True)
class Thresholds:
    """等級門檻，風速一律用節（HD2，2026-10-19）。依據寫在 `assess.py` 開頭。"""

    model_medium_gust_kt: float = 37
    model_high_gust_kt: float = 48
    taf_medium_gust_kt: float = 37
    taf_high_gust_kt: float = 48
    taf_high_wind_kt: float = 35
    crosswind_medium_kt: float = 27
    crosswind_high_kt: float = 33
    ec_p49_high: float = 0.3  # 系集陣風 ≥ 25 m/s（≈ 48.6 節）的機率
    # 第五階段天氣種類（HD8，2026-10-19 定案；先上線、累積一個月紀錄再調）。
    # 能見度公尺、雲底呎、雨量毫米
    taf_rain_medium_vis_m: float = 1600  # TS 且能見度 ≤ 這個 → 中
    taf_snow_medium_vis_m: float = 1600  # SN（不是 -SN／+SN）且能見度 ≤ 這個 → 中
    fog_medium_vis_m: float = 1000  # 能見度 < 這個 → 中（官方與 GFS 同一組）
    fog_high_vis_m: float = 400  # 能見度 < 這個 → 高；只用在官方層，模式層的霧封頂在中（HD10）
    fog_medium_ceiling_ft: float = 200  # 雲底 ≤ 這個 → 中
    fog_high_ceiling_ft: float = 100  # 雲底 ≤ 這個 → 高；只用在官方層，模式層的霧封頂在中（HD10）
    model_rain_medium_mm6h: float = 30
    model_rain_high_mm6h: float = 60
    ec_p24h_rain50_medium: float = 0.3  # 系集 24 小時雨量 ≥ 50 mm 的機率
    model_snow_medium_mm6h: float = 5  # 降雪（水當量）
    model_snow_high_mm6h: float = 10
    model_freezing_rain_high_mm6h: float = 1


# 多模式投票（HD14，Shawn 2026-10-19）：沒有陣風的模式用 10 米平均風 × 係數 G 估算陣風
# （標 `gustEstimated`）。HD18（2026-10-20）起 G 是每個機場自己的：最近 30 天每格「陣風÷
# 10 米平均風」的中位數（只收平均風 ≥ 10 節的格），夾在 1.2～2.0；樣本不足的順序見
# `gustfactor.py`，最後的保底是 1.4。HD19（2026-10-20 11:24）起中位數**只用 IFS** 的樣本
# （`gustfactor.G_SOURCE`），門檻 40 比的也是 IFS 的樣本數；GFS 的樣本照存，30 天後檢討
GUST_FACTOR_DEFAULT = 1.4
GUST_FACTOR_RANGE = (1.2, 2.0)
GUST_FACTOR_MIN_WIND_KT = 10
GUST_FACTOR_MIN_SAMPLES = 40
GUST_FACTOR_WINDOW_DAYS = 30


@dataclass(frozen=True)
class Model:
    """模式層投票的一個模式（HD14）。`id` 與 `name` 是 `latest.json` 的契約（頂層 `models`、
    `slots[].model.models[]`），順序就是輸出順序。

    `votes_only_high`：只參加「高」的投票（判中時不算分母），IFS 系集與 WeatherNext 2 系集用；
    `gust_estimated`：沒有陣風、用平均風 × 機場的係數估算（HD18，`gustfactor.py`）；
    `voting`：`False` 是旁觀模式（HD16）——照樣抓、照樣寫進 `models[]` 與路徑檔，但不算進任何一類的
    分母、不投票（`vote.total` 不含它），頂層 `models[].voting` 讓網頁標「旁觀，不投票」；
    `three_hourly`：0–72 小時有 3 小時（或更細）的風（HD35，機場頁的 3 小時格各自算）；`False` 的
    模式在 3 小時格用包住它的 6 小時格的值、標 `sixHourly`（`assess.merge_3h`）；
    `ai`：`False` 的不放進給 AI 短評的文字（HD33b：三個旁觀模式不給，改 AI 提示要另外決定）。"""

    id: str
    name: dict[str, str]
    votes_only_high: bool = False
    gust_estimated: bool = False
    voting: bool = True
    three_hourly: bool = False
    ai: bool = True


# HD15：Google WeatherNext 3（`sources/wn3.py`）的兩個開關，環境變數可以覆寫（`build.yml` 不設就是
# 這裡的值）。2026-10-20 讀完 GDM 即時資料條款的結論（README「資料來源與授權」）：即時（有效時間在
# 1 小時內或未來）的數字算「未修改的即時資料」，不能公開放在網頁、`latest.json` 與公開的 `data`
# 分支，而且條款把日本列為限制國家——所以預設 `report-only`：
# - `report-only`：`latest.json` 完全沒有 WN3（頂層 `models`、每格 `models[]`、`runs` 都沒有）；
#   只在事件期間抓「最後一個有效時間已經過了 1 小時」的那一報（起報 ≤ 現在 − 121 小時，資料是
#   CC BY 4.0），寫 `history/events/<id>/wn3/` 與路徑檔，給颱風過後的報告比對
# - `observe`：每報抓最新一報，進 `models[]` 與路徑檔（Google 書面同意公開顯示之後才切）；
#   投不投票看 `WN3_VOTING`
WN3_MODES = ("observe", "report-only")
WN3_MODE_DEFAULT = "report-only"
# 旁觀（`False`）：29W 驗證期凍結（2026-10-22 12:00 起）不改投票，解凍後才改 True
WN3_VOTING_DEFAULT = False


def wn3_mode(env: dict[str, str] | None = None) -> str:
    """`WN3_MODE` 環境變數（`observe`／`report-only`），沒設或不認得用 `WN3_MODE_DEFAULT`。"""
    v = (os.environ if env is None else env).get("WN3_MODE", "").strip()
    return v if v in WN3_MODES else WN3_MODE_DEFAULT


def wn3_voting(env: dict[str, str] | None = None) -> bool:
    """`WN3_VOTING=1`（或 `0`）覆寫 `WN3_VOTING_DEFAULT`。"""
    v = (os.environ if env is None else env).get("WN3_VOTING", "").strip()
    return WN3_VOTING_DEFAULT if v not in ("0", "1") else v == "1"


WN3_MODEL = Model(
    "wn3",
    {
        "zh-TW": "Google WeatherNext 3",
        "zh-HK": "Google WeatherNext 3",
        "zh-CN": "Google WeatherNext 3",
        "en": "Google WeatherNext 3",
    },
    gust_estimated=True,
    voting=wn3_voting(),
)

# 之後加模式只改這裡＋一個來源檔（HD15 `wn3` 只在 `observe` 模式才在這裡，見上面）
MODELS: tuple[Model, ...] = (
    Model(
        "ifs",
        {
            "zh-TW": "歐洲中期預報中心 IFS",
            "zh-HK": "歐洲中期預報中心 IFS",
            "zh-CN": "欧洲中期预报中心 IFS",
            "en": "ECMWF IFS",
        },
        three_hourly=True,  # HD35：HRES 陣風 0–144 小時每 3 小時一筆（`sources/ecmwf.py`）
    ),
    Model(
        "gfs",
        {"zh-TW": "美國 GFS", "zh-HK": "美國 GFS", "zh-CN": "美国 GFS", "en": "NOAA GFS"},
    ),
    Model(
        "ifs-ens",
        {
            "zh-TW": "歐洲系集",
            "zh-HK": "歐洲系集",
            "zh-CN": "欧洲系集",
            "en": "ECMWF ensemble",
        },
        votes_only_high=True,
    ),
    Model(
        "aifs",
        {
            "zh-TW": "歐洲 AI 模式 AIFS",
            "zh-HK": "歐洲 AI 模式 AIFS",
            "zh-CN": "欧洲 AI 模式 AIFS",
            "en": "ECMWF AIFS",
        },
        gust_estimated=True,
    ),
    Model(
        "aigfs",
        {
            "zh-TW": "美國 AI 模式 AIGFS",
            "zh-HK": "美國 AI 模式 AIGFS",
            "zh-CN": "美国 AI 模式 AIGFS",
            "en": "NOAA AIGFS",
        },
        gust_estimated=True,
    ),
    # HD16：Open-Meteo（`sources/openmeteo.py`）。JMA GSM 在 Open-Meteo 沒有陣風（2026-10-20 實抓
    # `wind_gusts_10m` 全是 null），估算；ICON 有陣風
    Model(
        "icon",
        {"zh-TW": "德國 ICON", "zh-HK": "德國 ICON", "zh-CN": "德国 ICON", "en": "DWD ICON"},
        three_hourly=True,  # HD35：Open-Meteo 逐時，ICON global 0–78 小時原生 1 小時
    ),
    Model(
        "jma",
        {"zh-TW": "日本 GSM", "zh-HK": "日本 GSM", "zh-CN": "日本 GSM", "en": "JMA GSM"},
        gust_estimated=True,
        # HD35：Open-Meteo 雖然逐時，雨量是每 6 小時一個值平均攤到 6 個小時、風是內插出來的
        # （2026-10-24 13Z 那報實看），當 6 小時資料（`three_hourly` 不設）
    ),
    Model(
        "wn2-ens",
        {
            "zh-TW": "Google WeatherNext 2 系集",
            "zh-HK": "Google WeatherNext 2 系集",
            "zh-CN": "Google WeatherNext 2 系集",
            "en": "Google WeatherNext 2 ensemble",
        },
        votes_only_high=True,
        gust_estimated=True,
    ),
    # HD33b：Open-Meteo 的三個旁觀模式（不投票、不給 AI），用 29W 回補（HD33a）比過準確度後再
    # 決定投票或加權，不照解析度加權。三個都有陣風（2026-10-25 00:08Z 51 個機場實抓），CMA 還有
    # 能見度（照存，旁觀不判霧）。UKMO 是 CC BY-SA 4.0（ShareAlike），不進 `latest.json`，只在
    # HD33a 的報告比對
    Model(
        "gem",
        {"zh-TW": "加拿大模式", "zh-HK": "加拿大模式", "zh-CN": "加拿大模式", "en": "Canada GEM"},
        voting=False,
        ai=False,
        three_hourly=True,  # HD35：Open-Meteo 逐時（GEM、CMA 原生 3 小時，ARPEGE 前段 1 小時）
    ),
    Model(
        "arpege",
        {
            "zh-TW": "法國模式",
            "zh-HK": "法國模式",
            "zh-CN": "法国模式",
            "en": "Météo-France ARPEGE",
        },
        voting=False,
        ai=False,
        three_hourly=True,  # HD35：Open-Meteo 逐時（GEM、CMA 原生 3 小時，ARPEGE 前段 1 小時）
    ),
    Model(
        "cma",
        {"zh-TW": "中國模式", "zh-HK": "中國模式", "zh-CN": "中国模式", "en": "CMA GRAPES"},
        voting=False,
        ai=False,
        three_hourly=True,  # HD35：Open-Meteo 逐時（GEM、CMA 原生 3 小時，ARPEGE 前段 1 小時）
    ),
    *((WN3_MODEL,) if wn3_mode() == "observe" else ()),
)


@dataclass(frozen=True)
class Runway:
    """一條跑道（實體跑道，同方位的平行跑道記一組）；`headings` 是兩個方向的方位（度，真北）。"""

    id: str
    headings: tuple[float, ...]


@dataclass(frozen=True)
class Region:
    """地區（H9）：`id` 是 `latest.json` 的契約（和 Duado spec 第 16 節一致），`name` 四語。"""

    id: str
    name: dict[str, str]


@dataclass(frozen=True)
class JmaArea:
    """機場在 JMA 防災 JSON 的區域（`airports.json` 的 `jmaArea`，HD9）：`office` 是都道府縣氣象台的
    代碼（警報 JSON 一個 office 一個檔）、`class20` 是機場所在的市町村代碼；`name`／`en_name` 是
    `area.json` 那個市町村的日文名與 `enName`（例如 `千歳市`／`Chitose City`），警報文字用。"""

    office: str
    class20: str
    name: str
    en_name: str


@dataclass(frozen=True)
class Airport:
    icao: str
    iata: str
    tz: str
    name: dict[str, str]
    lat: float
    lon: float
    warning_sources: tuple[str, ...]
    thresholds: Thresholds
    runways: tuple[Runway, ...] = ()
    cwa_areas: tuple[str, ...] = ()  # 氣象署警戒區關鍵字（`airports.json` 的 `cwaAreas`）
    region: str = ""  # 地區 id（`Region.id`）
    nws_zone: str = ""  # NWS 的 zone（`airports.json` 的 `nwsZone`，HD3），例如關島 GUZ001
    # 氣象署局屬站站號（`airports.json` 的 `cwaStation`，HD13）：AviationWeather 沒有 METAR 時
    # 用這站的觀測（金門 467110、馬祖 467990）
    cwa_station: str | None = None
    jma_area: JmaArea | None = None  # HD9：JMA 警報的區域（`airports.json` 的 `jmaArea`）
    # HD29（SWIC）：中國氣象局預警對機場用的縣級代碼（GB/T 2260 前 6 碼，`cmaAreas`）、
    # PAGASA 警報用的 PSGC 9 碼（`psgcAreas`）；韓國用機場座標對 CAP 的多邊形，不用另外設
    cma_areas: tuple[str, ...] = ()
    psgc_areas: tuple[str, ...] = ()


@dataclass(frozen=True)
class ConfirmedPeriod:
    airport: str
    start: datetime
    end: datetime
    note: dict[str, str]


@dataclass(frozen=True)
class EventSeed:
    """找颱風中心的備用起點（HD21，`events.json` 的 `seed`）：`at`（UTC）時的位置。"""

    lat: float
    lon: float
    at: datetime


@dataclass(frozen=True)
class Event:
    """要完整保存、之後拿來驗證的天氣事件（HD20，`events.json`，第一筆是颱風 29W）。

    `start`／`end` 是**台灣日期**（含兩端）；`jma_tc_id` 是 JMA bosai 的颱風代號（`TC2636` 這種，
    不是颱風號數）、`jtwc_id` 是 JTWC 的檔名代號（`wp2926`）；沒有就不抓那個來源。`seed` 是路徑
    抽取找中心的備用起點（HD21，`tracks.find_seed`），沒有現報時才用。"""

    id: str
    name: str
    start: date
    end: date
    airports: tuple[str, ...]
    jma_tc_id: str | None = None
    jtwc_id: str | None = None
    seed: EventSeed | None = None


_EVENT_ID = re.compile(r"^[A-Za-z0-9_-]+$")
_ICAO = re.compile(r"^[A-Z]{4}$")
_NWS_ZONE = re.compile(r"^[A-Z]{2}Z\d{3}$")
_JMA_OFFICE = re.compile(r"^\d{6}$")
_JMA_CLASS20 = re.compile(r"^\d{7}$")
_CMA_AREA = re.compile(r"^\d{6}$")
_PSGC_AREA = re.compile(r"^\d{9}$")

_THRESHOLD_KEYS = {
    "modelMediumGustKt": "model_medium_gust_kt",
    "modelHighGustKt": "model_high_gust_kt",
    "tafMediumGustKt": "taf_medium_gust_kt",
    "tafHighGustKt": "taf_high_gust_kt",
    "tafHighWindKt": "taf_high_wind_kt",
    "crosswindMediumKt": "crosswind_medium_kt",
    "crosswindHighKt": "crosswind_high_kt",
    "ecP49High": "ec_p49_high",
    "tafRainMediumVisM": "taf_rain_medium_vis_m",
    "tafSnowMediumVisM": "taf_snow_medium_vis_m",
    "fogMediumVisM": "fog_medium_vis_m",
    "fogHighVisM": "fog_high_vis_m",
    "fogMediumCeilingFt": "fog_medium_ceiling_ft",
    "fogHighCeilingFt": "fog_high_ceiling_ft",
    "modelRainMediumMm6h": "model_rain_medium_mm6h",
    "modelRainHighMm6h": "model_rain_high_mm6h",
    "ecP24hRain50Medium": "ec_p24h_rain50_medium",
    "modelSnowMediumMm6h": "model_snow_medium_mm6h",
    "modelSnowHighMm6h": "model_snow_high_mm6h",
    "modelFreezingRainHighMm6h": "model_freezing_rain_high_mm6h",
}


def _thresholds(icao: str, raw: dict) -> Thresholds:
    """`airports.json` 的 `thresholds`；HD2 以前的 m/s 鍵（`modelHighGustMs` 等）不再接受。"""
    unknown = sorted(set(raw) - set(_THRESHOLD_KEYS))
    if unknown:
        raise ValueError(f"airports.json {icao} 的 thresholds 有不認得的鍵：{', '.join(unknown)}")
    return Thresholds(**{_THRESHOLD_KEYS[k]: v for k, v in raw.items()})


def _raw(path: str | Path) -> dict:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not {"regions", "airports"} <= set(raw):
        raise ValueError('airports.json 要是 {"regions": [...], "airports": [...]}')
    return raw


def _regions(raw: dict) -> list[Region]:
    return [Region(r["id"], dict(r["name"])) for r in raw["regions"]]


def load_regions(path: str | Path) -> list[Region]:
    return _regions(_raw(path))


def _jma_area(raw: dict | None) -> JmaArea | None:
    if not raw:
        return None
    return JmaArea(
        office=str(raw.get("office", "")),
        class20=str(raw.get("class20", "")),
        name=str(raw.get("name", "")),
        en_name=str(raw.get("enName", "")),
    )


def load_airports(path: str | Path) -> list[Airport]:
    raw = _raw(path)
    airports = []
    for a in raw["airports"]:
        airports.append(
            Airport(
                icao=a["icao"],
                iata=a["iata"],
                tz=a["tz"],
                name=dict(a["name"]),
                lat=float(a["lat"]),
                lon=float(a["lon"]),
                warning_sources=tuple(a.get("warningSources", [])),
                thresholds=_thresholds(a["icao"], a.get("thresholds", {})),
                runways=tuple(
                    Runway(r["id"], tuple(float(h) for h in r["headings"]))
                    for r in a.get("runways", [])
                ),
                cwa_areas=tuple(a.get("cwaAreas", [])),
                region=a["region"],
                nws_zone=a.get("nwsZone", ""),
                cwa_station=a.get("cwaStation") or None,
                jma_area=_jma_area(a.get("jmaArea")),
                cma_areas=tuple(str(c) for c in a.get("cmaAreas", [])),
                psgc_areas=tuple(str(c) for c in a.get("psgcAreas", [])),
            )
        )
    _check(_regions(raw), airports)
    return airports


def _check(regions: list[Region], airports: list[Airport]) -> None:
    ids = [r.id for r in regions]
    if len(set(ids)) != len(ids):
        raise ValueError(f"airports.json 的地區 id 重複：{ids}")
    icaos = [a.icao for a in airports]
    dup = sorted({i for i in icaos if icaos.count(i) > 1})
    if dup:
        raise ValueError(f"airports.json 的 ICAO 重複：{', '.join(dup)}")
    for a in airports:
        if a.region not in ids:
            raise ValueError(f"airports.json {a.icao} 的 region {a.region!r} 不在 regions 裡")
        try:
            ZoneInfo(a.tz)
        except (ZoneInfoNotFoundError, ValueError) as e:
            raise ValueError(f"airports.json {a.icao} 的 tz {a.tz!r} 不是 IANA 時區") from e
        for r in a.runways:
            if not r.headings or not all(0 <= h <= 360 for h in r.headings):
                raise ValueError(
                    f"airports.json {a.icao} 跑道 {r.id} 的方位不在 0–360：{r.headings}"
                )
        if "nws" in a.warning_sources and not _NWS_ZONE.match(a.nws_zone):
            raise ValueError(
                f"airports.json {a.icao} 看 NWS 警報但 nwsZone {a.nws_zone!r} 不是 zone 代碼"
                "（例如 GUZ001）"
            )
        if "jma" in a.warning_sources:
            j = a.jma_area
            if (
                j is None
                or not _JMA_OFFICE.match(j.office)
                or not _JMA_CLASS20.match(j.class20)
                or not j.name
            ):
                raise ValueError(
                    f"airports.json {a.icao} 看 JMA 警報但 jmaArea {j!r} 不對"
                    '（例如 {"office": "016000", "class20": "0122400", "name": "千歳市"}）'
                )
        if "cma" in a.warning_sources and (
            not a.cma_areas or not all(_CMA_AREA.match(c) for c in a.cma_areas)
        ):
            raise ValueError(
                f"airports.json {a.icao} 看中國氣象局預警但 cmaAreas {list(a.cma_areas)} 不對"
                '（縣級 6 碼，例如 ["330303"]）'
            )
        if "pagasa" in a.warning_sources and (
            not a.psgc_areas or not all(_PSGC_AREA.match(c) for c in a.psgc_areas)
        ):
            raise ValueError(
                f"airports.json {a.icao} 看 PAGASA 警報但 psgcAreas {list(a.psgc_areas)} 不對"
                '（PSGC 9 碼，例如 ["137600000"]）'
            )
    # 照地區順序分段：機場的地區順序不能往回跳
    order = [ids.index(a.region) for a in airports]
    if order != sorted(order):
        raise ValueError("airports.json 的 airports 要照 regions 的順序排（同一地區連在一起）")


def load_confirmed(path: str | Path) -> list[ConfirmedPeriod]:
    """人工填的已確認停飛時段。格式：

    [{"airport": "VHHH", "from": "2026-10-20T00:00:00Z", "to": "2026-10-20T12:00:00Z",
      "note": {"zh-TW": "…", "en": "…"}}]
    """
    p = Path(path)
    if not p.exists():
        return []
    raw = json.loads(p.read_text(encoding="utf-8"))
    out = []
    for c in raw:
        start, end = parse_time(c["from"]), parse_time(c["to"])
        if start is None or end is None or end <= start:
            raise ValueError(f"confirmed.json 時段不正確：{c}")
        out.append(ConfirmedPeriod(c["airport"], start, end, dict(c.get("note", {}))))
    return out


def _event_seed(raw: object) -> EventSeed | None:
    """`seed`（可以沒有）：`{"lat", "lon", "at"}`，`at` 是 ISO 時間。格式不對丟 `ValueError`。"""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError(f"events.json 的 seed 要是物件：{raw!r}")
    at = parse_time(str(raw["at"]))
    if at is None:
        raise ValueError(f"events.json 的 seed 沒有 at：{raw!r}")
    return EventSeed(float(raw["lat"]), float(raw["lon"]), at)


def load_events(path: str | Path) -> list[Event]:
    """`events.json`（HD20）；檔案不存在回空的。格式：

    {"events": [{"id": "29W", "name": "…", "from": "2026-10-19", "to": "2026-10-28",
      "airports": ["RCTP", …], "jma": {"tcId": "TC2636"}, "jtwc": {"id": "wp2926"},
      "seed": {"lat": 16.0, "lon": 135.6, "at": "2026-10-20T00:00Z"}}]}

    `id` 會當目錄名（`history/events/<id>/`），只能有英數、`-`、`_`；`id` 不能重複、`from` ≤ `to`、
    機場是四個大寫字母。不對就丟 `ValueError`。"""
    p = Path(path)
    if not p.exists():
        return []
    raw = json.loads(p.read_text(encoding="utf-8"))
    out = []
    for e in raw.get("events", []) if isinstance(raw, dict) else []:
        start, end = date.fromisoformat(e["from"]), date.fromisoformat(e["to"])
        ev = Event(
            id=e["id"],
            name=e.get("name", ""),
            start=start,
            end=end,
            airports=tuple(e.get("airports", [])),
            jma_tc_id=(e.get("jma") or {}).get("tcId") or None,
            jtwc_id=(e.get("jtwc") or {}).get("id") or None,
            seed=_event_seed(e.get("seed")),
        )
        if not _EVENT_ID.match(ev.id):
            raise ValueError(f"events.json 的 id {ev.id!r} 只能有英數、-、_")
        if end < start:
            raise ValueError(f"events.json {ev.id} 的 to 早於 from")
        bad = [i for i in ev.airports if not _ICAO.match(i)]
        if bad:
            raise ValueError(f"events.json {ev.id} 的機場不是 ICAO：{bad}")
        out.append(ev)
    ids = [e.id for e in out]
    if len(set(ids)) != len(ids):
        raise ValueError(f"events.json 的 id 重複：{ids}")
    return out
