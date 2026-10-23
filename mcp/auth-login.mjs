// Interactive Google sign-in for NotebookLM — replaces
// `notebooklm-mcp-server auth`, which doesn't work at 4.0.2 (verified live
// 2026-10-22):
//   - it treats any notebooklm.google.com page at "/" as signed in, which also
//     matches the public landing page, so it exits within seconds and saves a
//     cookie jar with no session;
//   - it exports cookies for notebooklm.google.com, but NotebookLM now lives
//     at notebook.google.com ("Gemini Notebook").
//
// This signs in on a persistent Chromium profile (git-ignored, under
// mcp/auth/browser-profile), waits until notebook.google.com is actually
// signed in, then saves the session to auth.json in the upstream format
// ({cookies, updatedAt}). Re-running it with a still-signed-in profile just
// re-exports the session, no sign-in needed.
//
// Run inside the mcp container (it has the display, noVNC and Playwright),
// then open http://localhost:6080/vnc.html to sign in:
//   docker compose --profile mcp run --rm --service-ports \
//     -v "$PWD/mcp/auth-login.mjs:/auth-login.mjs:ro" mcp node /auth-login.mjs
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
const PROFILE = path.join(HOME, "browser-profile");
const AUTH_PATH = path.join(HOME, "auth.json");
const ORIGIN = "https://notebook.google.com";
const TIMEOUT_MS = 15 * 60 * 1000;

const ctx = await chromium.launchPersistentContext(PROFILE, {
  headless: false,
  args: ["--disable-blink-features=AutomationControlled"],
});
const page = ctx.pages()[0] ?? (await ctx.newPage());

// Signed in = on notebook.google.com with the page's CSRF token present (the
// same token the server needs for every call).
const signedIn = async () => {
  try {
    return (
      page.url().startsWith(ORIGIN) &&
      (await page.evaluate(() => Boolean(window.WIZ_global_data?.SNlM0e)))
    );
  } catch {
    return false; // mid-navigation
  }
};

await page.goto(ORIGIN + "/", { waitUntil: "domcontentloaded", timeout: 60000 });
if (!(await signedIn())) {
  await page.goto(
    `https://accounts.google.com/ServiceLogin?continue=${encodeURIComponent(ORIGIN + "/")}`,
  );
  console.error("[auth-login] Waiting for you to sign in (up to 15 minutes)...");
  const deadline = Date.now() + TIMEOUT_MS;
  while (!(await signedIn())) {
    if (Date.now() > deadline) {
      console.error("[auth-login] Timed out waiting for sign-in; nothing saved.");
      await ctx.close();
      process.exit(1);
    }
    await page.waitForTimeout(2000);
  }
}

// Same cookie selection as upstream: the site's cookies plus a few critical
// ones from the wider jar.
const cookieMap = new Map();
for (const c of await ctx.cookies(ORIGIN)) cookieMap.set(c.name, c.value);
for (const c of await ctx.cookies()) {
  if (["__Secure-1PSIDTS", "__Secure-3PSIDTS", "LSID"].includes(c.name) && !cookieMap.has(c.name)) {
    cookieMap.set(c.name, c.value);
  }
}
const missing = ["SID", "HSID", "SSID", "APISID", "SAPISID"].filter((n) => !cookieMap.has(n));
if (missing.length) console.error(`[auth-login] Warning: missing cookies: ${missing.join(", ")}`);

fs.writeFileSync(
  AUTH_PATH,
  JSON.stringify(
    {
      cookies: [...cookieMap].map(([k, v]) => `${k}=${v}`).join("; "),
      updatedAt: new Date().toISOString(),
    },
    null,
    2,
  ),
);
console.error(`[auth-login] Signed in. Saved ${cookieMap.size} cookies to ${AUTH_PATH}`);
await ctx.close();
