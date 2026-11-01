// googlevideo throttles a plain GET of an Audio Overview to playback speed
// (~32 KB/s, so a 20 MB file takes 10+ minutes); byte ranges come at full speed.
// Run: node --test mcp/shim/test/
import { test, afterEach } from "node:test";
import assert from "node:assert/strict";
import { download } from "../studio.js";

const realFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = realFetch;
});

function fakeGooglevideo(file) {
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    const range = init.headers?.Range;
    calls.push(range ?? "full");
    if (!range) {
      // the throttled stream: its body must never be read
      const body = new ReadableStream({ pull: () => new Promise(() => {}) });
      return new Response(body, {
        status: 200,
        headers: { "content-type": "audio/mp4", "content-length": String(file.length) },
      });
    }
    const [, a, b] = range.match(/^bytes=(\d+)-(\d+)$/);
    const end = Math.min(Number(b), file.length - 1);
    return new Response(file.subarray(Number(a), end + 1), {
      status: 206,
      headers: { "content-type": "audio/mp4", "content-range": `bytes ${a}-${end}/${file.length}` },
    });
  };
  return calls;
}

test("downloads googlevideo media in byte ranges instead of the throttled stream", async () => {
  const file = Buffer.from(Array.from({ length: 2.5 * 1024 * 1024 }, (_, i) => i % 251));
  const calls = fakeGooglevideo(file);

  const { type, data } = await download("https://rr1---sn-x.googlevideo.com/videoplayback?id=1");

  assert.equal(type, "audio/mp4");
  assert.ok(data.equals(file));
  assert.deepEqual(calls.slice(1), [
    "bytes=0-1048575",
    "bytes=1048576-2097151",
    "bytes=2097152-2621439",
  ]);
});

test("a 5xx or 429 from the media host is transient (502); other failures are permanent", async () => {
  const { failStatus } = await import("../tools.js");
  for (const [status, expected] of [[503, 502], [429, 502], [404, 422]]) {
    globalThis.fetch = async () => new Response("", { status });
    const err = await download("https://lh3.googleusercontent.com/x").catch((e) => e);
    assert.equal(failStatus(err), expected, `HTTP ${status}`);
  }
});

test("a 5xx on a byte range is transient (502)", async () => {
  const { failStatus } = await import("../tools.js");
  const file = Buffer.alloc(2 * 1024 * 1024, 1);
  globalThis.fetch = async (_url, init = {}) => {
    if (!init.headers?.Range) {
      return new Response("", { status: 200, headers: { "content-type": "audio/mp4", "content-length": String(file.length) } });
    }
    return new Response("", { status: 503 });
  };
  const err = await download("https://rr1---sn-x.googlevideo.com/videoplayback?id=1").catch((e) => e);
  assert.equal(failStatus(err), 502);
});
