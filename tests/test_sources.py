"""各來源的解析，用 `fixtures/` 裡的小樣本（不連網）。"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest
import requests
from conftest import FIXTURES, load_json, utc

from hongthai.sources import cwa, ecmwf, flights, gfs, hko, nws, smg, taf
from hongthai.units import KT_PER_MS

# ---- TAF／METAR ----


def test_parse_tafs_real_sample():
    tafs = taf.parse_tafs(load_json("taf.json"))
    assert set(tafs) == {"RCTP", "RCSS", "RCKH", "VHHH", "VMMC", "ZSPD", "ROAH", "RJTT", "RKSI"}
    t = tafs["RCTP"]
    assert t.issued == utc(2026, 10, 17, 23)
    assert t.valid_from == utc(2026, 10, 18, 0)
    assert t.raw.startswith("TAF RCTP")
    assert [p.kind for p in t.periods] == ["main", "main", "main", "tempo", "main"]
    assert t.periods[0].wind_kt == 5 and t.periods[0].gust_kt is None
    assert t.periods[2].wdir == 90


def test_parse_tafs_multi_station_h9():
    """41 個機場一次請求的回應（fixture 加了四站，2026-10-18 抓的）：各站各自解析。"""
    tafs = taf.parse_tafs(load_json("taf.json"))
    # 中國的 TAF 用 MPS，API 解碼成節是乘 2（01006MPS → 12 節）
    pd = tafs["ZSPD"]
    assert "01006MPS" in pd.raw
    assert [(p.kind, p.wdir, p.wind_kt) for p in pd.periods] == [("main", 10, 12), ("main", 120, 8)]
    # 有天氣沒有風的 TEMPO 段：風是 None
    hnd = tafs["RJTT"]
    assert [(p.kind, p.wind_kt) for p in hnd.periods] == [("main", 12), ("tempo", None)]
    assert tafs["RKSI"].issued == utc(2026, 10, 18, 17)
    metars = taf.parse_metars(load_json("metar.json"))
    assert {"ZSPD", "ROAH", "RJTT", "RKSI", "ROMY"} <= set(metars)
    assert "ROMY" not in tafs  # 宮古只有 METAR
    assert metars["ROMY"].wind_kt == 7


class _Resp:
    def __init__(self, status, body):
        self.status_code, self.content = status, body

    def json(self):
        return json.loads(self.content)


def test_taf_fetch_one_request_for_all_and_204(monkeypatch, airports):
    calls = []

    def fake_get(url, *, params=None, error=None, **kw):
        calls.append((url, params))
        if url == taf.TAF_URL:
            return _Resp(200, (FIXTURES / "taf.json").read_bytes())
        return _Resp(204, b"")  # 一站 METAR 都沒有

    monkeypatch.setattr(taf, "http_get", fake_get)
    data = taf.fetch(airports)
    assert len(calls) == 2
    ids = calls[0][1]["ids"].split(",")
    assert ids == [a.icao for a in airports] and len(ids) == 51
    assert len(calls[0][1]["ids"]) < 300  # 網址長度沒問題
    assert data.metars == {} and data.raw["metar"] == []
    assert "RCYU" not in data.tafs and "RCTP" in data.tafs


def test_period_kind_prob_and_tempo():
    assert taf.period_kind({"fcstChange": "TEMPO", "probability": None}) == "tempo"
    assert taf.period_kind({"fcstChange": "PROB", "probability": 30}) == "prob30"
    assert taf.period_kind({"fcstChange": "TEMPO", "probability": 40}) == "prob40"
    assert taf.period_kind({"fcstChange": "BECMG"}) == "main"
    assert taf.period_kind({"fcstChange": None}) == "main"


def test_parse_metars_real_sample():
    m = taf.parse_metars(load_json("metar.json"))
    assert m["VHHH"].wind_kt == 11
    assert m["VHHH"].wdir == 90
    assert m["VHHH"].gust_kt is None
    assert m["RCTP"].observed.tzinfo is not None
    assert m["RCTP"].raw.startswith("METAR RCTP")


def test_metar_variable_direction():
    m = taf.parse_metars([{"icaoId": "X", "obsTime": 0, "wdir": "VRB", "wspd": 3, "rawOb": ""}])
    assert m["X"].wdir is None


# ---- 天文台 ----


def _hko(kind):
    return {lang: load_json(f"hko_warnsum_{kind}_{lang}.json") for lang in ("tc", "en", "sc")}


def test_hko_no_signal_real_sample():
    assert hko.parse_signal(_hko("fire")) is None


def test_hko_signal8():
    s = hko.parse_signal(_hko("tc8ne"))
    assert s.code == "TC8NE"
    assert s.level == "high"
    assert s.text["zh-TW"] == s.text["zh-HK"] == "八號東北烈風或暴風信號"
    assert s.text["zh-CN"] == "八号东北烈风或暴风信号"
    assert s.text["en"] == "Gale or Storm Signal No. 8 Northeast"
    assert s.issued_at == "2026-10-20T01:40:00Z"


@pytest.mark.parametrize(
    "code,level",
    [("TC1", "low"), ("TC3", "medium"), ("TC8SW", "high"), ("TC9", "high"), ("TC10", "high")],
)
def test_hko_signal_levels(code, level):
    assert hko.signal_level(code) == level


def test_hko_cancelled_signal_ignored():
    data = _hko("tc8ne")
    for d in data.values():
        d["WTCSGNL"]["actionCode"] = "CANCEL"
    assert hko.parse_signal(data) is None


# ---- 氣象署 ----


def test_cwa_cancel_real_sample_no_warning():
    assert cwa.parse_warnings(load_json("cwa_w-c0034-001_cancel.json"), utc(2026, 8, 28, 7)) == []


def test_cwa_land_warning_taoyuan_in_zone():
    ws = cwa.parse_warnings(load_json("cwa_w-c0034-001_land.json"), utc(2026, 8, 27, 5))
    assert len(ws) == 1
    w = ws[0]
    assert (w.kind, w.level, w.in_zone) == ("typhoon_land", "high", True)
    assert "沙德爾" in w.text["zh-TW"] and "桃園在警戒區" in w.text["zh-TW"]
    assert "Saudel" in w.text["en"]
    assert set(w.text) == {"zh-TW", "zh-HK", "zh-CN", "en"}
    assert w.issued_at == "2026-08-27T03:30:00Z"
    assert "桃園市" in w.detail


def test_cwa_sea_warning_medium():
    ws = cwa.parse_warnings(load_json("cwa_w-c0034-001_sea.json"), utc(2026, 8, 27, 5))
    assert [(w.kind, w.level, w.in_zone) for w in ws] == [("typhoon_sea", "medium", False)]


def test_cwa_north_text_counts_but_not_north_sea():
    info = {"area": [{"areaDesc": "臺灣北部海面"}], "description": {"section": []}}
    assert cwa.taoyuan_in_zone(info) is False
    info["description"]["section"] = [{"title": "警戒區域及事項", "value": "北部地區應嚴加戒備"}]
    assert cwa.taoyuan_in_zone(info) is True


def test_cwa_stale_warning_ignored():
    data = load_json("cwa_w-c0034-001_land.json")
    assert cwa.parse_warnings(data, utc(2026, 8, 28, 0)) == []


def test_cwa_zone_per_airport(airports):
    by = {a.icao: a for a in airports}
    data = load_json("cwa_w-c0034-001_land.json")
    # 警戒區文字只有北部；area 只留警戒區裡的縣市
    north = {"基隆市", "臺北市", "新北市", "桃園市", "新竹縣", "新竹市", "苗栗縣", "連江縣"}
    for info in data["records"]["info"]:
        info["area"] = [a for a in info["area"] if a["areaDesc"] in north]
    bulletins = cwa.parse_bulletins(data, utc(2026, 8, 27, 5))
    got = {}
    taiwan = [a.icao for a in airports if a.region == "taiwan"]
    for icao in taiwan:
        a = by[icao]
        (w,) = cwa.for_airport(bulletins, a.cwa_areas, a.name)
        got[icao] = (w.kind, w.level, w.in_zone)
    # 北部＋連江縣在警戒區（警戒區文字也寫「馬祖應嚴加戒備」）→ 桃園、松山、馬祖高，其他中
    in_zone = {"RCTP", "RCSS", "RCFG"}
    assert got == {
        i: ("typhoon_land", "high", True) if i in in_zone else ("typhoon_land", "medium", False)
        for i in taiwan
    }
    (w,) = cwa.for_airport(bulletins, by["RCSS"].cwa_areas, by["RCSS"].name)
    assert "松山在警戒區" in w.text["zh-TW"]
    assert "Taipei Songshan is in the warning area" in w.text["en"]
    (w,) = cwa.for_airport(bulletins, by["RCKH"].cwa_areas, by["RCKH"].name)
    assert "警戒區" not in w.text["zh-TW"]


def test_cwa_keywords_match_cwa_county_names(airports):
    """每個台灣機場的關鍵字對得到氣象署 `areaDesc` 的縣市寫法（臺中市、臺東縣、連江縣……），
    也對不到別的機場的縣市（「東部」「中部」「南部」只會在警戒區文字裡出現）。"""
    county = {
        "RCTP": "桃園市",
        "RCSS": "臺北市",
        "RCKH": "高雄市",
        "RCMQ": "臺中市",
        "RCNN": "臺南市",
        "RCYU": "花蓮縣",
        "RCFN": "臺東縣",
        "RCQC": "澎湖縣",
        "RCBS": "金門縣",
        "RCFG": "連江縣",
    }
    descs = {
        a["areaDesc"] for a in load_json("cwa_w-c0034-001_land.json")["records"]["info"][0]["area"]
    }
    assert set(county.values()) <= descs  # fixture 裡就是這樣寫
    taiwan = {a.icao: a for a in airports if a.region == "taiwan"}
    assert set(taiwan) == set(county)
    for icao, a in taiwan.items():
        assert len(a.cwa_areas) == len(set(a.cwa_areas)) > 0
        for other, name in county.items():
            hit = cwa.in_zone([name], "", a.cwa_areas)
            same_city = {icao, other} <= {"RCTP", "RCSS"}  # 桃園、松山同一組
            assert hit is (other == icao or same_city), (icao, name)
    assert cwa.in_zone([], "宜蘭、花蓮、臺東應嚴加戒備", taiwan["RCYU"].cwa_areas)
    assert cwa.in_zone([], "東部地區應嚴加戒備", taiwan["RCFN"].cwa_areas)
    assert not cwa.in_zone([], "東部海面航行船隻", taiwan["RCFN"].cwa_areas)
    assert cwa.in_zone([], "澎湖、金門、馬祖應嚴加戒備", taiwan["RCQC"].cwa_areas)
    assert cwa.in_zone([], "澎湖、金門、馬祖應嚴加戒備", taiwan["RCBS"].cwa_areas)
    assert not cwa.in_zone([], "馬祖海面航行船隻", taiwan["RCFG"].cwa_areas)


def test_cwa_south_keywords():
    south = ("南部", "高雄")
    assert cwa.in_zone(["高雄市"], "", south) is True
    assert cwa.in_zone(["臺灣南部海面"], "", south) is False
    assert cwa.in_zone([], "南部地區應嚴加戒備", south) is True
    assert cwa.in_zone([], "南部海面航行船隻", south) is False
    assert cwa.in_zone(["臺北市", "新北市"], "北部地區", south) is False
    assert cwa.in_zone(["臺北市"], "", cwa.TAOYUAN_AREAS) is True


def test_cwa_no_key():
    with pytest.raises(cwa.CwaError) as e:
        cwa.fetch(None, utc(2026, 10, 18))
    assert e.value.code == "no_api_key"


# ---- GRIB：ECMWF、GFS ----


def test_ecmwf_hres_parse(airports):
    run, pts = ecmwf.parse_hres(FIXTURES / "ecmwf_oper_subregion.grib2", airports)
    assert run == utc(2026, 10, 17, 18)
    assert set(pts) == {a.icao for a in airports}  # fixture 只裁了台灣到港澳，框外的取邊上的格點
    g = pts["VHHH"]
    assert [x.end - run for x in g] == [timedelta(hours=h) for h in (87, 90, 93, 96)]
    # 0–90 小時的 10fg 是前 1 小時，93 以後的 10fg3 是前 3 小時
    assert g[0].end - g[0].start == timedelta(hours=1)
    assert g[2].end - g[2].start == timedelta(hours=3)
    # GRIB 是 m/s，解析完換算成節
    assert g[2].gust_kt == pytest.approx(9.08 * KT_PER_MS, abs=0.02)
    # 10u／10v 配區間結束時間往後最近的 6 小時步長（fixture 18Z 起報：87、90 → 90；93、96 → 96）
    assert [round(x.wdir) for x in g] == [42, 42, 2, 2]
    assert pts["RCTP"][0].wdir == pytest.approx(48, abs=1)


def test_ecmwf_hres_parse_wind_from_separate_file(airports, tmp_path):
    """陣風與 10 米風分兩個檔下載時一樣配得起來（風檔只有 6 小時整的步長）。"""
    import eccodes

    gust, wind = tmp_path / "gust.grib2", tmp_path / "wind.grib2"
    with (
        open(FIXTURES / "ecmwf_oper_subregion.grib2", "rb") as src,
        gust.open("wb") as g_out,
        wind.open("wb") as w_out,
    ):
        while (h := eccodes.codes_grib_new_from_file(src)) is not None:
            short, step = eccodes.codes_get(h, "shortName"), eccodes.codes_get(h, "endStep")
            if short in ecmwf.HRES_GUST_PARAMS:
                g_out.write(eccodes.codes_get_message(h))
            elif step % 6 == 0:
                w_out.write(eccodes.codes_get_message(h))
            eccodes.codes_release(h)
    run, pts = ecmwf.parse_hres(gust, airports, wind)
    _, same = ecmwf.parse_hres(FIXTURES / "ecmwf_oper_subregion.grib2", airports)
    assert run == utc(2026, 10, 17, 18)
    for icao in pts:
        assert [(x.end, x.gust_kt, x.wdir) for x in pts[icao]] == [
            (x.end, x.gust_kt, x.wdir) for x in same[icao]
        ]


def test_ecmwf_ens_parse(airports):
    run, pts = ecmwf.parse_ens(FIXTURES / "ecmwf_ep_subregion.grib2", airports)
    assert run == utc(2026, 10, 17, 12)
    w = pts["VHHH"][0]
    assert (w.start - run, w.end - run) == (timedelta(hours=0), timedelta(hours=24))
    assert (w.p10, w.p15, w.p25) == (0.86, 0.07, 0.0)


def test_ecmwf_step_helpers():
    assert ecmwf.hres_steps(6, 144)[:2] == [9, 12]
    assert ecmwf.hres_steps(6, 144)[-1] == 126
    assert ecmwf.hres_steps(36, 240)[-4:] == [141, 144, 150, 156]  # 144 以後只有每 6 小時
    assert ecmwf.hres_steps(36, 144)[-1] == 144
    # 10 米風只抓 6 小時整的步長；陣風區間配結束時間往後最近的那個
    assert [ecmwf.wind_step(s) for s in (3, 6, 9, 87, 90, 93, 144, 150)] == [
        6,
        6,
        12,
        90,
        90,
        96,
        144,
        150,
    ]
    steps = ecmwf.hres_steps(6, 144)
    assert len(steps) == 40
    assert ecmwf.wind_steps(steps) == list(range(12, 127, 6))
    assert ecmwf.wind_steps(ecmwf.hres_steps(36, 240))[-3:] == [144, 150, 156]
    assert ecmwf.ens_windows(0)[:2] == ["0-24", "12-36"]
    assert ecmwf.ens_windows(18)[0] == "0-24"


class FakeClient:
    """假的 `ecmwf.opendata.Client`：照 `plan` 決定每個 source 的 `latest()`／`retrieve()` 結果。"""

    def __init__(self, source, plan, calls, retry):
        self.source, self.plan, self.calls, self.retry = source, plan, calls, retry

    def latest(self, **request):
        self.calls.append(("latest", self.source, request["stream"]))
        r = self.plan["latest"][request["stream"]].get(self.source)
        if isinstance(r, Exception):
            raise r
        if r is None:
            raise ValueError("Cannot establish latest date")
        return r.replace(tzinfo=None)  # ecmwf-opendata 回的是 naive datetime

    def retrieve(self, target, **request):
        self.calls.append(("retrieve", self.source, request["stream"]))
        self.plan.setdefault("requests", []).append((self.source, request))
        # AWS 下載不重試（S3 的 503 Slow Down 一來就換下一個）
        assert self.retry == ({"maximum_retries": 1} if self.source == "aws" else {})
        if self.source not in self.plan["retrieve"]:
            resp = requests.Response()
            resp.status_code = 404
            raise requests.HTTPError("404 Not Found", response=resp)
        fixture = "ecmwf_oper_subregion" if request["stream"] == "oper" else "ecmwf_ep_subregion"
        Path(target).write_bytes((FIXTURES / f"{fixture}.grib2").read_bytes())


def _fake_clients(monkeypatch, plan):
    calls = []
    monkeypatch.setattr(
        ecmwf, "_client", lambda source, **retry: FakeClient(source, plan, calls, retry)
    )
    return calls


def test_ecmwf_latest_from_ecmwf_download_falls_back_from_aws(monkeypatch, airports, tmp_path):
    """ecmwf 的 latest() 成功；aws 還沒有那一報（404）→ 回 ecmwf 下載。"""
    plan = {
        "latest": {
            "oper": {"ecmwf": utc(2026, 10, 17, 18), "aws": utc(2026, 10, 17, 12)},
            "enfo": {"ecmwf": utc(2026, 10, 17, 12)},
        },
        "retrieve": {"ecmwf"},
    }
    calls = _fake_clients(monkeypatch, plan)
    data = ecmwf.fetch(airports, utc(2026, 10, 18, 6), tmp_path)
    assert calls == [
        ("latest", "ecmwf", "oper"),
        ("retrieve", "aws", "oper"),  # 陣風：aws 沒有 → ecmwf
        ("retrieve", "ecmwf", "oper"),
        ("retrieve", "ecmwf", "oper"),  # 10 米風先試陣風成功的 ecmwf
        ("latest", "ecmwf", "enfo"),
        ("retrieve", "aws", "enfo"),
        ("retrieve", "ecmwf", "enfo"),
    ]
    assert (data.run, data.ens_run) == (utc(2026, 10, 17, 18), utc(2026, 10, 17, 12))
    assert (data.mirror, data.ens_mirror, data.ens_error) == ("ecmwf", "ecmwf", None)
    assert data.bytes_downloaded > 0
    assert data.points["VHHH"].hres and data.points["VHHH"].ens
    # HRES 分兩個請求：陣風（10fg／10fg3）全部步長、10 米風只有 6 小時整的步長
    oper = [r for src, r in plan["requests"] if src == "ecmwf" and r["stream"] == "oper"]
    gust_req, wind_req = oper
    assert gust_req["param"] == ["10fg", "10fg3"]
    assert gust_req["step"] == ecmwf.hres_steps(12, 144)  # 18Z 起報、slot0 06Z → rel0=12
    assert wind_req["param"] == ["10u", "10v"]
    assert wind_req["step"] == list(range(18, 133, 6))


def test_ecmwf_latest_429_switches_to_aws(monkeypatch, airports, tmp_path):
    """ecmwf 的 latest() 一直 429（重試用盡）→ 改問 aws 的 latest()，從 aws 下載。"""
    too_many = ecmwf.EcmwfError("HTTP 429", "http_429")
    plan = {
        "latest": {
            "oper": {"ecmwf": too_many, "aws": utc(2026, 10, 17, 18)},
            "enfo": {"ecmwf": too_many, "aws": utc(2026, 10, 17, 12)},
        },
        "retrieve": {"aws", "ecmwf"},
    }
    calls = _fake_clients(monkeypatch, plan)
    data = ecmwf.fetch(airports, utc(2026, 10, 18, 6), tmp_path)
    assert calls == [
        ("latest", "ecmwf", "oper"),
        ("latest", "aws", "oper"),
        ("retrieve", "aws", "oper"),
        ("retrieve", "aws", "oper"),
        ("latest", "ecmwf", "enfo"),
        ("latest", "aws", "enfo"),
        ("retrieve", "aws", "enfo"),
    ]
    assert (data.mirror, data.ens_mirror) == ("aws", "aws")


def test_ecmwf_all_sources_fail(monkeypatch, airports, tmp_path):
    too_many = ecmwf.EcmwfError("HTTP 429", "http_429")
    plan = {"latest": {"oper": {"ecmwf": too_many, "aws": too_many}}, "retrieve": set()}
    _fake_clients(monkeypatch, plan)
    with pytest.raises(ecmwf.EcmwfError) as e:
        ecmwf.fetch(airports, utc(2026, 10, 18, 6), tmp_path)
    assert e.value.code == "http_429"

    plan = {"latest": {"oper": {"ecmwf": utc(2026, 10, 17, 18)}}, "retrieve": set()}
    calls = _fake_clients(monkeypatch, plan)
    with pytest.raises(ecmwf.EcmwfError) as e:
        ecmwf.fetch(airports, utc(2026, 10, 18, 6), tmp_path)
    assert e.value.code == "http_404"
    assert [c[1] for c in calls if c[0] == "retrieve"] == ["aws", "ecmwf", "google"]


def test_ecmwf_client_bounded_retries(monkeypatch):
    """真的 Client：重試上限 3 次、不照伺服器的 Retry-After；用盡後還是 429 就丟 http_429。"""
    import multiurl.retry

    sleeps = []
    monkeypatch.setattr(multiurl.retry, "_logged_sleep", sleeps.append)
    client = ecmwf._client("ecmwf")
    assert (client.maximum_retries, client.retry_after) == (3, 10)
    assert client.use_server_retry_after is False

    heads = []

    def head(url, **kwargs):
        heads.append(url)
        r = requests.Response()
        r.status_code = 429
        r.headers["Retry-After"] = "3600"
        return r

    monkeypatch.setattr(client.session, "head", head)
    with pytest.raises(ecmwf.EcmwfError) as e:
        client.latest(stream="oper", type="fc", param="10fg3", step=144)
    assert e.value.code == "http_429"
    assert len(heads) == 3 and sleeps == [10, 10]
    assert ecmwf._client("aws", **ecmwf.DOWNLOAD_RETRY["aws"]).maximum_retries == 1


def test_gfs_nomads_one_box(airports):
    """NOMADS 備援（H9）：一個框涵蓋全部 51 個機場（外接框 ±1°；HD3 起框變大）。"""
    box = gfs.subregion(airports)
    assert float(box["bottomlat"]) == pytest.approx(6.37)  # 帛琉 7.367
    assert float(box["toplat"]) == pytest.approx(43.77)  # 新千歲 42.77
    assert float(box["leftlon"]) == pytest.approx(102.99)  # 富國島 103.9935
    assert float(box["rightlon"]) == pytest.approx(145.80)  # 關島 144.7973
    assert 6 <= float(box["bottomlat"]) and float(box["toplat"]) <= 44
    assert 102 <= float(box["leftlon"]) and float(box["rightlon"]) <= 146


def test_gfs_parse_one_box_all_airports(airports):
    """2026-10-18 實測 NOMADS 一個框（12Z f120，113 KB）：51 個機場都在框內、都解析得到。"""
    pts = gfs.parse_file(FIXTURES / "gfs_all_f120.grb2", airports)
    assert set(pts) == {a.icao for a in airports}
    for icao, ps in pts.items():
        (p,) = ps
        assert p.valid == utc(2026, 10, 23, 12)
        assert p.gust_kt is not None and 0 < p.gust_kt < 150, icao
        assert p.wdir is not None and 0 <= p.wdir < 360


def test_gfs_parse_file_with_wind(airports):
    by = {a.icao: a for a in airports}
    hkmo = gfs.parse_file(FIXTURES / "gfs_hkmo_f006.grb2", [by["VHHH"], by["VMMC"]])
    tw = gfs.parse_file(FIXTURES / "gfs_tw_f006.grb2", [by[i] for i in ("RCTP", "RCSS", "RCKH")])
    assert set(hkmo) == {"VHHH", "VMMC"} and set(tw) == {"RCTP", "RCSS", "RCKH"}
    (p,) = tw["RCTP"]
    assert p.valid == utc(2026, 10, 18, 6)
    assert p.gust_kt == pytest.approx(2.8 * KT_PER_MS, abs=0.02)
    assert p.wdir == pytest.approx(355.5, abs=0.1)
    (p,) = hkmo["VMMC"]
    assert p.gust_kt == pytest.approx(5.6 * KT_PER_MS, abs=0.02)
    assert p.wdir == pytest.approx(120.8, abs=0.1)


def test_gfs_names():
    assert gfs.file_name(utc(2026, 10, 18, 6), 12) == "gfs.t06z.pgrb2.0p25.f012"
    assert gfs.run_dir(utc(2026, 10, 18, 6)) == "/gfs.20261018/06/atmos"


# 2026-10-18 實測 S3 `gfs.t06z.pgrb2.0p25.f120.idx` 的幾行（其他行省略；byte 起點是真的）
REAL_IDX = """\
13:5292860:d=2026101806:VIS:surface:120 hour fcst:
14:5891123:d=2026101806:GUST:surface:120 hour fcst:
15:6503070:d=2026101806:HGT:0.01 mb:120 hour fcst:
587:421612095:d=2026101806:TMP:2 m above ground:120 hour fcst:
588:422538109:d=2026101806:UGRD:10 m above ground:120 hour fcst:
589:423505789:d=2026101806:VGRD:10 m above ground:120 hour fcst:
590:424452587:d=2026101806:ICEG:10 m above mean sea level:120 hour fcst:
"""


def test_gfs_idx_byte_ranges():
    # GUST 單獨一段；UGRD、VGRD 相鄰併成一段；都到下一筆起點的前一個 byte
    assert gfs.byte_ranges(REAL_IDX) == [(5891123, 6503069), (422538109, 424452586)]
    # 要的那筆是最後一筆：到檔尾（None）
    tail = "1:0:d=x:GUST:surface:6 hour fcst:\n2:10:d=x:UGRD:10 m above ground:6 hour fcst:\n"
    tail += "3:25:d=x:VGRD:10 m above ground:6 hour fcst:\n"
    assert gfs.byte_ranges(tail) == [(0, None)]
    with pytest.raises(gfs.GfsError) as e:
        gfs.byte_ranges(REAL_IDX.replace("GUST", "XXXX"))
    assert e.value.code == "bad_idx"


def _grib_messages(path: Path) -> list[bytes]:
    b = path.read_bytes()
    out, i = [], 0
    while i < len(b):
        n = int.from_bytes(b[i + 8 : i + 16], "big")  # GRIB2 第 0 段的總長度
        out.append(b[i : i + n])
        i += n
    return out


class FakeResponse:
    def __init__(self, status_code: int, content: bytes = b""):
        self.status_code, self.content = status_code, content
        self.text = content.decode("utf-8", "replace")


class FakeNoaa:
    """假的 `http_get`：S3 照 `Range` 回假的全球檔片段（真的 GRIB 訊息夾在別的資料中間），
    NOMADS filter 回 fixture 的小檔。`aws`／`nomads` 是各自的行為：
    `"ok"`、`"403"`、`"not_grib"`。"""

    def __init__(self, aws="ok", nomads="ok", aws_ok_steps=None, s3_runs=None):
        self.aws, self.nomads = aws, nomads
        self.aws_ok_steps = aws_ok_steps  # 只有這些步長 AWS 正常（None＝全部）
        self.s3_runs = s3_runs  # S3 上有哪些時次（None＝全部）
        self.calls: list[str] = []
        gust, u, v = _grib_messages(FIXTURES / "gfs_tw_f006.grb2")
        self.full = b"P" * 100 + gust + b"H" * 50 + u + v + b"I" * 30
        self.idx = (
            "1:0:d=x:PRMSL:mean sea level:6 hour fcst:\n"
            "2:100:d=x:GUST:surface:6 hour fcst:\n"
            f"3:{100 + len(gust)}:d=x:HGT:0.01 mb:6 hour fcst:\n"
            f"4:{150 + len(gust)}:d=x:UGRD:10 m above ground:6 hour fcst:\n"
            f"5:{150 + len(gust) + len(u)}:d=x:VGRD:10 m above ground:6 hour fcst:\n"
            f"6:{150 + len(gust) + len(u) + len(v)}:d=x:ICEG:10 m above msl:6 hour fcst:\n"
        )

    def __call__(self, url, *, params=None, headers=None, ok_404=False, error=None, **kw):
        host = "aws" if url.startswith(gfs.S3_URL) else "nomads"
        kind = "idx" if url.endswith(".idx") else "range" if headers else "filter"
        self.calls.append(f"{host}:{kind}")
        mode = self.aws if host == "aws" else self.nomads
        fh = int(url.rsplit(".f", 1)[1][:3]) if host == "aws" or kind == "idx" else None
        if host == "aws" and self.aws_ok_steps is not None and fh not in self.aws_ok_steps:
            mode = "not_grib"
        if mode == "403":
            raise error("HTTP 403", "http_403")
        if kind == "idx":
            if (
                self.s3_runs is not None
                and host == "aws"
                and not any(f"{r}/atmos" in url for r in self.s3_runs)
            ):
                return FakeResponse(404)
            return FakeResponse(200, self.idx.encode())
        if kind == "range":
            if mode == "not_grib":
                return FakeResponse(200, b"<html>SlowDown</html>")
            a, b = headers["Range"].removeprefix("bytes=").split("-")
            return FakeResponse(206, self.full[int(a) : int(b) + 1 if b else None])
        return FakeResponse(200, (FIXTURES / "gfs_all_f120.grb2").read_bytes())


def _fake_noaa(monkeypatch, **kw) -> FakeNoaa:
    fake = FakeNoaa(**kw)
    monkeypatch.setattr(gfs, "http_get", fake)
    monkeypatch.setattr(gfs.time, "sleep", lambda s: None)
    return fake


def test_gfs_find_latest_run_aws_then_nomads(monkeypatch):
    now, slot0 = utc(2026, 10, 18, 14, 33), utc(2026, 10, 18, 12)
    # S3 還沒有 12Z → 往前一報 06Z（在 S3 找到）
    fake = _fake_noaa(monkeypatch, s3_runs=["06"])
    assert gfs.find_latest_run(now, slot0) == (utc(2026, 10, 18, 6), "aws")
    assert fake.calls == ["aws:idx", "aws:idx"]
    # S3 403 → 改看 NOMADS
    fake = _fake_noaa(monkeypatch, aws="403")
    assert gfs.find_latest_run(now, slot0) == (utc(2026, 10, 18, 12), "nomads")
    assert fake.calls == ["aws:idx", "nomads:idx"]
    # 兩邊都 403 → 丟最後一個的代碼
    _fake_noaa(monkeypatch, aws="403", nomads="403")
    with pytest.raises(gfs.GfsError) as e:
        gfs.find_latest_run(now, slot0)
    assert e.value.code == "http_403"


def test_gfs_fetch_from_aws(monkeypatch, airports, tmp_path):
    fake = _fake_noaa(monkeypatch)
    data = gfs.fetch(airports, utc(2026, 10, 18, 8, 10), utc(2026, 10, 18, 6), tmp_path)
    assert (data.run, data.mirror) == (utc(2026, 10, 18, 6), "aws")
    assert "nomads" not in "".join(fake.calls)
    # 每個步長：.idx 一個、GUST 一段、UGRD＋VGRD 一段
    assert fake.calls[1:5] == ["aws:idx", "aws:range", "aws:range", "aws:idx"]
    assert fake.calls.count("aws:range") == 2 * 21
    (gust, u, v) = _grib_messages(FIXTURES / "gfs_tw_f006.grb2")
    assert data.bytes_downloaded == 21 * (len(gust) + len(u) + len(v))
    pts = data.points["RCTP"]
    assert len(pts) == 21
    # fixture 是 f006 的檔，每個步長都回它；值與 NOMADS 小檔解析的一樣
    assert pts[0].gust_kt == pytest.approx(2.8 * KT_PER_MS, abs=0.02)
    assert pts[0].wdir == pytest.approx(355.5, abs=0.1)


def test_gfs_fetch_aws_failure_falls_back_to_nomads(monkeypatch, airports, tmp_path):
    """AWS 第三個步長回的不是 GRIB → 那個步長起改 NOMADS，之後不回 AWS。"""
    fake = _fake_noaa(monkeypatch, aws_ok_steps={0, 6})
    data = gfs.fetch(airports, utc(2026, 10, 18, 8, 10), utc(2026, 10, 18, 6), tmp_path)
    assert data.mirror == "nomads"
    i = fake.calls.index("nomads:filter")
    assert fake.calls[:i] == ["aws:idx"] + ["aws:idx", "aws:range", "aws:range"] * 2 + [
        "aws:idx",
        "aws:range",
    ]
    assert set(fake.calls[i:]) == {"nomads:filter"}
    assert fake.calls[i:].count("nomads:filter") == 19  # 一個框 × 剩下的 19 個步長
    assert all(len(data.points[a.icao]) == 21 for a in airports)
    # 後面的步長是 NOMADS 一個框的檔（fixture 是 12Z f120）
    nomads = gfs.parse_file(FIXTURES / "gfs_all_f120.grb2", airports)
    assert data.points["ROAH"][-1].gust_kt == nomads["ROAH"][0].gust_kt


def test_gfs_fetch_nomads_when_aws_down(monkeypatch, airports, tmp_path):
    fake = _fake_noaa(monkeypatch, aws="403")
    data = gfs.fetch(airports, utc(2026, 10, 18, 8, 10), utc(2026, 10, 18, 6), tmp_path)
    assert data.mirror == "nomads"
    assert fake.calls[:3] == ["aws:idx", "nomads:idx", "nomads:filter"]
    assert "aws" not in "".join(fake.calls[1:])


# ---- 澳門 SMG ----


def _smg(kind):
    return {"c": (FIXTURES / f"smg_c_typhoon_{kind}.xml").read_text("utf-8")}


def test_smg_no_signal_real_sample():
    raw = {lang: (FIXTURES / f"smg_{lang}_typhoon_none.xml").read_text("utf-8") for lang in "ce"}
    assert smg.parse_signal(raw) is None


def test_smg_signal3_real_sample():
    s = smg.parse_signal(_smg("sig3"))
    assert (s.code, s.level) == ("TC3", "medium")
    assert s.text == {
        "zh-TW": "澳門三號風球",
        "zh-HK": "澳門三號風球",
        "zh-CN": "澳门三号风球",
        "en": "Macao Tropical Cyclone Signal No. 3",
    }
    assert s.issued_at == "2026-07-25T10:00:00Z"  # SignalChangedAt 18:00 澳門時間
    assert "三號風球仍然生效" in s.detail


def test_smg_pending_upgrade_counts():
    s = smg.parse_signal(_smg("sig1_pending3"))
    assert (s.code, s.level) == ("TC1", "medium")
    assert s.text["zh-TW"] == "澳門一號風球；預告07-25 18:00改發三號風球"
    assert s.text["zh-CN"] == "澳门一号风球；预告07-25 18:00改发三号风球"
    assert "Signal No. 3 expected at 07-25 18:00" in s.text["en"]


def test_smg_cancel_real_sample():
    assert smg.parse_signal(_smg("cancel")) is None


def test_smg_signal8_direction():
    xml = _smg("sig3")["c"]
    for tag in ("Inforce", "Warncode"):
        xml = xml.replace(f"<{tag}>3</{tag}>", f"<{tag}>8ne</{tag}>")
    s = smg.parse_signal({"c": xml})
    assert (s.code, s.level) == ("TC8NE", "high")
    assert s.text["zh-TW"] == "澳門八號東北風球"
    assert s.text["zh-CN"] == "澳门八号东北风球"
    assert s.text["en"] == "Macao Tropical Cyclone Signal No. 8 NE"


@pytest.mark.parametrize(
    "inforce,level",
    [("1", "low"), ("3", "medium"), ("8SW", "high"), ("9", "high"), ("10", "high")],
)
def test_smg_levels(inforce, level):
    assert smg.signal_level(smg.normalize(inforce)) == level


@pytest.mark.parametrize("inforce", ["0", "-", "NIL", "", None, "8"])
def test_smg_not_a_signal(inforce):
    assert smg.normalize(inforce) is None


def test_smg_bad_xml():
    with pytest.raises(smg.SmgError) as e:
        smg.parse_signal({"c": "<html>"})
    assert e.value.code == "bad_xml"


# ---- NWS（關島，HD3） ----


def test_nws_no_tc_alert_real_sample():
    """2026-10-18 17:5xZ 的 `/alerts/active?zone=GUZ001`：只有 Wind Advisory 等，沒有颱風的。"""
    doc = load_json("nws_alerts_active_guz001_none.json")
    assert {f["properties"]["event"] for f in doc["features"]} >= {"Wind Advisory", "Flood Watch"}
    assert nws.parse_alerts(doc) == []


def test_nws_typhoon_real_sample():
    """Champi（29W）期間的真實警報：颱風警報（更新）、颱風守視、颱風警報解除、Flood Watch。"""
    alerts = nws.parse_alerts(load_json("nws_alerts_active_guz001_typhoon.json"))
    assert [(a.kind, a.level, a.code) for a in alerts] == [
        ("typhoon_warning", "high", "Typhoon Warning"),
        ("typhoon_watch", "medium", "Typhoon Watch"),
    ]  # 解除（messageType Cancel）與 Flood Watch 不算
    w = alerts[0]
    assert w.zones == ("GUZ001",)
    assert w.issued_at == "2026-10-18T05:01:00Z"  # sent 15:01 ChST（+10:00）
    assert w.detail == "TYPHOON WARNING REMAINS IN EFFECT"
    assert w.text == {
        "zh-TW": "颱風警報生效中（美國國家氣象局）",
        "zh-HK": "颱風警告生效中（美國國家氣象局）",
        "zh-CN": "台风警报生效中（美国国家气象局）",
        "en": "Typhoon Warning issued October 18 at 3:01PM ChST by NWS Tiyan GU",
    }
    assert [a.kind for a in nws.for_zone(alerts, "GUZ001")] == ["typhoon_warning", "typhoon_watch"]
    assert [a.kind for a in nws.for_zone(alerts, "MPZ001")] == ["typhoon_watch"]  # 守視涵蓋北馬
    assert nws.for_zone(alerts, "PWZ003") == []


@pytest.mark.parametrize(
    ("event", "kind", "level"),
    [
        ("Typhoon Warning", "typhoon_warning", "high"),
        ("Tropical Storm Warning", "ts_warning", "high"),
        ("Typhoon Watch", "typhoon_watch", "medium"),
        ("Tropical Storm Watch", "ts_watch", "medium"),
    ],
)
def test_nws_event_levels(event, kind, level):
    doc = load_json("nws_alerts_active_guz001_typhoon.json")
    f = doc["features"][0]
    f["properties"].update(event=event, headline=f"{event} issued by NWS Tiyan GU")
    (a,) = nws.parse_alerts({"features": [f]})
    assert (a.kind, a.level, a.code, a.text["en"]) == (
        kind,
        level,
        event,
        f"{event} issued by NWS Tiyan GU",
    )
    assert a.text["zh-TW"].endswith("生效中（美國國家氣象局）")


def test_nws_skips_test_messages_and_keeps_latest():
    f = load_json("nws_alerts_active_guz001_typhoon.json")["features"][0]
    old = json.loads(json.dumps(f))
    old["properties"].update(sent="2026-10-18T12:02:00+10:00", headline="older")
    exercise = json.loads(json.dumps(f))
    exercise["properties"]["status"] = "Exercise"
    alerts = nws.parse_alerts({"features": [old, f, exercise]})
    assert len(alerts) == 2  # 演習的不算
    (a,) = nws.for_zone(alerts, "guz001")  # 同一種取 sent 最新的；zone 不分大小寫
    assert a.issued_at == "2026-10-18T05:01:00Z"
    # 沒有 geocode 時從 affectedZones 取 zone
    del f["properties"]["geocode"]
    assert nws.parse_alerts({"features": [f]})[0].zones == ("GUZ001",)


def test_nws_bad_format():
    with pytest.raises(nws.NwsError) as e:
        nws.parse_alerts({"title": "no features"})
    assert e.value.code == "bad_format"


def test_nws_fetch_one_request_for_all_zones(monkeypatch):
    calls = []

    def fake_get(url, *, params=None, headers=None, error=None, **kw):
        calls.append((url, params, headers, error))
        return _Resp(200, (FIXTURES / "nws_alerts_active_guz001_typhoon.json").read_bytes())

    monkeypatch.setattr(nws, "http_get", fake_get)
    data = nws.fetch(["GUZ001", "guz001", "PWZ003"])
    assert calls == [
        (nws.URL, {"zone": "GUZ001,PWZ003"}, {"Accept": "application/geo+json"}, nws.NwsError)
    ]
    assert [a.kind for a in data.alerts] == ["typhoon_warning", "typhoon_watch"]
    assert data.raw["title"].startswith("Current watches")


def test_nws_fetch_without_zone(monkeypatch):
    monkeypatch.setattr(nws, "http_get", lambda *a, **k: pytest.fail("不該連網"))
    with pytest.raises(nws.NwsError) as e:
        nws.fetch([])
    assert e.value.code == "no_zone"
    with pytest.raises(nws.NwsError):
        nws.fetch(["", ""])


def test_nws_fetch_not_json(monkeypatch):
    monkeypatch.setattr(nws, "http_get", lambda *a, **k: _Resp(200, b"<html>"))
    with pytest.raises(nws.NwsError) as e:
        nws.fetch(["GUZ001"])
    assert e.value.code == "bad_json"


# ---- 航班 ----


def test_tpe_parse_big5():
    rows = flights.parse_tpe((FIXTURES / "tpe_flights_big5.txt").read_bytes())
    assert len(rows) == 14
    assert rows[0]["airlineName"] == "真航空"
    assert rows[0]["airportZh"] == "仁川"
    assert rows[0]["status"].endswith("ARRIVED")


def test_tsa_khh_mfm_samples():
    tsa = load_json("tsa_intl_departure.json")
    assert tsa[0]["UpAirportCode"] == "TSA" and tsa[0]["AirFlyStatus"]
    khh = load_json("khh_intdep.json")
    assert khh[0]["airLineNum"] == "IT284" and khh[0]["airFlyStatus"] == "離站"
    mfm = flights.parse_mfm(load_json("mfm_departure_en.json"))
    assert mfm[0]["flightNo"] == "TW650"
    # 文件範例的包法
    assert flights.parse_mfm({"data": json.dumps(mfm)}) == mfm
    with pytest.raises(flights.FlightsError):
        flights.parse_mfm({"error": "x"})


def test_flights_fetch_skips_failed_airport(monkeypatch):
    hk = load_json("hkg_arrival.json")
    monkeypatch.setattr(flights, "fetch_hkg", lambda now: {"arrival": hk, "departure": []})
    monkeypatch.setattr(flights, "fetch_tpe", lambda: {"rows": []})
    monkeypatch.setattr(flights, "fetch_tsa", lambda: {})
    monkeypatch.setattr(flights, "fetch_khh", lambda: {})

    def down():
        raise flights.FlightsError("down", "timeout")

    monkeypatch.setattr(flights, "fetch_mfm", down)
    data = flights.fetch(utc(2026, 10, 18, 7, 25))
    assert data.errors == {"VMMC": "timeout"}
    assert sorted(data.snapshots) == ["RCKH", "RCSS", "RCTP", "VHHH"]
    assert data.snapshots["VHHH"]["arrival"] == hk


def test_hkg_fetches_yesterday_and_today(monkeypatch):
    calls = []

    class Resp:
        def __init__(self, params):
            self.params = params

        def json(self):
            return [{"date": self.params["date"], "list": []}]

    def fake_get(url, params=None, **kw):
        calls.append((params["date"], params["arrival"]))
        return Resp(params)

    monkeypatch.setattr(flights, "http_get", fake_get)
    out = flights.fetch_hkg(utc(2026, 10, 18, 20, 25))  # 香港 10/19 04:25
    assert calls == [
        ("2026-10-18", "false"),
        ("2026-10-18", "true"),
        ("2026-10-19", "false"),
        ("2026-10-19", "true"),
    ]
    assert [g["date"] for g in out["departure"]] == ["2026-10-18", "2026-10-19"]

    # 昨天的抓不到：只用今天的；今天的抓不到：整個機場失敗
    def flaky(url, params=None, **kw):
        if params["date"] == "2026-10-18":
            raise flights.FlightsError("down", "timeout")
        return Resp(params)

    monkeypatch.setattr(flights, "http_get", flaky)
    out = flights.fetch_hkg(utc(2026, 10, 18, 20, 25))
    assert [g["date"] for g in out["arrival"]] == ["2026-10-19"]
    with pytest.raises(flights.FlightsError):
        flights.fetch_hkg(utc(2026, 10, 18, 10))  # 香港 10/18 18:00，今天就是 10/18


def test_cwa_tls_adapter_keeps_verification_but_not_strict():
    import ssl

    from hongthai.sources import NonStrictTLSAdapter

    ctx = NonStrictTLSAdapter._context()
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname
    assert not ctx.verify_flags & ssl.VERIFY_X509_STRICT
