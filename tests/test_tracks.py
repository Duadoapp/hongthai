"""颱風路徑抽取（HD21）：找中心（方框、逐步追、停止條件）、起點、ECMWF 路徑產品（BUFR）、
系集中位數、存檔格式、build 的來源、補過去的報。"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest
from conftest import FIXTURES, mslp_grib, utc

from hongthai import events, tracks
from hongthai.config import Event, EventSeed
from hongthai.sources import ecmwf

RUN = utc(2026, 10, 20, 0)
EV = Event(
    "29W",
    "CHAMPI（薔琵）",
    date(2026, 10, 19),
    date(2026, 10, 28),
    ("RCTP",),
    "TC2636",
    "wp2926",
)
OPER = FIXTURES / "ecmwf_tf_oper_2026102000.bufr"
ENFO = FIXTURES / "ecmwf_tf_enfo_2026102000.bufr"


# ---- 找中心 ----

LATS = np.arange(-5, 45.001, 0.25)
LONS = np.arange(95, 185.001, 0.25)


def field(*lows: tuple[float, float, float]) -> tracks.Field:
    """0.25° 的場，底 1012 hPa，`lows` 是（緯, 經, 深度 hPa）。"""
    hpa = np.full((len(LATS), len(LONS)), 1012.0)
    for la, lo, depth in lows:
        hpa -= depth * np.exp(-((LATS[:, None] - la) ** 2 + (LONS[None, :] - lo) ** 2) / 2)
    return tracks.Field(LATS, LONS, hpa)


def series(*lows, start: int = 6) -> dict:
    """每 6 小時一個場（`lows` 每個是那一步的低壓，None＝沒有低壓）。"""
    return {
        RUN + timedelta(hours=start + 6 * k): field(*([lo] if lo else []))
        for k, lo in enumerate(lows)
    }


def test_find_track_follows_low():
    fields = series((16, 135, 40), (16.5, 134, 40), (17.25, 133, 45), (18, 132.5, 30))
    points, stop = tracks.find_track(fields, 16.4, 135.6)
    assert stop == "end"
    assert [(p["lat"], p["lon"]) for p in points] == [
        (16, 135),
        (16.5, 134),
        (17.25, 133),
        (18, 132.5),
    ]
    assert points[0] == {
        "validAt": "2026-10-20T06:00:00Z",
        "lat": 16.0,
        "lon": 135.0,
        "mslpHpa": 972.0,
    }
    assert points[2]["mslpHpa"] == 967.0


def test_seed_box_is_4_degrees_then_3():
    # 起點離中心 3.5°：第一步的 ±4° 方框找得到；之後同樣的跳動（3.5°）在 ±3° 方框的邊上 → 停
    fields = series((16, 135, 40), (16, 131.5, 40))
    points, stop = tracks.find_track(fields, 16, 138.5)
    assert [(p["lat"], p["lon"]) for p in points] == [(16, 135)]
    assert stop == "edge"


def test_find_track_stops_when_weak():
    fields = series((16, 135, 40), (17, 134, 10), (18, 133, 6.5))  # 第三步 1005.5 hPa
    points, stop = tracks.find_track(fields, 16, 135)
    assert len(points) == 2 and stop == "weak"
    points, stop = tracks.find_track(series((16, 135, 7)), 16, 135)  # 剛好 1005 還算
    assert len(points) == 1 and stop == "end"


def test_find_track_stops_at_domain_and_gap():
    # 中心跨出北緯 40°
    points, stop = tracks.find_track(series((39, 140, 30), (41, 141, 30)), 39, 140)
    assert len(points) == 1 and stop == "domain"
    # 東經 180° 以東（經度照 0–360 判斷）
    points, stop = tracks.find_track(series((30, 179.5, 30), (30, 181, 30)), 30, 179.5)
    assert len(points) == 1 and stop == "domain"
    # 中間少一個步長
    fields = series((16, 135, 40), (17, 134, 40), (18, 133, 40))
    del fields[RUN + timedelta(hours=12)]
    points, stop = tracks.find_track(fields, 16, 135)
    assert len(points) == 1 and stop == "gap"


def test_box_min_edge_and_empty():
    f = field((16, 140, 40))
    lat, lon, hpa, edge = tracks.box_min(f, 16, 135, 3)  # 低壓在方框東邊外面 → 最小點在邊上
    assert (lat, lon, edge) == (16, 138, True)
    assert tracks.box_min(f, 16, 140, 3)[3] is False
    assert tracks.box_min(f, 80, 140, 3) is None  # 方框在裁的範圍外


@pytest.mark.parametrize(("name", "lon_first"), [("prmsl", 0.0), ("msl", 180.0)])
def test_read_mslp_crops_and_wraps(tmp_path, name, lon_first):
    """GFS／AIGFS 的 `prmsl`（經度 0–360）與 AIFS 的 `msl`（經度 −180–180）都讀得到；不相干的
    變數不讀。"""
    path = tmp_path / "m.grib2"
    lows = {6: (16, 135, 50), 12: (17, 134, 50)}
    path.write_bytes(mslp_grib(name, (6, 12), lon_first, lows) + mslp_grib("2t", (6,)))
    fields = tracks.read_mslp([path, tmp_path / "missing.grib2"])
    assert sorted(fields) == [RUN + timedelta(hours=6), RUN + timedelta(hours=12)]
    f = fields[RUN + timedelta(hours=6)]
    assert (f.lats[0], f.lats[-1], f.lons[0], f.lons[-1]) == (-5, 45, 95, 185)
    assert np.all(np.diff(f.lats) > 0) and np.all(np.diff(f.lons) > 0)
    assert f.hpa.min() == pytest.approx(962, abs=0.1)
    points, stop = tracks.find_track(fields, 16.5, 135.5)
    assert [(p["lat"], p["lon"]) for p in points] == [(16, 135), (17, 134)] and stop == "end"


# ---- 起點 ----


def _pos(d: Path, source: str, rows: list[dict]) -> None:
    p = d / "position" / f"{source}-2026-10-20.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps({"kind": "analysis", "source": source, **r}) + "\n")


def test_position_near_prefers_jtwc_and_closest(tmp_path):
    _pos(tmp_path, "jtwc", [{"validAt": "2026-10-19T18:00:00Z", "lat": 15, "lon": 137}])
    _pos(
        tmp_path,
        "jma",
        [
            {
                "validAt": "2026-10-20T03:00:00Z",
                "issuedAt": "2026-10-20T03:45:00Z",
                "lat": 16.2,
                "lon": 134.9,
            },
            {
                "validAt": "2026-10-20T01:00:00Z",
                "issuedAt": "2026-10-20T01:45:00Z",
                "lat": 16.1,
                "lon": 135.2,
            },
            {
                "validAt": "2026-10-20T01:00:00Z",
                "issuedAt": "2026-10-20T02:10:00Z",
                "lat": 16.15,
                "lon": 135.25,
            },
            {"kind": "forecast", "validAt": "2026-10-20T00:00:00Z", "lat": 1, "lon": 1},
        ],
    )
    # JTWC 那筆在 6 小時前（窗外）→ JMA 離起報最近的（01Z，兩筆取發布較晚的）
    assert tracks.position_near(tmp_path, RUN) == {
        "lat": 16.15,
        "lon": 135.25,
        "at": "2026-10-20T01:00:00Z",
        "source": "jma",
    }
    _pos(tmp_path, "jtwc", [{"validAt": "2026-10-20T00:00:00Z", "lat": 15.9, "lon": 135.6}])
    assert tracks.position_near(tmp_path, RUN)["source"] == "jtwc"
    assert tracks.position_near(tmp_path, RUN + timedelta(hours=12)) is None


def test_find_seed_fallbacks(tmp_path):
    ev = Event(**{**EV.__dict__, "seed": EventSeed(16.0, 135.6, RUN + timedelta(hours=2))})
    observed = {"lat": 16.0, "lon": 135.6, "at": "2026-10-20T06:00:00Z", "source": "ecmwf-tf"}
    asked = []

    def obs():
        asked.append(1)
        return observed

    seed = tracks.find_seed(tmp_path, RUN, ev, obs)
    assert seed == {
        "lat": 16.0,
        "lon": 135.6,
        "at": "2026-10-20T02:00:00Z",
        "source": "events.json",
    }
    assert not asked  # events.json 的 seed 在窗內就不用抓 ECMWF
    # events.json 的 seed 離這報超過 3 小時 → ECMWF tf 的觀測位置
    assert tracks.find_seed(tmp_path, RUN + timedelta(hours=6), ev, obs) == observed
    assert tracks.find_seed(tmp_path, RUN + timedelta(hours=6), ev, lambda: None) is None
    assert tracks.find_seed(tmp_path, RUN, EV) is None


# ---- ECMWF 路徑產品 ----


def test_parse_tf_oper():
    trudy, champi = tracks.parse_tf(OPER)
    assert (trudy.id, trudy.name, champi.id, champi.name) == ("21E", "TRUDY", "36W", "CHAMPI")
    assert champi.run == RUN and champi.observed == (16.0, 135.6)
    (m,) = champi.members
    assert (m.number, m.control, len(m.points)) == (51, True, 20)
    assert m.points[0] == {
        "validAt": "2026-10-20T00:00:00Z",
        "lat": 15.9,
        "lon": 135.5,
        "pressureHpa": 953.0,
        "windKt": 77.0,
    }
    assert m.points[1]["validAt"] == "2026-10-20T06:00:00Z"
    assert m.points[-1]["validAt"] == "2026-10-24T18:00:00Z"  # +114 小時
    assert trudy.observed == (19.4, -108.0)


def test_parse_tf_enfo():
    champi, dist = tracks.parse_tf(ENFO)
    assert [m.number for m in champi.members] == list(range(40, 52))
    assert [m.control for m in champi.members] == [False] * 11 + [True]
    assert [len(m.points) for m in champi.members] == [
        20,
        20,
        24,
        26,
        25,
        24,
        19,
        22,
        18,
        21,
        21,
        20,
    ]
    # 新生的擾動沒有觀測位置，比距離時用第一個成員的第一點
    assert (dist.id, dist.observed) == ("70W", None)
    assert dist.position() == (dist.members[0].points[0]["lat"], dist.members[0].points[0]["lon"])


def test_storm_ids_and_name():
    assert tracks.storm_ids(EV) == {"29W"}
    assert tracks.storm_name(EV) == "CHAMPI"
    ev = Event("21E", "TRUDY", EV.start, EV.end, (), None, "ep2126")
    assert tracks.storm_ids(ev) == {"21E"} and tracks.storm_name(ev) == "TRUDY"
    assert tracks.storm_name(Event("x", "（無名）", EV.start, EV.end, ())) is None


def test_pick_storm_id_name_distance():
    storms = tracks.parse_tf(OPER) + tracks.parse_tf(ENFO)
    assert tracks.pick_storm(storms, EV, None)[1] == "name"  # 29W 在 ECMWF 叫 36W
    ev = Event("x", "Nameless", EV.start, EV.end, (), None, "ep2126")
    assert [(s.id, how) for s, how in [tracks.pick_storm(storms, ev, None)]] == [("21E", "id")]
    ev = Event("x", "Nameless", EV.start, EV.end, ())
    near = {"lat": 16.2, "lon": 134.9}  # 離 CHAMPI 的觀測位置約 80 公里
    s, how = tracks.pick_storm(tracks.parse_tf(OPER), ev, near)
    assert (s.name, how) == ("CHAMPI", "distance")
    assert tracks.pick_storm(storms, ev, {"lat": 30, "lon": 150}) is None  # 300 公里內沒有
    assert tracks.pick_storm(storms, ev, None) is None


def test_tf_doc_hres_and_ensemble():
    doc = tracks.tf_doc("ifs", RUN, tracks.parse_tf(OPER), EV, None)
    assert set(doc) == {"model", "run", "storm", "members", "mean"}
    assert doc["storm"] == {
        "id": "36W",
        "name": "CHAMPI",
        "matchedBy": "name",
        "observed": {"lat": 16.0, "lon": 135.6},
    }
    assert [m["member"] for m in doc["members"]] == [0] and doc["mean"] == []
    ens = tracks.tf_doc("ifs-ens", RUN, tracks.parse_tf(ENFO), EV, None)
    assert [m["member"] for m in ens["members"]] == list(range(40, 52))
    counts: dict[str, int] = {}
    for m in ens["members"]:
        for p in m["points"]:
            counts[p["validAt"]] = counts.get(p["validAt"], 0) + 1
    assert [p["validAt"] for p in ens["mean"]] == sorted(t for t, n in counts.items() if n >= 10)
    assert len(ens["mean"]) < len(counts)  # 後面成員不到 10 個的時間點沒寫
    first = ens["mean"][0]
    lats = [m["points"][0]["lat"] for m in ens["members"]]
    assert first == {
        "validAt": "2026-10-20T00:00:00Z",
        "lat": round(float(np.median(lats)), 2),
        "lon": first["lon"],
        "n": 12,
    }
    # 找不到這顆：照寫一份空的
    other = Event("x", "Nameless", EV.start, EV.end, ())
    assert tracks.tf_doc("ifs", RUN, tracks.parse_tf(OPER), other, None) == {
        "model": "ifs",
        "run": "2026-10-20T00:00:00Z",
        "storm": None,
        "members": [],
        "mean": [],
    }


def test_ens_mean_needs_10_members():
    pts = [{"validAt": "t", "lat": 10.0 + i, "lon": 130.0 + i} for i in range(9)]
    members = [{"member": i, "points": [p]} for i, p in enumerate(pts)]
    assert tracks.ens_mean(members) == []
    members.append({"member": 9, "points": [{"validAt": "t", "lat": 30.0, "lon": 120.0}]})
    assert tracks.ens_mean(members) == [{"validAt": "t", "lat": 14.5, "lon": 133.5, "n": 10}]


# ---- 下載 ----


def test_downloads_tf_request_and_cache(tmp_path, monkeypatch):
    calls = []

    def fake_download(clients, target, sources=ecmwf.DOWNLOAD_SOURCES, label="", **request):
        calls.append(request)
        if request["time"] == 6:
            raise ecmwf.EcmwfError("沒有", "http_404")
        shutil.copyfile(OPER if request["stream"] == "oper" else ENFO, target)
        return target.stat().st_size, "ecmwf"

    monkeypatch.setattr(ecmwf, "_download", fake_download)
    dl = tracks.Downloads(tmp_path)
    assert [s.name for s in dl.tf("oper", RUN)] == ["TRUDY", "CHAMPI"]
    dl.tf("oper", RUN)  # 同一個只抓一次
    dl.tf("enfo", RUN)
    assert calls == [
        {"date": "20261020", "time": 0, "stream": "oper", "type": "tf", "step": 360},
        {"date": "20261020", "time": 0, "stream": "enfo", "type": "tf", "step": 360},
    ]
    assert dl.bytes == OPER.stat().st_size + ENFO.stat().st_size
    run6 = RUN + timedelta(hours=6)
    with pytest.raises(ecmwf.EcmwfError):
        dl.tf("oper", run6)
    with pytest.raises(tracks.TracksError) as e:  # 失敗也記著，不重抓
        dl.tf("oper", run6)
    assert e.value.code == "tf_failed"
    assert calls[-1]["step"] == 144 and len(calls) == 3


class FakeS3Mslp:
    """GFS／AIGFS 的 S3：`.idx` 裡 PRMSL 夾在別的資料中間，`Range` 照切。"""

    def __init__(self):
        self.msg = mslp_grib("prmsl", (6,), 0.0, {6: (16, 135, 40)})
        self.full = b"X" * 50 + self.msg + b"Y" * 30
        self.calls = []

    def __call__(self, url, *, headers=None, error=None, **kw):
        if url.endswith(".idx"):
            self.calls.append(url.rsplit("/", 1)[1])
            idx = (
                "1:0:d=x:UGRD:10 m above ground:6 hour fcst:\n"
                "2:50:d=x:PRMSL:mean sea level:6 hour fcst:\n"
                f"3:{50 + len(self.msg)}:d=x:TMP:surface:6 hour fcst:\n"
            )
            return _Resp(200, idx.encode())
        self.calls.append(headers["Range"])
        a, b = headers["Range"].removeprefix("bytes=").split("-")
        return _Resp(206, self.full[int(a) : int(b) + 1])


class _Resp:
    def __init__(self, status_code: int, content: bytes):
        self.status_code, self.content = status_code, content
        self.text = content.decode("utf-8", "replace")


@pytest.mark.parametrize("model", ["gfs", "aigfs"])
def test_downloads_mslp_noaa_only_prmsl(tmp_path, monkeypatch, model):
    fake = FakeS3Mslp()
    monkeypatch.setattr(tracks, "http_get", fake)
    monkeypatch.setattr(tracks.gfs, "http_get", fake)
    dl = tracks.Downloads(tmp_path)
    paths = dl.mslp(model, RUN, [6, 12])
    assert [p.name for p in paths] == [
        f"{model}-msl-2026102000-f006.grib2",
        f"{model}-msl-2026102000-f012.grib2",
    ]
    name = "gfs.t00z.pgrb2.0p25.f006.idx" if model == "gfs" else "aigfs.t00z.sfc.f006.grib2.idx"
    assert fake.calls[:2] == [name, f"bytes=50-{50 + len(fake.msg) - 1}"]
    assert dl.bytes == 2 * len(fake.msg)
    assert len(tracks.read_mslp(paths[:1])) == 1


def test_downloads_mslp_aifs(tmp_path, monkeypatch):
    calls = []

    def fake_download(clients, target, sources=ecmwf.DOWNLOAD_SOURCES, label="", **request):
        calls.append((label, request))
        target.write_bytes(mslp_grib("msl", (6, 12), 180.0))
        return target.stat().st_size, "ecmwf"

    monkeypatch.setattr(ecmwf, "_download", fake_download)
    dl = tracks.Downloads(tmp_path)
    (path,) = dl.mslp("aifs", RUN, [6, 12])
    assert calls[0] == (
        "AIFS msl",
        {
            "date": "20261020",
            "time": 0,
            "stream": "oper",
            "type": "fc",
            "param": ["msl"],
            "step": [6, 12],
        },
    )
    assert len(tracks.read_mslp([path])) == 2


def test_mslp_steps_same_as_build():
    slot0 = RUN + timedelta(hours=6)
    assert tracks.mslp_steps("gfs", RUN, slot0) == list(range(6, 127, 6))
    assert tracks.mslp_steps("aigfs", RUN, RUN) == list(range(0, 121, 6))
    assert tracks.mslp_steps("aifs", RUN, RUN) == list(range(6, 121, 6))  # AIFS 不抓第 0 步


# ---- 抽一報、存檔 ----


class FakeDownloads(tracks.Downloads):
    def __init__(self, workdir: Path, fail: tuple[str, ...] = ()):
        super().__init__(workdir)
        self.fail = fail
        self.asked: list[tuple] = []

    def tf(self, stream, run):
        self.asked.append(("tf", stream, run))
        if stream in self.fail:
            raise ecmwf.EcmwfError("down", "http_503")
        return tracks.parse_tf(OPER if stream == "oper" else ENFO)

    def mslp(self, model, run, steps):
        self.asked.append(("mslp", model, run, tuple(steps)))
        return []


def test_extract_writes_both_formats(tmp_path):
    d = tmp_path / "events" / "29W"
    _pos(d, "jtwc", [{"validAt": "2026-10-20T00:00:00Z", "lat": 15.9, "lon": 135.6}])
    dl = FakeDownloads(tmp_path / "work")
    fields = series((16, 135, 40), (16.5, 134, 40))
    for model in tracks.TRACK_MODELS:
        p = tracks.extract(d, EV, model, RUN, dl, lambda: fields)
        assert p == d / "tracks" / f"20261020T0000Z-{model}.json"
    gfs_doc = json.loads((d / "tracks" / "20261020T0000Z-gfs.json").read_text("utf-8"))
    assert gfs_doc == {
        "model": "gfs",
        "run": "2026-10-20T00:00:00Z",
        "seed": {"lat": 15.9, "lon": 135.6, "at": "2026-10-20T00:00:00Z", "source": "jtwc"},
        "points": [
            {"validAt": "2026-10-20T06:00:00Z", "lat": 16.0, "lon": 135.0, "mslpHpa": 972.0},
            {"validAt": "2026-10-20T12:00:00Z", "lat": 16.5, "lon": 134.0, "mslpHpa": 972.0},
        ],
        "stop": "end",
    }
    ens = json.loads((d / "tracks" / "20261020T0000Z-ifs-ens.json").read_text("utf-8"))
    assert ens["model"] == "ifs-ens" and len(ens["members"]) == 12 and ens["mean"]
    # 有現報就不用 ECMWF 的觀測位置
    assert ("tf", "oper", RUN) in dl.asked and ("tf", "enfo", RUN) in dl.asked
    # 存檔不縮排；系集 12 個成員約 15 KB
    text = (d / "tracks" / "20261020T0000Z-ifs-ens.json").read_text("utf-8")
    assert "\n" not in text.rstrip("\n") and len(text) < 30_000


def test_extract_seed_from_ecmwf_or_skip(tmp_path, caplog):
    d = tmp_path / "events" / "29W"
    fields = series((16, 135, 40))
    # 沒有現報 → 用 ECMWF tf 裡 CHAMPI 的觀測位置
    p = tracks.extract(d, EV, "aigfs", RUN, FakeDownloads(tmp_path / "w"), lambda: fields)
    assert json.loads(p.read_text("utf-8"))["seed"] == {
        "lat": 16.0,
        "lon": 135.6,
        "at": "2026-10-20T00:00:00Z",
        "source": "ecmwf-tf",
    }
    # ECMWF 也抓不到 → 跳過、不寫檔
    with caplog.at_level(logging.WARNING, logger="hongthai"):
        dl = FakeDownloads(tmp_path / "w", fail=("oper",))
        assert tracks.extract(d, EV, "aifs", RUN, dl, lambda: fields) is None
    assert not (d / "tracks" / "20261020T0000Z-aifs.json").exists()
    assert "找不到起點" in caplog.text


def test_build_tracks_skips_existing_and_reads_fields_once(tmp_path, monkeypatch):
    ev2 = Event("30W", "OTHER", EV.start, EV.end, ())
    for e in (EV, ev2):
        _pos(
            tmp_path / "events" / e.id,
            "jtwc",
            [{"validAt": "2026-10-20T00:00:00Z", "lat": 16, "lon": 135}],
        )
    existing = tracks.track_path(tmp_path / "events" / "29W", RUN, "gfs")
    existing.parent.mkdir(parents=True)
    existing.write_text("舊的", encoding="utf-8")
    reads = []

    def fake_read(paths):
        reads.append(list(paths))
        return series((16, 135, 40))

    monkeypatch.setattr(tracks, "read_mslp", fake_read)
    monkeypatch.setattr(tracks, "Downloads", lambda workdir: FakeDownloads(workdir, ("enfo",)))
    res = tracks.build_tracks(
        tmp_path,
        [EV, ev2],
        RUN,
        {"gfs": (RUN, [Path("g")]), "aifs": (RUN - timedelta(hours=6), [])},
        tmp_path / "work",
    )
    assert existing.read_text("utf-8") == "舊的"
    assert res.skipped == 1
    names = sorted(p.relative_to(tmp_path / "events").as_posix() for p in res.written)
    assert names == [
        "29W/tracks/20261020T0000Z-ifs.json",
        "30W/tracks/20261020T0000Z-gfs.json",
        "30W/tracks/20261020T0000Z-ifs.json",  # 30W 不在產品裡：照寫一份空的
    ]
    assert reads == [[Path("g")]]  # 兩個事件共用一次讀場
    # 系集抓失敗 → 兩個事件都失敗；AIFS（18Z）：29W 有起點（ECMWF tf 的觀測位置）但沒抓到海平面
    # 氣壓 → 失敗，30W 沒有起點 → 跳過；AIGFS 這報沒抓到（不在 mslp 裡）→ 只 log
    assert res.failed == [
        "ifs-ens@2026-10-20T00:00:00Z",
        "aifs@2026-10-19T18:00:00Z",
        "ifs-ens@2026-10-20T00:00:00Z",
    ]
    assert res.no_seed == 1


# ---- 補過去的報 ----


def _snapshot(d: Path, stamp: str, runs: dict) -> None:
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{stamp}.json").write_text(json.dumps({"runs": runs}), encoding="utf-8")


def test_runs_wanted_earliest_slot(tmp_path):
    _snapshot(tmp_path, "20261018T2300Z", {"gfs": "2026-10-18T12:00:00Z"})  # --from 之前
    _snapshot(
        tmp_path,
        "20261019T0210Z",
        {
            "ecmwf": "2026-10-18T18:00:00Z",
            "ecmwfEns": "2026-10-18T12:00:00Z",
            "gfs": "2026-10-18T18:00:00Z",
            "aifs": None,
            "aigfs": "bad",
        },
    )
    _snapshot(tmp_path, "20261019T0810Z", {"gfs": "2026-10-18T18:00:00Z"})
    wanted = tracks.runs_wanted(tmp_path, utc(2026, 10, 19))
    assert wanted == {
        ("ifs", utc(2026, 10, 18, 18)): utc(2026, 10, 19, 0),
        ("ifs", utc(2026, 10, 18, 12)): utc(2026, 10, 19, 0),
        ("ifs-ens", utc(2026, 10, 18, 18)): utc(2026, 10, 19, 0),
        ("ifs-ens", utc(2026, 10, 18, 12)): utc(2026, 10, 19, 0),
        ("gfs", utc(2026, 10, 18, 18)): utc(2026, 10, 19, 0),  # 最早那份的 slot0
    }


def test_backfill_tracks_skips_existing(tmp_path, monkeypatch):
    history = tmp_path / "history"
    d = history / "events" / "29W"
    _snapshot(
        d,
        "20261020T0210Z",
        {
            "ecmwf": "2026-10-20T00:00:00Z",
            "gfs": "2026-10-20T00:00:00Z",
            "aigfs": "2026-10-19T18:00:00Z",
        },
    )
    _pos(d, "jtwc", [{"validAt": "2026-10-20T00:00:00Z", "lat": 16, "lon": 135}])
    tracks.write_doc(tracks.track_path(d, RUN, "ifs"), {"old": True})
    made: list[FakeDownloads] = []

    def downloads(workdir):
        made.append(FakeDownloads(workdir))
        return made[-1]

    monkeypatch.setattr(tracks, "Downloads", downloads)
    monkeypatch.setattr(tracks, "read_mslp", lambda paths: series((16, 135, 40)))
    (tmp_path / "work").mkdir()
    (tmp_path / "work" / "left.grib2").write_bytes(b"x")
    out = tracks.backfill_tracks(history, [EV], utc(2026, 10, 19), tmp_path / "work")
    res = out["29W"]
    assert res.skipped == 1 and res.failed == [] and res.no_seed == 0
    assert sorted(p.name for p in res.written) == [
        "20261019T1800Z-aigfs.json",  # 18Z 沒有現報 → ECMWF tf 的觀測位置
        "20261020T0000Z-gfs.json",
        "20261020T0000Z-ifs-ens.json",
    ]
    assert json.loads(tracks.track_path(d, RUN, "ifs").read_text("utf-8")) == {"old": True}
    asked = made[0].asked
    assert ("mslp", "gfs", RUN, tuple(range(0, 121, 6))) in asked  # slot0 00Z → rel0 0
    assert ("mslp", "aigfs", RUN - timedelta(hours=6), tuple(range(6, 127, 6))) in asked
    assert not list((tmp_path / "work").glob("*.grib2"))  # 抽完就刪
    # 再跑一次全部跳過
    assert (
        tracks.backfill_tracks(history, [EV], utc(2026, 10, 19), tmp_path / "work")["29W"].skipped
        == 4
    )


def test_events_cli_backfill_tracks(tmp_path, monkeypatch, capsys):
    got = {}

    def fake(history, evs, since, workdir):
        got.update(history=history, ids=[e.id for e in evs], since=since)
        r = tracks.TracksResult(written=[Path("20261020T0000Z-gfs.json")], skipped=2, bytes=1234)
        return {"29W": r}

    monkeypatch.setattr(tracks, "backfill_tracks", fake)
    (tmp_path / "events.json").write_text(
        json.dumps(
            {"events": [{"id": "29W", "name": "CHAMPI", "from": "2026-10-19", "to": "2026-10-28"}]}
        ),
        encoding="utf-8",
    )
    argv = ["backfill-tracks", "--archive", str(tmp_path / "data"), "--events"]
    assert events.main([*argv, str(tmp_path / "events.json"), "--from", "2026-10-19T06:00Z"]) == 0
    assert got == {
        "history": tmp_path / "data" / "history",
        "ids": ["29W"],
        "since": utc(2026, 10, 19, 6),
    }
    out = capsys.readouterr().out
    assert "29W：寫了 1 份、已經有 2" in out and "1,234 bytes" in out
