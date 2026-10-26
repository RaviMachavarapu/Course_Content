import { apiFetch, ApiError, readCookie } from "@/lib/api";

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
  throw new ApiError(
    res.status,
    data?.error?.code ?? "error",
    data?.error?.message ?? `Upload failed (${res.status})`,
  );
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
    let attempt = 0;
    for (;;) {
      const result = await putChunk(started.upload_id, offset, slice, signal);
      if (result.kind === "retry") {
        const delay = RETRY_DELAYS_MS[attempt++];
        if (delay === undefined) throw result.error;
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
