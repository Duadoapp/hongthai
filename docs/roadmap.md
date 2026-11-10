# HongTai 路線圖

做什麼、先做什麼看這份（2026-11-10 建立，比照 Duado 的 `docs/roadmap.md`）。**排序由 Shawn 決定**；主對話的排法先照建議做（可以反悔、不花錢、不對外的），
要 Shawn 決定的題目放 Duado repo `docs/pending.md` 的「HongTai」段。做完的從這裡拿掉，寫進當天日誌。

規則：**現在**是已經開工的；**下一個**輪到才寫提示詞；**之後**確定要做但還沒排；**點子箱**一行就好。

## 現在（2026-11-10 這一批，互不撞檔）

| 代號 | 做什麼 | 模型 | 只動 |
| --- | --- | --- | --- |
| HD44 | `http_get` 加大小上限（S1 的 L27） | Opus 中 | `src/hongthai/sources/__init__.py`、測試 |
| HD45 | `build.yml` 拆成 build／publish 兩個 job（S1 的 L25） | Fable 5.2 | `.github/workflows/build.yml`、README、`docs/cloudflare-trigger.md` |
| HD46 | 回測校準報告：燈號等級對實際取消／延誤（10/18 起） | Opus 高 | `tools/calibration_report.py`、`report/`、測試 |
| HD47 | AI 評論成本：量每段 token、提高快取命中、`DAILY_CAP` | Opus 高 | `src/hongthai/ai/`、`tools/ai_cost.py`、測試 |
| HW25 | 網頁程式不寫死 `/hongthai` 路徑（搬家的前置，畫面不變） | Fable 5.2 | Duado `site/hongthai/` |

## 下一個

1. **改名 HongTai＋搬到 `hongtai.app`**（Duado spec 第 16 節「改名與獨立網域」）：等 Shawn 買網域、開 Cloudflare Pages 專案（pending）。順序：
   HW25（前置）→ Duado 總指揮加建置目標與轉送 → HW26 改名、副標題、canonical、sitemap、隱私頁 → HD48 分享圖上的名稱與網址 →
   `duado.app/hongthai/...` 301 → Search Console、送 sitemap
2. **回測之後的校準**：HD46 的報告出來後，看門檻（`assess.py`、`airports.json`）要不要調；改門檻前先問 Shawn
3. **AI 評論成本的第二步**：HD47 報告列的大項（精簡輸入、少評幾個機場、換小模型）要 Shawn 決定的部分

## 之後

- WN3 的雨量：改讀 Zarr 的逐時雨量（每報多下載約 3 GB、build 多約 1 分鐘），現在 WN3 那一票只看風（pending）
- WN3 內部檢視頁（`admin.duado.app`，Duado 總指揮；Shawn 要先建只讀服務帳號 `hongthai-wn3-reader`）
- 下一個影響範圍內機場的颱風：`events.json` 加一筆、照 29W 的流程保存與出報告
- Cloudflare Worker 的 PAT 到期日改 90 天（S1 的 L26，Shawn 換 PAT 時做；pending）
- 還沒排的來源：FNV3／WeatherNext Cyclones 路徑、日本機場警報（JMA bosai）、華南與馬尼拉

## 點子箱

- 「Sunhong Studio 出品」：公司成立後頁尾與關於頁才寫
- 等級從「風險」改叫「機率」：要回測校準站得住才談
