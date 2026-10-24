"""Open-Meteo 的 ICON、JMA GSM、WeatherNext 2 系集（HD16）：解析、換成 6 小時格、請求與失敗。

fixture 是 2026-10-20 11:17Z 一次 51 個機場的真實回應，裁成桃園、石垣、新千歲三筆（系集只留 8 個
成員；`tests/fixtures/README.md`）。
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from conftest import load_json, utc

from hongthai import build
from hongthai.assess import GustFactor, ensemble_for_slot, hourly_for_slot
from hongthai.config import Runway, Thresholds
from hongthai.sources import openmeteo
from hongthai.sources.openmeteo import OmHour

ICAOS = ["RCTP", "ROIG", "RJCC"]
TH = Thresholds()


@pytest.fixture
def hourly():
    return openmeteo.parse_forecast(load_json("openmeteo_forecast_3.json"), ICAOS)


@pytest.fixture
def ens():
    return openmeteo.parse_ensemble(load_json("openmeteo_ensemble_3x8.json"), ICAOS)


def test_parse_forecast_real_response(hourly):
    # HD16 的 fixture 沒有 HD33b 三個旁觀模式的欄位 → 那三個丟掉（`{}`），ICON、JMA 照用
    assert set(hourly) == {"icon", "jma", *openmeteo.OBSERVER_MODELS}
    assert all(hourly[mid] == {} for mid in openmeteo.OBSERVER_MODELS)
    for mid in ("icon", "jma"):
        assert list(hourly[mid]) == ICAOS
        for rows in hourly[mid].values():
            assert len(rows) == 144
            assert rows[0].valid == utc(2026, 10, 20, 0)
            assert rows[-1].valid == utc(2026, 10, 25, 23)
    icon, jma = hourly["icon"]["ROIG"], hourly["jma"]["ROIG"]
    # 2026-10-20 實抓：ICON 有陣風、JMA 沒有；兩個都沒有能見度；都有雨量、降雪、天氣碼
    assert all(h.gust_kt is not None for h in icon)
    assert all(h.gust_kt is None for h in jma)
    assert all(h.vis_m is None for h in icon + jma)
    assert all(h.precip_mm is not None and h.code is not None for h in icon + jma)
    assert max(h.gust_kt for h in icon) == 148.5  # 29W 經過石垣
    h = next(h for h in icon if h.valid == utc(2026, 10, 22, 5))
    assert (h.wind_kt, h.wdir, h.gust_kt, h.precip_mm, h.snow_mm) == (29.5, 25.0, 50.7, 0.2, 0.0)


def test_parse_ensemble_real_response(ens):
    steps, members = ens
    assert members == 8 and list(steps) == ICAOS
    roig = steps["ROIG"]
    assert len(roig) == 24
    assert [s.valid for s in roig[:2]] == [utc(2026, 10, 20, 0), utc(2026, 10, 20, 6)]
    s = next(s for s in roig if s.valid == utc(2026, 10, 22, 6))
    # 成員 0 是不帶後綴的 `wind_speed_10m`，排第一個
    assert len(s.winds) == 8 and s.winds[0] == 41.4


def test_icon_slot_real(hourly):
    """石垣 10/22 00–06Z：陣風取 (00, 06] 的小時裡最大（05Z 的 50.7，同樣大取先的），平均風是
    同一小時的；雨量 (00, 06] 加總；側風每小時用陣風算再取大。"""
    start, end = utc(2026, 10, 22, 0), utc(2026, 10, 22, 6)
    rwy = (Runway("04/22", (40.0, 220.0)),)
    d = hourly_for_slot(hourly["icon"]["ROIG"], start, end, rwy)
    assert d == {
        "windKt": 29.5,
        "gustKt": 50.7,
        "crosswindKt": 13.1,  # 05Z：50.7 × |sin(25° − 40°)|
        "rain6hMm": 1.2,
        "ptype": "rain",
        "visibilityM": None,
    }
    calm = hourly_for_slot(hourly["icon"]["RJCC"], utc(2026, 10, 20, 6), utc(2026, 10, 20, 12))
    assert (calm["gustKt"], calm["rain6hMm"], calm["ptype"]) == (4.3, 0.0, "none")


def test_jma_slot_estimated_real(hourly):
    """JMA GSM 沒有陣風：[00, 06] 小時裡最大的平均風（06Z 36.7 節）× G。"""
    start, end = utc(2026, 10, 22, 0), utc(2026, 10, 22, 6)
    d = hourly_for_slot(hourly["jma"]["ROIG"], start, end, (), GustFactor(1.4, "run"))
    assert (d["windKt"], d["gustKt"], d["gustFactor"], d["gustFactorBasis"]) == (
        36.7,
        51.4,
        1.4,
        "run",
    )
    assert (d["rain6hMm"], d["ptype"], d["visibilityM"], d["crosswindKt"]) == (
        2.4,
        "rain",
        None,
        None,
    )


def _hours(precip, snow_cm=0.0, code=61, n=6):
    t0 = utc(2026, 12, 10, 0)
    return [
        OmHour(t0 + timedelta(hours=i), 10.0, 90.0, 20.0, precip, snow_cm / 0.7, None, code)
        for i in range(1, n + 1)
    ]


@pytest.mark.parametrize(
    ("precip", "snow_cm", "code", "ptype"),
    [
        (0.0, 0.0, 0, "none"),
        (0.01, 0.0, 61, "none"),  # 6 小時 0.06 mm < 0.1
        (1.0, 0.0, 61, "rain"),
        (1.0, 0.4, 71, "snow"),  # 降雪水當量 0.57 mm ≥ 雨量的一半
        (1.0, 0.3, 71, "rain"),  # 0.43 mm < 一半
        (1.0, 0.0, 66, "freezing_rain"),
        (1.0, 0.0, 57, "freezing_drizzle"),
    ],
)
def test_slot_ptype(precip, snow_cm, code, ptype):
    assert openmeteo.slot_ptype(_hours(precip, snow_cm, code)) == ptype


def test_slot_without_data():
    start, end = utc(2026, 10, 22, 0), utc(2026, 10, 22, 6)
    assert hourly_for_slot(None, start, end) == {
        "windKt": None,
        "gustKt": None,
        "crosswindKt": None,
        "rain6hMm": None,
        "ptype": None,
        "visibilityM": None,
    }
    assert openmeteo.slot_ptype([]) is None
    assert ensemble_for_slot(None, start, end, TH) == {
        "windKt": None,
        "gustKt": None,
        "p49Kt": None,
    }


def test_ensemble_slot_real(ens):
    """石垣 10/22 00–06Z，8 個成員取頭尾兩點大的風：41.4、40.7、41.4、45.6、40.2、36.5、39.9、38.5。
    G 1.2：估算陣風 ≥ 48 節的有 5 個（41.4×2、40.7、45.6、40.2）→ 0.62；中位數 40.45 → 40.5。"""
    steps, _ = ens
    start, end = utc(2026, 10, 22, 0), utc(2026, 10, 22, 6)
    d = ensemble_for_slot(steps["ROIG"], start, end, TH, GustFactor(1.2, "airport30d"))
    assert d == {
        "windKt": 40.5,
        "gustKt": 48.6,
        "gustFactor": 1.2,
        "gustFactorBasis": "airport30d",
        "p49Kt": 0.62,
    }
    # G 1.4 全部 ≥ 48；機場的門檻改高就變少
    assert ensemble_for_slot(steps["ROIG"], start, end, TH, GustFactor(1.4, "run"))["p49Kt"] == 1.0
    high = Thresholds(model_high_gust_kt=60)
    assert (
        ensemble_for_slot(steps["ROIG"], start, end, high, GustFactor(1.4, "run"))["p49Kt"] == 0.12
    )
    assert ensemble_for_slot(steps["RJCC"], start, end, TH)["p49Kt"] == 0.0


def test_ensemble_member_without_values_not_counted():
    t0 = utc(2026, 10, 22, 0)
    steps = [
        openmeteo.EnsStep(t0, (40.0, None, 10.0)),
        openmeteo.EnsStep(t0 + timedelta(hours=6), (30.0, None, 20.0)),
    ]
    d = ensemble_for_slot(steps, t0, t0 + timedelta(hours=6), TH, GustFactor(1.4, "run"))
    assert d["p49Kt"] == 0.5  # 2 個有值的成員裡 1 個（40 × 1.4 = 56）
    assert d["windKt"] == 30.0  # 40 與 20 的中位數


def test_weighted_calls():
    """Open-Meteo 文件 API 頁的公式：51 個機場一報 71.4 ＋ 326.4 ＝ 397.8 次（< 每分鐘 600），一天
    4 報約 1,591 次。系集照提示詞抓 3 個變數會是 979.2 次，一個請求就超過每分鐘 600。
    HD33b：預報多三個模式（5 個模式）→ 178.5 ＋ 326.4 ＝ 504.9 次，還在每分鐘 600 內。"""
    assert openmeteo.forecast_calls(51, 2) == 71.4
    assert openmeteo.forecast_calls(51) == 178.5  # HD33b
    assert openmeteo.ensemble_calls(51) == 326.4
    assert round(openmeteo.forecast_calls(51) + openmeteo.ensemble_calls(51), 1) == 504.9 < 600
    assert round(504.9 * 4, 1) == 2019.6 < 10_000
    assert openmeteo.weighted_calls(3, 64, 6, 51) == 979.2
    assert openmeteo.weighted_calls(1, 1, 7, 1) == 1.0  # 一地 7 天單變數
    assert openmeteo.weighted_calls(20, 1, 7, 1) == 2.0  # 超過 10 個變數
    assert openmeteo.weighted_calls(10, 1, 28, 1) == 2.0  # 超過 2 週
    assert round((71.4 + 326.4) * 4, 1) == 1591.2 < 5000


class _Resp:
    def __init__(self, doc, size=100):
        self.doc, self.content = doc, b"x" * size

    def json(self):
        return self.doc


def _airports(airports):
    return [a for a in airports if a.icao in ICAOS]


def test_fetch_requests_and_runs(monkeypatch, airports):
    docs = {
        openmeteo.FORECAST_URL: load_json("openmeteo_forecast_3.json"),
        openmeteo.ENSEMBLE_URL: load_json("openmeteo_ensemble_3x8.json"),
    }
    meta = {
        openmeteo.META_URLS["icon"]: 1792476000,  # 2026-10-20T06:00Z
        openmeteo.META_URLS["jma"]: 1792476000,
        openmeteo.META_URLS["gem"]: 1792454400,  # 2026-10-20T00:00Z（HD33b）
    }
    asked = []

    def fake_get(url, **kw):
        asked.append((url, kw))
        if url in meta:
            return _Resp({"last_run_initialisation_time": meta[url]})
        if url in docs:
            return _Resp(docs[url], 1000)
        raise openmeteo.OpenMeteoError(f"{url}: timeout", "timeout")  # WN2 的 metadata 問不到

    monkeypatch.setattr(openmeteo, "http_get", fake_get)
    aps = _airports(airports)
    data = openmeteo.fetch(aps)
    # 先兩個資料請求（不重試、60 秒逾時）、再六個 metadata（5 秒逾時）；同一個 Session。HD33b 的三個
    # 旁觀模式併在預報那個請求，請求數不變
    assert [u for u, _ in asked] == [*docs, *openmeteo.META_URLS.values()]
    fc_kw, ens_kw = asked[0][1], asked[1][1]
    assert (fc_kw["retries"], fc_kw["timeout"]) == (1, 60)
    assert {kw["timeout"] for _, kw in asked[2:]} == {5}
    assert len({id(kw["session"]) for _, kw in asked}) == 1
    assert fc_kw["params"] == {
        "latitude": ",".join(f"{a.lat:g}" for a in aps),
        "longitude": ",".join(f"{a.lon:g}" for a in aps),
        "models": "icon_global,jma_gsm,gem_global,meteofrance_arpege_world,cma_grapes_global",
        "hourly": "wind_speed_10m,wind_direction_10m,wind_gusts_10m,precipitation,snowfall,"
        "visibility,weather_code",
        "forecast_days": 6,
        "wind_speed_unit": "kn",
        "timezone": "UTC",
    }
    assert ens_kw["params"]["models"] == "google_weathernext2_ensemble"
    assert ens_kw["params"]["hourly"] == "wind_speed_10m"
    assert ens_kw["params"]["temporal_resolution"] == "native"
    assert data.runs == {
        "icon": utc(2026, 10, 20, 6),
        "jma": utc(2026, 10, 20, 6),
        "wn2-ens": None,
        "gem": utc(2026, 10, 20, 0),
        "arpege": None,
        "cma": None,
    }
    assert data.meta_errors == dict.fromkeys(("wn2-ens", "arpege", "cma"), "timeout")
    # fixture 沒有三個旁觀模式的欄位 → 丟掉、記原因
    assert data.model_errors == dict.fromkeys(openmeteo.OBSERVER_MODELS, "missing")
    assert data.bytes_downloaded == 2000 and data.members == 8
    assert data.calls == round(openmeteo.forecast_calls(3) + openmeteo.ensemble_calls(3), 1)
    assert set(data.raw) == {"forecast", "ensemble"}
    assert list(data.hourly["icon"]) == ICAOS == list(data.ensemble)


@pytest.mark.parametrize(
    ("bad", "code"),
    [
        ({"error": True, "reason": "Parameter 'models' invalid"}, "api_error"),
        ([{"hourly": {"time": []}}], "bad_format"),  # 地點數不對
    ],
)
def test_fetch_bad_response(monkeypatch, airports, bad, code):
    monkeypatch.setattr(
        openmeteo,
        "http_get",
        lambda url, **kw: _Resp(bad if url == openmeteo.FORECAST_URL else {"x": 1}),
    )
    with pytest.raises(openmeteo.OpenMeteoError) as e:
        openmeteo.fetch(_airports(airports))
    assert e.value.code == code


def test_wrong_units_rejected():
    doc = load_json("openmeteo_forecast_3.json")
    doc[0]["hourly_units"]["wind_speed_10m_icon_global"] = "km/h"
    with pytest.raises(openmeteo.OpenMeteoError) as e:
        openmeteo.parse_forecast(doc, ICAOS)
    assert e.value.code == "bad_units"


def test_failure_returns_none_in_build(monkeypatch, airports):
    """請求失敗（逾時、HTTP 錯誤）→ `_call` 回 None、`sources.openmeteo.ok` 是 false＋`error`。"""

    def down(url, **kw):
        if "meta.json" in url:
            return _Resp({"last_run_initialisation_time": 1792476000})
        raise openmeteo.OpenMeteoError(f"{url}: HTTP 429", "http_429")

    monkeypatch.setattr(openmeteo, "http_get", down)
    status: dict = {}
    assert build._call("openmeteo", lambda: openmeteo.fetch(_airports(airports)), status) is None
    assert status["openmeteo"]["ok"] is False and status["openmeteo"]["error"] == "http_429"


# ---- HD33b：三個旁觀模式（GEM、ARPEGE、CMA；UKMO 是 CC BY-SA 4.0，不放） ----


def _with_observers(doc: list[dict], drop: tuple[str, ...] = (), gustless: tuple[str, ...] = ()):
    """在 HD16 的 fixture 補三個旁觀模式的欄位（照 ICON 的值：GEM ×1.1、ARPEGE ×1.2、CMA ×0.9）。
    `drop` 的模式不補（整欄沒有）；`gustless` 的模式陣風全 null（同 JMA）。"""
    scale = {"gem": 1.1, "arpege": 1.2, "cma": 0.9}
    for loc in doc:
        h, units = loc["hourly"], loc["hourly_units"]
        for mid, k in scale.items():
            if mid in drop:
                continue
            suffix = openmeteo.FORECAST_MODELS[mid]
            for v in openmeteo.FORECAST_VARS:
                src = h[f"{v}_icon_global"]
                if v in ("wind_speed_10m", "wind_gusts_10m"):
                    src = [None if x is None else round(x * k, 1) for x in src]
                if v == "wind_gusts_10m" and mid in gustless:
                    src = [None] * len(src)
                h[f"{v}_{suffix}"] = src
                units[f"{v}_{suffix}"] = units[f"{v}_icon_global"]
    return doc


def test_parse_forecast_observers():
    """三個旁觀模式和 ICON、JMA 從同一份回應解析；陣風全 null 的模式（這裡假設 CMA）照樣有
    平均風。"""
    doc = _with_observers(load_json("openmeteo_forecast_3.json"), gustless=("cma",))
    errors: dict[str, str] = {}
    hourly = openmeteo.parse_forecast(doc, ICAOS, errors=errors)
    assert errors == {}
    for mid in openmeteo.OBSERVER_MODELS:
        assert list(hourly[mid]) == ICAOS and len(hourly[mid]["ROIG"]) == 144
    icon, gem, cma = (hourly[m]["ROIG"] for m in ("icon", "gem", "cma"))
    i = next(i for i, h in enumerate(icon) if h.valid == utc(2026, 10, 22, 5))
    assert (gem[i].wind_kt, gem[i].gust_kt, gem[i].precip_mm) == (32.5, 55.8, 0.2)
    assert cma[i].gust_kt is None and cma[i].wind_kt == 26.6
    # 旁觀模式也走 ICON 的一格算法（有陣風 → 不估算）
    start, end = utc(2026, 10, 22, 0), utc(2026, 10, 22, 6)
    assert hourly_for_slot(gem, start, end)["gustKt"] == round(
        hourly_for_slot(icon, start, end)["gustKt"] * 1.1, 1
    )


@pytest.mark.parametrize(
    ("break_it", "code"),
    [
        (lambda h, u: h.pop("wind_speed_10m_cma_grapes_global"), "missing"),
        (lambda h, u: u.update(wind_speed_10m_cma_grapes_global="undefined"), "bad_units"),
    ],
)
def test_observer_error_drops_only_that_model(break_it, code):
    """旁觀模式（這裡是 CMA）單位不對或整欄沒有：只丟掉它，其他五個照用、不丟例外。"""
    doc = _with_observers(load_json("openmeteo_forecast_3.json"))
    break_it(doc[1]["hourly"], doc[1]["hourly_units"])  # 只有第二個機場壞 → 整個模式都不用
    errors: dict[str, str] = {}
    hourly = openmeteo.parse_forecast(doc, ICAOS, errors=errors)
    assert errors == {"cma": code}
    assert hourly["cma"] == {}
    assert all(list(hourly[m]) == ICAOS for m in ("icon", "jma", "gem", "arpege"))


def test_core_model_bad_units_still_fails():
    """ICON、JMA 單位不對照舊整個失敗（HD16 的行為不變）。"""
    doc = _with_observers(load_json("openmeteo_forecast_3.json"))
    doc[0]["hourly_units"]["wind_speed_10m_jma_gsm"] = "km/h"
    with pytest.raises(openmeteo.OpenMeteoError) as e:
        openmeteo.parse_forecast(doc, ICAOS)
    assert e.value.code == "bad_units"


def test_fetch_one_forecast_request_with_observers(monkeypatch, airports):
    """五個模式一個預報請求（請求數和 HD16 一樣是 2 個資料請求）；加權次數照 5 個模式算。"""
    docs = {
        openmeteo.FORECAST_URL: _with_observers(load_json("openmeteo_forecast_3.json")),
        openmeteo.ENSEMBLE_URL: load_json("openmeteo_ensemble_3x8.json"),
    }
    asked = []

    def fake_get(url, **kw):
        asked.append(url)
        if url in docs:
            return _Resp(docs[url], 1000)
        return _Resp({"last_run_initialisation_time": 1792476000})

    monkeypatch.setattr(openmeteo, "http_get", fake_get)
    data = openmeteo.fetch(_airports(airports))
    assert asked.count(openmeteo.FORECAST_URL) == 1 and asked.count(openmeteo.ENSEMBLE_URL) == 1
    assert len(asked) == 2 + 6
    assert data.model_errors == {} and data.meta_errors == {}
    assert data.calls == round(openmeteo.forecast_calls(3, 5) + openmeteo.ensemble_calls(3), 1)
    assert all(list(data.hourly[m]) == ICAOS for m in openmeteo.FORECAST_MODELS)
    assert data.runs["cma"] == utc(2026, 10, 20, 6)


def test_fetch_http_400_retries_without_observers(monkeypatch, airports):
    """預報請求回 400（旁觀模式的名字失效）→ 只帶 ICON、JMA 再請求一次；兩票照用、三個記
    http_400。"""
    fc = load_json("openmeteo_forecast_3.json")
    asked = []

    def fake_get(url, **kw):
        if url == openmeteo.FORECAST_URL:
            asked.append(kw["params"]["models"])
            if "cma_grapes_global" in kw["params"]["models"]:
                raise openmeteo.OpenMeteoError(f"{url}: HTTP 400", "http_400")
            return _Resp(fc, 1000)
        if url == openmeteo.ENSEMBLE_URL:
            return _Resp(load_json("openmeteo_ensemble_3x8.json"), 1000)
        return _Resp({"last_run_initialisation_time": 1792476000})

    monkeypatch.setattr(openmeteo, "http_get", fake_get)
    data = openmeteo.fetch(_airports(airports))
    assert asked == [",".join(openmeteo.FORECAST_MODELS.values()), "icon_global,jma_gsm"]
    assert data.model_errors == dict.fromkeys(openmeteo.OBSERVER_MODELS, "http_400")
    assert list(data.hourly["icon"]) == ICAOS and data.hourly["gem"] == {}
    assert data.calls == round(openmeteo.forecast_calls(3, 2) + openmeteo.ensemble_calls(3), 1)


def test_fetch_other_errors_not_retried(monkeypatch, airports):
    """400 以外（逾時、429）照 HD16：整個來源失敗、不多請求。"""
    asked = []

    def fake_get(url, **kw):
        asked.append(url)
        raise openmeteo.OpenMeteoError(f"{url}: HTTP 429", "http_429")

    monkeypatch.setattr(openmeteo, "http_get", fake_get)
    with pytest.raises(openmeteo.OpenMeteoError):
        openmeteo.fetch(_airports(airports))
    assert asked == [openmeteo.FORECAST_URL]


def test_observer_meta_skipped_after_deadline(monkeypatch, airports):
    """已經超過 `META_DEADLINE_S` 就不問旁觀模式的 metadata（`skipped`），ICON、JMA、WN2 照問。"""
    docs = {
        openmeteo.FORECAST_URL: _with_observers(load_json("openmeteo_forecast_3.json")),
        openmeteo.ENSEMBLE_URL: load_json("openmeteo_ensemble_3x8.json"),
    }
    asked = []

    def fake_get(url, **kw):
        asked.append(url)
        if url in docs:
            return _Resp(docs[url])
        return _Resp({"last_run_initialisation_time": 1792476000})

    monkeypatch.setattr(openmeteo, "http_get", fake_get)
    monkeypatch.setattr(openmeteo, "META_DEADLINE_S", -1)
    data = openmeteo.fetch(_airports(airports))
    assert asked[2:] == [openmeteo.META_URLS[m] for m in ("icon", "jma", "wn2-ens")]
    assert data.meta_errors == dict.fromkeys(openmeteo.OBSERVER_MODELS, "skipped")
    assert all(data.runs[m] is None for m in openmeteo.OBSERVER_MODELS)
    assert data.runs["icon"] == utc(2026, 10, 20, 6)
