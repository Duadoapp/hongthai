"""HD18：IFS、GFS 多留 10 米平均風（`GustInterval.wind_kt`、`GustPoint.wind_kt`），從 u／v 算。"""

from __future__ import annotations

from datetime import timedelta
from math import hypot

import pytest
from conftest import FIXTURES, utc

from hongthai import grib
from hongthai.sources import ecmwf, gfs
from hongthai.units import KT_PER_MS


def test_wind_speed_kt():
    assert grib.wind_speed_kt(3.0, -4.0) == pytest.approx(5 * KT_PER_MS)
    assert grib.wind_speed_kt(0.0, 0.0) == 0
    assert grib.wind_speed_kt(None, 1.0) is None and grib.wind_speed_kt(1.0, None) is None


def test_ecmwf_wind_kt_from_uv_at_wind_step(airports):
    """每個陣風區間的平均風＝`wind_step`（區間結束往後最近的 6 小時步長）那個 `10u`／`10v` 的風速，
    和風向同一個時間點。"""
    run, pts = ecmwf.parse_hres(FIXTURES / "ecmwf_oper_subregion.grib2", airports)
    raw = grib.read_points(FIXTURES / "ecmwf_oper_subregion.grib2", {"VHHH": (22.31, 113.92)})
    uv = {
        k: dict(zip(raw["VHHH"][k].steps, raw["VHHH"][k].values, strict=True))
        for k in ("10u", "10v")
    }
    g = pts["VHHH"]
    # fixture 18Z 起報：87、90 → 90；93、96 → 96
    for x, ws in zip(g, (90, 90, 96, 96), strict=True):
        assert x.end - run in (timedelta(hours=ws), timedelta(hours=ws - 3))
        expect = hypot(uv["10u"][ws], uv["10v"][ws]) * KT_PER_MS
        assert x.wind_kt == pytest.approx(expect)
        assert x.wind_kt > 0
    assert g[0].wind_kt == g[1].wind_kt and g[2].wind_kt == g[3].wind_kt


def test_ecmwf_wind_kt_none_without_uv(airports, tmp_path):
    """只有陣風、沒有 10u／10v 的檔：風向與平均風都是 None。"""
    import eccodes

    gust = tmp_path / "gust.grib2"
    with open(FIXTURES / "ecmwf_oper_subregion.grib2", "rb") as src, gust.open("wb") as out:
        while (h := eccodes.codes_grib_new_from_file(src)) is not None:
            if eccodes.codes_get(h, "shortName") in ecmwf.HRES_GUST_PARAMS:
                out.write(eccodes.codes_get_message(h))
            eccodes.codes_release(h)
    _, pts = ecmwf.parse_hres(gust, airports)
    assert all(x.wind_kt is None and x.wdir is None for x in pts["VHHH"])


def test_gfs_wind_kt_from_uv(airports):
    by = {a.icao: a for a in airports}
    pts = gfs.parse_file(FIXTURES / "gfs_tw_f006.grb2", [by["RCTP"]])
    raw = grib.read_points(
        FIXTURES / "gfs_tw_f006.grb2", {"RCTP": (by["RCTP"].lat, by["RCTP"].lon)}
    )
    u, v = raw["RCTP"]["10u"].values[0], raw["RCTP"]["10v"].values[0]
    (p,) = pts["RCTP"]
    assert p.valid == utc(2026, 10, 18, 6)
    assert p.wind_kt == pytest.approx(hypot(u, v) * KT_PER_MS)
    # 弱風時 GFS 的 GUST 可以比 10 米風小（這格 5.4 對 8.0 節）；樣本只收平均風 ≥ 10 節的格
    assert p.wind_kt == pytest.approx(8.03, abs=0.01) and p.gust_kt < p.wind_kt
