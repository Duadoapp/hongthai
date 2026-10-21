// HD25：Cloudflare 排程 Worker——依 cron 用 GitHub REST API 觸發 hongthai 的 workflow_dispatch。
// token 是只授權 Duadoapp/hongthai、只有 Actions: Read and write 的 fine-grained PAT，
// 放在 Worker 的 secret GITHUB_TOKEN（npx wrangler secret put GITHUB_TOKEN），不進 repo。

export const REPO = "Duadoapp/hongthai";
export const RETRY_DELAY_MS = 30_000;

export interface Dispatch {
  workflow: string;
  inputs: Record<string, string>;
}

// wrangler.toml 的 [triggers] crons → 觸發哪個 workflow（UTC）
export const CRONS: Record<string, Dispatch> = {
  // build.yml 的四個排定時間：01:05、13:05、08:25、20:25Z
  "5 1,13 * * *": { workflow: "build.yml", inputs: { trigger: "cloudflare" } },
  "25 8,20 * * *": { workflow: "build.yml", inputs: { trigger: "cloudflare" } },
  // events.yml 每小時
  "7 * * * *": { workflow: "events.yml", inputs: { trigger: "cloudflare" } },
};

export function dispatchFor(cron: string): Dispatch | null {
  return CRONS[cron] ?? null;
}

interface Env {
  GITHUB_TOKEN: string;
}

interface ScheduledController {
  cron: string;
  scheduledTime: number;
}

async function dispatchOnce(env: Env, d: Dispatch): Promise<boolean> {
  const url = `https://api.github.com/repos/${REPO}/actions/workflows/${d.workflow}/dispatches`;
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: {
        Accept: "application/vnd.github+json",
        Authorization: `Bearer ${env.GITHUB_TOKEN}`,
        "Content-Type": "application/json",
        "User-Agent": "hongthai-trigger",
        "X-GitHub-Api-Version": "2022-11-28",
      },
      body: JSON.stringify({ ref: "main", inputs: d.inputs }),
    });
    if (res.status === 204) {
      return true;
    }
    const body = (await res.text()).slice(0, 300);
    console.error(`觸發 ${d.workflow} 失敗：HTTP ${res.status} ${body}`);
  } catch (e) {
    console.error(`觸發 ${d.workflow} 失敗：${String(e)}`);
  }
  return false;
}

export default {
  async scheduled(controller: ScheduledController, env: Env): Promise<void> {
    const d = dispatchFor(controller.cron);
    if (d === null) {
      console.error(`沒有對應的 workflow：cron "${controller.cron}"`);
      return;
    }
    if (await dispatchOnce(env, d)) {
      console.log(`已觸發 ${d.workflow}（cron "${controller.cron}"）`);
      return;
    }
    // 重試一次（隔 30 秒）；還是失敗就等 GitHub 自己的 cron 備援
    await new Promise((resolve) => setTimeout(resolve, RETRY_DELAY_MS));
    if (await dispatchOnce(env, d)) {
      console.log(`重試後已觸發 ${d.workflow}（cron "${controller.cron}"）`);
    }
  },
};
