"""颱風名稱的三個官方名單（HD34d，Shawn 2026-10-26 23:43）：`typhoons.refresh_names` 在名稱對照表
（`typhoon_names.json`）查不到某個名字時當報抓這三個機關的頁面，解析成同一個格式。

- 中央氣象署「表2-1 西北太平洋及南海颱風中文譯名及國際命名對照表」（`CWA_URL`，副檔名 `.txt`
  但內容是 HTML 片段、UTF-8）：`<p id="table_title_1">` 是表名；表頭有「第1組」的那張表，每列
  `來源` ＋ 五組，每格「中文<br>English」
- 香港天文台「<年>年起生效的西北太平洋及南海熱帶氣旋名字」中文版與英文版（`HKO_URL`，網址有年份：
  **先試當年、404 再試前一年**；2026-10-26 實測 `tcname2027e.html` 是 404、`tcname2025e.html`
  還在）：`<table id="sound">`，每列 `來源` ＋ 五組、每格一個名字；中英文兩頁同一個格子位置是
  同一個名字
- 中國氣象局國家氣象中心（中央氣象台）「台风命名_西北太平洋」（`NMC_URL`）：`<table
  id="typhoonNameTable">`，每列 `<th>` 來源 ＋ 十格（五組各一格英文名、一格中文名）；每格另有隱藏的
  `div.meaning`（滑鼠移上去才顯示的說明），不讀
- 三份都照「第 1 組到第 5 組、每組 28 個照來源成員的順序」排成 140 格（`typhoon_names.json` 的
  `names` 也是這個順序）；每個機關只解析自己的中文名，**不互相補、不翻譯**
- 三個網站各逾時 `TIMEOUT` 秒、不重試，四個請求（天文台中英文兩頁）平行抓，最壞約 2 × `TIMEOUT` 秒
  （天文台當年的 404 再抓前一年）
- 氣象署的網站擋太短的瀏覽器 User-Agent（`Mozilla/5.0` 回 403 Request Rejected）；照 `http_get`
  用專案自己的 `USER_AGENT` 抓得到（2026-10-26 實測）
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from html.parser import HTMLParser

import requests

from . import NonStrictTLSAdapter, SourceError, http_get

CWA_URL = "https://www.cwa.gov.tw/V8/C/K/Encyclopedia/typhoon/typhoon-07.txt"
HKO_URL = "https://www.hko.gov.hk/{lang}/informtc/sound/tcname{year}e.html"
NMC_URL = "https://www.nmc.cn/publish/typhoon/typhoon-name/index.html"
TIMEOUT = 15
GROUPS = 5
PER_GROUP = 28
COUNT = GROUPS * PER_GROUP  # 140
# 每個機關的機關名稱（寫進 `typhoon_names.json` 的 `sources`）
AGENCIES = {
    "cwa": "中央氣象署",
    "hko": "香港天文台",
    "nmc": "中国气象局国家气象中心（中央气象台）",
}


class NamesError(SourceError):
    pass


@dataclass
class Page:
    """一個官方頁解析出來的名單：`cells` 照輪替順序 140 格，每格（英文名, 中文名）；天文台英文版
    的中文名是空字串、中文版的英文名是空字串。"""

    url: str
    title: str
    cells: list[tuple[str, str]]


@dataclass
class NameLists:
    cwa: Page
    hko_tc: Page
    hko_en: Page
    nmc: Page


# ---- 解析 ----


class _Tables(HTMLParser):
    """把 HTML 裡的表格拆成 [(表格屬性, [[(格子標籤, [文字段, …]), …], …])]。`<br>`、`<div>`、
    `<p>`、`<span>` 都當成分段；class 有 `meaning` 的元素整個略過（國家氣象中心的隱藏說明）。"""

    BREAKS = {"br", "div", "p", "span"}
    VOID = {"br", "img", "input", "meta", "link", "hr", "wbr", "source"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[tuple[dict[str, str], list[list[tuple[str, list[str]]]]]] = []
        self._stack: list[tuple[dict[str, str], list[list[tuple[str, list[str]]]]]] = []
        self._cell: tuple[str, list[str]] | None = None
        self._buf = ""
        self._skip = 0  # 在略過的元素裡的深度（0 = 沒有在略過）

    def _flush(self) -> None:
        if self._cell is not None and self._buf.strip():
            self._cell[1].append(" ".join(self._buf.split()))
        self._buf = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: v or "" for k, v in attrs}
        if self._skip:
            if tag not in self.VOID:
                self._skip += 1
            return
        if "meaning" in a.get("class", "").split() and tag not in self.VOID:
            self._flush()
            self._skip = 1
            return
        if tag == "table":
            self._stack.append((a, []))
        elif tag == "tr" and self._stack:
            self._stack[-1][1].append([])
        elif tag in ("td", "th") and self._stack and self._stack[-1][1]:
            self._flush()
            self._cell = (tag, [])
            self._stack[-1][1][-1].append(self._cell)
        elif tag in self.BREAKS:
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        if self._skip:
            self._skip -= 1
            return
        if tag in ("td", "th"):
            self._flush()
            self._cell = None
        elif tag == "table" and self._stack:
            self._flush()
            self._cell = None
            self.tables.append(self._stack.pop())
        elif tag in self.BREAKS:
            self._flush()

    def handle_data(self, data: str) -> None:
        if not self._skip and self._cell is not None:
            self._buf += data


def _tables(html: str) -> list[tuple[dict[str, str], list[list[tuple[str, list[str]]]]]]:
    p = _Tables()
    p.feed(html)
    p.close()
    return p.tables


def _data_rows(rows: list[list[tuple[str, list[str]]]], width: int) -> list[list[list[str]]]:
    """有 `width` 個 `<td>` 的列（表頭是 `<th>`、不算），只留 `<td>` 的文字段。"""
    out = []
    for row in rows:
        tds = [segs for tag, segs in row if tag == "td"]
        if len(tds) == width:
            out.append(tds)
    return out


def _check(cells: list[tuple[str, str]], what: str) -> list[tuple[str, str]]:
    if len(cells) != COUNT:
        raise NamesError(f"{what}：解析出 {len(cells)} 格，不是 {COUNT}", "parse")
    return cells


def _title(html: str, pattern: str) -> str:
    m = re.search(pattern, html, re.S)
    return " ".join(re.sub(r"<[^>]+>", "", m.group(1)).split()) if m else ""


def parse_cwa(html: str) -> tuple[str, list[tuple[str, str]]]:
    """氣象署表2-1 → （表名, 140 格（英文名, 中文名））。每格第一段中文、最後一段英文。"""
    table = next(
        (
            rows
            for _, rows in _tables(html)
            if any("第1組" in x for r in rows for _, c in r for x in c)
        ),
        None,
    )
    if table is None:
        raise NamesError("氣象署：找不到「第1組」的表", "parse")
    rows = _data_rows(table, 1 + GROUPS)
    cells = []
    for g in range(1, GROUPS + 1):
        for r in rows:
            segs = r[g]
            cells.append((segs[-1] if len(segs) >= 2 else "", segs[0] if len(segs) >= 2 else ""))
    title = _title(html, r'<p[^>]*id="table_title_1"[^>]*>(.*?)</p>')
    return title, _check(cells, "氣象署")


def parse_hko(html: str, lang: str) -> tuple[str, list[tuple[str, str]]]:
    """天文台 `<table id="sound">` → （頁面標題, 140 格）。`lang` 是 `tc`（中文名放第二欄）或 `en`
    （英文名放第一欄）。"""
    table = next((rows for attrs, rows in _tables(html) if attrs.get("id") == "sound"), None)
    if table is None:
        raise NamesError("天文台：找不到 table#sound", "parse")
    rows = _data_rows(table, 1 + GROUPS)
    cells = []
    for g in range(1, GROUPS + 1):
        for r in rows:
            name = " ".join(r[g])
            cells.append((name, "") if lang == "en" else ("", name))
    title = _title(html, r"<title>(.*?)</title>").split("｜")[0].split("|")[0].strip()
    return title, _check(cells, f"天文台（{lang}）")


def parse_nmc(html: str) -> tuple[str, list[tuple[str, str]]]:
    """國家氣象中心 `<table id="typhoonNameTable">` → （標題, 140 格（英文名, 中文名））。標題是頁面
    `<title>` 的「台风命名_西北太平洋」加上表名與生效日（頁面上的「（自…起执行）」）。"""
    table = next(
        (rows for attrs, rows in _tables(html) if attrs.get("id") == "typhoonNameTable"), None
    )
    if table is None:
        raise NamesError("國家氣象中心：找不到 table#typhoonNameTable", "parse")
    rows = _data_rows(table, 2 * GROUPS)
    cells = []
    for g in range(GROUPS):
        for r in rows:
            cells.append((" ".join(r[2 * g]), " ".join(r[2 * g + 1])))
    page = _title(html, r"<title>(.*?)</title>")
    page = page.removeprefix("台风海洋_")
    caption = _title(html, r"<strong>([^<]*命名表)注释</strong>")
    since = _title(html, r"<strong>（(自[^<]*?起执行)）</strong>")
    extra = "，".join(x for x in (caption, since) if x)
    return (f"{page}（{extra}）" if extra else page), _check(cells, "國家氣象中心")


# ---- 抓取 ----


def _session() -> requests.Session:
    s = requests.Session()
    s.mount("https://", NonStrictTLSAdapter())  # 氣象署的憑證（見 `NonStrictTLSAdapter`）
    return s


def _get(url: str, session: requests.Session, ok_404: bool = False) -> requests.Response:
    return http_get(
        url, session=session, retries=1, timeout=TIMEOUT, error=NamesError, ok_404=ok_404
    )


def _text(r: requests.Response) -> str:
    return r.content.decode("utf-8", errors="replace")


def fetch_cwa(session: requests.Session) -> Page:
    title, cells = parse_cwa(_text(_get(CWA_URL, session)))
    return Page(CWA_URL, title, cells)


def fetch_hko(session: requests.Session, lang: str, year: int) -> Page:
    """天文台當年那頁；404 就抓前一年。"""
    for y in (year, year - 1):
        url = HKO_URL.format(lang=lang, year=y)
        r = _get(url, session, ok_404=True)
        if r.status_code != 404:
            title, cells = parse_hko(_text(r), lang)
            return Page(url, title, cells)
    raise NamesError(f"天文台 {lang}：{year}、{year - 1} 年的頁面都是 404", "http_404")


def fetch_nmc(session: requests.Session) -> Page:
    title, cells = parse_nmc(_text(_get(NMC_URL, session)))
    return Page(NMC_URL, title, cells)


def fetch(year: int) -> NameLists:
    """平行抓三個機關（天文台中英文兩頁）；任一個失敗丟 `NamesError`（`code` 是第一個失敗的
    原因）。"""
    jobs = {  # 每個請求各自一個 Session（requests.Session 不保證執行緒安全）
        "cwa": lambda: fetch_cwa(_session()),
        "hko_tc": lambda: fetch_hko(_session(), "tc", year),
        "hko_en": lambda: fetch_hko(_session(), "en", year),
        "nmc": lambda: fetch_nmc(_session()),
    }
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futures = {k: pool.submit(fn) for k, fn in jobs.items()}
        pages: dict[str, Page] = {}
        errors: dict[str, Exception] = {}
        for k, fut in futures.items():
            try:
                pages[k] = fut.result()
            except Exception as e:  # 解析的意外錯誤也當失敗
                errors[k] = e
    if errors:
        k, e = next(iter(errors.items()))
        code = getattr(e, "code", "parse")
        raise NamesError(f"{', '.join(errors)} 失敗：{e}", code) from e
    return NameLists(**pages)
