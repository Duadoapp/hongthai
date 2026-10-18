"""用 cfgrib／xarray 讀 GRIB，取各機場最近格點的時間序列。"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from datetime import UTC, datetime
from math import atan2, degrees, hypot
from pathlib import Path

import numpy as np


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

    shortName 例如 `10fg`、`10fg3`、`10fgg25`、`gust`。
    """
    import cfgrib  # 延後載入：沒有 eccodes 的環境也能跑其他測試

    out: dict[str, dict[str, PointSeries]] = {k: {} for k in points}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        datasets = cfgrib.open_datasets(str(path), backend_kwargs={"indexpath": ""})
    for ds in datasets:
        run = _to_datetime(ds["time"].values)
        steps = np.atleast_1d(ds["step"].values) / np.timedelta64(1, "h")
        lon_max = float(ds["longitude"].max())
        for var in ds.data_vars:
            da = ds[var]
            key = da.attrs.get("GRIB_shortName") or str(var)
            for name, (lat, lon) in points.items():
                if lon < 0 and lon_max > 180:
                    lon += 360
                vals = np.atleast_1d(da.sel(latitude=lat, longitude=lon, method="nearest").values)
                series = out[name].setdefault(key, PointSeries(run, [], []))
                for s, v in zip(steps, vals, strict=True):
                    series.steps.append(float(s))
                    series.values.append(None if np.isnan(v) else float(v))
        ds.close()
    return out


def wind_dir_from_uv(u: float | None, v: float | None) -> float | None:
    """風的 u／v 分量（m/s）→ 風向（風「吹來」的方向，度，真北）；沒資料或無風時回 None。"""
    if u is None or v is None or hypot(u, v) < 0.1:
        return None
    return degrees(atan2(-u, -v)) % 360
