"""分享預覽圖（HD1、HD4、HD39）：每個機場一張 1200×630 的 PNG，發布到 GitHub Pages 的
`og/<iata>.png`（iata 小寫）。

規格是 Duado #374 定的、預設值 Shawn 2026-10-19 拍板（`docs/prompts/2026-10-19-HD1-og-image.md`）：
- 內容：左上 IATA 大字、其下機場名 zh-TW＋en；右上燈號色塊與一行小字；左下更新時間（機場當地時間）；
  右下品牌（HD39）：漩渦 LOGO＋「HongThai」字標＋「風颱」，下面 `duado.app/hongthai`。不放地圖
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
- 顏色、字型是 HongThai 網頁的品牌「風眼夜航」（HD39，Duado HW8）：深夜藍底、大圓角色塊、
  不用框線與陰影（低等級的 `lowEdge` 內框例外）。色碼只在 `COLORS`／`LEVEL_COLORS`，照 Duado
  `site/hongthai/theme.ts` 的 token，**兩邊要一起改**；LOGO 與字標照 `site/hongthai/brand.ts`
  （`MARK_*`、`WORDMARK_*`）
- 字型（`assets/fonts/`，都是 SIL OFL 1.1，只放子集）：ASCII 與數字用 Space Grotesk（IATA 大字
  Bold、其他 Medium），其他字用 Noto Sans TC（機場名與燈號字 Bold、其他 Regular）。Pillow 不會
  自動補字，所以逐字分段（`_runs`）、各段用自己的字型畫在同一條基線上。子集怎麼重做見
  `assets/fonts/README.md`
- PNG 轉成調色盤模式＋`optimize=True`，每張 ≤ 60 KB。調色盤是固定的
  （`_palette`）：上面幾個顏色本身，加上會相鄰的兩色之間的 `BLEND_STEPS` 個中間色（文字與圓角的
  反鋸齒），所以色塊與底色的顏色和規格完全一樣
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import cache
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageChops, ImageDraw, ImageFont

from . import budget
from .timeutil import SLOT_COUNT, parse_time

log = logging.getLogger("hongthai")

WIDTH, HEIGHT = 1200, 630
MARGIN = 64


def _blend(fg: str, bg: str, alpha: float) -> str:
    """`fg` 以不透明度 `alpha` 疊在 `bg` 上的實色（#RRGGBB）。"""
    a, b = _rgb(fg), _rgb(bg)
    return "#" + "".join(f"{round(y + (x - y) * alpha):02X}" for x, y in zip(a, b, strict=True))


def _rgb(hex_color: str) -> tuple[int, int, int]:
    return tuple(int(hex_color[i : i + 2], 16) for i in (1, 3, 5))  # type: ignore[return-value]


# 色碼來源：Duado `site/hongthai/theme.ts` 的 `htColors`（HW8「風眼夜航」；改色時兩邊一起改）
COLORS = {
    "night": "#0E1726",  # 底
    "text": "#E8EEF6",
    "textSoft": "#B8C4D6",
    "textMuted": "#9AA8BC",
    "eye": "#5CC8E8",  # 風眼青：LOGO
    "lowEdge": "#5A6E8F",  # 低等級色塊的內框
}
# 無資料與 AI error（資料不足）：網頁是 text 色不透明度 `NONE_ALPHA`（theme.ts），
# 這裡疊在底色上算成實色
NONE_ALPHA = 0.3
# 燈的底色與字色（theme.ts 的 `LEVEL_COLORS`；unknown 是網頁的 none）
LEVEL_COLORS: dict[str, tuple[str, str]] = {
    "low": ("#2F4263", COLORS["textSoft"]),
    "medium": ("#F2B84B", COLORS["night"]),
    "high": ("#FF6B5A", COLORS["night"]),
    "confirmed": ("#E8EEF6", COLORS["night"]),
    "unknown": (_blend(COLORS["text"], COLORS["night"], NONE_ALPHA), COLORS["text"]),
}
LOW_EDGE = 2  # 低等級內框的粗細（px）
LEVEL_TEXT = {
    "low": "低",
    "medium": "中",
    "high": "高",
    "confirmed": "已確認",
    "unknown": "資料不足",
}
RANKED = ("low", "medium", "high")
# 字標旁的「風颱」（Duado `brand.ts` 的 `BRAND_NATIVE`）
BRAND_NATIVE = "風颱"
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
    "duado.app/hongthai",
    "規則",
    "Claude",
    "Gemini",
    "沒看到明顯風險",
    *CAUSE_TEXT.values(),
    BRAND_NATIVE,
)
# 全形標點與幾個符號（子集要涵蓋，機場名或之後的字串可能用到）
PUNCTUATION = "，。、：；！？（）「」『』　・–—～／％"

FONT_FILES = {
    "latin": "SpaceGrotesk-Medium.subset.ttf",
    "latin-bold": "SpaceGrotesk-Bold.subset.ttf",  # IATA 大字
    "cjk": "NotoSansTC-Regular.subset.ttf",
    "cjk-bold": "NotoSansTC-Bold.subset.ttf",  # 機場名、燈號字
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
URL_SIZE = 24
MARK_SIZE = 52  # 漩渦 LOGO 的邊長
BRAND_GAP = 12  # LOGO、字標、「風颱」之間
NATIVE_SIZE = 24  # 「風颱」
LIGHTS_MAX_W = 620  # 三顆燈並排時佔的最大寬度
COL_GAP = 40  # 左側文字區與燈號區之間
# 時間軸（HD4）：格寬依可用空間算，介於 TL_CELL_MIN（不到就改整排橫跨）與 TL_CELL_MAX 之間
TL_CELL_H, TL_R, TL_GAP = 28, 8, 6
TL_CELL_MIN, TL_CELL_MAX = 24, 48
DATE_SIZE = 20
DATE_GAP = 8  # 日期標籤之間至少留的空
MAX_DATES = 6
BLEND_STEPS = 7
SS = 4  # 色塊、LOGO、字標先畫成 SS 倍大的遮罩再縮小（反鋸齒）

# 品牌（HD39）：Duado `site/hongthai/brand.ts`，改名或改圖時兩邊一起改。
# 漩渦：中心圓 r=7 與兩條三次貝茲弧線（viewBox 0 0 48 48，線寬 3、圓頭）
MARK_VIEWBOX = 48
MARK_CIRCLE = (24, 24, 7)
MARK_ARCS = (
    ((24, 17), (33, 17), (38, 11), (42, 5)),
    ((24, 31), (15, 31), (10, 37), (6, 43)),
)
MARK_STROKE = 3
# 字標「HongThai」：Space Grotesk Bold 的外框（brand.ts 的 `WORDMARK_PATH`，含字距調整；
# 座標是字體單位，y 向下、左上角 0,0；基線在 y=714）。高度是 LOGO 的 `WORDMARK_SCALE` 倍
# （整個 viewBox 的高，含 g 的下伸部）
WORDMARK_VIEWBOX = (4452, 914)
WORDMARK_BASELINE = 714
WORDMARK_SCALE = 0.6
WORDMARK_PATH = "".join(
    (
        "M0 714V14H132V303H392V14H524V714H392V423H132V714Z",
        "M896 728Q822 728 763 698Q704 668 670 611Q636 554 636 474V458Q636 378 670 321"
        "Q704 264 763 234Q822 204 896 204Q970 204 1029 234Q1088 264 1122 321"
        "Q1156 378 1156 458V474Q1156 554 1122 611Q1088 668 1029 698Q970 728 896 728Z",
        "M896 616Q954 616 992 578Q1030 541 1030 471V461Q1030 391 992 354Q955 316 896 316"
        "Q838 316 800 354Q762 391 762 461V471Q762 541 800 578Q838 616 896 616Z",
        "M1272 714V218H1396V283H1414Q1426 257 1459 234Q1492 210 1559 210Q1617 210 1660 236"
        "Q1704 263 1728 310Q1752 356 1752 418V714H1626V428Q1626 372 1598 344"
        "Q1571 316 1520 316Q1462 316 1430 354Q1398 393 1398 462V714Z",
        "M1864 468V452Q1864 374 1895 318Q1926 263 1978 234Q2029 204 2090 204"
        "Q2158 204 2193 228Q2228 252 2244 278H2262V218H2386V802Q2386 853 2356 884"
        "Q2326 914 2276 914H1944V804H2232Q2260 804 2260 774V645H2242Q2232 661 2214 678"
        "Q2196 694 2166 705Q2136 716 2090 716Q2029 716 1978 686Q1926 657 1895 602"
        "Q1864 546 1864 468Z",
        "M2126 606Q2184 606 2223 569Q2262 532 2262 465V455Q2262 387 2224 350"
        "Q2185 314 2126 314Q2068 314 2029 350Q1990 387 1990 455V465Q1990 532 2029 569"
        "Q2068 606 2126 606Z",
        "M2684 714V134H2480V14H3020V134H2816V714Z",
        "M3114 714V14H3240V279H3258Q3266 263 3283 247Q3300 231 3328 220Q3357 210 3401 210"
        "Q3459 210 3502 236Q3546 263 3570 310Q3594 356 3594 418V714H3468V428"
        "Q3468 372 3440 344Q3413 316 3362 316Q3304 316 3272 354Q3240 393 3240 462V714Z",
        "M3884 728Q3831 728 3789 710Q3747 691 3722 656Q3698 620 3698 569Q3698 518 3722 484"
        "Q3747 449 3790 432Q3834 414 3890 414H4026V386Q4026 351 4004 328Q3982 306 3934 306"
        "Q3887 306 3864 328Q3841 349 3834 383L3718 344Q3730 306 3756 274Q3783 243 3828 224"
        "Q3872 204 3936 204Q4034 204 4091 253Q4148 302 4148 395V580Q4148 610 4176 610H4216"
        "V714H4132Q4095 714 4071 696Q4047 678 4047 648V647H4028Q4024 659 4010 678"
        "Q3996 698 3966 713Q3936 728 3884 728Z",
        "M3906 626Q3959 626 3992 596Q4026 567 4026 518V508H3899Q3864 508 3844 523"
        "Q3824 538 3824 565Q3824 592 3845 609Q3866 626 3906 626Z",
        "M4308 714V218H4434V714Z",
        "M4371 160Q4337 160 4314 138Q4290 116 4290 80Q4290 44 4314 22Q4337 0 4371 0"
        "Q4406 0 4429 22Q4452 44 4452 80Q4452 116 4429 138Q4406 160 4371 160Z",
    )
)
CURVE_STEPS = 12  # 貝茲曲線攤平成幾段


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
    mark: Box | None = None  # 漩渦 LOGO
    wordmark: Box | None = None  # 字標「HongThai」


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


def font_key(ch: str, bold: bool = False) -> str:
    """ASCII（含數字）→ Space Grotesk；其他字 → Noto Sans TC。`bold` 用 Bold 那套。"""
    k = "latin" if ord(ch) < 128 else "cjk"
    return f"{k}-bold" if bold else k


def _runs(text: str, bold: bool = False) -> list[tuple[str, str]]:
    """逐字分段：[(字型, 這段文字)]。"""
    out: list[tuple[str, str]] = []
    for ch in text:
        k = font_key(ch, bold)
        if out and out[-1][0] == k:
            out[-1] = (k, out[-1][1] + ch)
        else:
            out.append((k, ch))
    return out


class _Canvas:
    def __init__(self, root: Path):
        self.root = root
        self.img = Image.new("RGB", (WIDTH, HEIGHT), COLORS["night"])
        self.draw = ImageDraw.Draw(self.img)

    def width(self, text: str, size: int, bold: bool = False) -> float:
        return sum(_font(k, size, self.root).getlength(s) for k, s in _runs(text, bold))

    def cap(self, size: int, bold: bool = False) -> int:
        """Space Grotesk 大寫字母的高度（基線到頂）。"""
        return -_font(font_key("H", bold), size, self.root).getbbox("H", anchor="ls")[1]

    def fit(
        self, text: str, size: int, max_w: float, min_size: int = 12, bold: bool = False
    ) -> int:
        while size > min_size and self.width(text, size, bold) > max_w:
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
        bold: bool = False,
    ) -> Box:
        """畫一行（各段用自己的字型、對齊同一條基線）。`align`：left／right／center，x 是那一側。
        回傳實際畫到的範圍。"""
        w = self.width(text, size, bold)
        x = {"left": x, "right": x - w, "center": x - w / 2}[align]
        box: Box | None = None
        for k, s in _runs(text, bold):
            f = _font(k, size, self.root)
            self.draw.text((x, baseline), s, font=f, fill=fill, anchor="ls")
            box = _union(box, self.draw.textbbox((x, baseline), s, font=f, anchor="ls"))
            x += f.getlength(s)
        return box or (x, baseline, x, baseline)

    def paint(self, x: int, y: int, mask: Image.Image, fill: str) -> None:
        """把 `SS` 倍大的遮罩縮小（邊緣才平滑），用 `fill` 色貼在 (x, y)。"""
        w, h = mask.width // SS, mask.height // SS
        small = mask.resize((w, h), Image.Resampling.LANCZOS)
        self.img.paste(Image.new("RGB", (w, h), fill), (x, y), small)

    def block(
        self,
        x: int,
        y: int,
        w: int,
        h: int,
        fill: str,
        radius: int = BLOCK_R,
        edge: str | None = None,
    ) -> Box:
        """圓角色塊；`edge` 有給時外圈 `LOW_EDGE` px 是這個顏色（低等級的內框）。"""

        def rounded(inset: int) -> Image.Image:
            mask = Image.new("L", (w * SS, h * SS), 0)
            i = inset * SS
            ImageDraw.Draw(mask).rounded_rectangle(
                (i, i, w * SS - 1 - i, h * SS - 1 - i), radius=(radius - inset) * SS, fill=255
            )
            return mask

        if edge is None:
            self.paint(x, y, rounded(0), fill)
        else:
            self.paint(x, y, rounded(0), edge)
            self.paint(x, y, rounded(LOW_EDGE), fill)
        return (x, y, x + w, y + h)

    def level_block(self, x: int, y: int, w: int, h: int, level: str, radius: int) -> Box:
        """等級色塊（燈號、時間軸一格）：低等級加 `lowEdge` 內框，深底上才看得出來。"""
        bg = LEVEL_COLORS.get(level, LEVEL_COLORS["unknown"])[0]
        edge = COLORS["lowEdge"] if level == "low" else None
        return self.block(x, y, w, h, bg, radius, edge)


def _union(a: Box | None, b: Box) -> Box:
    if a is None:
        return tuple(b)  # type: ignore[return-value]
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


@cache
def _palette() -> Image.Image:
    """固定調色盤：`COLORS`、燈的底色與字色，以及會相鄰的兩色之間的中間色（反鋸齒）：
    底色和每個顏色（文字、LOGO、色塊）、燈的底色和字色、低等級的內框和底色與色塊。"""
    bg = COLORS["night"]
    pairs = {(bg, c) for k, c in COLORS.items() if k != "night"}
    pairs |= {(bg, b) for b, _ in LEVEL_COLORS.values()}
    pairs |= {(b, f) for b, f in LEVEL_COLORS.values()}
    pairs.add((COLORS["lowEdge"], LEVEL_COLORS["low"][0]))
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


Point = tuple[float, float]


def _bezier(pts: tuple[Point, ...], steps: int = CURVE_STEPS) -> list[Point]:
    """二次或三次貝茲曲線攤平成折線（不含起點）。"""
    out: list[Point] = []
    for i in range(1, steps + 1):
        t = i / steps
        ps = list(pts)
        while len(ps) > 1:  # de Casteljau
            ps = [
                (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
                for a, b in zip(ps, ps[1:], strict=False)
            ]
        out.append(ps[0])
    return out


def path_polygons(d: str) -> list[list[Point]]:
    """SVG path 攤平成多邊形，一個子路徑一個。只認絕對座標的 M、L、H、V、Q、C、Z
    （字標用到的就這些）。"""
    tokens = re.findall(r"[MLHVQCZ]|-?\d+(?:\.\d+)?", d)
    polys: list[list[Point]] = []
    cur: list[Point] = []
    i, cmd = 0, ""
    while i < len(tokens):
        if tokens[i].isalpha():
            cmd = tokens[i]
            i += 1
            if cmd == "Z":
                polys.append(cur)
                cur = []
                continue
        nums = {"M": 2, "L": 2, "H": 1, "V": 1, "Q": 4, "C": 6}[cmd]
        v = [float(t) for t in tokens[i : i + nums]]
        i += nums
        if cmd == "M":
            if cur:
                polys.append(cur)
            cur = [(v[0], v[1])]
        elif cmd == "L":
            cur.append((v[0], v[1]))
        elif cmd == "H":
            cur.append((v[0], cur[-1][1]))
        elif cmd == "V":
            cur.append((cur[-1][0], v[0]))
        else:
            ctrl = tuple((v[j], v[j + 1]) for j in range(0, nums, 2))
            cur.extend(_bezier((cur[-1], *ctrl)))
    if cur:
        polys.append(cur)
    return polys


def _mark(c: _Canvas, x: int, y: int, size: int) -> Box:
    """漩渦 LOGO（`eye` 色），左上角 (x, y)、邊長 `size`。"""
    k = size * SS / MARK_VIEWBOX
    sw = MARK_STROKE * k
    mask = Image.new("L", (size * SS, size * SS), 0)
    d = ImageDraw.Draw(mask)
    cx, cy, r = (v * k for v in MARK_CIRCLE)
    d.ellipse(
        (cx - r - sw / 2, cy - r - sw / 2, cx + r + sw / 2, cy + r + sw / 2),
        outline=255,
        width=round(sw),
    )
    for arc in MARK_ARCS:
        pts = [(px * k, py * k) for px, py in (arc[0], *_bezier(arc, 24))]
        d.line(pts, fill=255, width=round(sw), joint="curve")
        for px, py in (pts[0], pts[-1]):  # 圓頭
            d.ellipse((px - sw / 2, py - sw / 2, px + sw / 2, py + sw / 2), fill=255)
    c.paint(x, y, mask, COLORS["eye"])
    return (x, y, x + size, y + size)


def _wordmark(c: _Canvas, x: int, y: int, height: int) -> Box:
    """字標「HongThai」（`text` 色），左上角 (x, y)、高 `height`（整個 viewBox 的高）。
    子路徑以奇偶規則填（o、g、a 的內圈是洞）。"""
    vw, vh = WORDMARK_VIEWBOX
    k = height * SS / vh
    w = round(vw * height / vh)
    mask = Image.new("L", (w * SS, height * SS), 0)
    for poly in path_polygons(WORDMARK_PATH):
        one = Image.new("L", mask.size, 0)
        ImageDraw.Draw(one).polygon([(px * k, py * k) for px, py in poly], fill=255)
        mask = ImageChops.difference(mask, one)
    c.paint(x, y, mask, COLORS["text"])
    return (x, y, x + w, y + height)


def _brand(c: _Canvas, layout: Layout, baseline: float) -> None:
    """右下品牌：漩渦 LOGO＋字標＋「風颱」靠右，字標與「風颱」的基線在 `baseline`，
    LOGO 和字標垂直置中（同網頁 `renderLogo`）。"""
    wm_h = round(MARK_SIZE * WORDMARK_SCALE)
    wm_w = round(WORDMARK_VIEWBOX[0] * wm_h / WORDMARK_VIEWBOX[1])
    native_w = c.width(BRAND_NATIVE, NATIVE_SIZE)
    right = WIDTH - MARGIN
    c.text(right, baseline, BRAND_NATIVE, NATIVE_SIZE, COLORS["textMuted"], "right")
    wm_x = round(right - native_w - BRAND_GAP - wm_w)
    wm_y = round(baseline - WORDMARK_BASELINE * wm_h / WORDMARK_VIEWBOX[1])
    layout.wordmark = _wordmark(c, wm_x, wm_y, wm_h)
    mark_x = wm_x - BRAND_GAP - MARK_SIZE
    mark_y = round(wm_y + wm_h / 2 - MARK_SIZE / 2)
    layout.mark = _mark(c, mark_x, mark_y, MARK_SIZE)


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
        fg = LEVEL_COLORS.get(lt.level, LEVEL_COLORS["unknown"])[1]
        if lt.label:
            box = _union(
                box,
                c.text(
                    x + w / 2,
                    MARGIN + LABEL_SIZE * 0.85,
                    lt.label,
                    LABEL_SIZE,
                    COLORS["textSoft"],
                    "center",
                ),
            )
        box = _union(box, c.level_block(x, top, w, BLOCK_H, lt.level, BLOCK_R))
        word = LEVEL_TEXT.get(lt.level, LEVEL_TEXT["unknown"])
        size = c.fit(word, BLOCK_TEXT_SIZE, w - 40, bold=True)
        # 漢字大致是 em 方塊，中心在基線上方約 0.38 em
        c.text(x + w / 2, top + BLOCK_H / 2 + size * 0.38, word, size, fg, "center", bold=True)
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
    """時間軸一格的底色：同燈號的底色；沒有等級或等級不認得當 `unknown`（低等級另有內框）。"""
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
        level = s.get("level") if s.get("level") in LEVEL_COLORS else "unknown"
        layout.cells.append(c.level_block(x + i * (w + TL_GAP), top, w, TL_CELL_H, level, TL_R))
    # 標籤對齊那格的左邊；和前一個太近就往右推、超出時間軸右邊就往左收
    baseline = top + TL_CELL_H + 10 + c.cap(DATE_SIZE)
    prev_right = float("-inf")
    for i, text in day_labels(slots, tz):
        tw = c.width(text, DATE_SIZE)
        lx = min(max(x + i * (w + TL_GAP), prev_right + DATE_GAP), right - tw)
        b = c.text(lx, baseline, text, DATE_SIZE, COLORS["textMuted"])
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
    iata_size = c.fit(iata, IATA_SIZE, col_w, 80, bold=True)
    iata_base = MARGIN + c.cap(iata_size, bold=True)
    c.text(MARGIN, iata_base, iata, iata_size, ink, bold=True)
    name = airport["name"]
    zh_base = iata_base + 40 + NAME_SIZE
    zh_size = c.fit(name["zh-TW"], NAME_SIZE, col_w, bold=True)
    c.text(MARGIN, zh_base, name["zh-TW"], zh_size, ink, bold=True)
    en_size = c.fit(name["en"], NAME_EN_SIZE, col_w)
    en_box = c.text(MARGIN, zh_base + 54, name["en"], en_size, COLORS["textSoft"])

    bottom = HEIGHT - MARGIN
    updated_box = c.text(
        MARGIN, bottom, updated_text(generated_at, airport["tz"]), UPDATED_SIZE, COLORS["textMuted"]
    )
    c.text(WIDTH - MARGIN, bottom, "duado.app/hongthai", URL_SIZE, COLORS["textMuted"], "right")
    _brand(c, layout, bottom - URL_SIZE - 22)

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
