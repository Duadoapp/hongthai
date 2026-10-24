"""颱風地圖的官方路徑與暴風圈（HD34，Shawn 2026-10-23、2026-10-25 定案）：**只轉載、不計算**。

兩個來源，`build.py` 各自一個 `_call`（`cwaTyphoon`、`jmaTyphoon`），失敗互不影響；選哪一份、
範圍與輸出在 `typhoons.py`。

中央氣象署 `W-C0034-005`「颱風消息與警報-熱帶氣旋路徑」（`CWA_URL`，授權碼同 `CWA_API_KEY`、
放 `Authorization` 標頭）。照平台 API 文件（`https://opendata.cwa.gov.tw/apidoc/v1`，只有參數）
與資料說明（`https://opendata.cwa.gov.tw/opendatadoc/MFC/W-C0034-005.pdf`，XML 欄位與範例）寫，
沒有授權碼不能實抓：
- 有熱帶氣旋時每 6 小時更新、颱風警報期間每 3 小時；西北太平洋與南海**所有**活動中的熱帶氣旋
- 每個熱帶氣旋：`year`、`typhoon_name`（英文）、`cwb_typhoon_name`（中文）、`cwb_td_no`
  （熱帶性低氣壓編號）、`cwb_ty_no`（颱風編號，和國際編號同號）；`analysis_data.fix[]`
  （過去與現在）：`fix_time`、`coordinate`（**「經度,緯度」**，範例 `124.90,12.30`）、
  `circle_of_15ms.radius`（七級風暴風半徑，公里）、`circle_of_25ms.radius`（十級風暴風半徑，
  公里）；`forecast_data.fix[]`：`init_time`、`tau`（預報時距，小時）、`coordinate`、兩個暴風
  半徑、`radius_of_70percent_probability`（70% 機率圈半徑，公里）。`-99` 是沒有
- JSON 版的鍵名文件沒寫（XML 是 snake_case、`cwb_`；平台其他資料集有 camelCase、PascalCase，
  `cwb` 也陸續改 `cwa`），所以**比對鍵名時不分大小寫、忽略 `_` 與 `-`、`cwb` 當 `cwa`**
  （`_get`）；只有一筆時可能不是 list（`_as_list`）；座標也接受分開的 `latitude`／`longitude`。
  原始回應存 `history/raw/<日期>/<HHMM>Z-cwa-typhoon.json`，第一次實跑後對一次欄位名
- 預報點的時間是 `init_time` ＋ `tau` 小時（原文兩個欄位照相加，不是推算）；`leadHours` 是 `tau`
- 氣象署資料沒有每個颱風的發布時間：`issuedAt` 用最新定位時間（預報的 `init_time`，沒有預報就用
  最後一個 `fix_time`）

日本氣象廳 bosai 的颱風 JSON（JMA 網頁自己用的，非正式介面、不用金鑰；`events.py` 每小時的
現報也在用）：
- `targetTc.json`（`JMA_TARGET_URL`）：目前的熱帶氣旋，`tropicalCyclone`（代號 `TC2636`）、
  `typhoonNumber`（號數 `2630`，熱帶低氣壓沒有）
- `<代號>/specifications.json`（`JMA_SPEC_URL`）：第一筆 `part: "title"`（`issue.UTC` 發布
  時間、`typhoonNumber`、`name.en`），之後每筆一個時間點：`part.jp`（`実況`／`推定　１時間後`／
  `予報　２４時間後`）、`advancedHours`、`validtime.UTC`、`position.deg`（[緯, 經]）、
  `category.en`（TD／TS／STS／TY／LOW）、`galeWarning[]`（強風域，風速 15 m/s 以上）與
  `stormWarning[]`（實況是暴風域、25 m/s 以上；**預報點是暴風警戒域**），每筆 `area`（`東`、
  `南西`、`全域`…，預報點是 `{"jp", "en"}`）與 `range`（`{"km", "nm"}`）、
  `probabilityCircleRadius`（予報円＝70% 機率圈，`{"km", "nm"}`）
- `<代號>/forecast.json`（`JMA_FORECAST_URL`）：JMA 畫圖用的幾何，實況那筆有 `track`
  （`preTyphoon`／`typhoon` 等，[緯, 經] 的串，沒有時間）＝過去路徑；每筆的
  `galeWarningArea`（偏心圓 `center`＋`radius` 公尺）、`stormWarningArea`（`arc`／`line`）、
  `probabilityCircle` 照原樣放進那個點的 `jmaShapes`
- 2026-10-25 00:45 JST 那報實抓：targetTc 211 bytes；TC2636（29W 薔琵）specifications 2351、
  forecast 2827 bytes；TC2637（インファ）3945、3051 bytes。原始回應存
  `history/raw/<日期>/<HHMM>Z-jma-typhoon.json`
  （`{"targetTc": …, "<代號>": {"specifications": …, "forecast": …}}`）
- 某一顆的 `specifications.json` 抓不到就跳過那顆（記在 `errors`）；`forecast.json` 抓不到只少
  過去路徑與 `jmaShapes`

點的格式（兩個來源一樣，給 `typhoons.py` 直接輸出）：`time`、`lat`、`lon`；`now` 與預報點另有
`radius15`／`radius25`（七級／十級暴風半徑＝JMA 強風域／暴風域，每筆
`{"dir", "km"[, "nm"][, "area"]}`，`dir` 是 `all`／`N`／`NE`…，`area` 是 JMA 原文的方位）；
預報點另有 `leadHours`、`probabilityRadius`（`{"km"[, "nm"]}` 或 null）、`stormWarning`
（JMA 預報點的暴風警戒域，格式同 `radius25`；氣象署沒有，是 `[]`）。數值與單位照原文（氣象署
只有公里、JMA 公里與海浬都是原文），**沒有換算**。JMA 的點多 `category`（原文的 `category.en`）
與 `jmaShapes`；JMA 的過去路徑點 `time` 是 null、多 `stage`（`track` 的鍵）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import requests

from ..timeutil import iso, parse_time
from . import NonStrictTLSAdapter, SourceError, http_get

CWA_URL = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/W-C0034-005"
CWA_PAGE = "https://www.cwa.gov.tw/V8/C/P/Typhoon/TY_NEWS.html"
JMA_TARGET_URL = "https://www.jma.go.jp/bosai/typhoon/data/targetTc.json"
JMA_SPEC_URL = "https://www.jma.go.jp/bosai/typhoon/data/{tc}/specifications.json"
JMA_FORECAST_URL = "https://www.jma.go.jp/bosai/typhoon/data/{tc}/forecast.json"
JMA_PAGE = "https://www.jma.go.jp/bosai/map.html#contents=typhoon"
MISSING = -99
# JMA 的方位（`area`）→ 代碼；`全域` 是整圈
JMA_DIRS = {
    "全域": "all",
    "北": "N",
    "北東": "NE",
    "東": "E",
    "南東": "SE",
    "南": "S",
    "南西": "SW",
    "西": "W",
    "北西": "NW",
}
# forecast.json 每個點裡，照原樣放進 `jmaShapes` 的鍵
JMA_SHAPE_KEYS = ("galeWarningArea", "stormWarningArea", "probabilityCircle")


class TyphoonError(SourceError):
    pass


@dataclass
class Storm:
    """一個來源的一顆熱帶氣旋（點的格式見模組說明）。"""

    source: str  # cwa／jma
    key: str  # 來源自己的代號：氣象署 `ty30`／`td21`，JMA `TC2636`
    number: str | None  # 國際編號 `2630`（熱帶性低氣壓沒有）
    name_zh: str
    name_en: str
    issued_at: datetime | None
    past: list[dict] = field(default_factory=list)
    now: dict | None = None
    forecast: list[dict] = field(default_factory=list)


@dataclass
class TyphoonData:
    storms: list[Storm]
    raw: object
    errors: dict[str, str] = field(default_factory=dict)  # JMA 某一顆抓不到（代號 → 原因）


# ---- 共用 ----


def _norm(k: str) -> str:
    return re.sub(r"[_\-\s]", "", k).lower().replace("cwb", "cwa")


def _get(d: object, *names: str) -> object:
    """鍵名不分大小寫、忽略 `_`／`-`、`cwb` 當 `cwa`（氣象署 JSON 的鍵名寫法沒有文件）。"""
    if not isinstance(d, dict):
        return None
    want = {_norm(n) for n in names}
    for k, v in d.items():
        if isinstance(k, str) and _norm(k) in want:
            return v
    return None


def _as_list(v: object) -> list:
    if isinstance(v, list):
        return v
    return [] if v is None else [v]


def _scalar(v: object) -> object:
    """XML 轉 JSON 的元素可能是 `{"value": …}`、`{"#text": …}` 或一個 list；取第一個值。"""
    if isinstance(v, list):
        return _scalar(v[0]) if v else None
    if isinstance(v, dict):
        return _scalar(_get(v, "value", "#text", "text"))
    return v


def _num(v: object) -> int | float | None:
    """數字或數字字串；`-99`（沒有）與看不懂的回 None。整數照整數存。"""
    v = _scalar(v)
    if isinstance(v, bool) or v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f == MISSING or f != f:
        return None
    return int(f) if f.is_integer() else f


def _int(v: object) -> int | None:
    n = _num(v)
    return n if isinstance(n, int) and n > 0 else None


def _time(v: object) -> datetime | None:
    v = _scalar(v)
    if not isinstance(v, str) or not v.strip():
        return None
    try:
        return parse_time(v.strip())
    except ValueError:
        return None


def _text(v: object) -> str:
    v = _scalar(v)
    return v.strip() if isinstance(v, str) else ""


# ---- 中央氣象署 W-C0034-005 ----


def _cwa_coord(fix: dict) -> tuple[float | None, float | None]:
    """（緯, 經）。`coordinate` 是「經度,緯度」；沒有就找 `latitude`／`longitude`。"""
    c = _scalar(_get(fix, "coordinate"))
    if isinstance(c, str) and "," in c:
        lon, _, lat = c.partition(",")
        return _num(lat.strip()), _num(lon.strip())
    return _num(_get(fix, "latitude", "lat")), _num(_get(fix, "longitude", "lon"))


def _cwa_radius(fix: dict, name: str) -> list[dict]:
    """暴風半徑（公里）→ `[{"dir": "all", "km": …}]`；`-99` 或沒有是 `[]`。"""
    circle = _get(fix, name)
    km = _num(_get(circle, "radius") if isinstance(circle, dict) else circle)
    return [] if km is None else [{"dir": "all", "km": km}]


def _cwa_point(fix: dict, t: datetime | None) -> dict | None:
    lat, lon = _cwa_coord(fix)
    if lat is None or lon is None:
        return None
    return {
        "time": iso(t),
        "lat": lat,
        "lon": lon,
        "radius15": _cwa_radius(fix, "circle_of_15ms"),
        "radius25": _cwa_radius(fix, "circle_of_25ms"),
    }


def parse_cwa(data: object) -> list[Storm]:
    """`W-C0034-005` → 每顆熱帶氣旋一個 `Storm`（格式見模組說明）。`records` 有、但沒有
    熱帶氣旋時回 `[]`。"""
    records = _get(data, "records")
    if not isinstance(records, dict):
        raise TyphoonError("氣象署路徑回傳沒有 records", "bad_format")
    tcs = _get(records, "tropicalCyclones")
    if isinstance(tcs, dict) and _get(tcs, "tropicalCyclone") is not None:
        tcs = _get(tcs, "tropicalCyclone")
    out = []
    for tc in _as_list(tcs):
        if not isinstance(tc, dict):
            continue
        body = _get(tc, "dataset") if isinstance(_get(tc, "dataset"), dict) else tc
        ty_no = _int(_get(tc, "cwa_ty_no"))
        td_no = _int(_get(tc, "cwa_td_no"))
        year = _int(_get(tc, "year"))
        number = f"{year % 100:02d}{ty_no:02d}" if ty_no and year else None
        if ty_no:
            key = f"ty{ty_no:02d}"
        elif td_no:
            key = f"td{td_no:02d}"
        else:
            continue
        fixes = []
        for fix in _as_list(_get(_get(body, "analysis_data"), "fix")):
            if not isinstance(fix, dict):
                continue
            t = _time(_get(fix, "fix_time"))
            p = _cwa_point(fix, t)
            if p is not None and t is not None:
                fixes.append((t, p))
        fixes.sort(key=lambda x: x[0])
        forecast = []
        init_times = []
        for fix in _as_list(_get(_get(body, "forecast_data"), "fix")):
            if not isinstance(fix, dict):
                continue
            init = _time(_get(fix, "init_time"))
            tau = _num(_get(fix, "tau"))
            if init is None or tau is None:
                continue
            init_times.append(init)
            p = _cwa_point(fix, init + timedelta(hours=tau))
            if p is None:
                continue
            prob = _get(fix, "radius_of_70percent_probability")
            prob_km = _num(_get(prob, "radius") if isinstance(prob, dict) else prob)
            p["leadHours"] = tau
            p["probabilityRadius"] = None if prob_km is None else {"km": prob_km}
            p["stormWarning"] = []
            forecast.append(p)
        forecast.sort(key=lambda p: p["leadHours"])
        issued = max(init_times) if init_times else (fixes[-1][0] if fixes else None)
        out.append(
            Storm(
                source="cwa",
                key=key,
                number=number,
                name_zh=_text(_get(tc, "cwa_typhoon_name")),
                name_en=_text(_get(tc, "typhoon_name")).title(),
                issued_at=issued,
                past=[{"time": p["time"], "lat": p["lat"], "lon": p["lon"]} for _, p in fixes],
                now=fixes[-1][1] if fixes else None,
                forecast=forecast,
            )
        )
    return out


def fetch_cwa(api_key: str | None) -> TyphoonData:
    if not api_key:
        raise TyphoonError("沒有設定 CWA_API_KEY", "no_api_key")
    session = requests.Session()
    session.mount("https://opendata.cwa.gov.tw/", NonStrictTLSAdapter())
    r = http_get(CWA_URL, session=session, headers={"Authorization": api_key}, error=TyphoonError)
    try:
        data = r.json()
    except ValueError as e:
        raise TyphoonError("氣象署路徑回傳不是 JSON", "bad_json") from e
    if str(_get(data, "success")).lower() != "true":
        raise TyphoonError("氣象署路徑回傳 success 不是 true", "api_error")
    return TyphoonData(parse_cwa(data), data)


# ---- 日本氣象廳 ----


def _jma_area(v: object) -> str:
    if isinstance(v, dict):
        v = v.get("jp")
    return v.strip() if isinstance(v, str) else ""


def _jma_ranges(items: object) -> list[dict]:
    """`galeWarning`／`stormWarning` → `[{"dir", "area", "km", "nm"}]`（原文的數值，沒有的
    單位不放）。"""
    out = []
    for it in _as_list(items):
        if not isinstance(it, dict):
            continue
        rng = it.get("range") if isinstance(it.get("range"), dict) else {}
        units = {u: _num(rng.get(u)) for u in ("km", "nm")}
        if all(v is None for v in units.values()):
            continue
        area = _jma_area(it.get("area"))
        out.append(
            {
                "dir": JMA_DIRS.get(area.removesuffix("側")),
                "area": area,
                **{u: v for u, v in units.items() if v is not None},
            }
        )
    return out


def _jma_label(part: object) -> str:
    return part.get("jp", "") if isinstance(part, dict) else ""


def parse_jma(tc: str, spec: object, forecast: object = None) -> Storm | None:
    """一顆的 `specifications.json`（與 `forecast.json`）→ `Storm`；看不懂回 None。"""
    if not isinstance(spec, list):
        return None
    title = next((p for p in spec if isinstance(p, dict) and p.get("part") == "title"), {})
    shapes: dict[object, dict] = {}
    past: list[dict] = []
    for p in forecast if isinstance(forecast, list) else []:
        if not isinstance(p, dict) or p.get("part") == "title":
            continue
        sh = {k: p[k] for k in JMA_SHAPE_KEYS if k in p}
        if sh:
            shapes[p.get("advancedHours")] = sh
        track = p.get("track")
        if isinstance(track, dict):
            for stage, pts in track.items():
                for pt in _as_list(pts):
                    if isinstance(pt, list) and len(pt) >= 2:
                        lat, lon = _num(pt[0]), _num(pt[1])
                        if lat is not None and lon is not None:
                            past.append({"time": None, "lat": lat, "lon": lon, "stage": stage})
    now_cands: list[dict] = []
    fc: list[dict] = []
    for p in spec:
        if not isinstance(p, dict) or p.get("part") == "title":
            continue
        pos = (p.get("position") or {}).get("deg") if isinstance(p.get("position"), dict) else None
        if not isinstance(pos, list) or len(pos) < 2:
            continue
        lat, lon = _num(pos[0]), _num(pos[1])
        lead = _num(p.get("advancedHours"))
        if lat is None or lon is None or lead is None:
            continue
        label = _jma_label(p.get("part"))
        cat = p.get("category")
        point: dict = {
            "time": iso(_time((p.get("validtime") or {}).get("UTC"))),
            "lat": lat,
            "lon": lon,
            "category": cat.get("en") if isinstance(cat, dict) else None,
            "radius15": _jma_ranges(p.get("galeWarning")),
        }
        is_now = label.startswith(("実況", "推定")) or (not label and lead == 0)
        if is_now:
            point["radius25"] = _jma_ranges(p.get("stormWarning"))
        else:
            prob = p.get("probabilityCircleRadius")
            units = {u: _num(prob.get(u)) for u in ("km", "nm")} if isinstance(prob, dict) else {}
            units = {u: v for u, v in units.items() if v is not None}
            point.update(
                leadHours=lead,
                radius25=[],
                probabilityRadius=units or None,
                stormWarning=_jma_ranges(p.get("stormWarning")),
            )
        if lead in shapes:
            point["jmaShapes"] = shapes[lead]
        (now_cands if is_now else fc).append(point)
    if not now_cands and not fc:
        return None
    now = max(now_cands, key=lambda q: q["time"] or "") if now_cands else None
    name = title.get("name") if isinstance(title.get("name"), dict) else {}
    number = title.get("typhoonNumber")
    return Storm(
        source="jma",
        key=tc,
        number=number if isinstance(number, str) and number.isdigit() else None,
        name_zh="",
        name_en=_text(name.get("en")),
        issued_at=_time((title.get("issue") or {}).get("UTC")),
        past=past,
        now=now,
        forecast=sorted(fc, key=lambda q: q["leadHours"]),
    )


def fetch_jma() -> TyphoonData:
    try:
        target = http_get(JMA_TARGET_URL, error=TyphoonError).json()
    except ValueError as e:
        raise TyphoonError("JMA targetTc 回傳不是 JSON", "bad_json") from e
    if not isinstance(target, list):
        raise TyphoonError("JMA targetTc 不是 list", "bad_format")
    raw: dict[str, object] = {"targetTc": target}
    out = TyphoonData([], raw)
    for t in target:
        tc = t.get("tropicalCyclone") if isinstance(t, dict) else None
        if not isinstance(tc, str) or not re.fullmatch(r"TC\d+", tc):
            continue
        try:
            spec = http_get(JMA_SPEC_URL.format(tc=tc), error=TyphoonError).json()
        except (TyphoonError, ValueError) as e:
            out.errors[tc] = getattr(e, "code", "bad_json")
            continue
        try:
            fc = http_get(JMA_FORECAST_URL.format(tc=tc), error=TyphoonError).json()
        except (TyphoonError, ValueError) as e:
            out.errors[f"{tc}/forecast"] = getattr(e, "code", "bad_json")
            fc = None
        raw[tc] = {"specifications": spec, "forecast": fc}
        storm = parse_jma(tc, spec, fc)
        if storm is None:
            out.errors[tc] = "bad_format"
        else:
            out.storms.append(storm)
    return out
