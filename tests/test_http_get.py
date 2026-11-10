"""`http_get` 的回應大小上限（HD44）：分塊讀、超過就關連線丟 `too_large`、不重試；其他照舊。"""

from __future__ import annotations

import io

import pytest
import requests
from requests.structures import CaseInsensitiveDict

from hongthai import budget, sources
from hongthai.sources import SourceError, http_get

URL = "https://example.test/data.json"


class Raw(io.BytesIO):
    """`requests.Response.raw` 的替身：記讀了多少、有沒有被關。"""

    def __init__(self, body: bytes):
        super().__init__(body)
        self.read_bytes = 0
        self.was_closed = False

    def read(self, n=-1, **_):
        out = super().read(n)
        self.read_bytes += len(out)
        return out

    def close(self):
        self.was_closed = True
        super().close()


def response(body: bytes, status: int = 200, content_length: int | None = None):
    r = requests.Response()
    r.status_code = status
    r.url = URL
    r.headers = CaseInsensitiveDict()
    if content_length is not None:
        r.headers["Content-Length"] = str(content_length)
    r.raw = Raw(body)
    return r


class FakeGet:
    """假的 `requests.get`：依序回 `script` 裡的回應（例外就丟），記下每次的參數。"""

    def __init__(self, *script):
        self.script = list(script)
        self.calls: list[dict] = []

    def __call__(self, url, **kw):
        self.calls.append(kw)
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


@pytest.fixture
def fake(monkeypatch):
    def install(*script):
        get = FakeGet(*script)
        monkeypatch.setattr(sources.requests, "get", get)
        monkeypatch.setattr(sources.time, "sleep", lambda s: None)
        return get

    return install


def bytes_counted(fn) -> tuple[object, int]:
    """在預算執行緒裡跑 `fn`，回傳（結果或例外, `add_bytes` 累計）。"""
    out = budget.run("t", fn, 5)
    return (out.error if out.error is not None else out.result), out.context.bytes


def test_normal_response_reads_body_and_keeps_response_api(fake):
    get = fake(response(b'{"a": 1}', content_length=8))
    r, n = bytes_counted(lambda: http_get(URL, max_bytes=100))
    assert get.calls[0]["stream"] is True
    assert r.status_code == 200 and r.url == URL
    assert r.content == b'{"a": 1}' and r.text == '{"a": 1}' and r.json() == {"a": 1}
    assert n == 8


def test_exactly_at_limit_is_ok(fake):
    body = b"x" * 100
    fake(response(body, content_length=100))
    assert http_get(URL, max_bytes=100).content == body
    fake(response(body))  # 沒有 Content-Length
    assert http_get(URL, max_bytes=100).content == body


def test_content_length_over_limit_gives_up_without_reading(fake, caplog):
    r = response(b"x" * 1000, content_length=1000)
    get = fake(r)
    err, n = bytes_counted(lambda: http_get(URL, max_bytes=100, error=MyError))
    assert isinstance(err, MyError) and err.code == "too_large"
    assert len(get.calls) == 1  # 不重試
    assert r.raw.read_bytes == 0 and r.raw.was_closed
    assert n == 0
    assert "100" in caplog.text and URL in caplog.text


def test_no_content_length_stops_while_reading(fake):
    body = b"x" * (sources.CHUNK_BYTES * 3)
    r = response(body)
    get = fake(r)
    limit = sources.CHUNK_BYTES + 10
    err, n = bytes_counted(lambda: http_get(URL, max_bytes=limit, error=MyError))
    assert isinstance(err, MyError) and err.code == "too_large"
    assert len(get.calls) == 1
    assert r.raw.was_closed and r.raw.read_bytes < len(body)  # 沒讀完就關
    assert n == sources.CHUNK_BYTES * 2  # 已讀的照算進下載量


def test_lying_content_length_still_counted(fake):
    """`Content-Length` 比實際小（例如 gzip 壓縮後的長度）：還是邊讀邊數。"""
    fake(response(b"x" * 500, content_length=50))
    with pytest.raises(SourceError) as e:
        http_get(URL, max_bytes=100)
    assert e.value.code == "too_large"


def test_too_large_on_error_status_not_retried(fake):
    get = fake(response(b"x" * 500, status=503, content_length=500), response(b"ok"))
    with pytest.raises(SourceError) as e:
        http_get(URL, max_bytes=100)
    assert e.value.code == "too_large" and len(get.calls) == 1


def test_log_truncates_long_url(fake, caplog):
    long_url = URL + "?q=" + "a" * 500
    r = response(b"x" * 500, content_length=500)
    r.url = long_url
    fake(r)
    with pytest.raises(SourceError):
        http_get(long_url, max_bytes=100)
    assert long_url[:200] + "…" in caplog.text and long_url not in caplog.text


def test_ok_404_unchanged(fake):
    get = fake(response(b"nope", status=404))
    r = http_get(URL, ok_404=True, max_bytes=100)
    assert r.status_code == 404 and r.content == b"nope" and len(get.calls) == 1


def test_404_without_ok_404_still_retries(fake):
    get = fake(*(response(b"nope", status=404) for _ in range(3)))
    with pytest.raises(SourceError) as e:
        http_get(URL)
    assert e.value.code == "http_404" and len(get.calls) == 3


def test_timeout_retries_unchanged(fake):
    get = fake(requests.Timeout("slow"), response(b"ok"))
    assert http_get(URL, retries=2).content == b"ok"
    assert len(get.calls) == 2 and all(c["timeout"] == sources.TIMEOUT for c in get.calls)
    get = fake(requests.Timeout("slow"), requests.Timeout("slow"))
    with pytest.raises(SourceError) as e:
        http_get(URL, retries=2)
    assert e.value.code == "timeout" and len(get.calls) == 2


def test_403_not_retried_unchanged(fake):
    get = fake(response(b"no", status=403), response(b"ok"))
    with pytest.raises(SourceError) as e:
        http_get(URL)
    assert e.value.code == "http_403" and len(get.calls) == 1


def test_session_gets_stream_too(monkeypatch):
    calls = []

    class S:
        def get(self, url, **kw):
            calls.append(kw)
            return response(b"ok")

    assert http_get(URL, session=S()).content == b"ok"
    assert calls[0]["stream"] is True


def test_limits_leave_room_over_measured_max():
    """2026-11-10 實測：一般回應最大約 1.8 MB（TDX）、GRIB 一段最大約 1.9 MB；上限至少 4 倍。"""
    assert sources.MAX_BYTES >= 4 * 1_800_000
    assert sources.GRIB_MAX_BYTES >= 4 * 1_900_000 and sources.GRIB_MAX_BYTES > sources.MAX_BYTES


def test_grib_downloads_pass_bigger_limit(monkeypatch, tmp_path):
    from hongthai.sources import gfs

    seen = []

    def get(url, **kw):
        seen.append(kw.get("max_bytes"))
        return response(b"GRIB....7777", status=206)

    monkeypatch.setattr(gfs, "http_get", get)
    gfs.download_ranges(URL, [(0, 11), (12, None)], tmp_path / "x.grib2", gfs.GfsError)
    assert seen == [sources.GRIB_MAX_BYTES] * 2


class MyError(SourceError):
    pass
