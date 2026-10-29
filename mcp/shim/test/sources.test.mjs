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

let uploadSource, sourceStatuses, readySourceIds, StudioError, PathNotAllowed;
before(async () => {
  ({ uploadSource, sourceStatuses, readySourceIds, PathNotAllowed } = await import("../sources.js"));
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

  const id = await uploadSource("NB", file, "upload-check.pdf", { root: home });

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

  await uploadSource("NB", file, "big.pdf", { root: home });

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

  await assert.rejects(uploadSource("NB", file, "upload-check.pdf", { root: home }), StudioError);
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

const src = (id, code) => [[id], `t${id}`, [null, null, [1, 2]], [null, code]];

test("Studio generation gets only ready source ids", async () => {
  fakeNotebookLm({ batchBody: batchReply("rLM1Ne", [["nb", [src("orphan", 5), src("good", 2)]]]) });
  assert.deepEqual(await readySourceIds("NB"), ["good"]);
});

test("no ready sources is a StudioError", async () => {
  fakeNotebookLm({ batchBody: batchReply("rLM1Ne", [["nb", [src("a", 5), src("b", 1)]]]) });
  await assert.rejects(readySourceIds("NB"), (e) => e instanceof StudioError && /no ready sources/.test(e.message));
});

test("a missing file fails before any source is registered", async () => {
  const calls = fakeNotebookLm();
  await assert.rejects(uploadSource("NB", path.join(home, "nope.pdf"), "nope.pdf", { root: home }), StudioError);
  assert.equal(calls.length, 0);
});

test("only PDFs under /data/media may be uploaded, checked before any request", async () => {
  const calls = fakeNotebookLm();
  for (const p of [
    "/root/.notebooklm-mcp/auth.json",
    "/data/media/../../root/.notebooklm-mcp/auth.json",
    "/data/media-evil/a.pdf",
    "/data/media/uploads/notes.txt",
    "uploads/a.pdf",
  ]) {
    await assert.rejects(
      uploadSource("NB", p, "a.pdf"),
      (e) => e instanceof PathNotAllowed && e.message === "path not allowed",
      p,
    );
  }
  assert.equal(calls.length, 0);
});

test("a .PDF under the media root is allowed (case-insensitive)", async () => {
  const file = path.join(home, "UPPER.PDF");
  fs.writeFileSync(file, "%PDF-1.4");
  fakeNotebookLm();
  assert.equal(await uploadSource("NB", file, "upload-check.pdf", { root: home }), "SRC");
});

test("unknown status codes are failed and logged once per call", async (t) => {
  const warn = t.mock.method(console, "warn", () => {});
  fakeNotebookLm({ batchBody: batchReply("rLM1Ne", [["nb", [src("a", 9), src("b", 2), src("c", 7)]]]) });

  const out = await sourceStatuses("NB");

  assert.deepEqual(
    out.map((s) => s.status),
    ["failed", "ready", "failed"],
  );
  assert.equal(warn.mock.callCount(), 1);
  const msg = warn.mock.calls[0].arguments.join(" ");
  assert.match(msg, /a.*9/);
  assert.match(msg, /c.*7/);
});

test("a symlink under the media root pointing outside it is refused", async () => {
  const outside = fs.mkdtempSync(path.join(os.tmpdir(), "outside-"));
  const secret = path.join(outside, "auth.pdf");
  fs.writeFileSync(secret, "%PDF secret");
  const link = path.join(home, "innocent.pdf");
  fs.symlinkSync(secret, link);
  const calls = fakeNotebookLm();
  await assert.rejects(uploadSource("NB", link, "innocent.pdf", { root: home }), PathNotAllowed);
  assert.equal(calls.length, 0);
});

test("a symlinked directory inside the media root is refused too", async () => {
  const outside = fs.mkdtempSync(path.join(os.tmpdir(), "outside-dir-"));
  fs.writeFileSync(path.join(outside, "x.pdf"), "%PDF x");
  fs.symlinkSync(outside, path.join(home, "linked"));
  const calls = fakeNotebookLm();
  await assert.rejects(
    uploadSource("NB", path.join(home, "linked", "x.pdf"), "x.pdf", { root: home }),
    PathNotAllowed,
  );
  assert.equal(calls.length, 0);
});

// -- Google 5xx/429 are transient; failed uploads don't leave orphan sources (review 2026-10-29)

test("an rpc answered with 5xx or 429 and no result is transient (502), a 4xx is permanent", async () => {
  const { rpc } = await import("../studio.js");
  const { failStatus } = await import("../tools.js");
  for (const [status, expected] of [[503, 502], [500, 502], [429, 502], [400, 422]]) {
    globalThis.fetch = async (url, init = {}) => {
      if ((init.method ?? "GET") === "GET") return new Response(PAGE, { status: 200 });
      return new Response("<html>busy</html>", { status });
    };
    const err = await rpc("R7cb6c", [], "/notebook/NB").catch((e) => e);
    assert.ok(err instanceof Error, `HTTP ${status}`);
    assert.equal(failStatus(err), expected, `HTTP ${status}`);
  }
});

function failingUpload({ startStatus = 503, deleteBody = null } = {}) {
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    url = String(url);
    if ((init.method ?? "GET") === "GET" && url === "https://notebook.google.com/") {
      return new Response(PAGE, { status: 200 });
    }
    const headers = Object.fromEntries(Object.entries(init.headers ?? {}).map(([k, v]) => [k.toLowerCase(), v]));
    calls.push({ url, body: init.body, headers });
    if (url.includes("rpcids=o4cbdc")) return new Response(O4CBDC_REPLY, { status: 200 });
    if (url.includes("rpcids=tGMBJ")) {
      if (deleteBody === "fail") return new Response("", { status: 500 });
      return new Response(batchReply("tGMBJ", []), { status: 200 });
    }
    return new Response("", { status: startStatus });
  };
  return calls;
}

test("an upload failing after the source was registered deletes that source", async () => {
  const file = tempFile(724);
  const calls = failingUpload();
  const { failStatus } = await import("../tools.js");

  const err = await uploadSource("NB", file, "upload-check.pdf", { root: home }).catch((e) => e);

  assert.equal(failStatus(err), 502); // still worth a retry
  const del = calls.find((c) => c.url.includes("rpcids=tGMBJ"));
  assert.ok(del, "the registered source is deleted");
  const fReq = new URLSearchParams(del.body).get("f.req");
  assert.deepEqual(JSON.parse(JSON.parse(fReq)[0][0][1]), [[["SRC"]], [2]]);
});

test("a failed cleanup never hides the upload's own error", async () => {
  const file = tempFile(724);
  failingUpload({ startStatus: 400, deleteBody: "fail" });
  const err = await uploadSource("NB", file, "upload-check.pdf", { root: home }).catch((e) => e);
  assert.ok(err instanceof StudioError);
  assert.match(err.message, /upload start failed \(HTTP 400\)/);
});

test("an artifact neither call lists is reported missing (it was deleted or never existed)", async () => {
  const { artifactState } = await import("../studio.js");
  const tool = (listed) => async (name) => {
    if (name === "artifact_content_get") return { raw: [], html: null };
    if (name === "studio_poll") return { artifacts: listed };
    throw new Error(name);
  };
  assert.deepEqual(await artifactState(tool([]), "NB", "A"), { status: null, raw: null, html: null, missing: true });
  assert.deepEqual(await artifactState(tool([{ artifact_id: "A", status: "in_progress" }]), "NB", "A"), {
    status: 2,
    raw: null,
    html: null,
    missing: false,
  });
  const row = ["A", "t", 1, null, 3];
  const withRow = async (name) => (name === "artifact_content_get" ? { raw: [row], html: "<p>" } : {});
  assert.deepEqual(await artifactState(withRow, "NB", "A"), { status: 3, raw: row, html: "<p>", missing: false });
});
