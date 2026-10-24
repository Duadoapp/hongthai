"""Open-Meteo Previous Runs API 回補事件期間的四個新模式（HD33a）：UKMO、GEM、ARPEGE、CMA GRAPES。

**只存資料給報告比**（`tools/report_29w.py`）：不進 `latest.json`、`models[]`、等級、投票、AI、網頁
（旁觀進 `latest.json` 是 HD33b）。Duado spec 第 16 節「新模式」定案：經 Open-Meteo 先旁觀、不投票，
用 29W 回補比過準確度再決定投票或加權；不照解析度加權。

來源：`PREVIOUS_RUNS_URL`（文件 <https://open-meteo.com/en/docs/previous-runs-api>）。變數名後面
接 `_previous_dayN` 是「提前 N 天的那一報」對同一個時間的預報（`_previous_day0` 是最新一報，同預報
API）；文件寫 `_previous_day1` 是 valid time 前 24 小時預報的值、`_previous_day2` 前 48 小時，
最多到 day 7。
所以 `previousDay` N 的提前時間是 24N 起、不到 24(N+1) 小時；報告怎麼對到 HD22 的提前段見
`tools/report_29w.py` 開頭。

- 模式（`MODELS`，id → Open-Meteo 的模式代號；id 和 HD33b 的 `config.MODELS` 一樣）：
  `ukmo` → `ukmo_global_deterministic_10km`、`gem` → `cmc_gem_gdps`、`arpege` →
  `meteofrance_arpege_world`、`cma` → `cma_grapes_global`。GEM Global 照 2026-10-24 的文件頁
  （預報 API 與 Previous Runs API 的模式清單都是 `cmc_gem_gdps`，GEM API 頁的範例是
  `cmc_gem_seamless`；舊名 `gem_global` 的 metadata 路徑 404），不是提示詞預計的 `gem_global`
- 變數：逐時 `wind_speed_10m`、`wind_direction_10m`、`wind_gusts_10m`、`precipitation`，每個都帶
  `_previous_day0`…`_previous_day5`（`PREVIOUS_DAYS`），`wind_speed_unit=kn`、`timezone=UTC`。
  `wind_gusts_10m` 是前一小時最大陣風、`precipitation` 是前一小時的量（同 `openmeteo.py`）
- **一個模式一個請求**、每個請求一次帶全部機場的座標（同 `openmeteo.py`；回應是 list，照座標順序）：
  模式代號不對或那個模式沒存，只有那個模式失敗，其他照抓。`start_date`／`end_date` 是 UTC 日期，
  回來的小時再切到 [`start`, `end`]
- 某個模式的陣風在整個回應裡全是 null（例如 JMA GSM，`openmeteo.py`）→ 那個模式每行
  `gustEstimated: true`、`gustKt: null`，報告用平均風 × 機場的估算係數 G
- 一行三個值（`windKt`、`gustKt`、`precipMm`）都是 null 的不寫（那一報還沒有或沒存），之後重跑還能補

加權呼叫次數（`openmeteo.weighted_calls`）：一個模式 4 個變數 × 6 個提前天數＝24 個變數，事件期間
不到 14 天 → 2.4 × 26 個機場＝62.4 次；四個模式 249.6 次（< 每分鐘 600、每日 10,000）。

存檔（`append`）：`data` 分支 `history/events/<id>/backfill/openmeteo-<模式 id>.jsonl`，一行一個
`{"t", "icao", "validAt", "previousDay", "windKt", "windDir", "gustKt", "gustEstimated",
"precipMm"}`（`t` 是抓的時間）；**只追加**，同一個（`icao`、`validAt`、`previousDay`）已經有就跳過。

授權同 `openmeteo.py`：Open-Meteo（CC BY 4.0），原始模式 © UK Met Office、ECCC、Météo-France、CMA；
免費版只限非商業。README「資料來源與授權」。
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import requests

from ..config import Airport
from ..timeutil import iso, parse_time
from . import http_get
from .openmeteo import OpenMeteoError, _coords, _locations, _num, _times, weighted_calls

log = logging.getLogger("hongthai")

PREVIOUS_RUNS_URL = "https://previous-runs-api.open-meteo.com/v1/forecast"
# id → Open-Meteo 的模式代號（照 README 的顯示順序）
MODELS = {
    "ukmo": "ukmo_global_deterministic_10km",
    "gem": "cmc_gem_gdps",
    "arpege": "meteofrance_arpege_world",
    "cma": "cma_grapes_global",
}
VARS = ("wind_speed_10m", "wind_direction_10m", "wind_gusts_10m", "precipitation")
PREVIOUS_DAYS = tuple(range(6))
TIMEOUT_S = 90
PAUSE_S = 2.0  # 模式之間停一下（每分鐘上限 600 加權次，四個模式一共 249.6）
FILE = "openmeteo-{model}.jsonl"


@dataclass
class ModelResult:
    """一個模式回補的結果；`error` 不是 None 就是那個模式失敗（`rows` 空的）。"""

    model: str
    rows: list[dict] = field(default_factory=list)
    gust_estimated: bool | None = None
    bytes: int = 0
    seconds: float = 0.0
    calls: float = 0.0
    empty: int = 0  # 三個值都是 null、沒寫的行數
    error: str | None = None


def var_name(var: str, day: int) -> str:
    return f"{var}_previous_day{day}"


def params(
    model: str, points: list[tuple[float, float]], start: datetime, end: datetime
) -> dict[str, object]:
    return {
        **_coords(points),
        "models": MODELS[model],
        "hourly": ",".join(var_name(v, d) for v in VARS for d in PREVIOUS_DAYS),
        "start_date": f"{start:%Y-%m-%d}",
        "end_date": f"{end:%Y-%m-%d}",
        "wind_speed_unit": "kn",
        "timezone": "UTC",
    }


def calls(n_locations: int, start: datetime, end: datetime) -> float:
    days = (end.date() - start.date()).days + 1
    return weighted_calls(len(VARS) * len(PREVIOUS_DAYS), 1, days, n_locations)


def _column(hourly: dict, key: str, n: int) -> list[float | None]:
    vals = hourly.get(key)
    if not isinstance(vals, list):
        return [None] * n
    return [_num(v) for v in vals[:n]] + [None] * max(0, n - len(vals))


def _r1(v: float | None) -> float | None:
    return None if v is None else round(v, 1)


def parse(
    doc: object, icaos: list[str], start: datetime, end: datetime, fetched: datetime
) -> tuple[list[dict], bool, int]:
    """Previous Runs 的回應（一個模式）→（行, 陣風是不是估算, 三個值都 null 沒寫的行數）。
    只留 `start` ≤ `validAt` ≤ `end` 的小時；風速單位不是 kn 丟 `OpenMeteoError`。"""
    locs = _locations(doc, len(icaos), "Previous Runs")
    cols: list[tuple[str, list[datetime], dict[tuple[str, int], list[float | None]]]] = []
    any_gust = False
    for icao, loc in zip(icaos, locs, strict=True):
        hourly = loc.get("hourly") or {}
        times = _times(hourly)
        units = loc.get("hourly_units") or {}
        for d in PREVIOUS_DAYS:
            key = var_name("wind_speed_10m", d)
            if key in units and units[key] != "kn":
                raise OpenMeteoError(
                    f"Open-Meteo Previous Runs 的 {key} 單位是 {units[key]!r}，不是 kn", "bad_units"
                )
        c = {
            (v, d): _column(hourly, var_name(v, d), len(times)) for v in VARS for d in PREVIOUS_DAYS
        }
        any_gust = any_gust or any(
            x is not None for d in PREVIOUS_DAYS for x in c[("wind_gusts_10m", d)]
        )
        cols.append((icao, times, c))
    estimated = not any_gust
    rows: list[dict] = []
    empty = 0
    for icao, times, c in cols:
        for i, t in enumerate(times):
            if not start <= t <= end:
                continue
            for d in PREVIOUS_DAYS:
                wind, gust = c[("wind_speed_10m", d)][i], c[("wind_gusts_10m", d)][i]
                precip = c[("precipitation", d)][i]
                if wind is None and gust is None and precip is None:
                    empty += 1
                    continue
                rows.append(
                    {
                        "t": iso(fetched),
                        "icao": icao,
                        "validAt": iso(t),
                        "previousDay": d,
                        "windKt": _r1(wind),
                        "windDir": _r1(c[("wind_direction_10m", d)][i]),
                        "gustKt": None if estimated else _r1(gust),
                        "gustEstimated": estimated,
                        "precipMm": _r1(precip),
                    }
                )
    rows.sort(key=lambda r: (r["validAt"], r["previousDay"], icaos.index(r["icao"])))
    return rows, estimated, empty


def _reason(e: OpenMeteoError) -> str:
    """HTTP 錯誤時 Open-Meteo 的回應是 `{"error": true, "reason": …}`，把 reason 接上。"""
    resp = getattr(e.__cause__, "response", None)
    try:
        reason = resp.json().get("reason") if resp is not None else None
    except ValueError:
        reason = None
    return f"{e}（{reason}）" if reason else str(e)


def fetch_model(
    model: str,
    airports: list[Airport],
    start: datetime,
    end: datetime,
    fetched: datetime,
    session: requests.Session | None = None,
) -> ModelResult:
    """抓一個模式；失敗不丟例外，記在 `ModelResult.error`。"""
    t0 = time.monotonic()
    icaos = [a.icao for a in airports]
    points = [(a.lat, a.lon) for a in airports]
    res = ModelResult(model, calls=calls(len(points), start, end))
    try:
        r = http_get(
            PREVIOUS_RUNS_URL,
            session=session,
            params=params(model, points, start, end),
            retries=2,
            timeout=TIMEOUT_S,
            error=OpenMeteoError,
        )
        res.bytes = len(r.content)
        try:
            doc = r.json()
        except ValueError as e:
            raise OpenMeteoError("Open-Meteo Previous Runs 回傳不是 JSON", "bad_json") from e
        res.rows, res.gust_estimated, res.empty = parse(doc, icaos, start, end, fetched)
    except OpenMeteoError as e:
        res.error = _reason(e)
        log.warning("Open-Meteo Previous Runs %s（%s）失敗：%s", model, MODELS[model], res.error)
    res.seconds = round(time.monotonic() - t0, 1)
    return res


def path_for(event_dir: Path, model: str) -> Path:
    return event_dir / "backfill" / FILE.format(model=model)


def row_key(row: dict) -> tuple:
    return (row["icao"], str(parse_time(row["validAt"])), int(row["previousDay"]))


def append(path: Path, rows: Iterable[dict]) -> int:
    """只追加：同一個（`icao`、`validAt`、`previousDay`）檔裡已經有就跳過。回傳寫了幾行。"""
    seen: set[tuple] = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                seen.add(row_key(json.loads(line)))
            except (ValueError, KeyError, TypeError, AttributeError):
                continue  # 壞掉的行不擋新的
    new = []
    for row in rows:
        k = row_key(row)
        if k not in seen:
            seen.add(k)
            new.append(row)
    if new:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            for row in new:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return len(new)


def backfill(
    event_dir: Path,
    airports: list[Airport],
    start: datetime,
    end: datetime,
    fetched: datetime,
    models: Iterable[str] = MODELS,
    pause: Callable[[float], None] = time.sleep,
) -> dict[str, tuple[ModelResult, int]]:
    """四個模式一個一個抓、各自追加進 `backfill/openmeteo-<模式>.jsonl`；回傳每個模式的
    （結果, 寫了幾行）。一個模式失敗不影響其他。"""
    out: dict[str, tuple[ModelResult, int]] = {}
    with requests.Session() as session:
        for i, model in enumerate(models):
            if i:
                pause(PAUSE_S)
            res = fetch_model(model, airports, start, end, fetched, session)
            if res.error:
                out[model] = (res, 0)
                continue
            written = append(path_for(event_dir, model), res.rows)
            log.info(
                "Open-Meteo Previous Runs %s：%d bytes、%.1f 秒、加權 %.1f 次；%d 行（寫了 %d）、"
                "空的 %d、陣風%s",
                model,
                res.bytes,
                res.seconds,
                res.calls,
                len(res.rows),
                written,
                res.empty,
                "估算" if res.gust_estimated else "有",
            )
            out[model] = (res, written)
    return out
