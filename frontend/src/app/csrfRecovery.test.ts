import { csrfRecoveryTarget } from "./csrfRecovery";

describe("csrfRecoveryTarget", () => {
  it("sends an admin to the admin login, remembering where they were", () => {
    expect(csrfRecoveryTarget("/api/admin/modules", "/admin/ingestion")).toEqual({
      to: "/admin/login",
      state: {
        from: "/admin/ingestion",
        notice: "Your session has expired — please sign in again.",
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
