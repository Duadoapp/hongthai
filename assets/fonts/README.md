# 分享預覽圖的字型（HD1、HD4、HD39）

`src/hongthai/og.py` 畫 `og/<iata>.png` 用的字型。HD39（2026-10-25）起換成 HongThai 品牌「風眼夜航」的字
（Duado HW8 設計稿：標題與數字 Space Grotesk、中文 Noto Sans TC），拿掉晨光風格的 Fraunces 與芫荽。
兩套都是 **SIL Open Font License 1.1**，這裡**只放子集**（只含圖上會出現的字），授權檔各自一份。完整字型不進 repo。

| 檔案 | 字型 | 用在哪 | 來源與版本 | 子集 | 授權 |
| --- | --- | --- | --- | --- | --- |
| `SpaceGrotesk-Medium.subset.ttf` | Space Grotesk Medium（wght 500） | ASCII 與數字的小字（英文名、日期時間、時間軸日期、`duado.app/hongthai`、「Claude」「Gemini」） | [google/fonts](https://github.com/google/fonts/tree/main/ofl/spacegrotesk) commit `47d54ca1`，`ofl/spacegrotesk/SpaceGrotesk[wght].ttf`，Version 2.000 | ASCII 可印字元 95 個，19 KB | `OFL-SpaceGrotesk.txt` |
| `SpaceGrotesk-Bold.subset.ttf` | Space Grotesk Bold（wght 700） | 只給 IATA 大字 | 同上 | 同上，95 字，19 KB | `OFL-SpaceGrotesk.txt`（共用） |
| `NotoSansTC-Regular.subset.ttf` | Noto Sans TC Regular（wght 400） | 中文小字（燈號小字、標籤、更新時間、「風颱」） | [google/fonts](https://github.com/google/fonts/tree/main/ofl/notosanstc) commit `47d54ca1`，`ofl/notosanstc/NotoSansTC[wght].ttf`，Version 2.004 | 149 字，41 KB | `OFL-NotoSansTC.txt` |
| `NotoSansTC-Bold.subset.ttf` | Noto Sans TC Bold（wght 700） | 機場名、燈號色塊裡的字 | 同上 | 同上，149 字，41 KB | `OFL-NotoSansTC.txt`（共用） |

- 兩套都是可變字型，用 fontTools `varLib.instancer` 固定 `wght` 產生靜態檔（產生的檔案一樣是 OFL）
- 程式逐字選字型（`og.font_key`）：ASCII（含數字）→ Space Grotesk，其他字 → Noto Sans TC；粗細看那一行
  （IATA、機場名 zh-TW、燈號字用 Bold，其他用 Medium／Regular）
- 子集涵蓋的字（`og.required_chars`）：`airports.json` 的機場名（zh-TW、en）與地區名（zh-TW）、
  `og.TEXTS`（燈號、小字、更新時間、「風颱」、`duado.app/hongthai` 等固定字串，也先放了 AI 對決要用的「規則」
  「Claude」「Gemini」「沒看到明顯風險」，HD8 加主因的「強風」「大雨」「大雪」「濃霧」）、`og.PUNCTUATION`
  （全形標點、`–`、`・`）裡不是 ASCII 的字放 Noto；Space Grotesk 只收 ASCII（`–`、`・` 這些走 Noto）
- 字標「HongThai」**不用字檔**：照 Duado `site/hongthai/brand.ts` 的 `WORDMARK_PATH`（Space Grotesk Bold
  轉成的外框，含字距調整）攤平成多邊形畫（`og._wordmark`），和網頁的字標一模一樣
- Reserved Font Name：Space Grotesk 沒有；Noto 的授權保留的是「Source」，子集的名稱不含這個字

## 怎麼重做

加了機場、改了機場名或 `og.TEXTS` 之後要重做（`tests/test_og.py` 會檢查涵蓋，沒重做 CI 會紅）：

```sh
pip install ".[dev]"
python tools/make_font_subset.py
```

腳本從上面的 commit 下載兩套完整的可變字型（Space Grotesk 約 140 KB、Noto Sans TC 約 12 MB）到暫存目錄（不進 repo），
先取子集再固定字重，各產兩個靜態檔寫回這裡，印出每個的字數與大小。Noto Sans TC 沒有的字會報錯（回傳 1）。
換字型版本時改腳本裡的 commit，再更新這份的表格。授權檔 `OFL-SpaceGrotesk.txt` 是同一個 commit 的
`ofl/spacegrotesk/OFL.txt`。
