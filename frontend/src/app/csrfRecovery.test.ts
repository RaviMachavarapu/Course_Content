import { csrfRecoveryTarget, sessionEndedTarget } from "./csrfRecovery";

describe("csrfRecoveryTarget", () => {
  it("sends an admin to the admin login, remembering where they were", () => {
    expect(csrfRecoveryTarget("/api/admin/modules", "/admin/ingestion")).toEqual({
      to: "/admin/login",
      state: {
        from: "/admin/ingestion",
        notice: "Session ended — please sign in again.",
      },
    });
  });

  it("sends a student to the student login", () => {
    const t = csrfRecoveryTarget("/api/student/artifacts/a/progress", "/learn/nn/0/slide_deck");
    expect(t?.to).toBe("/login");
    expect(t?.state.from).toBe("/learn/nn/0/slide_deck");
  });

  it("explains that a logout did not go through", () => {
    const t = csrfRecoveryTarget("/api/student/auth/logout", "/catalog");
    expect(t?.state.notice).toMatch(/couldn’t log you out/i);
    expect(t?.state.from).toBeUndefined();
  });

  it("does nothing while already on a login page", () => {
    expect(csrfRecoveryTarget("/api/admin/auth/login", "/admin/login")).toBeNull();
  });
});

describe("sessionEndedTarget", () => {
  it("sends an admin to the admin login with the full return path", () => {
    expect(
      sessionEndedTarget("/api/admin/staging/modules/m1", "/admin/staging/m1", "?tab=quiz"),
    ).toEqual({
      to: "/admin/login",
      state: {
        from: "/admin/staging/m1?tab=quiz",
        notice: "Session ended — please sign in again.",
      },
    });
  });

  it("sends a student to the student login", () => {
    const t = sessionEndedTarget("/api/student/me/progress", "/progress", "");
    expect(t).toEqual({
      to: "/login",
      state: { from: "/progress", notice: "Session ended — please sign in again." },
    });
  });

  it("ignores the other area's 401 (an admin page never leaves for the student login)", () => {
    expect(sessionEndedTarget("/api/student/catalog", "/admin/ingestion", "")).toBeNull();
    expect(sessionEndedTarget("/api/admin/users", "/catalog", "")).toBeNull();
  });

  it("does nothing once on a login page (several polls fail together)", () => {
    expect(sessionEndedTarget("/api/admin/users", "/admin/login", "")).toBeNull();
    expect(sessionEndedTarget("/api/student/catalog", "/login", "")).toBeNull();
  });
});

describe("csrfRecoveryTarget keeps the query string", () => {
  it("returns to the page with its search", () => {
    const t = csrfRecoveryTarget("/api/admin/modules", "/admin/ingestion", "?course=c1&focus=form");
    expect(t?.state.from).toBe("/admin/ingestion?course=c1&focus=form");
  });
});
