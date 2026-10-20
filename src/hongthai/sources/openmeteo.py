"""Open-Meteo（CC BY 4.0）的三個模式：DWD ICON global、JMA GSM、Google WeatherNext 2 系集（HD16）。

授權：Open-Meteo 免費版只限非商業（HongThai、Duado 目前沒收費、沒廣告）。**一旦收費、訂閱或放廣告，
必須改買商業方案或拿掉這三個模式**；網頁與資料來源標「Open-Meteo（CC BY 4.0）・DWD ICON・JMA・
Google WeatherNext 2」。Google 對即時 WeatherNext 資料另有實驗條款，Open-Meteo 的授權來源查不到
（README「已知的保守假設」）。

兩個請求，**每個請求一次帶全部機場的座標**（`latitude=…,…&longitude=…,…`；回應是 list，
照座標順序）：
- `FORECAST_URL`：`models=icon_global,jma_gsm`，逐時 10 米風、風向、陣風、雨量、降雪、能見度、
  天氣碼；每個變數名後面接 `_icon_global`／`_jma_gsm`
- `ENSEMBLE_URL`：`models=google_weathernext2_ensemble`、`temporal_resolution=native`（6 小時一個
  時間點），**只要 `wind_speed_10m`**（WN2 只投風的高、不算側風、不投雨，提示詞列的風向、雨量
  用不到，而且會讓這個請求超過每分鐘上限，見下面），64 個成員：成員 0 是不帶後綴的
  `wind_speed_10m`，其他是 `wind_speed_10m_member01`…`63`
- 不用金鑰；`User-Agent` 是 HongThai 與 repo 網址（`sources.USER_AGENT`）；逾時 60 秒、**不重試**：
  失敗就是這一報沒有這三票（`build.py` 不沿用舊資料，見 README）。用同一個 `requests.Session`
  （兩個主機各一條連線，metadata 和資料共用）：雲端開發機 2026-10-20 連 Open-Meteo 時 TLS 建立偶爾
  逾時或被斷（4 次裡 2 次），少握手一次是一次

實測（2026-10-20 11:17Z，雲端開發機，51 個機場）：
- 預報 632,290 bytes、1.0 秒；系集（當時照提示詞抓 3 個變數）1,635,607 bytes、1.2 秒
- 單位照要的（`wind_speed_unit=kn`）；`snowfall` 是公分（Open-Meteo 文件：水當量毫米＝公分 ÷ 0.7）
- **JMA GSM 沒有陣風**（`wind_gusts_10m_jma_gsm` 全是 null，單位寫 `undefined`）→ `config.MODELS`
  的 `jma` 是 `gust_estimated`；**ICON global 也沒有能見度**（`visibility_icon_global` 全是 null，
  JMA 也沒有），所以霧的分母還是只有 GFS
- 逐時資料從當天 00Z 起 144 個小時（`forecast_days=6`），涵蓋 slot0 起 120 小時。ICON 06／18Z
  那報只到 120 小時，後面的小時 Open-Meteo 自動接前一報（00／12Z 到 180 小時）
- 系集 24 個時間點（00／06／12／18Z）

加權呼叫次數（Open-Meteo 文件 API 頁「equivalent to N calls」的公式，`weighted_calls`）：
`max(1, 變數數 × 模式數（系集是成員數）÷ 10 × max(1, 天數 ÷ 14)) × 座標數`。
免費版的上限（使用條款）：**每分鐘 600**、每小時 5,000、每日 10,000、每月 300,000。
預報 7 個變數 × 2 個模式、6 天 → 1.4 × 51 ＝ 71.4 次；系集 1 個變數 × 64 個成員 → 6.4 × 51 ＝
326.4 次；**一報 397.8**（< 每分鐘 600）、一天 4 報約 1,591 次（< 提示詞的每日 5,000，所以全部
機場都抓）。照提示詞抓系集 3 個變數的話系集一個請求就是 979.2 次，超過每分鐘 600。
`sources.openmeteo.calls` 記這一報的加權次數

起報時間：資料的回應裡沒有。Open-Meteo 有 metadata API（`META_URLS`，文件「Model Updates」頁），
`last_run_initialisation_time` 是最近一報的起報時間（Unix 秒）。兩個資料請求**之後**才問（每個
模式一個約 600 bytes 的小請求、不算呼叫次數、逾時 5 秒，最多多花 15 秒，不會把 90 秒的預算吃掉）；
問不到的那個模式 `run` 是 None，不影響資料。文件說新的一報在 `last_run_availability_time` 之後約
10 分鐘內各台伺服器才會一致，所以剛好碰到換報的那幾分鐘，`runs.*` 可能和實際用到的資料差一報
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

import requests

from ..config import Airport
from . import SourceError, http_get

log = logging.getLogger("hongthai")

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ENSEMBLE_URL = "https://ensemble-api.open-meteo.com/v1/ensemble"
# 每個模式最近一報的起報時間（`last_run_initialisation_time`）
META_URLS = {
    "icon": "https://api.open-meteo.com/data/dwd_icon/static/meta.json",
    "jma": "https://api.open-meteo.com/data/jma_gsm/static/meta.json",
    "wn2-ens": "https://ensemble-api.open-meteo.com/data/google_weathernext2_ensemble/static/meta.json",
}
# `config.MODELS` 的 id → Open-Meteo 預報 API 的模式名（變數名的後綴）
FORECAST_MODELS = {"icon": "icon_global", "jma": "jma_gsm"}
FORECAST_VARS = (
    "wind_speed_10m",
    "wind_direction_10m",
    "wind_gusts_10m",
    "precipitation",
    "snowfall",
    "visibility",
    "weather_code",
)
ENSEMBLE_MODEL = "google_weathernext2_ensemble"
ENSEMBLE_ID = "wn2-ens"
ENSEMBLE_MEMBERS = 64
# 只要風速：多一個變數一報就多 326.4 次（見開頭「加權呼叫次數」）
ENSEMBLE_VARS = ("wind_speed_10m",)
FORECAST_DAYS = 6
TIMEOUT_S = 60
META_TIMEOUT_S = 5
SNOW_CM_PER_MM = 0.7  # Open-Meteo：降雪公分 ÷ 0.7 ＝ 水當量毫米
NO_PRECIP_MM = 0.1  # 6 小時總降水小於這個 → `none`（同 AIFS）
# WMO 天氣碼（Open-Meteo 的 `weather_code`）
FREEZING_RAIN_CODES = frozenset({66, 67})
FREEZING_DRIZZLE_CODES = frozenset({56, 57})
_MEMBER = re.compile(r"^wind_speed_10m(?:_member(\d+))?$")


class OpenMeteoError(SourceError):
    pass


@dataclass
class OmHour:
    """ICON／JMA 的一個小時。`wind_kt`、`wdir`、`vis_m` 是當下的值；`gust_kt`（前一小時最大陣風）、
    `precip_mm`、`snow_mm`（降雪水當量）、`code`（天氣碼）是「前一小時」的（Open-Meteo 的定義）。"""

    valid: datetime
    wind_kt: float | None
    wdir: float | None
    gust_kt: float | None
    precip_mm: float | None
    snow_mm: float | None
    vis_m: float | None
    code: int | None


@dataclass
class EnsStep:
    """WeatherNext 2 系集的一個 6 小時整時間點：每個成員的 10 米平均風（節），成員 0 在最前面。"""

    valid: datetime
    winds: tuple[float | None, ...]


@dataclass
class OpenMeteoData:
    runs: dict[str, datetime | None]  # `config.MODELS` 的 id（icon、jma、wn2-ens）→ 起報時間
    hourly: dict[str, dict[str, list[OmHour]]]  # icon／jma → icao → 逐時
    ensemble: dict[str, list[EnsStep]]  # icao → 6 小時一個時間點
    raw: dict[str, object]  # {"forecast": 回應, "ensemble": 回應}
    bytes_downloaded: int = 0
    calls: float = 0.0  # 這一報的加權呼叫次數
    members: int = 0  # 系集實際的成員數
    meta_errors: dict[str, str] = field(default_factory=dict)


def weighted_calls(n_vars: int, n_models: int, days: float, n_locations: int) -> float:
    """Open-Meteo 文件 API 頁的公式（`equivalent to N calls`）：系集的 `n_models` 是成員數。"""
    per = n_vars * max(n_models, 1) / 10
    return round(max(1.0, max(per, days / 14 * per)) * n_locations, 1)


def forecast_calls(n_locations: int) -> float:
    return weighted_calls(len(FORECAST_VARS), len(FORECAST_MODELS), FORECAST_DAYS, n_locations)


def ensemble_calls(n_locations: int) -> float:
    return weighted_calls(len(ENSEMBLE_VARS), ENSEMBLE_MEMBERS, FORECAST_DAYS, n_locations)


def _coords(points: list[tuple[float, float]]) -> dict[str, str]:
    return {
        "latitude": ",".join(f"{lat:g}" for lat, _ in points),
        "longitude": ",".join(f"{lon:g}" for _, lon in points),
    }


def forecast_params(points: list[tuple[float, float]]) -> dict[str, object]:
    return {
        **_coords(points),
        "models": ",".join(FORECAST_MODELS.values()),
        "hourly": ",".join(FORECAST_VARS),
        "forecast_days": FORECAST_DAYS,
        "wind_speed_unit": "kn",
        "timezone": "UTC",
    }


def ensemble_params(points: list[tuple[float, float]]) -> dict[str, object]:
    return {
        **_coords(points),
        "models": ENSEMBLE_MODEL,
        "hourly": ",".join(ENSEMBLE_VARS),
        "forecast_days": FORECAST_DAYS,
        "temporal_resolution": "native",
        "wind_speed_unit": "kn",
        "timezone": "UTC",
    }


def _num(v: object) -> float | None:
    return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else None


def _times(hourly: dict) -> list[datetime]:
    try:
        return [datetime.fromisoformat(t).replace(tzinfo=UTC) for t in hourly["time"]]
    except (KeyError, TypeError, ValueError) as e:
        raise OpenMeteoError("Open-Meteo 回應的 hourly.time 不對", "bad_format") from e


def _locations(doc: object, n: int, label: str) -> list[dict]:
    """多座標的回應是 list；一個座標時是單一物件。個數要和座標一樣。"""
    if isinstance(doc, dict) and doc.get("error"):
        raise OpenMeteoError(f"Open-Meteo {label}：{doc.get('reason')}", "api_error")
    locs = [doc] if isinstance(doc, dict) else doc
    if not isinstance(locs, list) or len(locs) != n or not all(isinstance(x, dict) for x in locs):
        raise OpenMeteoError(f"Open-Meteo {label} 回應的地點數不是 {n}", "bad_format")
    return locs


def _check_units(loc: dict, key: str, label: str) -> None:
    unit = (loc.get("hourly_units") or {}).get(key)
    if unit != "kn":
        raise OpenMeteoError(f"Open-Meteo {label} 的 {key} 單位是 {unit!r}，不是 kn", "bad_units")


def _series(hourly: dict, key: str, n: int) -> list[float | None]:
    vals = hourly.get(key)
    if not isinstance(vals, list):
        return [None] * n
    return [_num(v) for v in vals[:n]] + [None] * max(0, n - len(vals))


def parse_forecast(doc: object, icaos: list[str]) -> dict[str, dict[str, list[OmHour]]]:
    """預報 API 的回應 → `{模式 id: {icao: 逐時}}`。"""
    locs = _locations(doc, len(icaos), "預報")
    out: dict[str, dict[str, list[OmHour]]] = {mid: {} for mid in FORECAST_MODELS}
    for icao, loc in zip(icaos, locs, strict=True):
        hourly = loc.get("hourly") or {}
        times = _times(hourly)
        n = len(times)
        for mid, suffix in FORECAST_MODELS.items():
            _check_units(loc, f"wind_speed_10m_{suffix}", "預報")
            col = {v: _series(hourly, f"{v}_{suffix}", n) for v in FORECAST_VARS}
            rows = []
            for i, t in enumerate(times):
                snow_cm = col["snowfall"][i]
                code = col["weather_code"][i]
                rows.append(
                    OmHour(
                        valid=t,
                        wind_kt=col["wind_speed_10m"][i],
                        wdir=col["wind_direction_10m"][i],
                        gust_kt=col["wind_gusts_10m"][i],
                        precip_mm=col["precipitation"][i],
                        snow_mm=None if snow_cm is None else snow_cm / SNOW_CM_PER_MM,
                        vis_m=col["visibility"][i],
                        code=None if code is None else int(code),
                    )
                )
            out[mid][icao] = rows
    return out


def _member_keys(hourly: dict) -> list[str]:
    """`wind_speed_10m`（成員 0）、`wind_speed_10m_member01`…，照成員編號排。"""
    found = []
    for k in hourly:
        m = _MEMBER.match(k)
        if m:
            found.append((int(m.group(1) or 0), k))
    return [k for _, k in sorted(found)]


def parse_ensemble(doc: object, icaos: list[str]) -> tuple[dict[str, list[EnsStep]], int]:
    """系集 API 的回應 → `{icao: 時間點}` 與成員數（各地點取最多的）。"""
    locs = _locations(doc, len(icaos), "系集")
    out: dict[str, list[EnsStep]] = {}
    members = 0
    for icao, loc in zip(icaos, locs, strict=True):
        hourly = loc.get("hourly") or {}
        times = _times(hourly)
        keys = _member_keys(hourly)
        if not keys:
            raise OpenMeteoError("Open-Meteo 系集回應沒有 wind_speed_10m 的成員", "bad_format")
        _check_units(loc, keys[0], "系集")
        cols = [_series(hourly, k, len(times)) for k in keys]
        members = max(members, len(keys))
        out[icao] = [EnsStep(t, tuple(c[i] for c in cols)) for i, t in enumerate(times)]
    return out, members


def _meta_run(mid: str, session: requests.Session | None = None) -> datetime:
    r = http_get(
        META_URLS[mid], session=session, retries=1, timeout=META_TIMEOUT_S, error=OpenMeteoError
    )
    try:
        return datetime.fromtimestamp(int(r.json()["last_run_initialisation_time"]), UTC)
    except (ValueError, KeyError, TypeError) as e:
        raise OpenMeteoError(f"Open-Meteo {mid} 的 metadata 不對", "bad_meta") from e


def _get_json(
    url: str, params: dict[str, object], label: str, session: requests.Session | None = None
) -> tuple[object, int]:
    r = http_get(
        url, session=session, params=params, retries=1, timeout=TIMEOUT_S, error=OpenMeteoError
    )
    try:
        return r.json(), len(r.content)
    except ValueError as e:
        raise OpenMeteoError(f"Open-Meteo {label} 回傳不是 JSON", "bad_json") from e


def fetch(airports: list[Airport]) -> OpenMeteoData:
    """抓全部機場的 ICON、JMA GSM 與 WeatherNext 2 系集。任何一個資料請求失敗就整個
    丟 `OpenMeteoError`（這一報沒有這三票）；metadata 問不到只是那個模式的 `run` 是 None。"""
    t0 = time.monotonic()
    icaos = [a.icao for a in airports]
    points = [(a.lat, a.lon) for a in airports]
    with requests.Session() as session:
        fc, fc_size = _get_json(FORECAST_URL, forecast_params(points), "預報", session)
        hourly = parse_forecast(fc, icaos)
        ens, ens_size = _get_json(ENSEMBLE_URL, ensemble_params(points), "系集", session)
        ensemble, members = parse_ensemble(ens, icaos)
        runs: dict[str, datetime | None] = {}
        meta_errors: dict[str, str] = {}
        for mid in META_URLS:
            try:
                runs[mid] = _meta_run(mid, session)
            except OpenMeteoError as e:
                log.warning("Open-Meteo %s 的起報時間問不到：%s", mid, e)
                runs[mid] = None
                meta_errors[mid] = e.code
    calls = round(forecast_calls(len(points)) + ensemble_calls(len(points)), 1)
    log.info(
        "Open-Meteo：預報 %d bytes、系集 %d bytes（%d 個成員）、加權 %.1f 次，%.1f 秒；起報 %s",
        fc_size,
        ens_size,
        members,
        calls,
        time.monotonic() - t0,
        {k: v.isoformat() if v else None for k, v in runs.items()},
    )
    return OpenMeteoData(
        runs=runs,
        hourly=hourly,
        ensemble=ensemble,
        raw={"forecast": fc, "ensemble": ens},
        bytes_downloaded=fc_size + ens_size,
        calls=calls,
        members=members,
        meta_errors=meta_errors,
    )


# ---- 一格（6 小時）的換算；`assess` 用 ----


def rain_sum(hours: list[OmHour]) -> float | None:
    """格內逐時雨量加總（前一小時的量，所以是 (from, to] 的小時）；全部沒有回 None。"""
    vals = [h.precip_mm for h in hours if h.precip_mm is not None]
    return sum(vals) if vals else None


def slot_ptype(hours: list[OmHour]) -> str | None:
    """格內的降水型態：總降水 < 0.1 mm → `none`；有凍雨碼（66、67）→ `freezing_rain`、凍毛毛雨碼
    （56、57）→ `freezing_drizzle`；降雪水當量 > 0 且 ≥ 總降水的一半 → `snow`；其他 `rain`。
    沒有雨量回 None。"""
    rain = rain_sum(hours)
    if rain is None:
        return None
    if rain < NO_PRECIP_MM:
        return "none"
    codes = {h.code for h in hours}
    if codes & FREEZING_RAIN_CODES:
        return "freezing_rain"
    if codes & FREEZING_DRIZZLE_CODES:
        return "freezing_drizzle"
    snow = sum(h.snow_mm for h in hours if h.snow_mm is not None)
    if snow > 0 and snow * 2 >= rain:
        return "snow"
    return "rain"


def member_winds(steps: list[EnsStep]) -> list[float]:
    """每個成員在這些時間點裡最大的 10 米平均風（沒有值的成員跳過）。"""
    n = max((len(s.winds) for s in steps), default=0)
    out = []
    for i in range(n):
        vals = [s.winds[i] for s in steps if i < len(s.winds) and s.winds[i] is not None]
        if vals:
            out.append(max(vals))  # type: ignore[type-var]
    return out
