# HD45：`build.yml` 拆成 build／publish 兩個 job（資安掃描 S1 的 L25）

模型：**Fable 5.2**（牽動每天四報的發布流程）。只改 `.github/workflows/build.yml`、必要時 `tools/push_data.sh`、README 與 `docs/cloudflare-trigger.md` 的說明。
**不改 Python 程式、輸出 JSON、排程時間、觸發方式（schedule、Cloudflare Worker 的 `workflow_dispatch`、手動）**。
同時在跑的 HD44（`sources/__init__.py`）、HD46（`tools/`、`report/`）、HD47（`src/hongthai/ai/`）不要碰。

先讀：`.github/workflows/build.yml` 全部、`tools/push_data.sh`、`events.yml`、`longrange.yml`（都推 `data` 分支，注意同時推的 rebase 重試）、
`docs/cloudflare-trigger.md`、README「相依套件」、`docs/worklog/2026-11-04.md`。S1 報告 L25 原文：同一個 job 同時拿 AI 金鑰、可寫 repo 的 token 與
Pages 部署的 OIDC token；三個都有用途，只是相依套件被動手腳時一次拿到三樣。

## 目標

- **build job**：拿所有來源與 AI 的 secrets（`ANTHROPIC_API_KEY`、`GOOGLE_*`、`CWA_API_KEY`、`TDX_*`…），`permissions` 只有 `contents: read`；
  裝套件、取出 `data` 分支（只讀）、跑 `python -m hongthai.build`，把「要推進 `data` 分支的變更」與「Pages 要發布的目錄」各包成 artifact
- **publish job**（`needs: build`）：**沒有任何來源與 AI 的 secrets、不裝 Python 套件、不執行這個 repo 的 Python 程式**；`permissions` 是
  `contents: write`、`pages: write`、`id-token: write`、`environment: github-pages`；下載 artifact → 推 `data` 分支（照 `push_data.sh` 的 rebase 重試）→
  上傳 Pages artifact → deploy
- 頂層 `permissions` 改成最小（`contents: read`），各 job 自己宣告

## 一定要保住的行為（逐條在 PR 說明寫怎麼確認的）

1. **WN3 的未來時段數值不能進 artifact 以外的任何公開地方**——而且 **Actions artifact 在公開 repo 是登入就能下載的**：artifact 裡只能放本來就要公開的檔
   （`data` 分支的新增／修改檔、Pages 目錄）。先確認 build 產生的東西裡沒有只存在 runner 上的私人中間檔被一起包進去（私人 bucket 那份是直接寫 GCS，不落地到
   `data`／Pages 目錄；照 `wn3private.py`、`wn3report.py` 確認）。artifact 保留天數設 1 天
2. `data` 分支的變更怎麼帶到 publish：build job 裡 `data` worktree 可能刪檔、搬檔（例如 WN3 超過 121 小時後搬家、history 清理）——不能只複製新增的檔。
   建議做法：build job 在 worktree 裡 `git add -A` 後產生 patch（`git diff --cached --binary`）或 bundle 當 artifact，publish job checkout `data` 後套用；
   你選一種，說明理由，並處理「build 開始後、publish 之前 `events.yml`／`longrange.yml` 先推了 `data`」的情況（現在靠 rebase）
3. 「這個時段已出過就跳過」（`cloudflare`／`schedule` 觸發）跳過時，publish job 要不要跑、Pages 要不要重發：照現在的行為（先讀現在怎麼做）
4. 現在各步驟的 `if:`、`continue-on-error`、「流程失敗時標紅」、記開始時間、`timeout-minutes`（build 步驟 45 分、整體 55 分）照舊的效果；
   兩個 job 的 timeout 加起來不超過現在太多（排程間隔至少 4.5 小時）
5. `concurrency` 設定照舊的效果（兩個 job 之間不要被另一次 run 插隊推 `data`）
6. action 一律釘完整 commit SHA、後面註解版本（M6）；新用到的 `upload-artifact`／`download-artifact` 也是，SHA 用
   `git ls-remote --tags https://github.com/actions/<名稱>` 查
7. `longrange.yml`、`events.yml` 這次**不拆**（PR 說明寫要不要比照、各自的風險，給主對話排下一支）

## 驗證

- 沒辦法在 PR 上真的跑發布：PR 說明寫清楚「合併後第一次 run 要看什麼」的清單（兩個 job 各自的步驟、`data` 分支有新 commit、Pages 更新時間、
  `latest.json` 的 `generatedAt`、artifact 內容抽查沒有 WN3 數值），主對話合併後會手動跑一次 build 照清單看
- 可以的話用 `actionlint`（或 `python -c "import yaml"` 至少語法）檢查；加一個不連網的測試檢查 workflow：build job 沒有 `contents: write`／`id-token`、
  publish job 的 `env` 與步驟沒有引用任何 `secrets.`（除了 `GITHUB_TOKEN`）、action 都釘 SHA
- 回滾方式：PR 說明寫「出問題時 revert 這支 PR 即可」是否成立

## 回報時要附

- 兩個 job 的權限與 secrets 對照表（之前／之後）
- artifact 清單與每個的內容、大小估計、保留天數
- 合併後檢查清單；和提示詞不一樣的地方

本機 `ruff check .`、`ruff format --check .`、`pytest -q` 全過才推，盡量一次推完。
開 PR 之後：`gh pr checks --watch` 等 CI，紅了自己修並推到同一個分支（最多三輪），全綠時告訴我；
不要自己合併，我會先請主對話審查。
