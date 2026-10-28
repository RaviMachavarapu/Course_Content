import { useEffect } from "react";
import { RouterProvider } from "react-router-dom";
import { setCsrfFailureHandler } from "@/lib/api";
import { csrfRecoveryTarget } from "./csrfRecovery";
import { AppProviders } from "./providers";
import { router } from "./router";

export function App(): JSX.Element {
  // A mutation rejected with 403 csrf_failed means the CSRF cookie is gone
  // (only login re-issues it): send the user to sign in again, with a notice,
  // instead of leaving the action to fail silently.
  useEffect(() => {
    setCsrfFailureHandler((apiPath) => {
      const target = csrfRecoveryTarget(apiPath, router.state.location.pathname);
      if (target) void router.navigate(target.to, { replace: true, state: target.state });
    });
    return () => setCsrfFailureHandler(null);
  }, []);

  return (
    <AppProviders>
      <RouterProvider router={router} />
    </AppProviders>
  );
}
