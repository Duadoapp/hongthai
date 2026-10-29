// cron → workflow 的對照（node --test；Node 22.18 起直接跑 .ts）
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { CRONS, dispatchFor } from "../src/index.ts";

test("build.yml 的四個排定時間", () => {
  for (const cron of ["5 1,13 * * *", "25 8,20 * * *"]) {
    assert.deepEqual(dispatchFor(cron), {
      workflow: "build.yml",
      inputs: { trigger: "cloudflare" },
    });
  }
});

test("events.yml 每小時", () => {
  assert.deepEqual(dispatchFor("7 * * * *"), {
    workflow: "events.yml",
    inputs: { trigger: "cloudflare" },
  });
});

test("longrange.yml 每天一次、時間和 longrange.yml 的 cron 一致", () => {
  const yml = readFileSync(new URL("../../../.github/workflows/longrange.yml", import.meta.url), "utf8");
  const github = [...yml.matchAll(/- cron: "([^"]+)"/g)].map((m) => m[1]);
  const worker = Object.entries(CRONS)
    .filter(([, d]) => d.workflow === "longrange.yml")
    .map(([cron]) => cron);
  assert.deepEqual(worker, github);
  assert.deepEqual(dispatchFor("47 11 * * *"), {
    workflow: "longrange.yml",
    inputs: { trigger: "cloudflare" },
  });
});

test("沒列的 cron 不觸發", () => {
  assert.equal(dispatchFor("0 * * * *"), null);
});

test("wrangler.toml 的 crons 和 CRONS 一致", () => {
  const toml = readFileSync(new URL("../wrangler.toml", import.meta.url), "utf8");
  const line = toml.split("\n").find((l) => l.startsWith("crons = "));
  assert.ok(line, "wrangler.toml 沒有 crons");
  assert.deepEqual(JSON.parse(line.slice("crons = ".length)), Object.keys(CRONS));
});

test("build 的時間和 build.yml 的 cron 一致", () => {
  const yml = readFileSync(new URL("../../../.github/workflows/build.yml", import.meta.url), "utf8");
  const github = [...yml.matchAll(/- cron: "(\d+) (\d+) \* \* \*"/g)].map((m) => `${m[2]}:${m[1]}`);
  const worker = Object.entries(CRONS)
    .filter(([, d]) => d.workflow === "build.yml")
    .flatMap(([cron]) => {
      const [minute, hours] = cron.split(" ");
      return hours.split(",").map((h) => `${h}:${minute}`);
    });
  assert.deepEqual(worker.sort(), github.sort());
});
