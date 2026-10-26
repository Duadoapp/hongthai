"""WeatherNext 3 的私人 bucket（HD15b，2026-10-26 定案）：隱形旁觀的存放處與超過 121 小時的搬家。

條款照比較嚴的讀法（看**有效時間**）：有效時間還沒過 1 小時的數值是即時資料，不能出現在任何
公開的地方（`latest.json`、GitHub Pages、`data` 分支、Actions 的日誌與 artifact、PR）。所以：

- **隱形旁觀**（`config.WN3_MODE` 的 `private`，預設；`build.py` 呼叫
  `wn3report.observe_private`）：每報抓最新的主報、照事件檔的格式算每格（含 `levels`／`level`），
  整份只寫進私人 bucket `gs://<GOOGLE_CLOUD_PROJECT>-wn3-private/observe/<起報>.json`
  （起報 `YYYYMMDDTHHMMZ`，`bucket_name`；環境變數 `WN3_PRIVATE_BUCKET` 可以換）。同一個起報
  已經在 bucket 裡就**跳過**（不再查 BigQuery）
- **搬家**（`archive`，`python -m hongthai.events wn3-archive`，`events` workflow 每天 00Z 那次）：
  起報 ≤ 現在 − 121 小時（`public_run`，提前 120 小時的有效時間也過了 1 小時，任何讀法下都是
  CC BY 4.0）、`data` 分支還沒有的，複製到 `history/wn3/<起報>.json`（`license`、`attribution`
  換成 CC BY 4.0 的）；起報落在事件期間（台灣日期）的，事件目錄 `wn3/` 也放一份（已經有就不
  覆寫，除非那份是補抓時截過的 `clippedAt`）。私人 bucket 的檔留著

這支只用 `requests` 與 `google-auth`（GCS JSON API），不載入 numpy／xarray：`events` workflow
每小時那支只裝這兩個套件。**日誌只印起報時間、檔名、HTTP 狀態碼**，不印檔案內容或回應本文。
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from urllib.parse import quote

import requests

from .config import Event
from .events import TAIPEI, event_dir
from .sources import SourceError
from .timeutil import floor_6h, iso

log = logging.getLogger("hongthai")

ENV_JSON, ENV_PROJECT, ENV_BUCKET = (
    "GOOGLE_SERVICE_ACCOUNT_JSON",
    "GOOGLE_CLOUD_PROJECT",
    "WN3_PRIVATE_BUCKET",
)
SCOPES = ("https://www.googleapis.com/auth/cloud-platform",)
BUCKET_SUFFIX = "-wn3-private"
OBSERVE_PREFIX = "observe/"
GCS_API = "https://storage.googleapis.com/storage/v1"
GCS_UPLOAD = "https://storage.googleapis.com/upload/storage/v1"
TIMEOUT_S = 30
STAMP = "%Y%m%dT%H%MZ"
SPAN_H = 120
# 提前 120 小時的有效時間也過了 1 小時（`wn3report.REPORT_LAG` 同值）
PUBLIC_LAG = timedelta(hours=SPAN_H + 1)
LICENSE_CC = "CC BY 4.0"
ATTRIBUTION_CC = "Google WeatherNext 3, © 2026 Google LLC, CC BY 4.0"


class PrivateError(SourceError):
    pass


def credentials(env: dict[str, str] | None = None):
    """服務帳號（`GOOGLE_SERVICE_ACCOUNT_JSON` 整份原文，`json.loads` 後直接給 `google.oauth2`，
    不寫到磁碟）與專案。少一個或讀不了丟 `no_credentials`（訊息不放 JSON 內容）。"""
    env = os.environ if env is None else env
    raw, project = env.get(ENV_JSON), env.get(ENV_PROJECT)
    if not (raw and project):
        raise PrivateError(
            "沒有 GOOGLE_SERVICE_ACCOUNT_JSON／GOOGLE_CLOUD_PROJECT", "no_credentials"
        )
    from google.oauth2 import service_account  # 延後載入

    try:
        info = json.loads(raw)
        creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    except (ValueError, KeyError, TypeError) as e:
        raise PrivateError("GOOGLE_SERVICE_ACCOUNT_JSON 讀不了", "no_credentials") from e
    return creds, project


def bucket_name(project: str, env: dict[str, str] | None = None) -> str:
    env = os.environ if env is None else env
    return env.get(ENV_BUCKET) or f"{project}{BUCKET_SUFFIX}"


def stamp(run: datetime) -> str:
    return f"{run:{STAMP}}"


def object_name(run: datetime) -> str:
    return f"{OBSERVE_PREFIX}{stamp(run)}.json"


def run_of(name: str) -> datetime | None:
    """`observe/<起報>.json` → 起報時間；不是這個格式回 None。"""
    base = name.removeprefix(OBSERVE_PREFIX)
    if base == name or not base.endswith(".json") or "/" in base:
        return None
    try:
        return datetime.strptime(base.removesuffix(".json"), STAMP).replace(tzinfo=UTC)
    except ValueError:
        return None


def report_path(d: Path, run: datetime) -> Path:
    """事件目錄的 WN3 事件檔（`wn3report` 也用這個）。"""
    return d / "wn3" / f"{stamp(run)}.json"


def history_path(history: Path, run: datetime) -> Path:
    return history / "wn3" / f"{stamp(run)}.json"


def in_period(e: Event, run: datetime) -> bool:
    """起報落在事件期間（台灣日期 `from` 00:00～`to` 24:00）。"""
    lo = datetime.combine(e.start, time(0), TAIPEI).astimezone(UTC)
    hi = datetime.combine(e.end + timedelta(days=1), time(0), TAIPEI).astimezone(UTC)
    return lo <= run < hi


def public_run(now: datetime) -> datetime:
    """起報 ≤ 這個時間的報可以公開（全部有效時間都過了 1 小時）。"""
    return floor_6h(now - PUBLIC_LAG)


# ---- GCS（JSON API）----


def _code(e: Exception) -> str:
    return f"gcs_{e.__class__.__name__}"


class Bucket:
    """私人 bucket 的四個動作。錯誤丟 `PrivateError`，`code` 是 `gcs_http_<狀態碼>` 或
    `gcs_<例外名稱>`；訊息只有動作、物件名稱與狀態碼（不放回應本文）。"""

    def __init__(self, name: str, session):
        self.name, self.session = name, session

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Bucket:
        creds, project = credentials(env)
        from google.auth.transport.requests import AuthorizedSession  # 延後載入

        return cls(bucket_name(project, env), AuthorizedSession(creds))

    def _url(self, obj: str) -> str:
        return f"{GCS_API}/b/{quote(self.name, safe='')}/o/{quote(obj, safe='')}"

    def _request(self, op: str, obj: str, method: str, url: str, **kw) -> requests.Response:
        try:
            return self.session.request(method, url, timeout=TIMEOUT_S, **kw)
        except requests.RequestException as e:
            raise PrivateError(f"私人 bucket {op} {obj}：{e.__class__.__name__}", _code(e)) from e

    @staticmethod
    def _fail(op: str, obj: str, r: requests.Response) -> PrivateError:
        return PrivateError(
            f"私人 bucket {op} {obj}：HTTP {r.status_code}", f"gcs_http_{r.status_code}"
        )

    def exists(self, obj: str) -> bool:
        r = self._request("查", obj, "GET", self._url(obj), params={"fields": "name"})
        if r.status_code == 404:
            return False
        if r.status_code != 200:
            raise self._fail("查", obj, r)
        return True

    def put_json(self, obj: str, doc: dict) -> bool:
        """寫一份（不縮排）；`ifGenerationMatch=0`：已經有同名的就不寫、回 False（兩次 build 同時
        寫同一報時，先到的算）。"""
        body = json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        r = self._request(
            "寫",
            obj,
            "POST",
            f"{GCS_UPLOAD}/b/{quote(self.name, safe='')}/o",
            params={"uploadType": "media", "name": obj, "ifGenerationMatch": "0"},
            data=body,
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        if r.status_code == 412:
            return False
        if r.status_code != 200:
            raise self._fail("寫", obj, r)
        return True

    def list(self, prefix: str) -> list[str]:
        names: list[str] = []
        token: str | None = None
        while True:
            params = {"prefix": prefix, "fields": "items(name),nextPageToken"}
            if token:
                params["pageToken"] = token
            r = self._request(
                "列", prefix, "GET", f"{GCS_API}/b/{quote(self.name, safe='')}/o", params=params
            )
            if r.status_code != 200:
                raise self._fail("列", prefix, r)
            try:
                body = r.json()
            except ValueError as e:
                raise PrivateError(f"私人 bucket 列 {prefix}：回應不是 JSON", "gcs_bad_json") from e
            names += [i["name"] for i in body.get("items") or [] if isinstance(i.get("name"), str)]
            token = body.get("nextPageToken")
            if not token:
                return names

    def get_json(self, obj: str) -> dict:
        r = self._request("讀", obj, "GET", self._url(obj), params={"alt": "media"})
        if r.status_code != 200:
            raise self._fail("讀", obj, r)
        try:
            doc = r.json()
        except ValueError as e:
            raise PrivateError(f"私人 bucket 讀 {obj}：不是 JSON", "gcs_bad_json") from e
        if not isinstance(doc, dict):
            raise PrivateError(f"私人 bucket 讀 {obj}：不是物件", "gcs_bad_json")
        return doc


# ---- 搬家（超過 121 小時）----


def write_json(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(doc, ensure_ascii=False, separators=(",", ":"))
    path.write_text(text + "\n", encoding="utf-8")


def _read(path: Path) -> dict | None:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def public_doc(doc: dict) -> dict:
    """私人那份 → 公開那份：`license`、`attribution` 換成 CC BY 4.0 的，其他照抄（`mode` 留
    `private`，表示是旁觀時寫的）。"""
    return {**doc, "license": LICENSE_CC, "attribution": ATTRIBUTION_CC}


@dataclass
class ArchiveResult:
    written: list[Path] = field(default_factory=list)
    skipped: int = 0  # 已經搬過的報
    failed: list[str] = field(default_factory=list)  # 起報


def _event_copies(history: Path, events: Sequence[Event], run: datetime, doc: dict) -> list[Path]:
    """事件目錄 `wn3/` 也放一份：已經有就不覆寫，除非那份是截過的（`clippedAt`，補抓時寫的）。"""
    out = []
    for e in events:
        if not in_period(e, run):
            continue
        path = report_path(event_dir(history, e), run)
        old = _read(path) if path.exists() else None
        if path.exists() and (old is None or not old.get("clippedAt")):
            continue
        write_json(path, doc)
        out.append(path)
    return out


def archive(history: Path, events: Sequence[Event], now: datetime, bucket: Bucket) -> ArchiveResult:
    """私人 bucket 裡起報 ≤ 現在 − 121 小時的報 → `history/wn3/`（還沒搬過的才讀 bucket）＋
    事件目錄。一報失敗只記起報、繼續下一報；列 bucket 失敗丟 `PrivateError`。"""
    res = ArchiveResult()
    limit = public_run(now)
    runs = sorted(r for n in bucket.list(OBSERVE_PREFIX) if (r := run_of(n)) and r <= limit)
    for run in runs:
        target = history_path(history, run)
        if target.exists():
            res.skipped += 1
            doc = _read(target)
        else:
            try:
                doc = bucket.get_json(object_name(run))
            except PrivateError as e:
                log.warning("WeatherNext 3 %s 搬不了（%s）", iso(run), e.code)
                res.failed.append(iso(run) or "")
                continue
            if doc.get("model") != "wn3" or doc.get("run") != iso(run):
                log.warning(
                    "WeatherNext 3 %s：私人 bucket 那份的 model／run 對不上，不搬", iso(run)
                )
                res.failed.append(iso(run) or "")
                continue
            doc = public_doc(doc)
            write_json(target, doc)
            res.written.append(target)
            log.info("WeatherNext 3 %s → %s", iso(run), target)
        if doc is not None:
            res.written += _event_copies(history, events, run, doc)
    return res
