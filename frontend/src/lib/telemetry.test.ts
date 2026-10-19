import * as Sentry from "@sentry/react";

vi.mock("@sentry/react", () => ({ init: vi.fn() }));

afterEach(() => {
  vi.unstubAllEnvs();
  vi.clearAllMocks();
});

describe("initTelemetry", () => {
  it("does nothing when VITE_SENTRY_DSN is unset", async () => {
    vi.stubEnv("VITE_SENTRY_DSN", "");
    const { initTelemetry } = await import("./telemetry");
    initTelemetry();
    expect(Sentry.init).not.toHaveBeenCalled();
  });

  it("initializes Sentry when VITE_SENTRY_DSN is set", async () => {
    vi.stubEnv("VITE_SENTRY_DSN", "https://example@sentry.io/1");
    vi.resetModules();
    const { initTelemetry } = await import("./telemetry");
    initTelemetry();
    expect(Sentry.init).toHaveBeenCalledWith(
      expect.objectContaining({ dsn: "https://example@sentry.io/1" }),
    );
  });
});
