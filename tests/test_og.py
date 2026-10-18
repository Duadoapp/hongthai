"""分享預覽圖（HD1）：51 張都畫得出來、尺寸與大小、一顆／三顆燈、子集涵蓋、燈號與小字的規則。"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from conftest import ROOT, utc
from fontTools.ttLib import TTFont
from PIL import Image
from test_build import NOW, _fail_all_but, _timing_lines, workspace  # noqa: F401

from hongthai import build, og
from hongthai.timeutil import iso

REAL_RENDER_ALL = og.render_all  # `workspace` 會把 build 裡的換成假的
AIRPORTS = json.loads((ROOT / "airports.json").read_text("utf-8"))["airports"]
T0 = utc(2026, 10, 19, 0)


def slots(levels: list[str]) -> list[dict]:
    return [
        {
            "from": iso(T0 + timedelta(hours=6 * i)),
            "to": iso(T0 + timedelta(hours=6 * i + 6)),
            "level": lv,
        }
        for i, lv in enumerate(levels)
    ]


def airport(iata: str, levels: list[str] | None = None) -> dict:
    a = next(a for a in AIRPORTS if a["iata"] == iata)
    keys = ("icao", "iata", "tz", "name", "region")
    return {**{k: a[k] for k in keys}, "slots": slots(["low"] * 20 if levels is None else levels)}


# ---- 燈號與小字 ----


def test_rule_light_highest_level_and_first_slot():
    # 台北 UTC+8：第 6 格 06Z–12Z ＝ 10/20 14–20 時（第一個中）、第 7 格 12Z–18Z（第一個高，跨午夜）
    a = airport("TPE", ["low"] * 5 + ["medium", "high", "medium", "high"] + ["low"] * 11)
    assert og.rule_light(a) == og.Light(None, "high", "最高：高　10/20 20 時–10/21 02 時")
    a = airport("TPE", ["low"] * 5 + ["medium"] + ["low"] * 14)
    assert og.rule_light(a) == og.Light(None, "medium", "最高：中　10/20 14–20 時")


def test_rule_light_all_low_unknown_and_mixed():
    assert og.rule_light(airport("GUM")).note == "未來 5 天：低"
    assert og.rule_light(airport("GUM")).level == "low"
    assert og.rule_light(airport("GUM", ["unknown"] * 20)) == og.Light(None, "unknown", "資料不足")
    # 有等級的格才算，unknown 不影響
    mixed = airport("GUM", ["unknown"] * 10 + ["low"] * 10)
    assert og.rule_light(mixed) == og.Light(None, "low", "未來 5 天：低")
    assert og.rule_light(airport("GUM", [])).level == "unknown"


def test_rule_light_confirmed_wins():
    a = airport("HKG", ["high"] * 3 + ["confirmed", "confirmed"] + ["low"] * 15)
    # 香港 UTC+8：第 4 格 18Z–00Z ＝ 10/20 02–08 時
    assert og.rule_light(a) == og.Light(None, "confirmed", "已確認停飛　10/20 02–08 時")
    assert og.rule_light(a, label="規則").label == "規則"


@pytest.mark.parametrize(
    ("tz", "start_h", "text"),
    [
        ("Asia/Taipei", 0, "10/19 08–14 時"),
        ("Asia/Taipei", 12, "10/19 20 時–10/20 02 時"),  # 跨午夜
        ("Pacific/Guam", 8, "10/19 18–24 時"),  # 結束在當地午夜
        ("Asia/Ho_Chi_Minh", 17, "10/20 00–06 時"),
        ("Pacific/Palau", 15, "10/20 00–06 時"),
    ],
)
def test_slot_text(tz, start_h, text):
    t = utc(2026, 10, 19, start_h)
    slot = {"from": iso(t), "to": iso(t + timedelta(hours=6))}
    assert og.slot_text(slot, tz) == text


def test_updated_text_uses_airport_timezone():
    assert (
        og.updated_text("2026-10-18T18:15:00Z", "Asia/Taipei")
        == "更新 2026-10-19 02:15（當地時間）"
    )
    assert (
        og.updated_text("2026-10-18T18:15:00Z", "Pacific/Guam")
        == "更新 2026-10-19 04:15（當地時間）"
    )


# ---- 畫圖 ----


def _check_png(path):
    im = Image.open(path)
    assert im.size == (og.WIDTH, og.HEIGHT)
    assert path.stat().st_size <= 60 * 1024
    return im.convert("RGB")


def test_render_all_51_airports(tmp_path):
    latest = {
        "generatedAt": "2026-10-18T18:15:00Z",
        "airports": [
            airport(a["iata"], ["low"] * 4 + ["medium", "high"] + ["unknown"] * 14)
            for a in AIRPORTS
        ],
    }
    (tmp_path / "og").mkdir()
    (tmp_path / "og" / "old.png").write_bytes(b"x")  # 不在這份的舊圖要刪掉
    res = REAL_RENDER_ALL(latest, tmp_path / "og")
    files = sorted(p.name for p in (tmp_path / "og").iterdir())
    assert files == sorted(f"{a['iata'].lower()}.png" for a in AIRPORTS)
    assert len(files) == 51
    assert res == {
        "ok": True,
        "count": 51,
        "bytes": sum(p.stat().st_size for p in (tmp_path / "og").iterdir()),
    }
    im = _check_png(tmp_path / "og" / "tpe.png")
    # 背景與燈（高＝apricot）的顏色和規格一樣
    assert im.getpixel((5, 5)) == (0xED, 0xF1, 0xF4)
    assert im.getpixel((og.WIDTH - og.MARGIN - 20, og.MARGIN + 20)) == (0xF7, 0xC9, 0xA9)
    for p in (tmp_path / "og").iterdir():
        _check_png(p)


def test_render_all_bad_airport_logged_others_drawn(tmp_path):
    bad = {**airport("TSA"), "tz": "Not/AZone"}
    res = REAL_RENDER_ALL(
        {"generatedAt": "2026-10-18T18:15:00Z", "airports": [airport("TPE"), bad]}, tmp_path
    )
    assert res["ok"] is False and res["count"] == 1 and res["error"].startswith("TSA:")
    assert [p.name for p in tmp_path.iterdir()] == ["tpe.png"]


@pytest.mark.parametrize("level", list(og.LEVEL_COLORS))
def test_render_one_light_each_level(tmp_path, level):
    note = "已確認停飛　10/20 20 時–10/21 02 時"
    og.render(
        airport("CXR"), "2026-10-18T18:15:00Z", [og.Light(None, level, note)], tmp_path / "a.png"
    )
    im = _check_png(tmp_path / "a.png")
    bg = og.LEVEL_COLORS[level][0]
    assert im.getpixel((og.WIDTH - og.MARGIN - 20, og.MARGIN + 20)) == og._rgb(bg)


def test_render_three_lights(tmp_path):
    lights = [
        og.Light("規則", "high", "最高：高　10/20 20 時–10/21 02 時"),
        og.Light("Claude", "medium", "沒看到明顯風險"),
        og.Light("Gemini", "unknown", "資料不足"),
    ]
    out = tmp_path / "three.png"
    og.render(airport("SHA"), "2026-10-18T18:15:00Z", lights, out)
    im = _check_png(out)
    # 三塊並排、靠右，各自的顏色
    w = min(og.BLOCK_W, (og.LIGHTS_MAX_W - 2 * og.BLOCK_GAP) // 3)
    right = og.WIDTH - og.MARGIN
    top = og.MARGIN + og.LABEL_SIZE + 14
    for i, lt in enumerate(lights):
        x = right - (3 - i) * w - (2 - i) * og.BLOCK_GAP + 12
        assert im.getpixel((x, top + 12)) == og._rgb(og.LEVEL_COLORS[lt.level][0])


def test_render_needs_a_light(tmp_path):
    with pytest.raises(ValueError):
        og.render(airport("TPE"), "2026-10-18T18:15:00Z", [], tmp_path / "x.png")


# ---- 字型子集 ----


def _cmap(key):
    return set(TTFont(ROOT / "assets" / "fonts" / og.FONT_FILES[key]).getBestCmap())


def test_font_subsets_cover_required_chars():
    """之後加機場或改字串沒重做子集（tools/make_font_subset.py），這裡會紅。"""
    latin, other = og.required_chars(ROOT / "airports.json")
    assert {ord(c) for c in latin} <= _cmap("latin")
    assert set("0123456789") <= latin
    cjk = _cmap("cjk") | _cmap("fallback")
    missing = sorted(c for c in other if ord(c) not in cjk)
    assert not missing, f"子集缺字：{''.join(missing)}（重跑 tools/make_font_subset.py）"


def test_font_files_and_licenses():
    d = ROOT / "assets" / "fonts"
    for f in og.FONT_FILES.values():
        t = TTFont(d / f)
        assert "fvar" not in t  # 都是靜態檔
    assert TTFont(d / og.FONT_FILES["latin"])["OS/2"].usWeightClass == 600
    for name in ("Iansui", "Fraunces", "NotoSansTC"):
        assert "SIL OPEN FONT LICENSE Version 1.1" in (d / f"OFL-{name}.txt").read_text("utf-8")
    assert (d / "README.md").exists()


def test_font_key_routing():
    root = og.font_dir()
    assert og.font_key("T", root) == "latin" and og.font_key("5", root) == "latin"
    assert og.font_key("桃", root) == "cjk"
    assert og.font_key("　", root) == "cjk"


# ---- 接進 build ----


def test_build_draws_og_and_writes_timing(workspace, monkeypatch):  # noqa: F811
    monkeypatch.setattr(build.og, "render_all", REAL_RENDER_ALL)
    _fail_all_but(monkeypatch)
    assert build.main([]) == 0
    pngs = sorted((workspace / "public" / "og").glob("*.png"))
    assert len(pngs) == 51
    line = next(r for r in _timing_lines(workspace) if r["source"] == "og")
    assert set(line) == {"run", "source", "ok", "error", "seconds", "bytes"}
    assert line["ok"] is True and line["error"] is None
    assert line["bytes"] == sum(p.stat().st_size for p in pngs)
    # 不進 data 分支，也不進 latest.json
    assert not (workspace / "data" / "og").exists()
    out = json.loads((workspace / "public" / "latest.json").read_text("utf-8"))
    assert "og" not in out["sources"]


def test_build_og_failure_does_not_fail_build(workspace, monkeypatch):  # noqa: F811
    def boom(latest, out_dir):
        raise RuntimeError("壞了")

    monkeypatch.setattr(build.og, "render_all", boom)
    _fail_all_but(monkeypatch)
    assert build.main([]) == 0
    line = next(r for r in _timing_lines(workspace) if r["source"] == "og")
    assert (line["ok"], line["error"]) == (False, "RuntimeError")


def test_build_crash_draws_og_from_previous(workspace, monkeypatch):  # noqa: F811
    prev = {"schema": 1, "generatedAt": "2026-10-18T01:00:00Z", "airports": [airport("TPE")]}
    (workspace / "data").mkdir()
    (workspace / "data" / "latest.json").write_text(json.dumps(prev), "utf-8")
    monkeypatch.setattr(build.og, "render_all", REAL_RENDER_ALL)
    monkeypatch.setattr(build, "run", lambda **kw: (_ for _ in ()).throw(RuntimeError("bug")))
    monkeypatch.setattr(build, "utcnow", lambda: NOW)
    assert build.main([]) == 1
    assert [p.name for p in (workspace / "public" / "og").iterdir()] == ["tpe.png"]
