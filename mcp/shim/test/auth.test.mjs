// Refresh auth / a new sign-in must not keep the old session's rotated cookies or
// page token in memory. Run: node --test mcp/shim/test/
import { test, before, afterEach } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

// AUTH_PATH is computed from os.homedir() when studio.js loads.
const home = fs.mkdtempSync(path.join(os.tmpdir(), "auth-test-"));
fs.mkdirSync(path.join(home, ".notebooklm-mcp"));
const AUTH = path.join(home, ".notebooklm-mcp", "auth.json");
const saveAuth = (cookies) => fs.writeFileSync(AUTH, JSON.stringify({ cookies }));
saveAuth("SID=one; SIDCC=saved");
process.env.HOME = home;

let studio;
before(async () => {
  studio = await import("../studio.js");
});

const realFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = realFetch;
  saveAuth("SID=one; SIDCC=saved");
  studio.resetSession();
});

function rotated(value) {
  return new Response("", { headers: [["set-cookie", `SIDCC=${value}; Domain=.google.com; Path=/`]] });
}

test("rotated cookies are used until Refresh auth resets the session", () => {
  studio.remember(rotated("fresh"));
  assert.match(studio.cookieHeader("notebook.google.com"), /SIDCC=fresh/);
  studio.resetSession();
  assert.match(studio.cookieHeader("notebook.google.com"), /SIDCC=saved/);
});

test("a new sign-in written to auth.json drops the old session's rotated cookies", () => {
  studio.cookieHeader("notebook.google.com"); // sees SID=one
  studio.remember(rotated("old-session"));
  saveAuth("SID=two; SIDCC=new-login");
  const header = studio.cookieHeader("notebook.google.com");
  assert.match(header, /SID=two/);
  assert.match(header, /SIDCC=new-login/);
  assert.doesNotMatch(header, /old-session/);
});

test("the connector rewriting the same session keeps the rotated cookies", () => {
  studio.cookieHeader("notebook.google.com");
  studio.remember(rotated("ours"));
  saveAuth("SID=one; SIDCC=connector");
  assert.match(studio.cookieHeader("notebook.google.com"), /SIDCC=ours/);
});

test("Refresh auth drops the cached page token", async () => {
  let pages = 0;
  globalThis.fetch = async (url) => {
    if (String(url) === `${studio.ORIGIN}/`) {
      pages += 1;
      return new Response('{"SNlM0e":"AT","FdrFJe":"1","cfb2h":"bl"}', { status: 200 });
    }
    const body = `)]}'\n\n1\n${JSON.stringify([["wrb.fr", "X", JSON.stringify([1]), null, null, null, "generic"]])}`;
    return new Response(body, { status: 200 });
  };
  await studio.rpc("X", [], "/");
  await studio.rpc("X", [], "/");
  assert.equal(pages, 1);
  studio.resetSession();
  await studio.rpc("X", [], "/");
  assert.equal(pages, 2);
});
