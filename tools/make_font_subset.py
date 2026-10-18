"""重做分享預覽圖用的字型子集（`assets/fonts/`）。

在 repo 根目錄跑 `python tools/make_font_subset.py`。

完整字型下載到暫存目錄（不進 repo），子集寫到 `assets/fonts/`：
- Fraunces（ASCII 可印字元＋`EXTRA_LATIN`）：可變字型用 `varLib.instancer` 固定 SOFT 100、wght 600，
  變成靜態檔再取子集。產兩個：小字用的 opsz、WONK 留預設（opsz 9、WONK 1）；IATA 大字用的 opsz 144
  （HD4，WONK 一樣留預設）
- 芫荽 Iansui：`hongthai.og.required_chars` 的非 ASCII 字裡芫荽有的
- Noto Sans TC（芫荽缺字的備援）：可變字型固定 wght 400，取芫荽沒有的那些字；一個都沒缺時
  照樣產生（只含全形空白），讓程式與測試的路徑固定

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
RAW = "https://raw.githubusercontent.com"
SOURCES = {
    "iansui": f"{RAW}/ButTaiwan/iansui/9d9a8e68bf1e138dd91e562eeff28d95bca33196"
    "/fonts/ttf/Iansui-Regular.ttf",
    "fraunces": f"{RAW}/undercasetype/Fraunces/7ccdec31c6028118dce3e47fe864e3744460371d"
    "/fonts/variable/Fraunces%5BSOFT,WONK,opsz,wght%5D.ttf",
    "noto": f"{RAW}/google/fonts/47d54ca1ebb14fd864695f1d39dc734f39017c33"
    "/ofl/notosanstc/NotoSansTC%5Bwght%5D.ttf",
}
EXTRA_LATIN = "–—’“”·"


def download(url: str, dest: Path) -> Path:
    print(f"下載 {url}")
    with urllib.request.urlopen(url, timeout=120) as r:
        dest.write_bytes(r.read())
    return dest


def make_subset(font: TTFont, chars: set[str], out: Path, pin: dict | None = None) -> None:
    """取子集（可變字型再用 `pin` 固定各軸，變成靜態檔）寫到 `out`。"""
    opts = subset.Options()
    opts.name_IDs = ["*"]  # 名稱表（含版本、授權）全部留著
    opts.name_languages = ["*"]
    opts.hinting = False  # Pillow（FreeType）畫圖不用 TrueType hinting
    opts.notdef_outline = True
    s = subset.Subsetter(opts)
    s.populate(unicodes=sorted(ord(c) for c in chars))
    s.subset(font)
    if pin is not None:  # 先取子集再固定（整套 CJK 可變字型直接 instancer 很慢）
        font = instancer.instantiateVariableFont(font, pin, updateFontNames=True)
    font.save(out)
    print(f"{out.relative_to(ROOT)}：{len(font.getBestCmap())} 字，{out.stat().st_size:,} bytes")


def main() -> int:
    latin, other = og.required_chars(ROOT / "airports.json")
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="hongthai-fonts-") as tmp:
        files = {k: download(u, Path(tmp) / f"{k}.ttf") for k, u in SOURCES.items()}

        for key, opsz in (("latin", None), ("display", 144)):
            make_subset(
                TTFont(files["fraunces"]),
                latin | set(EXTRA_LATIN),
                OUT / og.FONT_FILES[key],
                {"SOFT": 100, "wght": 600, "opsz": opsz, "WONK": None},
            )

        ia = TTFont(files["iansui"])
        ia_cmap = ia.getBestCmap()
        have = {c for c in other if ord(c) in ia_cmap}
        missing = other - have
        make_subset(ia, have, OUT / og.FONT_FILES["cjk"])

        noto = TTFont(files["noto"])
        noto_cmap = noto.getBestCmap()
        lost = {c for c in missing if ord(c) not in noto_cmap}
        if lost:
            print(f"芫荽與 Noto 都沒有：{''.join(sorted(lost))}")
            return 1
        make_subset(noto, missing | {"　"}, OUT / og.FONT_FILES["fallback"], {"wght": 400})
        print(f"芫荽缺、靠 Noto 補的字（{len(missing)}）：{''.join(sorted(missing)) or '（無）'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
