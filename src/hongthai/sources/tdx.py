"""TDX（交通部運輸資料流通服務平臺）航空即時航班（FIDS）。HD32：事件保存（`events.py` 的
`hourly`）每小時存逐班紀錄；HD38：`build.py` 每一報也抓一次，台中、台南、花蓮、台東、澎湖、金門、
馬祖南竿的取消／延誤統計進 `latest.json`（桃園、松山、高雄照舊用原本的來源）。

- 認證：OAuth2 client credentials。`TDX_CLIENT_ID`、`TDX_CLIENT_SECRET` 從環境變數讀（Actions
  secrets），**不寫進檔案、log 不印**；沒設就整件事跳過（`Client.from_env` 回 None，記一行
  「TDX 未設定」）。token 端點照 swagger 的 `securitySchemes.TDX.flows.clientCredentials.tokenUrl`：
  `POST https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token`
  （`application/x-www-form-urlencoded`：`grant_type=client_credentials`、`client_id`、
  `client_secret`），回 `access_token`；之後的請求帶 `Authorization: Bearer <token>`。token 效期
  24 小時，一次執行取一次、記在記憶體（`Client`），不存檔
- 資料：基礎服務「公共運輸-航空」v2（swagger `eb87998f-2f9c-4592-8d75-c62e5b724962`，
  2026-10-23 讀）的 `GET /api/basic/v2/Air/FIDS/Airport`「取得機場的即時航班資料」：一次拿多個
  機場，每個機場一筆 `{"AirportID": IATA, "FIDSDeparture": [...], "FIDSArrival": [...],
  "UpdateTime"}`。用 OData `$filter=AirportID eq 'TPE' or …` 只拿要的機場（平臺「資料服務使用
  原則」要求善用 `$filter`／`$top`），所以**每小時只有 token＋資料兩個請求**。逐班欄位：
  `FlightDate`、`FlightNumber`（不含航空公司代碼）、`AirlineID`、`DepartureAirportID`、
  `ArrivalAirportID`、`ScheduleDepartureTime`／`ScheduleArrivalTime`、`Actual…`、`Estimated…`
  （當地時間 `yyyy-MM-ddTHH:mm`）、`DepartureRemark`／`ArrivalRemark`（中文狀態）、
  `…RemarkEn`、`CodeShare`（共用班號；swagger 寫字串，另有 `{AirlineID, FlightNumber}` 的型別，
  兩種都接）、`IsCargo`、`AcType`、`UpdateTime`。解析在 `flights_log.tdx_rows`
- 頻率限制（`/webapi/pricing/` 與收費說明，2026-10-23 讀）：基礎會員「TWD 0 元/月| 虛擬點數：
  3 點/月| 存取頻率：5 次/分/金鑰」；計費「計次：1,500次/1點」「計量：150MB/1點」，兩者合併計算；
  超過頻率回 429；點數用到 105% 當月停權。回應要求 gzip 壓縮（`Accept-Encoding`）壓低計量。
  HD38（Shawn 2026-10-25 實測）：**照壓縮後的傳輸量計**，10/24 一天 17 次共 1,764 KB（每次約
  104 KB；解壓縮後約 1.68 MB），每月免費 3 點約 4,400 次。每次資料請求（token 不算）都在 `data`
  分支 `history/tdx/calls-<YYYY-MM>.jsonl` 追加一行（`CallLog`：`t`、`caller`、`bytes`），build 與
  事件保存都讀這個檔計數（`month_calls`）：平常每報（build）到 `BUILD_CALL_LIMIT` 就停，事件期間的
  每小時存檔（events）到 `MONTHLY_CALL_LIMIT` 才停（用量估算見 README「TDX 用量」）
- 授權：政府資料開放授權條款；平臺「資料授權利用條款」要求標示資料來源為「交通部運輸資料流通服務
  平臺」或其資料來源單位（README「資料來源與授權」）
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import requests

from ..timeutil import iso, utcnow
from . import TIMEOUT, USER_AGENT, SourceError, http_get

log = logging.getLogger("hongthai")

TOKEN_URL = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
FIDS_URL = "https://tdx.transportdata.tw/api/basic/v2/Air/FIDS/Airport"
ENV_ID, ENV_SECRET = "TDX_CLIENT_ID", "TDX_CLIENT_SECRET"
# HD38（Shawn 2026-10-25）：每月資料請求（`fids`，不含 token）的上限，build 與事件保存合計，
# 是免費額度（約 4,400 次）的一半。快到上限先停平常每報的（build，`BUILD_CALL_LIMIT`），事件期間
# 每小時的存檔（events）到 `MONTHLY_CALL_LIMIT` 才停
MONTHLY_CALL_LIMIT = 2000
BUILD_CALL_LIMIT = 1700
CALLERS = ("build", "events")
FIDS_ATTEMPTS, FIDS_BACKOFF_S = 2, 2.0
# build 與 events 可能同時往同一個月的檔追加，`tools/push_data.sh` 的 rebase 會在檔尾衝突；
# 這個目錄放 `.gitattributes` 讓 git 用 union 合併（兩邊的行都留下）
GITATTRIBUTES = "*.jsonl merge=union\n"


def calls_path(history: Path, t: datetime) -> Path:
    """`history/tdx/calls-<YYYY-MM>.jsonl`（`t` 的 UTC 月份）。"""
    return history / "tdx" / f"calls-{iso(t)[:7]}.jsonl"


def month_calls(history: Path, now: datetime) -> int:
    """這個月（UTC）已經送出的 TDX 資料請求數：build＋事件保存，`calls_path` 的行數（壞掉的行
    跳過）。"""
    path = calls_path(history, now)
    if not path.exists():
        return 0
    n = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            n += isinstance(json.loads(line), dict)
        except ValueError:
            continue
    return n


@dataclass
class CallLog:
    """每次資料請求追加一行 `{"t", "caller", "bytes"}`（HD38）。`bytes` 是回應的 `Content-Length`
    （gzip 壓縮後的傳輸量，TDX 照這個計費；沒有這個標頭時是解壓縮後的長度），請求失敗是 null。
    寫不了只 log，不讓請求失敗。"""

    history: Path
    caller: str  # `CALLERS`
    clock: Callable[[], datetime] = field(default=utcnow, repr=False)  # 測試換掉

    def record(self, nbytes: int | None) -> None:
        t = self.clock()
        path = calls_path(self.history, t)
        line = json.dumps({"t": iso(t), "caller": self.caller, "bytes": nbytes})
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            attrs = path.parent / ".gitattributes"
            if not attrs.exists():
                attrs.write_text(GITATTRIBUTES, encoding="utf-8")
            with path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError as e:
            log.warning("TDX 呼叫紀錄寫不進 %s：%s", path, e)


def transfer_bytes(r: requests.Response) -> int:
    """回應的傳輸量：`Content-Length`（壓縮後），沒有就用解壓縮後的長度。"""
    try:
        return int(r.headers.get("Content-Length") or len(r.content))
    except (TypeError, ValueError):
        return len(r.content)


class TdxError(SourceError):
    pass


def fids_params(iatas: Iterable[str]) -> dict[str, str]:
    """只拿這幾個機場（OData `$filter`）；`$top` 是機場筆數上限（預設 30）。"""
    codes = sorted(set(iatas))
    return {
        "$filter": " or ".join(f"AirportID eq '{c}'" for c in codes),
        "$top": str(max(len(codes), 1)),
        "$format": "JSON",
    }


@dataclass
class Client:
    client_id: str
    client_secret: str = field(repr=False)
    _token: str | None = field(default=None, repr=False)
    # 同一次執行同樣的機場只請求一次（期間重疊的事件不重抓）
    _fids: dict[tuple[str, ...], dict[str, dict]] = field(default_factory=dict, repr=False)
    calls: int = 0  # 這次執行送出的資料請求數（HD38）
    log: CallLog | None = field(default=None, repr=False)  # 每次資料請求記一行（HD38）

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Client | None:
        env = os.environ if env is None else env
        cid, secret = (env.get(k, "").strip() for k in (ENV_ID, ENV_SECRET))
        if not cid or not secret:
            log.info("TDX 未設定（%s／%s），跳過", ENV_ID, ENV_SECRET)
            return None
        return cls(cid, secret)

    def token(self) -> str:
        """取 token（一次執行一次）。失敗丟 `TdxError`，訊息只有狀態碼與 OAuth 的 `error`，
        不含金鑰。"""
        if self._token:
            return self._token
        data = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }
        try:
            r = requests.post(
                TOKEN_URL,
                data=data,
                headers={"User-Agent": USER_AGENT},
                timeout=TIMEOUT,
            )
        except requests.RequestException as e:
            raise TdxError(f"TDX token：{e.__class__.__name__}", "token_network") from None
        if r.status_code != 200:
            try:
                reason = str(r.json().get("error") or "")
            except (ValueError, AttributeError):
                reason = ""
            raise TdxError(f"TDX token：HTTP {r.status_code} {reason}".strip(), "token_http")
        try:
            tok = r.json().get("access_token")
        except (ValueError, AttributeError):
            tok = None
        if not tok:
            raise TdxError("TDX token：回應沒有 access_token", "token_format")
        self._token = str(tok)
        return self._token

    def fids(self, iatas: Iterable[str]) -> dict[str, dict]:
        """`/v2/Air/FIDS/Airport` 一次拿這幾個機場 → IATA → 該機場那筆（`FIDSDeparture`、
        `FIDSArrival`）。請求的機場沒回來的記 log。"""
        want = tuple(sorted(set(iatas)))
        if want in self._fids:
            return self._fids[want]
        headers = {"Authorization": f"Bearer {self.token()}", "Accept-Encoding": "gzip"}
        # 最多試 2 次（同以前的 `retries=2`），但每送一次就記一行，計數才不會少
        for attempt in range(1, FIDS_ATTEMPTS + 1):
            self.calls += 1
            nbytes = None
            try:
                r = http_get(
                    FIDS_URL, params=fids_params(want), headers=headers, retries=1, error=TdxError
                )
                nbytes = transfer_bytes(r)
                break
            except TdxError as e:
                if attempt == FIDS_ATTEMPTS or e.code in ("http_401", "http_403"):
                    raise
                time.sleep(FIDS_BACKOFF_S)
            finally:
                if self.log is not None:
                    self.log.record(nbytes)
        try:
            body = r.json()
        except ValueError as e:
            raise TdxError("TDX 航班回傳不是 JSON", "bad_json") from e
        if not isinstance(body, list):
            raise TdxError("TDX 航班回傳格式不對", "bad_format")
        out = {
            str(a.get("AirportID") or "").strip().upper(): a
            for a in body
            if isinstance(a, dict) and a.get("AirportID")
        }
        missing = [c for c in want if c not in out]
        if missing:
            log.warning("TDX 航班沒有回這幾個機場：%s", "、".join(missing))
        self._fids[want] = {c: out[c] for c in want if c in out}
        return self._fids[want]
