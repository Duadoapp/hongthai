# HD51：`events.yml` 比照 HD45 拆成 collect／publish 兩個 job

模型：**Fable 5.2**（每小時跑、所有補抓都走它）。只改 `.github/workflows/events.yml`、必要時 `tools/push_data.sh`、`tests/test_workflows.py`（HD45 加的 workflow 檢查）、
README 與 `docs/cloudflare-trigger.md` 的說明。**不改 Python 程式、輸出檔、排程時間、觸發方式、手動輸入（backfill 那些勾選）**。`build.yml`、`longrange.yml` 不要碰。

先讀：`.github/workflows/events.yml` 全部（開頭的長註解是各個手動輸入的說明）、**HD45 的做法**（`.github/workflows/build.yml`、`tools/push_data.sh`、
`tests/test_workflows.py`、PR #175 的說明：`gh api repos/Duadoapp/hongthai/pulls/175 --jq .body`）、`docs/prompts/2026-11-10-HD45-build-publish-split.md`、
`docs/worklog/2026-11-10.md`（HD45 合併後的驗收）。

## 目標（和 HD45 同一個形狀）

- **collect job**：拿來源的 secrets（`GOOGLE_*`、`CWA_API_KEY`、`TDX_*`…）、`permissions` 只有 `contents: read`；取出 `data` 分支（只讀）、跑現有的每個步驟，
  最後把 `data` worktree 的變更包成 patch artifact（照 HD45：`git add -A` 後 `git diff --cached --binary`、記基準 commit 與套完之後的 tree）
- **publish job**（`needs`）：沒有任何來源的 secrets、不裝 Python 套件、不執行這個 repo 的 Python 程式；`permissions: contents: write`；下載 artifact、
  從基準 commit 套 patch、核對 tree、照 `push_data.sh` 的 rebase 重試推 `data`。`events` 不發布 Pages，所以沒有 Pages 那幾步、不需要 `id-token`
- 頂層 `permissions` 改成 `contents: read`，各 job 自己宣告；action 釘完整 commit SHA（沿用 `build.yml` 已經釘的那幾個版本）

## 一定要保住的行為（逐條在 PR 說明寫怎麼確認的）

1. **WN3**：`events.yml` 的 backfill-tracks 與每天 00Z 的搬家只會把**有效時間已過 1 小時以上**（或起報超過 121 小時）的 WN3 寫進 `data` worktree；
   artifact 是登入就能下載的——確認 artifact 裡只有本來就要推上 `data` 的檔，runner 上沒有別的含未來時段 WN3 數值的中間檔被包進去。artifact 保留 1 天
2. 現在一個 job 裡若有**多次推 `data`**（例如每小時的存檔推一次、backfill 各自再推）：先讀清楚現在推幾次、各在哪一步之後，拆完之後 `data` 分支上的結果要一樣
   （可以合成一個 commit，但 commit 訊息與「沒有變更就不推」的行為要交代）
3. `concurrency: events`（不取消進行中的）照舊的效果；和 `build.yml`、`longrange.yml` 同時推 `data` 的 rebase 重試（`.jsonl` 的 union 合併）照舊。
   每小時跑一次：兩個 job 加起來平常不能比現在慢太多（現在約 1 分鐘；寫出預期多幾秒），手動 backfill 的 `timeout-minutes: 90` 的效果照舊
4. 期間外「印一行就結束、不推」：publish job 要不要起來（照 HD45 的 `packed` 輸出，沒有變更就不跑 publish）
5. 各步驟現有的 `if:`、`continue-on-error`、失敗時 run 標紅的行為照舊；手動輸入一個都不能少、名稱不變（Cloudflare Worker 用 `trigger: cloudflare` 觸發）
6. `tests/test_workflows.py` 把 `events.yml` 也納入：collect job 沒有 `contents: write`、publish job 沒有引用任何 `secrets.`（除了 `GITHUB_TOKEN`）、action 都釘 SHA
7. `longrange.yml` 這次不拆（PR 說明寫一句它現在的狀況與建議）

## 驗證

- 沒辦法在 PR 上真的跑：PR 說明給「合併後第一次 run 要看什麼」的清單（每小時那次：兩個 job、`data` 有新 commit 或照舊沒變更不推；
  手動 `wn3-archive` 或 `backfill-metar` 各跑一次要看什麼），主對話合併後照清單看
- 回滾方式：revert 這支 PR 是否就回到現在

## 回報時要附

- 兩個 job 的權限與 secrets 對照表（之前／之後）、artifact 內容與大小估計
- 現在推 `data` 的次數與拆完之後的對照
- 合併後檢查清單；和提示詞不一樣的地方

本機 `ruff check .`、`ruff format --check .`、`pytest -q` 全過才推，盡量一次推完。
開 PR 之後：`gh pr checks --watch` 等 CI，紅了自己修並推到同一個分支（最多三輪），全綠時告訴我；
不要自己合併，我會先請主對話審查。
