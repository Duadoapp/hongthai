"""給模型看的系統提示與一個機場的精簡文字（不把整段 JSON 丟進去）。

精簡文字（`airport_text`）只來自 `latest.json` 那個機場的欄位：機場名、時區、資料時間、METAR、
TAF 原文、生效中的警報、已確認停飛、20 格每格的當地時段、等級、依據、官方層（TAF 平均風／陣風、
側風、套用的警報）、模式層（EC／GFS 陣風、側風、`p29Kt`／`p49Kt`）、一致性、落差。單位一律節，
機率用百分比。最後附規則燈的門檻（`config.Thresholds` 的預設值；目前所有機場同一套），讓模型知道
規則燈怎麼來的。
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from ..config import Thresholds
from ..og import slot_text
from ..timeutil import parse_time

SYSTEM = "\n".join(
    [
        "你是航空氣象評論員，替「HongThai 機場停飛風險」網頁評一個機場未來 5 天的強風停飛風險。",
        "",
        "規則：",
        "1. 只能根據使用者訊息裡給你的數據講。不能用你自己的天氣知識、新聞或任何外部資訊，"
        "也不能推測數據裡沒有的事。",
        "2. 不能自己估或寫出任何機率數字；數據裡已經有的機率可以照引"
        "（例如「陣風超過 49 節的機率 30%」）。",
        "3. 風速一律用「節」。時間用數據裡的當地日期時段（例如「10/23 14–20 時」）。",
        "4. 給一個等級：low（低）、medium（中）、high（高）三選一。可以和規則燈不同，"
        "這正是請你評的原因，但要說得出依據。",
        "5. 寫一段短評，像評論員：說明依據哪幾格、哪些數字，zh-TW 60–120 字。"
        "只講風險判讀，不給乘客建議（例如改票、提早出門）。",
        "6. 短評先寫 zh-TW，再把同一段忠實翻成 zh-HK、zh-CN、en（各語的用語見下面「用字」）。"
        "四語內容必須完全一樣，不得增減任何資訊。",
        "7. 只回一個 JSON 物件，不要 Markdown、不要其他文字：",
        '{"level": "low|medium|high", "comment": '
        '{"zh-TW": "…", "zh-HK": "…", "zh-CN": "…", "en": "…"}}',
        "",
        "用字：",
        "1. 短評裡不出現內部代號：p29Kt、p49Kt、EC、GFS、HRES、TAF、METAR、crosswindKt、gustKt、"
        "basis、agreement、slots 這些欄位名或縮寫都不要寫，改成白話——",
        "   - EC → 「歐洲模式」（en: European model）；GFS → 「美國模式」（en: US model）",
        "   - p49Kt 56% → 「陣風超過 49 節的機率 56%」（en: 56% chance of gusts over 49 kt）；"
        "p29Kt 同樣寫「陣風超過 29 節的機率 …」",
        "   - TAF → 「機場預報」，第一次出現時可以括號附原名「機場預報（TAF）」"
        "（en: airport forecast (TAF)），之後只寫「機場預報」；METAR → 「機場觀測」，同樣處理",
        "   - 側風、陣風、平均風直接用中文（en: crosswind, gusts, mean wind）",
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
        "資料 → 数据（不是「资料」）",
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
}


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


def _official(o: dict | None) -> str:
    if not isinstance(o, dict):
        return "官方：無"
    warns = "、".join(WARNING_KIND_TEXT.get(k, str(k)) for k in o.get("warnings") or []) or "無"
    return (
        f"官方：等級 {o.get('level') or '—'}、TAF（{o.get('kind') or '無'}）平均風 "
        f"{_kt(o.get('windKt'))}、陣風 {_kt(o.get('gustKt'))}、側風 {_kt(o.get('crosswindKt'))}、"
        f"警報 {warns}"
    )


def _model(m: dict | None) -> str:
    if not isinstance(m, dict):
        return "模式：無"
    ec = m.get("ec") if isinstance(m.get("ec"), dict) else {}
    gfs = m.get("gfs") if isinstance(m.get("gfs"), dict) else {}
    agreement = AGREEMENT_TEXT.get(m.get("agreement"), "缺一個模式")  # type: ignore[arg-type]
    return (
        f"模式：等級 {m.get('level') or '—'}、EC 陣風 {_kt(ec.get('hresGustKt'))}、"
        f"GFS 陣風 {_kt(gfs.get('gustKt'))}、EC 側風 {_kt(ec.get('crosswindKt'))}、"
        f"GFS 側風 {_kt(gfs.get('crosswindKt'))}、p29Kt {_pct(ec.get('p29Kt'))}、"
        f"p49Kt {_pct(ec.get('p49Kt'))}、EC 與 GFS {agreement}"
    )


def slot_line(i: int, slot: dict, tz: str) -> str:
    try:
        when = slot_text(slot, tz)
    except (KeyError, TypeError, ValueError, AttributeError):
        when = f"{slot.get('from')}–{slot.get('to')}（UTC）"
    gap = "是" if slot.get("gap") else "否"
    return (
        f"{i}. {when}｜等級 {slot.get('level') or '—'}"
        f"（依據 {BASIS_TEXT.get(slot.get('basis'), '—')}）｜"  # type: ignore[arg-type]
        f"{_official(slot.get('official'))}｜{_model(slot.get('model'))}｜官方與模式落差 {gap}"
    )


def rules_text(th: Thresholds | None = None) -> str:
    th = th or Thresholds()
    return "\n".join(
        [
            "p29Kt／p49Kt：EC 系集「陣風 ≥ 29／49 節」的機率。",
            "規則燈怎麼算（每格取官方層與模式層；0–30 小時以官方為準）：",
            f"- 陣風（TAF 與模式同一套）：≥ {th.model_high_gust_kt:g} 節 → high，"
            f"≥ {th.model_medium_gust_kt:g} 節 → medium；"
            f"TAF 平均風 ≥ {th.taf_high_wind_kt:g} 節 → high",
            f"- 含陣風側風（所有跑道裡最小的）：≥ {th.crosswind_high_kt:g} 節 → high，"
            f"≥ {th.crosswind_medium_kt:g} 節 → medium",
            f"- p49Kt ≥ {round(th.ec_p49_high * 100)}% → high；中級不用系集（p29Kt 只是參考）",
            "- 官方警報：颱風／熱帶氣旋信號（8 號以上、陸上警報、Warning）→ high，"
            "3 號、海上警報、Watch → medium；只套用到「現在 + 12 小時」內開始的格",
            "- 已確認停飛的格 → confirmed；官方與模式都沒資料 → unknown",
            "- 官方與模式差一級以上標「落差」；EC 與 GFS 陣風同一級＝一致",
            "短評裡請用白話，不要照抄上面的欄位名（EC、GFS、p29Kt、p49Kt、TAF、METAR 這些）。",
        ]
    )


def airport_text(airport: dict, generated_at: str) -> str:
    """一個機場給模型看的精簡文字（`airport` 是 `latest.json` 的 `airports[]` 一筆）。"""
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
        lines.append(
            f"METAR（觀測 當地 {_local(metar.get('observedAt'), z)}）：風向 "
            f"{'不定' if wdir is None else _num(wdir, '°')}、風 {_kt(metar.get('windKt'))}、"
            f"陣風 {_kt(metar.get('gustKt'))}；原文 {metar.get('raw')}"
        )
    else:
        lines.append("METAR：無")
    taf = airport.get("taf")
    if isinstance(taf, dict):
        lines.append(
            f"TAF（發布 當地 {_local(taf.get('issuedAt'), z)}，"
            f"有效 {_local(taf.get('validFrom'), z)}–{_local(taf.get('validTo'), z)}）："
            f"原文 {taf.get('raw')}"
        )
    else:
        lines.append("TAF：無")
    official = airport.get("official")
    if isinstance(official, dict) and official.get("warnings") is False:
        lines.append("生效中的官方警報：這個機場沒有接官方警報來源")
    else:
        warns = [w for w in airport.get("warnings") or [] if isinstance(w, dict)]
        if not warns:
            lines.append("生效中的官方警報：無")
        else:
            lines.append("生效中的官方警報：")
            for w in warns:
                text = (w.get("text") or {}).get("zh-TW") or ""
                kind = WARNING_KIND_TEXT.get(w.get("kind"), w.get("kind"))  # type: ignore[arg-type]
                lines.append(
                    f"- {kind}（等級 {w.get('level')}，發布 當地 {_local(w.get('issuedAt'), z)}）："
                    f"{text}"
                )
    confirmed = [c for c in airport.get("confirmed") or [] if isinstance(c, dict)]
    if not confirmed:
        lines.append("已確認停飛：無")
    else:
        lines.append("已確認停飛：")
        for c in confirmed:
            note = (c.get("note") or {}).get("zh-TW") or ""
            lines.append(f"- 當地 {_local(c.get('from'), z)}–{_local(c.get('to'), z)} {note}")
    slots = [s for s in airport.get("slots") or [] if isinstance(s, dict)]
    lines.append(f"每格（{len(slots)} 格、每格 6 小時、當地時間）：")
    lines += [slot_line(i, s, tz) for i, s in enumerate(slots, 1)]
    lines.append(rules_text())
    return "\n".join(lines)
