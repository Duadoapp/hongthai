"""WeatherNext 3 旁觀等級上傳 Cloudflare R2（HD15c，2026-10-28 定案）。

條款：看不出原始數字的加值（Non-Retrievable VAS，例如只有等級）可以公開，要附 Section 4(b) 的固定
標註與取得管道；不能在限制國家提供——擋限制國家的**訪客**由 Duado 的轉送程式看 Cloudflare 的訪客
國家做（`GET /hongthai/wn3/<iata>.json`），不在這支。所以這裡只負責：

- `private` 模式算完那一報（`wn3report.observe_private` 這一報有查到資料）之後，每個機場一份**只有
  等級**的檔 `wn3/<iata 小寫>.json`（51 個都傳，日本、南韓的機場照樣有；覆寫，只放最新一份）：

      {"schema": 1, "generatedAt", "run", "model": "wn3", "attribution",
       "slots": [{"from", "to", "level", "levels": {"wind", "rain", "snow", "fog"}} × 20]}

  格子同 `latest.json` 的 6 小時格（`slot_bounds(now)`，0–120 小時），等級同 `wn3report` 事件檔那
  筆的 `levels`／`level`（`assess.model_entry`；旁觀不判霧）。**不放任何數字**（`windKt`、`gustKt`、
  雨量、`p49Kt` 都沒有）
- 這一報 WN3 失敗、或私人 bucket 已經有這一報（沒查）就不上傳：R2 留著上一份，網頁由 `generatedAt`
  判斷舊不舊
- R2 用 S3 相容 API（`PUT https://<R2_ACCOUNT_ID>.r2.cloudflarestorage.com/<bucket>/<物件>`），
  `requests`＋自己簽 AWS Signature Version 4（`region` 是 `auto`、`service` 是 `s3`），不加套件。
  secrets `R2_ACCOUNT_ID`、`R2_ACCESS_KEY_ID`、`R2_SECRET_ACCESS_KEY` 少一個就跳過
  （`not_configured`）；bucket 名稱是 Variable `R2_BUCKET`（預設 `hongthai-wn3`）
- `sources.wn3` 多 `r2`（`ok`／`not_configured`／錯誤碼）、`r2Files`（上傳了幾個檔）、`r2Bytes`。
  一個檔失敗就停（多半是金鑰或權限，後面的也會失敗），已經傳的留著
- **日誌只印上傳幾個檔、bytes、錯誤碼**，不印等級（等級雖然不是原始數字，日誌是公開的、會在限制國家
  被看到）
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from urllib.parse import quote

import requests

from . import assess
from .budget import check_cancelled
from .config import WN3_MODEL, Airport
from .sources import SourceError
from .sources.wn3 import TERMS_URL, Wn3Data
from .timeutil import iso, slot_bounds, utcnow

log = logging.getLogger("hongthai")

SCHEMA = 1
PREFIX = "wn3/"
ENV_ACCOUNT, ENV_KEY_ID, ENV_SECRET, ENV_BUCKET = (
    "R2_ACCOUNT_ID",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "R2_BUCKET",
)
BUCKET_DEFAULT = "hongthai-wn3"
REGION, SERVICE = "auto", "s3"
TIMEOUT_S = 15
NOT_CONFIGURED = "not_configured"
VIA_NAMES = {"bigquery": "Google BigQuery", "zarr": "Google Cloud Storage"}
# GDM 即時資料條款 Section 4(b) 的固定標註原文（README「WeatherNext 3 的條款」）
ATTRIBUTION_4B = (
    "© 2024-6 Google LLC, whose machine learning models were used to create the experimental data "
    f"made available under the following licence terms {TERMS_URL}. This data is intended for "
    "experimental modelling only and is not intended, validated, or approved for real world use."
)


class R2Error(SourceError):
    pass


def attribution(via: str) -> str:
    """Section 4(b) 原文＋實際的取得管道（`Wn3Data.via`：`bigquery`／`zarr`）。"""
    return f"Google WeatherNext 3 via {VIA_NAMES.get(via, VIA_NAMES['zarr'])}. {ATTRIBUTION_4B}"


def object_name(a: Airport) -> str:
    return f"{PREFIX}{a.iata.lower()}.json"


def level_doc(
    data: Wn3Data,
    a: Airport,
    factor: assess.GustFactor,
    now: datetime,
) -> dict:
    """一個機場的等級檔：`latest.json` 那 20 格，每格只有 `levels`／`level`。"""
    points = data.points.get(a.icao)
    slots = []
    for start, end in slot_bounds(now):
        src = assess.wn3_for_slot(points, start, end, a.runways, factor)
        entry = assess.model_entry(WN3_MODEL, {}, {}, src, {}, a.thresholds)
        slots.append(
            {
                "from": iso(start),
                "to": iso(end),
                "level": entry["level"],
                "levels": {c: entry["levels"][c] for c in assess.CAUSES},
            }
        )
    return {
        "schema": SCHEMA,
        "generatedAt": iso(now),
        "run": iso(data.run),
        "model": "wn3",
        "attribution": attribution(data.via),
        "slots": slots,
    }


def level_docs(
    data: Wn3Data,
    airports: Sequence[Airport],
    factors: Mapping[str, assess.GustFactor],
    now: datetime,
) -> dict[str, dict]:
    """物件名稱 → 等級檔，每個機場一份（沒有那個機場的資料也有，等級全是 null）。"""
    return {
        object_name(a): level_doc(data, a, factors.get(a.icao, assess.DEFAULT_GUST_FACTOR), now)
        for a in airports
    }


# ---- R2（S3 相容 API，AWS Signature Version 4）----


def _hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def sign_v4(
    method: str,
    host: str,
    path: str,
    headers: Mapping[str, str],
    payload: bytes,
    access_key: str,
    secret_key: str,
    at: datetime,
    region: str = REGION,
    service: str = SERVICE,
) -> dict[str, str]:
    """AWS Signature Version 4（標頭簽章，沒有查詢字串）：回傳要送出的標頭（`host` 以外、全部小寫，
    含 `x-amz-date`、`x-amz-content-sha256`、`authorization`）。`path` 是還沒編碼的路徑。"""
    amz_date = f"{at.astimezone(UTC):%Y%m%dT%H%M%SZ}"
    day = amz_date[:8]
    payload_hash = hashlib.sha256(payload).hexdigest()
    signed_headers = {k.lower(): " ".join(v.split()) for k, v in headers.items()}
    signed_headers.update(
        {"host": host, "x-amz-content-sha256": payload_hash, "x-amz-date": amz_date}
    )
    names = sorted(signed_headers)
    canonical = "\n".join(
        [
            method,
            quote(path, safe="/-_.~"),
            "",  # 查詢字串
            "".join(f"{k}:{signed_headers[k]}\n" for k in names),
            ";".join(names),
            payload_hash,
        ]
    )
    scope = f"{day}/{region}/{service}/aws4_request"
    to_sign = "\n".join(
        ["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(canonical.encode()).hexdigest()]
    )
    key = _hmac(
        _hmac(_hmac(_hmac(f"AWS4{secret_key}".encode(), day), region), service), "aws4_request"
    )
    signature = hmac.new(key, to_sign.encode(), hashlib.sha256).hexdigest()
    out = {k: v for k, v in signed_headers.items() if k != "host"}
    out["authorization"] = (
        f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, "
        f"SignedHeaders={';'.join(names)}, Signature={signature}"
    )
    return out


class R2:
    """一個 R2 bucket 的上傳。錯誤丟 `R2Error`，`code` 是 `r2_http_<狀態碼>` 或 `r2_<例外名稱>`；
    訊息只有物件名稱與狀態碼（不放回應本文、不放金鑰）。"""

    def __init__(
        self,
        account_id: str,
        access_key: str,
        secret_key: str,
        bucket: str = BUCKET_DEFAULT,
        session=None,
        clock: Callable[[], datetime] = utcnow,
    ):
        self.host = f"{account_id}.r2.cloudflarestorage.com"
        self.access_key, self.secret_key, self.bucket = access_key, secret_key, bucket
        self.session = session or requests.Session()
        self.clock = clock

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> R2 | None:
        """三個 secret 少一個就回 None（不上傳）；`R2_BUCKET` 沒設用 `hongthai-wn3`。"""
        env = os.environ if env is None else env
        account, key_id, secret = (
            env.get(k, "").strip() for k in (ENV_ACCOUNT, ENV_KEY_ID, ENV_SECRET)
        )
        if not (account and key_id and secret):
            return None
        return cls(account, key_id, secret, env.get(ENV_BUCKET, "").strip() or BUCKET_DEFAULT)

    def put(
        self, obj: str, body: bytes, content_type: str = "application/json; charset=utf-8"
    ) -> None:
        path = f"/{self.bucket}/{obj}"
        headers = sign_v4(
            "PUT",
            self.host,
            path,
            {"content-type": content_type},
            body,
            self.access_key,
            self.secret_key,
            self.clock(),
        )
        url = f"https://{self.host}{quote(path, safe='/-_.~')}"
        try:
            r = self.session.request("PUT", url, data=body, headers=headers, timeout=TIMEOUT_S)
        except requests.RequestException as e:
            raise R2Error(
                f"R2 寫 {obj}：{e.__class__.__name__}", f"r2_{e.__class__.__name__}"
            ) from e
        if r.status_code != 200:
            raise R2Error(f"R2 寫 {obj}：HTTP {r.status_code}", f"r2_http_{r.status_code}")


def encode(doc: dict) -> bytes:
    return json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def upload(docs: Mapping[str, dict], client: R2 | None) -> dict:
    """傳到 R2，回 `sources.wn3` 要併進去的欄位：`r2`（`ok`／`not_configured`／錯誤碼）、
    `r2Files`、`r2Bytes`。一個失敗就停。"""
    if client is None:
        log.info("WeatherNext 3 等級：沒設 R2 的 secrets，不上傳")
        return {"r2": NOT_CONFIGURED, "r2Files": 0, "r2Bytes": 0}
    files = size = 0
    status = "ok"
    for obj, doc in docs.items():
        check_cancelled()
        body = encode(doc)
        try:
            client.put(obj, body)
        except R2Error as e:
            log.warning("WeatherNext 3 等級：R2 上傳失敗（%s），已傳 %d 個檔", e.code, files)
            status = e.code or "r2_error"
            break
        files += 1
        size += len(body)
    if status == "ok":
        log.info("WeatherNext 3 等級：R2 上傳 %d 個檔、%d bytes", files, size)
    return {"r2": status, "r2Files": files, "r2Bytes": size}


def publish(
    data: Wn3Data,
    airports: Sequence[Airport],
    factors: Mapping[str, assess.GustFactor],
    now: datetime,
    client: R2 | None = None,
    env: Mapping[str, str] | None = None,
) -> dict:
    """這一報的等級檔 → R2（`client` 沒給就照環境變數建）。"""
    client = client or R2.from_env(env)
    return upload(level_docs(data, airports, factors, now), client)
