"""WeatherNext 3 旁觀等級上傳 R2（HD15c）：等級檔的格式（51 個機場、20 格、除了時間與 schema 沒有
任何數字）、出處照 `via`、SigV4 簽章（AWS 文件的範例）、R2 的請求與錯誤碼、沒設 secrets 跳過、
`private` build 的整個流程（`latest.json`、Pages、`data` 分支、日誌都沒有 WN3 的等級）。數值全是
手造的，全部不連網。"""

from __future__ import annotations

import json
import logging
from datetime import timedelta

import pytest
import requests
from conftest import utc
from test_build import _boom, _fail_all_but, workspace  # noqa: F401
from test_sources_wn3 import FakeClient, _rows, no_zarr
from test_wn3_private import BQ, REAL_FETCH, SECRET_STRINGS, FakeBucket, _data

from hongthai import build, wn3levels, wn3private
from hongthai.sources import wn3
from hongthai.timeutil import iso, slot_bounds

LEVELS = {"low", "medium", "high", None}
TIME_KEYS = {"generatedAt", "run", "from", "to"}


def _numbers(obj, key=None):
    """JSON 裡所有的數字（含布林以外）與所在的鍵。"""
    if isinstance(obj, dict):
        return [n for k, v in obj.items() for n in _numbers(v, k)]
    if isinstance(obj, list):
        return [n for v in obj for n in _numbers(v, key)]
    if isinstance(obj, int | float) and not isinstance(obj, bool):
        return [(key, obj)]
    return []


def _strings(obj, key=None):
    if isinstance(obj, dict):
        return [s for k, v in obj.items() for s in _strings(v, k)]
    if isinstance(obj, list):
        return [s for v in obj for s in _strings(v, key)]
    return [(key, obj)] if isinstance(obj, str) else []


class FakeR2:
    def __init__(self, fail_at=None, code="r2_http_403"):
        self.objects: dict[str, bytes] = {}
        self.fail_at, self.code = fail_at, code

    def put(self, obj, body, content_type="application/json; charset=utf-8"):
        if self.fail_at is not None and len(self.objects) == self.fail_at:
            raise wn3levels.R2Error("拒絕", self.code)
        self.objects[obj] = body


class FakeResponse:
    def __init__(self, status, text=""):
        self.status_code, self.text = status, text


class FakeSession:
    def __init__(self, *responses, error=None):
        self.responses, self.error = list(responses), error
        self.calls = []

    def request(self, method, url, **kw):
        self.calls.append((method, url, kw))
        if self.error is not None:
            raise self.error
        return self.responses.pop(0)


# ---- 等級檔 ----


def test_level_docs_only_levels_for_every_airport(airports):
    run = utc(2026, 10, 26, 0)
    now = utc(2026, 10, 26, 8, 25)
    data = _data(airports[:3], run, n=132)  # 只有 3 個機場有資料，其他的也要有檔
    docs = wn3levels.level_docs(data, airports, {}, now)
    assert len(docs) == len(airports) == 51
    assert set(docs) == {f"wn3/{a.iata.lower()}.json" for a in airports}
    doc = docs[f"wn3/{airports[0].iata.lower()}.json"]
    assert list(doc) == ["schema", "generatedAt", "run", "model", "attribution", "slots"]
    assert (doc["schema"], doc["generatedAt"], doc["run"], doc["model"]) == (
        1,
        "2026-10-26T08:25:00Z",
        "2026-10-26T00:00:00Z",
        "wn3",
    )
    # 格子同 `latest.json`（現在往前取整的那格起 20 格）
    assert [(s["from"], s["to"]) for s in doc["slots"]] == [
        (iso(a), iso(b)) for a, b in slot_bounds(now)
    ]
    for s in doc["slots"]:
        assert list(s) == ["from", "to", "level", "levels"]
        assert list(s["levels"]) == ["wind", "rain", "snow", "fog"]
        assert s["level"] in LEVELS and set(s["levels"].values()) <= LEVELS
    # 43.7 節 × 1.4 → 高；旁觀不判霧、沒有降水型態不判雪
    assert {s["level"] for s in doc["slots"]} == {"high"}
    assert {s["levels"]["snow"] for s in doc["slots"]} == {None}
    assert {s["levels"]["fog"] for s in doc["slots"]} == {None}
    # 沒有資料的機場：等級全是 null
    empty = docs[f"wn3/{airports[-1].iata.lower()}.json"]
    assert {s["level"] for s in empty["slots"]} == {None}

    for d in docs.values():
        # 除了 schema 沒有任何數字；字串只有時間、model、出處與等級
        assert _numbers(d) == [("schema", 1)]
        for key, _value in _strings(d):
            assert key in TIME_KEYS | {"model", "attribution", "level"} or (
                key in ("wind", "rain", "snow", "fog")
            ), key
        text = json.dumps(d, ensure_ascii=False)
        for k in ("windKt", "gustKt", "rain6hMm", "p49Kt", "crosswindKt", "windKtP90"):
            assert k not in text
        assert not any(x in text for x in SECRET_STRINGS)


def test_attribution_follows_via(airports):
    run = utc(2026, 10, 26, 0)
    now = utc(2026, 10, 26, 8, 25)
    bq = wn3levels.level_doc(
        _data(airports[:1], run), airports[0], wn3levels.assess.DEFAULT_GUST_FACTOR, now
    )
    assert bq["attribution"].startswith(
        "Google WeatherNext 3 via Google BigQuery. © 2024-6 Google LLC"
    )
    assert wn3.TERMS_URL in bq["attribution"]
    assert bq["attribution"].endswith("not intended, validated, or approved for real world use.")
    zarr = wn3.Wn3Data(run, {}, "zarr", 0)
    doc = wn3levels.level_doc(zarr, airports[0], wn3levels.assess.DEFAULT_GUST_FACTOR, now)
    assert doc["attribution"].startswith("Google WeatherNext 3 via Google Cloud Storage. ©")


# ---- R2 ----


def test_sign_v4_matches_aws_example():
    """AWS 文件「Signature Calculations for the Authorization Header」的 GET Object 範例。"""
    h = wn3levels.sign_v4(
        "GET",
        "examplebucket.s3.amazonaws.com",
        "/test.txt",
        {"Range": "bytes=0-9"},
        b"",
        "AKIAIOSFODNN7EXAMPLE",
        "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        utc(2013, 5, 24),
        region="us-east-1",
    )
    assert h["authorization"] == (
        "AWS4-HMAC-SHA256 Credential=AKIAIOSFODNN7EXAMPLE/20130524/us-east-1/s3/aws4_request, "
        "SignedHeaders=host;range;x-amz-content-sha256;x-amz-date, "
        "Signature=f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41"
    )
    assert h["x-amz-date"] == "20130524T000000Z"
    assert h["x-amz-content-sha256"] == (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )
    assert "host" not in h  # requests 自己帶


def test_r2_from_env():
    full = {"R2_ACCOUNT_ID": "acct", "R2_ACCESS_KEY_ID": "id", "R2_SECRET_ACCESS_KEY": "s"}
    c = wn3levels.R2.from_env(full)
    assert (c.host, c.bucket) == ("acct.r2.cloudflarestorage.com", "hongthai-wn3")
    assert wn3levels.R2.from_env({**full, "R2_BUCKET": "b"}).bucket == "b"
    assert wn3levels.R2.from_env({**full, "R2_BUCKET": ""}).bucket == "hongthai-wn3"
    for k in full:
        assert wn3levels.R2.from_env({**full, k: ""}) is None
    assert wn3levels.R2.from_env({}) is None


def test_r2_put_request_and_errors():
    s = FakeSession(FakeResponse(200), FakeResponse(403, "<Error>秘密</Error>"))
    c = wn3levels.R2("acct", "AKID", "SECRET", "hongthai-wn3", s, clock=lambda: utc(2026, 10, 28))
    c.put("wn3/tpe.json", b'{"schema":1}')
    method, url, kw = s.calls[0]
    assert (method, url) == (
        "PUT",
        "https://acct.r2.cloudflarestorage.com/hongthai-wn3/wn3/tpe.json",
    )
    assert kw["data"] == b'{"schema":1}' and kw["timeout"] == wn3levels.TIMEOUT_S
    h = kw["headers"]
    assert h["content-type"] == "application/json; charset=utf-8"
    assert h["x-amz-date"] == "20261028T000000Z"
    assert h["authorization"].startswith(
        "AWS4-HMAC-SHA256 Credential=AKID/20261028/auto/s3/aws4_request, "
        "SignedHeaders=content-type;host;x-amz-content-sha256;x-amz-date, Signature="
    )
    with pytest.raises(wn3levels.R2Error) as e:
        c.put("wn3/tpe.json", b"{}")
    assert e.value.code == "r2_http_403"
    assert "秘密" not in str(e.value) and "SECRET" not in str(e.value)

    c = wn3levels.R2("acct", "AKID", "SECRET", session=FakeSession(error=requests.Timeout("慢")))
    with pytest.raises(wn3levels.R2Error) as e:
        c.put("wn3/tpe.json", b"{}")
    assert e.value.code == "r2_Timeout"


def test_upload_not_configured_and_stops_at_first_failure(airports, caplog):
    caplog.set_level(logging.DEBUG)
    docs = wn3levels.level_docs(
        _data(airports[:2], utc(2026, 10, 26, 0)), airports, {}, utc(2026, 10, 26, 8, 25)
    )
    assert wn3levels.upload(docs, None) == {"r2": "not_configured", "r2Files": 0, "r2Bytes": 0}

    r2 = FakeR2()
    out = wn3levels.upload(docs, r2)
    assert (out["r2"], out["r2Files"]) == ("ok", 51)
    assert out["r2Bytes"] == sum(len(b) for b in r2.objects.values()) > 0
    assert json.loads(r2.objects["wn3/tpe.json"]) == docs["wn3/tpe.json"]

    r2 = FakeR2(fail_at=3)
    assert wn3levels.upload(docs, r2) == {
        "r2": "r2_http_403",
        "r2Files": 3,
        "r2Bytes": sum(len(b) for b in r2.objects.values()),
    }
    # 日誌只有檔數、bytes、錯誤碼，沒有等級
    logs = "\n".join(r.getMessage() for r in caplog.records)
    assert "R2 上傳 51 個檔" in logs and "r2_http_403" in logs
    assert not any(w in logs for w in ("high", "medium", "low", "level"))


# ---- `private` build 的整個流程 ----


def _setup(monkeypatch, airports, r2, rows=True):
    _fail_all_but(monkeypatch)
    bucket = FakeBucket()
    monkeypatch.setattr(wn3private.Bucket, "from_env", classmethod(lambda cls, env=None: bucket))
    monkeypatch.setattr(wn3levels.R2, "from_env", classmethod(lambda cls, env=None: r2))
    run = utc(2026, 10, 17, 18)
    client = FakeClient({run: _rows(airports, 1, 132, **BQ)} if rows else {})
    asked = []

    def fetch(aps, r, start, end, **k):
        asked.append((r, start, end))
        return REAL_FETCH(aps, r, start, end, client=client, open_stats=no_zarr, **k)

    monkeypatch.setattr(build.wn3, "fetch", fetch)
    return bucket, asked


def test_private_build_uploads_levels_and_keeps_them_out_of_public(
    workspace,  # noqa: F811
    monkeypatch,
    airports,
    caplog,
):
    ws = workspace
    r2 = FakeR2()
    bucket, asked = _setup(monkeypatch, airports, r2)
    caplog.set_level(logging.DEBUG)
    assert build.main([]) == 0
    # NOW 08:10Z：前一天 18Z 那報，終點是 06Z 起 120 小時（`latest.json` 最後一格）
    run = utc(2026, 10, 17, 18)
    assert asked[0][0] == run and asked[0][2] == utc(2026, 10, 18, 6) + timedelta(hours=120)
    assert "observe/20261017T1800Z.json" in bucket.objects
    assert sorted(r2.objects) == sorted(f"wn3/{a.iata.lower()}.json" for a in airports)
    tpe = json.loads(r2.objects["wn3/tpe.json"])
    assert tpe["run"] == "2026-10-17T18:00:00Z" and tpe["generatedAt"] == "2026-10-18T08:10:00Z"
    assert "via Google BigQuery" in tpe["attribution"]
    assert {s["level"] for s in tpe["slots"]} == {"high"}  # 20 格都有資料
    assert _numbers(tpe) == [("schema", 1)]

    latest_text = (ws / "public" / "latest.json").read_text("utf-8")
    out = json.loads(latest_text)
    src = out["sources"]["wn3"]
    assert (src["ok"], src["stored"], src["r2"], src["r2Files"]) == (True, "written", "ok", 51)
    assert src["r2Bytes"] == sum(len(b) for b in r2.objects.values())
    assert "wn3" not in [m["id"] for m in out["models"]] and "wn3" not in out["runs"]
    assert all(
        e["id"] != "wn3" for a in out["airports"] for s in a["slots"] for e in s["model"]["models"]
    )
    # 公開的地方沒有等級檔的內容（出處那段只在等級檔裡）
    for p in (p for d in ("public", "data") for p in (ws / d).rglob("*") if p.is_file()):
        if p.suffix == ".png":
            continue
        text = p.read_text("utf-8", errors="replace")
        assert (
            "Google WeatherNext 3 via" not in text and '"model":"wn3","attribution"' not in text
        ), p

    # 日誌：WN3 等級那幾行只有檔數與 bytes
    msgs = [r.getMessage() for r in caplog.records if "WeatherNext 3" in r.getMessage()]
    assert any("R2 上傳 51 個檔" in m for m in msgs)
    assert not any(w in m for m in msgs for w in ("high", "medium", "level", "高"))

    # `latest.json` 和 WN3 失敗那一報一模一樣（等級沒有漏進任何一格）
    monkeypatch.setattr(build.wn3, "fetch", _boom)
    bucket.objects.clear()
    r2.objects.clear()
    assert build.main(["--trigger", "manual"]) == 0
    other = json.loads((ws / "public" / "latest.json").read_text("utf-8"))
    assert other["airports"] == out["airports"]
    assert r2.objects == {}  # WN3 失敗：不上傳
    assert "r2" not in other["sources"]["wn3"]


def test_private_build_skips_upload_when_already_stored_or_not_configured(
    workspace,  # noqa: F811
    monkeypatch,
    airports,
):
    ws = workspace
    r2 = FakeR2()
    bucket, asked = _setup(monkeypatch, airports, r2)
    bucket.objects["observe/20261017T1800Z.json"] = {"model": "wn3"}
    assert build.main([]) == 0
    assert asked == [] and r2.objects == {}  # 這一報已經在私人 bucket、沒查 → 不上傳
    src = json.loads((ws / "public" / "latest.json").read_text("utf-8"))["sources"]["wn3"]
    assert src["stored"] == "exists" and "r2" not in src

    # 沒設 secrets：照樣寫私人 bucket，`r2` 記 not_configured
    bucket.objects.clear()
    monkeypatch.setattr(wn3levels.R2, "from_env", classmethod(lambda cls, env=None: None))
    assert build.main(["--trigger", "manual"]) == 0
    src = json.loads((ws / "public" / "latest.json").read_text("utf-8"))["sources"]["wn3"]
    assert (src["ok"], src["stored"], src["r2"], src["r2Files"]) == (
        True,
        "written",
        "not_configured",
        0,
    )


def test_private_build_r2_failure_only_records_code(workspace, monkeypatch, airports):  # noqa: F811
    ws = workspace
    r2 = FakeR2(fail_at=0, code="r2_http_401")
    bucket, _ = _setup(monkeypatch, airports, r2)
    assert build.main([]) == 0  # 整報照出
    out = json.loads((ws / "public" / "latest.json").read_text("utf-8"))
    src = out["sources"]["wn3"]
    assert (src["ok"], src["stored"], src["r2"], src["r2Files"]) == (
        True,
        "written",
        "r2_http_401",
        0,
    )
    assert "observe/20261017T1800Z.json" in bucket.objects  # 私人 bucket 照寫
    timing = (ws / "data" / "history" / "timing" / "2026-10.jsonl").read_text("utf-8")
    line = next(json.loads(x) for x in timing.splitlines() if '"source": "wn3"' in x)
    assert (line["r2"], line["r2Files"]) == ("r2_http_401", 0)


def test_build_workflow_passes_r2_settings():
    text = (build.Path(__file__).resolve().parents[1] / ".github/workflows/build.yml").read_text(
        "utf-8"
    )
    for k in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY"):
        assert f"{k}: ${{{{ secrets.{k} }}}}" in text
    assert "R2_BUCKET: ${{ vars.R2_BUCKET }}" in text
