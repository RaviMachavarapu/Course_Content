// Run: node --test mcp/shim/test/
import { test, before, afterEach } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

// AUTH_PATH is computed from os.homedir() when studio.js loads, so HOME must
// point at the temp dir before the dynamic imports below.
const home = fs.mkdtempSync(path.join(os.tmpdir(), "sources-test-"));
fs.mkdirSync(path.join(home, ".notebooklm-mcp"));
fs.writeFileSync(path.join(home, ".notebooklm-mcp", "auth.json"), JSON.stringify({ cookies: "SID=x; OSID=y" }));
process.env.HOME = home;

let uploadSource, sourceStatuses, StudioError;
before(async () => {
  ({ uploadSource, sourceStatuses } = await import("../sources.js"));
  ({ StudioError } = await import("../studio.js"));
});

const realFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = realFetch;
});

const PAGE = '<html>{"SNlM0e":"AT","FdrFJe":"1","cfb2h":"bl"}</html>';
const UPLOAD_URL = "https://notebook.google.com/upload/_/?authuser=0&upload_id=U1&upload_protocol=resumable";
const O4CBDC_REPLY =
  ')]}\'\n\n123\n[["wrb.fr","o4cbdc","[[[[\\"SRC\\"],\\"upload-check.pdf\\",[null,null,[1,2],null,3]]]]",null,null,null,"generic"]]';

function batchReply(rpcId, result) {
  return `)]}'\n\n123\n${JSON.stringify([["wrb.fr", rpcId, JSON.stringify(result), null, null, null, "generic"]])}`;
}

/** Stubs fetch; `finalStatus` is the x-goog-upload-status of the last reply. */
function fakeNotebookLm({ finalStatus = "final", batchBody = O4CBDC_REPLY } = {}) {
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    url = String(url);
    const headers = Object.fromEntries(Object.entries(init.headers ?? {}).map(([k, v]) => [k.toLowerCase(), v]));
    if ((init.method ?? "GET") === "GET" && url === "https://notebook.google.com/") {
      return new Response(PAGE, { status: 200 });
    }
    calls.push({ url, method: init.method, headers, body: init.body });
    if (url.includes("batchexecute")) return new Response(batchBody, { status: 200 });
    if (headers["x-goog-upload-command"] === "start") {
      return new Response("", {
        status: 200,
        headers: { "x-goog-upload-url": UPLOAD_URL, "x-goog-upload-status": "active" },
      });
    }
    const last = headers["x-goog-upload-command"] === "upload, finalize";
    return new Response(last ? "OK: Enqueued blob bytes to spanner queue for processing." : "", {
      status: 200,
      headers: { "x-goog-upload-status": last ? finalStatus : "active" },
    });
  };
  return calls;
}

function tempFile(size) {
  const file = path.join(home, `f${size}.pdf`);
  fs.writeFileSync(file, Buffer.from(Array.from({ length: size }, (_, i) => i % 251)));
  return file;
}

test("registers, starts, then uploads in one finalize for a small file", async () => {
  const file = tempFile(724);
  const calls = fakeNotebookLm();

  const id = await uploadSource("NB", file, "upload-check.pdf");

  assert.equal(id, "SRC");
  assert.equal(calls.length, 3);

  const [register, start, upload] = calls;
  assert.match(register.url, /batchexecute\?.*rpcids=o4cbdc/);
  const fReq = new URLSearchParams(register.body).get("f.req");
  assert.deepEqual(JSON.parse(JSON.parse(fReq)[0][0][1]), [
    [["upload-check.pdf", 3]],
    "NB",
    [2, null, [1], [1, null, null, null, null, null, null, null, null, null, [1, 3]]],
  ]);

  assert.equal(start.method, "POST");
  assert.equal(start.url, "https://notebook.google.com/upload/_/?authuser=0");
  assert.equal(start.headers["x-goog-upload-command"], "start");
  assert.equal(start.headers["x-goog-upload-header-content-length"], "724");
  assert.equal(start.headers["x-goog-upload-protocol"], "resumable");
  assert.equal(start.body, '{"PROJECT_ID":"NB","SOURCE_NAME":"upload-check.pdf","SOURCE_ID":"SRC"}');

  assert.equal(upload.url, UPLOAD_URL);
  assert.equal(upload.headers["x-goog-upload-command"], "upload, finalize");
  assert.equal(upload.headers["x-goog-upload-offset"], "0");
  assert.ok(Buffer.from(upload.body).equals(fs.readFileSync(file)));
});

test("uploads a 2.5 MB file in 1 MB pieces", async () => {
  const file = tempFile(2.5 * 1024 * 1024);
  const calls = fakeNotebookLm();

  await uploadSource("NB", file, "big.pdf");

  const pieces = calls.filter((c) => c.url === UPLOAD_URL);
  assert.deepEqual(
    pieces.map((c) => [c.headers["x-goog-upload-command"], c.headers["x-goog-upload-offset"], c.body.length]),
    [
      ["upload", "0", 1048576],
      ["upload", "1048576", 1048576],
      ["upload, finalize", "2097152", 524288],
    ],
  );
});

test("throws StudioError when the final reply is not x-goog-upload-status: final", async () => {
  const file = tempFile(724);
  fakeNotebookLm({ finalStatus: "active" });

  await assert.rejects(uploadSource("NB", file, "upload-check.pdf"), StudioError);
});

test("maps source status codes", async () => {
  const src = (id, code) => [[id], `t${id}`, [null, null, [1, 2]], [null, code]];
  fakeNotebookLm({ batchBody: batchReply("rLM1Ne", [["nb", [src("a", 5), src("b", 1), src("c", 2), src("d", 9)]]]) });

  assert.deepEqual(await sourceStatuses("NB"), [
    { id: "a", title: "ta", status: "pending" },
    { id: "b", title: "tb", status: "pending" },
    { id: "c", title: "tc", status: "ready" },
    { id: "d", title: "td", status: "failed" },
  ]);
});
