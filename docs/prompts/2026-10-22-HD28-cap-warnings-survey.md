# HD28（調查）：中國、韓國、菲律賓、越南、帛琉的官方警報能從哪裡拿——WMO SWIC、WIS2、各國 CAP feed 實測

模型：Opus，強度中。**這是調查，不改管線**：不動 `src/`、`.github/workflows/`、`airports.json`、`latest.json`，凍結期間可以跑。
產出一份報告 `docs/surveys/2026-10-22-cap-warnings.md`（新資料夾），附實測時抓到的少量樣本到 `docs/surveys/samples/2026-10-22-cap/`
（每國每條路一兩則，總共 < 2 MB；不要存金鑰或帳密）。開一個 docs PR。

先讀 `docs/ORCHESTRATOR.md` 的警報段落、`docs/worklog/2026-10-22.md`（「官方警報還沒接的地方」與待決定 (b)）、`airports.json`（這幾國的機場、座標、
地區）、`src/hongthai/sources/nws.py`（關島怎麼接）、`sources/hko.py`、`sources/jma.py`（現有警報來源的樣子）。

## 背景（主對話 2026-10-22 01:44 查的，雲端要實測確認）

- 沒有官方警報來源的機場：中國大陸 15 個、韓國 4 個（ICN、GMP、PUS、CJU）、越南 4 個（HAN、SGN、DAD、CXR、PQC 裡的實際清單以 `airports.json` 為準）、
  菲律賓 3 個（MNL、CEB、CRK）、帛琉 ROR
- 中國氣象局網頁 `weather.cma.cn/web/alarm/map.html` 前面有 WAF 滑塊驗證碼——**不要嘗試繞過任何驗證碼或防火牆**；只走公開給機器讀的管道
- 可能的管道：
  1. **WMO SWIC 3.0**（`severeweather.wmo.int`，香港天文台代 WMO 經營）：彙整 130 多個會員的官方 CAP 警報，CMA、KMA、PAGASA、越南都有參加；
     使用須知（`note.html`）寫「The information is free for re-use by media or other websites」，要註明各國發布機關。網頁地圖背後的 JSON 網址要
     實際打開網頁、看網路請求（用 Playwright，環境已裝 Chromium）
  2. **WIS2**：SWIC 的資料集 `urn:wmo:md:hk-hko-swic:recommended.weather.advisories-warnings`（MQTT topic
     `origin/a/wis2/hk-hko-swic/data/recommended/weather/advisories-warnings`，Global Broker 例如 cn-cma、fr-meteofrance、us-noaa-nws）；
     我們是批次工作（每小時、每 6 小時），查 **Global Cache 有沒有 HTTP 可以補抓最近 24 小時**，以及通知裡的 `canonical` 下載網址
  3. **各國原始 CAP feed**：IFRC Alert Hub 的 CAP Aggregator（`github.com/IFRC-Alert-Hub/Alert-Hub-CAP-Aggregator`，正式環境的 `feeds/` 介面）
     列出它轉發中的 feed，可拿來找各國原始網址；也查 Google Public Alerts 的來源清單、各國氣象機關網站
  4. **帛琉**：NWS 關島分處的責任區含帛琉（`weather.gov/gum/AOR`）；查 NWS API（`api.weather.gov/alerts/active?zone=…`）帛琉的 zone 代碼
  5. **韓國**：若 CAP 拿不到，公共資料入口網的氣象廳特報 API（要申請金鑰）——只寫怎麼申請、免不免費，**不要申請、不要要金鑰**

## 每一條路要回答

- 能不能**匿名**讀？網址、格式（CAP 1.2 XML／RSS／Atom／JSON）、要不要金鑰；回應大小與秒數（從這台與從 GitHub Actions 的網路各試一次若可行）
- **更新頻率**與延遲：警報發布到出現在這條路上多久
- **內容**：有沒有颱風（熱帶氣旋）警報、大風、暴雨、濃霧；有沒有涵蓋到我們的機場（CAP 的 `area` 是多邊形、地理代碼還是地名；怎麼對到機場）；
  語言（有沒有中文、英文）
- **授權**：原文照錄（SWIC 的使用須知、各國機關的條款、WIS2 data policy `recommended` 的條件）；轉載時要怎麼標示
- **實測**：颱風 29W 期間，各國現在有哪些生效中的警報（列出來，這正好拿來驗證涵蓋範圍）

## 報告格式

1. 一張總表：國家 × 管道（SWIC JSON、WIS2、原始 CAP、其他）→ 能／不能、網址、金鑰、格式、延遲、授權一句話
2. 每國一節：細節、樣本檔名、對到機場的方法、坑
3. **建議**：先接哪幾國、用哪條路、接進現在管線的做法（`sources/<名稱>.py`、`warningSources`、`kind` 命名、等級建議——等級由主對話與產品負責人定，
   這裡只提建議並註明「待定」），預算秒數估計
4. 還不確定、要產品負責人或主對話決定的事

## 不要做

- 不改任何程式與設定；不申請帳號或金鑰；不繞過驗證碼、WAF、robots；每個網站請求量保持很小（同一網址不要連打）

開 PR 之後：`gh pr checks --watch` 等 CI，紅了自己修並推到同一個分支（最多三輪），全綠時告訴我；
不要自己合併，我會先請主對話審查。
