/**
 * Sentry (T043) — no-op unless `VITE_SENTRY_DSN` is set, so dev/CI never
 * depend on it. Call once, before the app renders.
 */
import * as Sentry from "@sentry/react";

export function initTelemetry(): void {
  const dsn = import.meta.env.VITE_SENTRY_DSN as string | undefined;
  if (!dsn) return;
  Sentry.init({ dsn, tracesSampleRate: 0 });
}
