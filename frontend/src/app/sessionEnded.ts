import type { QueryClient } from "@tanstack/react-query";
import { dropUserData } from "@/lib/sessionCache";
import { sessionEndedTarget } from "./csrfRecovery";

type Navigate = (
  to: string,
  opts: { replace: boolean; state: { from?: string; notice?: string } },
) => unknown;

/**
 * A request of the signed-in area came back 401 (decision 3, 2026-10-29): the
 * session ended — idle or absolute expiry, a password reset on another device,
 * the account deactivated. Go to that area's login page with "Session ended —
 * please sign in again" and the way back, then forget the user's data so no
 * poll or retry keeps firing at the API. The login page is reached before the
 * session is cleared, so the guard doesn't redirect first without the notice.
 */
export function handleSessionEnded(
  apiPath: string,
  location: { pathname: string; search: string },
  navigate: Navigate,
  qc: QueryClient,
): void {
  const target = sessionEndedTarget(apiPath, location.pathname, location.search);
  if (!target) return;
  void navigate(target.to, { replace: true, state: target.state });
  dropUserData(qc);
  qc.setQueryData([apiPath.startsWith("/api/admin/") ? "admin" : "student", "session"], null);
}
