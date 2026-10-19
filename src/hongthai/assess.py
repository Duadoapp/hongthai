"""判讀：把各來源的資料對到 6 小時格，依規格的等級規則算等級。全部是純函式。

規格（Duado `docs/spec.md`「16. HongThai」，初版、保守，之後用實際紀錄校準）。HD2（2026-10-19）起
風速一律用節（1 m/s = 1.943844 節），模式陣風解析完就換算成節：
- 模式：HRES 或 GFS 陣風 ≥ 48 節、或 EC 系集「陣風 ≥ 25 m/s（≈ 48.6 節）」機率 ≥ 30%
  （`p49Kt`）→ 高；HRES 或 GFS 陣風 ≥ 37 節 → 中；其他低。中級**不用系集**：ECMWF 開放資料的
  機率產品只有 ≥ 10／15／25 m/s（≈ 19.4／29.2／48.6 節），沒有 37 節的（`p37Kt` 一律 `null`，
  之後用 GEFS 系集成員自己算）；`p29Kt`（＝`p15`）只輸出、不進規則
- 官方（只看 0–30 小時）：天文台／SMG 8 號或以上 → 高，3 號 → 中；氣象署陸上颱風警報且機場在警戒區
  → 高，海上警報 → 中；NWS（關島，HD3）Typhoon／Tropical Storm Warning → 高、Watch → 中
  （對照在 `sources/nws.py`）；TAF 該時段陣風 ≥ 48 節（或平均風 ≥ 35 節）→ 高，陣風 ≥ 37 節 → 中
- 陣風門檻（TAF 與模式同一套）的依據：桃園機場空橋規則，最大瞬間風速 37 節（蒲福 8 級）啟動
  空橋防護、48 節（10 級）空橋停用、55 節以上全部綁死
- 0–30 小時以官方為準；官方與模式差一級以上標「落差」（`gap`）
- 一致性：HRES 與 GFS 的陣風落在同一級＝一致（`agree`）
- `confirmed.json` 有時段的格 → `confirmed`
- 所有機場先用同一套門檻（`config.Thresholds` 的預設值），之後找到個別機場的作業標準再在
  `airports.json` 的 `thresholds` 覆寫

本模組自己的約定（規格沒寫死的地方）：
- 「0–30 小時」：格的開始時間早於「現在 + 30 小時」
- 目前生效的警報（天文台／SMG 信號、氣象署颱風警報、NWS 警報）套用到開始時間早於
  「現在 + 12 小時」的格（`WARNING_HORIZON_H`；警報本身沒有預報時段，先保守地只套前兩三格）
- EC 系集機率是 24 小時窗：一格的機率取「完整包住這一格的所有窗」的最小值（6 小時內的機率
  不會超過任何包住它的 24 小時窗，所以是上界，偏保守）
- HRES 陣風：一格取結束時間落在 (from, to] 的所有區間最大值；GFS 是瞬時值，取 [from, to] 的時間點
- 官方與模式都沒有資料時，`level="unknown"`、`basis="none"`（規格以外新增的值）

側風（第二階段，2026-10-18 補充）：
- 側風分量＝含陣風的風速（有陣風用陣風，沒有用平均風）× |sin(風向 − 跑道方位)|；每條跑道的兩個
  方向取小的，再取所有跑道裡最小的（還有一條能用就不算停飛）。風向可變（VRB）或沒有風向時，
  側風＝風速本身（最保守）；機場沒設定跑道時不算側風（`crosswindKt: null`）
- 跑道方位用真北（METAR／TAF 與模式的風向都是真北；磁方位只記在 `airports.json` 備查）
- 門檻：含陣風側風 ≥ 27 節 → 中、≥ 33 節 → 高（`crosswindMediumKt`／`crosswindHighKt`，HD2）；
  依據是窄體客機常見的作業限制（737-800 濕跑道起飛約 27 節、乾跑道約 33 節）。
  和陣風規則取較高的等級（官方層、模式層各自合成）
- 官方：一格取重疊的 TAF 時段裡最大的側風；METAR 只算進「現在」所在的那一格（觀測在 3 小時內），
  而且只在該格本來就有官方資料（TAF 或警報）時

已經過去的 TAF 時段（HD7，2026-10-19）：
- TAF 只算「結束時間在現在之後」的時段（主時段、TEMPO、BECMG、PROB 都一樣）；只會影響現在所在的
  第一格。跨過現在的時段照算（還沒結束）
- 第一格裡的 TAF 時段全部已經過去時，這格當作沒有 TAF：有警報走「只有警報」的路（METAR 側風照上面
  的規則算進去），沒有警報就沒有官方層（TAF 全部過去代表那份 TAF 已經過期，跟沒有 TAF 一樣）
- 起因：關島 2026-10-19T03:57Z 那報，第一格被一段 02–03Z（產出前就結束）的 TEMPO 陣風 46 節判成高
- 模式：HRES 的 `10u`／`10v` 只抓 6 小時整的步長（00／06／12／18Z，H10 起，為了減少下載量），
  每個陣風區間配**區間結束時間往後最近**的那個 6 小時步長的風向（例如結束在 09Z 的 3 小時區間配
  12Z 的風）；GFS 用同一時間點的 `UGRD`／`VGRD`。一格取格內最大的側風（時間上取最壞、跑道上取最好）
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import radians, sin

from .config import ConfirmedPeriod, Runway, Thresholds
from .sources.ecmwf import EcmwfPoint
from .sources.gfs import GustPoint
from .sources.taf import Metar, TafPeriod
from .timeutil import iso
from .units import kt_to_ms, ms_to_kt

LEVELS = ("low", "medium", "high")
OFFICIAL_HORIZON_H = 30
WARNING_HORIZON_H = 12
METAR_MAX_AGE_H = 3


@dataclass(frozen=True)
class ActiveWarning:
    """目前生效的官方警報（天文台／SMG 信號、氣象署颱風警報、NWS 警報），給判讀與輸出用。"""

    source: str  # hko／cwa／smg／nws
    # tc_signal／typhoon_land／typhoon_sea／typhoon_warning／typhoon_watch／ts_warning／ts_watch
    kind: str
    level: str
    text: dict[str, str]
    issued_at: str | None
    code: str | None = None  # 天文台／SMG 信號代碼（例如 TC8NE）、NWS 的 event
    detail: str | None = None


def rank(level: str | None) -> int:
    return LEVELS.index(level) if level in LEVELS else -1


def max_level(levels: Iterable[str | None]) -> str | None:
    best = None
    for lv in levels:
        if lv in LEVELS and rank(lv) > rank(best):
            best = lv
    return best


def _round(v: float | None, nd: int) -> float | None:
    return None if v is None else round(v, nd)


# ---- 側風 ----


def crosswind_kt(
    speed_kt: float | None, wdir: float | None, runways: Sequence[Runway]
) -> float | None:
    """所有跑道（每條兩個方向）裡最小的側風分量；沒有風向時＝風速本身，沒有跑道時回 None。"""
    if speed_kt is None or not runways:
        return None
    if wdir is None:
        return float(speed_kt)
    return min(speed_kt * abs(sin(radians(wdir - h))) for r in runways for h in r.headings)


def crosswind_level(xw_kt: float | None, th: Thresholds) -> str | None:
    if xw_kt is None:
        return None
    if xw_kt >= th.crosswind_high_kt:
        return "high"
    if xw_kt >= th.crosswind_medium_kt:
        return "medium"
    return "low"


def _gusty_kt(wind_kt: float | None, gust_kt: float | None) -> float | None:
    return gust_kt if gust_kt is not None else wind_kt


def _max(vals: Iterable[float | None]) -> float | None:
    return max((v for v in vals if v is not None), default=None)


# ---- 官方：TAF ----


def taf_level(wind_kt: float | None, gust_kt: float | None, th: Thresholds) -> str:
    g = gust_kt or 0
    w = wind_kt or 0
    if g >= th.taf_high_gust_kt or w >= th.taf_high_wind_kt:
        return "high"
    if g >= th.taf_medium_gust_kt:
        return "medium"
    return "low"


def taf_for_slot(
    periods: Sequence[TafPeriod],
    now: datetime,
    start: datetime,
    end: datetime,
    th: Thresholds,
    runways: Sequence[Runway] = (),
) -> dict | None:
    """該格內所有 TAF 時段（主時段、TEMPO、PROB30／40）的最大風、最大陣風與最大側風；`kind` 記等級
    最高的那一種時段（同級取陣風較大的）。等級＝陣風規則與側風規則取較高者。
    只算在 `now` 之後還有效的時段（`end > now`，HD7）；沒有任何這樣的時段重疊回 None。"""
    hits = [p for p in periods if p.start < end and p.end > start and p.end > now]
    if not hits:
        return None

    def xw(p: TafPeriod) -> float | None:
        return crosswind_kt(_gusty_kt(p.wind_kt, p.gust_kt), p.wdir, runways)

    def period_level(p: TafPeriod) -> str | None:
        return max_level([taf_level(p.wind_kt, p.gust_kt, th), crosswind_level(xw(p), th)])

    wind = _max(p.wind_kt for p in hits)
    gust = _max(p.gust_kt for p in hits)
    cross = _max(xw(p) for p in hits)
    worst = max(
        hits,
        key=lambda p: (rank(period_level(p)), p.gust_kt or 0, p.wind_kt or 0, p.kind == "main"),
    )
    return {
        "windKt": wind,
        "gustKt": gust,
        "kind": worst.kind,
        "level": max_level([taf_level(wind, gust, th), crosswind_level(cross, th)]),
        "crosswindKt": _round(cross, 1),
    }


def metar_crosswind(metar: Metar | None, now: datetime, runways: Sequence[Runway]) -> float | None:
    """METAR 的側風；觀測超過 `METAR_MAX_AGE_H` 小時就不算。"""
    if metar is None or metar.observed is None:
        return None
    if now - metar.observed > timedelta(hours=METAR_MAX_AGE_H):
        return None
    return crosswind_kt(_gusty_kt(metar.wind_kt, metar.gust_kt), metar.wdir, runways)


# ---- 模式 ----


EC_KEYS = (
    "p10",
    "p15",
    "p25",
    "p29Kt",
    "p37Kt",
    "p49Kt",
    "hresGustMs",
    "hresGustKt",
    "crosswindKt",
)
# 系集機率的節欄位 ← ECMWF 的 m/s 門檻欄位（15 m/s ≈ 29.2 節、25 m/s ≈ 48.6 節）
EC_PROB_KT = {"p29Kt": "p15", "p49Kt": "p25"}


def fill_kt(ec: dict, gfs: dict) -> None:
    """節的欄位是空的、但對應的 m/s 欄位有值時補上（HD2 以前的結果被沿用時只有 m/s 欄位）。"""
    for kt, ms in EC_PROB_KT.items():
        if ec.get(kt) is None and ec.get(ms) is not None:
            ec[kt] = ec[ms]
    ec.setdefault("p37Kt", None)
    for d, kt, ms in ((ec, "hresGustKt", "hresGustMs"), (gfs, "gustKt", "gustMs")):
        if d.get(kt) is None and d.get(ms) is not None:
            d[kt] = _round(ms_to_kt(d[ms]), 1)


def ec_for_slot(
    point: EcmwfPoint | None, start: datetime, end: datetime, runways: Sequence[Runway] = ()
) -> dict:
    """`hresGustMs`／`p10`／`p15`／`p25` 是契約的舊欄位（m/s 與 ECMWF 的 m/s 門檻），照出；
    HD2 加 `hresGustKt` 與 `p29Kt`（＝`p15`）、`p37Kt`（沒有來源，一律 None）、
    `p49Kt`（＝`p25`）。"""
    out: dict[str, float | None] = dict.fromkeys(EC_KEYS)
    if point is None:
        return out
    hits = [g for g in point.hres if g.gust_kt is not None and start < g.end <= end]
    gust = _max(g.gust_kt for g in hits)
    out["hresGustMs"] = _round(kt_to_ms(gust), 1)
    out["hresGustKt"] = _round(gust, 1)
    out["crosswindKt"] = _round(_max(crosswind_kt(g.gust_kt, g.wdir, runways) for g in hits), 1)
    windows = [w for w in point.ens if w.start <= start and w.end >= end]
    for key in ("p10", "p15", "p25"):
        vals = [getattr(w, key) for w in windows if getattr(w, key) is not None]
        out[key] = _round(min(vals), 2) if vals else None
    for kt, ms in EC_PROB_KT.items():
        out[kt] = out[ms]
    return out


def gfs_for_slot(
    points: Sequence[GustPoint] | None,
    start: datetime,
    end: datetime,
    runways: Sequence[Runway] = (),
) -> dict:
    hits = [p for p in points or [] if p.gust_kt is not None and start <= p.valid <= end]
    gust = _max(p.gust_kt for p in hits)
    return {
        "gustMs": _round(kt_to_ms(gust), 1),
        "gustKt": _round(gust, 1),
        "crosswindKt": _round(_max(crosswind_kt(p.gust_kt, p.wdir, runways) for p in hits), 1),
    }


def gust_level(gust_kt: float | None, th: Thresholds) -> str | None:
    if gust_kt is None:
        return None
    if gust_kt >= th.model_high_gust_kt:
        return "high"
    if gust_kt >= th.model_medium_gust_kt:
        return "medium"
    return "low"


def _model_gust_level(ec: dict, gfs: dict, th: Thresholds) -> str:
    """確定性陣風（HRES、GFS）決定中、高；系集只看 `p49Kt` 進高（沒有 37 節的機率）。"""
    p49 = ec.get("p49Kt")
    high_by_ens = p49 is not None and p49 >= th.ec_p49_high
    gust = max_level(gust_level(v, th) for v in (ec.get("hresGustKt"), gfs.get("gustKt")))
    return "high" if high_by_ens else gust or "low"


def model_level(ec: dict, gfs: dict, th: Thresholds) -> str | None:
    """陣風規則與兩個模式的側風規則取較高者；完全沒有模式資料回 None。"""
    keys = (
        ec.get("p10"),
        ec.get("p29Kt"),
        ec.get("p49Kt"),
        ec.get("hresGustKt"),
        gfs.get("gustKt"),
    )
    if all(v is None for v in keys):
        return None
    return max_level(
        [
            _model_gust_level(ec, gfs, th),
            crosswind_level(ec.get("crosswindKt"), th),
            crosswind_level(gfs.get("crosswindKt"), th),
        ]
    )


def agreement(ec: dict, gfs: dict, th: Thresholds) -> str | None:
    a, b = gust_level(ec.get("hresGustKt"), th), gust_level(gfs.get("gustKt"), th)
    if a is None or b is None:
        return None
    return "agree" if a == b else "disagree"


# ---- 組合 ----


def assess_slots(
    *,
    now: datetime,
    slots: Sequence[tuple[datetime, datetime]],
    thresholds: Thresholds,
    ec: EcmwfPoint | None,
    gfs: Sequence[GustPoint] | None,
    taf_periods: Sequence[TafPeriod] | None,
    warnings: Sequence[ActiveWarning],
    confirmed: Sequence[ConfirmedPeriod],
    runways: Sequence[Runway] = (),
    metar: Metar | None = None,
) -> list[dict]:
    """單一機場的所有格。`taf_periods`／`ec`／`gfs`／`metar` 是 None 代表該來源失敗或沒資料。"""
    official_until = now + timedelta(hours=OFFICIAL_HORIZON_H)
    warning_until = now + timedelta(hours=WARNING_HORIZON_H)
    metar_xw = metar_crosswind(metar, now, runways)
    out = []
    for start, end in slots:
        ec_v = ec_for_slot(ec, start, end, runways)
        gfs_v = gfs_for_slot(gfs, start, end, runways)
        m_level = model_level(ec_v, gfs_v, thresholds)
        model = {
            "ec": ec_v,
            "gfs": gfs_v,
            "level": m_level,
            "agreement": agreement(ec_v, gfs_v, thresholds),
        }

        official = None
        if start < official_until:
            taf = taf_for_slot(taf_periods or [], now, start, end, thresholds, runways)
            applied = [w for w in warnings if start < warning_until]
            if taf is not None or applied:
                official = taf or {
                    "windKt": None,
                    "gustKt": None,
                    "kind": None,
                    "level": None,
                    "crosswindKt": None,
                }
                if metar_xw is not None and start <= now < end:
                    official["crosswindKt"] = _round(_max([official["crosswindKt"], metar_xw]), 1)
                official["level"] = max_level(
                    [
                        official["level"],
                        crosswind_level(official["crosswindKt"], thresholds),
                        *(w.level for w in applied),
                    ]
                )
                official["warnings"] = [w.kind for w in applied]
                if taf is None:
                    official["kind"] = "warning"

        if official is not None:
            level, basis = official["level"], "official"
        elif m_level is not None:
            level, basis = m_level, "model"
        else:
            level, basis = "unknown", "none"

        if any(c.start < end and c.end > start for c in confirmed):
            level, basis = "confirmed", "confirmed"

        gap = official is not None and m_level is not None and official["level"] != m_level
        out.append(
            {
                "from": iso(start),
                "to": iso(end),
                "level": level,
                "basis": basis,
                "official": official,
                "model": model,
                "gap": gap,
            }
        )
    return out
