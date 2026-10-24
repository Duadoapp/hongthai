"""組 `latest.json` 與 `history/`，寫到發布目錄。`python -m hongthai.build` 執行。

目錄：
- `--archive`（預設 `data/`，Actions 裡是 `data` 分支的 checkout）：長期保存
  - `latest.json`、`history/<YYYYMMDDTHHMM>Z.json`（每次的結果）
  - `history/raw/<YYYY-MM-DD>/<HHMM>Z-<來源>.json`（TAF、METAR、天文台、氣象署、SMG、NWS、JMA
    原始回應；SMG 是 XML，存成 `{語言: XML 原文}` 的 JSON；氣象署天氣特報 `W-C0033-001` 是另一個檔
    `-cwa-hazards.json`，HD8，`-cwa.json` 維持颱風警報原文；金門、馬祖的局屬站觀測 `O-A0003-001` 是
    `-cwa-obs.json`，HD13；JMA 是 `{office 代碼: 回應}`，HD9；Open-Meteo 是
    `{"forecast": 回應, "ensemble": 回應}`、不縮排（約 1.2 MB），HD16；SWIC 是
    `{"wmoAll": 中韓菲三國的清單摘錄, "caps": {url: CAP 原文}, "capErrors": {url: 原因}}`，HD29）
  - `history/cancellations/<YYYY-MM-DD>.json`（每機場每 6 小時格的航班取消／延誤統計，日期是格的
    UTC 日期；合併規則見 `cancellations.py`。原始航班資料不存）
  - `history/timing/<YYYY-MM>.jsonl`（每次 build 每個來源的耗時，一行一筆，見 `Timing`）
  - `history/cancellations/unknown-statuses.json`（航班狀態對照表沒列的字串與次數，見
    `cancellations.store_unknown`）
  - `history/ai/<YYYY-MM-DD>.json`（AI 對決戰績）、`history/ai/calls-<YYYY-MM-DD>.json`（每個模型
    今天呼叫了幾次；HD5，見 `ai/run.py`）
  - `history/gustfactor/<YYYY-MM>.jsonl`（每報每機場 IFS、GFS 的「陣風÷平均風」樣本）與
    `history/gustfactor/latest.json`（這一報算出的每機場估算陣風係數；HD18，見 `gustfactor.py`）
  - `history/events/<id>/<YYYYMMDDTHHMM>Z.json`：`generatedAt` 落在 `events.json` 某個事件
    期間內的報，`history/<時間>.json` 原樣再存一份（HD20，`events.snapshot`；每小時的 METAR
    與颱風現報也在 `history/events/<id>/` 底下，由 `python -m hongthai.events hourly` 寫）
  - `history/events/<id>/tracks/<起報時間>-<模式>.json`：事件期間每個模式每一報的颱風路徑（HD21，
    `tracks.py`；來源 `tracks`，見下面）
  - `history/events/<id>/wn3/<起報時間>.json`：WeatherNext 3 每格的數字（HD15，`wn3report.py`）
- `--out`（預設 `public/`，GitHub Pages 發布的內容）：`latest.json` 與最近 7 天的
  `history/<YYYYMMDDTHHMM>Z.json`（`PAGES_HISTORY_DAYS`，H9；只放結果，不放原始快照與航班統計），
  以及每個機場一張分享預覽圖 `og/<iata 小寫>.png`（HD1，`og.py`；每報重畫，不進 `data` 分支）

失敗處理：單一來源失敗記在 `sources.<名稱>`，其他照出。整個流程失敗（例外沒接到）時不產生新的
`latest.json`，改用上一份（先找 `--archive` 裡的，沒有就從 Pages 網址抓）重新發布，並回傳非 0。
預覽圖在 `publish()` 之後畫（`draw_og`，改發布上一份時也用那一份畫），畫不出來只 log，不影響回傳值。

AI 對決（HD5，`ai/`）：組好 `latest.json`、模式沿用之後，在寫檔之前跑（`run_ai`）。
走 `_call("ai", …)`、預算 `BUDGET_S["ai"]`；兩個模型平行呼叫，超時的機場記 `error: "timeout"`。
AI 失敗不影響 `latest.json` 其他內容：頂層 `ai`、每個機場的 `ai`、`sources.ai` 一定會有
（細節見 `ai/run.py`）。每日呼叫次數與對決戰績寫在 `--archive` 的 `history/ai/`
（不進 Pages、不進 `latest.json`）。

時間預算（H7）：每個來源（含航班）在 daemon 執行緒裡跑，最多等 `BUDGET_S` 秒；超過就記
`sources.<名稱> = {"ok": false, "error": "timeout", "seconds": <預算>}`、不等它，繼續下一個來源
（被放棄的執行緒怎麼收尾見 `budget.py`）。

模式沿用（H7；H10 改成往前找）：`ecmwf`、`gfs`、`aifs`、`aigfs`（HD14）失敗時，從「最近一份有該模式
資料」的結果把同一機場、同一 `from` 的 `model.ec`／`model.gfs`（AIFS、AIGFS 是 `model.models[]` 裡
同 `id` 那筆）抄過來，等級與投票照常算（`reuse_models`）。哪一份由
`find_reuse_source` 找：`--archive` 的 `history/<時間>.json` 由新到舊，第一份 `sources.<名稱>.ok` 是
`true`（自己也在沿用的不算）而且 `runs.<鍵>` 離現在 `REUSE_MAX_AGE`（24 小時）內的；archive 裡找不到
才退回上一份 `latest.json`（`previous_latest`，H7 的做法）。`sources.<名稱>.ok` 維持 `false`，另加
`reusedFrom`（那一份的 `generatedAt`）；`runs` 用那一份的（舊預報的真實時次）。模式時次超過 24 小時
就不沿用（系集與 HRES 各自判斷），所以連續失敗時 24 小時後自然停掉。TAF、METAR、警報不沿用。
Open-Meteo 的三個模式（`openmeteo`，HD16）也**不沿用**：失敗那一報 `models[]` 那三筆全是 null、不算
分母，等級照其他五票算（避免把 24 小時前的 WeatherNext 2 當今天的票）。別的模式沿用時 `_rescore`
重組 `models[]`，這三筆用的是這一報自己的數字。

颱風路徑（HD21，`tracks.py`）：有事件在期間內時，GFS、AIGFS、AIFS 多抓海平面氣壓（`mslp=True`），
四個模式抓完後跑來源 `tracks`（`BUDGET_S["tracks"]`）：IFS／系集抓 ECMWF 路徑產品、另外三個從氣壓場
找中心，寫 `history/events/<id>/tracks/`。`latest.json` 只多 `sources.tracks`（`ok`、`seconds`、
`bytes`；有模式抽不出來時 `ok: false`、`error: "partial"`，其他照寫）；期間外不跑、沒有
`sources.tracks`。

WeatherNext 3（HD15，`sources/wn3.py`、`wn3report.py`）：模式由 `config.WN3_MODE`（環境變數
`WN3_MODE`）決定。`report-only`（預設，條款的結論）：`latest.json` 沒有 WN3（只有 `sources.wn3`），
只在「5 天前那一報」（`wn3report.report_run`，資料已經是 CC BY 4.0）的起報時間落在事件期間時跑
來源 `wn3`，寫 `history/events/<id>/wn3/` 與路徑檔；`observe`：每報抓最新一報進 `models[]`
（`voting` 看 `WN3_VOTING`），事件期間也寫事件檔、路徑由來源 `tracks` 一起抽。不沿用舊資料。
核准前 `sources.wn3` 是 `ok: false`（`http_403` 之類），是預期的。

排程與跳過（HD25）：`build.yml` 由 Cloudflare 排程 Worker（`cloudflare/trigger/`，主）與
GitHub 自己的 cron（備援）各觸發一次。`--trigger` 是 `cloudflare`／`schedule` 時，開頭（下載任何
模式之前）算出這個時段的排定時間（`SLOTS` 裡 ≤ 開始時間的最近一個，`slot_of`）；`--archive` 的
`latest.json`（`data` 分支最新快照；`concurrency: build` 排隊的第二個進來時，第一個已經推上去了）
的 `generatedAt` ≥ 排定時間就跳過（`already_built`）：不產生、不發布，`timing/` 只記一行
`source: "skip"`，回傳 0。`manual`（手動按的）一律照跑；讀不到上一份時照跑。

估算陣風的係數（HD18）：模式都抓完、組 `latest.json` 之前，用這一報的 IFS、GFS 算樣本、寫進
`history/gustfactor/`、讀 30 天窗算每個機場的 G（`gust_factors`），交給 `assess`。沿用 AIFS／AIGFS
舊數字時，`_rescore` 用抄來的 `windKt` × 這一報的 G 重算估算陣風（`assess.refactor_estimated`）。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
import tempfile
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import requests

from . import assess, budget, cancellations, events, gustfactor, og, tracks, wn3report
from .ai import run as ai
from .config import (
    MODELS,
    Airport,
    ConfirmedPeriod,
    Event,
    Region,
    Thresholds,
    load_airports,
    load_confirmed,
    load_events,
    load_regions,
    wn3_mode,
)
from .sources import (
    aifs,
    aigfs,
    cwa,
    ecmwf,
    flights,
    gfs,
    hko,
    jma,
    nws,
    openmeteo,
    smg,
    swic,
    taf,
    wn3,
)
from .timeutil import floor_6h, iso, parse_time, slot_bounds, utcnow

log = logging.getLogger("hongthai")

SCHEMA = 1
# build.yml 的四個排定時間（UTC，時、分）；Cloudflare Worker 的 cron 同這四個（HD25）
SLOTS = ((1, 5), (8, 25), (13, 5), (20, 25))
TRIGGERS = ("manual", "schedule", "cloudflare")
PAGES_URL = "https://duadoapp.github.io/hongthai/latest.json"
SOURCE_NAMES = (
    "ecmwf",
    "gfs",
    "aifs",
    "aigfs",
    "openmeteo",
    "taf",
    "hko",
    "cwa",
    "smg",
    "nws",
    "jma",
    "swic",
)

# 每個來源的時間預算（秒）。2026-10-18 實測：ecmwf 約 90–240（入口 0.5–1.4 MB/s；H10 起 HRES
# 一報約 82 MB＋系集約 10 MB）、gfs 約 110（NOMADS）、flights 約 20、其他幾秒。HD14 的 aifs
# 約 66 MB、55 秒，aigfs 約 51 MB、38 秒（2026-10-20 雲端開發機實測）。
# 總和 1785 秒（29.75 分鐘，HD3 加 nws 30 秒、HD1 加 og 60 秒、HD5 加 ai 180 秒、HD12 ai 再加
# 60 秒、HD14 加 aifs 180＋aigfs 120 秒、HD21 加 tracks 150 秒、HD9 加 jma 45 秒、HD16 加
# openmeteo 90 秒、HD15 加 wn3 120 秒）；HD29 加 swic 45 秒，總和 1830 秒（30.5 分鐘），還在
# `build.yml` 那一步的 32 分鐘內，workflow 不用改。`build.yml` 那一步的上限是 32 分鐘（HD15 前
# 30、HD16 前 28、HD21 前 25、HD14 前 20、HD12 前 18）。HD16 的 openmeteo 兩個請求約 1.2 MB、2 秒
# （2026-10-20 雲端開發機實測）。
# HD21 的海平面氣壓算在 gfs／aifs／aigfs 自己的預算裡（每個步長約 1.0／0.5／1.0 MB，21 個步長
# 共約 52 MB；2026-10-20 雲端開發機實測）。
BUDGET_S: dict[str, float] = {
    "ecmwf": 300,  # HRES＋系集，含鏡像切換
    "gfs": 180,
    "aifs": 180,  # HD14：ECMWF AIFS Single，鏡像切換同 ecmwf
    "aigfs": 120,  # HD14：NOAA AIGFS，只有 AWS
    # HD16：ICON、JMA GSM、WeatherNext 2 系集，兩個請求各 60 秒逾時、不重試；HD33b 的三個旁觀模式
    # 併在預報那個請求（請求數不變，回應約 0.6 → 1.6 MB）
    "openmeteo": 90,
    # HD15：WeatherNext 3，BigQuery 一個查詢（失敗退 GCS Zarr）＋事件期間的海平面氣壓；核准前每報
    # 幾秒就 `http_403`。`report-only`（預設）只在 5 天前那一報落在事件期間時才跑
    "wn3": 120,
    "tracks": 150,  # HD21：颱風路徑，只在事件期間；ECMWF 路徑產品約 1.3 MB＋解析三個模式的氣壓場
    "taf": 45,  # TAF 與 METAR 同一個來源，各一個請求
    "hko": 30,
    "smg": 30,
    "cwa": 45,  # 颱風警報、天氣特報、局屬站觀測（HD13）各一個請求；實測 1–5 秒
    "nws": 30,  # HD3：關島的颱風警報，一個請求
    "jma": 45,  # HD9：日本與沖繩的大雪警報，一個 office 一個請求（11 個）；實測每個 0.5–1 秒
    # HD29：WMO SWIC（中國氣象局、韓國氣象廳、PAGASA）：清單一個請求（約 0.9 MB、0.6–3 秒）＋要的
    # CAP 原文每則 0.6–1 秒、4 條平行；平時幾則、颱風期間估 10–40 則
    "swic": 45,
    "flights": 120,  # 抓＋統計＋寫檔
    "ai": 240,  # HD5：AI 對決，兩個模型平行，每報最多 20 個機場、單次請求 60 秒；HD12 180 → 240
    "og": 60,  # HD1：51 張分享預覽圖，publish() 之後畫（本機約 3 秒）
}

REUSE_MAX_AGE = timedelta(hours=24)
# GitHub Pages 的 `history/` 只放最近幾天（H9：41 個機場每份約 515 KB）；`data` 分支全部保留
PAGES_HISTORY_DAYS = 7
# 模式來源 → (`model` 裡的鍵, [(`runs` 的鍵, 那一報決定的欄位)])；系集與 HRES 的時次各自判斷期限。
# 節的欄位（HD2）在 HD2 以前的結果裡沒有，抄完由 `_rescore` 用 m/s 欄位補（`assess.fill_kt`）。
# HD8 的雨量、降水型態、能見度一起抄（`ptype` 是字串）；三類的等級不抄，由 `_rescore` 重算。
# HD14：`models.<id>` 是 `model.models[]` 裡 `id` 那筆（不是 `model` 底下的鍵），抄那筆的數字；
# `gustEstimated`、`levels`、`level` 與投票由 `_rescore` 重算。
# HD18：IFS、GFS 那筆的 `windKt` 也抄；AIFS／AIGFS 抄 `windKt` 與舊的 `gustFactor`，估算陣風與側風
# 由 `_rescore` 用這一報的 G 重算。
# 每個來源一串（`model` 裡的位置, `runs` 的鍵, 欄位）；第一個的 `runs` 鍵是
# `find_reuse_source` 判斷用的
REUSE_FIELDS: dict[str, tuple[tuple[str, str, tuple[str, ...]], ...]] = {
    "ecmwf": (
        (
            "ec",
            "ecmwf",
            ("hresGustMs", "hresGustKt", "crosswindKt", "rain6hMm", "ptype", "temp2mC"),
        ),
        ("models.ifs", "ecmwf", ("windKt",)),
        (
            "ec",
            "ecmwfEns",
            ("p10", "p15", "p25", "p29Kt", "p37Kt", "p49Kt", "p24hRain25", "p24hRain50"),
        ),
    ),
    "gfs": (
        ("gfs", "gfs", ("gustMs", "gustKt", "crosswindKt", "rain6hMm", "ptype", "visibilityM")),
        ("models.gfs", "gfs", ("windKt",)),
    ),
    "aifs": (
        (
            "models.aifs",
            "aifs",
            ("windKt", "gustKt", "gustFactor", "crosswindKt", "rain6hMm", "ptype"),
        ),
    ),
    "aigfs": (
        ("models.aigfs", "aigfs", ("windKt", "gustKt", "gustFactor", "crosswindKt", "rain6hMm")),
    ),
}
# `models[].run` ← `runs` 的哪個鍵（HD14）
MODEL_RUN_KEYS = {
    "ifs": "ecmwf",
    "gfs": "gfs",
    "ifs-ens": "ecmwfEns",
    "aifs": "aifs",
    "aigfs": "aigfs",
}


def model_runs(runs: dict) -> dict[str, str | None]:
    """頂層 `runs` → 各模式（`config.MODELS` 的 id）的時次。"""
    return {m.id: runs.get(MODEL_RUN_KEYS.get(m.id, m.id)) for m in MODELS}


def model_part(model: dict, key: str) -> dict | None:
    """`model.ec`／`model.gfs`，或 `models.<id>`：`model.models[]` 裡 `id` 是 `<id>` 的那筆
    （HD14）。"""
    if not key.startswith("models."):
        part = model.get(key)
        return part if isinstance(part, dict) else None
    mid = key.removeprefix("models.")
    entries = model.get("models")
    return (
        next(
            (e for e in entries if isinstance(e, dict) and e.get("id") == mid),
            None,
        )
        if isinstance(entries, list)
        else None
    )


def _dump(path: Path, obj: object, compact: bool = False) -> None:
    """`compact=True`：不縮排（`latest.json` 與 `history/<時間>.json`，HD14 起；每格多了 5 筆
    `models[]`，`indent=1` 時約 3.3 MB、不縮排約 1.9 MB）。原始快照照舊 `indent=1`。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = (
        json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
        if compact
        else json.dumps(obj, ensure_ascii=False, indent=1)
    )
    path.write_text(text + "\n", encoding="utf-8")


class Timing:
    """`history/timing/<YYYY-MM>.jsonl`：每個來源一跑完就 append 一行並關檔，不等全部結束。

    `build.yml` 的「推 data 分支」是 `if: always()`，所以「產生 latest.json」被 Actions 砍掉時，
    已經寫進去的行也會推上去；沒有 `done` 那行就表示那次被砍了。欄位名固定（主對話直接看這個檔）：
    - 開始：`{"run", "source": "start", "ok": true, "seconds": 0, "commit", "trigger", "slot",
      "startedAt", "delayMinutes"}`（HD25）：`trigger` 是 `manual`／`schedule`／`cloudflare`；
      `slot` 是這個時段的排定時間（`manual` 是 null）；`startedAt` 是 job 開始的時間（`build.yml`
      的 `JOB_STARTED_AT`，沒有就是程式開始的時間；含排隊等 `concurrency` 的時間）；
      `delayMinutes` 是 `startedAt − slot`
    - 跳過（HD25）：`{"run", "source": "skip", "ok": true, "seconds": 0, "trigger", "slot",
      "startedAt", "delayMinutes", "generatedAt": <已經出過的那份>}`，只有這一行（沒有
      `start`／`done`）
    - 每個來源：`{"run", "source", "ok", "error", "seconds", "bytes"}`，ecmwf、gfs、aifs、aigfs
      （HD14）多 `mirror`；openmeteo（HD16）多 `calls`（Open-Meteo 的加權呼叫次數，失敗是 null）；
      wn3（HD15）多 `mode`、`via`（`bigquery`／`zarr`）、`estimateBytes`（BigQuery dry run）、
      `bytesBilled`
    - 分享預覽圖（HD1）：`{"run", "source": "og", "ok", "error", "seconds", "bytes": <圖的總大小>}`
    - AI 對決（HD5）：`{"run", "source": "ai", "ok", "error", "seconds", "bytes": 0,
      "calls": {"claude": n, "gemini": n}, "usage": {...}, "costUsd": {"claude": x, "gemini": y},
      "errorMessages": {"claude": 字串或 null, "gemini": 字串或 null}}`
      （`calls` 是這一報的呼叫次數；HD26 的 `usage` 是各模型這一報的 token 合計，鍵同戰績的 `usage`
      再加 `calls`（有回應的次數），`costUsd` 是估計費用（美元），見 `ai/usage.py`；HD30 的
      `errorMessages` 是各模型這一報第一則錯誤的訊息，見 `ai/run.py`）
    - 結束：`{"run", "source": "done", "ok": <有沒有產出 latest.json>, "seconds": <總秒數>}`
    """

    def __init__(self, archive: Path, now: datetime):
        self.path = archive / "history" / "timing" / f"{now:%Y-%m}.jsonl"
        self.run = iso(now)

    def write(self, **fields: object) -> None:
        line = json.dumps({"run": self.run, **fields}, ensure_ascii=False)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError as e:  # 耗時紀錄寫不了不能讓 build 失敗
            log.warning("耗時紀錄寫不進 %s：%s", self.path, e)

    def source(self, name: str, st: dict, ctx: budget.Context) -> None:
        fields: dict[str, object] = {
            "source": name,
            "ok": st["ok"],
            "error": None if st["ok"] else st.get("error"),
            "seconds": st["seconds"],
            "bytes": st.get("bytes", ctx.bytes),
        }
        if name in ("ecmwf", "gfs", "aifs", "aigfs"):
            fields["mirror"] = st.get("mirror", ctx.notes.get("mirror"))
        if name == "ai":
            fields["bytes"] = 0
            fields["calls"] = st.get("calls")
            fields["usage"] = st.get("usage")  # HD26
            fields["costUsd"] = st.get("costUsd")
            fields["errorMessages"] = st.get("errorMessages")  # HD30
        if name == "openmeteo":
            fields["calls"] = st.get("calls")
        if name == "wn3":  # HD15
            for k in ("mode", "via", "estimateBytes", "bytesBilled"):
                fields[k] = st.get(k)
        self.write(**fields)


def _call(
    name: str,
    fn: Callable[[], object],
    status: dict,
    timing: Timing | None = None,
    extra: Callable[[object], dict] | None = None,
    base: dict | None = None,
) -> object | None:
    """在 `BUDGET_S[name]` 秒內跑一個來源；失敗或超時記成 `ok=false`＋原因，回傳 None。

    成功時 `extra(結果)` 回傳的欄位併進 `sources.<名稱>`；`base` 的欄位成功失敗都併進去（HD15
    `wn3` 的 `mode`）。跑完立刻寫一行耗時紀錄。
    """
    limit = BUDGET_S[name]
    out = budget.run(name, fn, limit)
    result = None
    if out.timed_out:
        log.warning("來源 %s 超過 %s 秒的預算，放棄、繼續下一個", name, limit)
        status[name] = {"ok": False, "error": "timeout", "seconds": float(limit)}
    elif out.error is not None:
        e = out.error
        code = getattr(e, "code", None) or e.__class__.__name__
        log.warning(
            "來源 %s 失敗（%s）：%s",
            name,
            code,
            e,
            exc_info=None if hasattr(e, "code") else (type(e), e, e.__traceback__),
        )
        status[name] = {"ok": False, "error": code, "seconds": round(out.seconds, 1)}
    else:
        result = out.result
        status[name] = {"ok": True, "seconds": round(out.seconds, 1)}
        if extra is not None:
            status[name].update(extra(result))
    if base:
        status[name].update(base)
    if timing is not None:
        timing.source(name, status[name], out.context)
    return result


def _ecmwf_extra(ec: ecmwf.EcmwfData) -> dict:
    d: dict[str, object] = {}
    if ec.ens_error:
        d["ensembleOk"] = False
        d["ensembleError"] = ec.ens_error
    d["bytes"] = ec.bytes_downloaded
    if ec.mirror:
        d["mirror"] = ec.mirror
    return d


def _download_extra(g: gfs.GfsData | aifs.AifsData | aigfs.AigfsData) -> dict:
    """gfs、aifs、aigfs（HD14）的 `sources.<名稱>`：下載量與實際的鏡像。"""
    d: dict[str, object] = {"bytes": g.bytes_downloaded}
    if g.mirror:
        d["mirror"] = g.mirror
    return d


def _openmeteo_extra(om: openmeteo.OpenMeteoData) -> dict:
    """`sources.openmeteo`（HD16）：下載量、加權呼叫次數；起報時間問不到的模式記在 `runError`；
    HD33b：丟掉的旁觀模式記在 `modelError`（例如 `"cma:bad_units"`，其他模式照用）。"""
    d: dict[str, object] = {"bytes": om.bytes_downloaded, "calls": om.calls}
    if om.meta_errors:
        d["runError"] = ",".join(f"{k}:{v}" for k, v in om.meta_errors.items())
    if om.model_errors:
        d["modelError"] = ",".join(f"{k}:{v}" for k, v in om.model_errors.items())
    return d


def _wn3_extra(w: wn3.Wn3Data) -> dict:
    """`sources.wn3`（HD15）：哪一報、走哪條路、BigQuery 的估計／實際掃描量與計費量、Zarr 讀的量；
    BigQuery 失敗退到 Zarr 時 `bqError`、海平面氣壓讀不到時 `mslpError`。"""
    d: dict[str, object] = {
        "run": iso(w.run),
        "via": w.via,
        "bytes": w.bytes_downloaded,
        "estimateBytes": w.estimate_bytes,
        "bytesProcessed": w.bytes_processed,
        "bytesBilled": w.bytes_billed,
    }
    if w.bq_error:
        d["bqError"] = w.bq_error
    if w.mslp_error:
        d["mslpError"] = w.mslp_error
    return d


def _is_num(v: object) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool)


def _swic_extra(s: swic.SwicData) -> dict:
    """HD29：這報抓了幾則 CAP（`caps`）；有幾則抓不到時 `capErrors`（則數；那幾則跳過、
    其他照列）。"""
    d: dict[str, object] = {"caps": s.caps}
    if s.cap_errors:
        d["capErrors"] = len(s.cap_errors)
    return d


def _cwa_extra(c: cwa.CwaData) -> dict:
    """氣象署天氣特報（HD8）或局屬站觀測（HD13）那個請求失敗時才有；颱風警報照常算 `ok`。"""
    d: dict[str, object] = {}
    if c.hazards_error is not None:
        d.update(heavyRainOk=False, heavyRainError=c.hazards_error)
    if c.obs_error is not None:
        d.update(obsOk=False, obsError=c.obs_error)
    return d


def _rescore(
    slot: dict,
    th: Thresholds,
    runs: dict[str, str | None] | None = None,
    factor: assess.GustFactor | None = None,
) -> None:
    """模式值換掉之後重算模式層等級、一致性、落差與整格等級（和 `assess.assess_slots` 同一套規則；
    官方層與已確認不受模式影響，維持原樣）。抄來的是 HD2 以前的結果時，先用 m/s 欄位補節的欄位。
    三類等級（HD8）照抄來的雨量重算；依據是模式層的格 `causes` 也重算（官方層的不動）。
    HD14：`models[]` 重組（IFS、GFS、IFS 系集從 `ec`／`gfs`，AIFS、AIGFS 從原本那筆的數字）、
    重新投票（`vote`、`level`）；`runs`（`model_runs` 的結果）沒給時 `models[].run` 維持原值。
    HD18：給了 `factor`（這一報這個機場的 G）時，估算陣風的那幾筆用 `windKt` × G 重算
    （`assess.refactor_estimated`；不沿用舊 G）。"""
    m = slot["model"]
    assess.fill_kt(m["ec"], m["gfs"])
    assess.fill_model_wx(m["ec"], m["gfs"], th)
    old = {e.get("id"): e for e in m.get("models") or [] if isinstance(e, dict)}
    if factor is not None:
        for mod in MODELS:
            if mod.gust_estimated and mod.id in old:
                assess.refactor_estimated(old[mod.id], factor)
    if runs is None:
        runs = {i: e.get("run") for i, e in old.items() if isinstance(i, str)}
    m["models"] = assess.model_entries(m["ec"], m["gfs"], old, runs, th)
    _, m["vote"] = assess.model_vote(m["models"])
    m["level"] = m["vote"]["level"]
    m["agreement"] = assess.agreement(m["ec"], m["gfs"], th)
    if slot["basis"] in ("model", "none"):
        slot["level"], slot["basis"] = (m["level"], "model") if m["level"] else ("unknown", "none")
    off = slot["official"]
    slot["gap"] = off is not None and m["level"] is not None and off["level"] != m["level"]
    causes = assess.slot_causes(slot, th)
    if causes is not None:
        slot["causes"] = causes


def _run_time(doc: dict, run_key: str) -> datetime | None:
    runs = doc.get("runs") if isinstance(doc.get("runs"), dict) else {}
    run = runs.get(run_key)
    try:
        return parse_time(run) if isinstance(run, str) else None
    except ValueError:
        return None


def _history_files(archive: Path) -> list[tuple[datetime, Path]]:
    """`history/<YYYYMMDDTHHMM>Z.json`，由新到舊（檔名不是這個格式的跳過）。"""
    out = []
    for p in (archive / "history").glob("*.json"):
        try:
            t = datetime.strptime(p.stem, "%Y%m%dT%H%MZ").replace(tzinfo=UTC)
        except ValueError:
            continue
        out.append((t, p))
    return sorted(out, reverse=True)


def find_reuse_source(archive: Path, name: str, now: datetime) -> dict | None:
    """由新到舊找第一份 `sources.<name>.ok` 是 `true`、`runs.<主要的鍵>` 在 24 小時內的結果。

    主要的鍵是 `REUSE_FIELDS[name]` 第一個的 `runs` 鍵（ecmwf 是 HRES 的 `ecmwf`，gfs 是 `gfs`）。
    一份結果的 `runs` 不會晚於它的 `generatedAt`，所以檔名早於 `now - REUSE_MAX_AGE` 就不用
    再往前找。
    """
    run_key = REUSE_FIELDS[name][0][1]
    for t, p in _history_files(archive):
        if t >= now:
            continue
        if now - t > REUSE_MAX_AGE:
            break
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            log.warning("歷史結果 %s 讀不了，跳過", p)
            continue
        if not isinstance(doc, dict) or not isinstance(doc.get("generatedAt"), str):
            continue
        sources = doc.get("sources")
        src = sources.get(name) if isinstance(sources, dict) else None
        if not isinstance(src, dict) or src.get("ok") is not True:
            continue
        run_t = _run_time(doc, run_key)
        if run_t is not None and now - run_t <= REUSE_MAX_AGE:
            return doc
    return None


def reuse_models(
    latest: dict,
    prev: dict[str, dict | None],
    failed: list[str],
    now: datetime,
    airports: list[Airport],
    factors: dict[str, assess.GustFactor] | None = None,
) -> None:
    """失敗的模式來源（`ecmwf`／`gfs`／`aifs`／`aigfs`）從 `prev[來源名稱]` 那一份抄同一機場、
    同一 `from` 的值。

    每個來源可以抄不同份（`find_reuse_source` 各自找）。`runs.<鍵>` 離 `now` 超過 `REUSE_MAX_AGE`
    的那一報不抄（系集與 HRES 各自判斷）；有抄到的才把 `runs` 換成那一份的、在 `sources.<名稱>` 加
    `reusedFrom`。`ok`／`error` 不動。`factors` 是這一報每個機場的估算陣風係數（HD18，`_rescore`）。
    """

    def slots_of(doc: dict) -> dict[tuple[object, object], dict]:
        out: dict[tuple[object, object], dict] = {}
        for a in doc.get("airports") or []:
            for s in (a.get("slots") or []) if isinstance(a, dict) else []:
                if isinstance(s, dict) and isinstance(s.get("model"), dict):
                    out[(a.get("icao"), s.get("from"))] = s["model"]
        return out

    # 先算好要改什麼，再一次套用（上一份格式怪也不會改到一半）
    updates: list[tuple[str, dict, str, str, float]] = []
    runs: dict[str, str] = {}
    reused_from: dict[str, str] = {}
    for name in failed:
        doc = prev.get(name)
        if not isinstance(doc, dict) or not isinstance(doc.get("generatedAt"), str):
            continue
        prev_slots = slots_of(doc)
        stale: set[str] = set()
        for key, run_key, fields in REUSE_FIELDS[name]:
            run_t = _run_time(doc, run_key)
            if run_t is None or now - run_t > REUSE_MAX_AGE:
                if run_key not in stale:
                    log.info(
                        "%s 那份的 runs.%s 超過 24 小時或沒有，不沿用", doc["generatedAt"], run_key
                    )
                stale.add(run_key)
                continue
            n = 0
            for a in latest["airports"]:
                for s in a["slots"]:
                    old = model_part(prev_slots.get((a["icao"], s["from"]), {}), key)
                    if old is None or model_part(s["model"], key) is None:
                        continue
                    for f in fields:
                        if _is_num(old.get(f)) or (f == "ptype" and isinstance(old.get(f), str)):
                            updates.append((a["icao"], s, key, f, old[f]))
                            n += 1
            if n:
                runs[run_key] = iso(run_t)
                reused_from[name] = doc["generatedAt"]
    if not updates:
        return

    th = {a.icao: a.thresholds for a in airports}
    touched: dict[int, tuple[dict, str]] = {}
    for icao, s, key, f, v in updates:
        part = model_part(s["model"], key)
        assert part is not None
        part[f] = v
        touched[id(s)] = (s, icao)
    latest["runs"].update(runs)
    by_model = model_runs(latest["runs"])
    for s, icao in touched.values():
        factor = None if factors is None else factors.get(icao, assess.DEFAULT_GUST_FACTOR)
        _rescore(s, th[icao], by_model, factor)
    for name, generated_at in reused_from.items():
        latest["sources"][name]["reusedFrom"] = generated_at
        log.info("%s 失敗，沿用 %s 那份的模式資料（runs：%s）", name, generated_at, runs)


def collect_warnings(
    airport: Airport,
    hko_data: hko.HkoData | None,
    cwa_data: cwa.CwaData | None,
    smg_data: smg.SmgData | None = None,
    nws_data: nws.NwsData | None = None,
    jma_data: jma.JmaData | None = None,
    swic_data: swic.SwicData | None = None,
) -> list[assess.ActiveWarning]:
    out: list[assess.ActiveWarning] = []
    if "hko" in airport.warning_sources and hko_data and hko_data.signal:
        s = hko_data.signal
        out.append(assess.ActiveWarning("hko", "tc_signal", s.level, s.text, s.issued_at, s.code))
    if "hko" in airport.warning_sources and hko_data:  # 暴雨、雷暴（HD8）
        for w in hko_data.warnings:
            out.append(assess.ActiveWarning("hko", w.kind, w.level, w.text, w.issued_at, w.code))
    if "smg" in airport.warning_sources and smg_data and smg_data.signal:
        s = smg_data.signal
        out.append(
            assess.ActiveWarning(
                "smg", "tc_signal", s.level, s.text, s.issued_at, s.code, s.detail or None
            )
        )
    if "cwa" in airport.warning_sources and cwa_data:
        for w in cwa.for_airport(cwa_data.bulletins, airport.cwa_areas, airport.name):
            out.append(
                assess.ActiveWarning(
                    "cwa", w.kind, w.level, w.text, w.issued_at, detail=w.detail or None
                )
            )
        for w in [
            *cwa.heavy_rain_for_airport(cwa_data.hazards, airport.cwa_areas, airport.name),
            *cwa.dense_fog_for_airport(cwa_data.hazards, airport.cwa_areas, airport.name),
            *cwa.strong_wind_for_airport(cwa_data.hazards, airport.cwa_areas),  # HD27
        ]:
            out.append(
                assess.ActiveWarning("cwa", w.kind, w.level, w.text, w.issued_at, detail=w.detail)
            )
    if "nws" in airport.warning_sources and nws_data:
        for w in nws.for_zone(nws_data.alerts, airport.nws_zone):
            out.append(
                assess.ActiveWarning(
                    "nws", w.kind, w.level, w.text, w.issued_at, w.code, w.detail or None
                )
            )
    if "jma" in airport.warning_sources and jma_data and airport.jma_area:
        for j in jma_data.warnings.get(airport.jma_area.class20, []):
            out.append(assess.ActiveWarning("jma", j.kind, j.level, j.text, j.issued_at, j.code))
    if swic_data is not None:  # HD29：cma／kma／pagasa，`for_airport` 只看這個機場有的
        for w in swic.for_airport(swic_data.alerts, airport):
            out.append(
                assess.ActiveWarning(
                    w.source, w.kind, w.level, w.text, w.issued_at, w.code, w.detail
                )
            )
    return out


def warning_json(w: assess.ActiveWarning) -> dict:
    d: dict[str, object] = {
        "source": w.source,
        "kind": w.kind,
        "level": w.level,
        "text": w.text,
        "issuedAt": w.issued_at,
    }
    if w.code:
        d["code"] = w.code
    if w.detail:
        d["detail"] = w.detail
    return d


def metar_json(m: taf.Metar | None) -> dict | None:
    """AviationWeather 的沒有 `source` 鍵；氣象署局屬站觀測（HD13）多 `source: "cwa"`。"""
    if m is None:
        return None
    d: dict[str, object] = {
        "observedAt": iso(m.observed),
        "windDirDeg": m.wdir,
        "windKt": m.wind_kt,
        "gustKt": m.gust_kt,
        "raw": m.raw,
        # HD8：觀測的能見度（公尺，9999＝以上）、天氣現象、雲幕（呎）
        "visibilityM": m.vis_m,
        "wx": list(m.wx),
        "ceilingFt": m.ceiling_ft,
    }
    if m.source:
        d["source"] = m.source
    return d


def station_metar(
    airport: Airport, tf: taf.TafData | None, cw: cwa.CwaData | None
) -> taf.Metar | None:
    """AviationWeather 的 METAR；沒有時用氣象署局屬站觀測（`cwaStation`，HD13）。"""
    metar = tf.metars.get(airport.icao) if tf else None
    if metar is None and airport.cwa_station and cw is not None:
        metar = cw.obs.get(airport.cwa_station)
    return metar


def main_period(t: taf.TafInfo, now: datetime | None = None) -> taf.TafPeriod | None:
    """TAF 的主時段：涵蓋 `now` 的主時段（FM／BECMG 之後的也算主時段），沒有就第一個還沒結束的、
    再沒有就第一個。"""
    mains = [p for p in t.periods if p.kind == "main"]
    if now is not None:
        cover = [p for p in mains if p.start <= now < p.end]
        if cover:
            return cover[-1]
        mains = [p for p in mains if p.end > now] or mains
    return mains[0] if mains else None


def taf_json(t: taf.TafInfo | None, now: datetime | None = None) -> dict | None:
    if t is None:
        return None
    main = main_period(t, now)
    return {
        "issuedAt": iso(t.issued),
        "validFrom": iso(t.valid_from),
        "validTo": iso(t.valid_to),
        "raw": t.raw,
        # HD8：主時段的能見度、天氣現象、雲幕
        "visibilityM": main.vis_m if main else None,
        "wx": list(main.wx) if main else [],
        "ceilingFt": main.ceiling_ft if main else None,
    }


def confirmed_json(c: ConfirmedPeriod) -> dict:
    return {"from": iso(c.start), "to": iso(c.end), "note": c.note}


def assemble(
    *,
    now: datetime,
    regions: list[Region],
    airports: list[Airport],
    confirmed: list[ConfirmedPeriod],
    status: dict,
    ec: ecmwf.EcmwfData | None,
    gf: gfs.GfsData | None,
    tf: taf.TafData | None,
    hk: hko.HkoData | None,
    cw: cwa.CwaData | None,
    sm: smg.SmgData | None = None,
    nw: nws.NwsData | None = None,
    af: aifs.AifsData | None = None,
    ag: aigfs.AigfsData | None = None,
    factors: dict[str, assess.GustFactor] | None = None,
    jm: jma.JmaData | None = None,
    om: openmeteo.OpenMeteoData | None = None,
    wn: wn3.Wn3Data | None = None,
    sw: swic.SwicData | None = None,
) -> dict:
    """純組裝：各來源結果（失敗的是 None）→ `latest.json` 的 dict。`factors` 是每個機場估算陣風的
    係數（HD18；沒有的機場用 1.4、`default`）。`om` 是 Open-Meteo 的三個模式（HD16）。`wn` 是
    WeatherNext 3（HD15）：只有 `MODELS` 裡有 `wn3`（`observe` 模式）才寫進 `runs` 與
    `models[]`。"""
    slots = slot_bounds(now)
    window_start, window_end = slots[0][0], slots[-1][1]
    runs = {
        "ecmwf": iso(ec.run) if ec else None,
        "ecmwfEns": iso(ec.ens_run) if ec else None,
        "gfs": iso(gf.run) if gf else None,
        "aifs": iso(af.run) if af else None,  # HD14
        "aigfs": iso(ag.run) if ag else None,
        # HD16：Open-Meteo 的 metadata 給的最近一報（`sources/openmeteo.py`）
        **{mid: iso(om.runs.get(mid)) if om else None for mid in openmeteo.META_URLS},
    }
    observe_wn3 = any(m.id == assess.WN3_ID for m in MODELS)
    if observe_wn3:
        runs[assess.WN3_ID] = iso(wn.run) if wn else None
    by_model = model_runs(runs)
    out_airports = []
    for a in airports:
        warns = collect_warnings(a, hk, cw, sm, nw, jm, sw)
        mine = [c for c in confirmed if c.airport == a.icao]
        taf_info = tf.tafs.get(a.icao) if tf else None
        metar = station_metar(a, tf, cw)
        slot_list = assess.assess_slots(
            now=now,
            slots=slots,
            thresholds=a.thresholds,
            ec=ec.points.get(a.icao) if ec else None,
            gfs=gf.points.get(a.icao) if gf else None,
            taf_periods=taf_info.periods if taf_info else None,
            warnings=warns,
            confirmed=mine,
            runways=a.runways,
            metar=metar,
            aifs=af.points.get(a.icao) if af else None,
            aigfs=ag.points.get(a.icao) if ag else None,
            runs=by_model,
            gust_factor=(factors or {}).get(a.icao, assess.DEFAULT_GUST_FACTOR),
            icon=om.hourly["icon"].get(a.icao) if om else None,
            jma=om.hourly["jma"].get(a.icao) if om else None,
            wn2=om.ensemble.get(a.icao) if om else None,
            # HD33b：三個旁觀模式
            om_hourly={
                mid: om.hourly.get(mid, {}).get(a.icao) if om else None
                for mid in openmeteo.OBSERVER_MODELS
            },
            wn3=wn.points.get(a.icao) if wn and observe_wn3 else None,
        )
        out_airports.append(
            {
                "icao": a.icao,
                "iata": a.iata,
                "tz": a.tz,
                "name": a.name,
                "region": a.region,
                # 有沒有接官方警報來源（H9）；false 的機場網頁顯示「官方警報：尚未提供」
                "official": {"warnings": bool(a.warning_sources)},
                # 接了哪些官方警報來源（HD29）：cwa／hko／smg／nws／jma／cma／kma／pagasa，沒接是 []
                "warningSources": list(a.warning_sources),
                "warnings": [warning_json(w) for w in warns],
                "metar": metar_json(metar),
                "taf": taf_json(taf_info, now),
                "slots": slot_list,
                "confirmed": [
                    confirmed_json(c) for c in mine if c.start < window_end and c.end > window_start
                ],
            }
        )
    return {
        "schema": SCHEMA,
        "generatedAt": iso(now),
        "runs": runs,
        "sources": {
            **{n: status.get(n, {"ok": False, "error": "skipped"}) for n in SOURCE_NAMES},
            **{k: v for k, v in status.items() if k not in SOURCE_NAMES},
        },
        "regions": [{"id": r.id, "name": r.name} for r in regions],
        # 模式層投票的模式（HD14，`config.MODELS` 的順序；每格的 `model.models[]` 只放 id）；
        # `voting: false` 是旁觀模式，網頁標「旁觀，不投票」（HD16）
        "models": [
            {"id": m.id, "name": m.name, "voting": m.voting, "votesOnlyHigh": m.votes_only_high}
            for m in MODELS
        ],
        "airports": out_airports,
    }


def flight_stats(
    fl: flights.FlightsData, airports: list[Airport], now: datetime, history: Path
) -> dict:
    """航班 → 每 6 小時格的取消／延誤統計，合併寫進 `history/cancellations/`；看不懂的狀態字串
    合併進 `history/cancellations/unknown-statuses.json`。

    回傳 `sources.flights`：抓不到的機場照舊記在 `error`；統計或寫檔失敗只 log、記在
    `statsError`，不讓 build 失敗。
    """
    out: dict[str, object] = {"ok": True}
    if fl.errors:
        out = {"ok": False, "error": ",".join(f"{k}:{v}" for k, v in fl.errors.items())}
    tz = {a.icao: a.tz for a in airports}
    stats: list[dict] = []
    unknown = {}
    errors: dict[str, str] = {}
    for icao, payload in fl.snapshots.items():
        try:
            parsed = cancellations.flights_of(icao, payload, tz[icao], now)
            stats += cancellations.slot_stats(icao, parsed, now)
            unknown[icao] = cancellations.unknown_statuses(parsed)
        except Exception as e:  # 某個機場格式突然變了，其他照算
            log.warning("航班統計 %s 失敗：%s", icao, e, exc_info=True)
            errors[icao] = f"{e.__class__.__name__}: {e}"[:120]
    budget.check_cancelled()  # 超過預算被放棄了就不寫檔
    try:
        for p in cancellations.store(history, stats):
            log.info("航班統計 → %s", p)
        cancellations.store_unknown(history, unknown, now)
    except (OSError, ValueError, KeyError, TypeError) as e:
        log.warning("航班統計寫檔失敗：%s", e, exc_info=True)
        errors["store"] = f"{e.__class__.__name__}: {e}"[:120]
    if errors:
        out["statsError"] = "; ".join(f"{k}:{v}" for k, v in errors.items())
    return out


def run(
    *,
    now: datetime,
    archive: Path,
    airports_path: Path,
    confirmed_path: Path,
    api_key: str | None,
    workdir: Path,
    pages_url: str = PAGES_URL,
    timing: Timing | None = None,
    events_path: Path | None = None,
) -> dict:
    regions = load_regions(airports_path)
    airports = load_airports(airports_path)
    confirmed = load_confirmed(confirmed_path)
    slot0 = floor_6h(now)
    status: dict[str, dict] = {}
    history = archive / "history"
    tracked = track_events(events_path, now)
    mslp = bool(tracked)  # HD21：事件期間多抓海平面氣壓

    ec = _call(
        "ecmwf",
        lambda: ecmwf.fetch(airports, slot0, workdir / "ecmwf"),
        status,
        timing,
        _ecmwf_extra,
    )
    gf = _call(
        "gfs",
        lambda: gfs.fetch(airports, now, slot0, workdir / "gfs", mslp=mslp),
        status,
        timing,
        _download_extra,
    )
    af = _call(
        "aifs",
        lambda: aifs.fetch(airports, slot0, workdir / "aifs", mslp=mslp),
        status,
        timing,
        _download_extra,
    )
    ag = _call(
        "aigfs",
        lambda: aigfs.fetch(airports, now, slot0, workdir / "aigfs", mslp=mslp),
        status,
        timing,
        _download_extra,
    )
    om = _call("openmeteo", lambda: openmeteo.fetch(airports), status, timing, _openmeteo_extra)
    wn_mode = wn3_mode()
    wn_run, wn_events = wn3_targets(wn_mode, now, events_path, history)
    wn: wn3.Wn3Data | None = None
    if wn_run is not None:
        observe = wn_mode == "observe"
        if observe:
            wn_start, wn_end = slot0, slot0 + timedelta(hours=wn3.SPAN_H)
        else:
            wn_start, wn_end = wn3report.report_window(wn_run)
        wn = _call(
            "wn3",
            lambda: wn3.fetch(
                airports,
                wn_run,
                wn_start,
                wn_end,
                mslp=bool(wn_events),
                retry_previous=observe,
            ),
            status,
            timing,
            _wn3_extra,
            {"mode": wn_mode},
        )
    if tracked:
        wn_grid = wn if wn_mode == "observe" else None
        _call(
            "tracks",
            lambda: run_tracks(history, tracked, ec, gf, af, ag, workdir / "tracks", wn_grid),
            status,
            timing,
            lambda n: {"bytes": n},
        )
    tf = _call("taf", lambda: taf.fetch(airports), status, timing)
    hk = _call("hko", hko.fetch, status, timing)
    stations = tuple(a.cwa_station for a in airports if a.cwa_station)
    cw = _call("cwa", lambda: cwa.fetch(api_key, now, stations), status, timing, _cwa_extra)
    sm = _call("smg", smg.fetch, status, timing)
    nws_zones = [a.nws_zone for a in airports if "nws" in a.warning_sources]
    nw = _call("nws", lambda: nws.fetch(nws_zones), status, timing)
    jma_areas = [a.jma_area for a in airports if "jma" in a.warning_sources and a.jma_area]
    jm = _call("jma", lambda: jma.fetch(jma_areas), status, timing)
    swic_airports = [a for a in airports if swic.SOURCES & set(a.warning_sources)]
    sw = _call("swic", lambda: swic.fetch(swic_airports, now), status, timing, _swic_extra)
    _call(
        "flights",
        lambda: flight_stats(flights.fetch(now), airports, now, history),
        status,
        timing,
        lambda r: r,
    )

    factors = gust_factors(ec, gf, airports, now, history)
    latest = assemble(
        now=now,
        regions=regions,
        airports=airports,
        confirmed=confirmed,
        status=status,
        ec=ec,
        gf=gf,
        tf=tf,
        hk=hk,
        cw=cw,
        sm=sm,
        nw=nw,
        af=af,
        ag=ag,
        factors=factors,
        jm=jm,
        om=om,
        wn=wn,
        sw=sw,
    )
    if wn is not None and wn_events:
        wn3_files(history, wn_events, wn, airports, factors, wn_mode, workdir / "wn3")
    failed = [n for n, d in (("ecmwf", ec), ("gfs", gf), ("aifs", af), ("aigfs", ag)) if d is None]
    if failed:
        sources: dict[str, dict | None] = {n: find_reuse_source(archive, n, now) for n in failed}
        if any(d is None for d in sources.values()):
            prev = previous_latest(archive, pages_url)  # archive 裡找不到的退回上一份（H7 的做法）
            sources = {n: d if d is not None else prev for n, d in sources.items()}
        reuse_models(latest, sources, failed, now, airports, factors)
    run_ai(latest, previous_latest(archive, pages_url), now, history, timing)

    stamp = f"{now:%Y%m%dT%H%M}Z"
    raw_dir = history / "raw" / f"{now:%Y-%m-%d}"
    if tf is not None:
        _dump(raw_dir / f"{now:%H%M}Z-taf.json", tf.raw["taf"])
        _dump(raw_dir / f"{now:%H%M}Z-metar.json", tf.raw["metar"])
    if hk is not None:
        _dump(raw_dir / f"{now:%H%M}Z-hko.json", hk.raw)
    if cw is not None:
        _dump(raw_dir / f"{now:%H%M}Z-cwa.json", cw.raw)
        if cw.hazards_raw is not None:
            _dump(raw_dir / f"{now:%H%M}Z-cwa-hazards.json", cw.hazards_raw)
        if cw.obs_raw is not None:
            _dump(raw_dir / f"{now:%H%M}Z-cwa-obs.json", cw.obs_raw)
    if sm is not None:
        _dump(raw_dir / f"{now:%H%M}Z-smg.json", sm.raw)
    if nw is not None:
        _dump(raw_dir / f"{now:%H%M}Z-nws.json", nw.raw)
    if jm is not None:
        _dump(raw_dir / f"{now:%H%M}Z-jma.json", jm.raw)
    if sw is not None:
        _dump(raw_dir / f"{now:%H%M}Z-swic.json", sw.raw)
    if om is not None:  # HD16：兩個回應約 1.2 MB，縮排會變好幾倍，不縮排
        _dump(raw_dir / f"{now:%H%M}Z-openmeteo.json", om.raw, compact=True)
    _dump(history / f"{stamp}.json", latest, compact=True)
    _dump(archive / "latest.json", latest, compact=True)
    if events_path is not None:
        event_snapshots(events_path, history, now, history / f"{stamp}.json")
    return latest


def track_events(events_path: Path | None, now: datetime) -> list[Event]:
    """`now` 在期間內、要抽颱風路徑的事件（HD21）；`events.json` 讀不了只 log、當作沒有。"""
    if events_path is None:
        return []
    try:
        return events.active(load_events(events_path), now)
    except Exception:  # 保險：事件設定壞了不能讓 build 失敗
        log.exception("events.json 讀不了，不抽颱風路徑")
        return []


def wn3_targets(
    mode: str, now: datetime, events_path: Path | None, history: Path
) -> tuple[datetime | None, list[Event]]:
    """這一報 WeatherNext 3（HD15）要抓哪一報、寫進哪些事件（`wn3report.targets`）。`report-only`
    時沒有事件、或每個事件那一報的事件檔與路徑檔都寫過了，就回 `(None, [])`（不跑來源 `wn3`，
    省一次 BigQuery 查詢）。`events.json` 讀不了只 log、當作沒有事件。"""
    try:
        evs = load_events(events_path) if events_path is not None else []
    except Exception:  # 保險：事件設定壞了不能讓 build 失敗
        log.exception("events.json 讀不了，WeatherNext 3 不寫事件檔")
        evs = []
    run, targets = wn3report.targets(mode, now, evs)
    if mode == "observe":
        return run, targets
    todo = [
        e
        for e in targets
        if not (
            wn3report.report_path(events.event_dir(history, e), run).exists()
            and tracks.track_path(events.event_dir(history, e), run, "wn3").exists()
        )
    ]
    return (run, todo) if todo else (None, [])


def wn3_files(
    history: Path,
    evs: list[Event],
    wn: wn3.Wn3Data,
    airports: list[Airport],
    factors: dict[str, assess.GustFactor],
    mode: str,
    workdir: Path,
) -> None:
    """事件檔 `history/events/<id>/wn3/`（HD15，`wn3report`）；`report-only` 時路徑也在這裡抽
    （`observe` 的路徑由來源 `tracks` 抽）。失敗只 log，不讓 build 失敗。"""
    try:
        res = wn3report.write_event_files(
            history, evs, wn, airports, factors, mode, workdir, with_tracks=mode != "observe"
        )
        log.info(
            "WeatherNext 3 事件檔：寫了 %d 份、已經有 %d、失敗 %s",
            len(res.written),
            res.skipped,
            res.failed or "無",
        )
    except Exception:  # 保險
        log.exception("WeatherNext 3 事件檔寫不了")


def run_tracks(
    history: Path,
    evs: list[Event],
    ec: ecmwf.EcmwfData | None,
    gf: gfs.GfsData | None,
    af: aifs.AifsData | None,
    ag: aigfs.AigfsData | None,
    workdir: Path,
    wn: wn3.Wn3Data | None = None,
) -> int:
    """來源 `tracks`（HD21）：回傳下載量；有模式抽不出來時寫完其他的再丟 `partial`。`wn` 是
    `observe` 模式的 WeatherNext 3（HD15，平均海平面氣壓網格）。"""
    mslp = {
        name: (d.run, d.mslp_files)
        for name, d in (("gfs", gf), ("aigfs", ag), ("aifs", af))
        if d is not None
    }
    # 沒有 WN3 時照 HD21 的呼叫方式（不帶 `grids`）
    grids = {"grids": {"wn3": (wn.run, wn3report.grid_fields(wn))}} if wn is not None else {}
    res = tracks.build_tracks(history, evs, ec.run if ec else None, mslp, workdir, **grids)
    log.info(
        "颱風路徑：寫了 %d 份、已經有 %d、沒有起點 %d、失敗 %s",
        len(res.written),
        res.skipped,
        res.no_seed,
        res.failed or "無",
    )
    if res.failed:
        raise tracks.TracksError(f"颱風路徑抽不出來：{', '.join(res.failed)}", "partial")
    return res.bytes


def event_snapshots(events_path: Path, history: Path, now: datetime, src: Path) -> None:
    """事件期間內的報多存一份到 `history/events/<id>/`（HD20）；失敗只 log，不讓 build 失敗。"""
    try:
        for p in events.snapshot(history, load_events(events_path), now, src):
            log.info("事件快照 → %s", p)
    except Exception:  # 保險：事件保存不能讓 build 失敗
        log.exception("事件快照失敗")


def gust_factors(
    ec: ecmwf.EcmwfData | None,
    gf: gfs.GfsData | None,
    airports: list[Airport],
    now: datetime,
    history: Path,
) -> dict[str, assess.GustFactor]:
    """這一報的樣本 → `history/gustfactor/` → 每個機場的估算陣風係數（HD18，`gustfactor.update`）。
    任何失敗只 log、回空的（全部用 1.4、`default`），不讓 build 失敗。"""
    try:
        samples = gustfactor.run_samples(ec, gf, airports, slot_bounds(now))
        return gustfactor.update(history, now, samples, [a.icao for a in airports])
    except Exception:  # 保險：係數算不出來不能讓 build 失敗
        log.exception("陣風係數算不出來，全部用 1.4")
        return {}


def run_ai(
    latest: dict, prev: dict | None, now: datetime, history: Path, timing: Timing | None = None
) -> None:
    """AI 對決（HD5）：在 `BUDGET_S["ai"]` 秒內評，結果寫進 `latest`（頂層 `ai`、
    `airports[].ai`、`sources.ai`），寫一行耗時紀錄（`source: "ai"`）。任何失敗都不丟例外、
    不動 `latest` 其他內容。"""
    status: dict[str, dict] = {}
    t0 = time.monotonic()
    try:
        duel = ai.Duel(latest, prev, now, history, budget_s=BUDGET_S["ai"])
        _call("ai", duel.run, status)
        result = duel.result(timed_out=status["ai"].get("error") == "timeout")
    except Exception as e:  # 保險：AI 不能讓 build 失敗
        log.exception("AI 對決失敗")
        status["ai"] = {"ok": False, "error": e.__class__.__name__}
        result = ai.fallback(latest, "network")
    src = result["source"]
    seconds = status.get("ai", {}).get("seconds", round(time.monotonic() - t0, 1))
    source = {"ok": src["ok"], "seconds": seconds, **{k: v for k, v in src.items() if k != "ok"}}
    ai.apply(latest, result, source)
    log.info("AI 對決：%s", source)
    if timing is not None:  # token 合計、估計費用、錯誤訊息只進 timing/，`latest.json` 不加
        extra = {k: result.get(k) for k in ("usage", "costUsd", "errorMessages")}  # HD26、HD30
        timing.source("ai", {**source, **extra}, budget.Context())


def publish(out: Path, archive: Path, latest: dict | None, now: datetime) -> None:
    """把 latest 與最近 `PAGES_HISTORY_DAYS` 天的結果（`history/<時間>.json`，不含
    raw／cancellations）放進發布目錄。

    檔名的時間就是那一份的 `generatedAt`，所以用檔名判斷、不用打開約 500 KB 的檔。發布目錄裡已經有、
    但超過天數的舊檔刪掉。`data` 分支（`--archive`）照舊全部保留（H9）。
    """
    out.mkdir(parents=True, exist_ok=True)
    if latest is not None:
        _dump(out / "latest.json", latest, compact=True)
    hist_out = out / "history"
    hist_out.mkdir(parents=True, exist_ok=True)
    since = now - timedelta(days=PAGES_HISTORY_DAYS)
    keep = {p.name for t, p in _history_files(archive) if t > since}
    for p in hist_out.glob("*.json"):
        if p.name not in keep:
            p.unlink()
    for name in sorted(keep):
        shutil.copy2(archive / "history" / name, hist_out / name)


def draw_og(out: Path, latest: dict, timing: Timing | None = None) -> None:
    """在 `BUDGET_S["og"]` 秒內畫 `out/og/<iata>.png`（HD1）；失敗或超時只 log、寫一行耗時紀錄
    （`source: "og"`，`bytes` 是全部圖的總大小），不丟例外。"""
    status: dict[str, dict] = {}  # 不進 latest.json（已經發布了）
    try:
        _call("og", lambda: og.render_all(latest, out / "og"), status, timing, lambda r: r)
        st = status["og"]
        log.info(
            "預覽圖：%s 張，%s bytes，%.1f 秒", st.get("count"), st.get("bytes"), st["seconds"]
        )
    except Exception:  # 保險：預覽圖不能讓 build 失敗或改發布上一份
        log.exception("預覽圖畫不出來")


def previous_latest(archive: Path, pages_url: str) -> dict | None:
    p = archive / "latest.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            log.warning("archive 的 latest.json 壞了")
    try:
        r = requests.get(pages_url, timeout=30)
        r.raise_for_status()
        return r.json()
    except (requests.RequestException, ValueError) as e:
        log.error("從 Pages 抓上一份 latest.json 也失敗：%s", e)
        return None


def slot_of(t: datetime) -> datetime:
    """`t` 之前（含）最近的排定時間（`SLOTS`；01:05Z 之前是前一天的 20:25Z）。"""
    day = t.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(
        c
        for c in (day + timedelta(days=d, hours=h, minutes=m) for d in (-1, 0) for h, m in SLOTS)
        if c <= t
    )


def already_built(archive: Path, slot: datetime) -> str | None:
    """`--archive` 的 `latest.json` 的 `generatedAt` ≥ `slot` 時回傳那個 `generatedAt`；
    沒有檔、壞掉、比較早都回 None（照跑，寧可多跑）。不從 Pages 抓：`data` 分支是 job 開始時
    才取出的，比 Pages 新。"""
    try:
        doc = json.loads((archive / "latest.json").read_text(encoding="utf-8"))
        generated = parse_time(doc["generatedAt"])
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None
    return iso(generated) if generated is not None and generated >= slot else None


def _started_at(fallback: datetime) -> datetime:
    """job 開始的時間（`build.yml` 第一步寫的 `JOB_STARTED_AT`）；沒有或看不懂就用 `fallback`。"""
    try:
        return parse_time(os.environ.get("JOB_STARTED_AT")) or fallback
    except ValueError:
        return fallback


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m hongthai.build", description=__doc__)
    ap.add_argument("--out", type=Path, default=Path("public"))
    ap.add_argument("--archive", type=Path, default=Path("data"))
    ap.add_argument("--airports", type=Path, default=Path("airports.json"))
    ap.add_argument("--confirmed", type=Path, default=Path("confirmed.json"))
    ap.add_argument("--events", type=Path, default=Path("events.json"))
    ap.add_argument("--pages-url", default=PAGES_URL)
    ap.add_argument(
        "--trigger",
        choices=TRIGGERS,
        default="manual",
        help="誰觸發的（HD25）：schedule／cloudflare 這個時段已經出過就跳過，manual 一律照跑",
    )
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stderr
    )
    for noisy in ("urllib3", "multiurl", "ecmwf", "cfgrib"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    t0 = time.monotonic()
    started = utcnow()
    now = started.replace(second=0, microsecond=0)
    timing = Timing(args.archive, now)
    started = _started_at(started)
    slot = None if args.trigger == "manual" else slot_of(started)
    when = {
        "trigger": args.trigger,
        "slot": iso(slot),
        "startedAt": iso(started),
        "delayMinutes": None if slot is None else round((started - slot).total_seconds() / 60, 1),
    }
    if slot is not None and (done := already_built(args.archive, slot)) is not None:
        print(f"這個時段 {slot:%H:%M}Z 已經在 {done} 出過，跳過")
        timing.write(source="skip", ok=True, seconds=0, **when, generatedAt=done)
        return 0
    commit = (os.environ.get("GITHUB_SHA") or "")[:7] or None
    timing.write(source="start", ok=True, seconds=0, commit=commit, **when)
    produced = False
    try:
        # 超時被放棄的來源執行緒可能還在往暫存目錄寫檔，清不乾淨就算了
        with tempfile.TemporaryDirectory(prefix="hongthai-", ignore_cleanup_errors=True) as tmp:
            latest = run(
                now=now,
                archive=args.archive,
                airports_path=args.airports,
                confirmed_path=args.confirmed,
                api_key=os.environ.get("CWA_API_KEY") or None,
                workdir=Path(tmp),
                pages_url=args.pages_url,
                timing=timing,
                events_path=args.events,
            )
        produced = True
        publish(args.out, args.archive, latest, now)
        draw_og(args.out, latest, timing)
        ok = {k: v.get("ok") for k, v in latest["sources"].items()}
        log.info("完成，%.1f 秒；來源：%s", time.monotonic() - t0, ok)
        return 0
    except Exception:
        log.exception("整個流程失敗，改發布上一份 latest.json")
        prev = previous_latest(args.archive, args.pages_url)
        if prev is None:
            return 2
        publish(args.out, args.archive, prev, now)
        draw_og(args.out, prev, timing)
        return 1
    finally:
        # 被放棄的來源執行緒是 daemon，不 join，程式照常結束
        timing.write(source="done", ok=produced, seconds=round(time.monotonic() - t0, 1))


if __name__ == "__main__":
    sys.exit(main())
