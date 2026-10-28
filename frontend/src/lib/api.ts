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

export const SESSION_EXPIRED_MESSAGE = "Your session has expired — please sign in again.";

type CsrfFailureHandler = (path: string) => void;
let csrfFailureHandler: CsrfFailureHandler | null = null;

/**
 * Register what happens when the server rejects a mutation with
 * `403 csrf_failed` (the `sdp_csrf` cookie is gone or stale). The server has
 * no endpoint that re-issues the token, only login does, so the app sends the
 * user to sign in again rather than failing silently.
 */
export function setCsrfFailureHandler(handler: CsrfFailureHandler | null): void {
  csrfFailureHandler = handler;
}

/** Shared by `apiFetch` and raw-fetch callers (chunked upload). */
export function reportCsrfFailure(path: string): void {
  csrfFailureHandler?.(path);
}

export function readCookie(name: string): string | undefined {
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
    if (res.status === 403 && err?.code === "csrf_failed") {
      reportCsrfFailure(path);
      throw new ApiError(403, "csrf_failed", SESSION_EXPIRED_MESSAGE, err.fields);
    }
    throw new ApiError(
      res.status,
      err?.code ?? "error",
      err?.message ?? res.statusText,
      err?.fields,
    );
  }

  return data as T;
}

/** A user-facing message for a failed request: the server's message plus the
 * first field-level validation detail when there is one (e.g. "note: String
 * should have at most 4000 characters"). */
export function errorMessage(err: unknown, fallback = "The request failed. Try again."): string {
  if (!(err instanceof ApiError)) return fallback;
  const first = Array.isArray(err.fields)
    ? (err.fields[0] as { loc?: unknown[]; msg?: string } | undefined)
    : undefined;
  if (!first?.msg) return err.message;
  const loc = Array.isArray(first.loc) ? first.loc.filter((p) => p !== "body").join(".") : "";
  return loc ? `${loc}: ${first.msg}` : first.msg;
}
