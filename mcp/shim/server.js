/**
 * T016 — thin HTTP proxy in front of `notebooklm-mcp-server`.
 *
 * The upstream server (github.com/moodRobotics/notebooklm-mcp-server) is a
 * stdio-only MCP server — it's designed to be spawned directly by an MCP
 * client (Claude Desktop, Cursor, etc.), not run as a network service. Our
 * backend lives in a separate container (so the heavy Chromium/Node runtime
 * needed for the Google-login dance stays out of the `api`/`worker` images),
 * so this shim spawns the real server as a child process, speaks MCP to it
 * over stdio using the official SDK, and re-exposes exactly the handful of
 * tool calls our provider needs as plain HTTP/JSON — matching the
 * `MCP_ENDPOINT` wiring `mcp/README.md` already anticipated.
 *
 * This is a generic proxy (`POST /call`), not a bespoke endpoint per tool:
 * the Python side (`app/pipeline/notebooklm_mcp.py`) knows the exact tool
 * names/argument shapes from the upstream `docs/TOOLS.md`.
 *
 * NOT YET LIVE-VERIFIED: the exact shape `callTool()` returns for each of
 * these specific tools (structuredContent vs. a text-JSON content block) is
 * inferred from the general MCP tool-result spec, not confirmed against a
 * real authenticated session. `unwrapToolResult` (tools.js) defensively handles
 * both shapes; if the real server returns something else, that function is
 * the one place to fix.
 */

import express from "express";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { createArtifact, download, outlineAction, resetSession } from "./studio.js";
import { PathNotAllowed, readySourceIds, sourceStatuses, uploadSource } from "./sources.js";
import { createSession } from "./session.js";
import { ToolError, failStatus } from "./tools.js";

const PORT = process.env.PORT || 7332;
const MCP_PACKAGE = process.env.NOTEBOOKLM_MCP_PACKAGE || "notebooklm-mcp-server@4.0.2";

let lastError = null;
let lastOkAt = null;

// One stdio session with the connector child: calls are serialised, and a child
// that exits is replaced on the next call (session.js).
const session = createSession(async () => {
  const transport = new StdioClientTransport({
    command: "npx",
    args: ["-y", MCP_PACKAGE, "server"],
    env: process.env,
  });
  const c = new Client({ name: "shikshak-dp-mcp-shim", version: "1.0.0" }, { capabilities: {} });
  await c.connect(transport);
  lastError = null;
  return c;
});

async function callTool(name, args) {
  const data = await session.call(name, args);
  lastOkAt = new Date().toISOString();
  return data;
}

const app = express();
app.use(express.json());

// Generic tool proxy — the Python provider names the exact tool + args.
app.post("/call", async (req, res) => {
  const { tool, args } = req.body ?? {};
  if (!tool) return res.status(400).json({ error: "missing 'tool'" });
  try {
    const data = await callTool(tool, args);
    res.json({ data });
  } catch (err) {
    // 422: the connector rejected it (e.g. a private video); 401: sign in again;
    // 502: the child or transport failed (worth a retry)
    lastError = String(err?.message ?? err);
    res.status(failStatus(err)).json({ error: lastError });
  }
});

// Health/auth status: a cheap, always-available tool call proves the
// session is authenticated (no dedicated "whoami" tool is documented). It goes
// through the same serialised session as every other call, so it never
// interleaves with one; while another call is running (up to 300 s) it doesn't
// queue behind it but answers from the last successful call.
const HEALTH_RECENT_MS = 15 * 60 * 1000;
app.get("/health", async (_req, res) => {
  if (session.busy()) {
    const recent = lastOkAt !== null && Date.now() - Date.parse(lastOkAt) < HEALTH_RECENT_MS;
    return res.json({ healthy: recent, last_ok_at: lastOkAt, detail: "busy with another call" });
  }
  try {
    await callTool("notebook_list", {});
    res.json({ healthy: true, last_ok_at: lastOkAt, detail: "notebook_list ok" });
  } catch (err) {
    res.json({
      healthy: false,
      last_ok_at: lastOkAt,
      detail: String(err?.message ?? err),
    });
  }
});

// Re-run `auth` (interactive Chromium login) has to happen out-of-band via
// `docker compose --profile mcp run --rm mcp npx notebooklm-mcp-server auth`
// (mcp/README.md). This endpoint just forces a fresh connection so a
// server that picks up rotated cookies from a re-auth is used immediately,
// mirroring the upstream `refresh_auth` tool if the running session exposes
// one, without requiring a full container restart.
app.post("/refresh-auth", async (_req, res) => {
  try {
    // Studio/upload requests' rotated cookies and page token belong to the old
    // session: drop them too, or they'd be mixed into the new one's requests.
    resetSession();
    await session.reset();
    await session.connect();
    res.status(204).end();
  } catch (err) {
    lastError = String(err?.message ?? err);
    res.status(502).json({ error: lastError });
  }
});

// Proxies a Studio artifact's binary media (e.g. the audio_overview mp3),
// per `studio_poll`'s `media_url` field.
//
// NOT YET LIVE-VERIFIED: whether `media_url` needs the MCP server's own
// session credentials to fetch (in which case this has to reuse whatever
// cookie jar `notebooklm-mcp-server` holds internally — not currently
// exposed via the MCP tool interface, so this may need an upstream feature
// request or a different retrieval path) or is a short-lived signed URL
// fetchable with a plain unauthenticated GET. This implementation assumes
// the latter until proven otherwise.
app.get("/media", async (req, res) => {
  const { notebook_id: notebookId, artifact_id: artifactId } = req.query;
  if (!notebookId || !artifactId) {
    return res.status(400).json({ error: "missing notebook_id or artifact_id" });
  }
  try {
    const poll = await callTool("studio_poll", { notebook_id: notebookId });
    const artifact = (poll.artifacts ?? []).find((a) => a.artifact_id === artifactId);
    if (!artifact?.media_url) {
      return res.status(404).json({ error: "no media_url for this artifact" });
    }
    const upstream = await fetch(artifact.media_url);
    if (!upstream.ok) {
      return res.status(502).json({ error: `media fetch failed: ${upstream.status}` });
    }
    res.setHeader(
      "Content-Type",
      upstream.headers.get("content-type") || "application/octet-stream",
    );
    const buf = Buffer.from(await upstream.arrayBuffer());
    res.send(buf);
  } catch (err) {
    res.status(502).json({ error: String(err?.message ?? err) });
  }
});

// -- Studio, in the web app's current request format (studio.js) -------------

// 401 = the Google session needs attention; 422 = NotebookLM rejected the
// request itself (retrying won't help); 502 = anything else (worth a retry).
// `pollable`: a connector tool error while polling a Studio artifact may just mean
// "not there yet", so it stays 502 (the backend keeps polling until its deadline).
function studioFail(res, err, { pollable = false } = {}) {
  lastError = String(err?.message ?? err);
  let status = failStatus(err);
  if (pollable && err instanceof ToolError && status === 422) status = 502;
  res.status(status).json({ error: lastError });
}

// studio_poll's status strings → NotebookLM's codes (connector's mapping).
const STATUS_CODES = { pending: 1, in_progress: 2, completed: 3, failed: 4 };

app.post("/studio/create", async (req, res) => {
  const { notebook_id: notebookId, kind, focus_prompt: focus, options } = req.body ?? {};
  try {
    const ids = await readySourceIds(notebookId);
    const artifactId = await createArtifact(notebookId, ids, kind, focus ?? "", options ?? {});
    lastOkAt = new Date().toISOString();
    res.json({ artifact_id: artifactId });
  } catch (err) {
    studioFail(res, err);
  }
});

// Slide outline review: {feedback} revises the outline, no feedback builds the deck.
app.post("/studio/outline", async (req, res) => {
  const { notebook_id: notebookId, artifact_id: artifactId, feedback } = req.body ?? {};
  try {
    await outlineAction(notebookId, artifactId, feedback || null);
    res.status(204).end();
  } catch (err) {
    studioFail(res, err);
  }
});

// Status + content of one artifact: {status, raw, html}. status is NotebookLM's
// code (3 = completed, 6 = outline waiting for review), or null if not found.
app.get("/studio/artifact", async (req, res) => {
  const { notebook_id: notebookId, artifact_id: artifactId } = req.query;
  try {
    const data = await callTool("artifact_content_get", { notebook_id: notebookId, artifact_id: artifactId });
    const row = Array.isArray(data?.raw) ? data.raw[0] : null;
    let status = row ? row[4] ?? null : null;
    if (status === null) {
      // Flashcards/quiz come back as html with no row; studio_poll has their status.
      const poll = await callTool("studio_poll", { notebook_id: notebookId });
      const listed = (poll.artifacts ?? []).find((a) => a.artifact_id === artifactId);
      status = listed ? (STATUS_CODES[listed.status] ?? null) : null;
    }
    res.json({ status, raw: row, html: data?.html ?? null });
  } catch (err) {
    studioFail(res, err, { pollable: true });
  }
});

// Media behind NotebookLM URLs (slide PNG/PDF/PPTX, infographic PNG, audio).
app.get("/studio/download", async (req, res) => {
  try {
    const { type, data } = await download(String(req.query.url ?? ""));
    res.setHeader("Content-Type", type);
    res.send(data);
  } catch (err) {
    studioFail(res, err);
  }
});

// Add a file from the shared media volume as a source: {notebook_id, path, name}.
app.post("/source/upload", async (req, res) => {
  const { notebook_id: notebookId, path: filePath, name } = req.body ?? {};
  if (!notebookId || !filePath || !name) {
    return res.status(400).json({ error: "missing notebook_id, path or name" });
  }
  try {
    const sourceId = await uploadSource(notebookId, filePath, name);
    lastOkAt = new Date().toISOString();
    res.json({ source_id: sourceId });
  } catch (err) {
    if (err instanceof PathNotAllowed) return res.status(400).json({ error: err.message });
    studioFail(res, err);
  }
});

// Per-source readiness: {sources: [{id, title, status: pending | ready | failed}]}.
app.get("/source/status", async (req, res) => {
  try {
    const sources = await sourceStatuses(String(req.query.notebook_id ?? ""));
    lastOkAt = new Date().toISOString();
    res.json({ sources });
  } catch (err) {
    studioFail(res, err);
  }
});

const server = app.listen(PORT, () => {
  console.log(`notebooklm-mcp shim listening on :${PORT} (package ${MCP_PACKAGE})`);
});

// Stop cleanly: no new requests, close the connector child (no orphaned npx/Chromium).
async function shutdown(signal) {
  console.log(`${signal}: closing`);
  server.close();
  await Promise.race([session.close(), new Promise((r) => setTimeout(r, 5000))]);
  process.exit(0);
}
process.on("SIGTERM", () => shutdown("SIGTERM"));
process.on("SIGINT", () => shutdown("SIGINT"));
