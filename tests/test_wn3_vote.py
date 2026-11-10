"""WeatherNext 3 投一票（HD43）：`vote` 模式（預設）的投票、`latest.json`／機場頁／`data` 分支沒有
WN3 的數值、日本與南韓排除、私人 bucket 的逐時檔、AI 的「多模式綜合」段與洩漏檢查（重生 → 拿掉那段
重生 → 照一般流程）。數值全是手造的（不是真的 WN3 資料），全部不連網。"""

from __future__ import annotations

import json
import logging
import threading
from datetime import timedelta
from itertools import takewhile
from types import SimpleNamespace

import pytest
from conftest import ROOT, utc
from test_build import NOW, _fail_all_but, _timing_lines, fake_ai, workspace  # noqa: F401
from test_wn3_private import FakeBucket

from hongthai import assess, build, wn3private, wn3report
from hongthai.ai import config as ai_config
from hongthai.ai import parse, prompt
from hongthai.ai import run as ai_run
from hongthai.config import WN3_EXCLUDED_REGIONS, wn3_allowed
from hongthai.sources import wn3

RUN = utc(2026, 10, 17, 18)  # NOW 08:10Z − 8 小時 30 分 → 前一天 18Z 那報
# 手造的「認得出來」的數字：p50 43.71 節 → `windKt` 43.7、估算陣風 × 1.4 ＝ 61.2；平均 40.73、
# p90 52.19。公開的地方（Pages、`data` 分支、日誌）一個都不能出現
WIND, MEAN, P90 = 43.71, 40.73, 52.19
SECRETS = ("43.71", "43.7", "61.2", "40.73", "52.19", "52.2")
JP_KR = ("ROAH", "RJTT", "RJCC", "RKSI", "RKPC")
HIDDEN = {"id": "wn3", "valuesHidden": True}


def _data(airports, run=RUN, wind=WIND):
    return wn3.Wn3Data(
        run,
        {
            a.icao: [
                wn3.Wn3Hour(run + timedelta(hours=h), wind, MEAN, P90, 90.0, 0.5, 25.0)
                for h in range(1, 145)
            ]
            for a in airports
        },
        "bigquery",
        0,
        estimate_bytes=6_000_000_000,
        bytes_processed=4_000_000_000,
        bytes_billed=4_000_000_000,
    )


def _wn3_entries(doc_airport: dict, key: str = "slots") -> list[dict]:
    return [e for s in doc_airport[key] for e in s["model"]["models"] if e["id"] == "wn3"]


def _by(doc: dict) -> dict[str, dict]:
    return {a["icao"]: a for a in doc["airports"]}


# ---- 設定與日韓排除 ----


def test_excluded_regions_are_the_15_japan_korea_airports(airports):
    """用 `airports.json` 的 `region`：沖繩 3、日本 8、韓國 4，共 15 個機場。"""
    out = [a for a in airports if not wn3_allowed(a.region)]
    assert len(out) == 15 and {a.region for a in out} == WN3_EXCLUDED_REGIONS
    assert all(a.tz in ("Asia/Tokyo", "Asia/Seoul") for a in out)
    assert all(a.tz not in ("Asia/Tokyo", "Asia/Seoul") for a in airports if wn3_allowed(a.region))


def test_public_entries_hide_values_and_drop_japan_korea():
    full = {"id": "wn3", "run": "x", "windKt": 43.7, "gustKt": 61.2, "levels": {}, "level": "high"}
    other = {"id": "ifs", "gustKt": 50.0, "level": "high"}
    assert assess.public_entries([other, full], "taiwan") == [other, HIDDEN]
    assert assess.public_entries([other, full], "japan") == [other]
    assert assess.values_hidden() == {"wn3"}


# ---- 投票（`assemble`）----


def _assemble(airports, wn=None):
    regions = build.load_regions(ROOT / "airports.json")
    return build.assemble(
        now=NOW,
        regions=regions,
        airports=airports,
        confirmed=[],
        status={},
        ec=None,
        gf=None,
        tf=None,
        hk=None,
        cw=None,
        wn=wn,
    )


def test_wn3_votes_outside_japan_korea(airports):
    out = _assemble(airports, _data(airports))
    by = _by(out)
    assert out["runs"]["wn3"] == "2026-10-17T18:00:00Z"
    assert out["models"][-1] == {
        "id": "wn3",
        "name": {k: "Google WeatherNext 3" for k in ("zh-TW", "zh-HK", "zh-CN", "en")},
        "voting": True,
        "votesOnlyHigh": False,
        "valuesHidden": True,
    }
    # 其他模式都沒資料：桃園只有 WN3 一票（估算陣風 61.2 ≥ 48 → 高）；日韓沒有票
    s = by["RCTP"]["slots"][0]
    assert (s["model"]["vote"]["total"], s["model"]["vote"]["high"]) == (1, 1)
    assert s["model"]["level"] == "high" and s["level"] == "high" and s["causes"] == ["wind"]
    for icao in JP_KR:
        t = by[icao]["slots"][0]
        assert t["model"]["vote"]["total"] == 0 and t["level"] == "unknown", icao
        assert all(e["level"] is None for e in _wn3_entries(by[icao]))  # 記憶體裡是空的那筆
    # 記憶體裡那筆是完整的（投票、AI 用）；寫出去之前才藏
    e = _wn3_entries(by["RCTP"])[0]
    assert (e["windKt"], e["gustKt"], e["level"]) == (43.7, 61.2, "high")
    build.hide_wn3(out)
    by = _by(out)
    assert _wn3_entries(by["RCTP"]) == [HIDDEN] * 20
    assert all(_wn3_entries(by[icao]) == [] for icao in JP_KR)
    assert by["RCTP"]["slots"][0]["model"]["vote"]["total"] == 1  # 票數照實（含 WN3）
    text = json.dumps(out, ensure_ascii=False)
    assert not any(x in text for x in SECRETS)


# ---- 私人 bucket（`observe_vote`）----


def test_observe_vote_writes_points_then_reads_them(airports):
    aps = [a for a in airports if a.icao in ("RCTP", "RJTT")]
    asked = []

    def fetch(aps_, r, start, end, **k):
        asked.append((r, start, end, k))
        return _data(aps_, r)

    bucket = FakeBucket()
    res = wn3report.observe_vote(aps, NOW, {}, bucket, fetch)
    end = utc(2026, 10, 18, 6) + timedelta(hours=120)
    assert asked == [(RUN, RUN - timedelta(hours=6), end, {"mslp": False, "retry_previous": True})]
    assert (res.run, res.stored, res.queried) == (RUN, "written", True)
    assert set(bucket.objects) == {"observe/20261017T1800Z.json", "points/20261017T1800Z.json"}
    obs = bucket.objects["observe/20261017T1800Z.json"]
    assert obs["mode"] == "vote" and obs["license"] == wn3.TERMS_URL
    assert obs["airports"]["RJTT"][0]["windKt"] == 43.7  # 私人那份 51 個機場都有（內部檢視頁）
    pts = bucket.objects["points/20261017T1800Z.json"]
    assert pts["airports"]["RCTP"][0] == ["2026-10-17T19:00:00Z", WIND, MEAN, P90, 90.0, 0.5, 25.0]

    # 同一報：從 points/ 讀，不查；讀回來的和原本一樣
    asked.clear()
    again = wn3report.observe_vote(aps, NOW + timedelta(minutes=15), {}, bucket, fetch)
    assert asked == [] and (again.stored, again.queried) == ("exists", False)
    assert again.data.points == res.data.points and again.data.via == "bigquery"


def test_observe_vote_falls_back_to_previous_points(airports):
    aps = [a for a in airports if a.icao == "RCTP"]
    bucket = FakeBucket()
    bucket.objects[wn3private.points_name(RUN)] = wn3report.points_doc(_data(aps))

    def not_yet(aps_, r, start, end, **k):
        assert (r, start, k["retry_previous"]) == (RUN + timedelta(hours=6), r, False)
        raise wn3.Wn3Error("沒有資料", "no_rows")

    res = wn3report.observe_vote(aps, NOW + timedelta(hours=6), {}, bucket, not_yet)
    assert (res.run, res.stored, res.latest_error) == (RUN, "previous", "no_rows")
    assert res.queried is False
    assert res.data.points["RCTP"][0].wind_kt == WIND
    # 前一報也沒有 → 照樣失敗
    with pytest.raises(wn3.Wn3Error):
        wn3report.observe_vote(aps, NOW + timedelta(hours=12), {}, bucket, not_yet_any)


def not_yet_any(*a, **k):
    raise wn3.Wn3Error("沒有資料", "no_rows")


def test_bad_points_file_is_source_error(airports):
    bucket = FakeBucket({wn3private.points_name(RUN): {"model": "wn3", "run": "壞的"}})
    with pytest.raises(wn3private.PrivateError) as e:
        wn3report.observe_vote(airports[:1], NOW, {}, bucket, not_yet_any)
    assert e.value.code == "gcs_bad_points" and "壞的" not in str(e.value)


# ---- 整個 build ----


def _parsed(body: str) -> dict:
    """同 `claude.evaluate`：解析失敗時 `AiError.usage` 也有 token 數。"""
    usage = {"input": 1000, "output": 100, "cacheRead": 0, "cacheWrite": 0}
    try:
        return {**parse.parse_response(body), "usage": usage}
    except parse.AiError as e:
        e.usage = usage
        raise


def _scripted(*responses):
    """假的 AI 模型：依序回 `responses`（模型回應的 JSON 字串，用真的 `parse_response` 解析），
    記下每次收到的精簡文字。"""
    texts: list[str] = []
    it = iter(responses)

    def evaluate(text, *, client=None, timeout=60):
        texts.append(text)
        return _parsed(next(it))

    return SimpleNamespace(make_client=object, evaluate=evaluate), texts


def _leak_once():
    """假的 AI 模型（build 裡多個機場平行評）：每段精簡文字第一次回 `LEAK_NUMBER`、之後
    `GOOD_MULTI`。"""
    texts: list[str] = []
    lock = threading.Lock()

    def evaluate(text, *, client=None, timeout=60):
        with lock:
            first = text not in texts
            texts.append(text)
        return _parsed(LEAK_NUMBER if first else GOOD_MULTI)

    return SimpleNamespace(make_client=object, evaluate=evaluate), texts


def _sentences(zh: str, zh_cn: str, en: str, src: list[str]) -> dict:
    return {
        lang: [{"text": t, "src": src}]
        for lang, t in (("zh-TW", zh), ("zh-HK", zh), ("zh-CN", zh_cn), ("en", en))
    }


def _resp(sentences: dict) -> str:
    return json.dumps({"level": "high", "sentences": sentences}, ensure_ascii=False)


LEAK_NUMBER = _resp(
    _sentences(
        "多模式綜合估算陣風 61 節，停飛風險高。",
        "多模式综合估算阵风 61 节，停飞风险高。",
        "The multi-model blend shows estimated gusts of 61 kt; disruption risk High.",
        ["multi"],
    )
)
LEAK_NAME = _resp(
    _sentences(
        "主因是強風，停飛風險高。",
        "主因是强风，停飞风险高。",
        "Mainly strong wind per Weather Next; disruption risk High.",
        ["vote"],
    )
)
GOOD_MULTI = _resp(
    _sentences(
        "主因是強風：模式投票認為高，停飛風險高。",
        "主因是强风：模式投票认为高，停飞风险高。",
        "Mainly strong wind: the model vote says High; disruption risk High.",
        ["vote", "multi"],
    )
)
GOOD_PLAIN = _resp(
    _sentences(
        "主因是強風：模式投票認為高，停飛風險高。",
        "主因是强风：模式投票认为高，停飞风险高。",
        "Mainly strong wind: the model vote says High; disruption risk High.",
        ["vote"],
    )
)


def test_vote_build_hides_values_everywhere(workspace, monkeypatch, airports, caplog):  # noqa: F811
    """`vote`（預設）的整個 build：私人 bucket 拿到整份與逐時檔；`latest.json`、`history/`、
    機場頁、Pages、`timing/`、`history/ai/` 與日誌都沒有 WN3 的任何數值；票數含 WN3、日韓不含；
    AI 拿得到多模式綜合那段（違規一次 → 重生）。第二報從 `points/` 讀、不查。"""
    ws = workspace
    _fail_all_but(monkeypatch)
    bucket = FakeBucket()
    monkeypatch.setattr(wn3private.Bucket, "from_env", classmethod(lambda cls, env=None: bucket))
    asked = []

    def fetch(aps, r, start, end, **k):
        asked.append(r)
        return _data(aps, r)

    monkeypatch.setattr(build.wn3, "fetch", fetch)
    claude, texts = _leak_once()
    monkeypatch.setitem(ai_run.EVALUATORS, "claude", claude)
    monkeypatch.setitem(ai_run.EVALUATORS, "gemini", fake_ai("high"))
    caplog.set_level(logging.DEBUG)
    assert build.main([]) == 0
    assert build.wn3_mode() == "vote" and asked == [RUN]
    assert set(bucket.objects) == {"observe/20261017T1800Z.json", "points/20261017T1800Z.json"}

    out = json.loads((ws / "public" / "latest.json").read_text("utf-8"))
    by = _by(out)
    assert out["models"][-1]["valuesHidden"] is True and out["runs"]["wn3"] == iso_run()
    for a in out["airports"]:
        want = [] if a["region"] in WN3_EXCLUDED_REGIONS else [HIDDEN] * 20
        assert _wn3_entries(a) == want, a["icao"]
    assert by["RCTP"]["slots"][0]["model"]["vote"]["total"] == 1
    assert by["RCTP"]["slots"][0]["level"] == "high"
    assert by["RJTT"]["slots"][0]["model"]["vote"]["total"] == 0
    src = out["sources"]["wn3"]
    assert isinstance(src.pop("seconds"), float)
    attribution = src.pop("attribution")
    assert attribution.startswith("Google WeatherNext 3 via Google BigQuery. © 2024-6 Google LLC")
    assert "experimental modelling only" in attribution and wn3.TERMS_URL in attribution
    assert src == {
        "ok": True,
        "run": "2026-10-17T18:00:00Z",
        "stored": "written",
        "via": "bigquery",
        "bytes": 0,
        "estimateBytes": 6_000_000_000,
        "bytesProcessed": 4_000_000_000,
        "bytesBilled": 4_000_000_000,
        "mode": "vote",
        "rain": True,  # HD49
    }
    # 機場頁（3 小時格）也一樣
    rctp = json.loads((ws / "public" / "airports" / "tpe.json").read_text("utf-8"))
    assert _wn3_entries(rctp, "slots3h") == [HIDDEN] * 24
    assert _wn3_entries(rctp, "slots6h") == [HIDDEN] * 8
    hnd = json.loads((ws / "public" / "airports" / "hnd.json").read_text("utf-8"))
    assert _wn3_entries(hnd, "slots3h") == [] and _wn3_entries(hnd, "slots6h") == []

    # AI：桃園的精簡文字有多模式綜合那段（內部輸入，有數字）；違規一次 → 同一段文字重生
    tpe = [t for t in texts if "（Taoyuan，RCTP" in t]
    assert len(tpe) == 2 and tpe[0] == tpe[1]
    assert "[multi] 多模式綜合" in tpe[0] and "估算陣風 61.2 節" in tpe[0]
    for name in ("WeatherNext", "WN3", "新一代"):
        assert name not in tpe[0]
    assert by["RCTP"]["ai"]["claude"]["status"] == "ok"
    ai_src = out["sources"]["ai"]
    n = ai_src["calls"]["claude"] // 2
    assert ai_src["wn3Retries"] == {"claude": n, "gemini": 0}
    assert ai_src["wn3Dropped"] == {"claude": 0, "gemini": 0}

    # 公開的地方（Pages、data 分支的整個 checkout）一個數字都沒有、也沒有事件檔
    public = [p for d in ("public", "data") for p in (ws / d).rglob("*") if p.is_file()]
    assert any("history/ai" in p.as_posix() for p in public)
    for p in public:
        if p.suffix == ".png":
            continue
        text = p.read_text("utf-8", errors="replace")
        assert not any(x in text for x in SECRETS), p
        assert "[multi]" not in text and "多模式綜合（另一個模式" not in text, p  # 提示詞不存
    assert not list((ws / "data").rglob("wn3/*.json"))
    line = next(x for x in _timing_lines(ws) if x["source"] == "wn3")
    assert (line["ok"], line["mode"], line["stored"]) == (True, "vote", "written")
    logs = "\n".join(r.getMessage() for r in caplog.records)
    assert "WeatherNext 3 投票" in logs and not any(x in logs for x in SECRETS)
    assert "wn3/number" in logs and "61 節" not in logs  # 違規只記標記，不記內容

    # 第二次（同一報）：從 points/ 讀、不查 BigQuery，照樣投票
    asked.clear()
    monkeypatch.setitem(ai_run.EVALUATORS, "claude", fake_ai("high"))
    assert build.main(["--trigger", "manual"]) == 0
    assert asked == []
    out = json.loads((ws / "public" / "latest.json").read_text("utf-8"))
    src = out["sources"]["wn3"]
    assert src["stored"] == "exists" and "via" not in src and "bytesBilled" not in src
    assert "attribution" in src
    assert _by(out)["RCTP"]["slots"][0]["model"]["vote"]["total"] == 1


def iso_run() -> str:
    return "2026-10-17T18:00:00Z"


# ---- AI：多模式綜合那段與檢查 ----


@pytest.fixture
def blended(airports):
    """`assemble` 出來、還沒藏的 `latest`（AI 看的那份）：桃園有 WN3、成田沒有。"""
    aps = [a for a in airports if a.icao in ("RCTP", "RJAA")]
    return _assemble(aps, _data(aps))


def test_airport_text_blend_only_outside_japan_korea(blended):
    by = _by(blended)
    gen = blended["generatedAt"]
    text = prompt.airport_text(by["RCTP"], gen)
    plain = prompt.airport_text(by["RCTP"], gen, wn3=False)
    lines = text.splitlines()
    i = lines.index(next(x for x in lines if x.startswith("[multi]")))
    assert "不能引用這段的任何數字" in lines[i] and "不能說是哪個模式說的" in lines[i]
    assert lines[i + 1].startswith("- 1. ") and "平均風 43.7 節、估算陣風 61.2 節" in lines[i + 1]
    assert len(list(takewhile(lambda x: x.startswith("- "), lines[i + 1 :]))) == 20
    assert lines[i + 21].startswith("提醒：")  # HD47：規則燈說明移到最前面（共用前綴）
    assert text.startswith("[rule] 規則燈怎麼算") and text.shared.startswith("[rule] 規則燈怎麼算")
    assert plain.shared == text.shared  # 拿掉那段重生時共用前綴不變（照樣命中快取）
    assert "[multi]" not in plain and "61.2" not in plain and "43.7" not in plain
    # 一般的模式明細沒有它、投票句含它那一票、規則說明多一句
    assert "Google 的新一代" not in text and "WeatherNext" not in text
    assert "投票（強風）：1 個模式中 1 個認為高 → high" in text
    assert "另有一個模式也投一票" in text and "另有一個模式也投一票" in plain
    # 日韓：沒有那段、規則也不提
    nrt = prompt.airport_text(by["RJAA"], gen)
    assert "[multi]" not in nrt and "另有一個模式" not in nrt
    assert not prompt.has_blend(by["RJAA"]) and prompt.has_blend(by["RCTP"])


def test_wn3_numbers_exclude_values_seen_elsewhere(blended):
    a = _by(blended)["RCTP"]
    nums = prompt.wn3_numbers(a, blended["generatedAt"])
    assert {44, 61} <= nums  # 43.7、61.2 四捨五入
    assert 3 not in nums  # 6 小時雨量 3 毫米：格的編號也有 3
    # 和其他來源同值的數字（例如門檻 48）不算 WN3 獨有
    for s in a["slots"]:
        for e in s["model"]["models"]:
            if e["id"] == "wn3":
                e["gustKt"] = 48.0
    assert 48 not in prompt.wn3_numbers(a, blended["generatedAt"])


def test_check_wn3_names_numbers_and_multi_code():
    def sents(text: str, src=("vote",)) -> dict:
        return {lang: [{"text": text, "src": list(src)}] for lang in ai_config.LANGS}

    nums = frozenset({44, 61})
    parse.check_wn3(sents("模式投票認為高，陣風門檻 48 節。"), nums)  # 不是獨有的數字
    with pytest.raises(parse.Wn3Leak) as e:
        parse.check_wn3(sents("估算陣風 61 節。"), nums)
    assert (e.value.code, e.value.tag) == ("bad_wording", "wn3/number")
    assert "61" not in str(e.value)
    with pytest.raises(parse.Wn3Leak):
        parse.check_wn3(sents("估算陣風 60.6 節。"), nums)  # 四捨五入後 61
    with pytest.raises(parse.Wn3Leak):
        parse.check_wn3(sents("估算陣風 ６１ 節。"), nums)  # 全形數字
    # 這次沒有那段：src 不能用 multi
    parse.check_wn3(sents("估算陣風 61 節。"), None)
    with pytest.raises(parse.AiError) as e:
        parse.check_wn3(sents("模式投票認為高。", ("vote", "multi")), None)
    assert (e.value.code, e.value.tag) == ("bad_format", "zh-TW_src_unknown")


@pytest.mark.parametrize(
    "en",
    [
        "WeatherNext says High; disruption risk High.",
        "Weather Next 3 says High; disruption risk High.",
        "WN3 says High; disruption risk High.",
        "wn-3 says High; disruption risk High.",
        "Google's next-generation AI ensemble says High; disruption risk High.",
    ],
)
def test_wn3_names_rejected_before_other_wording(en):
    body = _resp(_sentences("停飛風險高。", "停飞风险高。", en, ["vote"]))
    with pytest.raises(parse.Wn3Leak) as e:
        parse.parse_response(body)
    assert e.value.tag == "wn3/name"
    zh = _resp(_sentences("Google 的新一代 AI 系集認為高。", "停飞风险高。", "High.", ["vote"]))
    with pytest.raises(parse.Wn3Leak):
        parse.parse_response(zh)


def test_prompt_rules_mention_multi():
    assert "multi" in ai_config.SOURCES and "multi" in prompt.SOURCE_TEXT
    assert "- multi：多模式綜合" in prompt.SYSTEM
    assert "不能寫出那段的任何數字" in prompt.SYSTEM and "11. 只回一個 JSON 物件" in prompt.SYSTEM
    for name in ("WeatherNext 3", "新一代"):
        assert name not in prompt.SOURCE_TEXT["multi"]
    assert ai_config.SOURCE_NAMES["multi"]["en"] == "Multi-model blend"


def _duel(doc, tmp_path, *claude_responses):
    claude, texts = _scripted(*claude_responses)
    evaluators = {"claude": claude, "gemini": fake_ai("high")}
    duel = ai_run.Duel(doc, None, NOW, tmp_path, evaluators=evaluators)
    return duel.run(), texts


def test_leak_twice_then_drops_blend(blended, tmp_path):
    """違規 → 同一段文字重生 → 又違規 → 拿掉那段重生（`multi` 不能再用）→ 過了。"""
    doc = {**blended, "airports": [_by(blended)["RCTP"]]}
    res, texts = _duel(doc, tmp_path, LEAK_NUMBER, LEAK_NAME, GOOD_PLAIN)
    assert len(texts) == 3 and texts[0] == texts[1]
    assert "[multi]" in texts[0] and "[multi]" not in texts[2]
    light = res["airports"]["RCTP"]["claude"]
    assert light["status"] == "ok" and light["sentences"]["zh-TW"][0]["src"] == ["vote"]
    src = res["source"]
    assert src["calls"]["claude"] == 3
    assert src["wn3Retries"] == {"claude": 2, "gemini": 0}
    assert src["wn3Dropped"] == {"claude": 1, "gemini": 0}
    assert res["usage"]["claude"]["calls"] == 3  # 丟掉的兩次也算錢
    rows = json.loads((tmp_path / "ai" / "2026-10-18.json").read_text("utf-8"))
    assert "detail" not in rows[0]["claude"]
    record = json.dumps(rows, ensure_ascii=False)
    assert not any(x in record for x in ("61", "43.7", "多模式", "multi"))


def test_leak_three_times_is_bad_wording(blended, tmp_path):
    doc = {**blended, "airports": [_by(blended)["RCTP"]]}
    res, texts = _duel(doc, tmp_path, LEAK_NAME, LEAK_NAME, LEAK_NAME)
    assert len(texts) == 3 and "[multi]" not in texts[2]
    light = res["airports"]["RCTP"]["claude"]
    assert (light["status"], light["error"]) == ("error", "bad_wording")
    rows = json.loads((tmp_path / "ai" / "2026-10-18.json").read_text("utf-8"))
    assert rows[0]["claude"]["detail"] == "bad_wording:-:-:wn3/name"
    assert res["source"]["wn3Retries"]["claude"] == 2


def test_leak_once_then_ok_keeps_blend(blended, tmp_path):
    doc = {**blended, "airports": [_by(blended)["RCTP"]]}
    res, texts = _duel(doc, tmp_path, LEAK_NUMBER, GOOD_MULTI)
    assert len(texts) == 2 and texts[0] == texts[1]
    assert res["airports"]["RCTP"]["claude"]["sentences"]["en"][0]["src"] == ["vote", "multi"]
    assert res["source"]["wn3Retries"] == {"claude": 1, "gemini": 0}
    assert res["source"]["wn3Dropped"] == {"claude": 0, "gemini": 0}


def test_no_blend_airport_cannot_use_multi_and_does_not_regenerate(airports, tmp_path):
    """沒有那段的機場（這一報沒有 WN3，或日韓）：`src` 用 `multi` 是格式錯、不重生；沒有計數的
    鍵。"""
    aps = [a for a in airports if a.icao == "RCTP"]
    doc = _assemble(aps, _data(aps))
    for s in doc["airports"][0]["slots"]:  # WN3 那筆沒資料（像日韓），但讓這個機場被選上
        s["model"]["models"] = [e for e in s["model"]["models"] if e["id"] != "wn3"]
    res, texts = _duel(doc, tmp_path, GOOD_MULTI)
    assert len(texts) == 1 and "[multi]" not in texts[0]
    light = res["airports"]["RCTP"]["claude"]
    assert (light["status"], light["error"]) == ("error", "bad_format")
    assert "wn3Retries" not in res["source"]


def test_bad_format_log_has_no_response_text_for_blend_airports(blended, tmp_path, caplog):
    """有那段的機場：`bad_format` 的 log 不印回應內容（一般機場會印前 80 字）。"""
    doc = {**blended, "airports": [_by(blended)["RCTP"]]}
    caplog.set_level(logging.DEBUG)
    res, _ = _duel(doc, tmp_path, "估算陣風 61.2 節，不是 JSON")
    assert res["airports"]["RCTP"]["claude"]["error"] == "bad_format"
    logs = "\n".join(r.getMessage() for r in caplog.records)
    assert "AI claude RCTP 失敗：bad_format［bad_format:-:-:not_json］" in logs
    assert "61.2" not in logs


# ---- HD49：雨量 ----

# 手造的雨量：每小時 12.37 mm → 6 小時 74.22 → `rain6hMm` 74.2（≥ 60 → 雨高）。風很小（只有雨投高）
RAIN_H, RAIN_6H = 12.37, 74.2
RAIN_SECRETS = ("12.37", "74.2", "74.22")


def _rain_data(airports, run=RUN, zarr=False):
    """`zarr`：Zarr 讀到的樣子（風每 6 小時、其他小時只有雨量）；否則每小時都有風
    （同 BigQuery）。"""
    hours = []
    for h in range(1, 145):
        windy = not zarr or h % 6 == 0
        hours.append(
            (h, 8.0 if windy else None, 7.0 if windy else None, 10.0 if windy else None, RAIN_H)
        )
    return wn3.Wn3Data(
        run,
        {
            a.icao: [
                wn3.Wn3Hour(
                    run + timedelta(hours=h), w, m, p, 90.0 if w is not None else None, r, None
                )
                for h, w, m, p, r in hours
            ]
            for a in airports
        },
        "zarr" if zarr else "bigquery",
        rain=True,
    )


@pytest.mark.parametrize("zarr", [False, True])
def test_wn3_rain_votes_and_public_has_no_values(airports, zarr):
    aps = [a for a in airports if a.icao in ("RCTP", "RJTT")]
    out = _assemble(aps, _rain_data(aps, zarr=zarr))
    by = _by(out)
    s = by["RCTP"]["slots"][0]
    e = next(x for x in s["model"]["models"] if x["id"] == "wn3")
    assert e["rain6hMm"] == RAIN_6H and e["ptype"] is None
    assert (e["levels"]["rain"], e["levels"]["snow"], e["levels"]["fog"]) == ("high", None, None)
    assert e["levels"]["wind"] == "low" and e["level"] == "high"
    # WN3 是唯一有資料的模式：雨的投票＝高，整格模式層高、主因是雨
    assert s["model"]["level"] == "high" and s["causes"] == ["rain"]
    # 日韓照舊沒有 WN3
    rjtt = next(x for x in by["RJTT"]["slots"][0]["model"]["models"] if x["id"] == "wn3")
    assert rjtt["rain6hMm"] is None and rjtt["level"] is None
    build.hide_wn3(out)
    text = json.dumps(out, ensure_ascii=False)
    assert not any(x in text for x in RAIN_SECRETS)
    assert _wn3_entries(_by(out)["RCTP"]) == [HIDDEN] * 20


def test_zarr_shaped_points_round_trip(airports):
    """Zarr 的逐時檔（6 的倍數以外的小時風是 null、只有雨量）寫進 `points/` 再讀回來一樣；
    算出來的格和直接用的一樣。"""
    aps = [a for a in airports if a.icao == "RCTP"]
    data = _rain_data(aps, zarr=True)
    doc = wn3report.points_doc(data)
    assert doc["airports"]["RCTP"][0] == [
        "2026-10-17T19:00:00Z",
        None,
        None,
        None,
        None,
        RAIN_H,
        None,
    ]
    back = wn3report.data_from_points(json.loads(json.dumps(doc)), RUN)
    assert back.points == data.points and wn3.has_rain(back)
    start = RUN + timedelta(hours=6)
    a = assess.wn3_for_slot(back.points["RCTP"], start, start + timedelta(hours=6))
    assert a["rain6hMm"] == RAIN_6H and a["windKt"] == 8.0


def test_sources_wn3_rain_fields(airports):
    """`sources.wn3` 的 `rain`／`rainError`（HD49）：只有布林與錯誤碼，沒有任何數值。"""
    aps = [a for a in airports if a.icao == "RCTP"]
    ok = _rain_data(aps, zarr=True)
    assert build._wn3_extra(ok)["rain"] is True and "rainError" not in build._wn3_extra(ok)
    no = _data(aps)
    no.via, no.rain, no.rain_error = "zarr", False, "rain_timeout"
    d = build._wn3_extra(no)
    assert (d["rain"], d["rainError"]) == (False, "rain_timeout")
    assert not any(x in json.dumps(d) for x in SECRETS + RAIN_SECRETS)
    # 從 `points/` 讀回來的（沒查）：看裡面有沒有雨量
    exists = build._wn3_private_extra(wn3report.PrivateResult(RUN, "exists", ok))
    assert exists["rain"] is True and "bytes" not in exists
    dry = wn3.Wn3Data(RUN, {"RCTP": [wn3.Wn3Hour(RUN, 8.0, 7.0, 10.0, 0.0, None)]}, "zarr")
    assert build._wn3_private_extra(wn3report.PrivateResult(RUN, "exists", dry))["rain"] is False
    queried = build._wn3_private_extra(wn3report.PrivateResult(RUN, "written", no, queried=True))
    assert (queried["rain"], queried["rainError"]) == (False, "rain_timeout")


def test_check_wn3_blocks_rain_numbers(airports):
    """AI：多模式綜合那段多了雨量數字，`wn3_numbers` 算進去，含那個數字的句子被擋。"""
    aps = [a for a in airports if a.icao == "RCTP"]
    doc = _assemble(aps, _rain_data(aps))
    a = _by(doc)["RCTP"]
    text = prompt.airport_text(a, doc["generatedAt"])
    assert "6 小時雨量 74.2 毫米" in text
    nums = prompt.wn3_numbers(a, doc["generatedAt"])
    assert 74 in nums
    sents = {
        lang: [{"text": "預估 6 小時雨量 74 毫米。", "src": ["multi"]}] for lang in ai_config.LANGS
    }
    with pytest.raises(parse.Wn3Leak) as e:
        parse.check_wn3(sents, nums)
    assert e.value.tag == "wn3/number"
    sents = {lang: [{"text": "雨量約 74.2 毫米。", "src": ["multi"]}] for lang in ai_config.LANGS}
    with pytest.raises(parse.Wn3Leak):
        parse.check_wn3(sents, nums)


def test_archived_rain_doc_still_reads(tmp_path, airports):
    """搬到公開 `history/` 的那份（`public_doc`）多了雨量數字：格式只是原本的
    `rain6hMm`／`levels.rain` 有值；`tools/report_29w.py` 讀新舊兩種檔都不壞。"""
    from test_report_29w import rpt

    aps = [a for a in airports if a.icao == "RCTP"]
    new = wn3private.public_doc(wn3report.report_doc(_rain_data(aps, zarr=True), aps, {}, "vote"))
    old = wn3private.public_doc(wn3report.report_doc(_data(aps), aps, {}, "vote"))
    row = new["airports"]["RCTP"][0]
    assert set(row) == set(old["airports"]["RCTP"][0])  # 欄位不變
    assert (row["rain6hMm"], row["levels"]["rain"]) == (RAIN_6H, "high")
    d = tmp_path / "ev"
    for run, doc in ((RUN, new), (RUN - timedelta(hours=6), old)):
        doc = {**doc, "run": iso_run() if run == RUN else "2026-10-17T12:00:00Z"}
        wn3report.write_report(wn3private.report_path(d, run), doc)
    runs = rpt.load_wn3(d, ["RCTP"])
    assert len(runs) == 2 and all(len(r.airports["RCTP"]) == 20 for r in runs)
