import type { QueryClient } from "@tanstack/react-query";
import { ApiError } from "./api";
import { useUIStore } from "./store";

function isSessionKey(key: readonly unknown[]): boolean {
  return key.length === 2 && (key[0] === "student" || key[0] === "admin") && key[1] === "session";
}

/** Drop every cached query that belongs to a signed-in user (keeps the session
 * entries). Query keys aren't user-scoped, so the next user on this tab would
 * otherwise be served the previous user's catalog, progress and positions. */
export function dropUserData(qc: QueryClient): void {
  qc.removeQueries({ predicate: (q) => !isSessionKey(q.queryKey) });
}

export const LOGOUT_TOKEN_EXPIRED_MESSAGE =
  "We couldn’t log you out because your session token expired. Sign in again, then log out.";

/** Tell the user a logout didn't go through: the server session may still be
 * live, so we don't pretend they are signed out. */
export function reportLogoutFailure(err: unknown): void {
  const description =
    err instanceof ApiError && err.code === "csrf_failed"
      ? LOGOUT_TOKEN_EXPIRED_MESSAGE
      : `${err instanceof ApiError ? err.message : "The request failed."} You’re still signed in on this device — try again.`;
  useUIStore.getState().pushToast({ tone: "error", title: "Couldn’t log out", description });
}
