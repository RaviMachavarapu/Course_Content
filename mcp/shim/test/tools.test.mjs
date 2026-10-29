// Run: node --test mcp/shim/test/
import { test } from "node:test";
import assert from "node:assert/strict";
import { TOOL_TIMEOUT_MS, ToolError, callMcpTool } from "../tools.js";

function fakeClient(result) {
  const calls = [];
  return {
    calls,
    async callTool(...args) {
      calls.push(args);
      return result;
    },
  };
}

test("passes a 300 s per-request timeout instead of the SDK's 60 s default", async () => {
  const c = fakeClient({ structuredContent: { ok: true } });
  const data = await callMcpTool(c, "notebook_query", { q: "x" });
  assert.equal(TOOL_TIMEOUT_MS, 300_000);
  assert.deepEqual(c.calls, [[{ name: "notebook_query", arguments: { q: "x" } }, undefined, { timeout: 300_000 }]]);
  assert.deepEqual(data, { ok: true });
});

test("defaults missing arguments to an empty object", async () => {
  const c = fakeClient({ content: [{ type: "text", text: '{"a":1}' }] });
  assert.deepEqual(await callMcpTool(c, "notebook_list"), { a: 1 });
  assert.deepEqual(c.calls[0][0], { name: "notebook_list", arguments: {} });
});

test("throws when the tool reports an error", async () => {
  const c = fakeClient({ isError: true, content: [{ type: "text", text: "boom" }] });
  await assert.rejects(
    callMcpTool(c, "notebook_list", {}),
    (e) => e instanceof ToolError && /tool notebook_list failed: .*boom/.test(e.message),
  );
});
