"""用 cfgrib／xarray 讀 GRIB，取各機場最近格點的時間序列。

eccodes 不是執行緒安全的，而超過時間預算被放棄的來源執行緒可能還在背景跑（見 `budget.py`），
所以所有解析都包在全域的 `GRIB_LOCK` 裡；被放棄的執行緒在解析前就會因 `check_cancelled()` 結束。
"""

from __future__ import annotations

import threading
import warnings
from dataclasses import dataclass
from datetime import UTC, datetime
from math import atan2, degrees, hypot
from pathlib import Path

import numpy as np
import xarray as xr

from .budget import check_cancelled

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
