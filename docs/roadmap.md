# HongTai 路線圖

做什麼、先做什麼看這份（2026-11-10 建立，比照 Duado 的 `docs/roadmap.md`）。**排序由 Shawn 決定**；主對話的排法先照建議做（可以反悔、不花錢、不對外的），
要 Shawn 決定的題目放 Duado repo `docs/pending.md` 的「HongTai」段。做完的從這裡拿掉，寫進當天日誌。

規則：**現在**是已經開工的；**下一個**輪到才寫提示詞；**之後**確定要做但還沒排；**點子箱**一行就好。

## 現在（2026-11-11）

| 代號 | 做什麼 | 模型 | 只動 |
| --- | --- | --- | --- |
| HD48 | 公開 WN3 自己的整體等級（`level`，沒有數值） | Opus 高 | `assess.public_slots`、`build.hide_wn3`、`config`、測試、README |
| HD49 | WN3 加雨量（讀 Zarr 逐時雨量） | Opus 高 | `sources/wn3.py`、`wn3report.py`、`wn3private.py`、測試、README |
| HW26 | 網頁模式表顯示 WN3 的等級（HD48 合併後開） | Opus 中 | Duado `site/hongthai/`、`hongthai.*` 語系鍵 |

- 觀察：HD47 上線後用 `python -m tools.ai_cost --from 2026-11-11 --breakdown --calibrate-as after` 驗快取命中與每次成本

## 下一個

1. `events.yml` 比照 HD45 拆 build／publish（每小時跑、也同時拿金鑰與可寫的 token）；`longrange.yml` 優先度低
2. **改名 HongTai＋搬到 `hongtai.app`**（Duado spec 第 16 節「改名與獨立網域」）：**Shawn 11/11 決定先不買網域，往後排**。順序：
   HW25（前置）→ Duado 總指揮加建置目標與轉送 → 改名、副標題（HW，編號到時再排）、canonical、sitemap、隱私頁 → HD48 分享圖上的名稱與網址 →
   `duado.app/hongthai/...` 301 → Search Console、送 sitemap
3. **回測之後的校準**：HD46 的報告出來後，看門檻（`assess.py`、`airports.json`）要不要調；改門檻前先問 Shawn
4. **AI 評論成本的第二步**：HD47 報告列的大項（精簡輸入、少評幾個機場、換小模型）要 Shawn 決定的部分

## 之後

- WN3 內部檢視頁（`admin.duado.app`，Duado 總指揮；Shawn 要先建只讀服務帳號 `hongthai-wn3-reader`）
- 下一個影響範圍內機場的颱風：`events.json` 加一筆、照 29W 的流程保存與出報告
- 還沒排的來源：FNV3／WeatherNext Cyclones 路徑、日本機場警報（JMA bosai）、華南與馬尼拉

## 點子箱

- 「Sunhong Studio 出品」：公司成立後頁尾與關於頁才寫
- 等級從「風險」改叫「機率」：要回測校準站得住才談
