"""用 cfgrib／xarray 讀 GRIB，取各機場最近格點的時間序列。

eccodes 不是執行緒安全的，而超過時間預算被放棄的來源執行緒可能還在背景跑（見 `budget.py`），
所以所有解析都包在全域的 `GRIB_LOCK` 裡；被放棄的執行緒在解析前就會因 `check_cancelled()` 結束。

NOAA 的 `.idx`（GFS、AIGFS 共用，HD14 從 `sources/gfs.py` 搬來）：一行一筆
`序號:byte 起點:d=<時次>:變數:層:時效:`；`byte_ranges` 算出要抓的那幾筆的 byte 範圍。
"""

from __future__ import annotations

import logging
import re
import threading
import warnings
from dataclasses import dataclass
from datetime import UTC, datetime
from math import atan2, degrees, hypot
from pathlib import Path

import numpy as np
import xarray as xr

from .budget import check_cancelled
from .units import ms_to_kt

log = logging.getLogger("hongthai")

GRIB_LOCK = threading.Lock()


@dataclass
class PointSeries:
    """單一變數在單一點的值；`steps` 是預報步長（小時，區間型參數是區間的結束步長）。"""

    run: datetime
    steps: list[float]
    values: list[float | None]


def _to_datetime(v) -> datetime:
    ts = (np.datetime64(v, "s") - np.datetime64(0, "s")) / np.timedelta64(1, "s")
    return datetime.fromtimestamp(float(ts), UTC)


def read_points(
    path: str | Path, points: dict[str, tuple[float, float]]
) -> dict[str, dict[str, PointSeries]]:
    """回傳 `{點名稱: {GRIB shortName: PointSeries}}`。

    shortName 例如 `10fg`、`10fg3`、`10fgg25`、`gust`。時段平均型（`stepType` 是 `avg`，例如 GFS 的
    `0-6 hour ave` 類別降水）的鍵加 `:avg`（`csnow:avg`），不和同名的瞬時值混在一起（HD8）。
    """
    import cfgrib  # 延後載入：沒有 eccodes 的環境也能跑其他測試

    check_cancelled()
    with GRIB_LOCK:
        check_cancelled()  # 等鎖的時候可能剛好超時
        return _read_points(cfgrib, path, points)


def _read_points(cfgrib, path, points) -> dict[str, dict[str, PointSeries]]:
    out: dict[str, dict[str, PointSeries]] = {k: {} for k in points}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        datasets = cfgrib.open_datasets(str(path), backend_kwargs={"indexpath": ""})
    names = list(points)
    for ds in datasets:
        run = _to_datetime(ds["time"].values)
        steps = np.atleast_1d(ds["step"].values) / np.timedelta64(1, "h")
        lon_max = float(ds["longitude"].max())
        # 所有點一次取（向量化的 nearest）：一個變數只解碼一次，點數多（H9 起 41 個）也不會變慢
        lats = xr.DataArray([points[n][0] for n in names], dims="point")
        lons = [points[n][1] for n in names]
        lons = xr.DataArray([x + 360 if x < 0 and lon_max > 180 else x for x in lons], dims="point")
        for var in ds.data_vars:
            da = ds[var]
            key = da.attrs.get("GRIB_shortName") or str(var)
            if da.attrs.get("GRIB_stepType") == "avg":
                key += ":avg"
            picked = da.sel(latitude=lats, longitude=lons, method="nearest")
            table = picked.transpose(..., "point").values.reshape(-1, len(names))
            for i, name in enumerate(names):
                series = out[name].setdefault(key, PointSeries(run, [], []))
                for s, v in zip(steps, table[:, i], strict=True):
                    series.steps.append(float(s))
                    series.values.append(None if np.isnan(v) else float(v))
        ds.close()
    return out


def wind_dir_from_uv(u: float | None, v: float | None) -> float | None:
    """風的 u／v 分量（m/s）→ 風向（風「吹來」的方向，度，真北）；沒資料或無風時回 None。"""
    if u is None or v is None or hypot(u, v) < 0.1:
        return None
    return degrees(atan2(-u, -v)) % 360


def wind_speed_kt(u: float | None, v: float | None) -> float | None:
    """風的 u／v 分量（m/s）→ 風速（節，HD18）；沒資料回 None。"""
    if u is None or v is None:
        return None
    return ms_to_kt(hypot(u, v))


# ---- NOAA `.idx`（GFS、AIGFS）----

# 從起報累積的時效字串：`0-12 hour acc fcst`、`0-5 day acc fcst`（AIGFS 的 f120，HD14）
_ACC_FROM_START = re.compile(r"^0-(\d+) (hour|day) acc fcst$")


def idx_records(idx_text: str) -> list[tuple[int, str, str, str]]:
    """`.idx` 文字 → （byte 起點, 變數, 層, 時效）；格式不對的行跳過。"""
    recs = []
    for line in idx_text.splitlines():
        parts = line.split(":")
        if len(parts) < 5 or not parts[1].strip().isdigit():
            continue
        recs.append((int(parts[1]), parts[3], parts[4], parts[5] if len(parts) > 5 else ""))
    return recs


def idx_time_ok(kind: str | None, text: str, fh: int | None) -> bool:
    """時效：None＝不限、`inst`＝瞬時（`anl`／`<n> hour fcst`）、`acc6`＝前 6 小時的累積
    （`<fh−6>-<fh> hour acc fcst`）、`acc0`＝從起報累積到 `fh`（`0-<fh> hour acc fcst`，
    或 `0-<n> day acc fcst`；HD14）。`acc6`／`acc0` 要給 `fh`。"""
    if kind is None:
        return True
    if kind == "inst":
        return "-" not in text and "ave" not in text and "acc" not in text
    if kind == "acc6":
        return fh is not None and text.strip() == f"{fh - 6}-{fh} hour acc fcst"
    if kind == "acc0":
        m = _ACC_FROM_START.match(text.strip())
        return m is not None and fh is not None and int(m[1]) * (24 if m[2] == "day" else 1) == fh
    raise ValueError(f"不認得的時效種類 {kind!r}")


def _time_of(field: tuple[str, ...], when: str, fh: int | None) -> bool:
    return idx_time_ok(field[2] if len(field) > 2 else None, when, fh)


def idx_has(idx_text: str, field: tuple[str, ...], fh: int | None = None) -> bool:
    """`.idx` 裡有沒有這個（變數, 層[, 時效]）。"""
    return any(
        (var, lev) == field[:2] and _time_of(field, when, fh)
        for _, var, lev, when in idx_records(idx_text)
    )


def byte_ranges(
    idx_text: str,
    fields,
    fh: int | None = None,
    optional=(),
    *,
    error: type[Exception] = ValueError,
    label: str = "",
) -> list[tuple[int, int | None]]:
    """`.idx` 文字 → 要抓的 byte 範圍（頭尾都含；最後一筆到檔尾時尾是 None），相鄰的併成一段。

    一筆的範圍是它的起點到下一個（起點更大的）紀錄的起點前一個 byte。`fields`／`optional` 每個是
    （變數, 層）或（變數, 層, 時效），時效見 `idx_time_ok`；同一個欄位只取第一筆合的。`fields` 少了
    任何一筆就丟 `error(…, "bad_idx")`，`optional` 少了只 log。
    """
    recs = idx_records(idx_text)
    starts = sorted({r[0] for r in recs})
    required = {tuple(f) for f in fields}
    wanted = required | {tuple(f) for f in optional}
    found: set[tuple[str, ...]] = set()
    out: list[tuple[int, int | None]] = []
    for start, var, lev, when in sorted(recs):
        hit = next(
            (f for f in wanted - found if f[:2] == (var, lev) and _time_of(f, when, fh)),
            None,
        )
        if hit is None:
            continue
        found.add(hit)
        later = [s for s in starts if s > start]
        end = later[0] - 1 if later else None
        if out and out[-1][1] is not None and out[-1][1] + 1 == start:
            out[-1] = (out[-1][0], end)
        else:
            out.append((start, end))
    if not required <= found:
        missing = ", ".join(":".join(f) for f in fields if tuple(f) not in found)
        raise error(f".idx 裡沒有 {missing}", "bad_idx")
    if found != wanted:
        lost = ", ".join(":".join(f) for f in optional if tuple(f) not in found)
        log.warning("%s f%s 的 .idx 裡沒有 %s，這幾筆不抓", label, fh, lost)
    return out
