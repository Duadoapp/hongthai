"""WeatherNext 3（HD15）：來源（BigQuery 假物件、本機 Zarr）、開關、每格的數字、旁觀不投票、
通用的找中心函式、事件檔與補報。全部不連網。"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, timedelta

import numpy as np
import pytest
import xarray as xr
from conftest import mslp_grib, utc
from google.api_core import exceptions as gexc

from hongthai import assess, config, tracks, wn3report
from hongthai.assess import DEFAULT_GUST_FACTOR, GustFactor
from hongthai.config import Event, Thresholds
from hongthai.sources import wn3
from hongthai.units import KT_PER_MS

RUN = utc(2026, 10, 20, 0)
EV = Event("29W", "CHAMPI（薔琵）", date(2026, 10, 19), date(2026, 10, 28), ("RCTP",))


def _airports(airports, *icaos):
    return [a for a in airports if a.icao in icaos]


# ---- 開關 ----


def test_switches_default_and_env():
    assert config.wn3_mode({}) == "report-only"  # 條款的結論：預設不上網頁
    assert config.wn3_mode({"WN3_MODE": "observe"}) == "observe"
    assert config.wn3_mode({"WN3_MODE": "public"}) == "report-only"  # 不認得 → 預設
    assert config.wn3_voting({}) is False  # 旁觀
    assert config.wn3_voting({"WN3_VOTING": "1"}) is True
    assert config.wn3_voting({"WN3_VOTING": "yes"}) is False
    m = config.WN3_MODEL
    assert (m.id, m.gust_estimated, m.votes_only_high, m.voting) == ("wn3", True, False, False)
    assert set(m.name.values()) == {"Google WeatherNext 3"}
    # 預設 report-only：`MODELS` 沒有 wn3（`latest.json` 完全沒有它）
    assert [x.id for x in config.MODELS][-1] == "wn2-ens"


def test_latest_run_follows_dissemination_schedule():
    # BigQuery 在起報後 8:10 發布、再留 20 分鐘
    assert wn3.latest_run(utc(2026, 10, 20, 8, 29)) == utc(2026, 10, 19, 18)
    assert wn3.latest_run(utc(2026, 10, 20, 8, 30)) == utc(2026, 10, 20, 0)
    assert wn3.lead_window(RUN, utc(2026, 10, 20, 6), utc(2026, 10, 25, 6)) == (6, 126)
    assert wn3.lead_window(RUN, RUN, RUN + timedelta(hours=120)) == (1, 120)  # 統計從 1 小時起
    assert wn3.mslp_leads(1, 120) == list(range(6, 121, 6))
    assert wn3.mslp_leads(8, 20) == [12, 18]


def test_credentials_missing_or_bad():
    with pytest.raises(wn3.Wn3Error) as e:
        wn3.credentials({})
    assert e.value.code == "no_credentials"
    with pytest.raises(wn3.Wn3Error) as e:
        wn3.credentials({"GOOGLE_SERVICE_ACCOUNT_JSON": "{壞的", "GOOGLE_CLOUD_PROJECT": "p"})
    assert e.value.code == "no_credentials" and "壞的" not in str(e.value)
    assert wn3.table_id("proj", {}) == "proj.weathernext_3.weathernext_3_0_0_0p1deg"
    assert wn3.table_id("proj", {"WN3_BQ_TABLE": "a.b.c"}) == "a.b.c"


# ---- BigQuery ----


def _rec(h, p50=10.0, mean=9.0, p90=15.0, u=-9.0, v=0.0, tp=0.001, t2=300.0):
    return {
        "hours": h,
        "wind_speed_10m_p50": p50,
        "wind_speed_10m_mean": mean,
        "wind_speed_10m_p90": p90,
        "u_component_of_wind_10m_mean": u,
        "v_component_of_wind_10m_mean": v,
        "total_precipitation_1hr_mean": tp,
        "temperature_2m_mean": t2,
    }


def _rows(airports, h0, h1, **kw):
    """每個機場兩個格點：最近的一格（照文件的結構）＋ 0.07° 外的一格（風大一倍，不該被選到）。"""
    rows = []
    for a in airports:
        near = round(a.lat, 1), round(a.lon, 1)
        rows.append(
            {"lat": near[0], "lon": near[1], "forecast": [_rec(h, **kw) for h in range(h0, h1 + 1)]}
        )
        far = [_rec(h, p50=20.0) for h in range(h0, h1 + 1)]
        rows.append({"lat": near[0] + 0.07, "lon": near[1], "forecast": far})
    return rows


class FakeJob:
    def __init__(self, rows=(), processed=None, billed=None, error=None):
        self.rows, self.error = list(rows), error
        self.total_bytes_processed, self.total_bytes_billed = processed, billed

    def result(self, timeout=None):
        if self.error is not None:
            raise self.error
        return iter(self.rows)


class FakeClient:
    """`query(sql, job_config)`：dry run 回估計量；真的查回 `rows_by_run[init]`。"""

    def __init__(self, rows_by_run=None, error=None, estimate=5_000_000_000):
        self.rows_by_run = rows_by_run or {}
        self.error, self.estimate = error, estimate
        self.calls = []

    def query(self, sql, job_config=None):
        params = {p.name: p.value for p in job_config.query_parameters}
        self.calls.append((sql, job_config.dry_run, job_config.maximum_bytes_billed, params))
        if self.error is not None:
            raise self.error
        if job_config.dry_run:
            return FakeJob(processed=self.estimate)
        rows = self.rows_by_run.get(params["init"], [])
        return FakeJob(rows, processed=3_100_000_000, billed=3_100_000_000)


def no_zarr(run):
    raise AssertionError("BigQuery 成功時不該讀 Zarr")


def test_build_sql_filters_partition_points_and_columns(airports):
    sql = wn3.build_sql("p.weathernext_3.weathernext_3_0_0_0p1deg", airports[:2])
    assert "FROM `p.weathernext_3.weathernext_3_0_0_0p1deg` AS t" in sql
    assert "WHERE t.init_time = @init" in sql  # 分割欄位
    assert "f.hours BETWEEN @h0 AND @h1" in sql
    a = airports[0]
    assert f"MULTIPOINT(({a.lon:.4f} {a.lat:.4f}), " in sql and ", 8000)" in sql
    for c in wn3.BQ_FIELDS:
        assert f"f.{c}" in sql
    assert "SELECT *" not in sql and "geography_polygon" not in sql  # 只選要的欄位


def test_fetch_bigquery_parses_document_structure(airports):
    aps = _airports(airports, "RCTP", "VHHH")
    client = FakeClient({RUN: _rows(aps, 6, 126)})
    data = wn3.fetch(
        aps, RUN, utc(2026, 10, 20, 6), utc(2026, 10, 25, 6), client=client, open_stats=no_zarr
    )
    assert (data.via, data.run, data.estimate_bytes, data.bytes_billed) == (
        "bigquery",
        RUN,
        5_000_000_000,
        3_100_000_000,
    )
    dry, real = client.calls
    assert dry[1] is True and not real[1]
    assert real[2] == wn3.BQ_MAX_BYTES == 8_000_000_000  # 超過就被 BigQuery 拒絕、不收錢
    assert real[3] == {"init": RUN, "h0": 6, "h1": 126}
    h = data.points["RCTP"][0]
    assert h.valid == utc(2026, 10, 20, 6) and len(data.points["RCTP"]) == 121
    assert h.wind_kt == round(10 * KT_PER_MS, 2)  # p50；遠的那格（20 m/s）沒被選到
    assert (h.wind_mean_kt, h.wind_p90_kt) == (round(9 * KT_PER_MS, 2), round(15 * KT_PER_MS, 2))
    assert h.wdir == 90.0  # u −9、v 0 → 東風
    assert (h.precip_mm, h.temp2m_c) == (1.0, 26.85)  # m → mm、K → °C


def test_fetch_retries_previous_run_when_not_published(airports):
    aps = _airports(airports, "RCTP")
    prev = RUN - timedelta(hours=6)
    client = FakeClient({prev: _rows(aps, 12, 132)})
    data = wn3.fetch(
        aps,
        RUN,
        utc(2026, 10, 20, 6),
        utc(2026, 10, 25, 6),
        retry_previous=True,
        client=client,
        open_stats=no_zarr,
    )
    assert data.run == prev and data.via == "bigquery"
    assert [c[3]["init"] for c in client.calls if not c[1]] == [RUN, prev]


def test_not_approved_403_is_ok_false_not_crash(airports):
    """核准前：BigQuery 403、GCS 也 403 → `Wn3Error("http_403")`（build 記 `ok: false`）。"""
    client = FakeClient(error=gexc.Forbidden("Access Denied: Table p:weathernext_3"))

    def zarr_403(run):
        raise wn3.Wn3Error("GCS 403", "http_403")

    with pytest.raises(wn3.Wn3Error) as e:
        wn3.fetch(
            airports, RUN, RUN, RUN + timedelta(hours=120), client=client, open_stats=zarr_403
        )
    assert e.value.code == "http_403"


def test_bytes_limit_code():
    err = gexc.BadRequest(
        "Query exceeded limit for bytes billed: 8000000000. bytesBilledLimitExceeded"
    )
    assert wn3._bq_code(err) == "bq_bytes_limit"
    assert wn3._bq_code(gexc.NotFound("Not found: Dataset")) == "http_404"


# ---- Zarr（本機造一個同結構的小網格）----


def stats_dataset(tmp_path, leads=range(1, 127), low=(16.0, 135.0)):
    """同統計 Zarr 的維度與變數名：`lead_time`（timedelta）、`lat_0p1`、`lon_0p1`（0–360）；
    風 p50 ＝ 10 m/s（RCTP 那格 12）、海平面氣壓 1010 hPa 加一個低壓（每小時往西 0.1°）。"""
    lats = np.round(np.arange(10.0, 30.01, 0.1), 1)
    lons = np.round(np.arange(115.0, 140.01, 0.1), 1)
    lt = np.array([np.timedelta64(h, "h") for h in leads]).astype("timedelta64[ns]")
    shape = (len(lt), len(lats), len(lons))
    p50 = np.full(shape, 10.0, dtype="float32")
    i, j = int(np.abs(lats - 25.1).argmin()), int(np.abs(lons - 121.2).argmin())
    p50[:, i, j] = 12.0
    msl = np.full(shape, 101000.0, dtype="float32")
    for k, h in enumerate(leads):
        la, lo = low[0], low[1] - 0.1 * h
        msl[k] -= (
            4000 * np.exp(-((lats[:, None] - la) ** 2 + (lons[None, :] - lo) ** 2) / 2)
        ).astype("float32")
    dims = ("lead_time", "lat_0p1", "lon_0p1")
    ds = xr.Dataset(
        {
            "wind_speed_10m_p50": (dims, p50),
            "wind_speed_10m_mean": (dims, p50 - 1),
            "wind_speed_10m_p90": (dims, p50 + 5),
            "u_component_of_wind_10m_mean": (dims, np.full(shape, 0.0, "float32")),
            "v_component_of_wind_10m_mean": (dims, np.full(shape, -9.0, "float32")),
            "mean_sea_level_pressure_mean": (dims, msl),
        },
        coords={"lead_time": lt, "lat_0p1": lats, "lon_0p1": lons},
    )
    path = tmp_path / "predictions.zarr"
    ds.to_zarr(
        path,
        zarr_format=3,
        consolidated=False,
        encoding={v: {"chunks": (1, len(lats), len(lons))} for v in ds},
    )
    return xr.open_zarr(path, chunks=None, consolidated=False)


def test_zarr_fallback_six_hourly_winds_no_rain(tmp_path, airports):
    aps = _airports(airports, "RCTP", "RCKH")
    ds = stats_dataset(tmp_path)
    client = FakeClient(error=gexc.BadRequest("bytesBilledLimitExceeded"))
    opened = []
    data = wn3.fetch(
        aps,
        RUN,
        utc(2026, 10, 20, 6),
        utc(2026, 10, 25, 6),
        mslp=True,
        client=client,
        open_stats=lambda run: opened.append(run) or ds,
    )
    assert (data.via, data.bq_error, opened) == ("zarr", "bq_bytes_limit", [RUN])
    rctp = data.points["RCTP"]
    assert [h.valid for h in rctp] == [
        utc(2026, 10, 20, 6) + timedelta(hours=6 * k) for k in range(21)
    ]
    assert rctp[0].wind_kt == round(12 * KT_PER_MS, 2) and data.points["RCKH"][0].wind_kt == round(
        10 * KT_PER_MS, 2
    )
    assert rctp[0].wdir == 0.0 and rctp[0].precip_mm is None  # 北風；Zarr 備援沒有雨量
    # 一報讀的量（未壓縮、一個 chunk 一整張）：5 個風的變數 × 21 個時間 × 201 × 251 × 4 bytes
    wind = 5 * 21 * 201 * 251 * 4
    assert sorted(data.mslp) == [RUN + timedelta(hours=h) for h in range(6, 127, 6)]
    g = data.mslp[RUN + timedelta(hours=6)]
    assert g.values.min() == pytest.approx(97000, abs=1)
    assert data.bytes_downloaded == wind + 21 * 201 * 251 * 4


def test_zarr_missing_run_retries_previous(tmp_path, airports):
    ds = stats_dataset(tmp_path)
    tried = []

    def open_stats(run):
        tried.append(run)
        if run == RUN:
            raise wn3.Wn3Error("沒有", "zarr_not_found")
        return ds

    client = FakeClient()  # BigQuery 兩報都沒有列
    data = wn3.fetch(
        _airports(airports, "RCTP"),
        RUN,
        utc(2026, 10, 20, 6),
        utc(2026, 10, 25, 0),
        retry_previous=True,
        client=client,
        open_stats=open_stats,
    )
    assert tried == [RUN, RUN - timedelta(hours=6)] and data.run == RUN - timedelta(hours=6)
    assert data.bq_error == "no_rows"


# ---- 每格的數字 ----


def hours(wind=20.0, p90=30.0, rain=1.0, start=RUN, n=127):
    return [
        wn3.Wn3Hour(start + timedelta(hours=h), wind + (h == 9), 19.0, p90 + h % 3, 90.0, rain)
        for h in range(n)
    ]


def test_wn3_for_slot_estimated_gust_no_ptype():
    start, end = RUN + timedelta(hours=6), RUN + timedelta(hours=12)
    f = GustFactor(1.5, "airport30d")
    out = assess.wn3_for_slot(hours(), start, end, (), f)
    assert out["windKt"] == 21.0  # [from, to] 最大（9 時 21 節）
    assert (out["gustKt"], out["gustFactor"], out["gustFactorBasis"]) == (31.5, 1.5, "airport30d")
    assert out["rain6hMm"] == 6.0  # (from, to] 六個小時
    assert out["ptype"] is None and out["visibilityM"] is None  # 不投雪、霧
    assert out["windKtP90"] == 32.0
    empty = assess.wn3_for_slot(None, start, end)
    assert empty["windKt"] is None and empty["windKtP90"] is None and empty["rain6hMm"] is None


def test_model_entry_wn3_has_p90_only_there():
    src = assess.wn3_for_slot(
        hours(wind=35.0, rain=0.0), RUN + timedelta(hours=6), RUN + timedelta(hours=12)
    )
    e = assess.model_entry(config.WN3_MODEL, {}, {}, src, {"wn3": "x"}, Thresholds())
    assert e["id"] == "wn3" and e["run"] == "x"
    assert (e["gustKt"], e["gustEstimated"], e["windKtP90"]) == (50.4, True, 32.0)
    assert e["levels"] == {"wind": "high", "rain": "low", "snow": None, "fog": None}
    other = assess.model_entry(config.MODELS[3], {}, {}, {}, {}, Thresholds())
    assert "windKtP90" not in other


def test_observe_non_voting_wn3_listed_but_not_counted(monkeypatch):
    """旁觀（`voting=False`）：`models[]` 有 wn3 那筆（等級照算），但不算分母、不投票。"""
    monkeypatch.setattr(assess, "MODELS", (*config.MODELS, config.WN3_MODEL))
    slots = assess.assess_slots(
        now=RUN,
        slots=[(RUN, RUN + timedelta(hours=6))],
        thresholds=Thresholds(),
        ec=None,
        gfs=None,
        taf_periods=None,
        warnings=[],
        confirmed=[],
        wn3=hours(wind=40.0),
    )
    m = slots[0]["model"]
    e = m["models"][-1]
    assert e["id"] == "wn3" and e["level"] == "high"
    assert m["vote"]["total"] == 0 and m["level"] is None  # 只有它有資料，但它不投
    monkeypatch.setattr(assess, "MODELS", (*config.MODELS, replace(config.WN3_MODEL, voting=True)))
    m = assess.assess_slots(
        now=RUN,
        slots=[(RUN, RUN + timedelta(hours=6))],
        thresholds=Thresholds(),
        ec=None,
        gfs=None,
        taf_periods=None,
        warnings=[],
        confirmed=[],
        wn3=hours(wind=40.0),
    )[0]["model"]
    assert m["vote"]["total"] == 1 and m["level"] == "high"  # 解凍後 WN3_VOTING=1


# ---- 路徑：通用的找中心函式 ----


def test_grid_field_same_as_grib_reader(tmp_path):
    """GRIB 的三個模式改用 `grid_field` 後結果不變：同一張場直接給陣列也得到一樣的 `Field`。"""
    path = tmp_path / "m.grib2"
    path.write_bytes(mslp_grib("prmsl", (6,), 0.0, {6: (16, 135, 50)}))
    via_grib = tracks.read_mslp([path])[RUN + timedelta(hours=6)]
    ds = xr.open_dataset(path, engine="cfgrib", backend_kwargs={"indexpath": ""})
    direct = tracks.grid_field(ds["latitude"].values, ds["longitude"].values, ds["prmsl"].values)
    np.testing.assert_array_equal(direct.lats, via_grib.lats)
    np.testing.assert_array_equal(direct.lons, via_grib.lons)
    np.testing.assert_array_equal(direct.hpa, via_grib.hpa)


def test_find_track_on_wn3_tenth_degree_grid(tmp_path):
    ds = stats_dataset(tmp_path, leads=range(6, 31, 6))
    grids, _ = wn3.zarr_mslp(ds, RUN, [6, 12, 18, 24, 30])
    data = wn3.Wn3Data(RUN, {}, "zarr", mslp=grids)
    fields = wn3report.grid_fields(data)
    points, stop = tracks.find_track(fields, 16.0, 134.5)
    assert stop == "end"
    assert [(p["lat"], p["lon"]) for p in points] == [
        (16.0, 134.4),
        (16.0, 133.8),
        (16.0, 133.2),
        (16.0, 132.6),
        (16.0, 132.0),
    ]
    assert points[0]["mslpHpa"] == 970.0


def test_build_tracks_with_grids(tmp_path):
    d = tmp_path / "events" / "29W"
    p = d / "position" / "jtwc-2026-10-20.jsonl"
    p.parent.mkdir(parents=True)
    p.write_text(
        json.dumps({"kind": "analysis", "validAt": "2026-10-20T00:00:00Z", "lat": 16, "lon": 135})
        + "\n",
        encoding="utf-8",
    )
    ds = stats_dataset(tmp_path, leads=range(6, 19, 6))
    grids, _ = wn3.zarr_mslp(ds, RUN, [6, 12, 18])
    fields = wn3report.grid_fields(wn3.Wn3Data(RUN, {}, "zarr", mslp=grids))
    res = tracks.build_tracks(tmp_path, [EV], None, {}, tmp_path / "work", {"wn3": (RUN, fields)})
    assert [x.name for x in res.written] == ["20261020T0000Z-wn3.json"]
    doc = json.loads(res.written[0].read_text("utf-8"))
    assert doc["model"] == "wn3" and doc["seed"]["source"] == "jtwc" and len(doc["points"]) == 3


# ---- 事件檔與補報 ----


def test_report_run_is_cc_by_window():
    now = utc(2026, 10, 25, 1, 5)
    run = wn3report.report_run(now)
    assert run == utc(2026, 10, 20, 0)
    assert run + timedelta(hours=120) <= now - timedelta(hours=1)  # 最後一個有效時間也過了 1 小時
    assert wn3report.report_run(utc(2026, 10, 25, 0, 59)) == utc(2026, 10, 19, 18)


def _data(airports, wind=30.0):
    return wn3.Wn3Data(RUN, {a.icao: hours(wind=wind) for a in airports}, "bigquery")


def test_report_doc_and_write_event_files(tmp_path, airports):
    aps = _airports(airports, "RCTP", "VHHH")
    data = _data(aps)
    f = {"RCTP": GustFactor(1.6, "airport30d")}
    res = wn3report.write_event_files(
        tmp_path, [EV], data, aps, f, "report-only", tmp_path / "w", with_tracks=False
    )
    path = tmp_path / "events" / "29W" / "wn3" / "20261020T0000Z.json"
    assert res.written == [path]
    doc = json.loads(path.read_text("utf-8"))
    assert (doc["model"], doc["run"], doc["mode"], doc["via"], doc["license"]) == (
        "wn3",
        "2026-10-20T00:00:00Z",
        "report-only",
        "bigquery",
        "CC BY 4.0",
    )
    assert "Google LLC" in doc["attribution"]
    rows = doc["airports"]["RCTP"]
    assert len(rows) == 20 and rows[0]["from"] == "2026-10-20T00:00:00Z"
    assert [r["leadHours"] for r in rows[:2]] == [6, 12]
    assert (rows[1]["windKt"], rows[1]["gustKt"], rows[1]["gustFactor"]) == (31.0, 49.6, 1.6)
    assert rows[1]["windKtP90"] == 32.0 and rows[1]["ptype"] is None and rows[1]["level"] == "high"
    assert doc["airports"]["VHHH"][1]["gustFactorBasis"] == "default"
    # 再寫一次跳過
    again = wn3report.write_event_files(
        tmp_path, [EV], data, aps, f, "report-only", tmp_path / "w", with_tracks=False
    )
    assert again.written == [] and again.skipped == 1
    observe = wn3report.report_doc(data, aps, f, "observe")
    assert (
        observe["license"] == wn3.TERMS_URL and "experimental modelling" in observe["attribution"]
    )


def test_write_event_files_tracks_need_seed_and_mslp(tmp_path, airports, monkeypatch):
    """`report-only` 的路徑在這裡抽：沒有起點 → 跳過（不算失敗）；有起點但沒讀到氣壓 → 失敗；
    兩種情況事件檔都照寫。"""
    monkeypatch.setattr(tracks, "Downloads", lambda workdir: _NoTf(workdir))
    aps = _airports(airports, "RCTP")
    res = wn3report.write_event_files(tmp_path, [EV], _data(aps), aps, {}, "report-only", tmp_path)
    assert [p.name for p in res.written] == ["20261020T0000Z.json"] and res.failed == []
    p = tmp_path / "events" / "29W" / "position" / "jtwc-2026-10-20.jsonl"
    p.parent.mkdir(parents=True)
    p.write_text(
        json.dumps({"kind": "analysis", "validAt": "2026-10-20T00:00:00Z", "lat": 16, "lon": 135})
        + "\n",
        encoding="utf-8",
    )
    res = wn3report.write_event_files(tmp_path, [EV], _data(aps), aps, {}, "report-only", tmp_path)
    assert res.failed == ["wn3@2026-10-20T00:00:00Z"] and res.skipped == 1


def test_event_runs_taipei_dates():
    runs = wn3report.event_runs(EV, utc(2026, 10, 1), utc(2026, 10, 20, 0))
    # 10/19 台灣 00:00 ＝ 10/18 16Z → 第一個主報 10/18 18Z
    assert runs[0] == utc(2026, 10, 18, 18) and runs[-1] == utc(2026, 10, 20, 0)
    assert len(runs) == 6
    end = wn3report.event_runs(EV, utc(2026, 10, 1), utc(2026, 11, 30))
    assert end[-1] == utc(2026, 10, 28, 12)  # 10/28 台灣 24:00 ＝ 10/28 16Z


def test_backfill_writes_and_stops_when_not_approved(tmp_path, airports, monkeypatch):
    aps = _airports(airports, "RCTP")
    monkeypatch.setattr(tracks, "Downloads", lambda workdir: _NoTf(workdir))
    asked = []

    def fetch(airports, run, start, end, mslp=False):
        asked.append((run, start, end, mslp))
        return replace(_data(aps), run=run)

    now = utc(2026, 10, 25, 1, 5)
    out = wn3report.backfill(tmp_path, [EV], aps, utc(2026, 10, 19, 12), now, tmp_path / "w", fetch)
    res = out["29W"]
    assert [a[0] for a in asked] == [utc(2026, 10, 19, 12), utc(2026, 10, 19, 18), RUN]
    assert asked[0][1:] == (utc(2026, 10, 19, 12), utc(2026, 10, 24, 12), True)
    assert len([p for p in res.written if p.parent.name == "wn3"]) == 3
    # 第二次：事件檔都有，但沒有起點所以路徑檔沒寫 → 照樣再試（不跳過）
    asked.clear()

    def denied(*a, **k):
        asked.append(a[1])
        raise wn3.Wn3Error("403", "http_403")

    out = wn3report.backfill(
        tmp_path, [EV], aps, utc(2026, 10, 19, 12), now, tmp_path / "w", denied
    )
    assert len(asked) == 1 and out["29W"].failed == ["wn3@2026-10-19T12:00:00Z"]


class _NoTf(tracks.Downloads):
    def tf(self, stream, run):
        raise tracks.TracksError("測試不連網", "tf_failed")


def test_saved_factors(tmp_path):
    assert wn3report.saved_factors(tmp_path) == {}
    p = tmp_path / "gustfactor" / "latest.json"
    p.parent.mkdir()
    p.write_text(json.dumps({"airports": {"RCTP": {"g": 1.9, "basis": "airport30d"}}}), "utf-8")
    assert wn3report.saved_factors(tmp_path) == {"RCTP": GustFactor(1.9, "airport30d")}
    assert DEFAULT_GUST_FACTOR.g == 1.4


def test_env_switches_at_import():
    """`MODELS` 在載入時看環境變數：`WN3_MODE=observe` 才有 wn3，`WN3_VOTING=1` 才投票。"""
    import os
    import subprocess
    import sys

    from conftest import ROOT

    code = "from hongthai.config import MODELS; m = MODELS[-1]; print(len(MODELS), m.id, m.voting)"

    def run(**env):
        base = {k: v for k, v in os.environ.items() if not k.startswith("WN3_")}
        base["PYTHONPATH"] = str(ROOT / "src")
        out = subprocess.run(
            [sys.executable, "-c", code], env={**base, **env}, capture_output=True, text=True
        )
        return out.stdout.split()

    assert run() == ["8", "wn2-ens", "True"]
    assert run(WN3_MODE="observe") == ["9", "wn3", "False"]
    assert run(WN3_MODE="observe", WN3_VOTING="1") == ["9", "wn3", "True"]


def test_budget_and_workflow_timeout():
    """HD15 加 wn3 120 秒：總和 1785 秒；HD29 加 swic 45 秒，總和 1830 秒（30.5 分鐘）；HD34 加
    cwaTyphoon 15＋jmaTyphoon 20 秒，總和 1865 秒（約 31.1 分鐘），`build.yml` 那一步 32 分鐘、
    job 42 分鐘不用改。"""
    from conftest import ROOT

    from hongthai import build

    assert build.BUDGET_S["wn3"] == 120 and build.BUDGET_S["swic"] == 45
    assert (build.BUDGET_S["cwaTyphoon"], build.BUDGET_S["jmaTyphoon"]) == (15, 20)
    assert sum(build.BUDGET_S.values()) == 1865
    yml = (ROOT / ".github" / "workflows" / "build.yml").read_text("utf-8")
    assert "timeout-minutes: 32" in yml and "timeout-minutes: 42" in yml
    assert sum(build.BUDGET_S.values()) / 60 < 32
