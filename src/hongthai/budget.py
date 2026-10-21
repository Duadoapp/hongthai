"""來源的時間預算：每個來源在自己的 daemon 執行緒裡跑，主執行緒最多等預算的秒數，超過就放棄它、
繼續下一個來源（`build._call`）。

被放棄的執行緒不會被強制停掉（Python 做不到），會在背景繼續跑到下一個檢查點：
- 主執行緒超時後設 `cancelled` 旗標；`http_get` 每次請求前、`grib.read_points` 解析前、
  ECMWF 換鏡像前呼叫 `check_cancelled()`，旗標已設就丟 `Cancelled` 直接結束，不再下載或解析
- `Cancelled` 繼承 `BaseException`（同 `asyncio.CancelledError`），來源裡的 `except Exception`
  不會吞掉它
- daemon 執行緒不會擋住程式結束，結束時也不 `join` 它們

執行緒裡可以用 `note()` 記下目前的進度（例如 ECMWF 正在試哪個鏡像）、`add_bytes()` 累計下載量，
超時時主執行緒還讀得到，寫進耗時紀錄。
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field


class Cancelled(BaseException):
    """這個來源已經超過預算被放棄了。"""


@dataclass
class Context:
    cancelled: threading.Event = field(default_factory=threading.Event)
    notes: dict[str, object] = field(default_factory=dict)
    bytes: int = 0


@dataclass
class Outcome:
    result: object = None
    error: BaseException | None = None
    timed_out: bool = False
    seconds: float = 0.0
    context: Context = field(default_factory=Context)


_local = threading.local()


def _current() -> Context | None:
    return getattr(_local, "context", None)


def check_cancelled() -> None:
    """在預算執行緒裡、而且已經被放棄時丟 `Cancelled`；主執行緒或還在預算內時什麼都不做。"""
    ctx = _current()
    if ctx is not None and ctx.cancelled.is_set():
        raise Cancelled()


def note(**kwargs: object) -> None:
    ctx = _current()
    if ctx is not None:
        ctx.notes.update(kwargs)


def add_bytes(n: int) -> None:
    ctx = _current()
    if ctx is not None:
        ctx.bytes += n


def run(name: str, fn: Callable[[], object], seconds: float) -> Outcome:
    """在 daemon 執行緒跑 `fn`，最多等 `seconds` 秒。"""
    out = Outcome()

    def target() -> None:
        _local.context = out.context
        try:
            out.result = fn()
        except BaseException as e:  # 執行緒裡的例外交給主執行緒處理
            out.error = e

    t = threading.Thread(target=target, name=f"source-{name}", daemon=True)
    t0 = time.monotonic()
    t.start()
    t.join(seconds)
    out.seconds = time.monotonic() - t0
    if t.is_alive():
        out.context.cancelled.set()
        out.timed_out = True  # 之後執行緒還可能寫 result／error，呼叫端看到 timed_out 就不理它們
    return out


def context() -> Context | None:
    """目前執行緒的預算 context；來源自己開的工作執行緒要用 `attach()` 接上（HD29）。"""
    return _current()


def attach(ctx: Context | None) -> None:
    """讓這條執行緒共用 `ctx`：`check_cancelled`、`add_bytes` 照這個來源算（HD29 平行抓 CAP）。"""
    _local.context = ctx
