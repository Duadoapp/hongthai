"""HD14 的兩個新來源：ECMWF AIFS Single、NOAA AIGFS。

fixture 是 2026-10-19 實際下載的檔裁成釜山附近（33.5–36.5°N、127.5–130.5°E）：
- `aifs_pus_subregion.grib2`：AIFS 18Z 步長 6／12／18 的 `10u`、`10v`、`2t`、`tp`、`sf`
- `aigfs_pus_f006.grib2`、`aigfs_pus_f012.grib2`：AIGFS 12Z 地面檔的 `UGRD`／`VGRD:10 m`、
  `TMP:2 m`、`APCP`（f006 兩筆都是 `0-6 hour acc fcst`；f012 是 `6-12` 與 `0-12`）
"""

from __future__ import annotations

from math import hypot

import pytest
import requests
from conftest import FIXTURES, utc

from hongthai.grib import byte_ranges, idx_time_ok
from hongthai.sources import aifs, aigfs, ecmwf, gfs
from hongthai.units import KT_PER_MS

PUS = (35.1795, 128.938)


@pytest.fixture
def pus(airports):
    return [a for a in airports if a.icao == "RKPK"]


# ---- AIFS ----


def test_aifs_parse_rain_snow_wind(pus):
    run, pts = aifs.parse(FIXTURES / "aifs_pus_subregion.grib2", pus)
    assert run == utc(2026, 10, 19, 18)
    steps = pts["RKPK"]
    assert [s.valid for s in steps] == [utc(2026, 10, 20, h) for h in (0, 6, 12)]
    # `tp` 是從起報累積的 mm（不是 HRES 的 m）：14.541、22.488、27.777 → 差
    assert [round(s.rain6h_mm, 2) for s in steps] == [14.54, 7.95, 5.29]
    assert [s.snow6h_mm for s in steps] == [0.0, 0.0, 0.0]
    assert [s.ptype for s in steps] == ["rain", "rain", "rain"]
    s0 = steps[0]
    assert s0.wind_kt == pytest.approx(hypot(-1.284, -2.113) * KT_PER_MS, abs=0.01)
    assert s0.wdir == pytest.approx(31.3, abs=0.1)  # u、v 都是負的：從東北吹來
    assert s0.temp2m_c == pytest.approx(289.493 - 273.15, abs=0.01)


@pytest.mark.parametrize(
    ("rain", "snow", "ptype"),
    [
        (10.0, 5.0, "snow"),  # 降雪 ≥ 總降水的一半
        (10.0, 4.9, "rain"),
        (10.0, None, "rain"),
        (0.05, 0.05, "none"),  # < 0.1 mm 當作沒降水
        (None, 3.0, None),
    ],
)
def test_aifs_ptype(rain, snow, ptype):
    assert aifs.AifsStep(utc(2026, 10, 20), 10.0, 90.0, rain, snow).ptype == ptype


def test_aifs_steps_include_slot_start():
    assert aifs.steps(6) == list(range(6, 127, 6))  # 18Z 起報、slot0 00Z
    assert aifs.steps(0) == list(range(6, 121, 6))  # 開始步長 0 不抓（tp(0) 當 0）


class FakeAifsClient:
    def __init__(self, source, model, calls, retry):
        self.source, self.model, self.calls, self.retry = source, model, calls, retry

    def latest(self, **request):
        self.calls.append(("latest", self.source, self.model, request))
        return utc(2026, 10, 19, 18).replace(tzinfo=None)

    def retrieve(self, target, **request):
        self.calls.append(("retrieve", self.source, self.model, request))
        if self.source == "aws":  # AWS 回 503 Slow Down（2026-10-20 實測連 .index 都是）
            resp = requests.Response()
            resp.status_code = 503
            raise requests.HTTPError("503 Slow Down", response=resp)
        target_path = FIXTURES / "aifs_pus_subregion.grib2"
        with open(target, "wb") as f:
            f.write(target_path.read_bytes())


def test_aifs_fetch_uses_ecmwf_mirrors(monkeypatch, pus, tmp_path):
    calls = []

    def client(source, model="ifs", **retry):
        return FakeAifsClient(source, model, calls, retry)

    monkeypatch.setattr(ecmwf, "_client", client)
    data = aifs.fetch(pus, utc(2026, 10, 20, 0), tmp_path)
    assert (data.run, data.mirror) == (utc(2026, 10, 19, 18), "ecmwf")
    assert data.bytes_downloaded == (FIXTURES / "aifs_pus_subregion.grib2").stat().st_size
    assert [(c[0], c[1], c[2]) for c in calls] == [
        ("latest", "ecmwf", "aifs-single"),
        ("retrieve", "aws", "aifs-single"),
        ("retrieve", "ecmwf", "aifs-single"),
    ]
    req = calls[-1][3]
    assert req["param"] == ["10u", "10v", "tp", "sf", "2t"]
    assert (req["stream"], req["type"], req["date"], req["time"]) == ("oper", "fc", "20261019", 18)
    assert req["step"] == list(range(6, 127, 6))
    assert len(data.points["RKPK"]) == 3


def test_aifs_fetch_mslp(monkeypatch, pus, tmp_path):
    """HD21：事件期間同一個請求多抓 `msl`，`mslp_files` 是那個檔。"""
    calls = []
    monkeypatch.setattr(
        ecmwf, "_client", lambda source, model="ifs", **r: FakeAifsClient(source, model, calls, r)
    )
    data = aifs.fetch(pus, utc(2026, 10, 20, 0), tmp_path, mslp=True)
    assert calls[-1][3]["param"] == ["10u", "10v", "tp", "sf", "2t", "msl"]
    assert data.mslp_files == [tmp_path / "aifs.grib2"]
    assert aifs.fetch(pus, utc(2026, 10, 20, 0), tmp_path).mslp_files == []


# ---- AIGFS ----

# 2026-10-19 12Z 地面檔的 `.idx`（真的）
IDX_F012 = """\
1:0:d=2026101912:UGRD:100 m above ground:12 hour fcst:
2:881206:d=2026101912:VGRD:100 m above ground:12 hour fcst:
3:1758284:d=2026101912:UGRD:10 m above ground:12 hour fcst:
4:2621281:d=2026101912:VGRD:10 m above ground:12 hour fcst:
5:3476143:d=2026101912:DPT:2 m above ground:12 hour fcst:
6:3951616:d=2026101912:TMP:2 m above ground:12 hour fcst:
7:4428906:d=2026101912:ACPCP:surface:6-12 hour acc fcst:
8:4429140:d=2026101912:PRMSL:mean sea level:12 hour fcst:
9:5459861:d=2026101912:TMP:surface:12 hour fcst:
10:6028495:d=2026101912:PRES:surface:12 hour fcst:
11:6929643:d=2026101912:APCP:surface:6-12 hour acc fcst:
12:7246323:d=2026101912:APCP:surface:0-12 hour acc fcst:
"""
IDX_F120_TAIL = """\
11:6887527:d=2026101912:APCP:surface:114-120 hour acc fcst:
12:7191599:d=2026101912:APCP:surface:0-5 day acc fcst:
"""
IDX_F000 = """\
1:0:d=2026101912:UGRD:10 m above ground:anl:
2:1052687:d=2026101912:VGRD:10 m above ground:anl:
3:2090717:d=2026101912:DPT:2 m above ground:anl:
4:2651605:d=2026101912:TMP:2 m above ground:anl:
"""


def test_aigfs_names():
    run = utc(2026, 10, 19, 12)
    assert aigfs.file_name(run, 6) == "aigfs.t12z.sfc.f006.grib2"
    assert aigfs.run_dir(run) == "/aigfs.20261019/12/model/atmos/grib2"


def test_aigfs_apcp_kind_both_ways():
    assert aigfs.apcp_kind(IDX_F012, 12) == "acc6"
    only_total = "".join(line + "\n" for line in IDX_F012.splitlines() if "6-12" not in line)
    assert aigfs.apcp_kind(only_total, 12) == "acc0"
    assert aigfs.apcp_kind(IDX_F120_TAIL, 120) == "acc6"
    assert aigfs.apcp_kind(IDX_F120_TAIL.splitlines()[1], 120) == "acc0"  # 0-5 day＝120 小時
    assert aigfs.apcp_kind(IDX_F000, 0) is None
    assert idx_time_ok("acc0", "0-5 day acc fcst", 120)
    assert not idx_time_ok("acc0", "0-5 day acc fcst", 114)


def test_aigfs_byte_ranges_one_apcp():
    """`UGRD`／`VGRD` 相鄰併成一段；`APCP` 只抓選到的那一筆。"""
    opt = (*aigfs.IDX_OPTIONAL, ("APCP", "surface", "acc6"))
    assert byte_ranges(IDX_F012, aigfs.IDX_FIELDS, 12, opt) == [
        (1758284, 3476142),
        (3951616, 4428905),
        (6929643, 7246322),
    ]
    opt = (*aigfs.IDX_OPTIONAL, ("APCP", "surface", "acc0"))
    assert byte_ranges(IDX_F012, aigfs.IDX_FIELDS, 12, opt)[-1] == (7246323, None)


@pytest.mark.parametrize(
    ("apcp", "want"),
    [
        # 每步重置（每個檔都有「前 6 小時」那桶）
        ({6: ("acc6", 6.0), 12: ("acc6", 21.4375)}, {6: 6.0, 12: 21.4375}),
        # 從起報累積：和前一個步長相減；f006 的 0-6 兩種都一樣
        ({6: ("acc6", 6.0), 12: ("acc0", 27.4375)}, {6: 6.0, 12: 21.4375}),
        ({6: ("acc0", 6.0), 12: ("acc0", 27.4375)}, {6: 6.0, 12: 21.4375}),
        # 混著來：acc6 接在 acc0 後面也能累積
        ({6: ("acc0", 6.0), 12: ("acc6", 1.0), 18: ("acc0", 10.0)}, {6: 6.0, 12: 1.0, 18: 3.0}),
        # 前一個步長沒有（第一格開始於 f012）→ acc0 算不出來
        ({12: ("acc0", 27.4375), 18: ("acc0", 30.0)}, {12: None, 18: 2.5625}),
        ({12: ("acc6", None)}, {12: None}),
    ],
)
def test_aigfs_rain6h_both_accumulations(apcp, want):
    assert aigfs.rain6h(apcp) == want


def _messages(name):
    b = (FIXTURES / name).read_bytes()
    out, i = [], 0
    while i < len(b):
        n = int.from_bytes(b[i + 8 : i + 16], "big")
        out.append(b[i : i + n])
        i += n
    return out


class FakeS3:
    """假的 `http_get`：S3 的 `.idx` 與 `Range`。每個步長的「全球檔」是 fixture 的訊息夾在別的
    資料中間，`.idx` 用真的字樣。`acc0_only=True` 時 `.idx` 沒有「前 6 小時」那筆。"""

    def __init__(self, acc0_only=False, prmsl=b"P" * 40):
        self.calls: list[str] = []
        self.files: dict[int, tuple[bytes, str]] = {}
        for fh in (6, 12):
            u, v, t, apcp6, apcp0 = _messages(f"aigfs_pus_f{fh:03d}.grib2")
            parts = [
                (prmsl, "PRMSL:mean sea level"),
                (u, "UGRD:10 m above ground"),
                (v, "VGRD:10 m above ground"),
                (b"D" * 20, "DPT:2 m above ground"),
                (t, "TMP:2 m above ground"),
                (b"S" * 30, "PRES:surface"),
                (apcp6, f"APCP:surface:{fh - 6}-{fh} hour acc fcst"),
                (apcp0, f"APCP:surface:0-{fh} hour acc fcst"),
            ]
            if acc0_only and fh == 12:
                del parts[6]
            full, lines, pos = b"", [], 0
            for i, (body, what) in enumerate(parts, 1):
                when = "" if "acc" in what else f":{fh} hour fcst"
                lines.append(f"{i}:{pos}:d=2026101912:{what}{when}:")
                full += body
                pos += len(body)
            self.files[fh] = (full, "\n".join(lines) + "\n")

    def __call__(self, url, *, headers=None, ok_404=False, error=None, **kw):
        if "aigfs.t18z" in url:  # 18Z 那報還沒出齊
            self.calls.append("idx 18z")
            return FakeResponse(404)
        assert url.startswith(aigfs.S3_URL + "/aigfs.20261019/12/model/atmos/grib2/")
        fh = int(url.split(".f", 1)[1][:3])
        full, idx = self.files.get(fh, self.files[12])
        if url.endswith(".idx"):
            self.calls.append(f"idx f{fh:03d}")
            return FakeResponse(200, idx.encode())
        self.calls.append(f"range f{fh:03d}")
        a, b = headers["Range"].removeprefix("bytes=").split("-")
        return FakeResponse(206, full[int(a) : int(b) + 1 if b else None])


class FakeResponse:
    def __init__(self, status_code: int, content: bytes = b""):
        self.status_code, self.content = status_code, content
        self.text = content.decode("utf-8", "replace")


@pytest.mark.parametrize("acc0_only", [False, True])
def test_aigfs_fetch_from_s3(monkeypatch, pus, tmp_path, acc0_only):
    fake = FakeS3(acc0_only)
    monkeypatch.setattr(aigfs, "http_get", fake)
    monkeypatch.setattr(gfs, "http_get", fake)
    monkeypatch.setattr(aigfs, "SPAN_H", 6)  # 只抓 f006、f012
    data = aigfs.fetch(pus, utc(2026, 10, 19, 20, 10), utc(2026, 10, 19, 18), tmp_path)
    assert (data.run, data.mirror) == (utc(2026, 10, 19, 12), "aws")
    assert fake.calls[:2] == ["idx 18z", "idx f126"]  # 18Z 還沒出齊 → 12Z（rel0＝6）
    pts = data.points["RKPK"]
    assert [p.valid for p in pts] == [utc(2026, 10, 19, 18), utc(2026, 10, 20, 0)]
    # 兩種累積方式都算出同樣的 6 小時雨量（f006 6.0、f012 21.4375）
    assert [p.rain6h_mm for p in pts] == [6.0, 21.4375]
    assert pts[1].wind_kt == pytest.approx(hypot(-1.0787, -1.6309) * KT_PER_MS, abs=0.01)
    assert pts[1].temp2m_c == pytest.approx(288.606 - 273.15, abs=0.01)
    assert all(p.ptype is None for p in pts)
    # 每個步長：.idx 一個、UGRD＋VGRD 一段、TMP 一段、APCP 一段
    assert fake.calls.count("range f006") == 3 and fake.calls.count("range f012") == 3
    assert data.bytes_downloaded > 0


def test_aigfs_fetch_mslp(monkeypatch, pus, tmp_path):
    """HD21：事件期間多抓 PRMSL，`mslp_files` 是每個步長的檔。"""
    from conftest import mslp_grib

    from hongthai import tracks

    fake = FakeS3(prmsl=mslp_grib("prmsl", (12,), 0.0, {12: (16, 135, 40)}, (2026, 10, 19, 12)))
    monkeypatch.setattr(aigfs, "http_get", fake)
    monkeypatch.setattr(gfs, "http_get", fake)
    monkeypatch.setattr(aigfs, "SPAN_H", 6)
    data = aigfs.fetch(pus, utc(2026, 10, 19, 20, 10), utc(2026, 10, 19, 18), tmp_path, mslp=True)
    # 假檔裡 PRMSL 緊接著 UGRD → 併成同一段（真的 `.idx` 不相鄰，每個步長多一段）
    assert fake.calls.count("range f006") == 3 and fake.calls.count("range f012") == 3
    assert fake.files[12][0].startswith(b"GRIB")
    assert data.mslp_files == [tmp_path / "aigfs-f006.grib2", tmp_path / "aigfs-f012.grib2"]
    assert list(tracks.read_mslp(data.mslp_files)) == [utc(2026, 10, 20, 0)]
    assert len(data.points["RKPK"]) == 2  # 原本的值照算


def test_aigfs_find_run_goes_back(monkeypatch):
    """S3 上 00Z、18Z 還沒出齊（最後步長的 .idx 404）→ 往前到 12Z。"""
    asked = []

    def fake(url, *, ok_404=False, error=None, **kw):
        asked.append(url.rsplit("/", 1)[1])
        return FakeResponse(404 if "aigfs.t18z" in url or "aigfs.t00z" in url else 200, b"x")

    monkeypatch.setattr(gfs, "http_get", fake)
    run = gfs.latest_run(
        lambda r, fh: f"{aigfs.S3_URL}{aigfs.run_dir(r)}/{aigfs.file_name(r, fh)}.idx",
        utc(2026, 10, 20, 1, 10),
        utc(2026, 10, 20, 0),
        4,
        aigfs.AigfsError,
    )
    assert run == utc(2026, 10, 19, 12)
    assert asked == [
        "aigfs.t00z.sfc.f120.grib2.idx",
        "aigfs.t18z.sfc.f126.grib2.idx",
        "aigfs.t12z.sfc.f132.grib2.idx",
    ]


def test_aigfs_no_run_error(monkeypatch):
    monkeypatch.setattr(gfs, "http_get", lambda url, **kw: FakeResponse(404))
    with pytest.raises(aigfs.AigfsError) as e:
        aigfs.fetch([], utc(2026, 10, 20, 1, 10), utc(2026, 10, 20, 0))
    assert e.value.code == "no_run"
