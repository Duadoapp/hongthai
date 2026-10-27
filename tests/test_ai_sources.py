"""HD40：AI 評論只陳述資料來源、不延伸推論＋逐句出處（提示詞、`sentences` 檢查、`latest.json`）。"""

from __future__ import annotations

import json
import re

import pytest
from test_ai import (
    COMMENT,
    NOW,
    RUN,
    SENTENCES,
    _resp,
    airport,
    as_sentences,
    duel_doc,
    fake_model,
    lv,
)
from test_build import latest  # noqa: F401

from hongthai import assess
from hongthai.ai import config, parse, prompt
from hongthai.ai import run as ai_run
from hongthai.ai.parse import AiError
from hongthai.config import MODELS as WEATHER_MODELS

LANGS = config.LANGS

# ---- 提示詞 ----


def test_system_prompt_no_extrapolation_rule():
    s = prompt.SYSTEM
    for must in (
        "只陳述資料來源說了什麼，不自行延伸推論",
        "每一句都要能在使用者訊息裡找到根據",
        "哪個來源、哪一格、什麼數字、幾個模式怎麼投",
        "「風會再增強」「颱風可能轉向」",
        "不能把一個來源的說法延伸到它沒涵蓋的時段或地點",
        "說明等級時只能引用資料",
        # 逐句出處
        "每一句附來源代號（src）",
        "只能用清單裡的代號，不能自己造",
        "四語的句數一樣、逐句對應",
        "同一個位置的句子 src 完全一樣",
        '"sentences"',
        '"src": ["taf", "ifs"]',
        "來源代號（使用者訊息每一段前面方括號裡的代號；src 只能用這些）：",
    ):
        assert must in s, must
    # 新規則緊接在原本第 1 條（只能根據數據）後面
    assert s.index("1. 只能根據使用者訊息") < s.index("2. 只陳述資料來源說了什麼")
    # 規則、來源代號、用字的順序
    assert s.index("規則：") < s.index("來源代號（") < s.index("用字：")
    # 模型不另寫一份整段短評（`comment` 由程式組）
    assert '"comment"' not in s


def test_source_list_in_prompt_matches_config():
    assert set(prompt.SOURCE_TEXT) == set(config.SOURCES)
    lines = [ln for ln in prompt.SYSTEM.splitlines() if re.match(r"- [a-z0-9-]+：", ln)]
    assert [ln.split("：")[0][2:] for ln in lines] == list(config.SOURCES)
    assert config.SOURCES == (
        "taf",
        "metar",
        "warning",
        "confirmed",
        "ifs",
        "gfs",
        "ifs-ens",
        "aifs",
        "aigfs",
        "icon",
        "jma",
        "wn2-ens",
        "vote",
        "rule",
    )
    # 給 AI 看的模式（`Model.ai`）每個都有代號；旁觀不給 AI 的三個沒有
    assert set(config.MODEL_SOURCES) == {m.id for m in WEATHER_MODELS if m.ai}
    assert not {"gem", "arpege", "cma"} & set(config.SOURCES)
    for m in config.MODEL_SOURCES:
        assert m in prompt.MODEL_TEXT


def test_source_names_four_languages():
    assert list(config.SOURCE_NAMES) == list(config.SOURCES)
    for code, names in config.SOURCE_NAMES.items():
        assert tuple(names) == LANGS, code
        assert all(isinstance(v, str) and v.strip() for v in names.values()), code
        assert not re.search(f"[{config.CJK_RANGES}]", names["en"]), code
        for ch in config.TRADITIONAL_CHARS:
            assert ch not in names["zh-CN"], (code, ch)
        for ch in config.SIMPLIFIED_CHARS:
            assert ch not in names["zh-TW"] and ch not in names["zh-HK"], (code, ch)
    # 模式名和短評的白話名一樣（`prompt.MODEL_TEXT`）
    for m in config.MODEL_SOURCES:
        assert config.SOURCE_NAMES[m]["zh-TW"] == prompt.MODEL_TEXT[m]


# ---- 精簡文字的來源標籤 ----

_TAG = re.compile(r"^\[([a-z0-9-]+)\] ")
_SLOT = re.compile(r"^\d+\. ")


def unlabeled(text: str) -> list[str]:
    """`airport_text` 裡沒有（或用了不在清單裡的）來源代號的段落；空的就是每一段都有。

    規則：`prompt.UNLABELED` 開頭的行不標；每格那一行（`1. …`）時段之後 `｜` 隔開的每一段、
    模式明細（`  - …`）與其他行都要以 `[代號] ` 開頭；`- ` 開頭的行是上一個有代號的段落底下的
    明細。"""
    bad: list[str] = []
    labeled = False
    for line in text.splitlines():
        if line.startswith(prompt.UNLABELED):
            labeled = False
            continue
        if _SLOT.match(line):
            parts = line.split("｜")[1:]
            bad += [p for p in parts if not ((m := _TAG.match(p)) and m[1] in config.SOURCES)]
            labeled = bool(parts)
            continue
        body = line[4:] if line.startswith("  - ") else line
        if (m := _TAG.match(body)) is not None:
            if m[1] not in config.SOURCES:
                bad.append(line)
            labeled = True
        elif line.startswith("- ") and labeled:
            continue
        else:
            bad.append(line)
    return bad


def tags(text: str) -> set[str]:
    return set(re.findall(r"\[([a-z0-9-]+)\] ", text))


def test_airport_text_every_segment_has_source(latest):  # noqa: F811
    seen: set[str] = set()
    for a in latest["airports"]:
        text = prompt.airport_text(a, latest["generatedAt"])
        assert unlabeled(text) == [], a["icao"]
        seen |= tags(text)
    assert seen <= set(config.SOURCES)
    # 樣本有 TAF、METAR、警報、已確認停飛、投票與規則燈
    assert {"taf", "metar", "warning", "confirmed", "vote", "rule", "ifs", "gfs"} <= seen


def _models_slot(ids: list[str]) -> dict:
    entries = [
        {"id": m, "gustKt": 40, "level": "medium", "levels": {"wind": "medium"}, "p49Kt": 0.2}
        for m in ids
    ]
    return {"level": "low", "vote": {"level": "low"}, "models": entries, "ec": {}}


def test_airport_text_all_models_labeled():
    """每個給 AI 看的模式都有一行、代號就是模式的 id。"""
    ap = airport("RCKH", lv(0, "high", 19))
    ap["slots"][0]["model"] = _models_slot(list(config.MODEL_SOURCES))
    text = prompt.airport_text(ap, RUN)
    assert unlabeled(text) == []
    assert set(config.MODEL_SOURCES) <= tags(text)
    for m in config.MODEL_SOURCES:
        assert f"  - [{m}] {prompt.MODEL_TEXT[m]}：" in text


def test_unlabeled_catches_new_segment(latest):  # noqa: F811
    """`airport_text` 多了沒有代號的新段落（或新的一格欄位、未知代號）要被抓到。"""
    a = next(a for a in latest["airports"] if a["icao"] == "VHHH")
    text = prompt.airport_text(a, latest["generatedAt"])
    assert unlabeled(text + "\n航班動態：準點率 80%") == ["航班動態：準點率 80%"]
    assert unlabeled(text + "\n[flights] 航班動態：準點率 80%") == [
        "[flights] 航班動態：準點率 80%"
    ]
    slot = next(ln for ln in text.splitlines() if ln.startswith("1. "))
    assert unlabeled(text.replace(slot, slot + "｜新欄位 3")) == ["新欄位 3"]
    assert unlabeled(text.replace(slot, slot + "｜[new] 新欄位 3")) == ["[new] 新欄位 3"]


def test_airport_text_hidden_or_unknown_model_flagged():
    """`models[]` 有沒代號的模式（例如之後加了模式卻沒加進 `MODEL_SOURCES`）會被抓到。"""
    ap = airport("RCKH", lv(0, "high", 19))
    ap["slots"][0]["model"] = _models_slot(["ifs", "zz"])
    assert unlabeled(prompt.airport_text(ap, RUN)) == [
        "  - [zz] zz：陣風 40 節、側風 —、"
        "rain6hMm —、ptype —、visibilityM —、等級 medium（wind medium、rain —、snow —、fog —）"
    ]


def test_metar_official_slot_tagged_metar(latest):  # noqa: F811
    """HD13：沒有 TAF 的機場第一格官方層是觀測，代號是 `metar`。"""
    ap = airport("RCFG", lv(0, "high", 19))
    ap["slots"][0]["official"] = {
        "kind": "metar",
        "level": "high",
        "windKt": 2.9,
        "gustKt": None,
        "crosswindKt": None,
        "warnings": [],
    }
    line = next(ln for ln in prompt.airport_text(ap, RUN).splitlines() if ln.startswith("1. "))
    assert "｜[metar] 官方：等級 high、METAR（觀測）平均風 2.9 節" in line
    assert "｜[warning] 套用的警報 無｜" in line


# ---- 回覆檢查 ----


def two_sentences(src2: list[str] | None = None) -> dict:
    return {
        "zh-TW": [
            {"text": "強風是主因，五個模式中三個認為高。", "src": ["vote"]},
            {"text": "10/23 14–20 時歐洲模式陣風 75 節。", "src": src2 or ["ifs"]},
        ],
        "zh-HK": [
            {"text": "強風是主因，五個模式中三個認為高。", "src": ["vote"]},
            {"text": "10/23 14–20 時歐洲模式陣風 75 節。", "src": src2 or ["ifs"]},
        ],
        "zh-CN": [
            {"text": "强风是主因，五个模式中三个认为高。", "src": ["vote"]},
            {"text": "10/23 14–20 时欧洲模式阵风 75 节。", "src": src2 or ["ifs"]},
        ],
        "en": [
            {
                "text": "Strong wind is the main cause; three of five models say High.",
                "src": ["vote"],
            },
            {"text": "European model gusts 75 kt on 10/23 14:00–20:00.", "src": src2 or ["ifs"]},
        ],
    }


def raw(sentences: object, **kw) -> str:
    return json.dumps({"level": "high", "sentences": sentences, **kw}, ensure_ascii=False)


def test_parse_sentences_and_joined_comment():
    sentences = two_sentences(["taf", "ifs", "gfs"])
    # 模型自己另給的 `comment` 不用（程式組）
    res = parse.parse_response(raw(sentences, comment={lang: "別的" for lang in LANGS}))
    assert res["level"] == "high"
    assert res["sentences"] == sentences
    assert res["sentences"]["en"][1]["src"] == ["taf", "ifs", "gfs"]  # 照模型給的順序
    assert res["comment"] == {
        "zh-TW": "強風是主因，五個模式中三個認為高。10/23 14–20 時歐洲模式陣風 75 節。",
        "zh-HK": "強風是主因，五個模式中三個認為高。10/23 14–20 時歐洲模式陣風 75 節。",
        "zh-CN": "强风是主因，五个模式中三个认为高。10/23 14–20 时欧洲模式阵风 75 节。",
        "en": "Strong wind is the main cause; three of five models say High. "
        "European model gusts 75 kt on 10/23 14:00–20:00.",
    }


def test_parse_strips_sentence_whitespace():
    s = two_sentences()
    s["en"][0]["text"] = "  Strong wind is the main cause.  "
    res = parse.parse_response(raw(s))
    assert res["sentences"]["en"][0]["text"] == "Strong wind is the main cause."
    assert res["comment"]["en"].startswith("Strong wind is the main cause. European")


def _bad(text: str) -> AiError:
    with pytest.raises(AiError) as e:
        parse.parse_response(text)
    assert e.value.code == "bad_format"
    return e.value


def _mut(fn) -> dict:
    s = two_sentences()
    fn(s)
    return s


@pytest.mark.parametrize(
    ("text", "tag"),
    [
        # 舊格式（只有 comment）
        (json.dumps({"level": "high", "comment": COMMENT}, ensure_ascii=False), "no_sentences"),
        (raw("一段"), "no_sentences"),
        (raw([{"text": "x", "src": ["ifs"]}]), "no_sentences"),
        # 缺一語、空陣列、不是陣列
        (raw({k: v for k, v in two_sentences().items() if k != "zh-CN"}), "missing_zh-CN"),
        (raw({**two_sentences(), "en": []}), "missing_en"),
        (raw({**two_sentences(), "zh-HK": "強風是主因。"}), "missing_zh-HK"),
        # 句子不是物件、text 空白或不是字串
        (raw(_mut(lambda s: s["zh-TW"].__setitem__(0, "強風。"))), "zh-TW_sentence"),
        (raw(_mut(lambda s: s["en"][1].__setitem__("text", "  "))), "en_sentence"),
        (raw(_mut(lambda s: s["en"][1].pop("text"))), "en_sentence"),
        # 缺 src、空的、不是字串陣列
        (raw(_mut(lambda s: s["zh-TW"][0].pop("src"))), "zh-TW_no_src"),
        (raw(_mut(lambda s: s["zh-HK"][1].__setitem__("src", []))), "zh-HK_no_src"),
        (raw(_mut(lambda s: s["zh-CN"][1].__setitem__("src", "ifs"))), "zh-CN_no_src"),
        (raw(_mut(lambda s: s["en"][0].__setitem__("src", ["vote", 1]))), "en_no_src"),
        # 未知代號（含大小寫、精簡文字以外的名字、旁觀模式）
        (
            raw(_mut(lambda s: s["zh-TW"][0].__setitem__("src", ["vote", "news"]))),
            "zh-TW_src_unknown",
        ),
        (raw(_mut(lambda s: s["en"][0].__setitem__("src", ["TAF"]))), "en_src_unknown"),
        (raw(_mut(lambda s: s["en"][0].__setitem__("src", ["[taf]"]))), "en_src_unknown"),
        (raw(_mut(lambda s: s["zh-CN"][1].__setitem__("src", ["cma"]))), "zh-CN_src_unknown"),
        # 四語句數不同
        (raw(_mut(lambda s: s["en"].pop())), "sentence_count"),
        (
            raw(_mut(lambda s: s["zh-HK"].append({"text": "另一句。", "src": ["rule"]}))),
            "sentence_count",
        ),
        # 同一個位置的 src 不同（代號不同、順序不同、多一個）
        (raw(_mut(lambda s: s["zh-CN"][1].__setitem__("src", ["gfs"]))), "src_mismatch"),
        (
            raw(
                _mut(
                    lambda s: (
                        [s[lang][1].__setitem__("src", ["ifs", "gfs"]) for lang in LANGS]
                        and s["en"][1].__setitem__("src", ["gfs", "ifs"])
                    )
                )
            ),
            "src_mismatch",
        ),
        (raw(_mut(lambda s: s["en"][0].__setitem__("src", ["vote", "rule"]))), "src_mismatch"),
    ],
)
def test_parse_sentences_bad_format(text, tag):
    assert _bad(text).tag == tag


def test_parse_joined_length_limit():
    """字數上限算接起來的整段（中文每語 300、en 800）。"""
    s = two_sentences()
    s["zh-TW"] = [{"text": "長" * 150, "src": ["vote"]}, {"text": "長" * 150, "src": ["ifs"]}]
    assert parse.parse_response(raw(s))["comment"]["zh-TW"] == "長" * 300
    s["zh-TW"][1]["text"] = "長" * 151
    assert _bad(raw(s)).tag == "zh-TW_too_long"
    s = two_sentences()
    s["en"] = [{"text": "x" * 400, "src": ["vote"]}, {"text": "x" * 399, "src": ["ifs"]}]
    assert len(parse.parse_response(raw(s))["comment"]["en"]) == 800  # 中間一個空白
    s["en"][1]["text"] = "x" * 400
    assert _bad(raw(s)).tag == "en_too_long"


def test_parse_wording_checked_on_joined_comment():
    """用字檢查照舊（`check_wording`），對象是接起來的整段：TAF 分在兩句也只能出現一次。"""
    s = two_sentences()
    s["zh-TW"][0]["text"] = "機場預報（TAF）陣風 46 節。"
    s["zh-TW"][1]["text"] = "TAF 之後轉弱。"
    with pytest.raises(AiError) as e:
        parse.parse_response(raw(s))
    assert str(e.value) == "bad_wording: zh-TW：TAF 出現第 2 次"
    s = two_sentences()
    s["zh-HK"][1]["text"] = "風險集中喺 10/23。"
    with pytest.raises(AiError) as e:
        parse.parse_response(raw(s))
    assert e.value.tag == "zh-HK/喺"


@pytest.mark.parametrize(
    ("lang", "text", "tag"),
    [
        ("zh-TW", "歐洲模式陣風 75 節 [ifs]。", "zh-TW/[ifs]"),
        ("zh-CN", "欧洲模式阵风 75 节［ifs-ens］。", "zh-CN/［ifs-ens］"),
        ("en", "European model gusts 75 kt [IFS].", "en/[IFS]"),
        ("en", "Three of five models say High [vote].", "en/[vote]"),
    ],
)
def test_parse_source_tag_in_text_is_bad_wording(lang, text, tag):
    """代號只放 `src`：句子裡寫了 `[代號]` → `bad_wording`。"""
    s = two_sentences()
    s[lang][1]["text"] = text
    with pytest.raises(AiError) as e:
        parse.parse_response(raw(s))
    assert e.value.code == "bad_wording" and e.value.tag == tag


def test_parse_brackets_without_code_ok():
    s = two_sentences()
    s["en"][1]["text"] = "European model gusts 75 kt [estimated gusts excluded]."
    assert parse.parse_response(raw(s))["level"] == "high"


# ---- latest.json 的 ai ----

# HD40 之前的燈（`ai.<燈>`），HD40 只多 `sentences`
OLD_OK = {"status": "ok", "level": "high", "comment": COMMENT, "model": "claude-opus-5-5"}
OLD_ERROR = {
    "status": "error",
    "level": None,
    "comment": None,
    "model": "gemini-4-argon",
    "error": "bad_format",
}


def test_latest_ai_only_adds_sentences(tmp_path):
    cl, ge = fake_model("high"), fake_model(exc="bad_format")
    res = ai_run.evaluate_all(
        duel_doc(), None, NOW, tmp_path, evaluators={"claude": cl, "gemini": ge}
    )
    risky, quiet = res["airports"]["RC00"], res["airports"]["ZZ00"]
    assert set(risky) == {"evaluatedAt", "claude", "gemini"}
    for light, old in ((risky["claude"], OLD_OK), (risky["gemini"], OLD_ERROR)):
        assert set(light) == set(old) | {"sentences"}
        assert {k: v for k, v in light.items() if k != "sentences"} == old
    assert risky["claude"]["sentences"] == SENTENCES
    assert risky["gemini"]["sentences"] is None
    for k in config.KEYS:
        old = {"status": "skipped", "level": "low", "comment": config.NO_RISK}
        assert quiet[k] == {**old, "model": config.MODELS[k], "sentences": None}
    # 頂層 `ai`、`sources.ai` 不變
    assert res["ai"] == {"disclaimer": config.DISCLAIMER, "models": config.MODELS}
    assert set(res["source"]) == {"ok", "calls", "errors"}


def test_fallback_and_run_cap_lights_have_null_sentences():
    doc = {"generatedAt": RUN, "airports": [airport("RCTP")]}
    res = ai_run.fallback(doc, "network")
    for k in config.KEYS:
        assert res["airports"]["RCTP"][k]["sentences"] is None
    assert ai_run.error("claude", "run_cap")["sentences"] is None


def test_ok_light_from_real_parse():
    """`parse_response` 的結果直接進燈：`comment`＝句子接起來、`sentences` 照存。"""
    parsed = parse.parse_response(_resp())
    light = ai_run.ok("claude", parsed)
    assert light == {**OLD_OK, "sentences": as_sentences(COMMENT)}


def test_assess_models_unchanged_for_prompt():
    """HD33b 的旁觀模式照舊不給 AI（沒有代號、不在精簡文字裡）。"""
    assert assess.ai_hidden() == {"gem", "arpege", "cma"}
