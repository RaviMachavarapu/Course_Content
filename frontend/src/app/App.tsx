import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { RouterProvider } from "react-router-dom";
import { setCsrfFailureHandler, setSessionEndedHandler } from "@/lib/api";
import { csrfRecoveryTarget } from "./csrfRecovery";
import { AppProviders } from "./providers";
import { router } from "./router";
import { handleSessionEnded } from "./sessionEnded";

/** Sends the user to sign in again, with a notice and the way back, when the
 * server says the session is over: a 401 from any request of the signed-in
 * area (query, mutation or poll), or a 403 `csrf_failed` that refreshing the
 * token through `/auth/me` couldn't fix. */
function SessionRecovery(): null {
  const qc = useQueryClient();
  useEffect(() => {
    setCsrfFailureHandler((apiPath) => {
      const { pathname, search } = router.state.location;
      const target = csrfRecoveryTarget(apiPath, pathname, search);
      if (target) void router.navigate(target.to, { replace: true, state: target.state });
    });
    setSessionEndedHandler((apiPath) =>
      handleSessionEnded(
        apiPath,
        router.state.location,
        (to, opts) => router.navigate(to, opts),
        qc,
      ),
    );
    return () => {
      setCsrfFailureHandler(null);
      setSessionEndedHandler(null);
    };
  }, [qc]);
  return null;
}

export function App(): JSX.Element {
  return (
    <AppProviders>
      <SessionRecovery />
      <RouterProvider router={router} />
    </AppProviders>
  );
}
