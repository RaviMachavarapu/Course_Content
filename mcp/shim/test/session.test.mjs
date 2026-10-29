// Connector session: reconnect after the child exits, one stdio call at a time,
// and permanent vs transient error statuses.
// Run: node --test mcp/shim/test/
import { test } from "node:test";
import assert from "node:assert/strict";
import { createSession } from "../session.js";
import { ToolError, failStatus } from "../tools.js";
import { StudioError } from "../studio.js";

/** A fake SDK client; `close()` behaves like the transport closing (calls onclose). */
function fakeClient(name, { reply = { structuredContent: { ok: name } }, delay = 0 } = {}) {
  const c = {
    name,
    calls: [],
    closed: false,
    onclose: undefined,
    async callTool(req) {
      if (c.closed) throw new Error("Not connected");
      c.calls.push(req.name);
      if (delay) await new Promise((r) => setTimeout(r, delay));
      return typeof reply === "function" ? reply(req) : reply;
    },
    async close() {
      c.closed = true;
      c.onclose?.();
    },
  };
  return c;
}

function factory(...clients) {
  const made = [];
  const connect = async () => {
    const c = clients[made.length] ?? fakeClient(`c${made.length}`);
    made.push(c);
    return c;
  };
  return { connect, made };
}

test("a child process that exits is replaced on the next call", async () => {
  const { connect, made } = factory();
  const s = createSession(connect);
  assert.deepEqual(await s.call("notebook_list", {}), { ok: "c0" });
  made[0].closed = true;
  made[0].onclose(); // the child exited: the SDK transport closes
  assert.deepEqual(await s.call("notebook_list", {}), { ok: "c1" });
  assert.equal(made.length, 2);
});

test("a call on a client that lost its transport reconnects once and retries", async () => {
  const { connect, made } = factory();
  const s = createSession(connect);
  await s.call("notebook_list", {});
  made[0].closed = true; // "Not connected", but onclose never fired
  assert.deepEqual(await s.call("notebook_create", { title: "x" }), { ok: "c1" });
  assert.deepEqual(made[1].calls, ["notebook_create"]);
});

test("a connection that closes mid-call is not retried (the call may have run)", async () => {
  const dying = fakeClient("c0", {
    reply: () => {
      throw new Error("MCP error -32000: Connection closed");
    },
  });
  const { connect, made } = factory(dying);
  const s = createSession(connect);
  await assert.rejects(s.call("notebook_add_url", {}), /Connection closed/);
  assert.equal(made.length, 1);
  await s.call("notebook_list", {}); // the next call gets a fresh child
  assert.equal(made.length, 2);
});

test("stdio calls run one at a time, in order", async () => {
  const log = [];
  const slow = fakeClient("c0", {
    delay: 20,
    reply: (req) => {
      log.push(req.name);
      return { structuredContent: req.name };
    },
  });
  const { connect } = factory(slow);
  const s = createSession(connect);
  const a = s.call("notebook_query", {});
  assert.equal(s.busy(), true);
  const b = s.call("notebook_list", {});
  assert.deepEqual(await Promise.all([a, b]), ["notebook_query", "notebook_list"]);
  assert.deepEqual(log, ["notebook_query", "notebook_list"]);
  assert.equal(s.busy(), false);
});

test("reset closes the child and the next call starts a new one", async () => {
  const { connect, made } = factory();
  const s = createSession(connect);
  await s.call("notebook_list", {});
  await s.reset();
  assert.equal(made[0].closed, true);
  await s.call("notebook_list", {});
  assert.equal(made.length, 2);
  await s.reset();
  await s.connect(); // Refresh auth starts the new child straight away
  assert.equal(made.length, 3);
  await s.close();
  assert.equal(made[2].closed, true);
});

test("connector rejections are permanent (422), sign-in problems 401, the rest 502", () => {
  assert.equal(failStatus(new ToolError("notebook_add_url", "This video is private")), 422);
  assert.equal(failStatus(new ToolError("notebook_list", "Authentication expired, please sign in")), 401);
  assert.equal(failStatus(new StudioError("unsupported kind")), 422);
  assert.equal(failStatus(new StudioError("session rejected", { auth: true })), 401);
  assert.equal(failStatus(new Error("Not connected")), 502);
  assert.equal(failStatus(new Error("MCP error -32001: Request timed out")), 502);
});

test("after a tool call times out the child is replaced (a stale call can't interleave)", async () => {
  const slow = fakeClient("slow", {
    reply: () => {
      const err = new Error("MCP error -32001: Request timed out");
      err.code = -32001;
      throw err;
    },
  });
  const { connect, made } = factory(slow);
  const s = createSession(connect);
  await assert.rejects(s.call("notebook_query", {}), /timed out/);
  assert.equal(slow.closed, true);
  assert.deepEqual(await s.call("notebook_list", {}), { ok: "c1" });
  assert.equal(made.length, 2);
});
