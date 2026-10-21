# HD25：外部鬧鐘——Cloudflare 排程 Worker 準時觸發 build／events，重複觸發自動跳過；METAR 往回抓 6 小時並補缺口

模型：Opus，強度中。**凍結前（2026-10-22 12:00 台灣時間）合併**：只動排程與資料保存，**不改等級規則、投票、門檻、`latest.json` 欄位**
（`latest.json` 一個欄位都不加；第 2 點的 `trigger` 只寫進 `timing/`）。
新 `cloudflare/trigger/`（Worker）、改 `.github/workflows/build.yml`、`events.yml`、`src/hongthai/build.py`（開頭的跳過檢查）、
`src/hongthai/events.py`（METAR 往回抓的時數、補缺口）、測試、README、新 `docs/cloudflare-trigger.md`、`docs/ORCHESTRATOR.md`。

先讀 `docs/ORCHESTRATOR.md`「29W 驗證期凍結」、`.github/workflows/build.yml`（cron 與 `concurrency`）、`events.yml`、`src/hongthai/build.py`
（`main`、`timing`、讀上一份 `latest.json` 的地方）、`src/hongthai/events.py`（`METAR_HOURS`、`hourly`、`metar/<日期>.jsonl` 去重）。

## 為什麼（實測，2026-10-20～21）

GitHub 的排程延遲很嚴重：build 13:05Z 那報 17:53Z 才觸發（晚 4 小時 48 分）、20:25Z 那報 23:14Z（晚 2 小時 49 分）、01:05Z 那報到 01:53Z
還沒觸發；`events.yml` 的整點 cron（xx:07）18 小時只自動跑了 4 次（13:30、18:25、22:12、01:26Z）。METAR 只往回抓 3 小時，所以
`history/events/29W/metar/` 已經有好幾段缺口——29W 驗證的真相資料在漏。

## 定案（Shawn 2026-10-21 10:02 同意主對話的做法）

1. **Cloudflare 排程 Worker 當主鬧鐘**，GitHub 自己的 cron **留著當備援**（不刪）
2. Worker 用 GitHub REST API `POST /repos/Duadoapp/hongthai/actions/workflows/<檔名>/dispatches`（`ref: main`）觸發；token 是 Shawn 建的
   fine-grained PAT（只授權 `Duadoapp/hongthai`、權限只有 **Actions: Read and write**），放 Worker 的 secret `GITHUB_TOKEN`，
   **不進 repo、不給主對話**
3. 兩邊都觸發時不重跑：build 開頭檢查，這一個排程時段已經出過就跳過；Shawn 手動按的一律照跑

## 1. Worker（`cloudflare/trigger/`）

- `wrangler.toml`（`name = "hongthai-trigger"`、`main = "src/index.ts"`、`compatibility_date` 用合併當天）＋`src/index.ts`＋`package.json`
  （只有 `wrangler` 一個 devDependency，自己一份 lock，**不動 repo 根目錄的任何東西**）
- Cron Triggers 三條（UTC；免費方案每個帳號 5 條，夠）：
  - `"5 1,13 * * *"`、`"25 8,20 * * *"` → 觸發 `build.yml`，`inputs: {trigger: "cloudflare"}`
  - `"7 * * * *"` → 觸發 `events.yml`，`inputs: {trigger: "cloudflare"}`
- `scheduled(event)` 依 `event.cron` 決定觸發哪個 workflow；請求帶 `Accept: application/vnd.github+json`、`X-GitHub-Api-Version`、
  `User-Agent: hongthai-trigger`；非 204 時 `console.error` 狀態碼與回應前 300 字（Cloudflare 的 Worker 日誌看得到），**重試一次**（隔 30 秒）
- 不開 `fetch` 路由（沒有網址可以從外面戳）；`workers_dev = false`
- 測試：`src/index.ts` 的「cron → workflow 檔名與 inputs」抽成純函式，用 `node --test`（或 vitest，擇一，寫在 `cloudflare/trigger/package.json`）
  測三條 cron 的對照；這個測試**不用進 Python 的 CI**，但在 `.github/workflows/ci.yml` 加一個只在 `cloudflare/**` 變動時跑的 job

## 2. build 的跳過檢查（`build.yml`、`build.py`）

- `workflow_dispatch` 加 input `trigger`（字串，預設 `"manual"`，選項 `manual`／`cloudflare`）；GitHub 排程觸發時視為 `"schedule"`
- `build.py` 開頭（下載任何模式之前）：`trigger` 是 `schedule` 或 `cloudflare` 時，算出「這個時段的排定時間」＝四個排定時間
  （01:05、08:25、13:05、20:25Z）裡 ≤ 現在的最近一個；讀目前 Pages 上的 `latest.json`（或 `data` 分支最新快照，擇一、寫清楚）的
  `generatedAt`，**≥ 排定時間就跳過**：印一行「這個時段 HH:MMZ 已經在 <generatedAt> 出過，跳過」、`timing/` 記一行
  `{"source": "skip", "trigger": ..., "slot": ...}`、workflow 成功結束（不推 Pages、不推 `data`）
- `manual` 一律照跑（Shawn 自己按的）
- 讀不到上一份 `latest.json` 時照跑（寧可多跑）
- `timing/` 每報第一行多記 `trigger`（`schedule`／`cloudflare`／`manual`）與排定時間、實際開始時間、延遲分鐘——給之後看 Worker
  準不準；`latest.json` **不加**
- `concurrency` 已經是 `group: build`、不取消，兩個同時觸發會排隊，第二個進來時第一個已經出過 → 跳過，正好

## 3. events 的觸發與 METAR 缺口（`events.yml`、`events.py`）

- `events.yml` 的 `workflow_dispatch` 加 `trigger` input（同上）；**events 不做跳過檢查**（一小時跑兩次也只是去重，成本很低）
- `METAR_HOURS` 3 → **6**（AviationWeather `hours` 參數；去重照舊，半小時一報的站多抓的會被去掉）
- **補缺口**：`python -m hongthai.events backfill-metar --archive data --from 2026-10-19T00:00Z`：對期間內每個機場，用 AviationWeather
  能往回抓的最長時數（**先查文件與實測上限**，例如 `hours=168` 能不能用；不行就查 Iowa State 的 ASOS／METAR 存檔
  `mesonet.agron.iastate.edu/cgi-bin/request/asos.py`，免金鑰、可以指定日期區間與站號，ICAO 四碼）把缺的小時補進
  `metar/<日期>.jsonl`（同一個去重鍵，已有的不覆蓋；補進來的每行多 `"backfill": "<來源>"`）；金馬（RCBS、RCFG）是氣象署觀測，
  氣象署 `O-A0003-001` 只有現在，**補不到就記 log、不硬補**
- `events.yml` 的 `workflow_dispatch` 加 `backfill-metar` 勾選項；合併後 Shawn 手動跑一次
- 回報：每個機場每天的觀測小時數，補之前／之後

## 4. 文件

- `docs/cloudflare-trigger.md`：Worker 做什麼、三條 cron、怎麼部署（**Windows cmd**：`cd cloudflare\trigger`、`npm ci`、
  `npx wrangler login`、`npx wrangler secret put GITHUB_TOKEN`（貼的是 Shawn 自己的 PAT，**不要寫進任何檔案**）、`npx wrangler deploy`）、
  fine-grained PAT 怎麼建（GitHub → Settings → Developer settings → Fine-grained tokens；Resource owner 選 `Duadoapp`、只選
  `hongthai`、Repository permissions 只開 Actions: Read and write、到期日 1 年；組織若要求核准，Shawn 是擁有者，到組織設定核准）、
  token 到期前要換、怎麼在 Cloudflare 主控台看 Worker 日誌、怎麼暫停（主控台把 Cron Triggers 拿掉）
- README「排程」改寫：Cloudflare 主、GitHub 備援、跳過規則；ORCHESTRATOR 凍結那段補「HD25 只動排程與資料保存，不改規則」

## 回報時要附

- AviationWeather `hours` 的實際上限（文件與實測）、補 METAR 用了哪個來源、每站補之前／之後的小時數
- `timing/` 最近 10 報的排定時間 vs 實際開始時間（從 `data` 分支的 `timing/` 算），給 Shawn 看延遲有多嚴重
- Shawn 要手動做的步驟清單（建 PAT、部署 Worker、跑 `backfill-metar`），照 `docs/cloudflare-trigger.md`

本機 `ruff check .`、`ruff format --check .`、`pytest -q` 全過才推，盡量一次推完。
開 PR 之後：`gh pr checks --watch` 等 CI，紅了自己修並推到同一個分支（最多三輪），全綠時告訴我；
不要自己合併，我會先請主對話審查。
