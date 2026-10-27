"""「幾點進暴風圈」（HD41，Shawn 2026-10-27 16:52、18:34 定案）：依官方暴風圈預報推算 51 個機場的
進入／離開時間，放在 `typhoons.json` 的 `entries`（`typhoons.build` 呼叫 `entries`）。

**這是 HongThai 依官方暴風圈預報推算的，不是官方發布**；方法刻意單純、可說明，不加任何自己的預測
（氣象署 2026-10-27 回覆第 1 點：延伸詮釋可能涉及預報）。網頁（Duado HW21）寫「依<來源>官方暴風圈
預報推算」，境外（日本氣象廳那份）加註「非日本氣象廳發布」，旁邊附標語。

- 每顆在 `storms` 裡、不是 `stale` 的颱風（`ended` 的本來就不在 `storms`）× 每個機場，只用那顆
  選用來源（`source`，和颱風地圖同一份、中途不換）的官方暴風圈：
  - 氣象署：`cwa_r15`（七級風暴風半徑 `Circle15ms`，15 m/s）、`cwa_r25`（十級風 `Circle25ms`，
    25 m/s），實況點與預報點同一種圈；**不用** 70% 機率圈
  - 日本氣象廳：`jma_storm_warning`（預報點的暴風警戒域 `stormWarning`＝暴風域 25 m/s 可能到達的
    範圍，原文已含預報誤差；起點是實況點的暴風域，和 JMA `forecast.json` 的 `stormWarningArea`
    一樣從實況暴風域接到各預報點的暴風警戒域）、`jma_storm`（實況點的暴風域）、`jma_gale`（實況點的
    強風域，15 m/s）。預報點沒有暴風域與強風域，所以 `jma_storm`／`jma_gale` 只看實況點（只會有
    `now`，不會有進入時間）
- 半徑：每筆原文有 `km` 就用 `km`，只有 `nm` 的乘 1.852。方位：
  - 氣象署實況點的四象限半徑（`radius15Quadrants`／`radius25Quadrants`，`NE`／`SE`／`SW`／`NW`）
    有就照機場在中心的哪個象限用那個半徑，沒有（預報點、上一份沿用的那筆）用整圈 `all`
  - 日本氣象廳的方位（`北`／`南`、`南西`／`北東`…兩個相對的方位）是**偏心圓**（氣象廳的定義：
    直徑兩端分別在兩個方位的距離上）：圓心往大的那邊移（大－小）÷2、半徑（大＋小）÷2；JMA 自己
    `forecast.json` 的 `galeWarningArea`（`center`、`radius`）就是這樣算的。`全域` 是整圈；其他
    看不懂的組合用最大的那個當整圈
- 時間軸：實況點＋預報點（官方的點）照時間排，取**第一段連續都有這種圈的點**（中間有一點沒有這種圈
  就到前一點為止，不跨過去）。相鄰兩點之間，**圓心經緯度與每個方位的半徑照時間線性內插**，每個 UTC
  整點檢查機場在不在圈內（大圓距離）。第一個在圈內的整點＝`enterAt`、之後第一個不在圈內的整點＝
  `exitAt`；到最後一點還在圈內就沒有 `exitAt`（null）。**不外插**：最後一點之後、第一點之前都不算
- 實況點（`now`）就已經在圈內 → `now: true`、`enterAt: null`（實況是那份官方資料的時間，不是
  `generatedAt`）
- 同一個機場、同一顆、同一種圈一筆；沒有進入的不寫

每筆 `{"iata", "icao", "stormId", "source", "circle", "enterAt", "exitAt", "now", "issuedAt",
"method": "linear_hourly"}`；時間是 UTC 整點，`issuedAt` 是那顆的 `issuedAt`（那份官方資料的發布
時間）。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from math import asin, atan2, cos, degrees, radians, sin, sqrt
from typing import Protocol

from .timeutil import iso, parse_time

METHOD = "linear_hourly"
EARTH_KM = 6371
NM_KM = 1.852
# （圈的代碼, 實況點的鍵, 預報點的鍵）：鍵是 `typhoons.json` 點的欄位
CIRCLES = {
    "cwa": (("cwa_r15", "radius15", "radius15"), ("cwa_r25", "radius25", "radius25")),
    "jma": (
        ("jma_storm_warning", "radius25", "stormWarning"),
        ("jma_storm", "radius25", "radius25"),
        ("jma_gale", "radius15", "radius15"),
    ),
}
QUADS = ("NE", "SE", "SW", "NW")  # 象限 i 是方位角 90i–90(i+1) 度
ANGLE = {"N": 0, "NE": 45, "E": 90, "SE": 135, "S": 180, "SW": 225, "W": 270, "NW": 315}

Shape = tuple[float, float, tuple[float, float, float, float]]  # 圓心（緯, 經）與四象限半徑（公里）


class Place(Protocol):
    iata: str
    icao: str
    lat: float
    lon: float


def km_between(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """大圓距離（公里）。"""
    p1, l1, p2, l2 = map(radians, (lat1, lon1, lat2, lon2))
    h = sin((p2 - p1) / 2) ** 2 + cos(p1) * cos(p2) * sin((l2 - l1) / 2) ** 2
    return 2 * EARTH_KM * asin(min(1.0, sqrt(h)))


def bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """從第一點看第二點的方位角（度，北 0、順時針，0–360）。"""
    p1, l1, p2, l2 = map(radians, (lat1, lon1, lat2, lon2))
    y = sin(l2 - l1) * cos(p2)
    x = cos(p1) * sin(p2) - sin(p1) * cos(p2) * cos(l2 - l1)
    return degrees(atan2(y, x)) % 360


def destination(lat: float, lon: float, angle: float, km: float) -> tuple[float, float]:
    """從（緯, 經）往方位角 `angle` 走 `km` 公里的點（大圓）。"""
    p, lam, th, d = radians(lat), radians(lon), radians(angle), km / EARTH_KM
    p2 = asin(sin(p) * cos(d) + cos(p) * sin(d) * cos(th))
    lam2 = lam + atan2(sin(th) * sin(d) * cos(p), cos(d) - sin(p) * sin(p2))
    return degrees(p2), degrees(lam2)


def _km(r: object) -> float | None:
    """一筆半徑（`{"dir", "km"[, "nm"]}`）的公里：有 `km` 用 `km`，只有 `nm` 的換算。"""
    if not isinstance(r, dict):
        return None
    for unit, factor in (("km", 1.0), ("nm", NM_KM)):
        v = r.get(unit)
        if isinstance(v, int | float) and not isinstance(v, bool) and v > 0:
            return float(v) * factor
    return None


def _radii(items: object) -> list[tuple[str | None, float]]:
    out = []
    for r in items if isinstance(items, list) else []:
        km = _km(r)
        if km is not None:
            d = r.get("dir")
            out.append((d if isinstance(d, str) else None, km))
    return out


def shape(point: dict, key: str) -> Shape | None:
    """一個官方點的這種圈（規則見模組說明）；這一點沒有這種圈回 None。"""
    lat, lon = point.get("lat"), point.get("lon")
    if not isinstance(lat, int | float) or not isinstance(lon, int | float):
        return None
    radii = _radii(point.get(key))
    quads = {d: km for d, km in _radii(point.get(f"{key}Quadrants")) if d in QUADS}
    whole = next((km for d, km in radii if d == "all"), None)
    if quads:  # 氣象署四象限：缺的象限用整圈
        fill = whole if whole is not None else max(quads.values())
        return lat, lon, tuple(quads.get(q, fill) for q in QUADS)  # type: ignore[return-value]
    if not radii:
        return None
    if whole is not None:
        return lat, lon, (whole,) * 4
    dirs = [(ANGLE.get(d or ""), km) for d, km in radii]
    if len(dirs) == 2 and all(a is not None for a, _ in dirs):
        (a1, k1), (a2, k2) = sorted(dirs, key=lambda x: -x[1])
        if abs(a1 - a2) == 180:  # type: ignore[operator]
            clat, clon = destination(lat, lon, a1, (k1 - k2) / 2)  # type: ignore[arg-type]
            return clat, clon, ((k1 + k2) / 2,) * 4
    r = max(km for _, km in radii)
    return lat, lon, (r,) * 4


def inside(s: Shape, lat: float, lon: float) -> bool:
    clat, clon, radii = s
    d = km_between(clat, clon, lat, lon)
    if d == 0:
        return True
    return d <= radii[int(bearing(clat, clon, lat, lon) // 90) % 4]


def _lerp(a: Shape, b: Shape, f: float) -> Shape:
    return (
        a[0] + (b[0] - a[0]) * f,
        a[1] + (b[1] - a[1]) * f,
        tuple(x + (y - x) * f for x, y in zip(a[2], b[2], strict=True)),  # type: ignore[arg-type]
    )


Run = list[tuple[datetime, Shape]]
Hit = tuple[bool, datetime | None, datetime | None]  # （`now`, 進入, 離開）


def run_of(storm: dict, now_key: str, fc_key: str) -> tuple[Run, bool]:
    """這顆這種圈的時間軸：第一段連續都有這種圈的官方點（時間, 圈），與這段是不是從實況點開始。"""
    pts: list[tuple[datetime, Shape | None, bool]] = []
    now = storm.get("now")
    if isinstance(now, dict) and (t := parse_time(now.get("time"))) is not None:
        pts.append((t, shape(now, now_key), True))
    for p in storm.get("forecast") or []:
        if isinstance(p, dict) and (t := parse_time(p.get("time"))) is not None:
            pts.append((t, shape(p, fc_key), False))
    pts.sort(key=lambda x: (x[0], not x[2]))
    run: Run = []
    at_now = False
    for t, s, is_now in pts:
        if s is None:
            if run:
                break
            continue
        if run and t <= run[-1][0]:
            continue  # 同一時間的第二點（不該有）不用
        if not run:
            at_now = is_now
        run.append((t, s))
    return run, at_now


def shape_at(run: Run, t: datetime) -> Shape | None:
    """時間 `t` 的圈（相鄰兩點線性內插）；在這段之外回 None（不外插）。"""
    for (t0, s0), (t1, s1) in zip(run, run[1:], strict=False):
        if t0 <= t <= t1:
            return _lerp(s0, s1, (t - t0) / (t1 - t0))
    if run and t == run[0][0]:
        return run[0][1]
    return None


def _hours(start: datetime, end: datetime) -> list[datetime]:
    """`start` 到 `end`（含）之間的每個 UTC 整點。"""
    h = start.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    if h < start:
        h += timedelta(hours=1)
    out = []
    while h <= end:
        out.append(h)
        h += timedelta(hours=1)
    return out


def crossing(run: Run, at_now: bool, lat: float, lon: float) -> Hit | None:
    """（`now`, 進入, 離開）；這段都沒進圈回 None。"""
    if not run:
        return None
    now_in = at_now and inside(run[0][1], lat, lon)
    entered, enter, leave = now_in, None, None
    for h in _hours(run[0][0], run[-1][0]):
        s = shape_at(run, h)
        if s is None:
            continue
        hit = inside(s, lat, lon)
        if not entered and hit:
            entered, enter = True, h
        elif entered and not hit:
            leave = h
            break
    return (now_in, enter, leave) if entered else None


def entries(storms: Sequence[dict], airports: Sequence[Place]) -> list[dict]:
    """`typhoons.json` 的 `entries`（規則見模組說明），照 `storms`、機場、圈的順序。"""
    out = []
    for storm in storms:
        if not isinstance(storm, dict) or storm.get("stale"):
            continue
        source = storm.get("source")
        circles = CIRCLES.get(source, ()) if isinstance(source, str) else ()
        runs = [(circle, *run_of(storm, now_key, fc_key)) for circle, now_key, fc_key in circles]
        for a in airports:
            for circle, run, at_now in runs:
                hit = crossing(run, at_now, a.lat, a.lon)
                if hit is None:
                    continue
                now_in, enter, leave = hit
                out.append(
                    {
                        "iata": a.iata,
                        "icao": a.icao,
                        "stormId": storm.get("id"),
                        "source": source,
                        "circle": circle,
                        "enterAt": iso(enter),
                        "exitAt": iso(leave),
                        "now": now_in,
                        "issuedAt": storm.get("issuedAt"),
                        "method": METHOD,
                    }
                )
    return out
