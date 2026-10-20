"""估算陣風的係數 G（HD18，Shawn 2026-10-20 定案）：AIFS、AIGFS 沒有陣風，用 10 米平均風 × G 估算。
HD16 起 JMA GSM 與 WeatherNext 2 系集（每個成員）也用同一個 G；ICON 有陣風、不估算。新模式**不進
樣本**（G 照 HD19 只用 IFS）。

G＝陣風 ÷ 10 米平均風，用 IFS 與 GFS **各自**的資料、同一模式同一機場同一格自己比自己（拿 AIFS／
AIGFS 去比 HRES 陣風不公平：颱風路線不同時同一格本來就差很多）：
- 樣本：一格一個比例。IFS＝該格的 `hresGustKt` ÷ 格結束步長的 10 米平均風（`ec_wind_for_slot`）；
  GFS＝該格的 `gustKt` ÷ 同一時間點（格內陣風最大那一點）的平均風（`gfs_wind_for_slot`）。兩個都
  先取一位小數（和 `latest.json` 的數字一樣），比例取兩位小數。平均風 < 10 節的格不收
  （`GUST_FACTOR_MIN_WIND_KT`）
- 每個機場一個 G：最近 30 天（`GUST_FACTOR_WINDOW_DAYS`，用每一行的 `run` 比）、每報每格，
  **只用 IFS** 的比例取中位數（HD19，`G_SOURCE`），再夾在 1.2～2.0（`GUST_FACTOR_RANGE`；夾中位數，
  不夾樣本）
- 樣本不足的順序（`basis`）：機場的 IFS 合格樣本 ≥ 40（`GUST_FACTOR_MIN_SAMPLES`）→ `airport30d`；
  不然全部機場合併的 30 天 IFS ≥ 40 → `all30d`；不然這一報的全部機場、全部格有 IFS 樣本 → `run`；
  這一報一個合格的 IFS 格都沒有 → 1.4（`GUST_FACTOR_DEFAULT`）、`default`
- 首報（30 天窗裡除了這一報沒有別的報，例如 `history/gustfactor/` 還沒有）一律 `run`：那時「30 天」
  就只有這一報，標 `airport30d`／`all30d` 會誤導
- `10fg` 是時段內最大陣風、`GUST` 是時間點的陣風，定義不同。HD18 先合併取中位數；首報 IFS 約
  1.65、GFS 約 1.27，HD19（Shawn 2026-10-20 11:24）起只用 IFS：每格看的是 6 小時內最大陣風，和
  `10fg` 一致。GFS 的樣本照收照存，30 天後用 `tools/gust_factor_report.py`（IFS、GFS 分開印）
  一起檢討

檔案（`--archive` 的 `history/gustfactor/`，不進 Pages、不進 `latest.json`）：
- `<YYYY-MM>.jsonl`：一行一報一機場 `{"run", "icao", "ifs": [比例…], "gfs": [比例…]}`，照格的順序、
  只存合格的；模式失敗（沿用舊資料）的那一報那個模式寫 `[]`。月份是 `run` 的 UTC 月份
- `latest.json`：這一報算出的係數 `{"generatedAt", "source", "window": {"from", "to"},
  "all": {"g", "n", "nIfs", "nGfs"}, "run": {同 all，只算這一報},
  "airports": {icao: {"g", "n", "nIfs", "nGfs", "basis"}}}`；`source` 是 G 用哪個模式的樣本
  （`"ifs"`）；`all`／`run` 的 `g` 是夾過的 IFS 中位數，沒有 IFS 樣本時 null；`n` 是 IFS 的樣本數
  （和 `nIfs` 一樣，`nGfs` 只是備查）；`airports[].n` 是那個機場 30 天的 IFS 樣本數
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median

from . import assess
from .assess import GustFactor
from .config import (
    GUST_FACTOR_DEFAULT,
    GUST_FACTOR_MIN_SAMPLES,
    GUST_FACTOR_MIN_WIND_KT,
    GUST_FACTOR_RANGE,
    GUST_FACTOR_WINDOW_DAYS,
    Airport,
)
from .sources.ecmwf import EcmwfData
from .sources.gfs import GfsData
from .timeutil import iso, parse_time

log = logging.getLogger("hongthai")

SAMPLE_MODELS = ("ifs", "gfs")
# G 只用哪個模式的樣本（HD19）；之後改回合併或改 GFS 改這裡，`latest.json` 的 `source` 跟著
G_SOURCE = "ifs"

Samples = dict[str, dict[str, list[float]]]  # icao → {"ifs": [...], "gfs": [...]}


def ratio(gust_kt: object, wind_kt: object) -> float | None:
    """陣風 ÷ 平均風（兩位小數）；平均風 < 10 節或缺一個回 None。"""
    g, w = assess._num(gust_kt), assess._num(wind_kt)
    if g is None or w is None or w < GUST_FACTOR_MIN_WIND_KT:
        return None
    return round(g / w, 2)


def run_samples(
    ec: EcmwfData | None,
    gf: GfsData | None,
    airports: Sequence[Airport],
    slots: Sequence[tuple[datetime, datetime]],
) -> Samples:
    """這一報每個機場的樣本（照格的順序）。`ec`／`gf` 是 None（失敗、沿用舊資料）時那個模式
    是 `[]`。"""
    out: Samples = {}
    for a in airports:
        ifs: list[float] = []
        gfs: list[float] = []
        point = ec.points.get(a.icao) if ec else None
        pts = gf.points.get(a.icao) if gf else None
        for start, end in slots:
            if point is not None:
                gust = assess.ec_for_slot(point, start, end)["hresGustKt"]
                r = ratio(gust, assess.ec_wind_for_slot(point, start, end))
                if r is not None:
                    ifs.append(r)
            if pts is not None:
                gust = assess.gfs_for_slot(pts, start, end)["gustKt"]
                r = ratio(gust, assess.gfs_wind_for_slot(pts, start, end))
                if r is not None:
                    gfs.append(r)
        out[a.icao] = {"ifs": ifs, "gfs": gfs}
    return out


def sample_path(history: Path, t: datetime) -> Path:
    return history / "gustfactor" / f"{t:%Y-%m}.jsonl"


def rows_of(run: str, samples: Samples) -> list[dict]:
    return [
        {"run": run, "icao": icao, **{m: s[m] for m in SAMPLE_MODELS}}
        for icao, s in samples.items()
    ]


def append_samples(history: Path, now: datetime, samples: Samples) -> Path:
    path = sample_path(history, now)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for row in rows_of(iso(now), samples):
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


def _months(since: datetime, until: datetime) -> list[datetime]:
    out, t = [], since.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    while t <= until:
        out.append(t)
        t = (t + timedelta(days=32)).replace(day=1)
    return out


def _valid_row(row: object) -> bool:
    return (
        isinstance(row, dict)
        and isinstance(row.get("run"), str)
        and isinstance(row.get("icao"), str)
        and all(isinstance(row.get(m), list) for m in SAMPLE_MODELS)
    )


def load_window(history: Path, now: datetime, days: int = GUST_FACTOR_WINDOW_DAYS) -> list[dict]:
    """最近 `days` 天（`run` 在 [now − days, now]）的樣本行，跨月讀兩個（或以上）月份的檔。
    同一報同一機場有兩行時取後面的；格式不對的行跳過。"""
    since = now - timedelta(days=days)
    rows: dict[tuple[str, str], dict] = {}
    for month in _months(since, now):
        path = sample_path(history, month)
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
                t = parse_time(row["run"]) if _valid_row(row) else None
            except (ValueError, KeyError, TypeError):
                continue
            if t is not None and since <= t <= now:
                rows[(row["run"], row["icao"])] = row
    return list(rows.values())


def _nums(values: Iterable[object]) -> list[float]:
    return [v for v in values if assess._num(v) is not None]  # type: ignore[misc]


def clamp(g: float) -> float:
    lo, hi = GUST_FACTOR_RANGE
    return round(min(hi, max(lo, g)), 2)


def summary(rows: Iterable[dict]) -> dict:
    """一群樣本行 → `{"g", "n", "nIfs", "nGfs"}`（HD19：`g` 是夾過的 IFS 中位數，沒有 IFS 樣本時
    None；`n` 是 IFS 的樣本數，門檻比的是它；`nGfs` 只是備查）。"""
    by: dict[str, list[float]] = {m: [] for m in SAMPLE_MODELS}
    for row in rows:
        for m in SAMPLE_MODELS:
            by[m] += _nums(row.get(m) or [])
    used = by[G_SOURCE]
    return {
        "g": clamp(median(used)) if used else None,
        "n": len(used),
        "nIfs": len(by["ifs"]),
        "nGfs": len(by["gfs"]),
    }


def compute(
    rows: Sequence[dict], run: str, icaos: Iterable[str]
) -> tuple[dict[str, GustFactor], dict]:
    """30 天窗的樣本行（含這一報 `run` 的）→ 每個機場的 G 與 `history/gustfactor/latest.json` 的
    `all`／`run`／`airports`。"""
    all_s = summary(rows)
    run_s = summary(r for r in rows if r["run"] == run)
    first = all(r["run"] == run for r in rows)  # 首報：窗裡只有這一報
    factors: dict[str, GustFactor] = {}
    airports: dict[str, dict] = {}
    for icao in icaos:
        mine = summary(r for r in rows if r["icao"] == icao)
        if not first and mine["n"] >= GUST_FACTOR_MIN_SAMPLES:
            f = GustFactor(mine["g"], "airport30d")
        elif not first and all_s["n"] >= GUST_FACTOR_MIN_SAMPLES:
            f = GustFactor(all_s["g"], "all30d")
        elif run_s["g"] is not None:
            f = GustFactor(run_s["g"], "run")
        else:
            f = GustFactor(GUST_FACTOR_DEFAULT, "default")
        factors[icao] = f
        airports[icao] = {**mine, "g": f.g, "basis": f.basis}
    return factors, {"all": all_s, "run": run_s, "airports": airports}


def update(
    history: Path, now: datetime, samples: Samples, icaos: Iterable[str]
) -> dict[str, GustFactor]:
    """這一報的樣本追加到 `<YYYY-MM>.jsonl`、讀 30 天窗算每個機場的 G、寫 `latest.json`。

    寫檔失敗只 log（G 照算：這一報的樣本直接用記憶體裡的）。"""
    run = iso(now)
    assert run is not None
    try:
        append_samples(history, now, samples)
    except OSError as e:
        log.warning("陣風係數樣本寫不進 %s：%s", sample_path(history, now), e)
    rows = [r for r in load_window(history, now) if r["run"] != run] + rows_of(run, samples)
    factors, doc = compute(rows, run, icaos)
    out = {
        "generatedAt": run,
        "source": G_SOURCE,
        "window": {"from": iso(now - timedelta(days=GUST_FACTOR_WINDOW_DAYS)), "to": run},
        **doc,
    }
    path = history / "gustfactor" / "latest.json"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    except OSError as e:
        log.warning("陣風係數寫不進 %s：%s", path, e)
    a = doc["all"]
    log.info(
        "陣風係數（只用 IFS）：30 天全機場 %s（IFS %d 個樣本；GFS %d 個照存），這一報 %s（%d 個）",
        a["g"],
        a["n"],
        a["nGfs"],
        doc["run"]["g"],
        doc["run"]["n"],
    )
    return factors
