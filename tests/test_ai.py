"""AI 對決（HD5、HD6）：選機場、提示文字、回應解析與用字檢查、兩個模型的呼叫、每日上限、輸出結構、
戰績檔。

全部不連網：SDK 用假物件，`Duel` 的模型換成假的 `evaluate`。
"""

from __future__ import annotations

import json
import re
import threading
import time
from datetime import timedelta
from types import SimpleNamespace

import anthropic
import httpx2
import pytest
from conftest import utc
from google.genai import errors as genai_errors
from google.genai import types as genai_types
from test_build import latest  # noqa: F401

from hongthai import assess, build
from hongthai.ai import claude, config, gemini, parse, prompt, select
from hongthai.ai import run as ai_run
from hongthai.ai.parse import AiError
from hongthai.config import Thresholds

T0 = utc(2026, 10, 19, 0)
RUN = "2026-10-19T02:15:00Z"
NOW = utc(2026, 10, 19, 2, 15)
LANGS = ("zh-TW", "zh-HK", "zh-CN", "en")
COMMENT = {
    "zh-TW": "10/23 14–20 時歐洲模式陣風 75 節、側風 51 節，陣風超過 49 節的機率 56%，停飛風險高。",
    "zh-HK": "10/23 14–20 時歐洲模式陣風 75 節、側風 51 節，陣風超過 49 節的機率 56%，停飛風險高。",
    "zh-CN": "10/23 14–20 时欧洲模式阵风 75 节、侧风 51 节，阵风超过 49 节的概率 56%，停飞风险高。",
    "en": "10/23 14:00–20:00: European model gusts 75 kt, crosswind 51 kt, 56% chance of gusts "
    "over 49 kt; disruption risk High.",
}
ENV_KEYS = [k for keys in config.ENV.values() for k in keys]


def slots(levels: list[str], t0=T0) -> list[dict]:
    out = []
    for i, lv in enumerate(levels):
        a, b = t0 + timedelta(hours=6 * i), t0 + timedelta(hours=6 * (i + 1))
        out.append(
            {
                "from": a.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "to": b.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "level": lv,
                "basis": "model",
                "official": None,
                "model": {
                    "ec": {"hresGustKt": 40.0, "crosswindKt": 20.0, "p29Kt": 0.5, "p49Kt": 0.1},
                    "gfs": {"gustKt": 30.0, "crosswindKt": 10.0},
                    "level": lv,
                    "agreement": "disagree",
                },
                "gap": False,
            }
        )
    return out


def airport(icao: str, levels: list[str] | None = None) -> dict:
    return {
        "icao": icao,
        "iata": icao[1:],
        "tz": "Asia/Taipei",
        "name": {"zh-TW": icao, "zh-HK": icao, "zh-CN": icao, "en": icao},
        "official": {"warnings": True},
        "warnings": [],
        "metar": None,
        "taf": None,
        "slots": slots(levels or ["low"] * 20),
        "confirmed": [],
    }


def doc(*airports: dict) -> dict:
    return {"generatedAt": RUN, "sources": {}, "airports": list(airports)}


def lv(n_low: int, level: str, n_after: int = 0, after: str = "low") -> list[str]:
    return ["low"] * n_low + [level] + [after] * (19 - n_low - n_after) + ["low"] * n_after


# ---- 選機場 ----


def test_candidates_level_and_changed():
    cur = doc(
        airport("RCTP", lv(5, "medium")),
        airport("RCSS"),  # 全低、沒變 → 不選
        airport("RCKH"),  # 全低，但和上一份比有一格變了 → changed
        airport("VHHH", lv(0, "confirmed")),
    )
    prev = doc(airport("RCTP"), airport("RCSS"), airport("RCKH", lv(3, "medium")))
    got = [(a["icao"], why) for a, why in select.candidates(cur, prev)]
    assert got == [("VHHH", "level"), ("RCTP", "level"), ("RCKH", "changed")]
    # 沒有上一份就沒有「有變」
    assert [a["icao"] for a, _ in select.candidates(cur, None)] == ["VHHH", "RCTP"]


def test_candidates_changed_only_compares_same_from():
    prev_ap = airport("RCKH", lv(0, "medium"))
    for s in prev_ap["slots"]:  # 上一份的格整個錯開 → 沒有同一個 from 可比
        s["from"] = s["from"].replace("T00", "T03")
    assert select.candidates(doc(airport("RCKH")), doc(prev_ap)) == []
    # unknown → low 也算有變（「任一格 level 不同」）
    cur = airport("RCKH")
    prev2 = airport("RCKH", ["unknown"] * 20)
    assert select.candidates(doc(cur), doc(prev2))[0][1] == "changed"


def test_candidates_sorted_by_max_level_then_first_slot_and_capped():
    aps = [airport(f"RC{i:02d}", lv(i % 19, "medium")) for i in range(25)]
    aps.append(airport("ZZHI", lv(15, "high")))
    aps.append(airport("ZZH2", lv(2, "high")))
    aps.append(airport("ZZCF", lv(18, "confirmed")))
    got = select.candidates(doc(*aps), None)
    assert len(got) == config.MAX_AIRPORTS == 20
    icaos = [a["icao"] for a, _ in got]
    assert icaos[:3] == ["ZZCF", "ZZH2", "ZZHI"]
    # 中級的依第一個中級格早的在前，同格照原順序
    firsts = [
        next(i for i, s in enumerate(a["slots"]) if s["level"] == "medium") for a, _ in got[3:]
    ]
    assert firsts == sorted(firsts)
    assert icaos[3:5] == ["RC00", "RC19"]  # 都是第 0 格，照原順序
    assert len(select.qualifying(doc(*aps), None)) == 28


def test_max_level():
    assert select.max_level(airport("RCTP", lv(3, "high"))) == ("high", "2026-10-19T18:00:00Z")
    assert select.max_level(airport("RCTP", ["unknown"] * 20)) == (None, None)


# ---- 提示文字 ----


def test_system_prompt_rules():
    s = prompt.SYSTEM
    for must in (
        "只能根據",
        "不能自己估",
        "60–120 字",
        "zh-HK",
        "zh-CN",
        "en",
        "不得增減",
        '"level"',
    ):
        assert must in s
    # 用字四條與對照表（HD6）
    for must in (
        "用字：",
        "不出現內部代號",
        "歐洲模式",
        "美國模式",
        "陣風超過 49 節的機率 56%",
        "機場預報（TAF）",
        "機場觀測",
        "不用粵語口語",
        "颱風警報 → 颱風警告",
        "八號信號",
        "飯店 → 酒店",
        "計程車 → 的士",
        "公車 → 巴士",
        "颱風 → 台风",
        "側風 → 侧风",
        "機場預報 → 机场预报",
        "信號 → 信号",
        "節 → 节",
        "機率 → 概率（不是「机率」）",  # HD7
        "資料 → 数据（不是「资料」）",
        "不寫英文等級字",
        "高（high）",
        "停飛風險",
        "停飞风险",
        "disruption risk",
        "12–13 h local",
        "不增不減",
    ):
        assert must in s, must
    assert s.index("規則：") < s.index("用字：")
    assert s.endswith("不要在 JSON 外面寫任何字、不要加 Markdown 標記。")
    assert "p49Kt 30%" not in s  # 規則 2 的例子改成白話


def test_airport_text_contains_data_and_units(latest):  # noqa: F811
    vhhh = next(a for a in latest["airports"] if a["icao"] == "VHHH")
    text = prompt.airport_text(vhhh, latest["generatedAt"])
    assert "香港（Hong Kong，VHHH／HKG），時區 Asia/Hong_Kong（UTC+8）" in text
    assert vhhh["metar"]["raw"] in text and vhhh["taf"]["raw"] in text
    assert vhhh["warnings"][0]["text"]["zh-TW"] in text  # 生效中的警報（8 號信號）
    assert "已確認停飛：\n- 當地 10/19 08:00–10/19 14:00" in text
    lines = [ln for ln in text.splitlines() if re.match(r"\d+\. ", ln)]
    assert len(lines) == 20
    first = lines[0]
    assert first.startswith("1. 10/18 14–20 時｜等級 high（依據 官方）")
    assert "熱帶氣旋信號" in first and "落差" in first
    assert "節" in text and "%" in text and "m/s" not in text and "Ms" not in text
    assert "p29Kt" in text and "p49Kt" in text
    # 規則燈的門檻
    for t in ("≥ 48 節 → high", "≥ 37 節 → medium", "≥ 33 節 → high", "≥ 27 節 → medium", "≥ 30%"):
        assert t in text
    assert "{" not in text  # 不是整段 JSON
    assert text.endswith(
        "短評裡請用白話，不要照抄上面的欄位名（EC、GFS、p29Kt、p49Kt、TAF、METAR 這些）。"
    )


def test_airport_text_weather_types():
    """HD8：每格的 causes、官方層 wx、模式層雨量／型態／能見度；METAR 的能見度與天氣。"""
    ap = airport("RCKH", lv(2, "medium"))
    ap["metar"] = {
        "observedAt": RUN,
        "windDirDeg": 90,
        "windKt": 5,
        "gustKt": None,
        "raw": "METAR RCKH 0300 FG VV001",
        "visibilityM": 300,
        "wx": ["FG"],
        "ceilingFt": 100,
    }
    s0 = ap["slots"][0]
    s0["causes"] = ["fog", "rain"]
    s0["official"] = {
        "windKt": 5,
        "gustKt": None,
        "kind": "main",
        "level": "high",
        "crosswindKt": None,
        "warnings": [],
        "wx": {
            "phenomena": ["FG", "+TSRA"],
            "visibilityM": 300,
            "ceilingFt": 100,
            "rain": "medium",
            "snow": "low",
            "fog": "high",
        },
    }
    s0["model"]["ec"].update(rain6hMm=35.2, ptype="rain", p24hRain50=0.4)
    s0["model"]["gfs"].update(rain6hMm=12.0, ptype="snow", visibilityM=800)
    _with_models(s0["model"])
    text = prompt.airport_text(ap, RUN)
    lines = text.splitlines()
    i = next(i for i, ln in enumerate(lines) if ln.startswith("1. "))
    line = lines[i]
    assert "causes fog（濃霧）、rain（大雨）" in line
    assert (
        "wx（現象 FG +TSRA、能見度 300 公尺、雲底 100 呎、rain medium、snow low、fog high）" in line
    )
    assert "p49Kt 10%、p24hRain50 40%" in line
    # HD14：每個模式一行，接在那一格後面
    ifs = "  - 歐洲模式：陣風 40 節、側風 20 節、rain6hMm 35.2 mm、ptype rain"
    gfs = "  - 美國模式：陣風 30 節、側風 10 節、rain6hMm 12 mm、ptype snow、visibilityM 800 公尺"
    assert lines[i + 1].startswith(ifs) and lines[i + 2].startswith(gfs)
    assert "能見度 300 公尺、天氣 FG、雲底 100 呎" in text  # METAR
    second = next(ln for ln in text.splitlines() if ln.startswith("2. "))
    assert "causes 無" in second
    # 規則說明有三類的門檻與「說出主因」
    assert "能見度 < 400 公尺或雲底 ≤ 100 呎 → high" in text
    assert "6 小時雨量 ≥ 60 mm → high" in text
    assert "模式層的霧最高只到 medium" in text  # HD10
    assert "短評要說出主要是哪種天氣造成" in text
    assert "第一句要點出主因天氣" in prompt.SYSTEM


def _with_models(m: dict, others: dict | None = None) -> dict:
    """用 `assess` 把 `ec`／`gfs`（＋其他模式的數字）組成 `models[]` 與 `vote`（HD14）。"""
    th = Thresholds()
    assess.fill_model_wx(m["ec"], m["gfs"], th)
    m["models"] = assess.model_entries(m["ec"], m["gfs"], others or {}, {}, th)
    _, m["vote"] = assess.model_vote(m["models"])
    m["level"] = m["vote"]["level"]
    return m


def test_airport_text_models_and_vote_hd14():
    """HD14：投票句、每個模式一行（白話名、估算陣風標「估」）、系集只投高。"""
    ap = airport("RCTP", lv(2, "medium"))
    m = ap["slots"][0]["model"]
    m["ec"].update(hresGustKt=50.0, p49Kt=0.4)
    m["gfs"].update(gustKt=49.0)
    _with_models(
        m,
        {
            "aifs": {"gustKt": 43.4, "crosswindKt": 20.0, "rain6hMm": 3.1, "ptype": "rain"},
            "aigfs": {"gustKt": 14.0, "rain6hMm": 0.4},
        },
    )
    text = prompt.airport_text(ap, RUN)
    lines = text.splitlines()
    i = next(i for i, ln in enumerate(lines) if ln.startswith("1. "))
    assert "模式：等級 high、投票（強風）：5 個模式中 3 個認為高 → high、" in lines[i]
    assert lines[i + 1 : i + 6] == [
        "  - 歐洲模式：陣風 50 節、側風 20 節、rain6hMm —、ptype —、visibilityM —、"
        "等級 high（wind high、rain —、snow —、fog —）",
        "  - 美國模式：陣風 49 節、側風 10 節、rain6hMm —、ptype —、visibilityM —、"
        "等級 high（wind high、rain —、snow —、fog —）",
        "  - 歐洲系集：p49Kt 40% → 投 high（只投高）",
        "  - 歐洲 AI 模式：陣風 43.4 節（估）、側風 20 節、rain6hMm 3.1 mm、ptype rain、"
        "visibilityM —、等級 medium（wind medium、rain low、snow low、fog —）",
        "  - 美國 AI 模式：陣風 14 節（估）、側風 —、rain6hMm 0.4 mm、ptype —、visibilityM —、"
        "等級 low（wind low、rain low、snow —、fog —）",
    ]
    assert lines[i + 6].startswith("2. ")
    # 規則說明：投票、系集只投高、估算陣風
    assert "達到有資料模式數的一半就成立" in text
    assert "歐洲系集只投 high：p49Kt ≥ 30% 投 high" in text
    assert "10 米平均風 × 1.4 估算（標「估」）" in text
    for must in ("估算陣風", "estimated gust", "五個模式中三個認為高", "US AI model"):
        assert must in prompt.SYSTEM, must


def test_airport_text_vote_low_and_thin_hd14():
    ap = airport("RCTP")
    m = ap["slots"][0]["model"]
    m["ec"] = {}
    _with_models(m)
    line = next(ln for ln in prompt.airport_text(ap, RUN).splitlines() if ln.startswith("1. "))
    assert "投票：每一類都沒有過半的模式認為中以上 → low（風只有 1 個模式有資料）" in line
    ap["slots"][0]["model"] = {"ec": {}, "gfs": {}, "level": None, "agreement": None}
    _with_models(ap["slots"][0]["model"])
    line = next(ln for ln in prompt.airport_text(ap, RUN).splitlines() if ln.startswith("1. "))
    assert "投票：沒有模式資料" in line


def test_airport_text_cwa_station_metar():
    """HD13：金門、馬祖的 METAR 是氣象署局屬站觀測，第一格的官方層由它撐起。"""
    ap = airport("RCBS", lv(2, "medium"))
    ap["metar"] = {
        "observedAt": RUN,
        "windDirDeg": 90,
        "windKt": 2.9,
        "gustKt": 6.2,
        "raw": "CWA 467110 2026-10-18T08:00Z 能見度 0.3 km 陰有霧 風 090° 1.5 m/s",
        "visibilityM": 300,
        "wx": ["FG"],
        "ceilingFt": None,
        "source": "cwa",
    }
    ap["slots"][0]["official"] = {
        "windKt": 2.9,
        "gustKt": 6.2,
        "kind": "metar",
        "level": "high",
        "crosswindKt": 2.7,
        "warnings": ["cwa_dense_fog"],
        "wx": None,
    }
    text = prompt.airport_text(ap, RUN)
    assert "METAR（氣象署局屬站觀測、觀測 當地" in text
    line = next(ln for ln in text.splitlines() if ln.startswith("1. "))
    assert "官方：等級 high、METAR（觀測）平均風 2.9 節" in line
    assert "警報 濃霧特報" in line


def test_airport_text_without_optional_data():
    ap = airport("RCKH", lv(2, "medium"))
    ap["official"] = {"warnings": False}
    ap["slots"][0]["model"] = None
    ap["slots"][1]["official"] = {
        "windKt": 25,
        "gustKt": None,
        "kind": "tempo",
        "level": "low",
        "crosswindKt": None,
        "warnings": ["typhoon_sea"],
    }
    text = prompt.airport_text(ap, RUN)
    assert "METAR：無" in text and "TAF：無" in text
    assert "沒有接官方警報來源" in text
    assert "模式：無" in text
    assert "TAF（tempo）平均風 25 節、陣風 —、側風 —、警報 海上颱風警報" in text


# ---- 回應解析 ----


def _resp(**kw) -> str:
    return json.dumps({"level": "high", "comment": dict(COMMENT), **kw}, ensure_ascii=False)


def test_parse_ok_and_fenced():
    assert parse.parse_response(_resp()) == {"level": "high", "comment": COMMENT}
    assert parse.parse_response("```json\n" + _resp() + "\n```")["level"] == "high"


@pytest.mark.parametrize(
    "text",
    [
        "以下是評論：\n" + _resp() + "\n以上。",
        "Here is the JSON:\n```json\n" + _resp() + "\n```",
        _resp() + "\n（依據第 3–5 格）",
    ],
)
def test_parse_json_with_surrounding_text(text):
    assert parse.parse_response(text) == {"level": "high", "comment": COMMENT}


@pytest.mark.parametrize(
    "text",
    [
        "這不是 JSON",
        "[1, 2]",
        _resp(level="severe"),
        _resp(level="confirmed"),
        _resp(comment={k: v for k, v in COMMENT.items() if k != "zh-CN"}),
        _resp(comment={**COMMENT, "en": "  "}),
        _resp(comment={**COMMENT, "zh-HK": "長" * 301}),
        _resp(comment={**COMMENT, "en": "x" * 801}),
        _resp(comment="一段"),
        "說明 { 不是 JSON }",
        _resp()[:-30],  # 被截斷
    ],
)
def test_parse_bad_format(text):
    with pytest.raises(AiError) as e:
        parse.parse_response(text)
    assert e.value.code == "bad_format"


def test_parse_length_limits():
    """中文每語 300 字、en 800 字（HD6；HD5 四語都 400，第一次實跑的 en 有一半卡在這裡）。"""
    assert config.MAX_COMMENT_CHARS == {"zh-TW": 300, "zh-HK": 300, "zh-CN": 300, "en": 800}
    ok = {**COMMENT, "zh-TW": "長" * 300, "en": "x" * 800}
    assert parse.parse_response(_resp(comment=ok))["level"] == "high"
    with pytest.raises(AiError) as e:
        parse.parse_response(_resp(comment={**COMMENT, "en": "x" * 801}))
    assert e.value.tag == "en_too_long"


# ---- 用字檢查（HD6） ----


def _wording(**langs: str) -> AiError:
    with pytest.raises(AiError) as e:
        parse.parse_response(_resp(comment={**COMMENT, **langs}))
    assert e.value.code == "bad_wording"
    return e.value


ZH = "10/23 14–20 時歐洲模式陣風 75 節，停飛風險高。"


@pytest.mark.parametrize(
    ("langs", "message"),
    [
        # 內部代號（大小寫不分、整字比對；中文字旁邊也抓得到）
        ({"zh-TW": "10/23 EC陣風 75 節，停飛風險高。"}, "zh-TW：內部代號 EC"),
        ({"zh-HK": "p49kt 56%，停飛風險高。"}, "zh-HK：內部代號 p49Kt"),
        ({"zh-CN": "GFS 阵风 51 节，停飞风险高。"}, "zh-CN：內部代號 GFS"),
        ({"en": "HRES gusts 75 kt; disruption risk High."}, "en：內部代號 HRES"),
        # agreement、slots 在 en 是常用字、不擋（HD17），中文照擋
        ({"zh-TW": "模式 agreement，停飛風險高。"}, "zh-TW：內部代號 agreement"),
        ({"zh-CN": "9 个 slots 为高，停飞风险高。"}, "zh-CN：內部代號 slots"),
        ({"zh-TW": "crosswindKt 51，停飛風險高。"}, "zh-TW：內部代號 crosswindKt"),
        ({"zh-TW": "依 latest.json，停飛風險高。"}, "zh-TW：內部代號 latest.json"),
        # TAF／METAR：括號裡一次可以，沒括號或第二次以上不行
        ({"zh-TW": "機場預報（TAF）陣風 46 節，TAF 之後轉弱。"}, "zh-TW：TAF 出現第 2 次"),
        ({"zh-HK": "TAF 陣風 46 節，停飛風險高。"}, "zh-HK：TAF 沒放在括號裡"),
        ({"en": "METAR shows 11 kt; disruption risk Low."}, "en：METAR 沒放在括號裡"),
        # 英文等級字
        ({"zh-TW": "停飛風險為高（high）。"}, "zh-TW：英文等級字 （high）"),
        ({"zh-CN": "停飞风险为中(medium)。"}, "zh-CN：英文等級字 (medium)"),
        # 粵語口語
        ({"zh-HK": "風險集中喺 10/21，停飛風險中。"}, "zh-HK：粵語口語「喺」"),
        ({"zh-HK": "陣風啱啱達到門檻，停飛風險中。"}, "zh-HK：粵語口語「啱啱」"),
        # 簡繁混用
        ({"zh-CN": "10/23 阵風 75 节，停飞风险高。"}, "zh-CN：繁體字「風」"),
        ({"zh-TW": "10/23 陣风 75 節，停飛風險高。"}, "zh-TW：簡體字「风」"),
        ({"zh-HK": "機场預報陣風 46 節，停飛風險高。"}, "zh-HK：簡體字「场」"),
        # 叫法不一致
        (
            {"zh-CN": "10/23 阵风 75 节，航班取消风险高。"},
            "zh-CN：叫法不一致「航班取消」（要用停飛風險）",
        ),
        (
            {"en": "Flight cancellation risk is High."},
            "en：叫法不一致「cancellation risk」（要用 disruption risk）",
        ),
        # en 含中日文字
        ({"en": "10/23 14–20 時: gusts 75 kt; disruption risk High."}, "en 含中日文字「時」"),
        ({"en": "Gusts 75 kt，disruption risk High."}, "en 含中日文字「，」"),
        ({"en": "Gusts 75 kt (ＴＡＦ); disruption risk High."}, "en 含中日文字「Ｔ」"),  # 全形字母
        # zh-CN 的台灣用語（HD7）
        ({"zh-CN": "阵风超过 49 节的机率 56%，停飞风险高。"}, "zh-CN 用了台灣用語：机率"),
        ({"zh-CN": "依目前资料，停飞风险高。"}, "zh-CN 用了台灣用語：资料"),
    ],
)
def test_parse_bad_wording(langs, message):
    e = _wording(**langs)
    assert str(e) == f"bad_wording: {message}"
    lang = message.split("：")[0].split(" ")[0]
    assert e.tag.startswith(f"{lang}/")


@pytest.mark.parametrize(
    "langs",
    [
        {"zh-TW": "機場預報（TAF）陣風 46 節，停飛風險高。"},
        {"zh-HK": "機場預報 (TAF) 陣風 46 節，機場觀測（METAR）風 11 節，停飛風險高。"},
        {"en": "The airport forecast (TAF) shows 46-kt gusts; disruption risk High."},
        {"en": "TAFF and ECMWF are not field names; disruption risk Low."},  # 整字比對
        {"zh-TW": "同時段歐洲模式與美國模式一致，停飛風險中。"},  # 「同」不算粵語
        {"en": "Gusts 46 kt on 10/19 12:00–13:00, 12–13 h local; disruption risk High."},
        # 「機率」「資料」只限制 zh-CN，zh-TW、zh-HK 照樣寫
        {"zh-TW": "依目前資料，陣風超過 49 節的機率 56%，停飛風險高。"},
        {"zh-HK": "依目前資料，陣風超過 49 節的機率 56%，停飛風險高。"},
        {"zh-CN": "依目前数据，阵风超过 49 节的概率 56%，停飞风险高。"},
    ],
)
def test_parse_wording_ok(langs):
    assert parse.parse_response(_resp(comment={**COMMENT, **langs}))["level"] == "high"


# 第一次實跑（2026-10-19T03:57Z，`data` 分支 `history/20261019T0357Z.json`）抓到的短評，原文照抄
REAL_MZG_CLAUDE = {
    "zh-TW": "近兩天風弱，TAF 平均風 4–6 節。轉折在 10/21 08–14 時，p29Kt 100%、p49Kt 31%。10/22 起 EC 與 GFS 一致，p49Kt 100%，10/22 08–14 時陣風達 57.1／48 節。10/23 14–20 時 EC 陣風 73.6 節、EC 側風 47.9 節。後段全靠模式，尚無官方 TAF 或警報。",  # noqa: E501
    "zh-HK": "近兩日風弱，TAF 平均風 4–6 節。轉捩點在 10/21 08–14 時，p29Kt 100%、p49Kt 31%。10/22 起 EC 與 GFS 一致，p49Kt 100%，10/22 08–14 時陣風達 57.1／48 節。10/23 14–20 時 EC 陣風 73.6 節、EC 側風 47.9 節。後段全靠模式，暫未有官方 TAF 或警告。",  # noqa: E501
    "zh-CN": "近两天风弱，TAF 平均风 4–6 节。转折在 10/21 08–14 时，p29Kt 100%、p49Kt 31%。10/22 起 EC 与 GFS 一致，p49Kt 100%，10/22 08–14 时阵风达 57.1／48 节。10/23 14–20 时 EC 阵风 73.6 节、EC 侧风 47.9 节。后段全靠模式，尚无官方 TAF 或预警。",  # noqa: E501
    "en": "Winds are light for the next two days, with TAF mean wind 4–6 kt. The turning point is 10/21 08–14, with p29Kt 100% and p49Kt 31%. From 10/22, EC and GFS agree, p49Kt is 100%, and gusts reach 57.1/48 kt on 10/22 08–14. On 10/23 14–20, EC gusts are 73.6 kt and EC crosswind is 47.9 kt. The later period relies entirely on models, with no official TAF or warning yet.",  # noqa: E501
}
REAL_NRT_CLAUDE = {
    "zh-TW": "風險集中在10/21 09–21時：EC與GFS陣風34.2–36.9節，未達37節中級門檻；含陣風側風EC約30節、GFS 33節，高等級只靠GFS剛觸及33節門檻撐起。p29Kt達100%，但p49Kt為0%。TAF時段最高陣風僅25節，整體評為中。",  # noqa: E501
    "zh-HK": "風險集中喺10/21 09–21時：EC同GFS陣風34.2–36.9節，未達37節中級門檻；含陣風側風EC約30節、GFS 33節，高等級只靠GFS啱啱觸及33節門檻撐起。p29Kt達100%，但p49Kt為0%。TAF時段最高陣風只有25節，整體評為中。",  # noqa: E501
    "zh-CN": "风险集中在10/21 09–21时：EC与GFS阵风34.2–36.9节，未达37节中级门槛；含阵风侧风EC约30节、GFS 33节，高等级只靠GFS刚触及33节门槛支撑。p29Kt达100%，但p49Kt为0%。TAF时段最高阵风仅25节，整体评为中。",  # noqa: E501
    "en": "Risk is concentrated on 10/21 09–21: EC and GFS gusts of 34.2–36.9 kt, below the 37 kt medium threshold; gust-inclusive crosswind is about 30 kt on EC and 33 kt on GFS, so the high rating rests only on GFS just touching the 33 kt threshold. p29Kt reaches 100%, but p49Kt is 0%. The highest TAF gust is only 25 kt. Overall rated medium.",  # noqa: E501
}
REAL_TNN_GEMINI = {
    "zh-TW": "10/19 08 時至 10/23 02 時停飛風險為低。10/23 02–08 時升為中等，EC 陣風 47.5 節。10/23 08 時至 10/24 08 時轉為高風險，期間 p49Kt 達 51%–59%，尤其 10/23 14 時至 10/24 02 時 EC 與 GFS 一致，EC 陣風最高 63.4 節、側風 48.4 節，GFS 陣風亦達 51.1 節。",  # noqa: E501
    "zh-HK": "10/19 08 時至 10/23 02 時停飛風險為低。10/23 02–08 時升為中等，EC 陣風 47.5 節。10/23 08 時至 10/24 08 時轉為高風險，期間 p49Kt 達 51%–59%，尤其 10/23 14 時至 10/24 02 時 EC 與 GFS 一致，EC 陣風最高 63.4 節、側風 48.4 節，GFS 陣風亦達 51.1 節。",  # noqa: E501
    "zh-CN": "10/19 08 时至 10/23 02 时航班取消风险为低。10/23 02–08 时升为中等，EC 阵风 47.5 节。10/23 08 时至 10/24 08 时转为高风险，期间 p49Kt 达 51%–59%，尤其 10/23 14 时至 10/24 02 时 EC 与 GFS 一致，EC 阵风最高 63.4 节、侧风 48.4 节，GFS 阵风亦达 51.1 节。",  # noqa: E501
    "en": "Flight cancellation risk is low from 10/19 08:00 to 10/23 02:00. It rises to medium during 10/23 02:00–08:00 with EC gusts at 47.5 kt. From 10/23 08:00 to 10/24 08:00, the risk turns high with p49Kt reaching 51%–59%. Specifically from 10/23 14:00 to 10/24 02:00, EC and GFS agree, showing EC gusts up to 63.4 kt, crosswind at 48.4 kt, and GFS gusts reaching 51.1 kt.",  # noqa: E501
}
REAL_MMY_GEMINI = {
    "zh-TW": "宮古機場未來 5 天停飛風險為高（high）。10/21 15–21 時起轉為中風險（EC 陣風 38.9 節、GFS 41.2 節）。10/22 03–09 時至 10/24 03–09 時連續 9 格高風險，p49Kt 達 21%–56%。峰值在 10/23 09–15 時，EC 陣風 76.7 節、側風 76.6 節，GFS 陣風 48.8 節、側風 46.9 節，模式一致。",  # noqa: E501
    "zh-HK": "宮古機場未來 5 天停飛風險為高（high）。10/21 15–21 時起轉為中風險（EC 陣風 38.9 節、GFS 41.2 節）。10/22 03–09 時至 10/24 03–09 時連續 9 格高風險，p49Kt 達 21%–56%。峰值在 10/23 09–15 時，EC 陣風 76.7 節、側風 76.6 節，GFS 陣風 48.8 節、側風 46.9 節，模式一致。",  # noqa: E501
    "zh-CN": "宫古机场未来 5 天停飞风险为高（high）。10/21 15–21 时起转为中风险（EC 阵风 38.9 节、GFS 41.2 节）。10/22 03–09 时至 10/24 03–09 时连续 9 格高风险，p49Kt 达 21%–56%。峰值在 10/23 09–15 时，EC 阵风 76.7 节、侧风 76.6 节，GFS 阵风 48.8 节、侧风 46.9 节，模式一致。",  # noqa: E501
    "en": "Miyako Airport faces a high flight suspension risk over the next 5 days. Risk turns medium from 10/21 15–21h (EC gusts 38.9 kt, GFS 41.2 kt). High risk spans 9 consecutive slots from 10/22 03–09h to 10/24 03–09h, with p49Kt reaching 21%–56%. The peak occurs at 10/23 09–15h with EC gusts of 76.7 kt, crosswind 76.6 kt, and GFS gusts of 48.8 kt, crosswind 46.9 kt, showing model agreement.",  # noqa: E501
}
REAL_GUM_CLAUDE_EN = "Slot 1 shows a high light from a TAF TEMPO period (10/19 12–13 時) with 46-knot gusts, but that period has already passed; the 10/19 13:54 observation shows only 11 knots, gusting 19 knots. After that, the main TAF gives 16 knots mean wind, gusting 27 knots, with a 24.5-knot crosswind below the medium threshold; the highest model gust is EC's 30.5 knots, and p49Kt stays at 0% throughout. Rated low."  # noqa: E501

# 把內部代號換成白話，用來看「代號以外」還抓得到什麼
_PLAIN = {
    "zh-TW": [("p29Kt", "陣風超過 29 節的機率"), ("p49Kt", "陣風超過 49 節的機率"),
              ("EC", "歐洲模式"), ("GFS", "美國模式"), ("TAF", "機場預報")],
    "zh-CN": [("p29Kt", "阵风超过 29 节的概率"), ("p49Kt", "阵风超过 49 节的概率"),
              ("EC", "欧洲模式"), ("GFS", "美国模式"), ("TAF", "机场预报")],
    "en": [("p29Kt", "the chance of gusts over 29 kt"), ("p49Kt", "the chance of gusts over 49 kt"),
           ("EC's", "the European model's"), ("EC", "the European model"), ("GFS", "the US model"),
           ("TAF", "airport forecast"), ("slots", "periods"), ("Slot", "Period"),
           ("agreement", "consensus")],
}  # fmt: skip
_PLAIN["zh-HK"] = _PLAIN["zh-TW"]


def plain(comment: dict[str, str]) -> dict[str, str]:
    out = {}
    for lang, text in comment.items():
        for a, b in _PLAIN[lang]:
            text = text.replace(a, b)
        out[lang] = text
    return out


@pytest.mark.parametrize(
    ("comment", "raw_message", "plain_message"),
    [
        # MZG（Claude）：滿是 p29Kt、p49Kt、EC、GFS、TAF；換成白話後就合格
        (REAL_MZG_CLAUDE, "zh-TW：內部代號 p29Kt", None),
        # NRT（Claude）：zh-HK 用了「喺、同、啱啱」
        (REAL_NRT_CLAUDE, "zh-TW：內部代號 p29Kt", "zh-HK：粵語口語「喺」"),
        # TNN（Gemini）：zh-CN「航班取消风险」、zh-TW 卻是「停飛風險」
        (REAL_TNN_GEMINI, "zh-CN：叫法不一致「航班取消」（要用停飛風險）", None),
        # MMY（Gemini）：「高（high）」
        (REAL_MMY_GEMINI, "zh-TW：內部代號 p49Kt", "zh-TW：英文等級字 （high）"),
        # GUM（Claude）的 en：「10/19 12–13 時」
        ({**COMMENT, "en": REAL_GUM_CLAUDE_EN}, "en：內部代號 p49Kt", "en 含中日文字「時」"),
    ],
)
def test_parse_real_run_comments(comment, raw_message, plain_message):
    with pytest.raises(AiError) as e:
        parse.parse_response(_resp(comment=comment))
    assert e.value.code == "bad_wording"
    assert str(e.value) == f"bad_wording: {raw_message}"
    cleaned = plain(comment)
    if plain_message is None:
        if comment is REAL_TNN_GEMINI:  # 叫法不一致不是代號，換白話也還在
            with pytest.raises(AiError) as e:
                parse.parse_response(_resp(comment=cleaned))
            assert str(e.value) == f"bad_wording: {raw_message}"
        else:
            assert parse.parse_response(_resp(comment=cleaned))["level"] == "high"
    else:
        with pytest.raises(AiError) as e:
            parse.parse_response(_resp(comment=cleaned))
        assert str(e.value) == f"bad_wording: {plain_message}"


# HD7：GUM（Claude）的 en 把「時」改成 12:00–13:00、代號換白話後就合格
def test_parse_real_gum_en_fixed():
    fixed = plain({"en": REAL_GUM_CLAUDE_EN})["en"].replace("12–13 時", "12:00–13:00")
    assert parse.parse_response(_resp(comment={**COMMENT, "en": fixed}))["level"] == "high"


# HD6 後第二次實跑（2026-10-19T04:39Z，`data` 分支 `history/20261019T0439Z.json`）PGUM 的 Gemini
# zh-CN 短評，原文照抄：「资料」「机率」是台灣用語
REAL_GUM_GEMINI_ZH_CN = "整体停飞风险评为低。10/19 10–16 时虽因机场预报（TAF）在当地 12–13 时短暂阵风与侧风达 46 节而列高风险，但目前资料时间为 14:39，该短暂强风时段已过，且 13:54 机场观测（METAR）阵风仅 19 节。10/19 16 时至 10/24 10 时机场预报及欧洲模式、美国模式阵风皆在 27 节以下，阵风超过 49 节的机率均为 0%，全为低风险。"  # noqa: E501


def test_parse_real_zh_cn_taiwan_terms():
    e = _wording(**{"zh-CN": REAL_GUM_GEMINI_ZH_CN})
    assert str(e) == "bad_wording: zh-CN 用了台灣用語：机率"
    assert e.tag == "zh-CN/机率"
    only_data = REAL_GUM_GEMINI_ZH_CN.replace("机率", "概率")
    assert str(_wording(**{"zh-CN": only_data})) == "bad_wording: zh-CN 用了台灣用語：资料"
    fixed = only_data.replace("资料", "数据")
    assert parse.parse_response(_resp(comment={**COMMENT, "zh-CN": fixed}))["level"] == "high"


def test_ai_error_trace():
    e = AiError("bad_format", "en 超過 800 字", tag="en_too_long")
    assert e.trace() == "bad_format:-:-:en_too_long"
    parse.with_response(e, "end_turn", 812)
    assert e.trace() == "bad_format:end_turn:812:en_too_long"
    e = AiError("bad_format", "超過 max_tokens 被截斷")
    parse.with_response(e, "max_tokens", 3000)
    assert e.trace() == "bad_format:max_tokens:3000"


# ---- Claude ----


class FakeAnthropic:
    def __init__(self, result=None, exc=None):
        self.result, self.exc, self.calls, self.options = result, exc, [], []
        self.messages = SimpleNamespace(create=self._create)

    def with_options(self, **kw):
        self.options.append(kw)
        return self

    def _create(self, **kw):
        self.calls.append(kw)
        if self.exc:
            raise self.exc
        return self.result


def _msg(text: str, stop: str = "end_turn", output_tokens: int = 812):
    blocks = [
        SimpleNamespace(type="thinking", thinking=""),
        SimpleNamespace(type="text", text=text),
    ]
    usage = SimpleNamespace(input_tokens=4000, output_tokens=output_tokens)
    return SimpleNamespace(stop_reason=stop, content=blocks, usage=usage)


def test_claude_request_and_parse():
    fake = FakeAnthropic(_msg(_resp()))
    assert claude.evaluate("文字", client=fake, timeout=42)["comment"] == COMMENT
    kw = fake.calls[0]
    assert kw["model"] == "claude-opus-5-5" and kw["max_tokens"] == config.MAX_TOKENS == 3000
    assert kw["system"] == prompt.SYSTEM
    assert kw["messages"] == [{"role": "user", "content": "文字"}]
    assert "temperature" not in kw  # Opus 5.5 不接受取樣參數
    assert kw["output_config"] == {"effort": "low"}
    assert fake.options == [{"timeout": 42, "max_retries": 0}]


_REQ = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


@pytest.mark.parametrize(
    ("exc", "code"),
    [
        (anthropic.APITimeoutError(request=_REQ), "timeout"),
        (anthropic.APIConnectionError(request=_REQ), "network"),
        (
            anthropic.APIStatusError(
                "overloaded", response=httpx2.Response(529, request=_REQ), body=None
            ),
            "http_529",
        ),
        (
            anthropic.RateLimitError(
                "rate", response=httpx2.Response(429, request=_REQ), body=None
            ),
            "http_429",
        ),
    ],
)
def test_claude_errors(exc, code):
    fake = FakeAnthropic(exc=exc)
    with pytest.raises(AiError) as e:
        claude.evaluate("文字", client=fake)
    assert e.value.code == code
    assert len(fake.calls) == 1  # 不重試


@pytest.mark.parametrize(
    ("stop", "code", "trace"),
    [
        ("refusal", "refusal", "refusal:refusal:3000"),
        ("max_tokens", "bad_format", "bad_format:max_tokens:3000"),
    ],
)
def test_claude_stop_reasons(stop, code, trace):
    with pytest.raises(AiError) as e:
        claude.evaluate("文字", client=FakeAnthropic(_msg(_resp(), stop, 3000)))
    assert e.value.code == code
    assert e.value.trace() == trace


def test_claude_trace_on_parse_errors():
    with pytest.raises(AiError) as e:
        claude.evaluate("文字", client=FakeAnthropic(_msg("不是 JSON", output_tokens=640)))
    assert e.value.trace() == "bad_format:end_turn:640:not_json"
    bad = _resp(comment={**COMMENT, "zh-HK": "風險集中喺 10/21，停飛風險高。"})
    with pytest.raises(AiError) as e:
        claude.evaluate("文字", client=FakeAnthropic(_msg(bad)))
    assert e.value.code == "bad_wording"
    assert e.value.trace() == "bad_wording:end_turn:812:zh-HK/喺"


def test_claude_no_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(AiError) as e:
        claude.make_client()
    assert e.value.code == "no_api_key"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-not-a-real-key")
    c = claude.make_client()
    assert c.max_retries == 0


# ---- Gemini ----


class FakeGenai:
    def __init__(self, result=None, exc=None):
        self.result, self.exc, self.calls = result, exc, []
        self.models = SimpleNamespace(generate_content=self._gen)

    def _gen(self, **kw):
        self.calls.append(kw)
        if self.exc:
            raise self.exc
        return self.result


def _gresp(text: str, reason=genai_types.FinishReason.STOP, out: int = 700, thoughts: int = 900):
    return genai_types.GenerateContentResponse(
        usage_metadata=genai_types.GenerateContentResponseUsageMetadata(
            prompt_token_count=4000, candidates_token_count=out, thoughts_token_count=thoughts
        ),
        candidates=[
            genai_types.Candidate(
                content=genai_types.Content(
                    role="model",
                    parts=[
                        genai_types.Part(text="想一下", thought=True),
                        genai_types.Part(text=text),
                    ],
                ),
                finish_reason=reason,
            )
        ],
    )


def test_gemini_request_and_parse():
    fake = FakeGenai(_gresp(_resp()))
    assert gemini.evaluate("文字", client=fake, timeout=30)["level"] == "high"
    kw = fake.calls[0]
    assert kw["model"] == "gemini-4-argon" and kw["contents"] == "文字"
    cfg = kw["config"]
    assert cfg.system_instruction == prompt.SYSTEM
    assert (cfg.temperature, cfg.max_output_tokens) == (0.3, 3000)
    assert cfg.response_mime_type == "application/json"
    assert cfg.http_options.timeout == 30_000
    # Gemini 4 只接受 thinking_level（送 thinking_budget 回 400），LOW 是最低
    assert cfg.thinking_config.thinking_level == genai_types.ThinkingLevel.LOW
    assert cfg.thinking_config.thinking_budget is None
    assert cfg.thinking_config.include_thoughts is False


@pytest.mark.parametrize(
    ("exc", "code"),
    [
        (genai_errors.APIError(429, {"error": {"code": 429, "message": "quota"}}), "http_429"),
        (genai_errors.ServerError(503, {"error": {"code": 503, "message": "x"}}), "http_503"),
        (gemini.httpx.ReadTimeout("slow"), "timeout"),
        (gemini.requests.ConnectionError("down"), "network"),
        (gemini.auth_exceptions.RefreshError("invalid_grant"), "http_401"),
    ],
)
def test_gemini_errors(exc, code):
    fake = FakeGenai(exc=exc)
    with pytest.raises(AiError) as e:
        gemini.evaluate("文字", client=fake)
    assert e.value.code == code
    assert len(fake.calls) == 1


@pytest.mark.parametrize(
    ("reason", "code", "trace"),
    [
        (genai_types.FinishReason.MAX_TOKENS, "bad_format", "bad_format:MAX_TOKENS:700+900"),
        (genai_types.FinishReason.SAFETY, "refusal", "refusal:SAFETY:700+900"),
    ],
)
def test_gemini_finish_reasons(reason, code, trace):
    with pytest.raises(AiError) as e:
        gemini.evaluate("文字", client=FakeGenai(_gresp(_resp(), reason)))
    assert e.value.code == code
    assert e.value.trace() == trace


def test_gemini_bad_json_response():
    with pytest.raises(AiError) as e:
        gemini.evaluate("文字", client=FakeGenai(_gresp("not json", thoughts=0)))
    assert e.value.code == "bad_format"
    assert e.value.trace() == "bad_format:STOP:700:not_json"


def test_gemini_json_with_preamble_and_bad_wording():
    assert gemini.evaluate("文字", client=FakeGenai(_gresp("好的：" + _resp())))["level"] == "high"
    bad = _resp(comment={**COMMENT, "zh-TW": "停飛風險為高（high）。"})
    with pytest.raises(AiError) as e:
        gemini.evaluate("文字", client=FakeGenai(_gresp(bad)))
    assert e.value.trace() == "bad_wording:STOP:700+900:zh-TW/（high）"


@pytest.mark.parametrize("missing", config.ENV["gemini"])
def test_gemini_no_api_key(monkeypatch, missing):
    for k in config.ENV["gemini"]:
        monkeypatch.setenv(k, "x")
    monkeypatch.delenv(missing)
    with pytest.raises(AiError) as e:
        gemini.make_client()
    assert e.value.code == "no_api_key"


def test_gemini_bad_service_account_json(monkeypatch):
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_JSON", "{不是 JSON")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "p")
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "global")
    with pytest.raises(AiError) as e:
        gemini.make_client()
    assert e.value.code == "no_api_key" and "不是 JSON" not in str(e.value)
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_JSON", '{"type": "service_account"}')
    with pytest.raises(AiError):
        gemini.make_client()


# ---- 流程 ----


def fake_model(
    level="high",
    delay=0.0,
    exc: str | None = None,
    client_error: str | None = None,
    response: tuple[str, int] | None = None,
):
    calls: list[str] = []
    lock = threading.Lock()

    def make_client():
        if client_error:
            raise AiError(client_error)
        return object()

    def evaluate(text, *, client=None, timeout=60):
        with lock:
            calls.append(text.splitlines()[0])
        if delay:
            time.sleep(delay)
        if exc:
            e = AiError(exc, tag="not_json" if exc == "bad_format" else "")
            if response:  # 有拿到回應（stop_reason、輸出 token 數）
                parse.with_response(e, *response)
            raise e
        return {"level": level, "comment": dict(COMMENT)}

    return SimpleNamespace(make_client=make_client, evaluate=evaluate, calls=calls)


def duel_doc(n_risky=2, n_quiet=2) -> dict:
    aps = [airport(f"RC{i:02d}", lv(i, "high")) for i in range(n_risky)]
    aps += [airport(f"ZZ{i:02d}") for i in range(n_quiet)]
    return doc(*aps)


def test_duel_output_structure(tmp_path):
    cl, ge = fake_model("high"), fake_model(exc="bad_format")
    res = ai_run.evaluate_all(
        duel_doc(), None, NOW, tmp_path, evaluators={"claude": cl, "gemini": ge}
    )
    assert res["ai"] == {
        "disclaimer": config.DISCLAIMER,
        "models": {"claude": "claude-opus-5-5", "gemini": "gemini-4-argon"},
    }
    assert set(res["ai"]["disclaimer"]) == set(LANGS)
    risky = res["airports"]["RC00"]
    assert risky == {
        "evaluatedAt": RUN,
        "claude": {
            "status": "ok",
            "level": "high",
            "comment": COMMENT,
            "model": "claude-opus-5-5",
        },
        "gemini": {
            "status": "error",
            "level": None,
            "comment": None,
            "model": "gemini-4-argon",
            "error": "bad_format",
        },
    }
    quiet = res["airports"]["ZZ00"]
    assert quiet["evaluatedAt"] == RUN
    for k in ("claude", "gemini"):
        assert quiet[k] == {
            "status": "skipped",
            "level": "low",
            "comment": config.NO_RISK,
            "model": config.MODELS[k],
        }
    assert config.NO_RISK == {
        "zh-TW": "沒看到明顯風險",
        "zh-HK": "未見明顯風險",
        "zh-CN": "未见明显风险",
        "en": "No notable risk seen",
    }
    assert res["source"] == {
        "ok": True,
        "calls": {"claude": 2, "gemini": 2},
        "errors": {"gemini": "bad_format"},
    }
    assert len(cl.calls) == len(ge.calls) == 2  # 只評被選的


def test_duel_no_api_key_other_model_runs(tmp_path):
    cl, ge = fake_model(client_error="no_api_key"), fake_model("medium")
    res = ai_run.evaluate_all(
        duel_doc(), None, NOW, tmp_path, evaluators={"claude": cl, "gemini": ge}
    )
    a = res["airports"]["RC01"]
    assert a["claude"]["error"] == "no_api_key" and a["claude"]["level"] is None
    assert a["gemini"]["status"] == "ok" and a["gemini"]["level"] == "medium"
    assert a["evaluatedAt"] == RUN
    assert res["source"]["errors"] == {"claude": "no_api_key"}
    assert res["source"]["calls"] == {"claude": 0, "gemini": 2}
    assert res["source"]["ok"] is True


def test_duel_both_errors_evaluated_at_null(tmp_path):
    bad = fake_model(client_error="no_api_key")
    res = ai_run.evaluate_all(
        duel_doc(), None, NOW, tmp_path, evaluators={"claude": bad, "gemini": bad}
    )
    assert res["airports"]["RC00"]["evaluatedAt"] is None
    assert res["airports"]["ZZ00"]["evaluatedAt"] == RUN  # skipped 也填
    src = res["source"]
    assert src["ok"] is False
    assert src["errors"] == {"claude": "no_api_key", "gemini": "no_api_key"}
    assert src["error"] == "claude:no_api_key,gemini:no_api_key"


def test_duel_nothing_selected_still_reports_missing_keys(tmp_path):
    bad, good = fake_model(client_error="no_api_key"), fake_model()
    res = ai_run.evaluate_all(
        duel_doc(0, 3), None, NOW, tmp_path, evaluators={"claude": good, "gemini": good}
    )
    assert res["source"] == {"ok": True, "calls": {"claude": 0, "gemini": 0}}
    res = ai_run.evaluate_all(
        duel_doc(0, 3), None, NOW, tmp_path, evaluators={"claude": bad, "gemini": good}
    )
    assert res["source"]["ok"] is False and res["source"]["errors"] == {"claude": "no_api_key"}


def test_duel_no_daily_cap_by_default(tmp_path):
    """開發期間 `DAILY_CAP=0` 不限（HD11）：超過 80 次照常呼叫，次數檔照常累加。"""
    assert config.DAILY_CAP == 0 and ai_run.DAILY_CAP == 0
    path = tmp_path / "ai" / "calls-2026-10-19.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"claude": 79, "gemini": 80}), "utf-8")
    cl, ge = fake_model(), fake_model()
    res = ai_run.evaluate_all(
        duel_doc(3, 0), None, NOW, tmp_path, evaluators={"claude": cl, "gemini": ge}
    )
    for i in range(3):
        a = res["airports"][f"RC{i:02d}"]
        assert a["claude"]["status"] == "ok" and a["gemini"]["status"] == "ok"
    assert len(cl.calls) == 3 and len(ge.calls) == 3
    assert json.loads(path.read_text("utf-8")) == {"claude": 82, "gemini": 83}
    assert res["source"]["calls"] == {"claude": 3, "gemini": 3}
    assert "errors" not in res["source"]


def test_duel_daily_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(ai_run, "DAILY_CAP", 2)
    path = tmp_path / "ai" / "calls-2026-10-19.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"claude": 0, "gemini": 2}), "utf-8")
    cl, ge = fake_model(), fake_model()
    res = ai_run.evaluate_all(
        duel_doc(4, 0), None, NOW, tmp_path, evaluators={"claude": cl, "gemini": ge}
    )
    statuses = [res["airports"][f"RC{i:02d}"]["claude"] for i in range(4)]
    assert sum(s["status"] == "ok" for s in statuses) == 2
    assert sum(s.get("error") == "daily_cap" for s in statuses) == 2
    assert all(res["airports"][f"RC{i:02d}"]["gemini"]["error"] == "daily_cap" for i in range(4))
    assert len(cl.calls) == 2 and ge.calls == []
    assert json.loads(path.read_text("utf-8")) == {"claude": 2, "gemini": 2}
    assert res["source"]["calls"] == {"claude": 2, "gemini": 0}
    # 換日（UTC）重新算
    res = ai_run.evaluate_all(
        duel_doc(1, 0),
        None,
        NOW + timedelta(days=1),
        tmp_path,
        evaluators={"claude": cl, "gemini": ge},
    )
    assert res["airports"]["RC00"]["gemini"]["status"] == "ok"
    assert json.loads((tmp_path / "ai" / "calls-2026-10-20.json").read_text("utf-8")) == {
        "claude": 1,
        "gemini": 1,
    }


def test_duel_failed_calls_count(tmp_path):
    ev = {"claude": fake_model(exc="http_500"), "gemini": fake_model(exc="timeout")}
    ai_run.evaluate_all(duel_doc(3, 0), None, NOW, tmp_path, evaluators=ev)
    calls = json.loads((tmp_path / "ai" / "calls-2026-10-19.json").read_text("utf-8"))
    assert calls == {"claude": 3, "gemini": 3}


def test_duel_run_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(ai_run, "MAX_AIRPORTS", 2)
    m = fake_model()
    res = ai_run.evaluate_all(
        duel_doc(3, 1), None, NOW, tmp_path, evaluators={"claude": m, "gemini": m}
    )
    # RC02 的高級格最晚 → 排第三，超過上限
    assert res["airports"]["RC02"]["claude"]["error"] == "run_cap"
    assert res["airports"]["RC02"]["evaluatedAt"] is None
    assert res["airports"]["ZZ00"]["claude"]["status"] == "skipped"
    assert res["source"]["ok"] is True and "errors" not in res["source"]


def concurrent_model(delay: float):
    """記下同時在跑的最大呼叫數。"""
    state = {"now": 0, "max": 0}
    lock = threading.Lock()

    def evaluate(text, *, client=None, timeout=60):
        with lock:
            state["now"] += 1
            state["max"] = max(state["max"], state["now"])
        time.sleep(delay)
        with lock:
            state["now"] -= 1
        return {"level": "high", "comment": dict(COMMENT)}

    return SimpleNamespace(make_client=object, evaluate=evaluate, state=state)


def test_duel_models_run_in_parallel(tmp_path):
    """每個模型 4 個機場、每次 0.4 秒；Claude 4 條並行約 0.4 秒、Gemini 3 條並行約 0.8 秒
    （HD6：Gemini 4 條時撞過 429、降到 2；HD12 升回 3）。兩個模型同時跑，總時間約 0.8 秒
    （不是 1.2 秒；模型內也不平行的話是 3.2 秒）。"""
    assert config.PARALLEL == {"claude": 4, "gemini": 3}
    ev = {"claude": concurrent_model(0.4), "gemini": concurrent_model(0.4)}
    t0 = time.monotonic()
    res = ai_run.evaluate_all(duel_doc(4, 0), None, NOW, tmp_path, evaluators=ev)
    took = time.monotonic() - t0
    assert res["source"]["calls"] == {"claude": 4, "gemini": 4}
    assert ev["claude"].state["max"] == 4 and ev["gemini"].state["max"] == 3
    assert took < 1.1, took


def test_duel_timeout_marks_unfinished(tmp_path):
    ev = {"claude": fake_model(delay=0.05), "gemini": fake_model(delay=5)}
    duel = ai_run.Duel(duel_doc(2, 1), None, NOW, tmp_path, budget_s=30, evaluators=ev)
    t = threading.Thread(target=duel.run, daemon=True)
    t.start()
    t.join(0.5)  # build 那邊的預算到了
    res = duel.result(timed_out=True)
    assert res["airports"]["RC00"]["claude"]["status"] == "ok"
    assert res["airports"]["RC00"]["gemini"]["error"] == "timeout"
    assert res["airports"]["ZZ00"]["gemini"]["status"] == "skipped"
    assert res["source"]["errors"] == {"gemini": "timeout"}
    assert duel.result() is res  # 只算一次
    calls = json.loads((tmp_path / "ai" / "calls-2026-10-19.json").read_text("utf-8"))
    assert calls == {"claude": 2, "gemini": 2}  # 送出去的也算


def test_duel_request_timeout_capped_by_budget(tmp_path):
    seen = []

    def evaluate(text, *, client=None, timeout=60):
        seen.append(timeout)
        return {"level": "low", "comment": dict(COMMENT)}

    m = SimpleNamespace(make_client=object, evaluate=evaluate)
    ai_run.evaluate_all(
        duel_doc(1, 0), None, NOW, tmp_path, budget_s=10, evaluators={"claude": m, "gemini": m}
    )
    assert len(seen) == 2 and all(5 < t <= 10 for t in seen)


# ---- 對決戰績 ----


def test_duel_records_written_and_merged(tmp_path):
    ev = {
        "claude": fake_model("high"),
        "gemini": fake_model(exc="bad_format", response=("MAX_TOKENS", "2400+600")),
    }
    prev = duel_doc(2, 2)
    cur = duel_doc(2, 2)
    cur["airports"][3]["slots"][5]["level"] = "unknown"  # ZZ01 有變
    ai_run.evaluate_all(cur, prev, NOW, tmp_path, evaluators=ev)
    path = tmp_path / "ai" / "2026-10-19.json"
    rows = json.loads(path.read_text("utf-8"))
    assert [r["airport"] for r in rows] == ["RC00", "RC01", "ZZ00", "ZZ01"]
    r = rows[0]
    for k in ("claude", "gemini"):  # 秒數另外測（`test_duel_records_seconds`）
        assert isinstance(r[k].pop("seconds"), float)
    assert r == {
        "run": RUN,
        "airport": "RC00",
        "selected": "level",
        "rule": {"maxLevel": "high", "firstFrom": "2026-10-19T00:00:00Z"},
        "claude": {"status": "ok", "level": "high"},
        # 呼叫失敗的那顆有 detail（HD6）：<代碼>:<stop_reason>:<輸出 token 數>[:<標記>]，不記內容
        "gemini": {
            "status": "error",
            "level": None,
            "detail": "bad_format:MAX_TOKENS:2400+600:not_json",
        },
        "slots": [{"from": s["from"], "level": s["level"]} for s in cur["airports"][0]["slots"]],
    }
    assert len(r["slots"]) == 20 and set(r["slots"][0]) == {"from", "level"}
    assert rows[2]["selected"] is None and rows[2]["claude"] == {
        "status": "skipped",
        "level": "low",
    }
    assert rows[3]["selected"] == "changed"
    assert "detail" not in rows[0]["claude"] and "detail" not in rows[2]["gemini"]
    assert "comment" not in path.read_text("utf-8")  # 不存短評
    # 同一跑次再跑一次：覆蓋，不重複
    ai_run.evaluate_all(cur, prev, NOW, tmp_path, evaluators=ev)
    assert len(json.loads(path.read_text("utf-8"))) == 4
    # 下一跑次：append
    later = duel_doc(2, 2)
    later["generatedAt"] = "2026-10-19T08:25:00Z"
    ai_run.evaluate_all(later, cur, NOW, tmp_path, evaluators=ev)
    rows = json.loads(path.read_text("utf-8"))
    assert len(rows) == 8 and [r["run"] for r in rows[::4]] == [RUN, "2026-10-19T08:25:00Z"]


def test_merge_records_keeps_others():
    old = [{"run": "a", "airport": "X", "v": 1}, {"run": "a", "airport": "Y", "v": 1}, "壞的"]
    new = [{"run": "a", "airport": "Y", "v": 2}, {"run": "b", "airport": "X", "v": 3}]
    assert ai_run.merge_records(old, new) == [
        {"run": "a", "airport": "X", "v": 1},
        {"run": "a", "airport": "Y", "v": 2},
        {"run": "b", "airport": "X", "v": 3},
    ]


def test_no_keys_in_code():
    """程式與測試裡不能出現金鑰（粗略檢查常見的金鑰前綴與私鑰）。"""
    from conftest import ROOT

    for p in [*(ROOT / "src").rglob("*.py"), *(ROOT / "tests").rglob("*.py")]:
        text = p.read_text("utf-8")
        assert "sk-" + "ant-" not in text, p
        assert "BEGIN PRIVATE" + " KEY" not in text, p


def test_duel_detail_only_for_call_failures(tmp_path, monkeypatch):
    """`detail` 只在真的呼叫失敗時有（HTTP 錯誤沒有回應，stop_reason／token 寫 `-`）；
    `daily_cap`、`no_api_key`、`run_cap` 沒呼叫，沒有 `detail`；`latest.json` 那邊不加欄位。"""
    monkeypatch.setattr(ai_run, "DAILY_CAP", 80)
    path = tmp_path / "ai" / "calls-2026-10-19.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"claude": 0, "gemini": 80}), "utf-8")
    ev = {"claude": fake_model(exc="http_429"), "gemini": fake_model()}
    res = ai_run.evaluate_all(duel_doc(1, 0), None, NOW, tmp_path, evaluators=ev)
    row = json.loads((tmp_path / "ai" / "2026-10-19.json").read_text("utf-8"))[0]
    assert isinstance(row["claude"].pop("seconds"), float)
    assert row["claude"] == {"status": "error", "level": None, "detail": "http_429:-:-"}
    assert row["gemini"] == {"status": "error", "level": None}  # daily_cap
    assert "detail" not in res["airports"]["RC00"]["claude"]


def test_budget_and_parallel_hd12():
    """HD12：AI 預算 180 → 240 秒、Gemini 2 → 3 條並行（429 回來就降回 2）。"""
    assert build.BUDGET_S["ai"] == 240
    assert config.PARALLEL == {"claude": 4, "gemini": 3}


def test_duel_records_seconds(tmp_path, monkeypatch):
    """戰績每筆真的送出的呼叫（成功、失敗）多 `seconds`（float、一位小數，HD12）；`skipped`、
    `run_cap`、`daily_cap`、`no_api_key` 沒送，沒有；`latest.json` 不加。"""
    monkeypatch.setattr(ai_run, "MAX_AIRPORTS", 2)
    ev = {"claude": fake_model("high", delay=0.12), "gemini": fake_model(exc="http_504")}
    res = ai_run.evaluate_all(duel_doc(3, 1), None, NOW, tmp_path, evaluators=ev)
    rows = {
        r["airport"]: r
        for r in json.loads((tmp_path / "ai" / "2026-10-19.json").read_text("utf-8"))
    }
    for icao in ("RC00", "RC01"):
        cl, ge = rows[icao]["claude"], rows[icao]["gemini"]
        # 504 重試一次仍失敗（HD17）：detail 加 `:retried`，其他格式不動
        assert cl["status"] == "ok" and ge["detail"] == "http_504:-:-:retried"
        for light in (cl, ge):
            assert isinstance(light["seconds"], float) and light["seconds"] >= 0
            assert light["seconds"] == round(light["seconds"], 1)
        assert cl["seconds"] >= 0.1
        for k in ("claude", "gemini"):
            assert "seconds" not in res["airports"][icao][k]
    assert rows["RC02"]["claude"] == {"status": "error", "level": None}  # run_cap
    assert rows["ZZ00"]["gemini"] == {"status": "skipped", "level": "low"}
    # 沒送出去的：no_api_key、daily_cap
    monkeypatch.setattr(ai_run, "DAILY_CAP", 1)
    ev = {"claude": fake_model(client_error="no_api_key"), "gemini": fake_model()}
    later = duel_doc(2, 0)
    later["generatedAt"] = "2026-10-19T08:25:00Z"
    ai_run.evaluate_all(later, None, NOW, tmp_path, evaluators=ev)
    rows = [
        r
        for r in json.loads((tmp_path / "ai" / "2026-10-19.json").read_text("utf-8"))
        if r["run"] == "2026-10-19T08:25:00Z"
    ]
    assert [r["claude"] for r in rows] == [{"status": "error", "level": None}] * 2  # no_api_key
    assert [r["gemini"] for r in rows] == [{"status": "error", "level": None}] * 2  # daily_cap


# ---- 新天氣種類的用字（HD8）----


@pytest.mark.parametrize(
    ("langs", "message"),
    [
        ({"zh-TW": "rain6hMm 35，停飛風險中。"}, "zh-TW：內部代號 rain6hMm"),
        ({"zh-HK": "visibilityM 300，停飛風險高。"}, "zh-HK：內部代號 visibilityM"),
        ({"zh-CN": "ptype 是 snow，停飞风险高。"}, "zh-CN：內部代號 ptype"),
        ({"en": "ceilingFt 100; disruption risk High."}, "en：內部代號 ceilingFt"),
        ({"zh-TW": "causes 是霧，停飛風險高。"}, "zh-TW：內部代號 causes"),  # en 不擋（HD17）
        ({"zh-TW": "p24hRain50 40%，停飛風險中。"}, "zh-TW：內部代號 p24hRain50"),
        ({"zh-TW": "p24hRain25 40%，停飛風險中。"}, "zh-TW：內部代號 p24hRain25"),
        ({"en": "APCP 35 mm; disruption risk Medium."}, "en：內部代號 APCP"),
        ({"en": "CSNOW is on; disruption risk High."}, "en：內部代號 CSNOW"),
        ({"en": "CFRZR is on; disruption risk High."}, "en：內部代號 CFRZR"),
        # 簡繁
        ({"zh-CN": "10/23 浓霧，停飞风险高。"}, "zh-CN：繁體字「霧」"),
        ({"zh-CN": "10/23 能見度 300 米，停飞风险高。"}, "zh-CN：繁體字「見」"),
        ({"zh-TW": "10/23 濃雾，停飛風險高。"}, "zh-TW：簡體字「雾」"),
        ({"zh-HK": "10/23 能见度 300 公尺，停飛風險高。"}, "zh-HK：簡體字「见」"),
    ],
)
def test_bad_wording_hd8(langs, message):
    assert str(_wording(**langs)) == f"bad_wording: {message}"


def test_good_wording_hd8():
    comment = {
        "zh-TW": "主因是濃霧：10/23 08–14 時能見度 300 公尺、雲底 100 呎，停飛風險高。",
        "zh-HK": "主因是濃霧：10/23 08–14 時能見度 300 公尺、雲底 100 呎，停飛風險高。",
        "zh-CN": "主因是浓雾：10/23 08–14 时能见度 300 米、云底 100 英尺，停飞风险高。",
        "en": "Mainly dense fog: visibility 300 m and cloud base 100 ft on 10/23 08:00–14:00; "
        "disruption risk High.",
    }
    assert parse.parse_response(_resp(comment=comment))["comment"] == comment


# ---- HD17：英文常用字不當代號擋；503／504 重試一次 ----


@pytest.mark.parametrize(
    "en",
    [
        "Strong winds causes delays on 10/23 08:00–14:00; disruption risk High.",
        "On the basis of the airport forecast (TAF), disruption risk is Medium.",
        "The European and US models are in agreement; disruption risk High.",
        "The afternoon slots on 10/23 are high; disruption risk High.",
    ],
)
def test_en_plain_words_ok_hd17(en):
    assert config.EN_PLAIN_WORDS == ("causes", "basis", "agreement", "slots")
    assert set(config.EN_PLAIN_WORDS) <= set(config.FORBIDDEN_TOKENS)  # 中文三語照擋
    assert parse.parse_response(_resp(comment={**COMMENT, "en": en}))["comment"]["en"] == en


@pytest.mark.parametrize(
    ("langs", "message"),
    [
        ({"zh-TW": "主因 causes 是強風，停飛風險高。"}, "zh-TW：內部代號 causes"),
        ({"zh-HK": "依 basis 判斷，停飛風險高。"}, "zh-HK：內部代號 basis"),
        ({"en": "p49Kt is 56%; disruption risk High."}, "en：內部代號 p49Kt"),
        ({"en": "ptype is snow; disruption risk High."}, "en：內部代號 ptype"),
    ],
)
def test_other_tokens_still_blocked_hd17(langs, message):
    assert str(_wording(**langs)) == f"bad_wording: {message}"


@pytest.mark.parametrize(
    ("langs", "message"),
    [
        ({"zh-TW": "AIFS 估算陣風 43 節，停飛風險中。"}, "zh-TW：內部代號 AIFS"),
        ({"zh-HK": "AIGFS 估算陣風 43 節，停飛風險中。"}, "zh-HK：內部代號 AIGFS"),
        ({"en": "The AIFS estimated gust is 43 kt; disruption risk Medium."}, "en：內部代號 AIFS"),
        ({"en": "gustEstimated is true; disruption risk Medium."}, "en：內部代號 gustEstimated"),
    ],
)
def test_bad_wording_model_names_hd14(langs, message):
    assert str(_wording(**langs)) == f"bad_wording: {message}"


def test_good_wording_hd14():
    comment = {
        "zh-TW": "主因是強風：五個模式中三個認為高，歐洲 AI 模式估算陣風 43 節，停飛風險高。",
        "zh-HK": "主因是強風：五個模式中三個認為高，歐洲 AI 模式估算陣風 43 節，停飛風險高。",
        "zh-CN": "主因是强风：五个模式中三个认为高，欧洲 AI 模式估算阵风 43 节，停飞风险高。",
        "en": "Mainly strong wind: three of five models say High, and the European AI model's "
        "estimated gust is 43 kt; disruption risk High.",
    }
    assert parse.parse_response(_resp(comment=comment))["comment"] == comment


def seq_model(*outcomes: str | None, delay: float = 0.0):
    """依序回 `outcomes`（錯誤代碼，`None` 是成功）；用完了就重複最後一個。記下每次的逾時。"""
    timeouts: list[float] = []
    lock = threading.Lock()

    def evaluate(text, *, client=None, timeout=60):
        with lock:
            code = outcomes[min(len(timeouts), len(outcomes) - 1)]
            timeouts.append(timeout)
        if delay:
            time.sleep(delay)
        if code:
            raise AiError(code)
        return {"level": "high", "comment": dict(COMMENT)}

    return SimpleNamespace(make_client=object, evaluate=evaluate, timeouts=timeouts)


def _gemini_row(tmp_path, ge, **kwargs) -> dict:
    ev = {"claude": fake_model(), "gemini": ge}
    res = ai_run.evaluate_all(duel_doc(1, 0), None, NOW, tmp_path, evaluators=ev, **kwargs)
    """RC00 的 Gemini 戰績，加上 `latest.json` 那顆燈（`light`）與這一報的呼叫數（`calls`）。"""
    row = json.loads((tmp_path / "ai" / "2026-10-19.json").read_text("utf-8"))[0]["gemini"]
    return row | {
        "light": res["airports"]["RC00"]["gemini"],
        "calls": res["source"]["calls"]["gemini"],
    }


def test_retry_504_then_ok_hd17(tmp_path):
    assert config.RETRY_CODES == ("http_503", "http_504") and config.RETRY_MIN_LEFT_S == 70
    ge = seq_model("http_504", None, delay=0.1)
    g = _gemini_row(tmp_path, ge)
    assert len(ge.timeouts) == 2
    assert g["status"] == "ok" and g["light"]["status"] == "ok" and "detail" not in g
    assert g["seconds"] >= 0.2  # 兩次合計
    assert g["calls"] == 2  # 重試也算一次呼叫
    calls = json.loads((tmp_path / "ai" / "calls-2026-10-19.json").read_text("utf-8"))
    assert calls == {"claude": 1, "gemini": 2}


@pytest.mark.parametrize("code", ["http_503", "http_504"])
def test_retry_fails_twice_hd17(tmp_path, code):
    ge = seq_model(code)
    g = _gemini_row(tmp_path, ge)
    assert len(ge.timeouts) == 2  # 只重試一次
    assert g["light"]["error"] == code and g["detail"] == f"{code}:-:-:retried"


def test_retry_second_error_recorded_hd17(tmp_path):
    g = _gemini_row(tmp_path, seq_model("http_504", "http_429"))
    assert g["light"]["error"] == "http_429" and g["detail"] == "http_429:-:-:retried"


@pytest.mark.parametrize(
    "code", ["http_429", "http_400", "http_500", "bad_format", "bad_wording", "refusal", "timeout"]
)
def test_no_retry_other_errors_hd17(tmp_path, code):
    ge = seq_model(code, None)
    g = _gemini_row(tmp_path, ge)
    assert len(ge.timeouts) == 1
    assert g["light"]["error"] == code and g["detail"] == f"{code}:-:-" and g["calls"] == 1


def test_no_retry_when_budget_short_hd17(tmp_path):
    """剩餘預算不到 70 秒不重試，照舊記 `http_504`（沒有 `:retried`）。"""
    ge = seq_model("http_504", None)
    g = _gemini_row(tmp_path, ge, budget_s=69)
    assert len(ge.timeouts) == 1
    assert g["light"]["error"] == "http_504" and g["detail"] == "http_504:-:-" and g["calls"] == 1
    # 預算夠：重試的逾時也取 `TIMEOUT_S` 與剩下時間的小者
    ge = seq_model("http_504", None)
    assert _gemini_row(tmp_path, ge, budget_s=100)["status"] == "ok"
    assert len(ge.timeouts) == 2 and all(t == config.TIMEOUT_S for t in ge.timeouts)


def test_no_retry_past_daily_cap_hd17(tmp_path, monkeypatch):
    monkeypatch.setattr(ai_run, "DAILY_CAP", 1)
    ge = seq_model("http_504", None)
    g = _gemini_row(tmp_path, ge)
    assert len(ge.timeouts) == 1 and g["detail"] == "http_504:-:-" and g["calls"] == 1
