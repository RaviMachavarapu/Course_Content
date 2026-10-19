/**
 * Thin fetch wrapper for the JSON API.
 *
 * - always sends cookies (`credentials: "include"`)
 * - mirrors the server's CSRF double-submit: for non-GET requests it copies the
 *   `sdp_csrf` cookie into the `X-CSRF-Token` header
 * - unwraps the `{ error: { code, message } }` envelope into a typed `ApiError`
 */

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly fields?: unknown;

  constructor(status: number, code: string, message: string, fields?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.fields = fields;
  }
}

const SAFE = new Set(["GET", "HEAD", "OPTIONS"]);

function readCookie(name: string): string | undefined {
  return document.cookie
    .split("; ")
    .find((row) => row.startsWith(`${name}=`))
    ?.split("=")[1];
}

export interface ApiOptions {
  method?: string;
  body?: unknown;
  signal?: AbortSignal;
}

export async function apiFetch<T>(path: string, opts: ApiOptions = {}): Promise<T> {
  const method = (opts.method ?? "GET").toUpperCase();
  const headers: Record<string, string> = { Accept: "application/json" };

  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  if (!SAFE.has(method)) {
    const csrf = readCookie("sdp_csrf");
    if (csrf) headers["X-CSRF-Token"] = decodeURIComponent(csrf);
  }

  const res = await fetch(path, {
    method,
    headers,
    credentials: "include",
    signal: opts.signal,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  });

  if (res.status === 204) return undefined as T;

  const data: unknown = await res.json().catch(() => null);

  if (!res.ok) {
    const err =
      data && typeof data === "object" && "error" in data
        ? (data as { error: { code?: string; message?: string; fields?: unknown } }).error
        : undefined;
    throw new ApiError(
      res.status,
      err?.code ?? "error",
      err?.message ?? res.statusText,
      err?.fields,
    );
  }

  return data as T;
}
