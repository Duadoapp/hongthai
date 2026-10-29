"""遠期關注（HD42）：三套系集第 6–15 天的成員比例（`longrange.py`、`sources/gefs.py`、
`ecmwf.fetch_longrange`、`openmeteo.fetch_longrange`）。

GEFS 用 eccodes 現做的 10° 小 GRIB 與假的 S3（`.idx`＋`Range`）；ECMWF 用既有的系集機率 fixture
（`ecmwf_ep_subregion.grib2`，2026-10-17 12Z 的 `0-24`／`12-36`／`24-48`）；WN2 用既有的系集 fixture
（`openmeteo_ensemble_3x8.json`，3 個機場 × 8 個成員）。都不連網。
"""

from __future__ import annotations

import json
import threading
from datetime import date, timedelta
from pathlib import Path

import pytest
from conftest import FIXTURES, load_json, utc

from hongthai import build, longrange
from hongthai.sources import ecmwf, gefs, gfs, openmeteo
from hongthai.sources.ecmwf import ProbWindow
from hongthai.sources.gefs import MemberPoint
from hongthai.sources.openmeteo import EnsStep
from hongthai.units import ms_to_kt

BASE = utc(2026, 10, 27)
ICAOS = ["RCTP", "ROIG", "RJCC"]  # openmeteo_ensemble_3x8.json 的順序


# ---- 窗與基準日 ----


def test_base_and_windows():
    assert longrange.base_of(utc(2026, 10, 27, 11, 47)) == BASE  # 排程：當天 00Z
    assert longrange.base_of(utc(2026, 10, 27, 3)) == utc(2026, 10, 26)  # 半夜手動：前一天
    wins = longrange.windows_of(BASE)
    assert len(wins) == 10
    assert wins[0] == (utc(2026, 11, 1), utc(2026, 11, 2))  # 第 6 天＝提前 120–144 小時
    assert wins[-1] == (utc(2026, 11, 10), utc(2026, 11, 11))  # 第 15 天＝提前 336–360 小時
    assert all(b - a == timedelta(hours=24) for a, b in wins)


def test_ecmwf_window_steps_align_to_run():
    wins = longrange.windows_of(BASE)
    assert ecmwf.window_steps(BASE, wins) == [f"{h}-{h + 24}" for h in range(120, 337, 24)]
    # 前一天 12Z 那報：步長多 12 小時，最後一個窗（372 小時）超過 360 → 少一個
    prev12 = ecmwf.window_steps(utc(2026, 10, 26, 12), wins)
    assert (prev12[0], prev12[-1], len(prev12)) == ("132-156", "324-348", 9)
    # 06Z 不是系集機率產品的時次：窗的開始不在 12 小時的格上 → 一個都沒有
    assert ecmwf.window_steps(utc(2026, 10, 26, 6), wins) == []


def test_gefs_steps_include_both_ends():
    wins = longrange.windows_of(BASE)
    steps = gefs.steps_for(BASE, wins)
    assert steps == list(range(120, 361, 6))  # 41 個步長 × 31 個成員 ＝ 1,271 個檔
    assert len(steps) * len(gefs.MEMBERS) == 1271
    assert gefs.steps_for(utc(2026, 10, 26, 18), wins[-1:]) == [342, 348, 354, 360, 366]
    assert gefs.steps_for(utc(2026, 10, 26, 0), wins[-1:]) == [360, 366, 372, 378, 384]


# ---- 比例 ----


def test_share_thresholds_are_ecmwf_ms():
    """門檻是 25／15 m/s（48.6／29.2 節），陣風一位小數後比。"""
    assert longrange.THRESHOLDS_KT == {"p29": 29.2, "p49": 48.6}
    assert longrange._share([48.6, 48.5, 29.2, 29.1]) == {"p29": 0.75, "p49": 0.25, "members": 4}


def test_ifs_entry_matches_window():
    ws = [ProbWindow(utc(2026, 11, 1), utc(2026, 11, 2), 0.9, 0.4314, 0.0784)]
    assert longrange.ifs_entry(ws, utc(2026, 11, 1), utc(2026, 11, 2)) == {
        "p29": 0.43,
        "p49": 0.08,
        "members": 51,
    }
    assert longrange.ifs_entry(ws, utc(2026, 11, 2), utc(2026, 11, 3)) is None
    assert longrange.ifs_entry(None, utc(2026, 11, 1), utc(2026, 11, 2)) is None


def test_gefs_entry_member_max_and_estimated():
    a, b = utc(2026, 11, 1), utc(2026, 11, 2)
    members = [
        [MemberPoint(a, 50.0), MemberPoint(b, 10.0)],  # 頭（00Z）算
        [MemberPoint(a + timedelta(hours=6), 30.0, estimated=True)],
        [MemberPoint(b + timedelta(hours=6), 99.0)],  # 窗外不算 → 沒有值，不算分母
        [MemberPoint(b, None)],
    ]
    assert longrange.gefs_entry(members, a, b) == {
        "p29": 1.0,
        "p49": 0.5,
        "members": 2,
        "estimated": True,
    }
    assert longrange.gefs_entry([[], []], a, b) is None


def test_wn2_entry_estimated_with_g():
    a, b = utc(2026, 11, 1), utc(2026, 11, 2)
    steps = [
        EnsStep(a, (20.0, 10.0, None)),
        EnsStep(a + timedelta(hours=12), (24.3, 15.0, None)),
        EnsStep(b, (10.0, 20.0, None)),
        EnsStep(b + timedelta(hours=6), (99.0, 99.0, 99.0)),  # 窗外
    ]
    # 成員最大：24.3、20.0；× 2.0 ＝ 48.6、40.0；第三個成員窗內沒有值、不算分母
    assert longrange.wn2_entry(steps, a, b, 2.0) == {
        "p29": 1.0,
        "p49": 0.5,
        "members": 2,
        "estimated": True,
    }
    assert longrange.wn2_entry([], a, b, 2.0) is None


# ---- 歐洲系集 ----


class FakeEcmwfClient:
    def __init__(self, source, calls):
        self.source, self.calls = source, calls

    def latest(self, **request):
        self.calls.append(("latest", self.source, request))
        return utc(2026, 10, 17, 12).replace(tzinfo=None)

    def retrieve(self, target, **request):
        self.calls.append(("retrieve", self.source, request))
        Path(target).write_bytes((FIXTURES / "ecmwf_ep_subregion.grib2").read_bytes())


def test_ecmwf_fetch_longrange(monkeypatch, airports, tmp_path):
    calls = []
    monkeypatch.setattr(ecmwf, "_client", lambda source, **retry: FakeEcmwfClient(source, calls))
    wins = [(utc(2026, 10, 18), utc(2026, 10, 19)), (utc(2026, 10, 19), utc(2026, 10, 20))]
    data = ecmwf.fetch_longrange(airports, wins, tmp_path)
    latest = calls[0]
    assert latest[2] == {"stream": "enfo", "type": "ep", "param": "10fgg25", "step": "336-360"}
    req = calls[1][2]
    assert (calls[1][1], req["param"], req["step"]) == (
        "aws",
        ["10fgg15", "10fgg25"],
        ["12-36", "36-60"],
    )
    assert (req["date"], req["time"]) == ("20261017", 12)
    assert data.run == utc(2026, 10, 17, 12) and data.mirror == "aws"
    _, parsed = ecmwf.parse_ens(FIXTURES / "ecmwf_ep_subregion.grib2", airports)
    want = next(w for w in parsed["RCTP"] if w.start == wins[0][0])
    got = longrange.ifs_entry(data.points["RCTP"], *wins[0])
    assert got == {"p29": round(want.p15, 2), "p49": round(want.p25, 2), "members": 51}
    assert longrange.ifs_entry(data.points["RCTP"], *wins[1]) is None  # fixture 沒有 36-60


# ---- GEFS（假的 S3）----


def _grib(run, fh: int, short: str, value: float) -> bytes:
    """10° 全球、整個場同一個值的 GRIB2（eccodes 現做）。"""
    import eccodes
    import numpy as np

    h = eccodes.codes_grib_new_from_samples("regular_ll_sfc_grib2")
    for k, v in (
        ("Ni", 36),
        ("Nj", 19),
        ("latitudeOfFirstGridPointInDegrees", 90.0),
        ("longitudeOfFirstGridPointInDegrees", 0.0),
        ("latitudeOfLastGridPointInDegrees", -90.0),
        ("longitudeOfLastGridPointInDegrees", 350.0),
        ("iDirectionIncrementInDegrees", 10.0),
        ("jDirectionIncrementInDegrees", 10.0),
        ("dataDate", int(run.strftime("%Y%m%d"))),
        ("dataTime", run.hour * 100),
        ("shortName", short),
        ("step", fh),
        ("bitsPerValue", 16),
    ):
        eccodes.codes_set(h, k, v)
    eccodes.codes_set_values(h, np.full(36 * 19, value))
    out = eccodes.codes_get_message(h)
    eccodes.codes_release(h)
    return out


IDX_NAMES = {
    "2t": ("TMP", "2 m above ground"),
    "gust": ("GUST", "surface"),
    "10u": ("UGRD", "10 m above ground"),
    "10v": ("VGRD", "10 m above ground"),
    "hgt": ("HGT", "1 mb"),
}


def _file(run, fh: int, member: str, fields: list[tuple[str, float]]) -> tuple[bytes, str]:
    """幾筆接成一個檔，配上 NOAA 格式的 `.idx`。"""
    body, lines = b"", []
    for n, (short, value) in enumerate(fields, 1):
        var, lev = IDX_NAMES[short]
        lines.append(f"{n}:{len(body)}:d={run:%Y%m%d%H}:{var}:{lev}:{fh} hour fcst:ENS={member}")
        body += _grib(run, fh, "2t" if short == "hgt" else short, value)
    return body, "\n".join(lines) + "\n"


class FakeS3:
    def __init__(self):
        self.files: dict[str, bytes] = {}
        self.requests: list[tuple[str, str | None]] = []

    def put(self, url: str, body: bytes, idx: str):
        self.files[url] = body
        self.files[f"{url}.idx"] = idx.encode()

    def get(self, url, *, headers=None, ok_404=False, error=gefs.GefsError, **kw):
        rng = (headers or {}).get("Range")
        self.requests.append((url, rng))
        if url not in self.files:
            if ok_404:
                return _Resp(404, b"")
            raise error(f"{url}: HTTP 404", "http_404")
        body = self.files[url]
        if rng is None:
            return _Resp(200, body)
        a, b = rng.removeprefix("bytes=").split("-")
        return _Resp(206, body[int(a) : int(b) + 1 if b else None])


class _Resp:
    def __init__(self, status: int, content: bytes):
        self.status_code, self.content = status, content

    @property
    def text(self) -> str:
        return self.content.decode()


def gefs_s3(monkeypatch, run, steps, value=lambda i, fh: 5.0, skip=(), no_gust=()):
    s3 = FakeS3()
    for i, m in enumerate(gefs.MEMBERS):
        for fh in steps:
            if (m, fh) in skip:
                continue
            if (m, fh) in no_gust:  # b 檔沒有陣風 → a 檔的 10 米風
                s3.put(gefs.file_url(run, m, fh), *_file(run, fh, m, [("2t", 280.0), ("hgt", 1.0)]))
                s3.put(
                    gefs.file_url(run, m, fh, "a"), *_file(run, fh, m, [("10u", 3.0), ("10v", 4.0)])
                )
                continue
            fields = [("2t", 280.0), ("gust", value(i, fh)), ("hgt", 1.0)]
            s3.put(gefs.file_url(run, m, fh), *_file(run, fh, m, fields))
    monkeypatch.setattr(gefs, "http_get", s3.get)
    monkeypatch.setattr(gfs, "http_get", s3.get)  # `download_ranges` 在 gfs.py
    return s3


def test_gefs_fetch_falls_back_a_run_and_counts_members(monkeypatch, airports, tmp_path):
    """基準日 00Z 還沒出 → 用前一報 18Z；成員 i 在 f354 的陣風 20 + 0.5i m/s，其他 5 m/s。"""
    run = utc(2026, 10, 26, 18)
    wins = longrange.windows_of(BASE)[-1:]
    steps = gefs.steps_for(run, wins)
    s3 = gefs_s3(monkeypatch, run, steps, lambda i, fh: 20 + 0.5 * i if fh == 354 else 5.0)
    aps = [a for a in airports if a.icao in ICAOS]
    data = gefs.fetch(aps, BASE, wins, tmp_path, workers=4)
    assert data.run == run and data.steps == [342, 348, 354, 360, 366]
    assert (data.files, data.missing, data.estimated) == (155, 0, False)
    # 找最新一報：00Z f360 沒有、18Z f366 有（控制與最後一個擾動成員都看）
    heads = [u for u, r in s3.requests if u.endswith(".idx") and r is None][:3]
    assert heads == [
        f"{gefs.file_url(BASE, 'gec00', 360)}.idx",
        f"{gefs.file_url(run, 'gec00', 366)}.idx",
        f"{gefs.file_url(run, 'gep30', 366)}.idx",
    ]
    # `.idx` 只抓前段（Range），陣風那一筆一個 Range
    ranged = [r for u, r in s3.requests if r is not None]
    assert ranged.count(f"bytes=0-{gefs.IDX_HEAD_BYTES - 1}") == 155
    pts = data.points["RCTP"]
    assert len(pts) == 31 and all(len(m) == 5 for m in pts)
    assert pts[10][2] == MemberPoint(utc(2026, 11, 10, 12), pytest.approx(ms_to_kt(25.0)))
    # 25 m/s 剛好 48.6 節（一位小數）→ 成員 10–30 共 21 個達 49 節門檻；15 m/s 以上 31 個全部
    entry = longrange.gefs_entry(pts, *wins[0])
    assert entry == {"p29": 1.0, "p49": round(21 / 31, 2), "members": 31, "estimated": False}


def test_gefs_full_idx_when_head_is_short(monkeypatch, airports, tmp_path):
    """`.idx` 前段沒有 GUST 的下一筆（算不出結束位置）→ 再抓整個 `.idx`。"""
    monkeypatch.setattr(gefs, "IDX_HEAD_BYTES", 120)  # 只到第二行中間
    wins = longrange.windows_of(BASE)[-1:]
    steps = gefs.steps_for(BASE, wins)
    s3 = gefs_s3(monkeypatch, BASE, steps)
    aps = [a for a in airports if a.icao == "RCTP"]
    data = gefs.fetch(aps, BASE, wins, tmp_path, workers=4)
    assert data.missing == 0
    full = [u for u, r in s3.requests if u.endswith(".idx") and r is None]
    assert len(full) == 2 + 155  # find_run 兩個＋每個檔一次整個 `.idx`
    assert longrange.gefs_entry(data.points["RCTP"], *wins[0])["p29"] == 0.0


def test_gefs_no_gust_uses_wind_times_g(monkeypatch, airports, tmp_path):
    """b 檔沒有 GUST → a 檔的 10 米風（3, 4 m/s → 5 m/s ≈ 9.7 節）× G，記 `estimated`。"""
    wins = longrange.windows_of(BASE)[-1:]
    steps = gefs.steps_for(BASE, wins)
    gefs_s3(monkeypatch, BASE, steps, no_gust={("gep01", 360)})
    aps = [a for a in airports if a.icao == "RCTP"]
    data = gefs.fetch(aps, BASE, wins, tmp_path, gust_factors={"RCTP": 2.0}, workers=4)
    assert data.estimated is True
    p = data.points["RCTP"][1][-1]
    assert p.estimated and p.gust_kt == pytest.approx(ms_to_kt(5.0) * 2.0)
    entry = longrange.gefs_entry(data.points["RCTP"], *wins[0])
    assert entry["estimated"] is True and entry["members"] == 31


def test_gefs_missing_files_tolerated_until_limit(monkeypatch, airports, tmp_path):
    wins = longrange.windows_of(BASE)[-1:]
    steps = gefs.steps_for(BASE, wins)
    gefs_s3(monkeypatch, BASE, steps, skip={("gep05", 348), ("gep06", 354)})
    aps = [a for a in airports if a.icao == "RCTP"]
    data = gefs.fetch(aps, BASE, wins, tmp_path, workers=4)
    assert (data.files, data.missing) == (153, 2)
    assert len(data.points["RCTP"][5]) == 4
    # 超過一成抓不到 → 整套失敗
    gefs_s3(monkeypatch, BASE, steps, skip={(m, fh) for m in gefs.MEMBERS[1:5] for fh in steps})
    with pytest.raises(gefs.GefsError) as e:  # 20 個 > 155 的一成
        gefs.fetch(aps, BASE, wins, tmp_path / "2", workers=4)
    assert e.value.code == "partial"


def test_gefs_head_drops_partial_line():
    assert gefs._head("1:0:a\n2:5:b\n3:9") == "1:0:a\n2:5:b\n"
    assert gefs._head("1:0:a\n") == "1:0:a\n"


# ---- WN2 系集 ----


def test_openmeteo_longrange_request_and_calls(monkeypatch, airports):
    asked = []

    class R:
        def __init__(self, doc):
            self.doc, self.content = doc, b"x" * 1000

        def json(self):
            return self.doc

    def fake_get(url, **kw):
        asked.append((url, kw))
        if url == openmeteo.ENSEMBLE_URL:
            return R(load_json("openmeteo_ensemble_3x8.json"))
        return R({"last_run_initialisation_time": 1793059200})  # 2026-10-27T00:00Z

    monkeypatch.setattr(openmeteo, "http_get", fake_get)
    aps = [a for a in airports if a.icao in ICAOS]
    aps.sort(key=lambda a: ICAOS.index(a.icao))
    data = openmeteo.fetch_longrange(aps, date(2026, 11, 1), date(2026, 11, 11))
    params = asked[0][1]["params"]
    assert params["start_date"] == "2026-11-01" and params["end_date"] == "2026-11-11"
    assert "forecast_days" not in params
    assert (params["models"], params["hourly"]) == (
        "google_weathernext2_ensemble",
        "wind_speed_10m",
    )
    assert asked[1][0] == openmeteo.META_URLS["wn2-ens"]
    assert data.run == utc(2026, 10, 27) and data.members == 8
    assert data.calls == openmeteo.longrange_calls(3, date(2026, 11, 1), date(2026, 11, 11))
    # fixture 的 10/21 00Z–10/22 00Z：RCTP 8 個成員的最大風 × G 2.0
    entry = longrange.wn2_entry(data.ensemble["RCTP"], utc(2026, 10, 21), utc(2026, 10, 22), 2.0)
    assert entry["members"] == 8 and entry["estimated"] is True
    winds = openmeteo.member_winds(
        [s for s in data.ensemble["RCTP"] if utc(2026, 10, 21) <= s.valid <= utc(2026, 10, 22)]
    )
    want = sum(round(round(w, 1) * 2.0, 1) >= 48.6 for w in winds) / 8
    assert entry["p49"] == round(want, 2)


def test_openmeteo_usage_budget():
    """一天一次 326.4 次（11 天沒超過 14 天，和 6 天一樣算）；加上 build 每天 4 報仍遠低於
    每日 5,000。"""
    n = 51
    one = openmeteo.longrange_calls(n, date(2026, 11, 1), date(2026, 11, 11))
    assert one == 326.4 < 600  # 單一請求也在每分鐘上限內
    per_build = openmeteo.forecast_calls(n) + openmeteo.ensemble_calls(n)
    assert round(per_build, 1) == 504.9
    assert round(4 * per_build + one, 1) == 2346.0 < 5000
    # 對照：用 forecast_days=15 抓整段會是 349.7 次
    assert openmeteo.weighted_calls(1, 64, 15, n) == 349.7


# ---- 組合、失敗與沿用 ----


def _fake_results(airports):
    run = BASE
    wins = longrange.windows_of(BASE)
    ifs = ecmwf.LongRangeData(
        run,
        {a.icao: [ProbWindow(s, e, None, 0.5, 0.25) for s, e in wins] for a in airports},
        100,
        "aws",
    )
    pts = [[MemberPoint(s + timedelta(hours=6), 30.0) for s, _ in wins] for _ in range(31)]
    gf = gefs.GefsData(run, {a.icao: pts for a in airports}, 200, 1271, 0, False, [])
    steps = [EnsStep(s + timedelta(hours=6), (10.0,) * 64) for s, _ in wins]
    wn2 = openmeteo.LongRangeEnsemble(run, {a.icao: steps for a in airports}, 64, 300, 326.4)
    return ifs, gf, wn2


def patch_sources(monkeypatch, airports, fail=()):
    ifs, gf, wn2 = _fake_results(airports)

    def maybe(name, value):
        def fn(*a, **k):
            if name in fail:
                raise ecmwf.EcmwfError("down", "http_503")
            return value

        return fn

    monkeypatch.setattr(ecmwf, "fetch_longrange", maybe("ifsEns", ifs))
    monkeypatch.setattr(gefs, "fetch", maybe("gefs", gf))
    monkeypatch.setattr(openmeteo, "fetch_longrange", maybe("wn2Ens", wn2))


def test_run_one_source_fails_others_still_out(monkeypatch, airports, tmp_path):
    patch_sources(monkeypatch, airports, fail={"gefs"})
    doc = longrange.run(utc(2026, 10, 27, 11, 47), tmp_path, airports, tmp_path)
    assert doc["schema"] == 1 and doc["stale"] is False and doc["base"] == "2026-10-27"
    assert doc["runs"] == {
        "ifsEns": "2026-10-27T00:00:00Z",
        "gefs": None,
        "wn2Ens": "2026-10-27T00:00:00Z",
    }
    assert doc["sources"]["gefs"]["ok"] is False and doc["sources"]["gefs"]["error"] == "http_503"
    assert doc["sources"]["ifsEns"]["ok"] is True and doc["sources"]["wn2Ens"]["calls"] == 326.4
    assert [w["day"] for w in doc["windows"]] == list(range(6, 16))
    assert set(doc["airports"]) == {a.icao for a in airports} and len(doc["airports"]) == 51
    row = doc["airports"]["RCTP"][0]
    assert row["from"] == "2026-11-01T00:00:00Z" and row["to"] == "2026-11-02T00:00:00Z"
    assert row["ifsEns"] == {"p29": 0.5, "p49": 0.25, "members": 51}
    assert row["gefs"] is None
    # 沒有陣風係數檔 → G 用預設 1.4：10 節 × 1.4 ＝ 14 節，沒到 29.2
    assert row["wn2Ens"] == {"p29": 0.0, "p49": 0.0, "members": 64, "estimated": True}
    assert doc["gustFactor"]["airports"]["RCTP"] == 1.4
    assert all(r["gefs"] is None for rows in doc["airports"].values() for r in rows)


def test_run_uses_gust_factor_file(monkeypatch, airports, tmp_path):
    patch_sources(monkeypatch, airports)
    gdir = tmp_path / "history" / "gustfactor"
    gdir.mkdir(parents=True)
    gdir.joinpath("latest.json").write_text(
        json.dumps({"generatedAt": "2026-10-27T08:25:00Z", "airports": {"RCTP": {"g": 3.0}}})
    )
    doc = longrange.run(utc(2026, 10, 27, 11, 47), tmp_path, airports, tmp_path)
    assert doc["gustFactor"]["generatedAt"] == "2026-10-27T08:25:00Z"
    assert doc["gustFactor"]["airports"]["RCTP"] == 3.0
    assert doc["airports"]["RCTP"][0]["wn2Ens"]["p29"] == 1.0  # 10 × 3.0 ＝ 30 節
    assert doc["airports"]["RCSS"][0]["wn2Ens"]["p29"] == 0.0  # 沒有 → 1.4
    assert doc["airports"]["RCTP"][0]["gefs"] == {
        "p29": 1.0,
        "p49": 0.0,
        "members": 31,
        "estimated": False,
    }


def test_gefs_gets_default_g_without_factor_file(monkeypatch, airports, tmp_path):
    """b 檔沒有陣風時的估算也用 G：沒有陣風係數檔的機場給 1.4，不是 None。"""
    patch_sources(monkeypatch, airports)
    got = {}
    real = gefs.fetch

    def spy(aps, latest, wins, workdir, g):
        got.update(g)
        return real(aps, latest, wins, workdir, g)

    monkeypatch.setattr(gefs, "fetch", spy)
    longrange.run(utc(2026, 10, 27, 11, 47), tmp_path, airports, tmp_path)
    assert len(got) == 51 and set(got.values()) == {1.4}


def test_source_timeout_recorded(monkeypatch, airports, tmp_path):
    patch_sources(monkeypatch, airports)
    release = threading.Event()

    def slow(*a, **k):
        release.wait(5)

    monkeypatch.setattr(gefs, "fetch", slow)
    monkeypatch.setitem(longrange.BUDGET_S, "gefs", 0.1)
    doc = longrange.run(utc(2026, 10, 27, 11, 47), tmp_path, airports, tmp_path)
    release.set()
    assert doc["sources"]["gefs"]["error"] == "timeout"
    assert doc["airports"]["RCTP"][0]["gefs"] is None


def test_main_writes_latest_and_history(monkeypatch, airports, tmp_path):
    patch_sources(monkeypatch, airports)
    monkeypatch.setattr(longrange, "utcnow", lambda: utc(2026, 10, 27, 11, 47, 30))
    archive = tmp_path / "data"
    assert longrange.main(["--archive", str(archive), "--airports", str(_airports_json())]) == 0
    doc = json.loads((archive / "longrange.json").read_text("utf-8"))
    hist = json.loads((archive / "history" / "longrange" / "2026-10-27.json").read_text("utf-8"))
    assert doc == hist and doc["generatedAt"] == "2026-10-27T11:47:00Z"
    assert not (archive / "latest.json").exists()  # 不碰 latest.json


def _airports_json() -> Path:
    return Path(__file__).parent.parent / "airports.json"


def test_all_fail_reuses_previous_as_stale(monkeypatch, airports, tmp_path):
    patch_sources(monkeypatch, airports, fail={"ifsEns", "gefs", "wn2Ens"})
    monkeypatch.setattr(longrange, "utcnow", lambda: utc(2026, 10, 28, 11, 47))
    archive = tmp_path / "data"
    archive.mkdir()
    prev = {"schema": 1, "generatedAt": "2026-10-27T11:47:00Z", "stale": False, "airports": {}}
    (archive / "longrange.json").write_text(json.dumps(prev), "utf-8")
    assert longrange.main(["--archive", str(archive), "--airports", str(_airports_json())]) == 1
    doc = json.loads((archive / "longrange.json").read_text("utf-8"))
    assert doc["stale"] is True and doc["staleAt"] == "2026-10-28T11:47:00Z"
    assert doc["generatedAt"] == "2026-10-27T11:47:00Z"  # 內容是上一份的
    assert doc["staleErrors"] == {"ifsEns": "http_503", "gefs": "http_503", "wn2Ens": "http_503"}
    assert not (archive / "history").exists()  # 沿用的不進歷史


@pytest.mark.parametrize(
    ("prev", "skipped"),
    [
        ({"base": "2026-10-29", "stale": False}, True),  # 這個基準日出過：跳過
        ({"base": "2026-10-29", "stale": True}, False),  # 出過但是沿用的：重跑
        ({"base": "2026-10-28", "stale": False}, False),  # 前一天的：照跑
        (None, False),  # 沒有檔：照跑
    ],
)
def test_skip_done(monkeypatch, tmp_path, prev, skipped):
    calls = []

    def fake_run(*a, **k):
        calls.append(1)
        raise KeyError("不該跑到這裡就停")

    monkeypatch.setattr(longrange, "run", fake_run)
    monkeypatch.setattr(longrange, "utcnow", lambda: utc(2026, 10, 29, 16, 56))

    def offline(url, **k):
        raise longrange.requests.ConnectionError("測試不連網")

    monkeypatch.setattr(longrange.requests, "get", offline)
    archive = tmp_path / "data"
    archive.mkdir()
    if prev is not None:
        (archive / "longrange.json").write_text(json.dumps({"schema": 1, **prev}), "utf-8")
    before = (archive / "longrange.json").read_bytes() if prev is not None else None
    code = longrange.main(["--archive", str(archive), "--skip-done"])
    assert (calls == []) is skipped
    if skipped:
        assert code == 0
        assert (archive / "longrange.json").read_bytes() == before  # 一個字都不動
    # 沒加 --skip-done 一律照跑
    calls.clear()
    longrange.main(["--archive", str(archive)])
    assert calls == [1]


def test_crash_reuses_previous_from_pages(monkeypatch, airports, tmp_path):
    def broken(*a, **k):
        raise KeyError("bug")

    monkeypatch.setattr(longrange, "run", broken)
    monkeypatch.setattr(longrange, "utcnow", lambda: utc(2026, 10, 28, 11, 47))

    class R:
        def raise_for_status(self):
            pass

        def json(self):
            return {"schema": 1, "generatedAt": "2026-10-26T11:47:00Z", "stale": False}

    asked = []
    monkeypatch.setattr(longrange.requests, "get", lambda url, **k: asked.append(url) or R())
    archive = tmp_path / "data"
    assert longrange.main(["--archive", str(archive)]) == 1
    assert asked == [longrange.PAGES_URL]
    doc = json.loads((archive / "longrange.json").read_text("utf-8"))
    assert doc["stale"] is True and doc["staleErrors"] == {"all": "KeyError"}

    def offline(url, **k):
        raise longrange.requests.ConnectionError("測試不連網")

    monkeypatch.setattr(longrange.requests, "get", offline)
    empty = tmp_path / "empty"
    assert longrange.main(["--archive", str(empty)]) == 2  # 沒有上一份：什麼都不寫
    assert not empty.exists()


def test_gefs_get_lines_filtered():
    f = longrange._QuietGefs()

    def rec(msg, *args, level=20):
        return longrange.logging.LogRecord("hongthai", level, "", 0, msg, args, None)

    url = gefs.file_url(BASE, "gec00", 120)
    assert not f.filter(rec("GET %s → %d，%d bytes，%.1f 秒", url, 206, 10, 0.1))
    assert f.filter(rec("GET %s → %d，%d bytes，%.1f 秒", openmeteo.ENSEMBLE_URL, 200, 10, 0.1))
    assert f.filter(rec("GET %s 第 %d 次失敗：%s", url, 1, "x", level=30))  # 失敗照印
    assert f.filter(rec("GEFS %s：%d 個成員", BASE, 31))


def test_watch_list():
    doc = {
        "airports": {
            "RCTP": [
                {
                    "from": "2026-11-09T00:00:00Z",
                    "ifsEns": {"p49": 0.35},
                    "gefs": {"p49": 0.2},
                    "wn2Ens": None,
                },
                {
                    "from": "2026-11-10T00:00:00Z",
                    "ifsEns": {"p49": 0.19},
                    "gefs": None,
                    "wn2Ens": None,
                },
            ]
        }
    }
    assert longrange.watch_list(doc) == [
        ("RCTP", "2026-11-09T00:00:00Z", {"ifsEns": 0.35, "gefs": 0.2})
    ]


# ---- build 只複製、latest.json 不變 ----


def test_publish_copies_longrange_and_latest_unchanged(tmp_path):
    latest = {"schema": 1, "generatedAt": "2026-10-27T13:05:00Z", "airports": []}
    now = utc(2026, 10, 27, 13, 5)
    archive = tmp_path / "data"
    archive.mkdir()
    build.publish(tmp_path / "a", archive, latest, now)
    lr = {"schema": 1, "stale": False, "airports": {"RCTP": []}}
    (archive / longrange.FILENAME).write_text(json.dumps(lr), "utf-8")
    build.publish(tmp_path / "b", archive, latest, now)
    a, b = (
        (tmp_path / "a" / "latest.json").read_bytes(),
        (tmp_path / "b" / "latest.json").read_bytes(),
    )
    assert a == b and b"longrange" not in b
    assert not (tmp_path / "a" / longrange.FILENAME).exists()
    assert json.loads((tmp_path / "b" / longrange.FILENAME).read_text("utf-8")) == lr
