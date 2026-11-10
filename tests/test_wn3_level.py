"""WeatherNext 3 公開它自己的整體等級（HD48，2026-11-11 Shawn 定案）：`vote` 模式每格 `models[]`
的 `wn3` 那筆從 `{"id", "valuesHidden"}` 變成多一個 `level`（投票用的那個整體等級，不另外算），頂層
`models[]` 那筆多 `levelPublic: true`；分項 `levels` 與任何數字照舊不公開；日韓照舊沒有這筆；
`WN3_PUBLIC_LEVEL=0` 關掉時輸出和 HD43 一樣。數值全是手造的（不是真的 WN3 資料），全部不連網。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import replace

import pytest
from conftest import ROOT
from test_build import _fail_all_but, fake_ai, workspace  # noqa: F401
from test_wn3_private import FakeBucket
from test_wn3_vote import HIDDEN, JP_KR, RUN, SECRETS, _assemble, _by, _data, _wn3_entries

from hongthai import assess, build, wn3private
from hongthai.ai import prompt
from hongthai.ai import run as ai_run
from hongthai.config import WN3_EXCLUDED_REGIONS, WN3_MODEL, wn3_public_level

LEVELS = ("low", "medium", "high")
PUBLIC_KEYS = {"id", "valuesHidden", "level"}


def _switch_off(monkeypatch):
    """`WN3_PUBLIC_LEVEL=0`：`MODELS` 在載入時決定，測試直接換掉 wn3 那筆。"""
    models = tuple(replace(m, level_public=False) if m.id == "wn3" else m for m in build.MODELS)
    monkeypatch.setattr(build, "MODELS", models)
    monkeypatch.setattr(build.assess, "MODELS", models)


def _strip_hd48(doc: dict) -> dict:
    """拿掉 HD48 加的兩個欄位（每格 wn3 那筆的 `level`、頂層 wn3 的 `levelPublic`）。"""
    doc = json.loads(json.dumps(doc))
    for m in doc.get("models") or []:
        m.pop("levelPublic", None)
    for a in doc.get("airports") or []:
        for s in a.get("slots") or []:
            for e in s["model"]["models"]:
                if e.get("valuesHidden"):
                    e.pop("level", None)
    return doc


def _wn3_dicts(obj: object):
    """任何地方 `id` 是 `wn3` 的 dict（每格那筆、頂層 `models[]` 那筆）。"""
    if isinstance(obj, dict):
        if obj.get("id") == "wn3":
            yield obj
        for v in obj.values():
            yield from _wn3_dicts(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _wn3_dicts(v)


# ---- 設定 ----


def test_switch_default_on_and_env_override():
    assert wn3_public_level({}) is True
    assert wn3_public_level({"WN3_PUBLIC_LEVEL": "0"}) is False
    assert wn3_public_level({"WN3_PUBLIC_LEVEL": "1"}) is True
    assert wn3_public_level({"WN3_PUBLIC_LEVEL": "yes"}) is True  # 不認得用預設
    assert WN3_MODEL.level_public is True and assess.level_public() == {"wn3"}


def test_switch_read_at_import():
    """`MODELS` 在載入時看環境變數：`vote` 預設公開等級、`WN3_PUBLIC_LEVEL=0` 關；只有 `vote`
    會開（`observe` 本來就全部公開、`level_public` 不用）。"""
    code = "from hongthai.config import MODELS; m = MODELS[-1]; print(m.id, m.level_public)"

    def run(**env):
        base = {k: v for k, v in os.environ.items() if not k.startswith("WN3_")}
        base["PYTHONPATH"] = str(ROOT / "src")
        out = subprocess.run(
            [sys.executable, "-c", code], env={**base, **env}, capture_output=True, text=True
        )
        return out.stdout.split()

    assert run() == ["wn3", "True"]
    assert run(WN3_PUBLIC_LEVEL="0") == ["wn3", "False"]
    assert run(WN3_MODE="observe") == ["wn3", "False"]


# ---- `public_entries` ----


def test_public_entry_has_only_id_values_hidden_and_level():
    full = {
        "id": "wn3",
        "run": "x",
        "windKt": 30.0,
        "gustKt": 42.0,
        "windKtP90": 35.0,
        "levels": {"wind": "medium", "rain": "low", "snow": None, "fog": None},
        "level": "medium",
    }
    (pub,) = assess.public_entries([full], "taiwan")
    assert pub == {"id": "wn3", "valuesHidden": True, "level": "medium"}
    assert assess.public_entries([{**full, "level": None}], "hongkong")[0]["level"] is None
    assert assess.public_entries([{**full, "level": "x"}], "taiwan")[0]["level"] is None
    assert assess.public_entries([full], "korea") == []  # 日韓照舊整筆拿掉


def test_public_entry_switch_off_is_hd43(monkeypatch):
    _switch_off(monkeypatch)
    full = {"id": "wn3", "windKt": 30.0, "levels": {}, "level": "high"}
    assert assess.public_entries([full], "taiwan") == [HIDDEN]
    assert assess.level_public() == frozenset()


# ---- `assemble` → `hide_wn3` ----


@pytest.mark.parametrize("wind", [10.0, 28.0, 43.71])
def test_level_is_the_voting_level(airports, wind):
    """公開的 `level` 就是記憶體裡那筆投票用的整體等級（`model_entry` 的 `level`）；只有 WN3 有
    資料時也等於這格模式層投票的結果。"""
    out = _assemble(airports, _data(airports, wind=wind))
    before = {
        a["icao"]: [e["level"] for e in _wn3_entries(a)]
        for a in out["airports"]
        if a["region"] not in WN3_EXCLUDED_REGIONS
    }
    build.hide_wn3(out)
    for a in out["airports"]:
        entries = _wn3_entries(a)
        if a["region"] in WN3_EXCLUDED_REGIONS:
            assert entries == [], a["icao"]
            continue
        assert entries == [{**HIDDEN, "level": lv} for lv in before[a["icao"]]], a["icao"]
        for s, e in zip(a["slots"], entries, strict=True):
            assert set(e) == PUBLIC_KEYS and e["level"] in (*LEVELS, None)
            assert e["level"] == s["model"]["vote"]["level"]
    assert out["models"][-1]["levelPublic"] is True
    text = json.dumps(out, ensure_ascii=False)
    assert not any(x in text for x in SECRETS)


def test_levels_differ_by_wind(airports):
    aps = [a for a in airports if a.icao == "RCTP"]
    got = set()
    for wind in (5.0, 28.0, 43.71):
        out = _assemble(aps, _data(aps, wind=wind))
        build.hide_wn3(out)
        got.add(_wn3_entries(out["airports"][0])[0]["level"])
    assert got == {"low", "medium", "high"}


def test_switch_off_output_equals_hd43(airports, monkeypatch):
    """關掉：沒有 `level`、沒有 `levelPublic`，其他每個位元組和開著的一樣。"""
    on = _assemble(airports, _data(airports))
    build.hide_wn3(on)
    _switch_off(monkeypatch)
    off = _assemble(airports, _data(airports))
    build.hide_wn3(off)
    assert "levelPublic" not in off["models"][-1]
    for a in off["airports"]:
        want = [] if a["region"] in WN3_EXCLUDED_REGIONS else [HIDDEN] * len(a["slots"])
        assert _wn3_entries(a) == want, a["icao"]
    assert json.dumps(off, ensure_ascii=False) == json.dumps(_strip_hd48(on), ensure_ascii=False)


# ---- AI 與其他讀公開快照的地方 ----


def test_public_entry_with_level_is_not_blend_data(airports):
    """公開快照（例如工具讀 `history/`）裡那筆有 `level` 但沒有數字：AI 不能把它當成有資料的
    多模式綜合那段（記憶體裡完整的那筆照舊算）。"""
    aps = [a for a in airports if a.icao == "RCTP"]
    out = _assemble(aps, _data(aps))
    a = out["airports"][0]
    assert prompt.has_blend(a)
    build.hide_wn3(out)
    assert _wn3_entries(a)[0]["level"] == "high"
    assert not prompt.has_blend(a)
    assert "[multi]" not in prompt.airport_text(a, out["generatedAt"])


def test_public_entry_does_not_vote_when_reread(airports):
    """重讀公開快照重算（`rescore`、`slot_causes`）時，只有 `level` 的那筆不算票（投票看
    `levels`）。"""
    aps = [a for a in airports if a.icao == "RCTP"]
    out = _assemble(aps, _data(aps))
    build.hide_wn3(out)
    entries = out["airports"][0]["slots"][0]["model"]["models"]
    _, v = assess.model_vote(entries)
    assert v["total"] == 0 and v["level"] is None


# ---- 整個 build ----


def test_build_publishes_level_only(workspace, monkeypatch, airports):  # noqa: F811
    """預設的整個 build：`latest.json`、`history/`、機場頁、`data` 分支寫出的每個檔，wn3 那筆
    只有 id、`valuesHidden`、`level`（日韓沒有），沒有 `levels`、沒有任何 WN3 數字。"""
    ws = workspace
    _fail_all_but(monkeypatch)
    bucket = FakeBucket()
    monkeypatch.setattr(wn3private.Bucket, "from_env", classmethod(lambda cls, env=None: bucket))
    monkeypatch.setattr(build.wn3, "fetch", lambda aps, r, start, end, **k: _data(aps, r))
    monkeypatch.setitem(ai_run.EVALUATORS, "claude", fake_ai("high"))
    monkeypatch.setitem(ai_run.EVALUATORS, "gemini", fake_ai("high"))
    assert build.main([]) == 0
    assert out_run(ws) == RUN.strftime("%Y-%m-%dT%H:%M:%SZ")

    out = json.loads((ws / "public" / "latest.json").read_text("utf-8"))
    top = out["models"][-1]
    assert (top["id"], top["valuesHidden"], top["levelPublic"]) == ("wn3", True, True)
    by = _by(out)
    assert [e["level"] for e in _wn3_entries(by["RCTP"])][0] == "high"
    for icao in JP_KR:
        assert _wn3_entries(by[icao]) == []
    rctp = json.loads((ws / "public" / "airports" / "tpe.json").read_text("utf-8"))
    for k in ("slots3h", "slots6h"):
        assert all(set(e) == PUBLIC_KEYS for e in _wn3_entries(rctp, k))
    hnd = json.loads((ws / "public" / "airports" / "hnd.json").read_text("utf-8"))
    assert _wn3_entries(hnd, "slots3h") == []

    files = [p for d in ("public", "data") for p in (ws / d).rglob("*.json") if p.is_file()]
    assert any("history" in p.as_posix() for p in files)
    for p in files:
        text = p.read_text("utf-8")
        assert not any(x in text for x in SECRETS), p
        for e in _wn3_dicts(json.loads(text)):
            assert "levels" not in e, p
            if "name" in e:  # 頂層 `models[]` 那筆
                continue
            assert set(e) <= PUBLIC_KEYS and e.get("valuesHidden") is True, p


def out_run(ws) -> str:
    return json.loads((ws / "public" / "latest.json").read_text("utf-8"))["runs"]["wn3"]


def test_build_switch_off_is_hd43(workspace, monkeypatch, airports):  # noqa: F811
    ws = workspace
    _switch_off(monkeypatch)
    _fail_all_but(monkeypatch)
    bucket = FakeBucket()
    monkeypatch.setattr(wn3private.Bucket, "from_env", classmethod(lambda cls, env=None: bucket))
    monkeypatch.setattr(build.wn3, "fetch", lambda aps, r, start, end, **k: _data(aps, r))
    monkeypatch.setitem(ai_run.EVALUATORS, "claude", fake_ai("high"))
    monkeypatch.setitem(ai_run.EVALUATORS, "gemini", fake_ai("high"))
    assert build.main([]) == 0
    out = json.loads((ws / "public" / "latest.json").read_text("utf-8"))
    assert "levelPublic" not in out["models"][-1]
    for a in out["airports"]:
        want = [] if a["region"] in WN3_EXCLUDED_REGIONS else [HIDDEN] * 20
        assert _wn3_entries(a) == want, a["icao"]
    rctp = json.loads((ws / "public" / "airports" / "tpe.json").read_text("utf-8"))
    assert _wn3_entries(rctp, "slots3h") == [HIDDEN] * 24
