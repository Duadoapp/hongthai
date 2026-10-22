# HD32（只存資料）：TDX 台灣其他機場航班——每小時逐班存檔，不上網頁

模型：Sonnet，強度中。**排在 HD31 合併之後**（用 HD31 的 `flights/` 格式與 `flights_log.py`）。**只多存資料**：不改 `latest.json`、等級、網頁；凍結期間
可以合併。改 `src/hongthai/sources/tdx.py`（新）、`src/hongthai/flights_log.py`（接 TDX）、`events.py`（`hourly` 第四件事多一個來源）、`events.yml`（secret
傳進去）、測試、README、`docs/ORCHESTRATOR.md`。

先讀 HD31 的提示詞與實作（`flights_log.py`、`events.py` 的 `flights/`）、`sources/flights.py`、`cancellations.py`（狀態分類規則）。

## 1. 認證與金鑰

- Shawn 在 TDX（`https://tdx.transportdata.tw/`）註冊會員、建立 API 金鑰，放進 repo 的 Actions secrets：**`TDX_CLIENT_ID`**、**`TDX_CLIENT_SECRET`**
  ——程式從環境變數讀，**不寫進任何檔案、log 不印**；`events.yml` 那一步的 `env` 加這兩個
- 取 token：OAuth2 client credentials（`POST https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token`，**以官方文件為準**），
  一次執行取一次、記在記憶體
- **secret 不存在時整件事跳過**（記一行 log「TDX 未設定」），其他不受影響——所以這支可以在 Shawn 設好 secret 之前先合併

## 2. 抓哪些（以 TDX 文件為準）

- 航空即時航班（FIDS）API，查 `airports.json` 裡**台灣全部機場**：TPE、TSA、KHH、RMQ、TNN、HUN、TTT、MZG、KNH、LZN（出發、抵達）
- 每小時一次，請求數要小（每個機場出發＋抵達各一，或文件有「全部機場」一次拿的就用那個）；遵守文件的頻率限制，**實測後把限制寫進 README**
- 欄位對照到 HD31 的一行格式，`source: "tdx"`；狀態文字照 `cancellations.py` 的台灣規則（開頭「取消」→ 取消、「延誤／延遲」→ 延誤），新看到的用語記 log
- **桃園、松山、高雄已經有原本的來源**：TDX 的照樣存（`source` 不同），之後比對兩邊一致性；不合併、不去重

## 3. 授權

TDX 資料依「政府資料開放授權條款」；README 資料來源加 TDX，註明出處寫法（照 TDX 的規定）。

## 4. 測試

TDX 回應的 fixture（文件範例或手造）：欄位轉換、分類、只在變化時寫；沒有 secret → 跳過、不報錯；token 失敗 → 只記 log

## 回報時要附

- TDX 實際用的端點、頻率限制（文件原文）、每小時請求數
- secret 設好後第一個整點：各機場寫了幾行（Shawn 設好前，PR 先附用文件範例跑的結果）

本機 `ruff check .`、`ruff format --check .`、`pytest -q` 全過才推，盡量一次推完。
開 PR 之後：`gh pr checks --watch` 等 CI，紅了自己修並推到同一個分支（最多三輪），全綠時告訴我；
不要自己合併，我會先請主對話審查。
