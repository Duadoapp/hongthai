"""分享預覽圖（HD1）：每個機場一張 1200×630 的 PNG，發布到 GitHub Pages 的 `og/<iata>.png`
（iata 小寫）。

規格是 Duado #374 定的、預設值 Shawn 2026-10-19 拍板（`docs/prompts/2026-10-19-HD1-og-image.md`）：
- 內容：左上 IATA 大字、其下機場名 zh-TW＋en；右上燈號色塊與一行小字；左下更新時間（機場當地時間）；
  右下「HongThai　機場停飛風險」與 `duado.app/hongthai`。不放 logo、不放地圖
- 燈號（`rule_light`）：這個機場未來 5 天（20 格）裡最高的等級，小字寫第一個達到那個等級的格的當地
  日期時段（「最高：高　10/23 14–20 時」）；全部低寫「未來 5 天：低」。有 `confirmed` 的格（視為高）
  時色塊寫「已確認」、小字「已確認停飛　<第一個已確認的格>」；全部 `unknown` 寫「資料不足」；
  有的格 `unknown`、有的有等級時只看有等級的
- 三顆燈：`render` 吃 `lights: list[Light]`，現在只傳一顆規則燈（`label=None` 不畫標籤）；AI 對決時
  多傳兩顆（`label="Claude"`／`"Gemini"`，規則燈 `label="規則"`），色塊寬度自動排
- 顏色、字型都是 Duado 晨光風格：淺底、大圓角色塊、不用框線與陰影、不做深色版
  （`COLORS`、`LEVEL_COLORS`）
- 字型（`assets/fonts/`，都是 SIL OFL 1.1，只放子集）：ASCII 與數字用 Fraunces（SOFT 100、
  wght 600 的靜態檔），其他字用芫荽，芫荽沒有的字才用 Noto Sans TC。Pillow 不會自動補字，
  所以逐字分段（`_runs`）、各段用自己的字型畫在同一條基線上。子集怎麼重做見 `assets/fonts/README.md`
- PNG 轉成調色盤模式＋`optimize=True`，每張約 15–20 KB（目標 ≤ 60 KB）。調色盤是固定的
  （`_palette`）：上面幾個顏色本身，加上會相鄰的兩色之間的 `BLEND_STEPS` 個中間色（文字與圓角的
  反鋸齒），所以色塊與底色的顏色和規格完全一樣
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import cache
from pathlib import Path
from zoneinfo import ZoneInfo

from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont

from . import budget
from .timeutil import parse_time

log = logging.getLogger("hongthai")

WIDTH, HEIGHT = 1200, 630
MARGIN = 64

COLORS = {"background": "#EDF1F4", "text": "#263038"}
# 燈的底色與字色（Duado 晨光色）。`confirmed` 的底色深，字用淺色
LEVEL_COLORS: dict[str, tuple[str, str]] = {
    "low": ("#C2DCC6", "#263038"),  # sage
    "medium": ("#F3E3A5", "#263038"),  # butter
    "high": ("#F7C9A9", "#263038"),  # apricot
    "confirmed": ("#263038", "#EDF1F4"),  # text
    "unknown": ("#D8DEE3", "#263038"),  # mapIdle
}
LEVEL_TEXT = {
    "low": "低",
    "medium": "中",
    "high": "高",
    "confirmed": "已確認",
    "unknown": "資料不足",
}
RANKED = ("low", "medium", "high")

# 圖上會出現的固定字串（子集要涵蓋；`tools/make_font_subset.py` 與測試都讀這裡）。
# 「沒看到明顯風險」與三個標籤是 AI 對決那支要用的，先放進子集
TEXTS = (
    *LEVEL_TEXT.values(),
    "最高：",
    "未來 5 天：",
    "已確認停飛",
    "時",
    "更新",
    "（當地時間）",
    "HongThai　機場停飛風險",
    "duado.app/hongthai",
    "規則",
    "Claude",
    "Gemini",
    "沒看到明顯風險",
)
# 全形標點與幾個符號（子集要涵蓋，機場名或之後的字串可能用到）
PUNCTUATION = "，。、：；！？（）「」『』　・–—～／％"

FONT_FILES = {
    "latin": "Fraunces-Soft600.subset.ttf",
    "cjk": "Iansui-Regular.subset.ttf",
    "fallback": "NotoSansTC-Regular.subset.ttf",
}

# 版面（px）
IATA_SIZE = 160
NAME_SIZE = 56
NAME_EN_SIZE = 36
BLOCK_W, BLOCK_H, BLOCK_R = 300, 110, 28
BLOCK_TEXT_SIZE = 52
BLOCK_GAP = 24
LABEL_SIZE = 26
NOTE_SIZE = 28
UPDATED_SIZE = 28
BRAND_SIZE = 32
URL_SIZE = 24
LIGHTS_MAX_W = 620  # 三顆燈並排時佔的最大寬度
BLEND_STEPS = 7


@dataclass(frozen=True)
class Light:
    """一顆燈。`level`：low／medium／high／confirmed／unknown；`label` 是 None 時不畫標籤。"""

    label: str | None
    level: str
    note: str


def font_dir() -> Path:
    """`assets/fonts/`：先找原始碼樹（`src/hongthai/og.py` 往上兩層），沒有再找目前目錄
    （Actions 是 `pip install .` 後在 repo 根目錄跑）。"""
    here = Path(__file__).resolve().parents[2] / "assets" / "fonts"
    return here if here.is_dir() else Path.cwd() / "assets" / "fonts"


@cache
def _font(key: str, size: int, root: Path) -> ImageFont.FreeTypeFont:
    # 固定用 BASIC 排版：有沒有裝 raqm 畫出來都一樣
    return ImageFont.truetype(
        str(root / FONT_FILES[key]), size, layout_engine=ImageFont.Layout.BASIC
    )


@cache
def _cmap(key: str, root: Path) -> frozenset[int]:
    return frozenset(TTFont(root / FONT_FILES[key], lazy=True).getBestCmap())


def font_key(ch: str, root: Path) -> str:
    """ASCII（含數字）→ Fraunces；其他字芫荽有就用芫荽，沒有用 Noto。"""
    if ord(ch) < 128:
        return "latin"
    return "cjk" if ord(ch) in _cmap("cjk", root) else "fallback"


def _runs(text: str, root: Path) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for ch in text:
        k = font_key(ch, root)
        if out and out[-1][0] == k:
            out[-1] = (k, out[-1][1] + ch)
        else:
            out.append((k, ch))
    return out


class _Canvas:
    def __init__(self, root: Path):
        self.root = root
        self.img = Image.new("RGB", (WIDTH, HEIGHT), COLORS["background"])
        self.draw = ImageDraw.Draw(self.img)

    def width(self, text: str, size: int) -> float:
        return sum(_font(k, size, self.root).getlength(s) for k, s in _runs(text, self.root))

    def cap(self, size: int) -> int:
        """Fraunces 大寫字母的高度（基線到頂）。"""
        return -_font("latin", size, self.root).getbbox("H", anchor="ls")[1]

    def fit(self, text: str, size: int, max_w: float, min_size: int = 12) -> int:
        while size > min_size and self.width(text, size) > max_w:
            size -= 1
        return size

    def text(
        self, x: float, baseline: float, text: str, size: int, fill: str, align: str = "left"
    ) -> None:
        """畫一行（各段用自己的字型、對齊同一條基線）。`align`：left／right／center，x 是那一側。"""
        w = self.width(text, size)
        x = {"left": x, "right": x - w, "center": x - w / 2}[align]
        for k, s in _runs(text, self.root):
            f = _font(k, size, self.root)
            self.draw.text((x, baseline), s, font=f, fill=fill, anchor="ls")
            x += f.getlength(s)

    def block(self, x: int, y: int, w: int, h: int, fill: str) -> None:
        """圓角色塊；四倍大畫遮罩再縮小，邊緣才平滑。"""
        s = 4
        mask = Image.new("L", (w * s, h * s), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            (0, 0, w * s - 1, h * s - 1), radius=BLOCK_R * s, fill=255
        )
        mask = mask.resize((w, h), Image.Resampling.LANCZOS)
        self.img.paste(Image.new("RGB", (w, h), fill), (x, y), mask)


def _rgb(hex_color: str) -> tuple[int, int, int]:
    return tuple(int(hex_color[i : i + 2], 16) for i in (1, 3, 5))  # type: ignore[return-value]


@cache
def _palette() -> Image.Image:
    """固定調色盤：底色、文字色、燈的底色與字色，以及會相鄰的兩色之間的中間色。"""
    bg, ink = COLORS["background"], COLORS["text"]
    pairs = {(bg, ink)} | {(bg, b) for b, _ in LEVEL_COLORS.values()}
    pairs |= {(b, f) for b, f in LEVEL_COLORS.values()}
    colors: list[tuple[int, int, int]] = []
    for a, b in sorted(pairs):
        ra, rb = _rgb(a), _rgb(b)
        for i in range(BLEND_STEPS + 2):
            t = i / (BLEND_STEPS + 1)
            c = tuple(round(x + (y - x) * t) for x, y in zip(ra, rb, strict=True))
            if c not in colors:
                colors.append(c)  # type: ignore[arg-type]
    pal = Image.new("P", (1, 1))
    pal.putpalette([v for c in colors for v in c])
    return pal


def _lights(c: _Canvas, lights: list[Light]) -> int:
    """右上的燈號（並排、靠右）；回傳燈號區最左邊的 x。"""
    n = len(lights)
    right = WIDTH - MARGIN
    w = min(BLOCK_W, int((LIGHTS_MAX_W - BLOCK_GAP * (n - 1)) / n))
    left = right - n * w - (n - 1) * BLOCK_GAP
    labelled = any(lt.label for lt in lights)
    top = MARGIN + (LABEL_SIZE + 14 if labelled else 0)
    note_base = top + BLOCK_H + NOTE_SIZE + 16
    for i, lt in enumerate(lights):
        x = left + i * (w + BLOCK_GAP)
        bg, fg = LEVEL_COLORS.get(lt.level, LEVEL_COLORS["unknown"])
        if lt.label:
            c.text(
                x + w / 2,
                MARGIN + LABEL_SIZE * 0.85,
                lt.label,
                LABEL_SIZE,
                COLORS["text"],
                "center",
            )
        c.block(x, top, w, BLOCK_H, bg)
        word = LEVEL_TEXT.get(lt.level, LEVEL_TEXT["unknown"])
        size = c.fit(word, BLOCK_TEXT_SIZE, w - 40)
        # 漢字大致是 em 方塊，中心在基線上方約 0.38 em
        c.text(x + w / 2, top + BLOCK_H / 2 + size * 0.38, word, size, fg, "center")
        if n == 1:  # 一顆燈時小字靠右、可以比色塊寬
            size = c.fit(lt.note, NOTE_SIZE, right - 560)
            c.text(right, note_base, lt.note, size, COLORS["text"], "right")
        else:  # 三顆燈時小字在各自色塊下置中，太長就在全形空白處換行
            size = NOTE_SIZE - 4
            lines = [lt.note]
            if c.fit(lt.note, size, w) < 20:
                lines = lt.note.split("　")
            for j, line in enumerate(lines):
                c.text(
                    x + w / 2,
                    note_base + j * (size + 10),
                    line,
                    c.fit(line, size, w),
                    COLORS["text"],
                    "center",
                )
    return left


def updated_text(generated_at: str, tz: str) -> str:
    t = parse_time(generated_at).astimezone(ZoneInfo(tz))
    return f"更新 {t:%Y-%m-%d %H:%M}（當地時間）"


def render(airport: dict, generated_at: str, lights: list[Light], out_path: Path) -> int:
    """畫一張預覽圖寫到 `out_path`（純畫圖，不讀網路）；回傳檔案大小（bytes）。

    `airport` 是 `latest.json` 的 `airports[]` 一筆（用 `iata`、`tz`、`name`）。
    """
    if not lights:
        raise ValueError("至少要一顆燈")
    c = _Canvas(font_dir())
    ink = COLORS["text"]
    lights_left = _lights(c, lights)
    col_w = lights_left - 40 - MARGIN

    iata_size = c.fit(airport["iata"], IATA_SIZE, col_w, 80)
    iata_base = MARGIN + c.cap(iata_size)
    c.text(MARGIN, iata_base, airport["iata"], iata_size, ink)
    name = airport["name"]
    zh_base = iata_base + 40 + NAME_SIZE
    c.text(MARGIN, zh_base, name["zh-TW"], c.fit(name["zh-TW"], NAME_SIZE, col_w), ink)
    c.text(MARGIN, zh_base + 54, name["en"], c.fit(name["en"], NAME_EN_SIZE, col_w), ink)

    bottom = HEIGHT - MARGIN
    c.text(MARGIN, bottom, updated_text(generated_at, airport["tz"]), UPDATED_SIZE, ink)
    c.text(WIDTH - MARGIN, bottom, "duado.app/hongthai", URL_SIZE, ink, "right")
    c.text(
        WIDTH - MARGIN, bottom - URL_SIZE - 22, "HongThai　機場停飛風險", BRAND_SIZE, ink, "right"
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img = c.img.quantize(palette=_palette(), dither=Image.Dither.NONE)
    img.save(out_path, format="PNG", optimize=True)
    return out_path.stat().st_size


def slot_text(slot: dict, tz: str) -> str:
    """一格的當地日期時段：「10/23 14–20 時」；結束在午夜寫 24（「10/23 18–24 時」）；
    跨過午夜寫兩個日期（「10/23 20 時–10/24 02 時」，UTC+8 的機場一天有一格這樣）。"""
    z = ZoneInfo(tz)
    a, b = parse_time(slot["from"]).astimezone(z), parse_time(slot["to"]).astimezone(z)

    def hm(t: datetime) -> str:
        return f"{t:%H}" if t.minute == 0 else f"{t:%H:%M}"

    if b.date() == a.date():
        return f"{a.month}/{a.day} {hm(a)}–{hm(b)} 時"
    if b.date() == a.date() + timedelta(days=1) and (b.hour, b.minute) == (0, 0):
        return f"{a.month}/{a.day} {hm(a)}–24 時"
    return f"{a.month}/{a.day} {hm(a)} 時–{b.month}/{b.day} {hm(b)} 時"


def rule_light(airport: dict, label: str | None = None) -> Light:
    """規則燈：未來 5 天（`slots`）最高的等級與小字（規則見模組說明）。"""
    slots = [s for s in airport.get("slots") or [] if isinstance(s, dict)]
    tz = airport["tz"]
    confirmed = [s for s in slots if s.get("level") == "confirmed"]
    if confirmed:
        return Light(label, "confirmed", f"已確認停飛　{slot_text(confirmed[0], tz)}")
    known = [s for s in slots if s.get("level") in RANKED]
    if not known:
        return Light(label, "unknown", "資料不足")
    top = max((s["level"] for s in known), key=RANKED.index)
    if top == "low":
        return Light(label, "low", "未來 5 天：低")
    first = next(s for s in known if s["level"] == top)
    return Light(label, top, f"最高：{LEVEL_TEXT[top]}　{slot_text(first, tz)}")


def render_all(latest: dict, out_dir: Path) -> dict:
    """`latest.json` 的每個機場畫一張 `out_dir/<iata 小寫>.png`；`out_dir` 裡不在這份的舊圖刪掉。

    一張畫不出來只 log、繼續畫其他張。回傳 `{"ok", "count", "bytes"}`（失敗的另有 `error`），
    給 `build` 寫耗時紀錄。
    """
    generated_at = latest["generatedAt"]
    airports = [a for a in latest.get("airports") or [] if isinstance(a, dict)]
    out_dir.mkdir(parents=True, exist_ok=True)
    keep = {f"{a.get('iata', '').lower()}.png" for a in airports}
    for p in out_dir.glob("*.png"):
        if p.name not in keep:
            p.unlink()
    total, count, errors = 0, 0, []
    for a in airports:
        budget.check_cancelled()  # 超過預算被放棄了就不再畫
        try:
            total += render(a, generated_at, [rule_light(a)], out_dir / f"{a['iata'].lower()}.png")
            count += 1
        except Exception as e:  # 一個機場的資料怪，其他照畫
            log.warning("預覽圖 %s 畫不出來：%s", a.get("iata"), e, exc_info=True)
            errors.append(f"{a.get('iata')}:{e.__class__.__name__}")
    out: dict[str, object] = {"ok": not errors, "count": count, "bytes": total}
    if errors:
        out["error"] = ",".join(errors)[:200]
    return out


def required_chars(airports_path: Path, extra: Iterable[str] = ()) -> tuple[set[str], set[str]]:
    """子集要涵蓋的字：(ASCII 可印字元，其他字)。其他字是 `airports.json` 的機場名（zh-TW、en）與
    地區名（zh-TW）、`TEXTS`、`PUNCTUATION` 裡不是 ASCII 的字。"""
    data = json.loads(airports_path.read_text(encoding="utf-8"))
    strings = [
        *(a["name"][k] for a in data["airports"] for k in ("zh-TW", "en")),
        *(r["name"]["zh-TW"] for r in data["regions"]),
        *TEXTS,
        PUNCTUATION,
        *extra,
    ]
    latin = {chr(i) for i in range(0x20, 0x7F)}
    other = {ch for s in strings for ch in s if ord(ch) >= 128}
    return latin, other
