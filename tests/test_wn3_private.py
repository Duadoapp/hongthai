"""WeatherNext 3 隱形旁觀（HD15b）：私人 bucket（假 GCS）、`private` 模式的 build（`latest.json` 與
日誌沒有任何 WN3 的值）、29W 補抓截到「現在 − 1 小時」與之後補寫、超過 121 小時的搬家、報告工具讀
截過的檔。數值全是手造的（不是真的 WN3 資料），全部不連網。"""

from __future__ import annotations

import importlib.util
import json
import logging
import sys
from dataclasses import replace
from datetime import date, timedelta

import numpy as np
import pytest
import requests
from conftest import ROOT, utc
from test_build import _boom, _fail_all_but, _timing_lines, workspace  # noqa: F401
from test_sources_wn3 import FakeClient, _rows, no_zarr

from hongthai import build, events, wn3private, wn3report
from hongthai.config import Event
from hongthai.sources import wn3

EV = Event("29W", "CHAMPI（薔琵）", date(2026, 10, 19), date(2026, 10, 26), ("RCTP",))
# 手造的「認得出來」的數字：日誌、`latest.json`、Pages 裡都不能出現（檔裡取到 1 位小數）
WIND, MEAN, P90 = 43.71, 40.73, 52.19
SECRET_STRINGS = ("43.71", "43.7", "40.73", "52.19", "52.2")
# BigQuery 假回應（m/s）：p50 22.4867 m/s ＝ 43.71 節、平均 20.9533 ＝ 40.73、p90 26.8489 ＝ 52.19
BQ = {"p50": 22.4867, "mean": 20.9533, "p90": 26.8489}
REAL_FETCH = wn3.fetch  # workspace 換掉之前的


def private_mode(monkeypatch):
    """HD43 起預設 `vote`（`MODELS` 載入時就放了 wn3）；測 HD15b 的 `private` 時換回來。"""
    models = tuple(m for m in build.MODELS if m.id != "wn3")
    monkeypatch.setattr(build, "wn3_mode", lambda: "private")
    monkeypatch.setattr(build, "MODELS", models)
    monkeypatch.setattr(build.assess, "MODELS", models)


def _airports(airports, *icaos):
    return [a for a in airports if a.icao in icaos]


def _hours(run, n=126, wind=WIND):
    return [
        wn3.Wn3Hour(run + timedelta(hours=h), wind, MEAN, P90, 90.0, 0.5, 25.0)
        for h in range(1, n + 1)
    ]


def _low(run, n=126):
    """每 6 小時一張平均海平面氣壓（Pa）：(16°N, 135°E) 一個不動的低壓（980 hPa）。"""
    lats = np.arange(5.0, 30.01, 0.5)
    lons = np.arange(120.0, 150.01, 0.5)
    la, lo = np.meshgrid(lats, lons, indexing="ij")
    vals = 101_000 - 3_000 * np.exp(-((la - 16) ** 2 + (lo - 135) ** 2) / 8)
    return {
        run + timedelta(hours=h): wn3.Grid(lats, lons, vals) for h in range(6, n + 1, wn3.STEP_H)
    }


def _data(airports, run, **kw):
    return wn3.Wn3Data(
        run,
        {a.icao: _hours(run, **kw) for a in airports},
        "bigquery",
        0,
        estimate_bytes=6_000_000_000,
        bytes_processed=4_000_000_000,
        bytes_billed=4_000_000_000,
        mslp=_low(run),
    )


class FakeBucket:
    """記在 dict 裡的私人 bucket（`wn3private.Bucket` 的四個動作）。"""

    def __init__(self, objects=None, error=None):
        self.objects = dict(objects or {})
        self.error = error
        self.calls: list[tuple[str, str]] = []

    def _check(self, op, name):
        self.calls.append((op, name))
        if self.error is not None:
            raise wn3private.PrivateError("拒絕", self.error)

    def exists(self, name):
        self._check("exists", name)
        return name in self.objects

    def put_json(self, name, doc):
        self._check("put", name)
        if name in self.objects:
            return False
        self.objects[name] = json.loads(json.dumps(doc))
        return True

    def list(self, prefix):
        self._check("list", prefix)
        return sorted(n for n in self.objects if n.startswith(prefix))

    def get_json(self, name):
        self._check("get", name)
        return json.loads(json.dumps(self.objects[name]))


# ---- 私人 bucket（GCS JSON API）----


class FakeResponse:
    def __init__(self, status, body=None):
        self.status_code, self.body = status, body

    def json(self):
        if self.body is None:
            raise ValueError("不是 JSON")
        return self.body


class FakeSession:
    def __init__(self, *responses, error=None):
        self.responses, self.error = list(responses), error
        self.calls = []

    def request(self, method, url, timeout=None, **kw):
        self.calls.append((method, url, kw))
        if self.error is not None:
            raise self.error
        return self.responses.pop(0)


def test_bucket_name_and_object_names():
    assert wn3private.bucket_name("hongthai-512102", {}) == "hongthai-512102-wn3-private"
    assert wn3private.bucket_name("p", {"WN3_PRIVATE_BUCKET": "b"}) == "b"
    run = utc(2026, 10, 26, 6)
    assert wn3private.object_name(run) == "observe/20261026T0600Z.json"
    assert wn3private.run_of("observe/20261026T0600Z.json") == run
    assert wn3private.run_of("observe/x.json") is None
    assert wn3private.run_of("other/20261026T0600Z.json") is None
    assert wn3private.run_of("observe/a/20261026T0600Z.json") is None
    with pytest.raises(wn3private.PrivateError) as e:
        wn3private.credentials({})
    assert e.value.code == "no_credentials"
    # `sources/wn3.credentials` 用同一個實作、丟自己的例外
    with pytest.raises(wn3.Wn3Error) as e:
        wn3.credentials({"GOOGLE_SERVICE_ACCOUNT_JSON": "{壞的", "GOOGLE_CLOUD_PROJECT": "p"})
    assert e.value.code == "no_credentials" and "壞的" not in str(e.value)


def test_bucket_requests_and_errors():
    s = FakeSession(FakeResponse(200, {"name": "x"}), FakeResponse(404), FakeResponse(403, {}))
    b = wn3private.Bucket("hongthai-512102-wn3-private", s)
    assert b.exists("observe/20261026T0600Z.json") is True
    assert b.exists("observe/20261026T0600Z.json") is False
    with pytest.raises(wn3private.PrivateError) as e:
        b.exists("observe/20261026T0600Z.json")
    assert e.value.code == "gcs_http_403"
    method, url, kw = s.calls[0]
    assert method == "GET" and url.endswith(
        "/b/hongthai-512102-wn3-private/o/observe%2F20261026T0600Z.json"
    )
    assert kw["params"] == {"fields": "name"}

    s = FakeSession(FakeResponse(200, {}), FakeResponse(412), FakeResponse(500, {"error": "秘密"}))
    b = wn3private.Bucket("bk", s)
    assert b.put_json("observe/a.json", {"windKt": WIND}) is True
    assert (
        b.put_json("observe/a.json", {"windKt": WIND}) is False
    )  # 已經有了（ifGenerationMatch=0）
    with pytest.raises(wn3private.PrivateError) as e:
        b.put_json("observe/a.json", {"windKt": WIND})
    assert (
        e.value.code == "gcs_http_500"
        and "秘密" not in str(e.value)
        and "41.37" not in str(e.value)
    )
    method, url, kw = s.calls[0]
    assert method == "POST" and "/upload/storage/v1/b/bk/o" in url
    assert kw["params"] == {
        "uploadType": "media",
        "name": "observe/a.json",
        "ifGenerationMatch": "0",
    }
    assert json.loads(kw["data"]) == {"windKt": WIND}

    s = FakeSession(
        FakeResponse(200, {"items": [{"name": "observe/1.json"}], "nextPageToken": "t"}),
        FakeResponse(200, {"items": [{"name": "observe/2.json"}]}),
        FakeResponse(200, {"run": "r"}),
    )
    b = wn3private.Bucket("bk", s)
    assert b.list("observe/") == ["observe/1.json", "observe/2.json"]
    assert s.calls[1][2]["params"]["pageToken"] == "t"
    assert b.get_json("observe/1.json") == {"run": "r"}
    assert s.calls[2][2]["params"] == {"alt": "media"}

    b = wn3private.Bucket("bk", FakeSession(error=requests.ConnectionError("斷線")))
    with pytest.raises(wn3private.PrivateError) as e:
        b.exists("observe/a.json")
    assert e.value.code == "gcs_ConnectionError"


# ---- 隱形旁觀（`private`）----


def test_observe_private_writes_bucket_and_skips_existing(airports):
    aps = _airports(airports, "RCTP", "VHHH")
    now = utc(2026, 10, 26, 13, 5)
    run = wn3.latest_run(now)
    assert run == utc(2026, 10, 26, 0)
    asked = []

    def fetch(aps_, r, start, end, **k):
        asked.append((r, start, end, k))
        return _data(aps_, r)

    bucket = FakeBucket()
    f = {"RCTP": wn3report.assess.GustFactor(1.4, "airport30d")}
    res = wn3report.observe_private(aps, now, f, bucket, fetch)
    # 前一報也不在 bucket → 查不到可以退一報；起點放前一報，這一報照樣從 1 小時起；終點蓋住
    # `latest.json` 那 20 格（HD15c：12Z 起 120 小時＝這一報的 132 小時）
    prev = run - timedelta(hours=6)
    end = utc(2026, 10, 26, 12) + timedelta(hours=120)
    assert asked == [(run, prev, end, {"mslp": False, "retry_previous": True})]
    assert wn3.lead_window(run, prev, end) == (1, 132)
    assert (res.run, res.stored) == (run, "written")
    doc = bucket.objects["observe/20261026T0000Z.json"]
    assert (doc["model"], doc["run"], doc["mode"], doc["license"]) == (
        "wn3",
        "2026-10-26T00:00:00Z",
        "private",
        wn3.TERMS_URL,
    )
    assert "experimental modelling" in doc["attribution"] and "clippedAt" not in doc
    rows = doc["airports"]["RCTP"]
    assert len(rows) == 20 and rows[0]["from"] == "2026-10-26T00:00:00Z"
    assert rows[-1]["to"] == "2026-10-31T00:00:00Z" and rows[-1]["leadHours"] == 120
    assert rows[1]["windKt"] == 43.7 and rows[1]["level"] == "high" and "levels" in rows[1]

    # 同一個起報已經有了 → 不查
    asked.clear()
    res = wn3report.observe_private(aps, now + timedelta(hours=1), f, bucket, fetch)
    assert asked == [] and (res.stored, res.data) == ("exists", None)
    # 前一報已經有了 → 不退一報、起點就是這一報
    nxt = now + timedelta(hours=6)
    wn3report.observe_private(aps, nxt, f, bucket, fetch)
    r2 = utc(2026, 10, 26, 6)
    end = utc(2026, 10, 26, 18) + timedelta(hours=120)
    assert asked == [(r2, r2, end, {"mslp": False, "retry_previous": False})]


def test_observe_private_bucket_error_raises_with_code(airports):
    def fetch(*a, **k):
        raise AssertionError("bucket 查不了就不該查 BigQuery")

    with pytest.raises(wn3private.PrivateError) as e:
        wn3report.observe_private(
            airports[:1], utc(2026, 10, 26, 13), {}, FakeBucket(error="gcs_http_403"), fetch
        )
    assert e.value.code == "gcs_http_403"


def test_private_build_latest_has_no_wn3_values_and_logs_are_clean(
    workspace,  # noqa: F811
    monkeypatch,
    airports,
    caplog,
):
    """整個 `private` 流程：私人 bucket 拿到整份；`latest.json`、`history/`、Pages、`timing/` 與日誌
    都沒有 WN3 的任何數值或等級，`sources.wn3` 只有中繼資料。"""
    ws = workspace
    private_mode(monkeypatch)
    _fail_all_but(monkeypatch)
    bucket = FakeBucket()
    monkeypatch.setattr(wn3private.Bucket, "from_env", classmethod(lambda cls, env=None: bucket))
    asked = []
    run = utc(2026, 10, 17, 18)
    client = FakeClient({run: _rows(airports, 1, 126, **BQ)})

    def fetch(aps, r, start, end, **k):  # 真的 `wn3.fetch`（含它的日誌），BigQuery 換假的
        asked.append(r)
        return REAL_FETCH(aps, r, start, end, client=client, open_stats=no_zarr, **k)

    monkeypatch.setattr(build.wn3, "fetch", fetch)
    caplog.set_level(logging.DEBUG)
    assert build.main([]) == 0
    assert build.wn3_mode() == "private"
    assert asked == [run]  # NOW 08:10Z − 8 小時 30 分 → 前一天 18Z 那報
    doc = bucket.objects["observe/20261017T1800Z.json"]
    row = doc["airports"]["RCTP"][2]
    assert len(doc["airports"]) == len(airports) and row["windKt"] == 43.7
    secrets = (*SECRET_STRINGS, *(f"{v}" for v in BQ.values()), f"{row['gustKt']}")  # 估算陣風

    latest_text = (ws / "public" / "latest.json").read_text("utf-8")
    out = json.loads(latest_text)
    assert "wn3" not in [m["id"] for m in out["models"]] and "wn3" not in out["runs"]
    assert all(
        e["id"] != "wn3" for a in out["airports"] for s in a["slots"] for e in s["model"]["models"]
    )
    src = out["sources"]["wn3"]
    assert isinstance(src.pop("seconds"), float)
    assert src == {
        "ok": True,
        "run": "2026-10-17T18:00:00Z",
        "stored": "written",
        "via": "bigquery",
        "bytes": 0,
        "estimateBytes": 5_000_000_000,
        "bytesProcessed": 3_100_000_000,
        "bytesBilled": 3_100_000_000,
        "mode": "private",
    }
    # 公開的地方（Pages、data 分支的整個 checkout）一個數字都沒有、也沒有事件檔
    public = [p for d in ("public", "data") for p in (ws / d).rglob("*") if p.is_file()]
    assert public
    for p in public:
        if p.suffix in (".png",):
            continue
        text = p.read_text("utf-8", errors="replace")
        assert not any(x in text for x in secrets), p
    assert not list((ws / "data").rglob("wn3/*.json")) and not list(
        (ws / "data").rglob("*-wn3.json")
    )
    line = next(x for x in _timing_lines(ws) if x["source"] == "wn3")
    assert (line["ok"], line["mode"], line["stored"], line["bytesBilled"]) == (
        True,
        "private",
        "written",
        3_100_000_000,
    )
    # 日誌：只有起報時間、機場數、bytes、秒數
    logs = "\n".join(r.getMessage() for r in caplog.records)
    assert "隱形旁觀" in logs and "WeatherNext 3 2026-10-17T18:00:00Z：bigquery" in logs
    assert not any(x in logs for x in secrets)

    # 第二次（同一報）：bucket 已經有了 → 不查 BigQuery
    asked.clear()
    assert build.main(["--trigger", "manual"]) == 0
    assert asked == []
    out = json.loads((ws / "public" / "latest.json").read_text("utf-8"))
    assert out["sources"]["wn3"]["stored"] == "exists" and "via" not in out["sources"]["wn3"]


def test_private_build_bucket_failure_is_source_error(workspace, monkeypatch):  # noqa: F811
    ws = workspace
    private_mode(monkeypatch)
    _fail_all_but(monkeypatch)
    monkeypatch.setattr(
        wn3private.Bucket,
        "from_env",
        classmethod(lambda cls, env=None: FakeBucket(error="gcs_http_403")),
    )
    monkeypatch.setattr(build.wn3, "fetch", _boom)
    assert build.main([]) == 0  # 整報照出
    src = json.loads((ws / "public" / "latest.json").read_text("utf-8"))["sources"]["wn3"]
    assert (src["ok"], src["error"], src["mode"]) == (False, "gcs_http_403", "private")


# ---- 29W 補抓（截到現在 − 1 小時）----


def _seed(monkeypatch):
    monkeypatch.setattr(
        wn3report.tracks,
        "find_seed",
        lambda d, run, e, observed=None: {
            "lat": 16.0,
            "lon": 135.0,
            "at": wn3report.iso(run),
            "source": "jtwc",
        },
    )


def test_backfill_clips_to_one_hour_ago_and_refills_later(tmp_path, airports, monkeypatch):
    aps = _airports(airports, "RCTP")
    _seed(monkeypatch)
    d = tmp_path / "events" / "29W"
    # 原本的 29W 檔（快照、別的模式的路徑）一個都不動
    keep = {
        d / "20261024T0810Z.json": '{"schema":1}\n',
        d / "tracks" / "20261024T1800Z-gfs.json": '{"model":"gfs"}\n',
    }
    for p, text in keep.items():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, "utf-8")
    asked = []

    def fetch(aps_, run, start, end, mslp=False):
        asked.append((run, start, end, mslp))
        return _data(aps_, run)  # 故意多給：檔裡照樣只留 1 小時以前的

    now = utc(2026, 10, 26, 3, 30)
    clip = utc(2026, 10, 26, 2, 30)
    since = utc(2026, 10, 20, 18)
    out = wn3report.backfill(tmp_path, [EV], aps, since, now, tmp_path / "w", fetch)
    runs = [utc(2026, 10, 20, 18) + timedelta(hours=6 * k) for k in range(21)]  # 到 10/25 18Z
    assert [a[0] for a in asked] == runs
    assert wn3.latest_run(now) == runs[-1]
    for run, start, end, mslp in asked:
        n = min(20, int((clip - run) / timedelta(hours=6)))
        assert (start, end, mslp) == (run, run + timedelta(hours=6 * n), True)
    assert out["29W"].failed == [] and len(out["29W"].written) == 2 * len(runs)

    first = json.loads((d / "wn3" / "20261020T1800Z.json").read_text("utf-8"))
    assert "clippedAt" not in first and len(first["airports"]["RCTP"]) == 20  # 128.5 小時：整報
    assert first["license"] == "CC BY 4.0" and "Google LLC" in first["attribution"]
    last = json.loads((d / "wn3" / "20261025T1800Z.json").read_text("utf-8"))
    assert last["clippedAt"] == "2026-10-26T02:30:00Z" and last["license"] == "CC BY 4.0"
    assert [r["to"] for r in last["airports"]["RCTP"]] == ["2026-10-26T00:00:00Z"]
    mid = json.loads((d / "wn3" / "20261024T0000Z.json").read_text("utf-8"))
    assert len(mid["airports"]["RCTP"]) == 8  # 50.5 小時 → 8 格
    for p in (d / "wn3").glob("*.json"):
        doc = json.loads(p.read_text("utf-8"))
        assert all(wn3report.parse_time(r["to"]) <= clip for r in doc["airports"]["RCTP"])
    tr_last = json.loads((d / "tracks" / "20261025T1800Z-wn3.json").read_text("utf-8"))
    assert (tr_last["stop"], tr_last["clippedAt"], tr_last["license"]) == (
        "clipped",
        "2026-10-26T02:30:00Z",
        "CC BY 4.0",
    )
    assert [p["validAt"] for p in tr_last["points"]] == ["2026-10-26T00:00:00Z"]
    tr_first = json.loads((d / "tracks" / "20261020T1800Z-wn3.json").read_text("utf-8"))
    assert (
        tr_first["stop"] == "end" and "clippedAt" not in tr_first and len(tr_first["points"]) == 20
    )
    for p in (d / "tracks").glob("*-wn3.json"):
        doc = json.loads(p.read_text("utf-8"))
        assert all(wn3report.parse_time(x["validAt"]) <= clip for x in doc["points"])
    assert {p for p in out["29W"].written} == {
        *(d / "wn3").glob("*.json"),
        *(d / "tracks").glob("*-wn3.json"),
    }
    assert all(p.read_text("utf-8") == text for p, text in keep.items())

    # 6 小時後再跑：截過的每報多一格 → 重抓、覆寫；整報的不再抓；多一報（10/26 00Z）
    asked.clear()
    now2 = now + timedelta(hours=6)
    out = wn3report.backfill(tmp_path, [EV], aps, since, now2, tmp_path / "w", fetch)
    full = {r for r in runs if r + timedelta(hours=120) <= clip}
    assert [a[0] for a in asked] == [r for r in runs if r not in full] + [utc(2026, 10, 26, 0)]
    assert out["29W"].skipped == len(full)
    last = json.loads((d / "wn3" / "20261025T1800Z.json").read_text("utf-8"))
    assert last["clippedAt"] == "2026-10-26T08:30:00Z" and len(last["airports"]["RCTP"]) == 2
    # 同一個時間再跑：沒有新的格 → 一報都不抓
    asked.clear()
    wn3report.backfill(tmp_path, [EV], aps, since, now2, tmp_path / "w", fetch)
    assert asked == []


def test_backfill_stops_when_not_approved_and_needs_track(tmp_path, airports, monkeypatch):
    aps = _airports(airports, "RCTP")
    asked = []

    def denied(aps_, run, *a, **k):
        asked.append(run)
        raise wn3.Wn3Error("403", "http_403")

    now = utc(2026, 10, 26, 3, 30)
    out = wn3report.backfill(tmp_path, [EV], aps, utc(2026, 10, 19), now, tmp_path / "w", denied)
    assert len(asked) == 1 and out["29W"].failed == ["wn3@2026-10-19T00:00:00Z"]

    # 沒有起點：事件檔照寫、路徑不寫 → 下次照樣重抓（缺路徑檔）
    monkeypatch.setattr(wn3report.tracks, "find_seed", lambda *a, **k: None)
    got = []

    def fetch(aps_, run, start, end, mslp=False):
        got.append(run)
        return _data(aps_, run)

    since = utc(2026, 10, 25, 12)
    out = wn3report.backfill(tmp_path, [EV], aps, since, now, tmp_path / "w", fetch)
    assert [p.parent.name for p in out["29W"].written] == ["wn3", "wn3"]
    wn3report.backfill(tmp_path, [EV], aps, since, now, tmp_path / "w", fetch)
    assert got == [utc(2026, 10, 25, 12), utc(2026, 10, 25, 18)] * 2


def test_public_slots_and_clip_time():
    run = utc(2026, 10, 25, 18)
    assert wn3report.clip_time(utc(2026, 10, 26, 3, 30, 59)) == utc(2026, 10, 26, 2, 30)
    assert wn3report.public_slots(run, utc(2026, 10, 25, 23, 59)) == 0
    assert wn3report.public_slots(run, utc(2026, 10, 26, 0)) == 1  # `to` ＝ 截止時間也算
    assert wn3report.public_slots(run, run + timedelta(hours=500)) == 20
    assert wn3report.public_slots(run, None) == 20


# ---- 超過 121 小時搬進 data 分支 ----


def _private_doc(airports, run):
    return wn3report.report_doc(_data(airports, run), airports, {}, "private")


def test_archive_moves_only_old_runs_and_keeps_event_files(tmp_path, airports):
    aps = _airports(airports, "RCTP")
    now = utc(2026, 11, 2, 0, 7)
    # 起報 ≤ 現在 − 121 小時 ＝ 10/27 23:07 → 10/27 18Z 以前
    old_in_event = utc(2026, 10, 26, 6)  # 事件期間（10/26 台灣 24:00 ＝ 16Z 以前）
    old_after = utc(2026, 10, 27, 18)
    too_new = utc(2026, 10, 28, 0)
    moved = utc(2026, 10, 26, 0)
    bad = utc(2026, 10, 27, 0)
    bucket = FakeBucket(
        {
            wn3private.object_name(r): _private_doc(aps, r)
            for r in (old_in_event, old_after, too_new, moved)
        }
    )
    bucket.objects[wn3private.object_name(bad)] = {"model": "wn3", "run": "2026-10-20T00:00:00Z"}
    bucket.objects["observe/README.txt"] = {}
    history = tmp_path
    # 已經搬過的（不再讀 bucket）；它的事件檔已經有（不是截過的）→ 不覆寫
    wn3private.write_json(wn3private.history_path(history, moved), {"run": "已經搬過"})
    ev_dir = events.event_dir(history, EV)
    wn3private.write_json(wn3private.report_path(ev_dir, moved), {"run": "原本的"})
    # 事件檔是補抓時截過的 → 換成整份
    wn3private.write_json(wn3private.report_path(ev_dir, old_in_event), {"clippedAt": "x"})

    res = wn3private.archive(history, [EV], now, bucket)
    assert ("get", wn3private.object_name(moved)) not in bucket.calls
    assert ("get", wn3private.object_name(too_new)) not in bucket.calls
    assert res.skipped == 1 and res.failed == ["2026-10-27T00:00:00Z"]
    out = json.loads(wn3private.history_path(history, old_in_event).read_text("utf-8"))
    assert (out["license"], out["attribution"], out["mode"]) == (
        "CC BY 4.0",
        wn3private.ATTRIBUTION_CC,
        "private",
    )
    assert out["airports"] == bucket.objects[wn3private.object_name(old_in_event)]["airports"]
    assert json.loads(wn3private.report_path(ev_dir, old_in_event).read_text("utf-8")) == out
    assert wn3private.history_path(history, old_after).exists()
    assert not wn3private.report_path(ev_dir, old_after).exists()  # 事件期間外
    assert not wn3private.history_path(history, too_new).exists()
    assert json.loads(wn3private.report_path(ev_dir, moved).read_text("utf-8")) == {"run": "原本的"}
    assert sorted(p.name for p in res.written) == [
        "20261026T0600Z.json",
        "20261026T0600Z.json",
        "20261027T1800Z.json",
    ]
    # 再跑一次：都搬過了
    again = wn3private.archive(history, [EV], now, bucket)
    assert again.written == [] and again.skipped == 3
    # 私人 bucket 的檔留著
    assert wn3private.object_name(old_in_event) in bucket.objects


def test_wn3_archive_command_without_credentials(tmp_path, monkeypatch, capsys):
    for k in ("GOOGLE_SERVICE_ACCOUNT_JSON", "GOOGLE_CLOUD_PROJECT"):
        monkeypatch.delenv(k, raising=False)
    ev = tmp_path / "events.json"
    ev.write_text(json.dumps({"events": []}), "utf-8")
    assert events.main(["wn3-archive", "--archive", str(tmp_path), "--events", str(ev)]) == 0
    assert "no_credentials" in capsys.readouterr().out


def test_wn3private_is_light():
    """events workflow 每小時那支只裝 requests、google-auth：`wn3private` 不載入 numpy 等。"""
    import subprocess

    code = (
        "import sys, hongthai.wn3private, hongthai.events; "
        "print(sorted(m for m in ('numpy', 'xarray', 'eccodes') if m in sys.modules))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        env={"PYTHONPATH": str(ROOT / "src"), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
    )
    assert out.stdout.strip() == "[]", out.stderr


def test_events_workflow_archives_daily_at_00z():
    yml = (ROOT / ".github" / "workflows" / "events.yml").read_text("utf-8")
    assert "pip install requests google-auth" in yml
    assert '"$(date -u +%H)" = "00"' in yml
    assert "python -m hongthai.events wn3-archive --archive data" in yml
    assert "wn3-archive:" in yml  # 手動


# ---- 報告工具讀截過的檔 ----


def _report_tool():
    spec = importlib.util.spec_from_file_location(
        "report_29w_wn3", ROOT / "tools" / "report_29w.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_load_wn3_reads_clipped_files(tmp_path, airports):
    rpt = _report_tool()
    aps = _airports(airports, "RCTP")
    run = utc(2026, 10, 25, 18)
    doc = wn3report.report_doc(_data(aps, run), aps, {}, "report-only", utc(2026, 10, 26, 2, 30))
    assert doc["clippedAt"] == "2026-10-26T02:30:00Z"
    full = wn3report.report_doc(
        replace(_data(aps, run - timedelta(days=6))), aps, {}, "report-only"
    )
    d = tmp_path / "events" / "29W"
    wn3report.write_report(wn3private.report_path(d, run), doc)
    wn3report.write_report(wn3private.report_path(d, run - timedelta(days=6)), full)
    runs = rpt.load_wn3(d, ["RCTP"])
    assert [len(w.airports["RCTP"]) for w in runs] == [20, 1]
    assert runs[1].airports["RCTP"][0].end == utc(2026, 10, 26, 0)
    # 缺的格當沒有預報：只有寫了的格進陣風統計
    res = rpt.gust_stats([], runs[1:], {"RCTP": []})
    assert res is not None
