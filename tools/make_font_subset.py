"""重做分享預覽圖用的字型子集（`assets/fonts/`）。

在 repo 根目錄跑 `python tools/make_font_subset.py`。

完整字型下載到暫存目錄（不進 repo），子集寫到 `assets/fonts/`（HD39 起是 HongThai 品牌「風眼夜航」
的字）：
- Space Grotesk（ASCII 可印字元 95 個）：可變字型用 `varLib.instancer` 固定 wght，產兩個靜態檔：
  小字用的 Medium（500）、IATA 大字用的 Bold（700）
- Noto Sans TC（`hongthai.og.required_chars` 的非 ASCII 字）：可變字型固定 wght，產兩個靜態檔：
  小字用的 Regular（400）、機場名與燈號字用的 Bold（700）。Noto 沒有的字會報錯（回傳 1）

加了機場、改了 `og.TEXTS` 之後要重跑（`tests/test_og.py` 會檢查涵蓋，沒重跑 CI 會紅）。
換字型版本時改下面的 commit，跑完把 `assets/fonts/README.md` 的版本與大小一起更新。
"""

from __future__ import annotations

import sys
import tempfile
import urllib.request
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from hongthai import og  # noqa: E402

OUT = ROOT / "assets" / "fonts"
GOOGLE_FONTS = (
    "https://raw.githubusercontent.com/google/fonts/47d54ca1ebb14fd864695f1d39dc734f39017c33"
)
SOURCES = {
    "spacegrotesk": f"{GOOGLE_FONTS}/ofl/spacegrotesk/SpaceGrotesk%5Bwght%5D.ttf",
    "noto": f"{GOOGLE_FONTS}/ofl/notosanstc/NotoSansTC%5Bwght%5D.ttf",
}
# 每個子集：(來源, 固定的 wght)
WEIGHTS = {
    "latin": ("spacegrotesk", 500),
    "latin-bold": ("spacegrotesk", 700),
    "cjk": ("noto", 400),
    "cjk-bold": ("noto", 700),
}


def download(url: str, dest: Path) -> Path:
    print(f"下載 {url}")
    with urllib.request.urlopen(url, timeout=120) as r:
        dest.write_bytes(r.read())
    return dest


def make_subset(font: TTFont, chars: set[str], out: Path, pin: dict) -> None:
    """取子集，再用 `pin` 固定各軸變成靜態檔，寫到 `out`。"""
    opts = subset.Options()
    opts.name_IDs = ["*"]  # 名稱表（含版本、授權）全部留著
    opts.name_languages = ["*"]
    opts.hinting = False  # Pillow（FreeType）畫圖不用 TrueType hinting
    opts.notdef_outline = True
    s = subset.Subsetter(opts)
    s.populate(unicodes=sorted(ord(c) for c in chars))
    s.subset(font)
    # 先取子集再固定（整套 CJK 可變字型直接 instancer 很慢）
    font = instancer.instantiateVariableFont(font, pin, updateFontNames=True)
    font.save(out)
    print(f"{out.relative_to(ROOT)}：{len(font.getBestCmap())} 字，{out.stat().st_size:,} bytes")


def main() -> int:
    latin, other = og.required_chars(ROOT / "airports.json")
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="hongthai-fonts-") as tmp:
        files = {k: download(u, Path(tmp) / f"{k}.ttf") for k, u in SOURCES.items()}
        noto_cmap = TTFont(files["noto"], lazy=True).getBestCmap()
        lost = {c for c in other if ord(c) not in noto_cmap}
        if lost:
            print(f"Noto Sans TC 沒有：{''.join(sorted(lost))}")
            return 1
        for key, (src, wght) in WEIGHTS.items():
            chars = latin if src == "spacegrotesk" else other
            make_subset(TTFont(files[src]), chars, OUT / og.FONT_FILES[key], {"wght": wght})
    return 0


if __name__ == "__main__":
    sys.exit(main())
