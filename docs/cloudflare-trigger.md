# Cloudflare 排程 Worker（HD25 外部鬧鐘）

GitHub Actions 自己的排程常常晚到好幾個小時（2026-10-20～21 實測：build 13:05Z 那報 17:53Z 才觸發、20:25Z 那報
23:14Z；`events` 的整點 cron 18 小時只自動跑了 4 次），所以用 Cloudflare 的排程 Worker 當**主鬧鐘**，準時呼叫
GitHub API 觸發 workflow；GitHub 自己的 cron **留著當備援**。

## 做什麼

`cloudflare/trigger/`（Worker 名稱 `hongthai-trigger`）只有排程，沒有網址（`workers_dev = false`、
`preview_urls = false`，沒有 `fetch` 路由）。三條 Cron Triggers（UTC，免費方案每個帳號 5 條）：

| cron（UTC） | 台北／香港 | 觸發 |
| --- | --- | --- |
| `5 1,13 * * *` | 09:05、21:05 | `build.yml` |
| `25 8,20 * * *` | 16:25、04:25 | `build.yml` |
| `7 * * * *` | 每小時 07 分 | `events.yml` |

每次呼叫 `POST https://api.github.com/repos/Duadoapp/hongthai/actions/workflows/<檔名>/dispatches`，
內容 `{"ref": "main", "inputs": {"trigger": "cloudflare"}}`。GitHub 回 204 就是成功；不是 204 時在 Worker 日誌記
狀態碼與回應前 300 字，隔 30 秒重試一次，還是失敗就等 GitHub 自己的 cron。

兩邊都觸發時不會重跑 build：`build.py` 開頭發現這個時段（四個排定時間裡 ≤ 開始時間的最近一個）已經出過
（`data` 分支 `latest.json` 的 `generatedAt` ≥ 排定時間）就跳過，`history/timing/` 記一行 `source: "skip"`。
Actions 頁面手動按的 Run workflow（`trigger` 預設 `manual`）一律照跑。`events` 不跳過（多跑一次只是去重）。
細節見 README「排程」。

## 要先有的

- **這個 PR 合併之後才部署**：`build.yml`、`events.yml` 的 `trigger` input 要在 `main` 上，不然 GitHub 回 422
  （Unexpected inputs provided）
- 電腦裝了 Node.js（LTS 版就好；cmd 打 `node -v` 有版本號）
- Cloudflare 帳號（和 duado.app 同一個就行）。免費方案每個帳號最多 5 條 Cron Triggers，這裡用 3 條；
  帳號裡別的 Worker 已經用了 3 條以上的話，部署會失敗，先到主控台看

## 1. 建 GitHub 的 fine-grained PAT

1. GitHub 右上角頭像 → **Settings** → 左下 **Developer settings** → **Personal access tokens** →
   **Fine-grained tokens** → **Generate new token**
2. Token name：`hongthai-trigger`；**Resource owner** 選 `Duadoapp`
3. **Expiration**：Custom，選一年後的日期（記在行事曆，到期前換，見下面「換 token」）
4. **Repository access**：Only select repositories → 只選 `hongthai`
5. **Permissions** → Repository permissions → **Actions** 選 **Read and write**；其他都不開（Metadata: Read-only
   是 GitHub 自動帶的，拿不掉）
6. **Generate token**，複製 `github_pat_…`。**這串只在這一頁出現一次，不要貼到任何檔案、聊天或 repo 裡**，
   下一步直接貼進 wrangler
7. 組織若要求核准 fine-grained token：Shawn 是 `Duadoapp` 的擁有者，到 **組織頁 → Settings → Personal access
   tokens → Pending requests** 核准這把。組織若根本沒開放 fine-grained token：同一頁的 **Settings** 選
   「Allow access via fine-grained personal access tokens」

## 2. 部署（Windows cmd）

在 hongthai repo 的資料夾（先 `git pull` 拿到合併後的 `main`）：

```bat
cd cloudflare\trigger
npm ci
npx wrangler login
npx wrangler deploy
npx wrangler secret put GITHUB_TOKEN
```

- `npm ci` 只裝這個資料夾的 `wrangler`（自己一份 `package-lock.json`，不動 repo 根目錄）
- `npx wrangler login` 會開瀏覽器，登入 Cloudflare 按 Allow
- `npx wrangler deploy` 建 Worker 與三條 Cron Triggers；輸出最後應該列出
  `schedule: 5 1,13 * * *`、`schedule: 25 8,20 * * *`、`schedule: 7 * * * *`
- `npx wrangler secret put GITHUB_TOKEN` 會問 `Enter a secret value:`，貼第 1 步的 `github_pat_…`、Enter
  （畫面不會顯示）。secret 存在 Cloudflare，不會寫進任何檔案。先 deploy 再放 secret：中間如果剛好碰到排程，
  那一次在日誌記 401、GitHub 的 cron 備援照跑

以後改了 `cloudflare/trigger/` 再部署只要 `cd cloudflare\trigger`、`npm ci`、`npx wrangler deploy`
（secret 會留著）。

## 3. 確認有在動

- 下一個整點 07 分過後，GitHub → hongthai → **Actions → events**，最新一筆的事件是 `workflow_dispatch`
  （GitHub 自己排的是 `schedule`），log 的「每小時 METAR、颱風現報與航班」第一行是 `觸發：cloudflare`
- 下一個 build 時段過後，**Actions → build** 有一筆 `workflow_dispatch`；如果 GitHub 的排程後來也到了，那一筆
  「產生 latest.json」印「這個時段 HH:MMZ 已經在 … 出過，跳過」，Pages 那兩步是灰的（skipped）
- `data` 分支 `history/timing/<YYYY-MM>.jsonl`：每報 `start` 那行有 `trigger`、`slot`（排定時間）、`startedAt`
  （job 開始）、`delayMinutes`，看 Worker 準不準；跳過的是 `source: "skip"` 那行

## 看 Worker 日誌

- Cloudflare 主控台 → **Workers & Pages** → `hongthai-trigger` → **Logs**（`wrangler.toml` 開了
  `[observability]`，`console.log`／`console.error` 都留著）：成功是「已觸發 build.yml（cron "…"）」，
  失敗是「觸發 … 失敗：HTTP 401 …」之類
- 同一頁的 **Settings → Trigger events** 看得到三條 cron 和下次執行時間
- 即時看：cmd 在 `cloudflare\trigger` 跑 `npx wrangler tail`（Ctrl+C 結束）

常見的錯：401（token 錯、過期、被撤銷 → 重新 `secret put`）、403（token 權限不對，或組織還沒核准）、
404（token 沒選到 `hongthai`，或 workflow 檔名改了）、422（`main` 上的 workflow 沒有 `trigger` input）。

## 換 token（到期前）

GitHub 會在到期前寄信。建一把新的（同第 1 步）→ cmd 在 `cloudflare\trigger` 跑
`npx wrangler secret put GITHUB_TOKEN` 貼新的 → 下一次排程確認日誌是「已觸發」→ GitHub 的 Fine-grained tokens
頁把舊的 **Delete**。忘了換也不會壞掉，只是退回 GitHub 自己的 cron（又會晚）。

## 暫停

- 主控台 → `hongthai-trigger` → **Settings → Trigger events**，把 Cron Triggers 刪掉（GitHub 的 cron 照常）。
  注意：之後從 repo 再 `npx wrangler deploy` 會把三條加回來
- 要整個停：同一頁最下面 **Delete** Worker；或 GitHub 把 token 刪掉（之後每次都是 401）
- 要長期停又不想每次部署加回來：把 `wrangler.toml` 的 `crons` 改成 `[]` 再部署，並在 README「排程」記一筆
