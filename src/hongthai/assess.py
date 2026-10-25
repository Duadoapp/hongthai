"""判讀：把各來源的資料對到 6 小時格，依規格的等級規則算等級。全部是純函式。

規格（Duado `docs/spec.md`「16. HongThai」，初版、保守，之後用實際紀錄校準）。HD2（2026-10-19）起
風速一律用節（1 m/s = 1.943844 節），模式陣風解析完就換算成節：
- 模式：HRES 或 GFS 陣風 ≥ 48 節、或 EC 系集「陣風 ≥ 25 m/s（≈ 48.6 節）」機率 ≥ 30%
  （`p49Kt`）→ 高；HRES 或 GFS 陣風 ≥ 37 節 → 中；其他低。中級**不用系集**：ECMWF 開放資料的
  機率產品只有 ≥ 10／15／25 m/s（≈ 19.4／29.2／48.6 節），沒有 37 節的（`p37Kt` 一律 `null`，
  之後用 GEFS 系集成員自己算）；`p29Kt`（＝`p15`）只輸出、不進規則
- 官方（只看 0–30 小時）：天文台／SMG 8 號或以上 → 高，3 號 → 中；氣象署陸上颱風警報且機場在警戒區
  → 高，海上警報 → 中；NWS（關島，HD3）Typhoon／Tropical Storm Warning → 高、Watch → 中
  （對照在 `sources/nws.py`）；JMA（日本與沖繩，HD9）大雪特別警報、暴風雪特別警報（HD16）→ 高、
  大雪警報 → 中、暴風雪警報低（只列出），算 `snow`（對照在 `sources/jma.py`）；
  TAF 該時段陣風 ≥ 48 節（或平均風 ≥ 35 節）→ 高，陣風 ≥ 37 節 → 中
- 陣風門檻（TAF 與模式同一套）的依據：桃園機場空橋規則，最大瞬間風速 37 節（蒲福 8 級）啟動
  空橋防護、48 節（10 級）空橋停用、55 節以上全部綁死
- 0–30 小時以官方為準；官方與模式差一級以上標「落差」（`gap`）
- 一致性：HRES 與 GFS 的陣風落在同一級＝一致（`agree`）
- `confirmed.json` 有時段的格 → `confirmed`
- 所有機場先用同一套門檻（`config.Thresholds` 的預設值），之後找到個別機場的作業標準再在
  `airports.json` 的 `thresholds` 覆寫

本模組自己的約定（規格沒寫死的地方）：
- 「0–30 小時」：格的開始時間早於「現在 + 30 小時」
- 目前生效的警報（天文台／SMG 信號、氣象署颱風警報、NWS 警報、JMA 警報）套用到開始時間早於
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
  而且只在該格本來就有官方資料（TAF、警報，或下面 HD13 的「沒有 TAF 的機場由 METAR 撐起」）時

已經過去的 TAF 時段（HD7，2026-10-19）：
- TAF 只算「結束時間在現在之後」的時段（主時段、TEMPO、BECMG、PROB 都一樣）；只會影響現在所在的
  第一格。跨過現在的時段照算（還沒結束）
- 第一格裡的 TAF 時段全部已經過去時，這格當作沒有 TAF：有警報走「只有警報」的路（METAR 側風照上面
  的規則算進去），沒有警報就沒有官方層（TAF 全部過去代表那份 TAF 已經過期，跟沒有 TAF 一樣）
- 起因：關島 2026-10-19T03:57Z 那報，第一格被一段 02–03Z（產出前就結束）的 TEMPO 陣風 46 節判成高
- 模式：HRES 的 `10u`／`10v` 只抓 6 小時整的步長（00／06／12／18Z，H10 起，為了減少下載量），
  每個陣風區間配**區間結束時間往後最近**的那個 6 小時步長的風向（例如結束在 09Z 的 3 小時區間配
  12Z 的風）；GFS 用同一時間點的 `UGRD`／`VGRD`。一格取格內最大的側風（時間上取最壞、跑道上取最好）

新天氣種類（第五階段，HD8；Shawn 2026-10-19 定案，門檻先上線、累積一個月紀錄再調）：
- 三類：`rain`（大雨＋雷雨）、`snow`（大雪＋結冰）、`fog`（濃霧＋低雲幕）；颱風帶來的雨歸
  `wind`（現有規則）。**燈號還是一種「停飛風險」等級**：一層的等級＝風（陣風、側風、風的警報）
  與三類取最高；種類只進每格的 `causes`、預覽圖小字與 AI 短評。原則：貼近實際會停飛的情況，
  只會延誤的不升級
- 官方層（TAF 各時段與 METAR；HD7 的「還有效且重疊」的時段；METAR 只進第一格、觀測 3 小時內、
  而且該格有 TAF 或由 METAR 撐起（HD13，見下）——只有警報的格 `wx` 是 null，METAR 的天氣不算）。
  每個時段各自判（TS 和能見度要在同一時段）：
  - `rain`：天氣現象含 `GR`（TSGR、+TSGR、GR、SHGR，冰雹）→ 高；`+TS` 開頭且含 `RA`（+TSRA）
    → 中；含 `TS` 且該時段能見度 ≤ 1600 公尺 → 中；其他（TS、TSRA、SHRA、+SHRA）低
  - `snow`：含 `FZRA`、`FZDZ`、`PL`（任何強度）→ 高；`+` 開頭且含 `SN`（+SN、+SHSN）→ 高；
    含 `SN`、不是 `-`／`+` 開頭（SN、SHSN、RASN；BLSN 也算）且能見度 ≤ 1600 公尺 → 中；
    -SN 低。FZFG 不在這裡
  - `fog`：能見度 < 400 公尺或雲底 ≤ 100 呎 → 高；< 1000 公尺或 ≤ 200 呎 → 中（任何原因的
    低能見度都算）；沒報的不算
- 模式層（每格）：
  - `rain`：HRES 或 GFS 6 小時雨量 ≥ 60 mm → 高；≥ 30 mm，或 EC 系集 24 小時雨量 ≥ 50 mm
    的機率 ≥ 30%（`p24hRain50`，24 小時窗取包住這格的最小值，同 `p49Kt`）→ 中
  - `snow`：降水型態是 `snow`／`wet_snow`／`rain_snow` 且 6 小時水當量 ≥ 10 mm → 高、
    ≥ 5 mm → 中；`freezing_rain`／`freezing_drizzle`／`ice_pellets` 且 ≥ 1 mm → 高。
    EC、GFS 各自算、取較高
  - `fog`：只有 GFS 能見度（EC 開放資料沒有能見度），門檻同官方，但**最高只到中**（HD10，
    Shawn 2026-10-19）：< 1000 公尺 → 中，< 400 公尺也只是中。到高要官方層（TAF／METAR）真的
    報霧或低雲幕。理由：GFS 能見度不準、又只有一個模式沒有對照（釜山 06:56Z 那報兩格只靠 GFS
    能見度 308 公尺、幾乎沒雨就判高），大雨時也會被壓得很低（花蓮、台東 76–92 公尺，同時 6 小時
    雨量 63–174 mm）
  - 一格的雨量、降水型態是「格結束時間」那個時間點的（EC 是 `tp` 差、GFS 是前 6 小時那桶）；
    GFS 能見度取格頭尾兩個時間點的最小值
  - `model.agreement` **還是只看陣風**（值域不變）
- 警報：天文台黑雨 → 中，紅雨、雷暴警告低（只列出）；氣象署大豪雨、超大豪雨特報且機場在範圍
  → 中。這幾種算 `rain`（`RAIN_WARNING_KINDS`）；氣象署濃霧特報且機場在範圍 → 中，算 `fog`
  （`FOG_WARNING_KINDS`，HD13）；JMA 大雪特別警報、暴風雪特別警報（HD16）→ 高、大雪警報 → 中、
  暴風雪警報低（只列出），算 `snow`（`SNOW_WARNING_KINDS`，HD9）；JMA 大雨警報（含危険、特別警報）
  低（只列出），算 `rain`；JMA 暴風警報、暴風特別警報與氣象署陸上強風特報低（只列出，HD27），
  和其他警報一樣算 `wind`。HD29 經 WMO SWIC 的中國氣象局、韓國氣象廳、PAGASA 警報全部低（只列出）：
  暴雨、豪雨算 `rain`，大霧算 `fog`，大雪算 `snow`，颱風、大風、強風、風球算 `wind`。
  **低的警報不會自己撐起官方層**：一格沒有 TAF、只有低的警報時 `official` 是 null、退回模式
  （天文台 1 號信號也是低，HD8 起一樣照這條）；有 TAF 或有中以上的警報時，`official.warnings`
  列全部（含低的）
- `causes`：從決定 `level` 的那一層（`official` 或 `model`；`confirmed` 看被它蓋掉的那一層：
  有官方層就是官方層）把等級 ≥ 中的種類列出——`wind`、`rain`、`snow`、`fog`；等級高的在前，
  同級照 `wind`、`snow`、`fog`、`rain` 的固定順序（`CAUSE_ORDER`），第一個就是主因；
  都低是 `[]`，`unknown` 是 `[]`。依據是模式層時（霧只來自 GFS 能見度、官方層沒有霧）同級改成
  `wind`、`snow`、`rain`、`fog`（`MODEL_CAUSE_ORDER`，HD10）：模式的低能見度常是大雨造成的，
  主因寫雨

沒有 TAF 的機場（HD13，Shawn 2026-10-19「金馬照建議」）：
- 機場完全沒有 TAF（`taf_periods` 是 None 或空的）、METAR 在 3 小時內（`metar_fresh`）、而且風、
  能見度、雲幕、天氣至少有一樣（`metar_has_data`；氣象署觀測全部缺測時不算）→ **第一格**的
  官方層由 METAR 組成：`kind: "metar"`，`windKt`／`gustKt`／`crosswindKt`／`wx` 都從 METAR 來，
  等級＝METAR 的風（TAF 的陣風規則）、側風、三類取最高，警報照舊疊上去。之後的格照舊（只有中以上的
  警報才有官方層，不然退回模式）
- 有 TAF 的機場完全不受影響（TAF 全部過去的也一樣——那是 HD7 的「當作沒有 TAF」，不走這條）
- 會用到的：金門、馬祖（METAR 是氣象署局屬站觀測，`sources/cwa.py`）與宮古（AviationWeather 有
  METAR 沒 TAF）；花蓮等六個連 METAR 也沒有的機場不變

多模式投票（HD14，Shawn 2026-10-19 定案）——上面「模式」那幾條改成每個模式各自判、再投票：
- 五票（`config.MODELS`）：IFS（HRES）、GFS、IFS 系集、AIFS、AIGFS，每個一筆 `models[]`
  （`model_entries`），權重相同。每一類各自投（`vote`）：某等級 L 的票＝等級 ≥ L 的模式數，
  票數 × 2 ≥ 分母就成立，取成立的最高；分母＝這一類有資料（不是 None）的模式。四類再取最高＝
  `model.level`
- IFS 系集只投「高」（`Model.votes_only_high`）：`p49Kt` ≥ `ecP49High` 投高、否則投低，判中時不算
  分母。所以系集單獨撐不起高（HD14 以前可以）
- AIFS、AIGFS 沒有陣風：10 米平均風 × 係數 G＝估算陣風，側風也用它（`estimated_for_slot`）。
  HD18 起 G 是每個機場自己的（`GustFactor`，由 `gustfactor.py` 從 30 天的「陣風÷平均風」算出，
  HD19 起只用 IFS 的樣本；`build` 交進來）；`models[]` 每筆多 `windKt`（10 米平均風：IFS 是格結束
  步長的、GFS 是格內陣風最大那一點的、AIFS／AIGFS 是估算陣風用的那個，系集 null）與
  `gustFactor`／`gustFactorBasis`（只有估算的那幾筆有）
- IFS、GFS 三類的等級就是 `model.ec`／`model.gfs` 的（值照舊）；IFS 的雨含系集 24 小時雨量機率。
  AIFS、AIGFS 的雨用 6 小時雨量；雪只有有降水型態的模式投（AIGFS 的 `ptype` 永遠 None → 不投）；
  霧只有 GFS（分母 1）
- `model.agreement` 照舊只看 IFS 與 GFS 的陣風；`causes` 依據是模式層時用投票後各類的等級

Open-Meteo 三票與旁觀模式（HD16，Shawn 2026-10-20 19:04 定案）——五票變**八票**：
- ICON（`icon`，有陣風）、JMA GSM（`jma`，Open-Meteo 沒有陣風 → 估算）：逐時資料換成格
  （`hourly_for_slot`）：陣風取格內「前一小時最大陣風」的最大（(from, to] 的小時）、風向與平均風
  用同一個小時的；估算的（JMA）同 AIFS：格頭尾含在內的小時裡最大的平均風 × G；6 小時雨量是
  (from, to] 逐時加總；型態看降雪水當量與天氣碼（`openmeteo.slot_ptype`）→ 兩個都投雨、雪；
  能見度兩個都沒有（2026-10-20 實抓全是 null），霧的分母還是只有 GFS
- WeatherNext 2 系集（`wn2-ens`）比照 IFS 系集只投高（`ensemble_for_slot`）：64 個成員各自取格頭尾
  兩個時間點大的 10 米風 × 機場的 G＝估算陣風，≥ `modelHighGustKt` 的成員比例（`p49Kt`，兩位小數；
  沒有值的成員不算分母）≥ `ecP49High` 投高、否則投低；不投雨、雪、霧。那筆的 `windKt`／`gustKt`
  是中位數（64 個成員格內最大風的中位數，`gustKt`＝它 × G，`gustEstimated: true`）
- `models[]` 每筆多 `p49Kt`：只有 WN2 系集那筆有值（成員比例），其他筆一律 null（IFS 系集的機率
  照舊在 `model.ec.p49Kt`）
- 旁觀模式（`Model.voting=False`，`NON_VOTING`）：`models[]` 照常寫（`levels`、`level` 都算），但
  `vote`／`tally`／`model_vote` 一律跳過，不算任何一類的分母、不投票，`vote.total` 不含它。
  HD16 的三票都投票；這個開關給 HD15 的 WeatherNext 3 與之後的新模式
- G 一律是 HD19 的（IFS 樣本）；新模式不進樣本（`gustfactor.py`）。這三個模式不沿用舊資料

HD33b 的三個旁觀模式（`gem` ECCC GEM、`arpege` Météo-France ARPEGE、`cma` CMA GRAPES，都經
Open-Meteo、`voting=False`；UKMO 是 CC BY-SA 4.0，不放）：數字與 `levels` 同 ICON
（`hourly_for_slot`，有陣風；`config` 標 `gust_estimated` 的才估算），`vote`／`level`／`causes`
完全不受影響；不給 AI 短評（`ai_hidden`）。**旁觀模式不判霧**：等級只算風（陣風、側風）、雨、雪；
CMA 的能見度照存 `visibilityM`，不進 `levels.fog`／`level`（2026-10-25 主對話定案）

WeatherNext 3（HD15，`wn3`）：只有 `config.WN3_MODE` 是 `observe` 時才在 `MODELS` 裡（預設
`report-only`，`latest.json` 沒有它）。數字是逐時的成員中位數（p50）10 米風，同 JMA GSM 估算陣風
（`wn3_for_slot`），雨量照投；沒有降水型態（不投雪）、沒有能見度。那筆多 `windKtP90`（格內最大的
p90 平均風，給報告看離散）。`voting` 預設 False（旁觀），環境變數 `WN3_VOTING=1` 才投
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import radians, sin
from statistics import median

from .config import GUST_FACTOR_DEFAULT, MODELS, ConfirmedPeriod, Model, Runway, Thresholds
from .sources.aifs import AifsStep
from .sources.aigfs import AigfsStep
from .sources.ecmwf import EcmwfPoint, PrecipStep
from .sources.gfs import GustPoint
from .sources.openmeteo import EnsStep, OmHour, member_winds, rain_sum, slot_ptype
from .sources.taf import Metar, TafPeriod
from .sources.wn3 import Wn3Hour
from .timeutil import iso
from .units import kt_to_ms, ms_to_kt

LEVELS = ("low", "medium", "high")
OFFICIAL_HORIZON_H = 30
WARNING_HORIZON_H = 12
METAR_MAX_AGE_H = 3
CAUSES = ("wind", "rain", "snow", "fog")
CAUSE_ORDER = ("wind", "snow", "fog", "rain")  # 同級時的順序
MODEL_CAUSE_ORDER = ("wind", "snow", "rain", "fog")  # 依據是模式層時（HD10）
# 算 `rain` 的警報種類；其他（颱風、熱帶氣旋信號……）算 `wind`
RAIN_WARNING_KINDS = frozenset(
    {
        "rainstorm_black",
        "rainstorm_red",
        "thunderstorm",
        "cwa_heavy_rain",
        # HD27：JMA 大雨警報（只列出，low）
        "jma_heavy_rain",
        "jma_heavy_rain_danger",
        "jma_heavy_rain_emergency",
        # HD29：中國氣象局暴雨、韓國氣象廳豪雨、PAGASA 豪雨紅色（經 SWIC，只列出，low）
        "cma_rainstorm_red",
        "cma_rainstorm_orange",
        "kma_heavy_rain_warning",
        "pagasa_rainfall_red",
    }
)
# 算 `fog` 的警報種類（HD13；HD29 加中國氣象局大霧，只列出）
FOG_WARNING_KINDS = frozenset({"cwa_dense_fog", "cma_fog_red", "cma_fog_orange"})
# 算 `snow` 的警報種類（HD9；HD16 加暴風雪特別警報；HD29 加韓國氣象廳大雪警報，只列出）
SNOW_WARNING_KINDS = frozenset(
    {
        "jma_heavy_snow",
        "jma_heavy_snow_emergency",
        "jma_snowstorm",
        "jma_snowstorm_emergency",
        "kma_heavy_snow_warning",
    }
)
SNOWY_PTYPES = frozenset({"snow", "wet_snow", "rain_snow"})
# `slots[].model.models[]` 每筆的數字欄位（HD14）
MODEL_NUM_KEYS = ("gustKt", "crosswindKt", "rain6hMm", "ptype", "visibilityM")
ONLY_HIGH = frozenset(m.id for m in MODELS if m.votes_only_high)
ESTIMATED = frozenset(m.id for m in MODELS if m.gust_estimated)
WN3_ID = "wn3"  # HD15：只有 `observe` 模式才在 `MODELS` 裡
ENS_ID = "ifs-ens"  # IFS 系集：機率從 `model.ec` 來（其他只投高的模式從自己那筆的 `p49Kt`，HD16）
FREEZING_PTYPES = frozenset({"freezing_rain", "freezing_drizzle", "ice_pellets"})


@dataclass(frozen=True)
class GustFactor:
    """估算陣風的係數（HD18）：`g`（兩位小數）與 `basis`（`airport30d`／`all30d`／`run`／
    `default`，見 `gustfactor.py`）。"""

    g: float
    basis: str


DEFAULT_GUST_FACTOR = GustFactor(GUST_FACTOR_DEFAULT, "default")


@dataclass(frozen=True)
class ActiveWarning:
    """目前生效的官方警報（天文台／SMG 信號、氣象署颱風警報、NWS 與 JMA 警報、HD29 經 SWIC 的
    中國氣象局、韓國氣象廳、PAGASA 警報），給判讀與輸出用。"""

    source: str  # hko／cwa／smg／nws／jma；HD29：cma／kma／pagasa
    # tc_signal／typhoon_land／typhoon_sea／typhoon_warning／typhoon_watch／ts_warning／ts_watch；
    # HD8：rainstorm_black／rainstorm_red／thunderstorm／cwa_heavy_rain；HD13：cwa_dense_fog；
    # HD9：jma_heavy_snow／jma_heavy_snow_emergency／jma_snowstorm；HD16：jma_snowstorm_emergency
    # HD27（只列出，low）：jma_storm／jma_storm_emergency／jma_heavy_rain／jma_heavy_rain_danger／
    # jma_heavy_rain_emergency／cwa_strong_wind
    # HD29（只列出，low，`sources/swic.py` 的 `KINDS`）：cma_typhoon_<顏色>／cma_gale_<顏色>／
    # cma_rainstorm_<顏色>／cma_fog_<顏色>／kma_typhoon_warning／kma_typhoon_advisory／
    # kma_strong_wind_warning／kma_strong_wind_advisory／kma_heavy_rain_warning／
    # kma_heavy_snow_warning／pagasa_tcws_<1–5>／pagasa_rainfall_red
    kind: str
    level: str
    text: dict[str, str]
    issued_at: str | None
    code: str | None = None  # 天文台／SMG 信號代碼（例如 TC8NE）、NWS 的 event、JMA 的種類代碼
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


def warning_cause(kind: str) -> str:
    if kind in FOG_WARNING_KINDS:
        return "fog"
    if kind in SNOW_WARNING_KINDS:
        return "snow"
    return "rain" if kind in RAIN_WARNING_KINDS else "wind"


def causes_from(levels: dict[str, str | None], order: Sequence[str] = CAUSE_ORDER) -> list[str]:
    """各種類的等級 → `causes`：≥ 中的，等級高的在前、同級照 `order`。"""
    hits = [c for c in order if rank(levels.get(c)) >= 1]
    return sorted(hits, key=lambda c: -rank(levels[c]))  # sorted 是穩定的，同級維持固定順序


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


def taf_hits(
    periods: Sequence[TafPeriod], now: datetime, start: datetime, end: datetime
) -> list[TafPeriod]:
    """和這格重疊、而且在 `now` 之後還有效的 TAF 時段（HD7）。"""
    return [p for p in periods if p.start < end and p.end > start and p.end > now]


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
    hits = taf_hits(periods, now, start, end)
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


# ---- 官方：天氣現象（HD8）----


def rain_wx_level(wx: Sequence[str], vis_m: float | None, th: Thresholds) -> str:
    if any("GR" in w for w in wx):
        return "high"
    if any(w.startswith("+TS") and "RA" in w for w in wx):
        return "medium"
    if any("TS" in w for w in wx) and vis_m is not None and vis_m <= th.taf_rain_medium_vis_m:
        return "medium"
    return "low"


def snow_wx_level(wx: Sequence[str], vis_m: float | None, th: Thresholds) -> str:
    if any(k in w for w in wx for k in ("FZRA", "FZDZ", "PL")):
        return "high"
    if any(w.startswith("+") and "SN" in w for w in wx):
        return "high"
    moderate = any("SN" in w and not w.startswith(("-", "+")) for w in wx)
    if moderate and vis_m is not None and vis_m <= th.taf_snow_medium_vis_m:
        return "medium"
    return "low"


def fog_level(vis_m: float | None, ceiling_ft: float | None, th: Thresholds) -> str | None:
    """能見度與雲底都沒報回 None。"""
    if vis_m is None and ceiling_ft is None:
        return None
    if (vis_m is not None and vis_m < th.fog_high_vis_m) or (
        ceiling_ft is not None and ceiling_ft <= th.fog_high_ceiling_ft
    ):
        return "high"
    if (vis_m is not None and vis_m < th.fog_medium_vis_m) or (
        ceiling_ft is not None and ceiling_ft <= th.fog_medium_ceiling_ft
    ):
        return "medium"
    return "low"


def official_wx(items: Sequence[TafPeriod | Metar], th: Thresholds) -> dict:
    """一格的 TAF 時段（加第一格的 METAR）→ `official.wx`：現象（去重、照出現順序）、最小能見度、
    最低雲底、三類等級（每個時段各自判、取最高）。"""
    phenomena: list[str] = []
    for it in items:
        phenomena += [w for w in it.wx if w not in phenomena]
    vis = [it.vis_m for it in items if it.vis_m is not None]
    ceil = [it.ceiling_ft for it in items if it.ceiling_ft is not None]
    return {
        "phenomena": phenomena,
        "visibilityM": min(vis, default=None),
        "ceilingFt": min(ceil, default=None),
        "rain": max_level(rain_wx_level(it.wx, it.vis_m, th) for it in items) or "low",
        "snow": max_level(snow_wx_level(it.wx, it.vis_m, th) for it in items) or "low",
        "fog": max_level(fog_level(it.vis_m, it.ceiling_ft, th) for it in items) or "low",
    }


def metar_fresh(metar: Metar | None, now: datetime) -> bool:
    return (
        metar is not None
        and metar.observed is not None
        and now - metar.observed <= timedelta(hours=METAR_MAX_AGE_H)
    )


def metar_has_data(metar: Metar) -> bool:
    """風、陣風、能見度、雲幕、天氣現象至少有一樣（HD13：氣象署觀測可能全部缺測）。"""
    values = (metar.wind_kt, metar.gust_kt, metar.vis_m, metar.ceiling_ft)
    return any(v is not None for v in values) or bool(metar.wx)


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
    # HD8
    "rain6hMm",
    "ptype",
    "p24hRain25",
    "p24hRain50",
    "temp2mC",
    "rain",
    "snow",
)
# 系集降水機率的輸出欄位 ← `ProbWindow` 的屬性（HD8）
EC_PROB_RAIN = {"p24hRain25": "tp25", "p24hRain50": "tp50"}
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
    out: dict[str, float | str | None] = dict.fromkeys(EC_KEYS)
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
    for key, attr in EC_PROB_RAIN.items():
        vals = [getattr(w, attr) for w in windows if getattr(w, attr) is not None]
        out[key] = _round(min(vals), 2) if vals else None
    pre: PrecipStep | None = next((p for p in point.precip if p.valid == end), None)
    if pre is not None:
        out["rain6hMm"] = _round(pre.rain6h_mm, 1)
        out["ptype"] = pre.ptype
        out["temp2mC"] = _round(pre.temp2m_c, 1)
    return out


def ec_wind_for_slot(point: EcmwfPoint | None, start: datetime, end: datetime) -> float | None:
    """IFS 一格的 10 米平均風（節，HD18）：格結束那個 6 小時整步長的 `10u`／`10v`（和風向同一個
    時間點；格內每個陣風區間配的都是它，取結束最晚那個區間的）。"""
    hits = [g for g in point.hres if start < g.end <= end] if point is not None else []
    winds = [g.wind_kt for g in sorted(hits, key=lambda g: g.end) if g.wind_kt is not None]
    return _round(winds[-1], 1) if winds else None


def gfs_wind_for_slot(
    points: Sequence[GustPoint] | None, start: datetime, end: datetime
) -> float | None:
    """GFS 一格的 10 米平均風（節，HD18）：格內時間點裡陣風最大那一點的（同樣大取先的）。"""
    hits = [p for p in points or [] if start <= p.valid <= end and p.gust_kt is not None]
    if not hits:
        return None
    return _round(max(hits, key=lambda p: p.gust_kt or 0).wind_kt, 1)


def gfs_for_slot(
    points: Sequence[GustPoint] | None,
    start: datetime,
    end: datetime,
    runways: Sequence[Runway] = (),
) -> dict:
    inside = [p for p in points or [] if start <= p.valid <= end]
    hits = [p for p in inside if p.gust_kt is not None]
    gust = _max(p.gust_kt for p in hits)
    last = next((p for p in inside if p.valid == end), None)
    vis = min((p.vis_m for p in inside if p.vis_m is not None), default=None)
    return {
        "gustMs": _round(kt_to_ms(gust), 1),
        "gustKt": _round(gust, 1),
        "crosswindKt": _round(_max(crosswind_kt(p.gust_kt, p.wdir, runways) for p in hits), 1),
        # HD8：雨量與型態用格結束那個時間點（前 6 小時那桶）、能見度取格內最小
        "rain6hMm": _round(last.rain6h_mm, 1) if last else None,
        "ptype": last.ptype if last else None,
        "visibilityM": None if vis is None else round(vis),
        "rain": None,
        "snow": None,
        "fog": None,
    }


def gust_level(gust_kt: float | None, th: Thresholds) -> str | None:
    if gust_kt is None:
        return None
    if gust_kt >= th.model_high_gust_kt:
        return "high"
    if gust_kt >= th.model_medium_gust_kt:
        return "medium"
    return "low"


def _num(v: object) -> float | None:
    return v if isinstance(v, int | float) and not isinstance(v, bool) else None


def rain_model_level(mm6h: object, th: Thresholds) -> str | None:
    mm = _num(mm6h)
    if mm is None:
        return None
    if mm >= th.model_rain_high_mm6h:
        return "high"
    if mm >= th.model_rain_medium_mm6h:
        return "medium"
    return "low"


def snow_model_level(mm6h: object, ptype: object, th: Thresholds) -> str | None:
    """雪（水當量）、凍雨的規則；沒有雨量回 None。"""
    mm = _num(mm6h)
    if mm is None:
        return None
    if ptype in FREEZING_PTYPES and mm >= th.model_freezing_rain_high_mm6h:
        return "high"
    if ptype in SNOWY_PTYPES:
        if mm >= th.model_snow_high_mm6h:
            return "high"
        if mm >= th.model_snow_medium_mm6h:
            return "medium"
    return "low"


def fog_model_level(vis_m: object, th: Thresholds) -> str | None:
    """GFS 能見度；門檻同官方，但封頂在中（HD10）。"""
    level = fog_level(_num(vis_m), None, th)
    return "medium" if level == "high" else level


def ec_rain_level(ec: dict, th: Thresholds) -> str | None:
    """HRES 6 小時雨量，或系集 24 小時 ≥ 50 mm 的機率 ≥ 30% → 中。"""
    by_rain = rain_model_level(ec.get("rain6hMm"), th)
    p50 = _num(ec.get("p24hRain50"))
    by_ens = None if p50 is None else ("medium" if p50 >= th.ec_p24h_rain50_medium else "low")
    return max_level([by_rain, by_ens])


def fill_model_wx(ec: dict, gfs: dict, th: Thresholds) -> None:
    """模式層每個模式的 `rain`／`snow`（GFS 加 `fog`）等級（輸出用，HD8）。"""
    ec["rain"] = ec_rain_level(ec, th)
    ec["snow"] = snow_model_level(ec.get("rain6hMm"), ec.get("ptype"), th)
    gfs["rain"] = rain_model_level(gfs.get("rain6hMm"), th)
    gfs["snow"] = snow_model_level(gfs.get("rain6hMm"), gfs.get("ptype"), th)
    gfs["fog"] = fog_model_level(gfs.get("visibilityM"), th)


def _wind_level(gust_kt: object, crosswind: object, th: Thresholds) -> str | None:
    """一個模式的風：陣風與側風（含陣風）取較高；兩個都沒有回 None。"""
    return max_level([gust_level(_num(gust_kt), th), crosswind_level(_num(crosswind), th)])


def estimated_gust(wind_kt: float | None, g: float) -> float | None:
    """估算陣風＝平均風（一位小數的那個）× G，一位小數（HD18；`_rescore` 也用這個，結果一樣）。"""
    return None if wind_kt is None else _round(wind_kt * g, 1)


def estimated_for_slot(
    steps: Sequence[AifsStep | AigfsStep] | None,
    start: datetime,
    end: datetime,
    runways: Sequence[Runway] = (),
    factor: GustFactor = DEFAULT_GUST_FACTOR,
) -> dict:
    """沒有陣風的模式（AIFS、AIGFS，HD14）一格的數字：平均風取格頭尾兩個時間點大的（`windKt`）、
    陣風＝它 × 機場的係數 G（估算，HD18）、側風用每個時間點的估算陣風算、雨量與型態用格結束那個
    時間點（同 GFS）。"""
    inside = [s for s in steps or [] if start <= s.valid <= end]
    winds = [(s.wind_kt, s.wdir) for s in inside if s.wind_kt is not None]
    wind = _round(_max(w for w, _ in winds), 1)
    last = next((s for s in inside if s.valid == end), None)
    return {
        "windKt": wind,
        "gustKt": estimated_gust(wind, factor.g),
        "gustFactor": factor.g,
        "gustFactorBasis": factor.basis,
        "crosswindKt": _round(_max(crosswind_kt(w * factor.g, d, runways) for w, d in winds), 1),
        "rain6hMm": _round(last.rain6h_mm, 1) if last else None,
        "ptype": last.ptype if last else None,
        "visibilityM": None,
    }


def hourly_for_slot(
    hours: Sequence[OmHour] | None,
    start: datetime,
    end: datetime,
    runways: Sequence[Runway] = (),
    factor: GustFactor | None = None,
) -> dict:
    """Open-Meteo 逐時資料（ICON、JMA GSM，HD16）一格的數字。`factor` 是 None：有陣風（ICON），
    取 (from, to] 小時裡前一小時最大陣風的最大，`windKt` 是同一小時的平均風、側風每小時用陣風與
    風向算再取大；給了 `factor`：估算（JMA），同 `estimated_for_slot`——[from, to] 小時裡最大的
    平均風 × G。雨量是 (from, to] 逐時加總、型態見 `openmeteo.slot_ptype`、能見度取 [from, to]
    的最小值。"""
    hours = hours or []
    inst = [h for h in hours if start <= h.valid <= end]
    prev = [h for h in hours if start < h.valid <= end]
    vis = min((h.vis_m for h in inst if h.vis_m is not None), default=None)
    rain = rain_sum(prev)
    out: dict[str, float | str | None] = {
        "rain6hMm": _round(rain, 1),
        "ptype": slot_ptype(prev),
        "visibilityM": None if vis is None else round(vis),
    }
    if factor is not None:
        winds = [(h.wind_kt, h.wdir) for h in inst if h.wind_kt is not None]
        wind = _round(_max(w for w, _ in winds), 1)
        return {
            "windKt": wind,
            "gustKt": estimated_gust(wind, factor.g),
            "gustFactor": factor.g,
            "gustFactorBasis": factor.basis,
            "crosswindKt": _round(
                _max(crosswind_kt(w * factor.g, d, runways) for w, d in winds), 1
            ),
            **out,
        }
    hits = [h for h in prev if h.gust_kt is not None]
    top = max(hits, key=lambda h: h.gust_kt or 0) if hits else None
    return {
        "windKt": _round(top.wind_kt, 1) if top else None,
        "gustKt": _round(top.gust_kt, 1) if top else None,
        "crosswindKt": _round(_max(crosswind_kt(h.gust_kt, h.wdir, runways) for h in hits), 1),
        **out,
    }


def ensemble_for_slot(
    steps: Sequence[EnsStep] | None,
    start: datetime,
    end: datetime,
    th: Thresholds,
    factor: GustFactor = DEFAULT_GUST_FACTOR,
) -> dict:
    """WeatherNext 2 系集（HD16）一格：每個成員取格頭尾兩個時間點大的 10 米風（一位小數）× G＝
    估算陣風，`p49Kt`＝估算陣風 ≥ `modelHighGustKt` 的成員比例（兩位小數）；`windKt` 是成員風的
    中位數、`gustKt`＝它 × G。沒有成員資料時全是 None。"""
    winds = [round(w, 1) for w in member_winds([s for s in steps or [] if start <= s.valid <= end])]
    if not winds:
        return {"windKt": None, "gustKt": None, "p49Kt": None}
    hit = sum((estimated_gust(w, factor.g) or 0) >= th.model_high_gust_kt for w in winds)
    wind = _round(median(winds), 1)
    return {
        "windKt": wind,
        "gustKt": estimated_gust(wind, factor.g),
        "gustFactor": factor.g,
        "gustFactorBasis": factor.basis,
        "p49Kt": round(hit / len(winds), 2),
    }


def wn3_for_slot(
    hours: Sequence[Wn3Hour] | None,
    start: datetime,
    end: datetime,
    runways: Sequence[Runway] = (),
    factor: GustFactor = DEFAULT_GUST_FACTOR,
) -> dict:
    """WeatherNext 3（HD15）一格：逐時的 p50 平均風當平均風，同 JMA GSM（`hourly_for_slot` 估算
    那條：[from, to] 小時裡最大的平均風 × G、雨量 (from, to] 加總）；**沒有降水型態**（`ptype`
    一律 None，所以不投雪）；`windKtP90` 是 [from, to] 小時裡最大的 p90 平均風（不乘 G）。"""
    hours = hours or []
    out = hourly_for_slot(
        [OmHour(h.valid, h.wind_kt, h.wdir, None, h.precip_mm, None, None, None) for h in hours],
        start,
        end,
        runways,
        factor,
    )
    out["ptype"] = None
    p90 = _max(h.wind_p90_kt for h in hours if start <= h.valid <= end)
    out["windKtP90"] = _round(p90, 1)
    return out


def refactor_estimated(entry: dict, factor: GustFactor) -> None:
    """沿用的 AIFS／AIGFS 那筆（HD18）：用抄來的 `windKt` × 這一報的 G 重算 `gustKt`，側風（和
    估算陣風成正比）照新舊 G 的比例換算。HD18 以前的那筆沒有 `windKt`／`gustFactor`：舊 G 當 1.4、
    平均風用舊的估算陣風倒推。沒有數字的不動。"""
    old_g = _num(entry.get("gustFactor")) or GUST_FACTOR_DEFAULT
    wind, gust = _num(entry.get("windKt")), _num(entry.get("gustKt"))
    if wind is None and gust is not None:
        wind = _round(gust / old_g, 1)
    if wind is None:
        return
    xw = _num(entry.get("crosswindKt"))
    entry["windKt"] = wind
    entry["gustKt"] = estimated_gust(wind, factor.g)
    entry["crosswindKt"] = None if xw is None else _round(xw * factor.g / old_g, 1)
    entry["gustFactor"], entry["gustFactorBasis"] = factor.g, factor.basis


def model_entries(
    ec: dict, gfs: dict, others: dict[str, dict], runs: dict[str, str | None], th: Thresholds
) -> list[dict]:
    """`slots[].model.models[]`（HD14）：照 `config.MODELS` 的順序，每個模式一筆，沒資料的也有
    （數字、`levels`、`level` 全是 null；旁觀模式也照寫，HD16）。`ec`／`gfs` 要先
    `fill_model_wx`（IFS、GFS 三類的等級直接用 `model.ec`／`model.gfs` 的，值照舊）；其他模式的
    數字從 `others[id]`（`estimated_for_slot` 等的結果，或沿用時抄來的那筆）；`windKt`（HD18）
    也從 `others[id]`（IFS、GFS 是 `ec_wind_for_slot`／`gfs_wind_for_slot`，IFS 系集沒有）。
    `gustFactor`／`gustFactorBasis` 只有估算陣風、而且有陣風的那幾筆有。

    - `ifs`：HRES 陣風、側風、雨量、型態；雨＝`ec.rain`（HRES 雨量或系集 24 小時雨量機率，同 HD8）
    - `gfs`：陣風、側風、雨量、型態、能見度（霧只有它）
    - `ifs-ens`（`votes_only_high`）：數字全 null，`levels.wind`＝`p49Kt` ≥ `ecP49High` 高、否則低
    - 其他只投高的（WN2 系集，HD16）：`windKt`／`gustKt` 是中位數成員的（估算），`p49Kt` 是成員
      比例（`ensemble_for_slot`），`levels.wind` 同上、其他三類 null
    - 其他（AIFS、AIGFS、ICON、JMA GSM）：`gust_estimated` 的是估算陣風（`gustEstimated: true`）；
      有降水型態才投雪；旁觀模式（`voting=False`，HD33b）不判霧（`levels.fog` 永遠 null）
    - `p49Kt`（HD16）：只有「IFS 系集以外、只投高」的那筆有值，其他 null
    - `windKtP90`（HD15）：只有 WeatherNext 3 那筆有這個鍵（`wn3_for_slot`）
    """
    return [model_entry(m, ec, gfs, others.get(m.id) or {}, runs, th) for m in MODELS]


def model_entry(
    m: Model, ec: dict, gfs: dict, src: dict, runs: dict[str, str | None], th: Thresholds
) -> dict:
    """`models[]` 的一筆（規則見 `model_entries`）；`src` 是這個模式自己的數字。HD15 的
    `report-only` 也用這個算 WeatherNext 3 那筆（不經過 `MODELS`）。"""
    lv: dict[str, str | None] = dict.fromkeys(CAUSES)
    if m.id == "ifs":
        nums = {
            "gustKt": ec.get("hresGustKt"),
            "crosswindKt": ec.get("crosswindKt"),
            "rain6hMm": ec.get("rain6hMm"),
            "ptype": ec.get("ptype"),
            "visibilityM": None,
        }
        lv.update(rain=ec.get("rain"), snow=ec.get("snow"))
    elif m.id == "gfs":
        nums = {k: gfs.get(k) for k in MODEL_NUM_KEYS}
        lv.update(rain=gfs.get("rain"), snow=gfs.get("snow"), fog=gfs.get("fog"))
    elif m.votes_only_high:
        nums = dict.fromkeys(MODEL_NUM_KEYS)
        if m.id != ENS_ID:
            nums["gustKt"] = _num(src.get("gustKt"))
        p49 = _num((ec if m.id == ENS_ID else src).get("p49Kt"))
        lv["wind"] = None if p49 is None else "high" if p49 >= th.ec_p49_high else "low"
    else:
        nums = {k: src.get(k) for k in MODEL_NUM_KEYS}
        lv["rain"] = rain_model_level(nums["rain6hMm"], th)
        if nums["ptype"] is not None:
            lv["snow"] = snow_model_level(nums["rain6hMm"], nums["ptype"], th)
        # 旁觀模式不判霧（HD33b，2026-10-25 主對話定案）：CMA 有能見度，數字照存 `visibilityM`，
        # 但不進 `levels`／`level`，同「模式的濃霧只看 GFS 能見度」
        if m.voting:
            lv["fog"] = fog_model_level(nums["visibilityM"], th)
    if not m.votes_only_high:
        lv["wind"] = _wind_level(nums["gustKt"], nums["crosswindKt"], th)
    estimated = nums["gustKt"] is not None and m.gust_estimated
    entry = {
        "id": m.id,
        "run": runs.get(m.id),
        "windKt": None if m.id == ENS_ID else _num(src.get("windKt")),
        "gustKt": nums["gustKt"],
        "gustEstimated": None if nums["gustKt"] is None else m.gust_estimated,
        "gustFactor": _num(src.get("gustFactor")) if estimated else None,
        "gustFactorBasis": src.get("gustFactorBasis") if estimated else None,
        "crosswindKt": nums["crosswindKt"],
        "rain6hMm": nums["rain6hMm"],
        "ptype": nums["ptype"],
        "visibilityM": nums["visibilityM"],
        "p49Kt": _num(src.get("p49Kt")) if m.votes_only_high and m.id != ENS_ID else None,
        "levels": lv,
        "level": max_level(lv.values()),
    }
    if m.id == WN3_ID:
        entry["windKtP90"] = _num(src.get("windKtP90"))
    return entry


def non_voting() -> frozenset[str]:
    """旁觀模式（`Model.voting=False`，HD16）的 id；每次從 `MODELS` 算（測試可以換掉 `MODELS`）。"""
    return frozenset(m.id for m in MODELS if not m.voting)


def ai_hidden() -> frozenset[str]:
    """不給 AI 短評看的模式（`Model.ai=False`，HD33b 的三個旁觀模式）的 id；同 `non_voting`。"""
    return frozenset(m.id for m in MODELS if not m.ai)


def _flags(flags: Sequence[bool], n: int, default: bool) -> list[bool]:
    return list(flags) + [default] * (n - len(flags))


def _pool(
    levels: Sequence[str | None],
    only_high: Sequence[bool],
    target: str,
    voting: Sequence[bool] = (),
) -> list[str]:
    """判 `target` 那一輪的分母：有等級、而且投票（`voting` 不是假，HD16）的模式；判「中」時
    `only_high` 為真的不算。"""
    n = len(levels)
    return [
        lv
        for lv, oh, vt in zip(
            levels, _flags(only_high, n, False), _flags(voting, n, True), strict=True
        )
        if vt and lv in LEVELS and not (oh and target == "medium")
    ]


def vote(
    levels: Sequence[str | None], only_high: Sequence[bool] = (), voting: Sequence[bool] = ()
) -> str | None:
    """一類的投票（HD14）：分母＝有等級（不是 None）的模式數；對 高、中、低 依序看，票數
    （等級 ≥ 它的模式數）× 2 ≥ 分母就成立，取成立的最高。判「中」時 `only_high` 為真的模式不算
    （不在分母、也不算票）；`voting` 為假的旁觀模式（HD16）哪一輪都不算。分母 0 回 None。"""
    for target in ("high", "medium", "low"):
        pool = _pool(levels, only_high, target, voting)
        if pool and sum(rank(lv) >= rank(target) for lv in pool) * 2 >= len(pool):
            return target
    return None


def tally(entries: Sequence[dict], cause: str, target: str) -> tuple[int, int]:
    """`models[]` 某一類判 `target` 那一輪的（票數, 分母），給 AI 短評的「投票」句；旁觀模式
    不算（HD16）。"""
    skip = non_voting()
    lv = [(e.get("levels") or {}).get(cause) for e in entries]
    only_high = [e.get("id") in ONLY_HIGH for e in entries]
    pool = _pool(lv, only_high, target, [e.get("id") not in skip for e in entries])
    return sum(rank(x) >= rank(target) for x in pool), len(pool)


def model_vote(entries: Sequence[dict]) -> tuple[dict[str, str | None], dict]:
    """`models[]` → 四類各自投票的結果與 `model.vote`。

    `vote` 的票數都是「風」那一類的：`total` 分母（含只投高的系集、不含旁觀模式）、`high` 投高的數、
    `medium` 等級 ≥ 中的數（不含只投高的模式，同判中的規則）、`mediumTotal` 判中的分母（不含只投高
    的模式，HD24）、`low` 投低的數；`level` 是四類投票結果取最高；`thin`＝風的分母 < 2。旁觀模式
    （HD16）完全不算。"""
    skip = non_voting()
    rows = [
        (e.get("levels") or {}, e.get("id") in ONLY_HIGH)
        for e in entries
        if e.get("id") not in skip
    ]
    cats = {c: vote([lv.get(c) for lv, _ in rows], [oh for _, oh in rows]) for c in CAUSES}
    wind = [(lv.get("wind"), oh) for lv, oh in rows if lv.get("wind") in LEVELS]
    return cats, {
        "total": len(wind),
        "high": sum(w == "high" for w, _ in wind),
        "medium": sum(rank(w) >= 1 and not oh for w, oh in wind),
        "mediumTotal": len(_pool([w for w, _ in wind], [oh for _, oh in wind], "medium")),
        "low": sum(w == "low" for w, _ in wind),
        "level": max_level(cats.values()),
        "thin": len(wind) < 2,
    }


def model_levels(entries: Sequence[dict]) -> dict[str, str | None] | None:
    """模式層各種類的等級＝各自投票的結果（HD14）；沒有任何模式有資料回 None。"""
    cats, _ = model_vote(entries)
    return None if all(v is None for v in cats.values()) else cats


def model_level(
    ec: dict, gfs: dict, th: Thresholds, others: dict[str, dict] | None = None
) -> str | None:
    """模式層等級（投票，HD14）；完全沒有模式資料回 None。不改 `ec`／`gfs`。"""
    ec, gfs = dict(ec), dict(gfs)
    fill_model_wx(ec, gfs, th)
    _, v = model_vote(model_entries(ec, gfs, others or {}, {}, th))
    return v["level"]


def slot_causes(slot: dict, th: Thresholds, official_levels: dict | None = None) -> list[str]:
    """一格的 `causes`（規則見模組說明）。官方層各種類的等級要另外給（`official_levels`；
    `latest.json` 裡沒有存風的等級）；沒給而依據是官方層時回 None 讓呼叫的人維持原值。
    依據是模式層時用投票後各類的等級（HD14）。"""
    basis = slot.get("basis")
    if basis == "confirmed":
        basis = "official" if slot.get("official") is not None else "model"
    if basis == "official":
        return causes_from(official_levels) if official_levels is not None else None
    if basis == "model":
        m = slot.get("model") or {}
        entries = m.get("models")
        if not isinstance(entries, list):
            ec, gfs = dict(m.get("ec") or {}), dict(m.get("gfs") or {})
            fill_model_wx(ec, gfs, th)
            entries = model_entries(ec, gfs, {}, {}, th)
        return causes_from(model_levels(entries) or {}, MODEL_CAUSE_ORDER)
    return []


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
    aifs: Sequence[AifsStep] | None = None,
    aigfs: Sequence[AigfsStep] | None = None,
    runs: dict[str, str | None] | None = None,
    gust_factor: GustFactor = DEFAULT_GUST_FACTOR,
    icon: Sequence[OmHour] | None = None,
    jma: Sequence[OmHour] | None = None,
    wn2: Sequence[EnsStep] | None = None,
    wn3: Sequence[Wn3Hour] | None = None,
    om_hourly: Mapping[str, Sequence[OmHour] | None] | None = None,
) -> list[dict]:
    """單一機場的所有格。`taf_periods`／`ec`／`gfs`／`metar`／`aifs`／`aigfs`／`icon`／`jma`／`wn2`
    是 None 代表該來源失敗或沒資料。`runs` 是各模式（`config.MODELS` 的 id）的時次，寫進
    `models[].run`；`gust_factor` 是這個機場估算陣風的係數（HD18）。`icon`／`jma`／`wn2` 是
    Open-Meteo 的 ICON、JMA GSM、WeatherNext 2 系集（HD16）；`wn3` 是 WeatherNext 3（HD15，只在
    `MODELS` 有 `wn3`、也就是 `observe` 模式時才會進 `models[]`）。`om_hourly` 是 Open-Meteo 其他
    逐時模式（HD33b 的三個旁觀模式：`gem`、`arpege`、`cma`），id → 逐時（None 是沒資料），
    算法同 ICON。"""
    official_until = now + timedelta(hours=OFFICIAL_HORIZON_H)
    warning_until = now + timedelta(hours=WARNING_HORIZON_H)
    metar_xw = metar_crosswind(metar, now, runways)
    out = []
    for start, end in slots:
        ec_v = ec_for_slot(ec, start, end, runways)
        gfs_v = gfs_for_slot(gfs, start, end, runways)
        fill_model_wx(ec_v, gfs_v, thresholds)
        others = {
            "ifs": {"windKt": ec_wind_for_slot(ec, start, end)},
            "gfs": {"windKt": gfs_wind_for_slot(gfs, start, end)},
            "aifs": estimated_for_slot(aifs, start, end, runways, gust_factor),
            "aigfs": estimated_for_slot(aigfs, start, end, runways, gust_factor),
            # HD16：Open-Meteo
            **{
                mid: hourly_for_slot(
                    hours, start, end, runways, gust_factor if mid in ESTIMATED else None
                )
                for mid, hours in (("icon", icon), ("jma", jma), *(om_hourly or {}).items())
            },
            "wn2-ens": ensemble_for_slot(wn2, start, end, thresholds, gust_factor),
            WN3_ID: wn3_for_slot(wn3, start, end, runways, gust_factor),  # HD15
        }
        entries = model_entries(ec_v, gfs_v, others, runs or {}, thresholds)
        _, vote_v = model_vote(entries)
        m_level = vote_v["level"]
        model = {
            "ec": ec_v,
            "gfs": gfs_v,
            "level": m_level,
            "agreement": agreement(ec_v, gfs_v, thresholds),
            "models": entries,
            "vote": vote_v,
        }

        official = None
        off_levels: dict[str, str | None] | None = None
        if start < official_until:
            taf = taf_for_slot(taf_periods or [], now, start, end, thresholds, runways)
            applied = [w for w in warnings if start < warning_until]
            first = start <= now < end
            # 沒有 TAF 的機場，第一格由 METAR 撐起（HD13）
            by_metar = (
                not taf_periods
                and first
                and metar is not None
                and metar_fresh(metar, now)
                and metar_has_data(metar)
            )
            # 低的警報不會自己撐起官方層（HD8）
            if taf is not None or by_metar or any(rank(w.level) >= rank("medium") for w in applied):
                if taf is not None:
                    official = taf
                elif by_metar and metar is not None:
                    official = {
                        "windKt": metar.wind_kt,
                        "gustKt": metar.gust_kt,
                        "kind": "metar",
                        "level": taf_level(metar.wind_kt, metar.gust_kt, thresholds),
                        "crosswindKt": None,
                    }
                else:
                    official = {
                        "windKt": None,
                        "gustKt": None,
                        "kind": None,
                        "level": None,
                        "crosswindKt": None,
                    }
                if metar_xw is not None and first:
                    official["crosswindKt"] = _round(_max([official["crosswindKt"], metar_xw]), 1)
                wx = None
                if taf is not None:
                    items: list[TafPeriod | Metar] = list(
                        taf_hits(taf_periods or [], now, start, end)
                    )
                    if first and metar is not None and metar_fresh(metar, now):
                        items.append(metar)
                    wx = official_wx(items, thresholds)
                elif by_metar and metar is not None:
                    wx = official_wx([metar], thresholds)
                off_levels = {
                    "wind": max_level(
                        [
                            official["level"],
                            crosswind_level(official["crosswindKt"], thresholds),
                            *(w.level for w in applied if warning_cause(w.kind) == "wind"),
                        ]
                    ),
                    "rain": max_level(
                        [
                            wx["rain"] if wx else None,
                            *(w.level for w in applied if warning_cause(w.kind) == "rain"),
                        ]
                    ),
                    "snow": max_level(
                        [
                            wx["snow"] if wx else None,
                            *(w.level for w in applied if warning_cause(w.kind) == "snow"),
                        ]
                    ),
                    "fog": max_level(
                        [
                            wx["fog"] if wx else None,
                            *(w.level for w in applied if warning_cause(w.kind) == "fog"),
                        ]
                    ),
                }
                official["level"] = max_level(off_levels.values())
                official["warnings"] = [w.kind for w in applied]
                official["wx"] = wx
                if taf is None and not by_metar:
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
        slot = {
            "from": iso(start),
            "to": iso(end),
            "level": level,
            "basis": basis,
            "causes": [],
            "official": official,
            "model": model,
            "gap": gap,
        }
        slot["causes"] = slot_causes(slot, thresholds, off_levels) or []
        out.append(slot)
    return out
