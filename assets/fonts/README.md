# 分享預覽圖的字型（HD1、HD4）

`src/hongthai/og.py` 畫 `og/<iata>.png` 用的字型。三套都是 **SIL Open Font License 1.1**，
這裡**只放子集**（只含圖上會出現的字），授權檔各自一份。完整字型不進 repo。

| 檔案 | 字型 | 用在哪 | 來源與版本 | 子集 | 授權 |
| --- | --- | --- | --- | --- | --- |
| `Fraunces-Soft600.subset.ttf` | Fraunces（SuperSoft SemiBold，opsz 9） | ASCII 與數字的小字（英文名、日期時間、時間軸日期、`duado.app/hongthai`） | [undercasetype/Fraunces](https://github.com/undercasetype/Fraunces) commit `7ccdec31`，`fonts/variable/Fraunces[SOFT,WONK,opsz,wght].ttf`，Version 1.003 | ASCII 可印字元 95 個＋`–—’“”·`，共 101 字，25 KB | `OFL-Fraunces.txt` |
| `Fraunces-Soft600-Display.subset.ttf` | Fraunces（144pt SuperSoft SemiBold，opsz 144） | 只給 IATA 大字（HD4） | 同上 | 同上，101 字，25 KB | `OFL-Fraunces.txt`（共用） |
| `Iansui-Regular.subset.ttf` | 芫荽 Iansui | 其他字（中文、全形標點） | [ButTaiwan/iansui](https://github.com/ButTaiwan/iansui) commit `9d9a8e68`，`fonts/ttf/Iansui-Regular.ttf`，Version 1.012 | 145 字，79 KB | `OFL-Iansui.txt` |
| `NotoSansTC-Regular.subset.ttf` | Noto Sans TC（Regular） | 芫荽缺的字（備援） | [google/fonts](https://github.com/google/fonts/tree/main/ofl/notosanstc) commit `47d54ca1`，`ofl/notosanstc/NotoSansTC[wght].ttf`，Version 2.004 | 芫荽缺的字＋全形空白；2026-10-19 芫荽全都有，所以只有全形空白 1 字，3 KB | `OFL-NotoSansTC.txt` |

- Fraunces 是可變字型，用 fontTools `varLib.instancer` 固定 `SOFT` 100（最圓）、`wght` 600，產生兩個
  靜態檔（產生的檔案一樣是 OFL）：小字用的 `opsz`、`WONK` 留預設（9、1）；IATA 大字用的 `opsz` 144
  （大字專用的字形，`WONK` 一樣留預設）。Noto Sans TC 固定 `wght` 400
- 程式逐字選字型：ASCII（含數字）→ Fraunces（IATA 大字用 opsz 144 那個，其他用 opsz 9 那個）；其他字芫荽子集有就用芫荽，沒有用 Noto（`og.font_key`）
- 子集涵蓋的字（`og.required_chars`）：`airports.json` 的機場名（zh-TW、en）與地區名（zh-TW）、
  `og.TEXTS`（燈號、小字、更新時間、品牌字樣等固定字串，也先放了 AI 對決要用的「規則」「Claude」
  「Gemini」「沒看到明顯風險」）、`og.PUNCTUATION`（全形標點、`–`、`・`），以及全部 ASCII
- Reserved Font Name：芫荽、Fraunces 沒有；Noto 的授權保留的是「Source」，子集的名稱不含這個字

## 怎麼重做

加了機場、改了機場名或 `og.TEXTS` 之後要重做（`tests/test_og.py` 會檢查涵蓋，沒重做 CI 會紅）：

```sh
pip install ".[dev]"
python tools/make_font_subset.py
```

腳本從上面三個 commit 下載完整字型（Fraunces 產兩個子集）到暫存目錄（不進 repo），取子集寫回這裡，印出每套的字數與大小、
芫荽缺了哪些字靠 Noto 補。芫荽與 Noto 都沒有的字會報錯（回傳 1）。換字型版本時改腳本裡的 commit，
再更新這份的表格。
