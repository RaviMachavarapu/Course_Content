import {
  apiFetch,
  ApiError,
  readCookie,
  refreshCsrfToken,
  reportCsrfFailure,
  reportSessionEnded,
  SESSION_ENDED_MESSAGE,
  SESSION_EXPIRED_MESSAGE,
} from "@/lib/api";

const RETRY_DELAYS_MS = [1000, 2000, 4000];

interface UploadStarted {
  upload_id: string;
  chunk_size: number;
}

function abortError(): Error {
  return new DOMException("Upload cancelled", "AbortError");
}

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(abortError());
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    const onAbort = () => {
      clearTimeout(timer);
      reject(abortError());
    };
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

type ChunkResult =
  | { kind: "ok"; received: number }
  | { kind: "resume"; received: number }
  | { kind: "retry"; error: Error };

/** One PUT. Raw fetch: the body is binary, which `apiFetch` (JSON only) can't send. */
async function putChunk(
  uploadId: string,
  offset: number,
  body: Blob,
  signal?: AbortSignal,
  csrfRetried = false,
): Promise<ChunkResult> {
  const headers: Record<string, string> = { "Content-Type": "application/octet-stream" };
  const csrf = readCookie("sdp_csrf");
  if (csrf) headers["X-CSRF-Token"] = decodeURIComponent(csrf);

  let res: Response;
  try {
    res = await fetch(`/api/admin/uploads/${uploadId}?offset=${offset}`, {
      method: "PUT",
      headers,
      credentials: "include",
      signal,
      body,
    });
  } catch (err) {
    if (signal?.aborted) throw abortError();
    return { kind: "retry", error: err instanceof Error ? err : new Error("Network error") };
  }

  const data = (await res.json().catch(() => null)) as {
    received_bytes?: number;
    code?: string;
    error?: { code?: string; message?: string };
  } | null;

  if (res.ok) return { kind: "ok", received: data?.received_bytes ?? offset + body.size };
  if (res.status === 409 && data?.code === "offset_mismatch" && data.received_bytes !== undefined) {
    return { kind: "resume", received: data.received_bytes };
  }
  if (res.status >= 500) {
    return { kind: "retry", error: new Error(`Upload failed (${res.status})`) };
  }
  if (res.status === 401) {
    const path = `/api/admin/uploads/${uploadId}`;
    reportSessionEnded(path);
    throw new ApiError(401, "unauthorized", SESSION_ENDED_MESSAGE);
  }
  if (res.status === 403 && data?.error?.code === "csrf_failed") {
    const path = `/api/admin/uploads/${uploadId}`;
    // rejected before it ran: refresh the token via /me and resend once
    if (!csrfRetried && (await refreshCsrfToken(path, signal))) {
      return putChunk(uploadId, offset, body, signal, true);
    }
    reportCsrfFailure(path);
    throw new ApiError(403, "csrf_failed", SESSION_EXPIRED_MESSAGE);
  }
  throw new ApiError(
    res.status,
    data?.error?.code ?? "error",
    data?.error?.message ?? `Upload failed (${res.status})`,
  );
}

/** True when the server already holds the whole file. Used when the final
 * chunk's response was lost: the chunk may have been committed even though we
 * saw a network error, a 5xx, or (on the retry) 409 `not_receiving`. */
async function isComplete(uploadId: string, total: number, signal?: AbortSignal): Promise<boolean> {
  try {
    const s = await apiFetch<{ received_bytes: number; status: string }>(
      `/api/admin/uploads/${uploadId}`,
      { signal },
    );
    return s.status === "complete" && s.received_bytes === total;
  } catch {
    if (signal?.aborted) throw abortError();
    return false;
  }
}

/**
 * Resumable chunked upload. Resolves to the server's upload id once every byte
 * is accepted (and the server has checked the file really is a PDF).
 */
export async function uploadPdf(
  file: File,
  onProgress: (sent: number, total: number) => void,
  signal?: AbortSignal,
): Promise<string> {
  const total = file.size;
  const started = await apiFetch<UploadStarted>("/api/admin/uploads", {
    method: "POST",
    body: { file_name: file.name, size_bytes: total },
    signal,
  });
  const chunkSize = started.chunk_size;
  onProgress(0, total);

  let offset = 0;
  while (offset < total) {
    const slice = file.slice(offset, Math.min(offset + chunkSize, total));
    const isFinal = offset + slice.size >= total;
    let attempt = 0;
    for (;;) {
      let result: ChunkResult;
      try {
        result = await putChunk(started.upload_id, offset, slice, signal);
      } catch (err) {
        if (
          isFinal &&
          err instanceof ApiError &&
          err.code === "not_receiving" &&
          (await isComplete(started.upload_id, total, signal))
        ) {
          result = { kind: "ok", received: total };
        } else {
          throw err;
        }
      }
      if (result.kind === "retry") {
        const delay = RETRY_DELAYS_MS[attempt++];
        if (delay === undefined) {
          if (isFinal && (await isComplete(started.upload_id, total, signal))) {
            offset = total;
            break;
          }
          throw result.error;
        }
        await sleep(delay, signal);
        continue;
      }
      offset = result.received;
      break;
    }
    onProgress(offset, total);
  }
  return started.upload_id;
}
