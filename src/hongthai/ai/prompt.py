"""給模型看的系統提示與一個機場的精簡文字（不把整段 JSON 丟進去）。

精簡文字（`airport_text`）只來自 `latest.json` 那個機場的欄位：機場名、時區、資料時間、METAR、
TAF 原文、生效中的警報、已確認停飛、20 格每格的當地時段、等級、依據、官方層（TAF 平均風／陣風、
側風、套用的警報）、模式層（EC／GFS 陣風、側風、`p29Kt`／`p49Kt`）、一致性、落差。單位一律節，
機率用百分比。最後附規則燈的門檻（`config.Thresholds` 的預設值；目前所有機場同一套），讓模型知道
規則燈怎麼來的。

HD8（新天氣種類）：每格多給 `causes`（主因在前）、官方層 `wx`（天氣現象、能見度、雲底、三類等級）、
模式層的雨量（`rain6hMm`）、降水型態（`ptype`）、系集 24 小時雨量機率（`p24hRain50`）、GFS 能見度
（`visibilityM`）；METAR 也給能見度、天氣現象、雲底。給模型看的標籤維持代號，短評裡要改成白話
（系統提示「用字」那段）。單位：雨量毫米、能見度公尺、雲底呎。

HD14（多模式投票）：模式層第一行給等級、投票句（「投票（強風）：5 個模式中 3 個認為高 → high」）、
一致性與系集機率；接著 `models[]` 每個模式一行（白話名、陣風——估算的標「估」、側風、雨量、型態、
等級）。模式名直接用白話（`MODEL_TEXT`），短評不能寫 AIFS、AIGFS（`ai/config.py` 擋）。

HD16（Open-Meteo 三票，8 票）：`models[]` 多德國模式（ICON）、日本模式（JMA GSM）、Google 的 AI 系集
（WeatherNext 2）三行，系集那行給中位數估算陣風與成員比例；旁觀模式（`voting: false`）那行標
「旁觀，不投票」，投票句的分母不含它（`assess.tally`）。短評不能寫 ICON、GSM、WeatherNext。

HD33b：Open-Meteo 的三個旁觀模式（加拿大、法國、中國模式，`Model.ai=False`）**不給 AI**，
文字維持上面 8 個模式（改 AI 提示要另外決定）；它們不投票，所以投票句也不變。

HD40（氣象署 2026-10-27 回覆、Shawn 定案）：規則加「只陳述資料來源說了什麼，不自行延伸
推論」；精簡文字每一段資料前面加來源代號（`tag`，代號是 `config.SOURCES`，給模型看的說明是
`SOURCE_TEXT`），模型每句短評附 `src`。不標代號的只有 `UNLABELED` 開頭的行與 `- ` 明細（明細
屬於上一個有代號的段落）。

HD43（WeatherNext 3 投一票，Shawn 2026-10-28 定案）：`vote` 模式時 WN3 不是一般的一行模式
明細（`Model.ai=False`），而是精簡文字最後另外一段「多模式綜合」（代號 `multi`，`multi_lines`；
只有日本、南韓以外、這一報有 WN3 資料的機場），**數字是送給 AI 的內部輸入**，那段與系統提示都寫明
不能引用數字、不能說是哪個模式；模式名不寫。投票句照 `model.vote`（含 WN3 那票）。程式檢查在
`parse.check_wn3`：`wn3_numbers` 是那段獨有的整數。`airport_text(..., wn3=False)` 是拿掉那段的
版本（重生用）。
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from ..assess import ENS_ID, MODEL_CAUSE_ORDER, ONLY_HIGH, ai_hidden, model_vote, non_voting, tally
from ..config import GUST_FACTOR_RANGE, Thresholds
from ..og import slot_text
from ..timeutil import parse_time
from .config import BLEND_SOURCE, BLEND_SOURCES, HIDDEN_MODELS, MODEL_SOURCES, SOURCES
from .parse import integers, round_half_up

# 模式的白話名（HD14；短評裡也照這樣寫）
MODEL_TEXT = {
    "ifs": "歐洲模式",
    "gfs": "美國模式",
    "ifs-ens": "歐洲系集",
    "aifs": "歐洲 AI 模式",
    "aigfs": "美國 AI 模式",
    "icon": "德國模式",  # HD16
    "jma": "日本模式",
    "wn2-ens": "Google 的 AI 系集",
    "wn3": "Google 的新一代 AI 系集",  # HD15，只在 `observe` 模式出現
}
# 來源代號（HD40，`config.SOURCES`）：給模型看的說明，和 `airport_text` 每一段前面的 `[代號]`
# 一一對應
SOURCE_TEXT = {
    "taf": "機場預報：TAF 原文，與每格官方層的機場預報數字（平均風、陣風、側風、wx）",
    "metar": "機場觀測：METAR，與沒有 TAF 的機場第一格官方層的觀測數字",
    "warning": "官方警報：生效中的官方警報，與每格套用的警報",
    "confirmed": "已確認停飛",
    **{
        m: f"{MODEL_TEXT[m]}：每格模式明細裡「{MODEL_TEXT[m]}」那一行"
        + ("，與每格的 p29Kt、p49Kt、p24hRain50" if m == ENS_ID else "")
        for m in MODEL_SOURCES
    },
    # HD43：不寫模式名
    BLEND_SOURCE: "多模式綜合：最後「多模式綜合」那一段（另一個模式的逐格估算，已算進模式投票；"
    "只能影響整體判斷，不能引用那段的任何數字、不能說是哪個模式說的）",
    "vote": "模式投票：每格模式層的等級、投票結果、歐洲模式與美國模式是否一致",
    "rule": "規則燈：每格的等級、依據、causes、官方與模式落差，與最後的規則燈門檻說明",
}
SOURCE_LINES = [f"- {k}：{SOURCE_TEXT[k]}" for k in SOURCES]

SYSTEM = "\n".join(
    [
        "你是航空氣象評論員，替「HongThai 機場停飛風險」網頁評一個機場未來 5 天的停飛風險"
        "（強風／側風、大雨／雷雨、大雪／結冰、濃霧／低雲）。",
        "",
        "規則：",
        "1. 只能根據使用者訊息裡給你的數據講。不能用你自己的天氣知識、新聞或任何外部資訊，"
        "也不能推測數據裡沒有的事。",
        "2. 只陳述資料來源說了什麼，不自行延伸推論：每一句都要能在使用者訊息裡找到根據"
        "（哪個來源、哪一格、什麼數字、幾個模式怎麼投）。不能預測資料沒寫的天氣變化"
        "（例如「風會再增強」「颱風可能轉向」），不能把一個來源的說法延伸到它沒涵蓋的時段"
        "或地點，也不能自己歸納資料沒寫的原因或趨勢。",
        "3. 不能自己估或寫出任何機率數字；數據裡已經有的機率可以照引"
        "（例如「陣風超過 49 節的機率 30%」）。",
        "4. 風速一律用「節」，雨量用「毫米」，能見度用「公尺」，雲底用「呎」。"
        "時間用數據裡的當地日期時段（例如「10/23 14–20 時」）。",
        "5. 給一個等級：low（低）、medium（中）、high（高）三選一。可以和規則燈不同，"
        "這正是請你評的原因；但短評裡說明等級時只能引用資料（例如「五個模式中三個認為高」"
        "「機場預報陣風 50 節，超過高的門檻 48 節」），不能用資料以外的理由。",
        "6. 寫一段短評，像評論員：說明依據哪幾格、哪些數字，分成幾個完整的句子，"
        "zh-TW 合計 60–120 字。只講風險判讀，不給乘客建議（例如改票、提早出門）。",
        "7. 每一句附來源代號（src）：那一句的內容出自哪幾段資料，就列那幾段前面方括號裡的代號"
        "（清單見下面「來源代號」），至少一個；只能用清單裡的代號，不能自己造，"
        "也不能列那一句沒用到的來源。代號只放在 src，句子裡不寫代號和方括號。",
        "8. 短評先寫 zh-TW，再把同一段逐句忠實翻成 zh-HK、zh-CN、en（各語的用語見下面「用字」）。"
        "四語內容必須完全一樣，不得增減任何資訊；四語的句數一樣、逐句對應，"
        "同一個位置的句子 src 完全一樣（同樣的代號、同樣的順序）。",
        "9. 短評第一句要點出主因天氣：強風／側風、大雨／雷雨、大雪／結冰、濃霧／低雲"
        "（每格的 causes 第一個就是規則燈的主因；你可以有不同看法，但要說得出依據）。",
        *(
            [
                "10. 「多模式綜合」那段（代號 multi，有的機場才有）是另一個模式的逐格估算，"
                "已算進每格的模式投票：只能用來影響你的整體判斷，短評裡不能寫出那段的任何數字"
                "（平均風、陣風、側風、雨量，換算、四捨五入或約略的寫法都不行），不能說是哪個模式、"
                "哪家公司的模式，也不能把判斷歸給它；用到那段的句子 src 寫 multi"
                "（和其他來源一起列也可以）。",
            ]
            if BLEND_SOURCES
            else []
        ),
        f"{11 if BLEND_SOURCES else 10}. 只回一個 JSON 物件，不要 Markdown、不要其他文字；"
        "不用另外寫整段短評（程式會把同一語的句子依序接起來）：",
        '{"level": "low|medium|high", "sentences": {'
        '"zh-TW": [{"text": "…", "src": ["taf", "ifs"]}, {"text": "…", "src": ["vote"]}], '
        '"zh-HK": […], "zh-CN": […], "en": […]}}',
        "",
        "來源代號（使用者訊息每一段前面方括號裡的代號；src 只能用這些）：",
        *SOURCE_LINES,
        "",
        "用字：",
        "1. 短評裡不出現內部代號：p29Kt、p49Kt、EC、GFS、HRES、TAF、METAR、crosswindKt、gustKt、"
        "basis、agreement、slots、causes、wx、ptype、rain6hMm、p24hRain50、visibilityM、ceilingFt、"
        "APCP、CSNOW、CFRZR、gustEstimated、AIFS、AIGFS、ICON、GSM、WeatherNext 這些欄位名或縮寫"
        "都不要寫，改成白話——",
        "   - EC → 「歐洲模式」（en: European model）；GFS → 「美國模式」（en: US model）；"
        "其他模式照資料裡的白話名寫：歐洲系集（en: European ensemble）、歐洲 AI 模式"
        "（en: European AI model）、美國 AI 模式（en: US AI model）、德國模式（en: German model）、"
        "日本模式（en: Japanese model）、Google 的 AI 系集（en: Google AI ensemble），"
        "不要寫 AIFS、AIGFS、ICON、GSM、WeatherNext",
        "   - 標「估」的陣風是用平均風估算的，要寫「估算陣風」（en: estimated gust），不能寫成陣風",
        "   - 投票的結果可以寫進短評，例如「五個模式中三個認為高」"
        "（en: three of five models say High）",
        "   - p49Kt 56% → 「陣風超過 49 節的機率 56%」（en: 56% chance of gusts over 49 kt）；"
        "p29Kt 同樣寫「陣風超過 29 節的機率 …」",
        "   - TAF → 「機場預報」，第一次出現時可以括號附原名「機場預報（TAF）」"
        "（en: airport forecast (TAF)），之後只寫「機場預報」；METAR → 「機場觀測」，同樣處理",
        "   - 側風、陣風、平均風直接用中文（en: crosswind, gusts, mean wind）",
        "   - rain6hMm 35 → 「6 小時雨量 35 毫米」（en: 35 mm of rain in 6 hours）；"
        "p24hRain50 30% → 「24 小時雨量超過 50 毫米的機率 30%」；"
        "visibilityM 800 → 「能見度 800 公尺」（en: visibility 800 m）；"
        "ceilingFt 200 → 「雲底 200 呎」（en: cloud base 200 ft）",
        "   - ptype：snow → 雪、wet_snow → 濕雪、rain_snow → 雨夾雪、freezing_rain → 凍雨、"
        "freezing_drizzle → 凍毛毛雨、ice_pellets → 冰珠、rain → 雨（en: snow, freezing rain…）；"
        "天氣現象代碼（+TSRA、FG、BR、SN）改寫成「強雷雨」「霧」「靄」「雪」",
        "   - 數字照抄資料，不准自己估",
        "   - en 也不要用 basis、agreement、slot 這幾個字（改寫成 based on、the models agree、"
        "period）",
        "2. 四語照當地用語：",
        "   - zh-TW 用台灣用語",
        "   - zh-HK 用書面語加香港用語，不用粵語口語（不寫喺、嘅、咗、嚟、啱啱、唔、佢、冇、咁，"
        "連接詞「同」改用「與」「和」）。颱風警報 → 颱風警告（台灣、日本、其他地方發的都寫"
        "「颱風警告」；只有提到香港天文台的熱帶氣旋警告信號時才寫「信號」，例如「八號信號」）；"
        "機場預報 → 機場預報；陣風 → 陣風；停飛 → 停飛；航班 → 航班；飯店 → 酒店；"
        "計程車 → 的士；公車 → 巴士；早上／晚上 → 上午／晚上",
        "   - zh-CN 用簡體加大陸用語：颱風 → 台风；停飛風險 → 停飞风险；側風 → 侧风；陣風 → 阵风；"
        "機場預報 → 机场预报；信號 → 信号；節 → 节；機率 → 概率（不是「机率」）；"
        "資料 → 数据（不是「资料」）；濃霧 → 浓雾；能見度 → 能见度；雲底 → 云底；結冰 → 结冰；"
        "冰雹 → 冰雹；雷雨 → 雷雨；大雪 → 大雪；公尺 → 米；呎 → 英尺",
        "   - zh-HK 的濃霧、能見度、雲底、結冰、冰雹、雷雨、大雪和台灣寫法一樣",
        "   - en 用自然英文（gusts、crosswind、typhoon signal、airport forecast (TAF)）；"
        "時間寫成 10/19 12:00–13:00 或 12–13 h local，不寫「時」；en 裡不能有任何中日文字"
        "或全形標點",
        "   - 內容四語完全一樣，只換用語，不增不減",
        "3. 短評裡不寫英文等級字，不出現「高（high）」這種寫法；等級用該語言的字——"
        "中文「低／中／高」，英文 Low／Medium／High（JSON 的 level 欄位照樣用 low／medium／high）",
        "4. 叫法一致：中文三語統一叫「停飛風險」（zh-CN「停飞风险」），不要一則寫「停飛」、"
        "一則寫「航班取消」；英文統一叫 disruption risk（不要一下 cancellation、一下 suspension）",
        "",
        "不要在 JSON 外面寫任何字、不要加 Markdown 標記。",
    ]
)

BASIS_TEXT = {"official": "官方", "model": "模式", "confirmed": "已確認停飛", "none": "無資料"}
AGREEMENT_TEXT = {"agree": "一致", "disagree": "不一致"}
WARNING_KIND_TEXT = {
    "tc_signal": "熱帶氣旋信號",
    "typhoon_land": "陸上颱風警報",
    "typhoon_sea": "海上颱風警報",
    "typhoon_warning": "颱風警報",
    "typhoon_watch": "颱風守視",
    "ts_warning": "熱帶風暴警報",
    "ts_watch": "熱帶風暴守視",
    "rainstorm_black": "黑色暴雨警告信號",
    "rainstorm_red": "紅色暴雨警告信號",
    "thunderstorm": "雷暴警告",
    "cwa_heavy_rain": "豪雨特報（大豪雨以上）",
    "cwa_dense_fog": "濃霧特報",
}
CAUSE_TEXT = {"wind": "強風", "rain": "大雨", "snow": "大雪", "fog": "濃霧"}
LEVEL_WORD = {"high": "高", "medium": "中以上"}


def _num(v: object, unit: str = "") -> str:
    if v is None or isinstance(v, bool) or not isinstance(v, int | float):
        return "—"
    return f"{v:g}{unit}"


def _kt(v: object) -> str:
    return _num(v, " 節")


def _pct(v: object) -> str:
    if v is None or isinstance(v, bool) or not isinstance(v, int | float):
        return "—"
    return f"{round(v * 100)}%"


def _local(t: str | None, z: ZoneInfo) -> str:
    dt = parse_time(t) if t else None
    return "—" if dt is None else f"{dt.astimezone(z):%m/%d %H:%M}"


def _utc_offset(z: ZoneInfo, at: datetime) -> str:
    off = at.astimezone(z).utcoffset()
    minutes = int(off.total_seconds() // 60) if off is not None else 0
    sign = "+" if minutes >= 0 else "-"
    h, m = divmod(abs(minutes), 60)
    return f"UTC{sign}{h}" + (f":{m:02d}" if m else "")


def _wx(wx: object) -> str:
    """官方層的 `wx`（HD8）。"""
    if not isinstance(wx, dict):
        return "wx 無"
    phen = " ".join(str(p) for p in wx.get("phenomena") or []) or "無"
    return (
        f"wx（現象 {phen}、能見度 {_num(wx.get('visibilityM'), ' 公尺')}、"
        f"雲底 {_num(wx.get('ceilingFt'), ' 呎')}、rain {wx.get('rain') or '—'}、"
        f"snow {wx.get('snow') or '—'}、fog {wx.get('fog') or '—'}）"
    )


def tag(code: str) -> str:
    """精簡文字裡一段資料的來源標籤（HD40）：`[taf]`；`code` 一定要在 `config.SOURCES` 裡。"""
    return f"[{code}]"


def _official(o: dict | None) -> str:
    """官方層：機場預報（沒有 TAF 的機場第一格是觀測）一段、套用的警報一段（HD40 分開標來源）。"""
    if not isinstance(o, dict):
        return f"{tag('taf')} 官方：無"
    warns = "、".join(WARNING_KIND_TEXT.get(k, str(k)) for k in o.get("warnings") or []) or "無"
    # HD13：沒有 TAF 的機場第一格由 METAR 撐起（`kind: "metar"`）
    if o.get("kind") == "metar":
        code, src = "metar", "METAR（觀測）"
    else:
        code, src = "taf", f"TAF（{o.get('kind') or '無'}）"
    return (
        f"{tag(code)} 官方：等級 {o.get('level') or '—'}、{src}平均風 "
        f"{_kt(o.get('windKt'))}、陣風 {_kt(o.get('gustKt'))}、側風 {_kt(o.get('crosswindKt'))}、"
        f"{_wx(o.get('wx'))}｜{tag('warning')} 套用的警報 {warns}"
    )


def _vote(m: dict, models: list[dict]) -> str:
    """「投票（強風）：5 個模式中 3 個認為高 → high」（HD14）。"""
    v = m.get("vote") if isinstance(m.get("vote"), dict) else {}
    level = v.get("level")
    if not models or level not in ("low", "medium", "high"):
        return "投票：沒有模式資料"
    thin = f"（風只有 {v.get('total')} 個模式有資料）" if v.get("thin") else ""
    if level == "low":
        return f"投票：每一類都沒有過半的模式認為中以上 → low{thin}"
    cats, _ = model_vote(models)
    cause = next((c for c in MODEL_CAUSE_ORDER if cats.get(c) == level), "wind")
    votes, total = tally(models, cause, level)
    return (
        f"投票（{CAUSE_TEXT[cause]}）：{total} 個模式中 {votes} 個認為{LEVEL_WORD[level]}"
        f" → {level}{thin}"
    )


def _model_entry(e: dict, ec: dict) -> str:
    mid = str(e.get("id"))
    name = f"{tag(mid)} {MODEL_TEXT.get(mid, mid)}"
    if mid in non_voting():  # HD16
        name += "（旁觀，不投票）"
    lv = e.get("levels") if isinstance(e.get("levels"), dict) else {}
    gust = _kt(e.get("gustKt")) + ("（估）" if e.get("gustEstimated") else "")
    if mid == ENS_ID:
        if lv.get("wind") is None:
            return f"  - {name}：無資料"
        return f"  - {name}：p49Kt {_pct(ec.get('p49Kt'))} → 投 {lv['wind']}（只投高）"
    if mid in ONLY_HIGH:  # WN2 系集（HD16）
        if lv.get("wind") is None:
            return f"  - {name}：無資料"
        return (
            f"  - {name}：成員中位數陣風 {gust}、估算陣風達 high 門檻的成員比例 "
            f"{_pct(e.get('p49Kt'))} → 投 {lv['wind']}（只投高）"
        )
    if e.get("level") is None:
        return f"  - {name}：無資料"
    levels = "、".join(f"{c} {lv.get(c) or '—'}" for c in ("wind", "rain", "snow", "fog"))
    return (
        f"  - {name}：陣風 {gust}、側風 {_kt(e.get('crosswindKt'))}、"
        f"rain6hMm {_num(e.get('rain6hMm'), ' mm')}、ptype {e.get('ptype') or '—'}、"
        f"visibilityM {_num(e.get('visibilityM'), ' 公尺')}、等級 {e.get('level')}（{levels}）"
    )


def _models(m: object) -> list[dict]:
    """`models[]` 裡給 AI 看的那幾筆：`Model.ai=False` 的（HD33b 的三個旁觀模式）不給。"""
    if not isinstance(m, dict):
        return []
    hidden = ai_hidden()
    return [e for e in m.get("models") or [] if isinstance(e, dict) and e.get("id") not in hidden]


def _model(m: dict | None) -> str:
    """模式層：等級、投票、一致性、系集機率（每個模式的明細在 `_model_lines`，HD14）。"""
    if not isinstance(m, dict):
        return f"{tag('vote')} 模式：無"
    ec = m.get("ec") if isinstance(m.get("ec"), dict) else {}
    agreement = AGREEMENT_TEXT.get(m.get("agreement"), "缺一個模式")  # type: ignore[arg-type]
    # 投票句用全部的模式（HD43：數值不公開的那個也算進分母；旁觀模式 `tally` 本來就不算）
    entries = [e for e in m.get("models") or [] if isinstance(e, dict)]
    return (
        f"{tag('vote')} 模式：等級 {m.get('level') or '—'}、{_vote(m, entries)}、"
        f"EC 與 GFS {agreement}（只看陣風）｜{tag(ENS_ID)} 系集機率 p29Kt {_pct(ec.get('p29Kt'))}、"
        f"p49Kt {_pct(ec.get('p49Kt'))}、p24hRain50 {_pct(ec.get('p24hRain50'))}"
    )


def _model_lines(m: object) -> list[str]:
    """`models[]` 每個模式一行（接在那一格後面）。"""
    ec = m.get("ec") if isinstance(m, dict) and isinstance(m.get("ec"), dict) else {}
    return [_model_entry(e, ec) for e in _models(m)]


def _causes(slot: dict) -> str:
    causes = [c for c in slot.get("causes") or [] if isinstance(c, str)]
    if not causes:
        return "causes 無"
    return "causes " + "、".join(f"{c}（{CAUSE_TEXT.get(c, c)}）" for c in causes)


def slot_line(i: int, slot: dict, tz: str) -> str:
    try:
        when = slot_text(slot, tz)
    except (KeyError, TypeError, ValueError, AttributeError):
        when = f"{slot.get('from')}–{slot.get('to')}（UTC）"
    gap = "是" if slot.get("gap") else "否"
    rule = tag("rule")
    line = (
        f"{i}. {when}｜{rule} 等級 {slot.get('level') or '—'}"
        f"（依據 {BASIS_TEXT.get(slot.get('basis'), '—')}）｜{rule} {_causes(slot)}｜"  # type: ignore[arg-type]
        f"{_official(slot.get('official'))}｜{_model(slot.get('model'))}｜"
        f"{rule} 官方與模式落差 {gap}"
    )
    return "\n".join([line, *_model_lines(slot.get("model"))])


def rules_text(th: Thresholds | None = None, blend: bool = False) -> str:
    """`blend`：這個機場的投票含數值不公開的模式（HD43，日本、南韓以外）。"""
    th = th or Thresholds()
    return "\n".join(
        [
            f"{tag('rule')} 規則燈怎麼算（每格取官方層與模式層；0–30 小時以官方為準）：",
            "- p29Kt／p49Kt：EC 系集「陣風 ≥ 29／49 節」的機率",
            f"- 陣風（TAF 與模式同一套）：≥ {th.model_high_gust_kt:g} 節 → high，"
            f"≥ {th.model_medium_gust_kt:g} 節 → medium；"
            f"TAF 平均風 ≥ {th.taf_high_wind_kt:g} 節 → high",
            f"- 含陣風側風（所有跑道裡最小的）：≥ {th.crosswind_high_kt:g} 節 → high，"
            f"≥ {th.crosswind_medium_kt:g} 節 → medium",
            "- 模式層是投票（每格）：歐洲模式、美國模式、歐洲系集、歐洲 AI 模式、美國 AI 模式、"
            "德國模式、日本模式、Google 的 AI 系集各一票；某一級的票（認為 ≥ 這一級的模式數）"
            "達到有資料模式數的一半就成立，取成立的最高級；強風、雨、雪、霧各自投，再取最高；"
            "標「旁觀，不投票」的模式只列出、不算票也不算分母"
            + (
                "；另有一個模式也投一票（明細不列，見「多模式綜合」那段；"
                "所以投票句的模式數比上面列的多一個）"
                if blend
                else ""
            ),
            f"- 歐洲系集只投 high：p49Kt ≥ {round(th.ec_p49_high * 100)}% 投 high、否則投 low，"
            "判 medium 時不算它（p29Kt 只是參考）",
            "- Google 的 AI 系集也只投 high：每個成員的估算陣風達 high 門檻"
            f"（{th.model_high_gust_kt:g} 節）的成員比例 ≥ {round(th.ec_p49_high * 100)}% "
            "投 high、否則投 low；不投雨、雪、霧",
            "- 歐洲 AI 模式、美國 AI 模式、日本模式、Google 的 AI 系集沒有陣風：10 米平均風 × "
            "這個機場的係數估算（標「估」；係數是歐洲模式最近 30 天陣風÷平均風的中位數，"
            f"{GUST_FACTOR_RANGE[0]:.1f}–{GUST_FACTOR_RANGE[1]:.1f}），門檻同陣風；"
            "雪只有有降水型態的模式投"
            "（美國 AI 模式不投），霧只有美國模式有能見度",
            "- 官方警報：颱風／熱帶氣旋信號（8 號以上、陸上警報、Warning）→ high，"
            "3 號、海上警報、Watch → medium；只套用到「現在 + 12 小時」內開始的格",
            "- 已確認停飛的格 → confirmed；官方與模式都沒資料 → unknown",
            "- 官方與模式差一級以上標「落差」；EC 與 GFS 陣風同一級＝一致",
            "- 雨（rain）：官方 冰雹 → high，+TSRA 或雷雨且能見度 ≤ "
            f"{th.taf_rain_medium_vis_m:g} 公尺 → medium；模式 6 小時雨量 ≥ "
            f"{th.model_rain_high_mm6h:g} mm → high、≥ {th.model_rain_medium_mm6h:g} mm "
            f"或 p24hRain50 ≥ {round(th.ec_p24h_rain50_medium * 100)}% → medium；"
            "天文台黑雨、氣象署大豪雨以上特報 → medium（紅雨、雷暴警告只列出）",
            "- 雪（snow）：官方 +SN、凍雨、冰珠 → high，雪且能見度 ≤ "
            f"{th.taf_snow_medium_vis_m:g} 公尺 → medium（-SN 不升級）；模式 降雪水當量 ≥ "
            f"{th.model_snow_high_mm6h:g} mm → high、≥ {th.model_snow_medium_mm6h:g} mm → medium，"
            f"凍雨 ≥ {th.model_freezing_rain_high_mm6h:g} mm → high",
            f"- 霧（fog）：能見度 < {th.fog_high_vis_m:g} 公尺或雲底 ≤ "
            f"{th.fog_high_ceiling_ft:g} 呎 → high，< {th.fog_medium_vis_m:g} 公尺或 ≤ "
            f"{th.fog_medium_ceiling_ft:g} 呎 → medium（模式只有美國模式的能見度，"
            "模式層的霧最高只到 medium；要到 high 得是官方真的報霧或低雲）",
            "- 每格的等級＝強風與三類取最高；causes 是達到 medium 以上的種類（高的在前），"
            "第一個是主因；只看模式時同級的雨排在霧前面（模式的低能見度常是大雨造成的）",
            "提醒：短評要說出主要是哪種天氣造成：強風／側風、大雨／雷雨、大雪／結冰、濃霧／低雲。",
            "提醒：每一句只陳述上面資料說了什麼、不自行延伸推論，src 列那一句用到的段落前面的"
            "方括號代號。",
            "提醒：短評裡請用白話，不要照抄上面的欄位名"
            "（EC、GFS、p29Kt、p49Kt、TAF、METAR 這些）。",
        ]
    )


# 精簡文字裡不標來源的行（HD40）：表頭、每格的標題與給模型的提醒；其他每一行都以 `[代號]` 開頭，
# 或是上一行底下的 `- ` 明細（模式明細那幾行自己也有代號），每格那一行 `｜` 隔開的每一段都有代號
UNLABELED = ("機場：", "資料時間：", "每格（", "提醒：")


def _hidden_entries(slot: dict) -> list[dict]:
    """一格裡數值不公開的模式（HD43 的 WN3）有資料的那幾筆（build 記憶體裡還是完整的）。"""
    m = slot.get("model")
    entries = m.get("models") if isinstance(m, dict) else None
    return [
        e
        for e in entries or []
        if isinstance(e, dict) and e.get("id") in HIDDEN_MODELS and e.get("level") is not None
    ]


# 多模式綜合那段給模型看的數字（`wn3_numbers` 也照這幾個算）
BLEND_KEYS = ("windKt", "gustKt", "crosswindKt", "rain6hMm")


def has_blend(airport: dict) -> bool:
    """這個機場有沒有多模式綜合那段（HD43）：`vote` 模式、而且至少一格 WN3 有資料（日本、南韓的
    機場 build 不給資料，所以沒有）。"""
    slots = [s for s in airport.get("slots") or [] if isinstance(s, dict)]
    return bool(BLEND_SOURCES) and any(_hidden_entries(s) for s in slots)


def multi_lines(airport: dict) -> list[str]:
    """多模式綜合那段（HD43）：說明一行＋每格一行（當地時段、平均風、估算陣風、側風、雨量、等級）。"""
    tz = airport.get("tz") or "UTC"
    lines = [
        f"{tag(BLEND_SOURCE)} 多模式綜合（另一個模式的逐格估算，已算進上面每格的模式投票）："
        "這段只能影響整體判斷，不能引用這段的任何數字（換算、四捨五入也不行），"
        "不能說是哪個模式說的；用到這段的句子 src 寫 multi"
    ]
    for i, slot in enumerate((s for s in airport.get("slots") or [] if isinstance(s, dict)), 1):
        try:
            when = slot_text(slot, tz)
        except (KeyError, TypeError, ValueError, AttributeError):
            when = f"{slot.get('from')}–{slot.get('to')}（UTC）"
        for e in _hidden_entries(slot):
            lv = e.get("levels") if isinstance(e.get("levels"), dict) else {}
            levels = "、".join(f"{c} {lv.get(c) or '—'}" for c in ("wind", "rain", "snow", "fog"))
            lines.append(
                f"- {i}. {when}：平均風 {_kt(e.get('windKt'))}、估算陣風 {_kt(e.get('gustKt'))}、"
                f"側風 {_kt(e.get('crosswindKt'))}、6 小時雨量 {_num(e.get('rain6hMm'), ' 毫米')}、"
                f"等級 {e.get('level')}（{levels}）"
            )
    return lines


def wn3_numbers(airport: dict, generated_at: str) -> frozenset[int]:
    """多模式綜合那段**獨有**的整數（HD43，`parse.check_wn3`）：那段的數值（`BLEND_KEYS`）四捨五入
    到整數，扣掉拿掉那段的精簡文字裡出現過的所有整數（其他來源同值的數字不算違規）。"""
    mine = {
        round_half_up(float(v))
        for s in airport.get("slots") or []
        if isinstance(s, dict)
        for e in _hidden_entries(s)
        for k in BLEND_KEYS
        if isinstance(v := e.get(k), int | float) and not isinstance(v, bool)
    }
    return frozenset(mine - integers(airport_text(airport, generated_at, wn3=False)))


def airport_text(airport: dict, generated_at: str, wn3: bool = True) -> str:
    """一個機場給模型看的精簡文字（`airport` 是 `latest.json` 的 `airports[]` 一筆）；每一段資料前面
    有來源代號（`tag`，HD40），模型每句短評的 `src` 就是這些代號。`wn3=False`：不放多模式綜合那段
    （HD43，WN3 違規兩次後重生用）。"""
    tz = airport.get("tz") or "UTC"
    z = ZoneInfo(tz)
    gen = parse_time(generated_at)
    name = airport.get("name") or {}
    lines = [
        f"機場：{name.get('zh-TW', '')}（{name.get('en', '')}，{airport.get('icao')}／"
        f"{airport.get('iata')}），時區 {tz}（{_utc_offset(z, gen)}）",
        f"資料時間：{generated_at}（當地 {_local(generated_at, z)}）",
    ]
    metar = airport.get("metar")
    if isinstance(metar, dict):
        wdir = metar.get("windDirDeg")
        phen = " ".join(str(w) for w in metar.get("wx") or []) or "無"
        # HD13：金門、馬祖沒有機場 METAR，用氣象署局屬站的觀測
        src = "氣象署局屬站觀測、" if metar.get("source") == "cwa" else ""
        lines.append(
            f"{tag('metar')} METAR（{src}觀測 當地 {_local(metar.get('observedAt'), z)}）：風向 "
            f"{'不定' if wdir is None else _num(wdir, '°')}、風 {_kt(metar.get('windKt'))}、"
            f"陣風 {_kt(metar.get('gustKt'))}、能見度 {_num(metar.get('visibilityM'), ' 公尺')}、"
            f"天氣 {phen}、雲底 {_num(metar.get('ceilingFt'), ' 呎')}；原文 {metar.get('raw')}"
        )
    else:
        lines.append(f"{tag('metar')} METAR：無")
    taf = airport.get("taf")
    if isinstance(taf, dict):
        lines.append(
            f"{tag('taf')} TAF（發布 當地 {_local(taf.get('issuedAt'), z)}，"
            f"有效 {_local(taf.get('validFrom'), z)}–{_local(taf.get('validTo'), z)}）："
            f"原文 {taf.get('raw')}"
        )
    else:
        lines.append(f"{tag('taf')} TAF：無")
    official = airport.get("official")
    if isinstance(official, dict) and official.get("warnings") is False:
        lines.append(f"{tag('warning')} 生效中的官方警報：這個機場沒有接官方警報來源")
    else:
        warns = [w for w in airport.get("warnings") or [] if isinstance(w, dict)]
        if not warns:
            lines.append(f"{tag('warning')} 生效中的官方警報：無")
        else:
            lines.append(f"{tag('warning')} 生效中的官方警報：")
            for w in warns:
                text = (w.get("text") or {}).get("zh-TW") or ""
                kind = WARNING_KIND_TEXT.get(w.get("kind"), w.get("kind"))  # type: ignore[arg-type]
                lines.append(
                    f"- {kind}（等級 {w.get('level')}，發布 當地 {_local(w.get('issuedAt'), z)}）："
                    f"{text}"
                )
    confirmed = [c for c in airport.get("confirmed") or [] if isinstance(c, dict)]
    if not confirmed:
        lines.append(f"{tag('confirmed')} 已確認停飛：無")
    else:
        lines.append(f"{tag('confirmed')} 已確認停飛：")
        for c in confirmed:
            note = (c.get("note") or {}).get("zh-TW") or ""
            lines.append(f"- 當地 {_local(c.get('from'), z)}–{_local(c.get('to'), z)} {note}")
    slots = [s for s in airport.get("slots") or [] if isinstance(s, dict)]
    lines.append(f"每格（{len(slots)} 格、每格 6 小時、當地時間）：")
    lines += [slot_line(i, s, tz) for i, s in enumerate(slots, 1)]
    blend = has_blend(airport)
    if blend and wn3:
        lines += multi_lines(airport)
    lines.append(rules_text(blend=blend))
    return "\n".join(lines)
