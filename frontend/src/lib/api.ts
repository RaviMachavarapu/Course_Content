/**
 * Thin fetch wrapper for the JSON API.
 *
 * - always sends cookies (`credentials: "include"`)
 * - mirrors the server's CSRF double-submit: for non-GET requests it copies the
 *   `sdp_csrf` cookie into the `X-CSRF-Token` header
 * - unwraps the `{ error: { code, message } }` envelope into a typed `ApiError`
 * - reports a session that ended (401 outside `/auth/`) and a stale CSRF token
 *   (403 `csrf_failed`, after one refresh-and-resend) to the app, which sends
 *   the user to the right login page
 */

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly fields?: unknown;
  /** Seconds until the server accepts another attempt (429 `retry_after`). */
  readonly retryAfter?: number;

  constructor(
    status: number,
    code: string,
    message: string,
    fields?: unknown,
    retryAfter?: number,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.fields = fields;
    this.retryAfter = retryAfter;
  }
}

const SAFE = new Set(["GET", "HEAD", "OPTIONS"]);

export const SESSION_ENDED_MESSAGE = "Session ended — please sign in again.";
/** Shown on the login page after a completed password reset (owner decision 2026-10-29). */
export const PASSWORD_RESET_DONE_MESSAGE =
  "Your password has been changed and this device is now trusted. Other devices have been signed out. Please sign in with your new password.";
/** The same notice: a CSRF token that can't be refreshed means no session. */
export const SESSION_EXPIRED_MESSAGE = SESSION_ENDED_MESSAGE;

type FailureHandler = (path: string) => void;
let csrfFailureHandler: FailureHandler | null = null;
let sessionEndedHandler: FailureHandler | null = null;

/**
 * Register what happens when the server rejects a mutation with
 * `403 csrf_failed` (the `sdp_csrf` cookie is gone or stale) and refreshing it
 * through `/auth/me` didn't help: the app sends the user to sign in again
 * rather than failing silently.
 */
export function setCsrfFailureHandler(handler: FailureHandler | null): void {
  csrfFailureHandler = handler;
}

/** Shared by `apiFetch` and raw-fetch callers (chunked upload). */
export function reportCsrfFailure(path: string): void {
  csrfFailureHandler?.(path);
}

/**
 * Register what happens when a request is rejected with 401 because the
 * session ended (idle or absolute expiry, a password reset elsewhere, the
 * account deactivated): queries, mutations and polls alike.
 */
export function setSessionEndedHandler(handler: FailureHandler | null): void {
  sessionEndedHandler = handler;
}

/** A 401 from a signed-in area's API. The auth endpoints (`/auth/me`, login,
 * reset…) answer 401 as part of their contract and are left to their callers. */
export function isSessionEnded(status: number, path: string): boolean {
  return status === 401 && /^\/api\/(admin|student)\//.test(path) && !path.includes("/auth/");
}

/** Shared by `apiFetch` and raw-fetch callers (chunked upload). */
export function reportSessionEnded(path: string): void {
  sessionEndedHandler?.(path);
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

type ErrorBody = { code?: string; message?: string; fields?: unknown; retry_after?: unknown };

/** `retry_after` from the error body, else the `Retry-After` header (seconds). */
function retryAfterOf(res: Response, err: ErrorBody | undefined): number | undefined {
  const raw = err?.retry_after ?? res.headers?.get?.("Retry-After");
  const seconds = typeof raw === "number" ? raw : Number(raw);
  return raw != null && Number.isFinite(seconds) && seconds > 0 ? Math.ceil(seconds) : undefined;
}

interface Sent {
  res: Response;
  data: unknown;
}

async function send(path: string, method: string, opts: ApiOptions): Promise<Sent> {
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
  const data: unknown = res.status === 204 ? null : await res.json().catch(() => null);
  return { res, data };
}

function errorOf(data: unknown): ErrorBody | undefined {
  return data && typeof data === "object" && "error" in data
    ? (data as { error: ErrorBody }).error
    : undefined;
}

export function isCsrfFailure(status: number, data: unknown): boolean {
  return status === 403 && errorOf(data)?.code === "csrf_failed";
}

type CsrfRefresh = "refreshed" | "signed_out" | "failed";

async function tryRefreshCsrf(failedPath: string, signal?: AbortSignal): Promise<CsrfRefresh> {
  const area = failedPath.startsWith("/api/admin") ? "admin" : "student";
  try {
    const res = await fetch(`/api/${area}/auth/me`, {
      method: "GET",
      headers: { Accept: "application/json" },
      credentials: "include",
      signal,
    });
    if (res.ok) return "refreshed";
    return res.status === 401 ? "signed_out" : "failed";
  } catch {
    return "failed";
  }
}

/**
 * Ask the server for a fresh `sdp_csrf` cookie: GET `/auth/me` of the area the
 * failed request belongs to re-issues it (as login does). True when still
 * signed in there.
 */
export async function refreshCsrfToken(failedPath: string, signal?: AbortSignal): Promise<boolean> {
  return (await tryRefreshCsrf(failedPath, signal)) === "refreshed";
}

export async function apiFetch<T>(path: string, opts: ApiOptions = {}): Promise<T> {
  const method = (opts.method ?? "GET").toUpperCase();

  let { res, data } = await send(path, method, opts);

  // An expired/missing CSRF token: the server rejected the request before
  // running it, so refreshing the token and sending it again once is safe.
  // Any other failure is never retried.
  if (!SAFE.has(method) && isCsrfFailure(res.status, data)) {
    const refresh = await tryRefreshCsrf(path, opts.signal);
    if (refresh === "refreshed") ({ res, data } = await send(path, method, opts));
    // logging out with neither a session nor a CSRF token left: already out
    else if (refresh === "signed_out" && path.endsWith("/auth/logout")) return undefined as T;
  }

  if (res.status === 204) return undefined as T;

  if (!res.ok) {
    const err = errorOf(data);
    if (isSessionEnded(res.status, path)) {
      reportSessionEnded(path);
      throw new ApiError(401, err?.code ?? "unauthorized", SESSION_ENDED_MESSAGE);
    }
    if (isCsrfFailure(res.status, data)) {
      reportCsrfFailure(path);
      throw new ApiError(403, "csrf_failed", SESSION_EXPIRED_MESSAGE, err?.fields);
    }
    throw new ApiError(
      res.status,
      err?.code ?? "error",
      err?.message ?? res.statusText,
      err?.fields,
      retryAfterOf(res, err),
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

/** `65` → `"1:05"`. */
export function formatCountdown(seconds: number): string {
  const s = Math.max(0, Math.ceil(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** Seconds to wait when `err` is a 429 that says how long (login pages count down). */
export function retryAfterSeconds(err: unknown): number | undefined {
  return err instanceof ApiError && err.status === 429 ? err.retryAfter : undefined;
}

export const RATE_LIMITED_MESSAGE = "Too many attempts — please try again later.";
export const RESET_DISABLED_MESSAGE =
  "Password reset is turned off on this site. Contact your administrator to regain access.";

/** Message for a failed sign-in / register / password-reset request. */
export function authErrorMessage(err: unknown, fallback: string): string {
  if (!(err instanceof ApiError)) return fallback;
  if (err.status === 429) return RATE_LIMITED_MESSAGE;
  if (err.code === "password_reset_disabled") return RESET_DISABLED_MESSAGE;
  return err.message;
}
