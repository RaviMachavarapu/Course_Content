import { SESSION_EXPIRED_MESSAGE } from "@/lib/api";
import { LOGOUT_TOKEN_EXPIRED_MESSAGE } from "@/lib/sessionCache";

export interface LoginRedirectState {
  from?: string;
  notice?: string;
}

const LOGIN_PAGES = new Set(["/login", "/admin/login"]);

/**
 * Where to send the user after the server rejected a mutation with
 * `403 csrf_failed`. Only login re-issues the CSRF cookie, so the way back is
 * to sign in again; `from` brings them back to the page they were on.
 */
export function csrfRecoveryTarget(
  apiPath: string,
  currentPath: string,
): { to: string; state: LoginRedirectState } | null {
  if (LOGIN_PAGES.has(currentPath)) return null;
  const to = apiPath.startsWith("/api/admin") ? "/admin/login" : "/login";
  if (apiPath.endsWith("/logout")) {
    return { to, state: { notice: LOGOUT_TOKEN_EXPIRED_MESSAGE } };
  }
  return { to, state: { from: currentPath, notice: SESSION_EXPIRED_MESSAGE } };
}

/** Only follow same-app paths from `state.from` (no `//host` open redirects). */
export function safeFrom(from: unknown, fallback: string, area: "admin" | "student"): string {
  if (typeof from !== "string" || !from.startsWith("/") || from.startsWith("//")) return fallback;
  const isAdmin = from === "/admin" || from.startsWith("/admin/");
  if ((area === "admin") !== isAdmin || LOGIN_PAGES.has(from)) return fallback;
  return from;
}
