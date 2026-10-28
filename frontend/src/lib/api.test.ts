import { ApiError, apiFetch, errorMessage, setCsrfFailureHandler } from "./api";

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
