"""HD34d：颱風名稱表查不到時當報抓三個機關的官方名單更新（`sources/tcnames.py`、
`typhoons.merge_names`／`refresh_names`／`read_names`）。fixture 是 2026-10-26 抓的官方頁，只留
標題與名單表格（`tests/fixtures/README.md`）。"""

from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from conftest import FIXTURES, ROOT, utc

from hongthai import typhoons
from hongthai.sources import tcnames
from hongthai.sources.tcnames import NameLists, NamesError, Page

AT = utc(2026, 10, 27, 1, 5)
REPO = json.loads((ROOT / typhoons.NAMES_FILENAME).read_text("utf-8"))
PAGES = {
    tcnames.CWA_URL: "tcnames_cwa_typhoon-07.html",
    tcnames.HKO_URL.format(lang="tc", year=2026): "tcnames_hko_tc_2026.html",
    tcnames.HKO_URL.format(lang="en", year=2026): "tcnames_hko_en_2026.html",
    tcnames.NMC_URL: "tcnames_nmc.html",
}


def _html(url: str) -> str:
    return (FIXTURES / PAGES[url]).read_text("utf-8")


def _lists() -> NameLists:
    def page(url: str, parsed: tuple[str, list[tuple[str, str]]]) -> Page:
        return Page(url, *parsed)

    hko_tc, hko_en = (tcnames.HKO_URL.format(lang=x, year=2026) for x in ("tc", "en"))
    return NameLists(
        page(tcnames.CWA_URL, tcnames.parse_cwa(_html(tcnames.CWA_URL))),
        page(hko_tc, tcnames.parse_hko(_html(hko_tc), "tc")),
        page(hko_en, tcnames.parse_hko(_html(hko_en), "en")),
        page(tcnames.NMC_URL, tcnames.parse_nmc(_html(tcnames.NMC_URL))),
    )


def _fake_http(monkeypatch, pages: dict[str, str | int], calls: list[str] | None = None):
    """`tcnames.http_get` 換成照網址回 `pages` 的內容（數字是 HTTP 狀態碼：404 照 `ok_404` 回傳，
    其他丟 `NamesError`）。"""

    def get(url, *, ok_404=False, error=NamesError, **kw):
        if calls is not None:
            calls.append(url)
        body = pages.get(url, 404)
        if isinstance(body, int):
            if body == 404 and ok_404:
                return SimpleNamespace(status_code=404, content=b"")
            raise error(f"{url}: HTTP {body}", f"http_{body}")
        return SimpleNamespace(status_code=200, content=body.encode("utf-8"))

    monkeypatch.setattr(tcnames, "http_get", get)


def _official(*edits: tuple[str, str, str]) -> dict[str, str | int]:
    """三個官方頁（天文台網址是 2026 年的）；`edits` 是（`cwa`／`hko_tc`／`hko_en`／`nmc`, 原文,
    換成）。"""
    keys = {"cwa": tcnames.CWA_URL, "nmc": tcnames.NMC_URL}
    keys |= {f"hko_{x}": tcnames.HKO_URL.format(lang=x, year=2026) for x in ("tc", "en")}
    out: dict[str, str | int] = {url: _html(url) for url in PAGES}
    for k, old, new in edits:
        text = out[keys[k]]
        assert isinstance(text, str) and text.count(old) == 1, (k, old)
        out[keys[k]] = text.replace(old, new)
    return out


# 「Koki」那格換成新名字（假設 WMO 除名替補）
NEW = (
    ("cwa", "高基<br>Koki", "新名甲<br>Newname"),
    ("hko_tc", ">高基<", ">新名乙<"),
    ("hko_en", ">Koki<", ">Newname<"),
    ("nmc", "<div> Koki </div>", "<div> Newname </div>"),
    ("nmc", "<div> 高基 </div>", "<div> 新名丙 </div>"),
)


# ---- 三個官方頁的解析 ----


def test_parse_official_pages():
    lists = _lists()
    for p in (lists.cwa, lists.hko_tc, lists.hko_en, lists.nmc):
        assert len(p.cells) == tcnames.COUNT == 140
    # 照輪替順序：第 1 組 28 個（柬埔寨、中國…照來源成員順序），再第 2 組
    assert lists.cwa.cells[:3] == [("Damrey", "丹瑞"), ("Tianma", "天馬"), ("Kirogi", "鴻雁")]
    assert lists.cwa.cells[28] == ("Koki", "高基")
    assert lists.cwa.cells[-1] == ("Saobien", "海星")
    assert lists.hko_tc.cells[0] == ("", "達維") and lists.hko_en.cells[0] == ("Damrey", "")
    # 國家氣象中心每格的隱藏說明（div.meaning）不讀
    assert lists.nmc.cells[0] == ("Damrey", "达维")
    assert all("：" not in zh and "：" not in en for en, zh in lists.nmc.cells)
    # 寫法各自照原文（比對時用 `_name_key`）
    assert ("Dim-Sum", "點心") in lists.cwa.cells and ("Dim-sum", "") in lists.hko_en.cells
    assert lists.cwa.title == "表2-1 西北太平洋及南海颱風中文譯名及國際命名對照表(2026年6月更新)"
    assert lists.hko_tc.title == "2026年起生效的西北太平洋及南海熱帶氣旋名字"
    assert lists.nmc.title == REPO["sources"]["zh-CN"]["title"]


def test_parse_rejects_wrong_shape():
    cwa = _html(tcnames.CWA_URL)
    with pytest.raises(NamesError):
        tcnames.parse_cwa("<p>沒有表</p>")
    # 少一列（139 格）
    start = cwa.index("<tr>", cwa.index("<tbody>"))
    end = cwa.index("</tr>", start) + len("</tr>")
    with pytest.raises(NamesError, match="不是 140"):
        tcnames.parse_cwa(cwa[:start] + cwa[end:])
    with pytest.raises(NamesError):
        tcnames.parse_hko("<table id='x'></table>", "tc")
    with pytest.raises(NamesError):
        tcnames.parse_nmc("<table></table>")


def test_merge_matches_repo_table():
    """2026-10-26 抓的三頁解析合併 ＝ repo 的 `typhoon_names.json`（#131 的 140 筆、表名、
    網址）。"""
    new = typhoons.merge_names(_lists(), REPO, AT)
    assert new["names"] == REPO["names"]
    assert new["about"] == REPO["about"]
    for k in ("zh-TW", "zh-HK", "en", "zh-CN"):
        src = new["sources"][k]
        assert {**src, "fetchedAt": "x"} == {**REPO["sources"][k], "fetchedAt": "x"}, k
        assert src["fetchedAt"] == "2026-10-27T01:05Z"
    # 寫出來和 repo 那份同樣排法
    assert typhoons.dump_names(REPO) == (ROOT / typhoons.NAMES_FILENAME).read_text("utf-8")


def test_merge_each_agency_own_column_only():
    """某個機關這一格還是舊名字：那個機關那一欄空著，不拿別人的補、不翻譯。"""
    lists = _lists()
    i = 28  # Koki
    lists.hko_en.cells[i] = ("Newname", "")
    lists.hko_tc.cells[i] = ("", "新名乙")
    lists.nmc.cells[i] = ("Newname", "新名丙")  # 氣象署還是 Koki／高基
    row = typhoons.merge_names(lists, REPO, AT)["names"][i]
    assert row == {"en": "Newname", "zh-TW": "", "zh-HK": "新名乙", "zh-CN": "新名丙"}
    # 只有氣象署換了：多數（天文台、國家氣象中心）還是 Koki → 氣象署那欄空著
    lists = _lists()
    lists.cwa.cells[i] = ("Newname", "新名甲")
    row = typhoons.merge_names(lists, REPO, AT)["names"][i]
    assert row == {"en": "Koki", "zh-TW": "", "zh-HK": "高基", "zh-CN": "高基"}


@pytest.mark.parametrize("bad", ["dup", "blank_en", "empty_col", "count"])
def test_merge_rejects_unreasonable(bad):
    lists = _lists()
    if bad == "dup":  # 英文名重複
        for p in (lists.cwa, lists.hko_en, lists.nmc):
            p.cells[1] = (p.cells[0][0], p.cells[1][1])
    elif bad == "blank_en":
        for p in (lists.cwa, lists.hko_en, lists.nmc):
            p.cells[1] = ("", p.cells[1][1])
    elif bad == "empty_col":  # 某一欄大量空白（超過 14 格）
        lists.nmc.cells[:15] = [(en, "") for en, _ in lists.nmc.cells[:15]]
    else:
        lists = replace(lists, cwa=replace(lists.cwa, cells=lists.cwa.cells[:139]))
    with pytest.raises(ValueError):
        typhoons.merge_names(lists, REPO, AT)
    # 14 格空白還算合理
    lists = _lists()
    lists.nmc.cells[:14] = [(en, "") for en, _ in lists.nmc.cells[:14]]
    assert typhoons.merge_names(lists, REPO, AT)["names"][0]["zh-CN"] == ""


# ---- 抓取 ----


def test_fetch_hko_year_fallback(monkeypatch):
    """天文台網址有年份：先試當年，404 再試前一年；氣象署與國家氣象中心照 #131 的網址。"""
    pages = {
        tcnames.HKO_URL.format(lang=x, year=2026).replace("2026", "2027"): 404 for x in ("tc", "en")
    }
    pages |= _official()
    calls: list[str] = []
    _fake_http(monkeypatch, pages, calls)
    lists = tcnames.fetch(2027)
    assert lists.hko_tc.url.endswith("/tc/informtc/sound/tcname2026e.html")
    assert lists.hko_en.url.endswith("/en/informtc/sound/tcname2026e.html")
    assert sorted(calls) == sorted([*PAGES, *(u for u, v in pages.items() if v == 404)])
    assert typhoons.merge_names(lists, REPO, AT)["names"] == REPO["names"]
    # 當年的就有：不抓前一年
    calls.clear()
    _fake_http(monkeypatch, _official(), calls)
    tcnames.fetch(2026)
    assert len(calls) == 4
    # 兩年都 404、或任一個網站失敗：NamesError
    _fake_http(monkeypatch, {tcnames.CWA_URL: _html(tcnames.CWA_URL)})
    with pytest.raises(NamesError):
        tcnames.fetch(2026)
    _fake_http(monkeypatch, {**_official(), tcnames.CWA_URL: 403})
    with pytest.raises(NamesError) as e:
        tcnames.fetch(2026)
    assert e.value.code == "http_403"


def test_fetch_timeout_and_no_retry(monkeypatch):
    seen = []

    def get(url, **kw):
        seen.append((kw["timeout"], kw["retries"]))
        return SimpleNamespace(status_code=200, content=_official()[url].encode())

    monkeypatch.setattr(tcnames, "http_get", get)
    tcnames.fetch(2026)
    assert seen == [(15, 1)] * 4


# ---- 名稱表自動更新 ----


def _fetch_from(monkeypatch, pages, calls=None):
    _fake_http(monkeypatch, pages, calls)
    return tcnames.fetch


def test_refresh_names_updates_and_once_per_day(monkeypatch, caplog):
    calls: list[str] = []
    fetch = _fetch_from(monkeypatch, _official(*NEW), calls)
    with caplog.at_level("WARNING", logger="hongthai"):
        new = typhoons.refresh_names(REPO, [("NEWNAME", "2641")], AT, fetch)
    assert len(calls) == 4
    table = typhoons.names_table(new)
    assert table["NEWNAME"] == {"zh-TW": "新名甲", "zh-HK": "新名乙", "zh-CN": "新名丙"}
    assert "KOKI" not in table and len(table) == 140
    assert new["refreshTried"] == {"date": "2026-10-27", "names": ["NEWNAME"]}
    assert {v["fetchedAt"] for v in new["sources"].values()} == {"2026-10-27T01:05Z"}
    msgs = [r.getMessage() for r in caplog.records]
    assert msgs == ["颱風名稱 NEWNAME（2641）：refreshed"]
    # 同一天第二報：這個名字抓過了（就算還是查不到）不再抓
    calls.clear()
    caplog.clear()
    with caplog.at_level("WARNING", logger="hongthai"):
        again = typhoons.refresh_names(new, [("Newname", "2641")], AT.replace(hour=8), fetch)
    assert again is new and calls == []
    assert "still_missing（今天抓過了）" in caplog.records[0].getMessage()
    # 同一天、另一個名字：抓；隔天同一個名字：再抓
    still = typhoons.refresh_names(new, [("Other", "2642")], AT.replace(hour=8), fetch)
    assert len(calls) == 4
    assert still["refreshTried"] == {"date": "2026-10-27", "names": ["NEWNAME", "OTHER"]}
    calls.clear()
    nxt = typhoons.refresh_names(still, [("Other", "2642")], utc(2026, 10, 28, 1, 5), fetch)
    assert len(calls) == 4 and nxt["refreshTried"] == {"date": "2026-10-28", "names": ["OTHER"]}


def test_refresh_names_still_missing(monkeypatch, caplog):
    fetch = _fetch_from(monkeypatch, _official())
    with caplog.at_level("WARNING", logger="hongthai"):
        new = typhoons.refresh_names(REPO, [("Newname", "2641")], AT, fetch)
    assert new["names"] == REPO["names"]  # 抓到的表合理就寫（fetchedAt 更新）
    assert new["sources"]["zh-TW"]["fetchedAt"] == "2026-10-27T01:05Z"
    assert [r.getMessage() for r in caplog.records] == ["颱風名稱 Newname（2641）：still_missing"]


@pytest.mark.parametrize("how", ["http", "parse", "unreasonable"])
def test_refresh_names_failure_keeps_table(monkeypatch, caplog, how):
    """抓取失敗、解析不出來、解析出來不合理：名單與 `sources` 不換，只記今天抓過。"""
    pages = _official(*NEW)
    if how == "http":
        pages[tcnames.NMC_URL] = 503
    elif how == "parse":
        pages[tcnames.NMC_URL] = "<html>改版了</html>"
    else:  # 國家氣象中心的表整欄空白
        text = pages[tcnames.NMC_URL]
        assert isinstance(text, str)
        for _, zh in _lists().nmc.cells:
            text = text.replace(f"<div> {zh} </div>", "<div> </div>")
        pages[tcnames.NMC_URL] = text
    fetch = _fetch_from(monkeypatch, pages)
    with caplog.at_level("WARNING", logger="hongthai"):
        new = typhoons.refresh_names(REPO, [("Newname", "2641")], AT, fetch)
    assert (new["names"], new["sources"]) == (REPO["names"], REPO["sources"])
    assert new["refreshTried"] == {"date": "2026-10-27", "names": ["NEWNAME"]}
    (rec,) = [r for r in caplog.records if r.getMessage().startswith("颱風名稱 Newname")]
    assert "fetch_failed" in rec.getMessage()


def test_read_names_data_branch_first(tmp_path):
    repo = tmp_path / "repo.json"
    data = tmp_path / "data.json"
    repo.write_text(typhoons.dump_names(REPO), "utf-8")
    assert typhoons.read_names(data, repo) == REPO  # data 分支沒有 → repo 的
    newer = {
        **REPO,
        "sources": {k: {**v, "fetchedAt": "2026-10-27T01:05Z"} for k, v in REPO["sources"].items()},
        "names": [{**r, "zh-TW": "改"} if r["en"] == "Koki" else r for r in REPO["names"]],
        "refreshTried": {"date": "2026-10-27", "names": ["NEWNAME"]},
    }
    data.write_text(typhoons.dump_names(newer), "utf-8")
    assert typhoons.read_names(data, repo) == newer  # data 分支那份優先
    # repo 那份比較新（之後有人改了 repo 的表）：用 repo 的，`refreshTried` 照 data 分支的
    later = {
        **REPO,
        "sources": {k: {**v, "fetchedAt": "2026-11-01T00:00Z"} for k, v in REPO["sources"].items()},
    }
    repo.write_text(typhoons.dump_names(later), "utf-8")
    assert typhoons.read_names(data, repo) == {**later, "refreshTried": newer["refreshTried"]}
    # data 分支那份壞了 → repo 的；兩份都沒有 → None
    data.write_text("{", "utf-8")
    assert typhoons.read_names(data, repo) == later
    assert typhoons.read_names(tmp_path / "x.json", tmp_path / "y.json") is None
