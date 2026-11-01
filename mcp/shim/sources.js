/**
 * Add a file to a notebook and report source readiness, using the requests the
 * NotebookLM web app sends (captured live 2026-10-26; see
 * docs/superpowers/specs/2026-10-26-pdf-sources-design.md section 3).
 *
 * Upload: register the source (batchexecute o4cbdc), open a Google resumable
 * upload session, then send the bytes in 1 MB pieces, the last with finalize.
 */

import fs from "node:fs";
import path from "node:path";
import { ORIGIN, UA, StudioError, cookieHeader, remember, rpc, transientHttp } from "./studio.js";

const PIECE = 1048576;
const UPLOAD_URL = `${ORIGIN}/upload/_/?authuser=0`;
// The backend's media volume (mounted read-only here); nothing else may be uploaded.
const MEDIA_ROOT = "/data/media";
const SOURCE_OPTIONS = [2, null, [1], [1, null, null, null, null, null, null, null, null, null, [1, 3]]];

function uploadHeaders(extra) {
  return {
    Cookie: cookieHeader("notebook.google.com"),
    "User-Agent": UA,
    Origin: ORIGIN,
    Referer: `${ORIGIN}/`,
    ...extra,
  };
}

// 401/403 = session problem; 5xx and 429 = worth a retry (plain Error -> 502);
// anything else was rejected for good (StudioError -> 422).
function failUpload(step, res) {
  const msg = `NotebookLM upload ${step} failed (HTTP ${res.status})`;
  if (res.status === 401 || res.status === 403) return new StudioError(msg, { auth: true });
  if (transientHttp(res.status)) return new Error(msg);
  return new StudioError(msg);
}

/** A path outside the media volume or not a .pdf: the route answers 400. */
export class PathNotAllowed extends Error {
  constructor() {
    super("path not allowed");
  }
}

export async function uploadSource(notebookId, filePath, name, { root = MEDIA_ROOT } = {}) {
  // Checked before anything is sent to NotebookLM: the shim's port must not be a
  // way to upload other files in this container (auth.json holds the session).
  const resolved = path.resolve(String(filePath));
  if (!path.isAbsolute(String(filePath)) || !resolved.startsWith(`${root}/`) || !/\.pdf$/i.test(resolved)) {
    throw new PathNotAllowed();
  }
  // Symlinks are resolved too: a link (or linked folder) under the root must not
  // lead outside it. The final open refuses a symlink swapped in meanwhile.
  try {
    const rootReal = await fs.promises.realpath(root);
    filePath = await fs.promises.realpath(resolved);
    if (!filePath.startsWith(`${rootReal}/`) || !/\.pdf$/i.test(filePath)) throw new PathNotAllowed();
  } catch (err) {
    if (err instanceof PathNotAllowed) throw err;
    throw new StudioError(`cannot read ${resolved}: ${err.code ?? err.message}`);
  }
  // Open first: a missing or unreadable file must fail before a source is
  // registered, or NotebookLM keeps an orphan stuck in "pending".
  let file;
  try {
    file = await fs.promises.open(filePath, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW);
  } catch (err) {
    throw new StudioError(`cannot read ${filePath}: ${err.code ?? err.message}`);
  }
  let sourceId;
  try {
    const registered = await rpc("o4cbdc", [[[name, 3]], notebookId, SOURCE_OPTIONS], `/notebook/${notebookId}`);
    sourceId = registered?.[0]?.[0]?.[0]?.[0];
    if (!sourceId) throw new StudioError("NotebookLM did not return a source id for the upload");
    const size = (await file.stat()).size;

    const started = await fetch(UPLOAD_URL, {
      method: "POST",
      headers: uploadHeaders({
        "x-goog-upload-command": "start",
        "x-goog-upload-header-content-length": String(size),
        "x-goog-upload-protocol": "resumable",
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
      }),
      body: JSON.stringify({ PROJECT_ID: notebookId, SOURCE_NAME: name, SOURCE_ID: sourceId }),
    });
    remember(started);
    if (!started.ok) throw failUpload("start", started);
    const sessionUrl = started.headers.get("x-goog-upload-url");
    if (!sessionUrl) throw new StudioError("NotebookLM did not open an upload session");

    let offset = 0;
    do {
      const len = Math.min(PIECE, size - offset);
      const piece = Buffer.alloc(len);
      let got = 0;
      while (got < len) {
        const { bytesRead } = await file.read(piece, got, len - got, offset + got);
        if (!bytesRead) throw new StudioError(`${filePath} ended early while uploading`);
        got += bytesRead;
      }
      const last = offset + len >= size;
      const res = await fetch(sessionUrl, {
        method: "POST",
        headers: uploadHeaders({
          "x-goog-upload-command": last ? "upload, finalize" : "upload",
          "x-goog-upload-offset": String(offset),
        }),
        body: piece,
      });
      remember(res);
      if (!res.ok) throw failUpload("send", res);
      if (last && res.headers.get("x-goog-upload-status") !== "final") {
        throw new StudioError("NotebookLM did not confirm the upload (x-goog-upload-status was not final)");
      }
      offset += len;
    } while (offset < size);
  } catch (err) {
    // Registered but not uploaded: NotebookLM would keep it "pending" for good (and
    // count it toward the notebook's source cap). Best effort; the upload's own error
    // is what the caller sees. NOT LIVE-VERIFIED: params are the connector's own
    // source_delete request (notebooklm-mcp-server 4.0.2 deleteSource).
    if (sourceId) await deleteSource(notebookId, sourceId);
    throw err;
  } finally {
    await file.close();
  }
  return sourceId;
}

async function deleteSource(notebookId, sourceId) {
  try {
    await rpc("tGMBJ", [[[sourceId]], [2]], `/notebook/${notebookId}`);
  } catch (err) {
    console.warn(`could not delete the half-uploaded source ${sourceId}: ${err?.message ?? err}`);
  }
}

// [null, N] in a source row: 2 = ready, 1 / 5 = still processing, else failed.
function statusOf(code) {
  if (code === 2) return "ready";
  if (code === 1 || code === 5) return "pending";
  return "failed";
}

const KNOWN_CODES = new Set([1, 2, 5]);

export async function sourceStatuses(notebookId) {
  const result = await rpc(
    "rLM1Ne",
    [notebookId, null, SOURCE_OPTIONS, null, 1, [[null, null, []]]],
    `/notebook/${notebookId}`,
  );
  const rows = (result?.[0]?.[1] ?? []).map((s) => ({ id: s[0]?.[0], title: s[1], code: s[3]?.[1] }));
  const unknown = rows.filter((r) => !KNOWN_CODES.has(r.code));
  if (unknown.length) {
    // still reported as failed, but a new NotebookLM code should show up in the logs
    console.warn(`unknown source status codes (treated as failed): ${unknown.map((r) => `${r.id}=${r.code}`).join(", ")}`);
  }
  return rows.map(({ id, title, code }) => ({ id, title, status: statusOf(code) }));
}

/** The source isn't one NotebookLM reports as failed: the route answers 409. */
export class SourceNotFailed extends Error {
  constructor(sourceId, status) {
    super(`source ${sourceId} is ${status}, not failed: not deleted`);
  }
}

/**
 * Delete a source NotebookLM failed to process, so the backend's re-upload doesn't
 * sit beside it (owner decision 2026-10-31). Only a source this notebook lists as
 * failed is deleted; one it no longer lists is already gone ({deleted: false}).
 * NOT LIVE-VERIFIED: the delete is the connector's own source_delete request
 * (notebooklm-mcp-server 4.0.2 deleteSource), as in the upload cleanup above.
 */
export async function deleteFailedSource(notebookId, sourceId) {
  const row = (await sourceStatuses(notebookId)).find((s) => s.id === sourceId);
  if (!row) return { deleted: false };
  if (row.status !== "failed") throw new SourceNotFailed(sourceId, row.status);
  await rpc("tGMBJ", [[[sourceId]], [2]], `/notebook/${notebookId}`);
  return { deleted: true };
}

/** Ids of the sources NotebookLM has finished processing; Studio may use only these. */
export async function readySourceIds(notebookId) {
  const ids = (await sourceStatuses(notebookId)).filter((s) => s.status === "ready").map((s) => s.id);
  if (!ids.length) throw new StudioError(`notebook ${notebookId} has no ready sources`);
  return ids;
}
