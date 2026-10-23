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
 * real authenticated session. `unwrapToolResult` below defensively handles
 * both shapes; if the real server returns something else, that function is
 * the one place to fix.
 */

import express from "express";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { StudioError, createArtifact, download, outlineAction } from "./studio.js";

const PORT = process.env.PORT || 7332;
const MCP_PACKAGE = process.env.NOTEBOOKLM_MCP_PACKAGE || "notebooklm-mcp-server@4.0.2";

let client = null;
let connecting = null;
let lastError = null;
let lastOkAt = null;

function unwrapToolResult(result) {
  if (result && result.structuredContent !== undefined) return result.structuredContent;
  if (result && Array.isArray(result.content)) {
    const textBlock = result.content.find((c) => c.type === "text");
    if (textBlock) {
      try {
        return JSON.parse(textBlock.text);
      } catch {
        return { text: textBlock.text };
      }
    }
  }
  return result;
}

async function getClient() {
  if (client) return client;
  if (connecting) return connecting;

  connecting = (async () => {
    const transport = new StdioClientTransport({
      command: "npx",
      args: ["-y", MCP_PACKAGE, "server"],
      env: process.env,
    });
    const c = new Client({ name: "shikshak-dp-mcp-shim", version: "1.0.0" }, { capabilities: {} });
    await c.connect(transport);
    client = c;
    lastError = null;
    return c;
  })();

  try {
    return await connecting;
  } finally {
    connecting = null;
  }
}

async function callTool(name, args) {
  const c = await getClient();
  const result = await c.callTool({ name, arguments: args ?? {} });
  if (result?.isError) {
    throw new Error(`tool ${name} failed: ${JSON.stringify(result.content ?? result)}`);
  }
  lastOkAt = new Date().toISOString();
  return unwrapToolResult(result);
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
    lastError = String(err?.message ?? err);
    res.status(502).json({ error: lastError });
  }
});

// Health/auth status: a cheap, always-available tool call proves the
// session is authenticated (no dedicated "whoami" tool is documented).
app.get("/health", async (_req, res) => {
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
    if (client) {
      await client.close().catch(() => {});
      client = null;
    }
    await getClient();
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
function studioFail(res, err) {
  lastError = String(err?.message ?? err);
  const status = err instanceof StudioError ? (err.auth ? 401 : 422) : 502;
  res.status(status).json({ error: lastError });
}

// studio_poll's status strings → NotebookLM's codes (connector's mapping).
const STATUS_CODES = { pending: 1, in_progress: 2, completed: 3, failed: 4 };

async function sourceIds(notebookId) {
  const nb = await callTool("notebook_get", { notebook_id: notebookId });
  const ids = (nb.sources ?? []).map((s) => s.id).filter(Boolean);
  if (!ids.length) throw new StudioError(`notebook ${notebookId} has no sources`);
  return ids;
}

app.post("/studio/create", async (req, res) => {
  const { notebook_id: notebookId, kind, focus_prompt: focus, options } = req.body ?? {};
  try {
    const ids = await sourceIds(notebookId);
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
    studioFail(res, err);
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

app.listen(PORT, () => {
  console.log(`notebooklm-mcp shim listening on :${PORT} (package ${MCP_PACKAGE})`);
});
