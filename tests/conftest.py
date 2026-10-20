from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).parent.parent


def load_json(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=UTC)


@pytest.fixture
def airports():
    from hongthai.config import load_airports

    return load_airports(ROOT / "airports.json")


def mslp_grib(
    short_name: str = "prmsl",
    steps=(6,),
    lon_first: float = 0.0,
    lows: dict | None = None,
    run=(2026, 10, 20, 0),
) -> bytes:
    """1° 全球的海平面氣壓 GRIB2（HD21 的測試用，eccodes 現做）：底是 1012 hPa，
    `lows` 是 `{步長: (緯, 經, 深度 hPa)}`（高斯形的低壓）。`lon_first` 180 像 ECMWF（經度
    −180–180）、0 像 NOAA。`short_name` 給別的（例如 `2t`）就是不相干的場。"""
    import eccodes
    import numpy as np

    lats = np.arange(90, -90.5, -1.0)
    lons = (lon_first + np.arange(360.0)) % 360
    out = b""
    for step in steps:
        h = eccodes.codes_grib_new_from_samples("regular_ll_sfc_grib2")
        for k, v in (
            ("Ni", 360),
            ("Nj", 181),
            ("latitudeOfFirstGridPointInDegrees", 90.0),
            ("longitudeOfFirstGridPointInDegrees", lon_first),
            ("latitudeOfLastGridPointInDegrees", -90.0),
            ("longitudeOfLastGridPointInDegrees", (lon_first + 359) % 360),
            ("iDirectionIncrementInDegrees", 1.0),
            ("jDirectionIncrementInDegrees", 1.0),
            ("dataDate", run[0] * 10000 + run[1] * 100 + run[2]),
            ("dataTime", run[3] * 100),
            ("shortName", short_name),
            ("step", step),
            ("bitsPerValue", 16),
        ):
            eccodes.codes_set(h, k, v)
        vals = np.full((181, 360), 101200.0)
        if lows and step in lows:
            la, lo, depth = lows[step]
            dlon = (lons[None, :] - lo + 180) % 360 - 180
            vals -= depth * 100 * np.exp(-((lats[:, None] - la) ** 2 + dlon**2) / (2 * 1.5**2))
        eccodes.codes_set_values(h, vals.ravel())
        out += eccodes.codes_get_message(h)
        eccodes.codes_release(h)
    return out
