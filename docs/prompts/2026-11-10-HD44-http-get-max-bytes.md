# HD44：`http_get` 加回應大小上限（資安掃描 S1 的 L27）

模型：Opus，強度中。只改 `src/hongthai/sources/__init__.py` 與測試；**輸出 JSON、排程、其他來源的行為都不變**。
同時在跑的 HD45（`build.yml`）、HD46（`tools/calibration_report.py`）、HD47（`src/hongthai/ai/`）不要碰。

先讀：`src/hongthai/sources/__init__.py` 的 `http_get`、`budget.py`（`add_bytes`、`check_cancelled`）、`docs/worklog/2026-11-04.md`（S1）。

## 背景

`http_get` 現在把整份回應讀進記憶體、沒有上限。上游回超大回應只會讓這一報失敗，不是漏洞，但要收掉。

## 要做

1. `http_get` 加 `max_bytes` 參數（預設值你量過再定：先 grep 所有呼叫的地方、看 `data` 分支 `history/timing/` 最近幾報各來源實際的 bytes，
   預設取「目前最大的單一回應 × 至少 4 倍」、湊整數；ECMWF／GFS 這類大檔的呼叫端各自傳比較大的上限）。PR 說明列出每個呼叫端目前最大值與設的上限
2. 用 `stream=True` 分塊讀：先看 `Content-Length`（有而且超過就直接放棄、不讀），沒有就邊讀邊數，超過就關連線
3. 超過上限：丟呼叫端的 `error` 類別、代碼 `too_large`，**不重試**（重試只會再下載一次）；log 只印網址（照現有截斷方式）、上限與已讀 bytes
4. 回傳的物件呼叫端照舊能用 `.content`、`.text`、`.json()`、`.status_code`、`.url`（不要改任何呼叫端的寫法，除了傳 `max_bytes`）；
   `add_bytes`、log 的 bytes 數、`ok_404`、逾時與重試照舊
5. README 來源錯誤代碼的表加 `too_large`
6. 不是走 `http_get` 的下載（gcsfs、BigQuery、Open-Meteo 若另有 client）不在這支；PR 說明列出還有哪些沒有上限

## 測試

- 有 `Content-Length` 超過、沒有 `Content-Length` 邊讀邊超過、剛好等於上限、`ok_404`、逾時重試照舊
- 超過不重試（只呼叫一次）
- 現有測試不改就過（用到假 `requests.get` 的測試若因 `stream` 要調整，PR 說明寫清楚改了哪些）

## 回報時要附

- 各呼叫端的實測最大值與上限表
- 和提示詞不一樣的地方

本機 `ruff check .`、`ruff format --check .`、`pytest -q` 全過才推，盡量一次推完。
開 PR 之後：`gh pr checks --watch` 等 CI，紅了自己修並推到同一個分支（最多三輪），全綠時告訴我；
不要自己合併，我會先請主對話審查。
