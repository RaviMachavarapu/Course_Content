/**
 * Add a file to a notebook and report source readiness, using the requests the
 * NotebookLM web app sends (captured live 2026-10-26; see
 * docs/superpowers/specs/2026-10-26-pdf-sources-design.md section 3).
 *
 * Upload: register the source (batchexecute o4cbdc), open a Google resumable
 * upload session, then send the bytes in 1 MB pieces, the last with finalize.
 */

import fs from "node:fs";
import { ORIGIN, UA, StudioError, cookieHeader, remember, rpc } from "./studio.js";

const PIECE = 1048576;
const UPLOAD_URL = `${ORIGIN}/upload/_/?authuser=0`;
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
  if (res.status >= 500 || res.status === 429) return new Error(msg);
  return new StudioError(msg);
}

export async function uploadSource(notebookId, filePath, name) {
  const registered = await rpc("o4cbdc", [[[name, 3]], notebookId, SOURCE_OPTIONS], `/notebook/${notebookId}`);
  const sourceId = registered?.[0]?.[0]?.[0]?.[0];
  if (!sourceId) throw new StudioError("NotebookLM did not return a source id for the upload");

  const file = await fs.promises.open(filePath, "r");
  try {
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
  } finally {
    await file.close();
  }
  return sourceId;
}

// [null, N] in a source row: 2 = ready, 1 / 5 = still processing, else failed.
function statusOf(code) {
  if (code === 2) return "ready";
  if (code === 1 || code === 5) return "pending";
  return "failed";
}

export async function sourceStatuses(notebookId) {
  const result = await rpc(
    "rLM1Ne",
    [notebookId, null, SOURCE_OPTIONS, null, 1, [[null, null, []]]],
    `/notebook/${notebookId}`,
  );
  return (result?.[0]?.[1] ?? []).map((s) => ({ id: s[0]?.[0], title: s[1], status: statusOf(s[3]?.[1]) }));
}
