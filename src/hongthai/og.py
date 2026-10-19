"""分享預覽圖（HD1、HD4）：每個機場一張 1200×630 的 PNG，發布到 GitHub Pages 的 `og/<iata>.png`
（iata 小寫）。

規格是 Duado #374 定的、預設值 Shawn 2026-10-19 拍板（`docs/prompts/2026-10-19-HD1-og-image.md`）：
- 內容：左上 IATA 大字、其下機場名 zh-TW＋en；右上燈號色塊與一行小字；左下更新時間（機場當地時間）；
  右下「HongThai　機場停飛風險」與 `duado.app/hongthai`。不放 logo、不放地圖
- 時間軸（HD4，`_timeline`）：機場名下方、更新時間上方，未來 5 天 20 格照 `slots` 的順序各一個小圓角
  色塊（顏色同燈號，`LEVEL_COLORS`；沒有等級當 `unknown`），色塊裡不寫字。寬度和左側文字區對齊；
  三顆燈時左側太窄（一格不到 `TL_CELL_MIN`），改放到燈號下方整排橫跨。每天第一格下方標當地日期
  `M/D`（`day_labels`：一格的日期以 `from` 換成當地時間為準，第一格一定標，之後當地日期變了就標，
  最多 6 個）
- 燈號（`rule_light`）：這個機場未來 5 天（20 格）裡最高的等級，小字寫第一個達到那個等級的格的當地
  日期時段（「最高：高　10/23 14–20 時」），那格有 `causes` 時後面接主因（`causes[0]`，HD8：
  「最高：高　10/23 08–14 時・強風」，`CAUSE_TEXT`）；全部低寫「未來 5 天：低」。有 `confirmed`
  的格（視為高）時色塊寫「已確認」、小字「已確認停飛　<第一個已確認的格>」；全部 `unknown`
  寫「資料不足」；有的格 `unknown`、有的有等級時只看有等級的
- 三顆燈（HD5，`lights_for`）：機場的 `ai` 兩顆都是 `skipped` 或 `error`（或沒有 `ai`）時
  只畫一顆規則燈（`label=None` 不畫標籤）；任一顆 `ok` 時畫三顆：「規則」（同上的等級與小字）、
  「Claude」、「Gemini」（AI 的等級；短評不畫、小字留空；`error` 用 `unknown` 色塊寫「資料不足」、
  `skipped` 用 low），色塊寬度自動排、時間軸移到燈號下方整排
- 顏色、字型都是 Duado 晨光風格：淺底、大圓角色塊、不用框線與陰影、不做深色版
  （`COLORS`、`LEVEL_COLORS`）
- 字型（`assets/fonts/`，都是 SIL OFL 1.1，只放子集）：ASCII 與數字用 Fraunces（SOFT 100、
  wght 600 的靜態檔；IATA 大字用 opsz 144 那個、其他小字用 opsz 9 那個），其他字用芫荽，
  芫荽沒有的字才用 Noto Sans TC。Pillow 不會自動補字，所以逐字分段（`_runs`）、各段用自己的字型
  畫在同一條基線上。子集怎麼重做見 `assets/fonts/README.md`
- PNG 轉成調色盤模式＋`optimize=True`，每張約 15–20 KB（目標 ≤ 60 KB）。調色盤是固定的
  （`_palette`）：上面幾個顏色本身，加上會相鄰的兩色之間的 `BLEND_STEPS` 個中間色（文字與圓角的
  反鋸齒），所以色塊與底色的顏色和規格完全一樣
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import cache
from pathlib import Path
from zoneinfo import ZoneInfo

from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont

from . import budget
from .timeutil import SLOT_COUNT, parse_time

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
# 主因（`slots[].causes[0]`，HD8）接在燈號小字後面
CAUSE_TEXT = {"wind": "強風", "rain": "大雨", "snow": "大雪", "fog": "濃霧"}

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
    *CAUSE_TEXT.values(),
)
# 全形標點與幾個符號（子集要涵蓋，機場名或之後的字串可能用到）
PUNCTUATION = "，。、：；！？（）「」『』　・–—～／％"

FONT_FILES = {
    "latin": "Fraunces-Soft600.subset.ttf",
    "display": "Fraunces-Soft600-Display.subset.ttf",  # opsz 144，只給 IATA 大字用
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
COL_GAP = 40  # 左側文字區與燈號區之間
# 時間軸（HD4）：格寬依可用空間算，介於 TL_CELL_MIN（不到就改整排橫跨）與 TL_CELL_MAX 之間
TL_CELL_H, TL_R, TL_GAP = 28, 8, 6
TL_CELL_MIN, TL_CELL_MAX = 24, 48
DATE_SIZE = 20
DATE_GAP = 8  # 日期標籤之間至少留的空
MAX_DATES = 6
BLEND_STEPS = 7


Box = tuple[float, float, float, float]  # (左, 上, 右, 下)


@dataclass(frozen=True)
class Light:
    """一顆燈。`level`：low／medium／high／confirmed／unknown；`label` 是 None 時不畫標籤。"""

    label: str | None
    level: str
    note: str


@dataclass
class Layout:
    """一張圖各區實際畫到的範圍（測試檢查版面用）。"""

    lights: Box  # 燈號區（標籤、色塊、小字）
    timeline: Box | None = None  # 時間軸（色塊與日期標籤）；沒有格時 None
    cells: list[Box] = field(default_factory=list)  # 時間軸每一格
    dates: list[tuple[int, str, Box]] = field(default_factory=list)  # (第幾格, "M/D", 範圍)


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


def _runs(text: str, root: Path, latin: str = "latin") -> list[tuple[str, str]]:
    """逐字分段；ASCII 那幾段用 `latin` 這個字型（IATA 大字傳 `"display"`）。"""
    out: list[tuple[str, str]] = []
    for ch in text:
        k = font_key(ch, root)
        k = latin if k == "latin" else k
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

    def width(self, text: str, size: int, latin: str = "latin") -> float:
        return sum(_font(k, size, self.root).getlength(s) for k, s in _runs(text, self.root, latin))

    def cap(self, size: int, latin: str = "latin") -> int:
        """Fraunces 大寫字母的高度（基線到頂）。"""
        return -_font(latin, size, self.root).getbbox("H", anchor="ls")[1]

    def fit(
        self, text: str, size: int, max_w: float, min_size: int = 12, latin: str = "latin"
    ) -> int:
        while size > min_size and self.width(text, size, latin) > max_w:
            size -= 1
        return size

    def text(
        self,
        x: float,
        baseline: float,
        text: str,
        size: int,
        fill: str,
        align: str = "left",
        latin: str = "latin",
    ) -> Box:
        """畫一行（各段用自己的字型、對齊同一條基線）。`align`：left／right／center，x 是那一側。
        回傳實際畫到的範圍。"""
        w = self.width(text, size, latin)
        x = {"left": x, "right": x - w, "center": x - w / 2}[align]
        box: Box | None = None
        for k, s in _runs(text, self.root, latin):
            f = _font(k, size, self.root)
            self.draw.text((x, baseline), s, font=f, fill=fill, anchor="ls")
            box = _union(box, self.draw.textbbox((x, baseline), s, font=f, anchor="ls"))
            x += f.getlength(s)
        return box or (x, baseline, x, baseline)

    def block(self, x: int, y: int, w: int, h: int, fill: str, radius: int = BLOCK_R) -> Box:
        """圓角色塊；四倍大畫遮罩再縮小，邊緣才平滑。"""
        s = 4
        mask = Image.new("L", (w * s, h * s), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            (0, 0, w * s - 1, h * s - 1), radius=radius * s, fill=255
        )
        mask = mask.resize((w, h), Image.Resampling.LANCZOS)
        self.img.paste(Image.new("RGB", (w, h), fill), (x, y), mask)
        return (x, y, x + w, y + h)


def _union(a: Box | None, b: Box) -> Box:
    if a is None:
        return tuple(b)  # type: ignore[return-value]
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


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


def _lights(c: _Canvas, lights: list[Light]) -> tuple[int, Box]:
    """右上的燈號（並排、靠右）；回傳（色塊最左邊的 x，燈號區含標籤與小字實際畫到的範圍）。"""
    n = len(lights)
    right = WIDTH - MARGIN
    w = min(BLOCK_W, int((LIGHTS_MAX_W - BLOCK_GAP * (n - 1)) / n))
    left = right - n * w - (n - 1) * BLOCK_GAP
    labelled = any(lt.label for lt in lights)
    top = MARGIN + (LABEL_SIZE + 14 if labelled else 0)
    note_base = top + BLOCK_H + NOTE_SIZE + 16
    box: Box | None = None
    for i, lt in enumerate(lights):
        x = left + i * (w + BLOCK_GAP)
        bg, fg = LEVEL_COLORS.get(lt.level, LEVEL_COLORS["unknown"])
        if lt.label:
            box = _union(
                box,
                c.text(
                    x + w / 2,
                    MARGIN + LABEL_SIZE * 0.85,
                    lt.label,
                    LABEL_SIZE,
                    COLORS["text"],
                    "center",
                ),
            )
        box = _union(box, c.block(x, top, w, BLOCK_H, bg))
        word = LEVEL_TEXT.get(lt.level, LEVEL_TEXT["unknown"])
        size = c.fit(word, BLOCK_TEXT_SIZE, w - 40)
        # 漢字大致是 em 方塊，中心在基線上方約 0.38 em
        c.text(x + w / 2, top + BLOCK_H / 2 + size * 0.38, word, size, fg, "center")
        if n == 1:  # 一顆燈時小字靠右、可以比色塊寬
            size = c.fit(lt.note, NOTE_SIZE, right - 560)
            box = _union(box, c.text(right, note_base, lt.note, size, COLORS["text"], "right"))
        else:  # 三顆燈時小字在各自色塊下置中，太長就在全形空白處換行
            size = NOTE_SIZE - 4
            lines = [lt.note]
            if c.fit(lt.note, size, w) < 20:
                lines = lt.note.split("　")
            for j, line in enumerate(lines):
                box = _union(
                    box,
                    c.text(
                        x + w / 2,
                        note_base + j * (size + 10),
                        line,
                        c.fit(line, size, w),
                        COLORS["text"],
                        "center",
                    ),
                )
    assert box is not None
    return left, box


def slot_color(slot: dict) -> str:
    """時間軸一格的顏色：同燈號的底色；沒有等級或等級不認得當 `unknown`。"""
    return LEVEL_COLORS.get(slot.get("level"), LEVEL_COLORS["unknown"])[0]  # type: ignore[arg-type]


def day_labels(slots: list[dict], tz: str) -> list[tuple[int, str]]:
    """時間軸要標日期的格：[(第幾格, "M/D")]。一格的日期是它的 `from` 換成當地時間的日期；
    第一格一定標，之後當地日期變了就標，最多 `MAX_DATES` 個。"""
    z = ZoneInfo(tz)
    out: list[tuple[int, str]] = []
    prev = None
    for i, s in enumerate(slots):
        d = parse_time(s["from"]).astimezone(z).date()
        if d != prev:
            out.append((i, f"{d.month}/{d.day}"))
            prev = d
    return out[:MAX_DATES]


def _timeline(
    c: _Canvas, layout: Layout, slots: list[dict], tz: str, x: int, top: int, avail: int
) -> None:
    """畫時間軸（左上角 `x`、`top`，寬度不超過 `avail`），範圍記到 `layout`。"""
    w = min(TL_CELL_MAX, (avail - (SLOT_COUNT - 1) * TL_GAP) // SLOT_COUNT)
    right = x + SLOT_COUNT * w + (SLOT_COUNT - 1) * TL_GAP
    box: Box = (x, top, right, top + TL_CELL_H)
    for i, s in enumerate(slots):
        layout.cells.append(c.block(x + i * (w + TL_GAP), top, w, TL_CELL_H, slot_color(s), TL_R))
    # 標籤對齊那格的左邊；和前一個太近就往右推、超出時間軸右邊就往左收
    baseline = top + TL_CELL_H + 10 + c.cap(DATE_SIZE)
    prev_right = float("-inf")
    for i, text in day_labels(slots, tz):
        tw = c.width(text, DATE_SIZE)
        lx = min(max(x + i * (w + TL_GAP), prev_right + DATE_GAP), right - tw)
        b = c.text(lx, baseline, text, DATE_SIZE, COLORS["text"])
        prev_right = b[2]
        layout.dates.append((i, text, b))
        box = _union(box, b)
    layout.timeline = box


def updated_text(generated_at: str, tz: str) -> str:
    t = parse_time(generated_at).astimezone(ZoneInfo(tz))
    return f"更新 {t:%Y-%m-%d %H:%M}（當地時間）"


def _draw(airport: dict, generated_at: str, lights: list[Light]) -> tuple[_Canvas, Layout]:
    """畫一張預覽圖；回傳（畫布，各區實際畫到的範圍）。"""
    if not lights:
        raise ValueError("至少要一顆燈")
    c = _Canvas(font_dir())
    ink = COLORS["text"]
    lights_left, lights_box = _lights(c, lights)
    layout = Layout(lights_box)
    col_w = lights_left - COL_GAP - MARGIN

    iata = airport["iata"]
    iata_size = c.fit(iata, IATA_SIZE, col_w, 80, latin="display")
    iata_base = MARGIN + c.cap(iata_size, "display")
    c.text(MARGIN, iata_base, iata, iata_size, ink, latin="display")
    name = airport["name"]
    zh_base = iata_base + 40 + NAME_SIZE
    c.text(MARGIN, zh_base, name["zh-TW"], c.fit(name["zh-TW"], NAME_SIZE, col_w), ink)
    en_box = c.text(MARGIN, zh_base + 54, name["en"], c.fit(name["en"], NAME_EN_SIZE, col_w), ink)

    bottom = HEIGHT - MARGIN
    updated_box = c.text(
        MARGIN, bottom, updated_text(generated_at, airport["tz"]), UPDATED_SIZE, ink
    )
    c.text(WIDTH - MARGIN, bottom, "duado.app/hongthai", URL_SIZE, ink, "right")
    c.text(
        WIDTH - MARGIN, bottom - URL_SIZE - 22, "HongThai　機場停飛風險", BRAND_SIZE, ink, "right"
    )

    slots = [s for s in airport.get("slots") or [] if isinstance(s, dict)][:SLOT_COUNT]
    if slots:
        # 左側文字區夠寬就和它對齊，不然（三顆燈）放到燈號下方整排橫跨
        avail = col_w
        if (avail - (SLOT_COUNT - 1) * TL_GAP) // SLOT_COUNT < TL_CELL_MIN:
            avail = WIDTH - 2 * MARGIN
        # 機場名與更新時間之間置中；整排橫跨時也要在燈號下方
        group_h = TL_CELL_H + 10 + c.cap(DATE_SIZE)
        top = round((en_box[3] + updated_box[1] - group_h) / 2)
        if avail > col_w:
            top = max(top, round(lights_box[3]) + 24)
        _timeline(c, layout, slots, airport["tz"], MARGIN, top, avail)
    return c, layout


def render(airport: dict, generated_at: str, lights: list[Light], out_path: Path) -> int:
    """畫一張預覽圖寫到 `out_path`（純畫圖，不讀網路）；回傳檔案大小（bytes）。

    `airport` 是 `latest.json` 的 `airports[]` 一筆（用 `iata`、`tz`、`name`、`slots`）。
    """
    c, _ = _draw(airport, generated_at, lights)
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
    causes = first.get("causes") if isinstance(first.get("causes"), list) else []
    cause = CAUSE_TEXT.get(causes[0], "") if causes else ""
    suffix = f"・{cause}" if cause else ""
    return Light(label, top, f"最高：{LEVEL_TEXT[top]}　{slot_text(first, tz)}{suffix}")


AI_LABELS = {"claude": "Claude", "gemini": "Gemini"}


def ai_light(light: object, label: str) -> Light:
    """一顆 AI 燈：`ok` 用模型的等級、`skipped` 用 low、其他（`error`、格式怪）用 unknown。"""
    d = light if isinstance(light, dict) else {}
    if d.get("status") == "ok" and d.get("level") in RANKED:
        return Light(label, d["level"], "")
    if d.get("status") == "skipped":
        return Light(label, "low", "")
    return Light(label, "unknown", "")


def lights_for(airport: dict) -> list[Light]:
    """一顆規則燈；`ai` 任一顆是 `ok` 時三顆（規則、Claude、Gemini）。"""
    ai = airport.get("ai") if isinstance(airport.get("ai"), dict) else {}
    if not any(isinstance(ai.get(k), dict) and ai[k].get("status") == "ok" for k in AI_LABELS):
        return [rule_light(airport)]
    return [rule_light(airport, "規則"), *(ai_light(ai.get(k), v) for k, v in AI_LABELS.items())]


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
            total += render(a, generated_at, lights_for(a), out_dir / f"{a['iata'].lower()}.png")
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
