import { ApiError, apiFetch, authErrorMessage, errorMessage, setCsrfFailureHandler } from "./api";

afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfFailureHandler(null);
  document.cookie = "sdp_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/";
});

function respond(status: number, body: unknown) {
  const fn = vi.fn((_input: string, _init?: RequestInit) =>
    Promise.resolve({
      ok: status < 300,
      status,
      statusText: String(status),
      json: () => Promise.resolve(body),
    } as Response),
  );
  vi.stubGlobal("fetch", fn);
  return fn;
}

describe("apiFetch", () => {
  it("sends X-CSRF-Token on student mutations", async () => {
    document.cookie = "sdp_csrf=tok%2B1; path=/";
    const fn = respond(200, {});
    await apiFetch("/api/student/artifacts/a/progress", { method: "PUT", body: {} });
    const init = fn.mock.calls[0]![1] as RequestInit;
    expect((init.headers as Record<string, string>)["X-CSRF-Token"]).toBe("tok+1");
  });

  it("does not send the token on GET", async () => {
    document.cookie = "sdp_csrf=tok; path=/";
    const fn = respond(200, {});
    await apiFetch("/api/student/catalog");
    const init = fn.mock.calls[0]![1] as RequestInit;
    expect((init.headers as Record<string, string>)["X-CSRF-Token"]).toBeUndefined();
  });

  it("reports a 403 csrf_failed to the handler with a session-expired message", async () => {
    respond(403, { error: { code: "csrf_failed", message: "Missing or invalid CSRF token" } });
    const handler = vi.fn();
    setCsrfFailureHandler(handler);
    const err = await apiFetch("/api/admin/modules", { method: "POST", body: {} }).catch(
      (e: unknown) => e,
    );
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).code).toBe("csrf_failed");
    expect((err as ApiError).message).toMatch(/session has expired/i);
    expect(handler).toHaveBeenCalledWith("/api/admin/modules");
  });

  it("leaves other 403s alone", async () => {
    respond(403, { error: { code: "forbidden", message: "Nope" } });
    const handler = vi.fn();
    setCsrfFailureHandler(handler);
    await expect(apiFetch("/api/admin/x", { method: "POST" })).rejects.toThrow("Nope");
    expect(handler).not.toHaveBeenCalled();
  });
});

describe("errorMessage", () => {
  it("prefers the first field detail of a validation error", () => {
    const err = new ApiError(422, "validation_error", "Request body failed validation", [
      { loc: ["body", "options", "language"], msg: "Input should be 'en'" },
    ]);
    expect(errorMessage(err)).toBe("options.language: Input should be 'en'");
  });
  it("falls back to the server message, then the default", () => {
    expect(errorMessage(new ApiError(409, "conflict", "Busy"))).toBe("Busy");
    expect(errorMessage(new Error("x"), "Nope")).toBe("Nope");
  });
});

type Reply = { status: number; body?: unknown; setCookie?: string };

function sequence(replies: Reply[]) {
  const queue = [...replies];
  const fn = vi.fn((_input: string, _init?: RequestInit) => {
    const r = queue.shift() ?? {
      status: 500,
      body: { error: { code: "x", message: "unexpected" } },
    };
    if (r.setCookie) document.cookie = r.setCookie;
    return Promise.resolve({
      ok: r.status < 300,
      status: r.status,
      statusText: String(r.status),
      json: () => Promise.resolve(r.body ?? null),
    } as Response);
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

const CSRF_403: Reply = {
  status: 403,
  body: { error: { code: "csrf_failed", message: "Missing or invalid CSRF token" } },
};

describe("apiFetch CSRF recovery", () => {
  it("refreshes the token via the area's /me and retries the request once", async () => {
    const handler = vi.fn();
    setCsrfFailureHandler(handler);
    const fn = sequence([
      CSRF_403,
      { status: 200, body: { user: {} }, setCookie: "sdp_csrf=fresh; path=/" },
      { status: 201, body: { ok: true } },
    ]);
    await expect(apiFetch("/api/admin/modules", { method: "POST", body: {} })).resolves.toEqual({
      ok: true,
    });
    expect(fn.mock.calls.map((c) => [c[0], c[1]?.method])).toEqual([
      ["/api/admin/modules", "POST"],
      ["/api/admin/auth/me", "GET"],
      ["/api/admin/modules", "POST"],
    ]);
    const retried = fn.mock.calls[2]![1]!.headers as Record<string, string>;
    expect(retried["X-CSRF-Token"]).toBe("fresh");
    expect(handler).not.toHaveBeenCalled();
  });

  it("uses the student /me for student requests", async () => {
    const fn = sequence([CSRF_403, { status: 200, body: { user: {} } }, { status: 204 }]);
    await apiFetch("/api/student/artifacts/a/progress", { method: "PUT", body: {} });
    expect(fn.mock.calls[1]![0]).toBe("/api/student/auth/me");
  });

  it("falls back to 'session expired' when /me says not signed in", async () => {
    const handler = vi.fn();
    setCsrfFailureHandler(handler);
    const fn = sequence([CSRF_403, { status: 401, body: { error: { code: "unauthorized" } } }]);
    await expect(apiFetch("/api/admin/modules", { method: "POST" })).rejects.toThrow(
      /session has expired/i,
    );
    expect(fn).toHaveBeenCalledTimes(2);
    expect(handler).toHaveBeenCalledWith("/api/admin/modules");
  });

  it("retries at most once", async () => {
    const handler = vi.fn();
    setCsrfFailureHandler(handler);
    const fn = sequence([CSRF_403, { status: 200, body: { user: {} } }, CSRF_403]);
    await expect(apiFetch("/api/admin/modules", { method: "POST" })).rejects.toMatchObject({
      code: "csrf_failed",
    });
    expect(fn).toHaveBeenCalledTimes(3);
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("never retries a mutation that failed for another reason", async () => {
    const fn = sequence([{ status: 500, body: { error: { code: "error", message: "boom" } } }]);
    await expect(apiFetch("/api/admin/modules", { method: "POST" })).rejects.toThrow("boom");
    expect(fn).toHaveBeenCalledTimes(1);
  });
});

describe("authErrorMessage", () => {
  it("explains rate limits and a disabled reset", () => {
    expect(authErrorMessage(new ApiError(429, "rate_limited", "x"), "f")).toBe(
      "Too many attempts — please try again later.",
    );
    expect(authErrorMessage(new ApiError(404, "password_reset_disabled", "x"), "f")).toMatch(
      /password reset is turned off/i,
    );
    expect(authErrorMessage(new ApiError(400, "bad", "Server says"), "f")).toBe("Server says");
    expect(authErrorMessage(new Error("x"), "f")).toBe("f");
  });
});
