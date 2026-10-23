// Record the NotebookLM web app's own batchexecute requests while you use it
// (via noVNC), to learn the current wire format of STUDIO_GENERATE and the
// option fields the pinned notebooklm-mcp-server@4.0.2 doesn't know about.
//
// Writes one JSON line per RPC to mcp/auth/capture.jsonl (git-ignored): the
// rpc id, the decoded params, the URL's source-path, and the start of the
// response. Cookies and the `at` CSRF token are never written.
//
//   docker compose --profile mcp run --rm --service-ports \
//     -v "$PWD/mcp/capture-requests.mjs:/capture.mjs:ro" mcp node /capture.mjs <notebook_id>
// Stop: close the Chromium window, or wait for the time limit.
// The browser also listens on 127.0.0.1:9222 (inside the container only) so
// helper scripts can drive the page with chromium.connectOverCDP while this
// process keeps recording.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";

const pkgDir = fs
  .readdirSync("/root/.npm/_npx")
  .map((d) => path.join("/root/.npm/_npx", d, "node_modules"))
  .find((d) => fs.existsSync(path.join(d, "notebooklm-mcp-server")));
const { chromium } = createRequire(path.join(pkgDir, "noop.js"))("playwright");

const HOME = path.join(os.homedir(), ".notebooklm-mcp");
const OUT = path.join(HOME, "capture.jsonl");
const NOTEBOOK = process.argv[2];
const LIMIT_MS = 3 * 60 * 60 * 1000;

function decodeBody(postData) {
  const form = new URLSearchParams(postData ?? "");
  const fReq = form.get("f.req");
  if (!fReq) return [];
  try {
    // [[[rpcId, paramsJson, null, "generic"], ...]]
    return JSON.parse(fReq)[0].map(([rpc, params]) => {
      let decoded = params;
      try {
        decoded = JSON.parse(params);
      } catch {}
      return { rpc, params: decoded };
    });
  } catch {
    return [{ rpc: null, raw: fReq.slice(0, 2000) }];
  }
}

const ctx = await chromium.launchPersistentContext(path.join(HOME, "browser-profile"), {
  headless: false,
  args: ["--disable-blink-features=AutomationControlled", "--remote-debugging-port=9222"],
});
const page = ctx.pages()[0] ?? (await ctx.newPage());
let count = 0;

ctx.on("requestfinished", async (req) => {
  const url = new URL(req.url());
  if (!url.pathname.endsWith("/data/batchexecute")) return;
  const calls = decodeBody(req.postData());
  let response = null;
  try {
    const res = await req.response();
    response = { status: res?.status(), head: (await res?.text())?.slice(0, 1500) };
  } catch {}
  for (const call of calls) {
    const line = {
      t: new Date().toISOString(),
      rpc: call.rpc,
      sourcePath: url.searchParams.get("source-path"),
      params: call.params ?? call.raw,
      response,
    };
    fs.appendFileSync(OUT, JSON.stringify(line) + "\n");
    count += 1;
  }
});

await page.goto(`https://notebook.google.com/notebook/${NOTEBOOK}`, {
  waitUntil: "domcontentloaded",
  timeout: 60000,
});
console.error(`[capture] Recording to ${OUT}. Close the browser window when done.`);

await Promise.race([
  new Promise((resolve) => ctx.on("close", resolve)),
  new Promise((resolve) => setTimeout(resolve, LIMIT_MS)),
]);
console.error(`[capture] Done. ${count} RPC calls recorded.`);
await ctx.close().catch(() => {});
