"""HD47：AI 成本——快取前綴（規則燈說明排到最前面、Claude 第二個快取斷點）、共用前綴每一種各先評
一個、模式明細省略整個機場都沒資料的欄位、`tools/ai_cost.py --breakdown`。

全部不連網：SDK 回應用假物件，`Duel` 的模型換成假的 `evaluate`。
"""

from __future__ import annotations

import json
import threading
import time
from types import SimpleNamespace

from test_ai import (
    NOW,
    RUN,
    FakeAnthropic,
    FakeGenai,
    _gresp,
    _msg,
    _resp,
    _with_models,
    airport,
    duel_doc,
    lv,
)
from test_ai_usage import _row, _write_day, ai_cost
from test_build import latest  # noqa: F401

from hongthai.ai import claude, gemini, prompt
from hongthai.ai import run as ai_run


def _request_prefix(text: prompt.Prompt) -> list:
    """Claude 請求裡到第二個快取斷點為止的內容（系統提示＋共用前綴那個 block）。"""
    fake = FakeAnthropic(_msg(_resp()))
    claude.evaluate(text, client=fake)
    kw = fake.calls[0]
    content = kw["messages"][0]["content"]
    assert content[0]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in content[1]
    return [kw["system"], content[0]]


def test_cache_prefix_identical_for_airports_in_same_run(latest):  # noqa: F811
    """同一報兩個機場：提示詞到快取斷點為止逐字相同；機場自己的資料在斷點之後。"""
    gen = latest["generatedAt"]
    texts = [prompt.airport_text(a, gen) for a in latest["airports"][:2]]
    assert texts[0].own != texts[1].own
    assert texts[0].shared == texts[1].shared
    assert _request_prefix(texts[0]) == _request_prefix(texts[1])
    for t in texts:  # 全文＝共用前綴＋機場資料；規則燈說明在最前面、提醒在最後
        assert str(t) == f"{t.shared}\n{t.own}"
        assert t.startswith("[rule] 規則燈怎麼算") and t.own.startswith("機場：")
        assert t.endswith("（EC、GFS、p29Kt、p49Kt、TAF、METAR 這些）。")
        assert "機場：" not in t.shared and "提醒：" not in t.shared


def test_claude_sends_shared_prefix_as_cached_block():
    text = prompt.airport_text(airport("RCTP", lv(2, "medium")), RUN)
    fake = FakeAnthropic(_msg(_resp()))
    claude.evaluate(text, client=fake)
    content = fake.calls[0]["messages"][0]["content"]
    assert content == [
        {"type": "text", "text": text.shared + "\n", "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": text.own},
    ]
    assert "".join(b["text"] for b in content) == str(text)
    # 系統提示的快取 block 照舊（HD26）
    assert fake.calls[0]["system"][0]["text"] is prompt.SYSTEM
    # 一般字串照舊送一整段
    fake = FakeAnthropic(_msg(_resp()))
    claude.evaluate("文字", client=fake)
    assert fake.calls[0]["messages"] == [{"role": "user", "content": "文字"}]


def test_gemini_sends_full_text_same_order():
    text = prompt.airport_text(airport("RCTP", lv(2, "medium")), RUN)
    fake = FakeGenai(_gresp(_resp()))
    gemini.evaluate(text, client=fake)
    contents = fake.calls[0]["contents"]
    assert type(contents) is str and contents == str(text)
    assert contents.startswith("[rule] 規則燈怎麼算")


def test_prompt_is_plain_text_for_checks():
    """`Prompt` 照樣是字串：WN3 檢查算整數、測試比對、`copy` 都照舊。"""
    import copy

    t = prompt.Prompt("共用 48 節", "機場 7 節")
    assert t == "共用 48 節\n機場 7 節" and "48" in t
    c = copy.deepcopy(t)
    assert (c.shared, c.own) == (t.shared, t.own)


def test_empty_fields_only_when_empty_in_every_slot():
    """欄位只有在這個機場**每一格**都沒資料才省略；某一格有資料，其他格照寫「—」。"""
    ap = airport("RCTP", lv(2, "medium"))
    m0, m1 = ap["slots"][0]["model"], ap["slots"][1]["model"]
    _with_models(m0, {"aifs": {"gustKt": 43.4, "rain6hMm": 3.1, "ptype": "rain"}})
    _with_models(m1, {"aifs": {"gustKt": 40.0, "rain6hMm": 1.0, "ptype": "rain"}})
    m1["models"] = [{**e, "visibilityM": 800} if e["id"] == "gfs" else e for e in m1["models"]]
    lines = prompt.airport_text(ap, RUN).own.splitlines()
    gfs = [ln for ln in lines if ln.startswith("  - [gfs]")]
    assert "visibilityM —" in gfs[0] and "visibilityM 800 公尺" in gfs[1]
    ifs = [ln for ln in lines if ln.startswith("  - [ifs]")]
    assert all("visibilityM" not in ln and "ptype" not in ln for ln in ifs)
    assert "模式明細不列這個機場每一格都沒有資料的欄位" in next(
        ln for ln in lines if ln.startswith("每格（")
    )


def test_omitting_fields_keeps_numbers():
    """省略的都是「—」：文字裡的整數（WN3 防洩漏的比對基礎）和省略前一樣。"""
    from unittest import mock

    from hongthai.ai.parse import integers

    ap = airport("RCTP", lv(2, "medium"))
    _with_models(ap["slots"][0]["model"], {"aifs": {"gustKt": 43.4, "rain6hMm": 3.1}})
    after = prompt.airport_text(ap, RUN)
    with mock.patch.object(prompt, "empty_fields", lambda slots: {}):
        before = prompt.airport_text(ap, RUN)
    assert len(after) < len(before)
    assert integers(after) == integers(before)


def test_warmups_one_per_shared_prefix():
    P = prompt.Prompt
    items = [("A", P("x", "1")), ("B", P("x", "2")), ("C", P("y", "3")), ("D", P("x", "4"))]
    assert ai_run.warmups(items) == ["A", "C"]
    assert ai_run.warmups([("A", "文字"), ("B", "文字")]) == ["A"]
    assert ai_run.warmups([]) == []


def _timed(delay: float):
    log: list[tuple[str, float, float]] = []
    lock = threading.Lock()

    def evaluate(text, *, client=None, timeout=60):
        t0 = time.monotonic()
        time.sleep(delay)
        with lock:
            log.append((text.own.splitlines()[0], t0, time.monotonic()))
        return {
            "level": "low",
            "comment": {},
            "sentences": None,
            "usage": None,
        }

    return SimpleNamespace(make_client=object, evaluate=evaluate, log=log)


def test_claude_warms_each_shared_prefix_first(tmp_path, monkeypatch):
    """兩種共用前綴（有沒有多模式綜合）：每一種的第一個機場依序先單獨評完，其他的才開線。"""
    monkeypatch.setattr(prompt, "has_blend", lambda a: a["icao"] in ("RC02", "RC03", "RC04"))
    monkeypatch.setattr(ai_run, "ok", lambda key, res: {"status": "ok", "level": "low"})
    ev = {"claude": _timed(0.15), "gemini": _timed(0.0)}
    ai_run.evaluate_all(duel_doc(5, 0), None, NOW, tmp_path, evaluators=ev)
    calls = sorted(ev["claude"].log, key=lambda r: r[1])
    assert len(calls) == 5
    first, second, rest = calls[0], calls[1], calls[2:]
    assert "RC00" in first[0] and "RC02" in second[0]
    assert second[1] >= first[2]  # 依序
    assert all(r[1] >= second[2] for r in rest)  # 兩個都評完才開線
    assert rest[1][1] - rest[0][1] < 0.1  # 其他的並行


# ---- tools/ai_cost.py --breakdown ----


def _archive(tmp_path) -> None:
    """一報、兩個機場的快照與戰績（usage 是假的、和片數成比例）。"""
    a1 = airport("RCTP", lv(2, "medium"))
    a1["metar"] = {"raw": "METAR RCTP 190200Z 05015KT 9999 FEW020 25/20 Q1015", "windKt": 15}
    _with_models(a1["slots"][0]["model"], {"aifs": {"gustKt": 43.4, "rain6hMm": 3.1}})
    a2 = airport("RCKH", lv(4, "high"))
    snap = {"generatedAt": RUN, "sources": {}, "airports": [a1, a2]}
    (tmp_path / "history").mkdir(parents=True)
    (tmp_path / "history" / ai_cost.snapshot_name(RUN)).write_text(json.dumps(snap), "utf-8")
    texts = ai_cost._texts(a1, RUN), ai_cost._texts(a2, RUN)
    sys_p = ai_cost.pieces(prompt.SYSTEM)
    rows = []
    for (icao, t), first in zip(
        (("RCTP", texts[0]), ("RCKH", texts[1])), (True, False), strict=True
    ):
        whole = sys_p + sum(ai_cost.segment_pieces(str(t["before"])).values())
        cu = {
            "input": whole - sys_p,
            "output": 1000,
            "cacheRead": 0 if first else sys_p,
            "cacheWrite": sys_p if first else 0,
        }
        gu = {"input": whole, "output": 500, "thinking": None, "cacheRead": None}
        rows.append(_row(RUN, icao, cu, gu))
    _write_day(tmp_path, "2026-10-19", rows)


def test_ai_cost_breakdown(tmp_path, capsys):
    _archive(tmp_path)
    res = ai_cost.breakdown(tmp_path, ai_cost.load(tmp_path, "2026-10-19", None))
    assert res["calls"] == 2
    cl = res["models"]["claude"]
    assert cl["calibration"]["n"] == 2 and abs(cl["calibration"]["k"] - 1) < 0.01
    before, after = cl["before"], cl["after"]
    segs = {s["segment"]: s for s in after["segments"]}
    assert (
        segs["rules"]["shared"]
        and not {s["segment"]: s for s in before["segments"]}["rules"]["shared"]
    )
    assert {"system:rules", "system:wording", "header", "slot:rule", "reminders"} <= set(segs)
    assert any(s.startswith("model:") for s in segs)
    assert abs(sum(s["share"] for s in after["segments"]) - 1) < 0.01
    assert after["avgTokens"] < before["avgTokens"]  # 模式明細省略的欄位
    assert after["sharedTokens"] > before["sharedTokens"]
    assert after["estimate"]["hitRate"] > before["estimate"]["hitRate"]
    assert cl["sharedPrefixTokens"]["after"] > cl["sharedPrefixTokens"]["before"]
    assert res["models"]["gemini"]["after"]["estimate"]["hitRate"] == 0
    # 印表：只有 token 數，不印提示詞內容
    assert ai_cost.main(["--archive", str(tmp_path), "--from", "2026-10-19", "--breakdown"]) == 0
    out = capsys.readouterr().out
    assert "規則燈怎麼算（門檻說明）" in out and "命中" in out
    assert "METAR RCTP" not in out and "05015KT" not in out and "≥ 48 節" not in out
    assert (
        ai_cost.main(["--archive", str(tmp_path), "--from", "2026-10-19", "--breakdown", "--json"])
        == 0
    )
    assert json.loads(capsys.readouterr().out)["models"]["claude"]["calibration"]["n"] == 2


def test_ai_cost_breakdown_placeholder_blend():
    """公開快照的 WN3 只有 `valuesHidden`：用別的估算模式的數字當佔位重建長度。"""
    ap = airport("RCTP", lv(2, "medium"))
    m = ap["slots"][0]["model"]
    _with_models(m, {"aifs": {"gustKt": 43.4, "windKt": 21.7, "rain6hMm": 3.1}})
    m["models"] = [e for e in m["models"] if e["id"] != "wn3"]
    m["models"].append({"id": "wn3", "valuesHidden": True})
    filled = ai_cost.with_placeholder_blend(ap)
    wn3 = next(e for e in filled["slots"][0]["model"]["models"] if e["id"] == "wn3")
    assert wn3["gustKt"] == 43.4 and wn3["level"] == "medium"  # 歐洲 AI 模式的數字
    assert ap["slots"][0]["model"]["models"][-1] == {"id": "wn3", "valuesHidden": True}
