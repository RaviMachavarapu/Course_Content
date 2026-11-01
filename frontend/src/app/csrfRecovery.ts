import { SESSION_ENDED_MESSAGE, SESSION_EXPIRED_MESSAGE } from "@/lib/api";
import { LOGOUT_TOKEN_EXPIRED_MESSAGE } from "@/lib/sessionCache";

export interface LoginRedirectState {
  from?: string;
  notice?: string;
}

const LOGIN_PAGES = new Set(["/login", "/admin/login"]);

type LoginTarget = { to: string; state: LoginRedirectState };

/**
 * Where to send the user after the server rejected a mutation with
 * `403 csrf_failed` and refreshing the token through `/auth/me` failed: sign
 * in again; `from` (path and query) brings them back to the page they were on.
 */
export function csrfRecoveryTarget(
  apiPath: string,
  currentPath: string,
  search = "",
): LoginTarget | null {
  if (LOGIN_PAGES.has(currentPath)) return null;
  const to = apiPath.startsWith("/api/admin") ? "/admin/login" : "/login";
  if (apiPath.endsWith("/logout")) {
    return { to, state: { notice: LOGOUT_TOKEN_EXPIRED_MESSAGE } };
  }
  return { to, state: { from: currentPath + search, notice: SESSION_EXPIRED_MESSAGE } };
}

function isAdminPath(path: string): boolean {
  return path === "/admin" || path.startsWith("/admin/");
}

/**
 * Where to send the user when a request of their area came back 401 (the
 * session ended: expiry, a reset elsewhere, deactivation). A 401 from the other
 * area's API (admin and student sessions are independent) changes nothing.
 */
export function sessionEndedTarget(
  apiPath: string,
  currentPath: string,
  search: string,
): LoginTarget | null {
  if (LOGIN_PAGES.has(currentPath)) return null;
  const adminApi = apiPath.startsWith("/api/admin/");
  if (adminApi !== isAdminPath(currentPath)) return null;
  return {
    to: adminApi ? "/admin/login" : "/login",
    state: { from: currentPath + search, notice: SESSION_ENDED_MESSAGE },
  };
}

/** Only follow same-app paths from `state.from` (no `//host` open redirects). */
export function safeFrom(from: unknown, fallback: string, area: "admin" | "student"): string {
  if (typeof from !== "string" || !from.startsWith("/") || from.startsWith("//")) return fallback;
  const pathOnly = from.split(/[?#]/)[0] ?? from;
  if ((area === "admin") !== isAdminPath(pathOnly) || LOGIN_PAGES.has(pathOnly)) return fallback;
  return from;
}
