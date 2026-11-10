"""Google WeatherNext 3（HD15）：64 個成員的 AI 系集，0.1°、逐時、主報 00／06／12／18Z 到 360 小時。

**核准前每報都是 `ok: false`**（`error` 是 `http_403`、`no_credentials` 之類）：要 Google 的
allowlist（2026-10-20 19:04 送出，5–7 個工作天），沒核准前查詢與讀檔都會被拒，這是預期的。

授權（README「WeatherNext 3 的條款」逐條引原文）：
- 有效時間在 1 小時內或未來的資料：GDM Real-Time Weather Forecasting Experimental Data Terms of Use
  （`TERMS_URL`）。內部使用可以；**未修改的數字（含裁切地區、挑時間與變數、乘固定比例）不能公開**，
  加工成看不出原始數字的東西才能公開、要附固定標註；日本是限制國家
- 有效時間在 1 小時以前的：CC BY 4.0
- 所以 `config.WN3_MODE` 預設 `private`（HD15b，2026-10-26 核准後：照有效時間的讀法，最新一報
  只寫進私人 bucket、超過 121 小時才公開，見 `wn3report.py`、`wn3private.py`）。**日誌不印任何
  預報值或等級**（只印起報時間、機場數、bytes、秒數、錯誤碼）

文件（2026-10-20 查；公開的 Colab 範例 `gs://weathernext-public/colabs/WeatherNext_3_Starter_Guide_*`
有完整欄位）：
- **BigQuery**（首選）：表 `weathernext_3_0_0_0p1deg`，核准後在 Analytics Hub 訂閱、在自己的專案
  建一個連結資料集（README 寫要取名 `weathernext_3`，`BQ_DATASET`；或用環境變數 `WN3_BQ_TABLE`
  給完整的 `專案.資料集.表`）。一列是一個 0.1° 格點的一報：`init_time`（TIMESTAMP，**依日分割**）、
  `geography`（格點中心 POINT）、`geography_polygon`（0.1° 方格）、`forecast`（REPEATED RECORD：
  `time`、`hours`（1–360）、每個變數 6 個統計 `_mean`／`_p10`／`_p25`／`_p50`／`_p75`／`_p90`）。
  變數（SI 單位）：`wind_speed_10m`（m/s）、`u_component_of_wind_10m`、`v_component_of_wind_10m`、
  `total_precipitation_1hr`（**m**，前 1 小時）、`temperature_2m`（K）、`mean_sea_level_pressure`
  （Pa）等。**沒有陣風、能見度、降水型態、降雪**。叢集欄位文件沒寫
- **GCS Zarr**（備援）：統計 `gs://weathernext3_statistics_spatial/weathernext_3_0_0_statistics/zarr/
  2026_to_present/<YYYYMMDD_HHhr_XX_preds>/predictions.zarr/`（Zarr v3），維度 `lead_time`
  （1–360 小時，timedelta，**逐時**）、`lat_0p1`（1801）、`lon_0p1`（3600，**0–360**），變數名同
  BigQuery（`<變數>_p50`；雨量 `total_precipitation_1hr_mean`，m，前 1 小時，2026-11-11 查公開的
  Statistics Colab 確認）；範例裡的 chunk 是**一個時間一整張全球**（1 × 1801 × 3600 float32 ≈
  25.9 MB 未壓縮）。64 個成員的原始資料在 `gs://weathernext3_spatial/`（requester pays，一個成員一個
  6 小時一張全球，讀成員路徑一報要上百 GB，不做）
- 發布時間（dissemination schedule）：主報 BigQuery 在起報後約 8 小時 10 分、GCS 7 小時 45 分（±15
  分鐘，偶爾 ±60 分鐘以上）→ `latest_run` 取「現在 − 8 小時 10 分 − 20 分鐘」以前最近的主報，
  查不到資料再退一報

一報要的數字（`Wn3Hour`，逐時）：風用 **p50**（每個時間點 64 個成員的中位數；BigQuery 與 Zarr
一樣），另存平均與 p90；風向用平均的 u／v；雨量用平均（m → mm）；2 米溫度用平均。沒有陣風 → `assess`
用平均風 × 機場的 G 估算（`config.MODELS` 的 `wn3` 是 `gust_estimated`）。

費用：
- BigQuery 每個查詢先 dry run 記下估計的掃描量（`estimateBytes`；叢集裁切前的上限），再用
  `maximum_bytes_billed`＝`BQ_MAX_BYTES`（8 GB）真的查：超過 BigQuery 直接拒絕、不收錢
  （`bq_bytes_limit`），退到 Zarr。每月免費 1 TB ÷（一天 4 報 × 31 天）≈ 8 GB
- Zarr 讀每 6 小時的風（p50、p90、平均 u／v，`ZARR_WIND_VARS`）＋**逐時雨量**（HD49，
  `ZARR_RAIN_VAR`，`zarr_rain`）：每個格 (from, to] 的 6 個小時，m → mm 與 BigQuery 同一個 `_hour`、
  加總同一個 `assess.wn3_for_slot`（所以 `rain6hMm` 只有一套算法）。一報約 120–132 個時效、每個
  一張全球 chunk（約 26 MB 未壓縮、約 3.4 GB 合計；壓縮後實際下載量看第一報的 `bytes`）。分批
  （`RAIN_BATCH_H` 個時效一批）、`RAIN_WORKERS` 條並行讀，最多 `RAIN_TIMEOUT_S` 秒；變數不在、
  時間軸不是逐時、讀失敗或超時都是**風照用、雨當沒有**（`Wn3Data.rain` false＋`rain_error`
  錯誤碼）。路徑用的平均海平面氣壓每 6 小時一張
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable, Sequence
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np

from ..budget import add_bytes, check_cancelled
from ..config import Airport
from ..grib import wind_dir_from_uv
from ..timeutil import floor_6h, hours_between, iso
from ..units import ms_to_kt
from . import SourceError

log = logging.getLogger("hongthai")

TERMS_URL = "https://storage.googleapis.com/weathernext-public/terms-of-use.pdf"
ENV_TABLE = "WN3_BQ_TABLE"
# 走哪條路（2026-10-26）：`auto`（預設，BigQuery 失敗退 Zarr）、`zarr`（不查 BigQuery：
# Analytics Hub 的 listing 連結數滿 1000、訂閱不了時用）、`bigquery`（不退 Zarr）。
# repo Variable `WN3_VIA` 可以覆寫
ENV_VIA = "WN3_VIA"
VIAS = ("auto", "zarr", "bigquery")
BQ_DATASET = "weathernext_3"
BQ_TABLE = "weathernext_3_0_0_0p1deg"
BQ_LATENCY = timedelta(hours=8, minutes=10)
LATENCY_MARGIN = timedelta(minutes=20)
BQ_MAX_BYTES = 8 * 10**9
BQ_TIMEOUT_S = 60
SEARCH_M = 8000  # 0.1° 方格的半對角線在赤道約 7.9 公里：一定找得到包含機場的那格
STATS_BUCKET = "weathernext3_statistics_spatial"
STATS_PREFIX = "weathernext_3_0_0_statistics/zarr/2026_to_present/"
STEP_H = 6
SPAN_H = 120
# 路徑用的海平面氣壓只留這個範圍（`tracks` 再裁到 0–40°N、100–180°E 加邊）
MSLP_LAT = (-5.0, 45.0)
MSLP_LON = (95.0, 185.0)

# BigQuery `forecast` 裡要的欄位（只選這些，掃描量才小）
BQ_FIELDS = (
    "wind_speed_10m_p50",
    "wind_speed_10m_mean",
    "wind_speed_10m_p90",
    "u_component_of_wind_10m_mean",
    "v_component_of_wind_10m_mean",
    "total_precipitation_1hr_mean",
    "temperature_2m_mean",
)
ZARR_WIND_VARS = (
    "wind_speed_10m_p50",
    "wind_speed_10m_mean",
    "wind_speed_10m_p90",
    "u_component_of_wind_10m_mean",
    "v_component_of_wind_10m_mean",
)
ZARR_MSLP_VAR = "mean_sea_level_pressure_mean"
# HD49：逐時雨量（m，前 1 小時；BigQuery 那條路的同名欄位）。一個時效一張全球 chunk，分批並行讀
ZARR_RAIN_VAR = "total_precipitation_1hr_mean"
RAIN_TIMEOUT_S = 90  # 雨量最多讀這麼久，超過就放棄（風照用、`rain_timeout`）
RAIN_BATCH_H = 6  # 一批幾個時效（一個 6 小時格）；批與批之間檢查取消與期限
RAIN_WORKERS = 4  # 幾批同時讀（zarr 一批裡的 chunk 自己也會並行抓）


class Wn3Error(SourceError):
    """`fields`：兩條路都失敗時各自的錯誤碼（`bqError`、`zarrError`），併進 `sources.wn3`
    （只有錯誤碼，沒有任何預報值）。"""

    def __init__(self, message: str, code: str | None = None, fields: dict | None = None):
        super().__init__(message, code)
        self.fields = dict(fields or {})


def via_mode(env: dict[str, str] | None = None) -> str:
    """`WN3_VIA` 環境變數（`auto`／`zarr`／`bigquery`），沒設或不認得是 `auto`。"""
    v = (os.environ if env is None else env).get(ENV_VIA, "").strip().lower()
    return v if v in VIAS else "auto"


@dataclass
class Wn3Hour:
    """一個小時（`valid` 是有效時間）：10 米風 p50、平均、p90（節）、平均風向、前 1 小時雨量
    （平均，mm）、2 米溫度（平均，°C）。Zarr 沒有溫度；風只有 6 的倍數的時效有，其他小時只有雨量
    （HD49；雨量讀不到時只有每 6 小時的風）。"""

    valid: datetime
    wind_kt: float | None
    wind_mean_kt: float | None
    wind_p90_kt: float | None
    wdir: float | None
    precip_mm: float | None
    temp2m_c: float | None = None


@dataclass
class Grid:
    """規則經緯網格的一張場（路徑用）：緯度、經度（0–360）一維、`values[緯, 經]`（原始單位）。"""

    lats: np.ndarray
    lons: np.ndarray
    values: np.ndarray


@dataclass
class Wn3Data:
    run: datetime
    points: dict[str, list[Wn3Hour]]
    via: str  # "bigquery" 或 "zarr"
    bytes_downloaded: int = 0
    estimate_bytes: int | None = None  # BigQuery dry run（叢集裁切前的上限）
    bytes_processed: int | None = None
    bytes_billed: int | None = None
    bq_error: str | None = None  # BigQuery 失敗、退到 Zarr 的原因
    mslp: dict[datetime, Grid] = field(default_factory=dict)  # 有效時間 → 平均海平面氣壓（Pa）
    mslp_error: str | None = None
    # HD49：雨量有沒有讀到（BigQuery 一律 True）；Zarr 讀不到時 `rain_error` 是錯誤碼
    rain: bool | None = None
    rain_error: str | None = None


def has_rain(data: Wn3Data) -> bool:
    """任一機場任一小時有雨量（`points/` 讀回來的那報用這個判斷 `sources.wn3.rain`）。"""
    return any(h.precip_mm is not None for hours in data.points.values() for h in hours)


# ---- 認證與時次 ----


def credentials(env: dict[str, str] | None = None):
    """服務帳號（同 Gemini：`GOOGLE_SERVICE_ACCOUNT_JSON` 整份原文，`json.loads` 後直接給
    `google.oauth2`，不寫到磁碟）與專案。少一個或讀不了丟 `no_credentials`。實作在輕量的
    `wn3private.credentials`（事件保存每小時那支搬家也用）。"""
    from ..wn3private import PrivateError
    from ..wn3private import credentials as load

    try:
        return load(env)
    except PrivateError as e:
        raise Wn3Error(str(e), e.code) from e


def table_id(project: str, env: dict[str, str] | None = None) -> str:
    env = os.environ if env is None else env
    return env.get(ENV_TABLE) or f"{project}.{BQ_DATASET}.{BQ_TABLE}"


def latest_run(now: datetime, latency: timedelta = BQ_LATENCY) -> datetime:
    """照發布時間表，現在應該已經完整發布的最新一個主報（00／06／12／18Z）。"""
    return floor_6h(now - latency - LATENCY_MARGIN)


def lead_window(run: datetime, start: datetime, end: datetime) -> tuple[int, int]:
    """[start, end] 對應的提前時間（小時）；統計資料從 1 小時起。"""
    return max(1, int(hours_between(run, start))), int(hours_between(run, end))


def mslp_leads(h0: int, h1: int) -> list[int]:
    """路徑用的氣壓：[h0, h1] 裡 6 的倍數（同其他模式每 6 小時一步）。"""
    first = max(STEP_H, -(-h0 // STEP_H) * STEP_H)
    return list(range(first, h1 + 1, STEP_H))


# ---- BigQuery ----


def build_sql(table: str, airports: Sequence[Airport]) -> str:
    """一個查詢取全部機場：`init_time` 用參數（分割裁切），機場是常數 MULTIPOINT（若表依
    `geography` 叢集，常數才能裁切），`forecast` 只留 [`@h0`, `@h1`] 小時與 `BQ_FIELDS`。
    機場座標是 `airports.json` 的數字，不是外部輸入。"""
    pts = ", ".join(f"({a.lon:.4f} {a.lat:.4f})" for a in airports)
    cols = ", ".join(f"f.{c}" for c in BQ_FIELDS)
    return (
        "SELECT ST_X(t.geography) AS lon, ST_Y(t.geography) AS lat,\n"
        f"  ARRAY(SELECT AS STRUCT f.hours, {cols}\n"
        "        FROM UNNEST(t.forecast) AS f\n"
        "        WHERE f.hours BETWEEN @h0 AND @h1 ORDER BY f.hours) AS forecast\n"
        f"FROM `{table}` AS t\n"
        "WHERE t.init_time = @init\n"
        f"  AND ST_DWITHIN(t.geography, ST_GEOGFROMTEXT('MULTIPOINT({pts})'), {SEARCH_M})"
    )


def _num(v: object) -> float | None:
    if isinstance(v, bool) or not isinstance(v, int | float | np.floating | np.integer):
        return None
    f = float(v)
    return f if np.isfinite(f) else None


def _round(v: float | None, nd: int = 2) -> float | None:
    return None if v is None else round(v, nd)


def _hour(run: datetime, hours: int, rec: dict) -> Wn3Hour:
    u, v = (
        _num(rec.get("u_component_of_wind_10m_mean")),
        _num(rec.get("v_component_of_wind_10m_mean")),
    )
    tp = _num(rec.get("total_precipitation_1hr_mean"))
    t2 = _num(rec.get("temperature_2m_mean"))
    return Wn3Hour(
        valid=run + timedelta(hours=hours),
        wind_kt=_round(ms_to_kt(_num(rec.get("wind_speed_10m_p50")))),
        wind_mean_kt=_round(ms_to_kt(_num(rec.get("wind_speed_10m_mean")))),
        wind_p90_kt=_round(ms_to_kt(_num(rec.get("wind_speed_10m_p90")))),
        wdir=_round(wind_dir_from_uv(u, v), 1),
        precip_mm=None if tp is None else round(max(0.0, tp) * 1000, 3),
        temp2m_c=None if t2 is None else round(t2 - 273.15, 2),
    )


def _distance_deg2(a: Airport, lat: float, lon: float) -> float:
    dlon = (lon - a.lon + 180) % 360 - 180
    return (lat - a.lat) ** 2 + (dlon * np.cos(np.radians(a.lat))) ** 2


def parse_rows(
    rows: Sequence, airports: Sequence[Airport], run: datetime
) -> dict[str, list[Wn3Hour]]:
    """查詢結果（每列一個格點：`lon`、`lat`、`forecast`；STRUCT 在 Python 裡是 dict）→ 每個機場
    最近那格的逐時資料；`SEARCH_M` 內沒有格點的機場不在結果裡。"""
    cells = []
    for r in rows:
        lat, lon = _num(r["lat"]), _num(r["lon"])
        if lat is None or lon is None:
            continue
        cells.append((lat, lon, list(r["forecast"] or [])))
    out: dict[str, list[Wn3Hour]] = {}
    for a in airports:
        near = [c for c in cells if _distance_deg2(a, c[0], c[1]) <= (SEARCH_M / 111_000) ** 2]
        if not near:
            continue
        _, _, fc = min(near, key=lambda c: _distance_deg2(a, c[0], c[1]))
        hours = [
            _hour(run, rec["hours"], rec)
            for rec in fc
            if isinstance(rec, dict) and isinstance(rec.get("hours"), int)
        ]
        out[a.icao] = sorted(hours, key=lambda x: x.valid)
    return out


def _bq_code(e: Exception) -> str:
    text = str(e)
    if "bytesBilledLimitExceeded" in text or "billing limit" in text.lower():
        return "bq_bytes_limit"
    code = getattr(e, "code", None)
    return f"http_{code}" if isinstance(code, int) else e.__class__.__name__


def bq_client(creds, project: str):
    from google.cloud import bigquery  # 延後載入

    return bigquery.Client(project=project, credentials=creds)


def _job_config(run: datetime, h0: int, h1: int, *, dry_run: bool):
    from google.cloud import bigquery

    params = [
        bigquery.ScalarQueryParameter("init", "TIMESTAMP", run),
        bigquery.ScalarQueryParameter("h0", "INT64", h0),
        bigquery.ScalarQueryParameter("h1", "INT64", h1),
    ]
    if dry_run:
        return bigquery.QueryJobConfig(query_parameters=params, dry_run=True, use_query_cache=False)
    return bigquery.QueryJobConfig(query_parameters=params, maximum_bytes_billed=BQ_MAX_BYTES)


@dataclass
class BqResult:
    points: dict[str, list[Wn3Hour]]
    estimate: int | None
    processed: int | None
    billed: int | None


def query_points(
    client,
    table: str,
    run: datetime,
    h0: int,
    h1: int,
    airports: Sequence[Airport],
    job_config: Callable[..., object] = _job_config,
) -> BqResult:
    """dry run 記掃描量上限 → 真的查（`maximum_bytes_billed`）。失敗丟 `Wn3Error`（`http_403`：
    還沒核准；`bq_bytes_limit`：超過上限、沒收錢；`http_404`：表或資料集不在）。"""
    sql = build_sql(table, airports)
    try:
        check_cancelled()
        dry = client.query(sql, job_config=job_config(run, h0, h1, dry_run=True))
        estimate = getattr(dry, "total_bytes_processed", None)
        log.info("WeatherNext 3 BigQuery %s：dry run 估計掃描 %s bytes", iso(run), estimate)
        check_cancelled()
        job = client.query(sql, job_config=job_config(run, h0, h1, dry_run=False))
        rows = list(job.result(timeout=BQ_TIMEOUT_S))
    except Wn3Error:
        raise
    except Exception as e:  # google.api_core 的各種錯誤、逾時
        raise Wn3Error(f"WeatherNext 3 BigQuery {iso(run)}：{e}"[:300], _bq_code(e)) from e
    return BqResult(
        parse_rows(rows, airports, run),
        estimate,
        getattr(job, "total_bytes_processed", None),
        getattr(job, "total_bytes_billed", None),
    )


# ---- GCS Zarr（備援、路徑）----


def stats_url(fs, run: datetime) -> str:
    """`<YYYYMMDD_HHhr_XX_preds>` 的 `XX` 文件沒說（範例是 `01`），列出來取最後一個。"""
    pattern = f"{STATS_BUCKET}/{STATS_PREFIX}{run:%Y%m%d_%H}hr_*_preds"
    found = sorted(fs.glob(pattern))
    if not found:
        raise Wn3Error(f"GCS 沒有 {iso(run)} 那報的統計 Zarr", "zarr_not_found")
    return f"gs://{found[-1]}/predictions.zarr"


def open_stats_gcs(creds, project: str) -> Callable[[datetime], object]:
    """回傳「時次 → xarray Dataset」：gcsfs 用服務帳號（不落地），Zarr v3、不預先載入。"""

    def open_run(run: datetime):
        import gcsfs  # 延後載入
        import xarray as xr

        fs = gcsfs.GCSFileSystem(token=creds, project=project)
        try:
            url = stats_url(fs, run)
            return xr.open_zarr(
                url, storage_options={"token": creds, "project": project}, chunks=None
            )
        except Wn3Error:
            raise
        except PermissionError as e:  # gcsfs 把 401／403 換成 PermissionError
            raise Wn3Error(f"GCS 統計 Zarr {iso(run)}：{e}"[:300], "http_403") from e
        except OSError as e:
            # gcsfs 的 403 是 `OSError("Forbidden: <路徑>…")`（不是 PermissionError；
            # 2026-10-26 服務帳號讀 Zarr 的那報 `zarrError` 是 `OSError`）
            msg = str(e)
            code = "http_403" if msg.startswith("Forbidden") else e.__class__.__name__
            raise Wn3Error(f"GCS 統計 Zarr {iso(run)}：{msg}"[:300], code) from e
        except Exception as e:
            code = getattr(e, "code", None)
            raise Wn3Error(
                f"GCS 統計 Zarr {iso(run)}：{e}"[:300],
                f"http_{code}" if isinstance(code, int) else e.__class__.__name__,
            ) from e

    return open_run


def _leads(ds, hours: Sequence[int]) -> list[int]:
    have = {int(td / np.timedelta64(1, "h")) for td in np.asarray(ds["lead_time"].values)}
    return [h for h in hours if h in have]


def _point_index(ds, airports: Sequence[Airport]) -> tuple[np.ndarray, np.ndarray]:
    """每個機場最近的格點（緯度索引, 經度索引）；經度照 0–360 繞一圈比。"""
    lats = np.asarray(ds["lat_0p1"].values, dtype=float)
    lons = np.asarray(ds["lon_0p1"].values, dtype=float) % 360
    li = np.array([int(np.abs(lats - a.lat).argmin()) for a in airports])
    lj = np.array([int(np.abs((lons - a.lon % 360 + 180) % 360 - 180).argmin()) for a in airports])
    return li, lj


def _chunk_bytes(da, lat_idx: Sequence[int], lon_idx: Sequence[int], box: bool = False) -> int:
    """讀這些格點（`box`：這兩串索引圍起來的方框）每個時間要抓的 chunk 未壓縮大小；`encoding`
    沒有 chunk 資訊時當一整張。"""
    chunks = da.encoding.get("chunks") or da.shape
    clat, clon = int(chunks[-2]), int(chunks[-1])
    if box:
        n = (max(lat_idx) // clat - min(lat_idx) // clat + 1) * (
            max(lon_idx) // clon - min(lon_idx) // clon + 1
        )
    else:
        n = len({(int(i) // clat, int(j) // clon) for i, j in zip(lat_idx, lon_idx, strict=True)})
    return n * clat * clon * da.dtype.itemsize


def rain_leads(h0: int, h1: int) -> list[int]:
    """逐時雨量要讀的時效：格是 (from, to]，所以 `h0` 是 6 的倍數（窗的起點在起報之後）時從
    `h0 + 1` 起；`h0` 是 1（`lead_window` 把起報或更早的起點夾成 1）時從 1 起。"""
    first = h0 + 1 if h0 % STEP_H == 0 else h0
    return list(range(max(1, first), h1 + 1))


@dataclass
class RainRead:
    """`zarr_rain` 的結果：時效 → 每個機場的雨量（m，原始值；換算交給 `_hour`）、估計讀的未壓縮
    bytes（讀完的批才算）、錯誤碼（None＝全部讀到）。有錯誤時 `values` 是空的（雨當沒有）。"""

    values: dict[int, np.ndarray]
    size: int
    error: str | None


def _rain_batch(da, leads: Sequence[int], pts: dict) -> np.ndarray:
    tds = [np.timedelta64(h, "h") for h in leads]
    out = da.sel(lead_time=tds).isel(pts)
    return np.asarray(out.transpose("lead_time", "pt").values, dtype=float)


def _rain_code(e: Exception) -> str:
    if isinstance(e, PermissionError) or str(e).startswith("Forbidden"):
        return "http_403"
    code = getattr(e, "code", None)
    return f"http_{code}" if isinstance(code, int) else e.__class__.__name__


def zarr_rain(
    ds,
    leads: Sequence[int],
    li: np.ndarray,
    lj: np.ndarray,
    timeout: float | None = None,
    workers: int | None = None,
) -> RainRead:
    """逐時雨量（`ZARR_RAIN_VAR`）的這些時效 → 每個機場（HD49）。分成 `RAIN_BATCH_H` 個時效一批、
    `workers`（預設 `RAIN_WORKERS`）條並行讀，主執行緒每秒檢查一次 `check_cancelled` 與 `timeout`
    （預設 `RAIN_TIMEOUT_S`）。

    錯誤碼（只有錯誤碼，日誌不印任何數值）：`zarr_no_rain`（沒有這個變數）、`zarr_empty`（沒有
    要的時效）、`zarr_not_hourly`（時間軸只有 6 的倍數，沒有逐時）、`rain_timeout`、或讀的那一批的
    錯誤（`http_403`、例外類別名）。被取消（`Cancelled`）照樣往外丟，沒讀完的批不再開始。"""
    if ZARR_RAIN_VAR not in ds:
        return RainRead({}, 0, "zarr_no_rain")
    have = _leads(ds, leads)
    if not have:
        return RainRead({}, 0, "zarr_empty")
    if all(h % STEP_H == 0 for h in have) and len(have) < len(leads):
        return RainRead({}, 0, "zarr_not_hourly")
    import xarray as xr  # 延後載入

    da = ds[ZARR_RAIN_VAR]
    pts = {"lat_0p1": xr.DataArray(li, dims="pt"), "lon_0p1": xr.DataArray(lj, dims="pt")}
    per_lead = _chunk_bytes(da, li, lj)
    batches = [have[k : k + RAIN_BATCH_H] for k in range(0, len(have), RAIN_BATCH_H)]
    deadline = time.monotonic() + (RAIN_TIMEOUT_S if timeout is None else timeout)
    n_workers = RAIN_WORKERS if workers is None else workers
    pool = ThreadPoolExecutor(max_workers=max(1, n_workers), thread_name_prefix="wn3-rain")
    futures = {pool.submit(_rain_batch, da, b, pts): b for b in batches}
    values: dict[int, np.ndarray] = {}
    size = 0
    error: str | None = None
    try:
        pending = set(futures)
        while pending and error is None:
            check_cancelled()
            left = deadline - time.monotonic()
            if left <= 0:
                error = "rain_timeout"
                break
            done, pending = wait(pending, timeout=min(1.0, left), return_when=FIRST_COMPLETED)
            for f in done:
                exc = f.exception()
                if exc is not None:
                    error = _rain_code(exc) if isinstance(exc, Exception) else "rain_cancelled"
                    break
                batch = futures[f]
                size += len(batch) * per_lead
                for k, h in enumerate(batch):
                    values[h] = f.result()[k]
    finally:
        # 沒開始的批不再開始；正在讀的那幾批讀完就結束（Python 停不了執行緒）
        pool.shutdown(wait=False, cancel_futures=True)
        add_bytes(size)
    return RainRead({} if error else values, size, error)


def zarr_points(
    ds, run: datetime, h0: int, h1: int, airports: Sequence[Airport], rain: bool = True
) -> tuple[dict[str, list[Wn3Hour]], int, RainRead | None]:
    """統計 Zarr 的每 6 小時風（`ZARR_WIND_VARS`）＋逐時雨量（`zarr_rain`，HD49；`rain=False` 不讀）
    → 每個機場；回傳（資料, 估計讀的未壓縮 bytes（風＋雨）, 雨量的結果）。用逐點索引，Zarr 只抓
    有機場的 chunk（範例裡一個 chunk 是一整張全球，就是每個時間一張）。雨量讀不到時只有風（同
    HD49 以前），讀到時每小時一筆（6 的倍數以外的小時風是 None）。沒有溫度。"""
    import xarray as xr  # 延後載入

    leads = _leads(ds, [h for h in range(h0, h1 + 1) if h % STEP_H == 0])
    if not leads:
        raise Wn3Error(f"統計 Zarr {iso(run)} 沒有 {h0}–{h1} 小時", "zarr_empty")
    li, lj = _point_index(ds, airports)
    pts = {
        "lat_0p1": xr.DataArray(li, dims="pt"),
        "lon_0p1": xr.DataArray(lj, dims="pt"),
    }
    tds = [np.timedelta64(h, "h") for h in leads]
    cols: dict[str, np.ndarray] = {}
    size = 0
    for var in ZARR_WIND_VARS:
        check_cancelled()
        if var not in ds:
            continue
        da = ds[var].sel(lead_time=tds).isel(pts)
        cols[var] = np.asarray(da.transpose("lead_time", "pt").values, dtype=float)
        size += len(tds) * _chunk_bytes(ds[var], li, lj)
    add_bytes(size)
    rr = zarr_rain(ds, rain_leads(h0, h1), li, lj) if rain else None
    rain_vals = rr.values if rr is not None else {}
    if rr is not None:
        size += rr.size
    wind_at = {h: k for k, h in enumerate(leads)}
    out: dict[str, list[Wn3Hour]] = {}
    for n, a in enumerate(airports):
        rows = []
        for h in sorted(set(leads) | set(rain_vals)):
            rec = {var: cols[var][wind_at[h], n] for var in cols} if h in wind_at else {}
            if h in rain_vals:
                rec[ZARR_RAIN_VAR] = rain_vals[h][n]
            rows.append(_hour(run, h, rec))
        out[a.icao] = rows
    return out, size, rr


def zarr_mslp(ds, run: datetime, leads: Sequence[int]) -> tuple[dict[datetime, Grid], int]:
    """路徑用：每 6 小時的平均海平面氣壓（Pa），只讀 `MSLP_LAT`／`MSLP_LON` 範圍。"""
    lats = np.asarray(ds["lat_0p1"].values, dtype=float)
    lons = np.asarray(ds["lon_0p1"].values, dtype=float) % 360
    li = np.nonzero((lats >= MSLP_LAT[0]) & (lats <= MSLP_LAT[1]))[0]
    lj = np.nonzero((lons >= MSLP_LON[0]) & (lons <= MSLP_LON[1]))[0]
    if not len(li) or not len(lj):
        return {}, 0
    box = {"lat_0p1": slice(li.min(), li.max() + 1), "lon_0p1": slice(lj.min(), lj.max() + 1)}
    out: dict[datetime, Grid] = {}
    size = 0
    for h in _leads(ds, leads):
        check_cancelled()
        da = ds[ZARR_MSLP_VAR].sel(lead_time=np.timedelta64(h, "h")).isel(box)
        vals = np.asarray(da.values, dtype=float)
        size += _chunk_bytes(ds[ZARR_MSLP_VAR], li, lj, box=True)
        sub_lats = lats[box["lat_0p1"]]
        sub_lons = lons[box["lon_0p1"]]
        out[run + timedelta(hours=h)] = Grid(sub_lats, sub_lons, vals)
    add_bytes(size)
    return out, size


# ---- 一報 ----


def fetch(
    airports: Sequence[Airport],
    run: datetime,
    start: datetime,
    end: datetime,
    *,
    mslp: bool = False,
    retry_previous: bool = False,
    client=None,
    open_stats: Callable[[datetime], object] | None = None,
    env: dict[str, str] | None = None,
) -> Wn3Data:
    """抓 `run` 那報 [start, end] 的全部機場（BigQuery，失敗退 Zarr）；`mslp`：多讀路徑用的
    平均海平面氣壓（Zarr）。`retry_previous`：那報還沒發布（BigQuery 查不到任何列、Zarr 沒有
    那個目錄）時退一報。`client`／`open_stats` 給測試換掉。兩條路都失敗丟 `Wn3Error`，`code`
    優先用 BigQuery 的（核准前是 `http_403`）。"""
    t0 = time.monotonic()
    if client is None or open_stats is None:
        creds, project = credentials(env)
        table = table_id(project, env)
        client = client or bq_client(creds, project)
        open_stats = open_stats or open_stats_gcs(creds, project)
    else:
        table = (env or {}).get(ENV_TABLE) or f"{BQ_DATASET}.{BQ_TABLE}"
    runs = [run, run - timedelta(hours=STEP_H)] if retry_previous else [run]
    via = via_mode(env)

    data: Wn3Data | None = None
    bq_error: str | None = "skipped" if via == "zarr" else None
    for r in [] if via == "zarr" else runs:
        h0, h1 = lead_window(r, start, end)
        try:
            res = query_points(client, table, r, h0, h1, airports)
        except Wn3Error as e:
            log.warning("WeatherNext 3 BigQuery 失敗（%s），改讀 GCS Zarr：%s", e.code, e)
            bq_error = e.code
            break
        if any(res.points.values()):
            data = Wn3Data(r, res.points, "bigquery", 0, res.estimate, res.processed, res.billed)
            data.rain = True
            break
        log.warning("WeatherNext 3 BigQuery %s 沒有資料（還沒發布？）", iso(r))
        bq_error = "no_rows"

    ds = None
    if data is None and via == "bigquery":
        raise Wn3Error(
            f"BigQuery：{bq_error}（WN3_VIA=bigquery，不退 Zarr）", bq_error or "no_rows"
        )
    if data is None:
        for r in runs:
            try:
                ds = open_stats(r)
                h0, h1 = lead_window(r, start, end)
                points, size, rr = zarr_points(ds, r, h0, h1, airports)
            except Wn3Error as e:
                if e.code == "zarr_not_found" and r is not runs[-1]:
                    continue
                code = bq_error if bq_error not in (None, "no_rows", "skipped") else e.code
                fields = {"bqError": bq_error, "zarrError": e.code}
                raise Wn3Error(f"BigQuery：{bq_error}；Zarr：{e}", code, fields) from e
            data = Wn3Data(r, points, "zarr", size, bq_error=bq_error)
            if rr is not None:
                data.rain, data.rain_error = rr.error is None, rr.error
                if rr.error:
                    log.warning("WeatherNext 3 的雨量讀不到（%s），只用風", rr.error)
            break
    assert data is not None
    data.points = {a.icao: data.points.get(a.icao, []) for a in airports}

    if mslp:
        h0, h1 = lead_window(data.run, start, end)
        try:
            ds = ds if ds is not None else open_stats(data.run)
            data.mslp, size = zarr_mslp(ds, data.run, mslp_leads(h0, h1))
            data.bytes_downloaded += size
            if not data.mslp:
                data.mslp_error = "zarr_empty"
        except Wn3Error as e:
            log.warning("WeatherNext 3 的海平面氣壓讀不到（%s）：%s", e.code, e)
            data.mslp_error = e.code
    log.info(
        "WeatherNext 3 %s：%s，%d 個機場有資料，雨量 %s，掃描 %s／計費 %s bytes、讀 Zarr %d bytes，"
        "%.1f 秒",
        iso(data.run),
        data.via,
        sum(bool(v) for v in data.points.values()),
        "有" if data.rain else f"沒有（{data.rain_error}）",
        data.bytes_processed,
        data.bytes_billed,
        data.bytes_downloaded,
        time.monotonic() - t0,
    )
    return data
