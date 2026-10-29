import { QueryClient } from "@tanstack/react-query";
import { handleSessionEnded } from "./sessionEnded";

function setup(pathname: string, search = "") {
  const qc = new QueryClient();
  qc.setQueryData(["admin", "session"], { id: "a" });
  qc.setQueryData(["student", "session"], { id: "s" });
  qc.setQueryData(["admin", "staging", "m1"], { x: 1 });
  const navigate = vi.fn();
  return { qc, navigate, location: { pathname, search } };
}

describe("handleSessionEnded", () => {
  it("routes an admin to the admin login with the notice, then signs the area out", () => {
    const { qc, navigate, location } = setup("/admin/staging/m1", "?tab=quiz");
    handleSessionEnded("/api/admin/staging/modules/m1", location, navigate, qc);
    expect(navigate).toHaveBeenCalledWith("/admin/login", {
      replace: true,
      state: {
        from: "/admin/staging/m1?tab=quiz",
        notice: "Session ended — please sign in again.",
      },
    });
    expect(qc.getQueryData(["admin", "session"])).toBeNull();
    expect(qc.getQueryData(["admin", "staging", "m1"])).toBeUndefined();
    // the other area's session is independent
    expect(qc.getQueryData(["student", "session"])).toEqual({ id: "s" });
  });

  it("routes a student to the student login", () => {
    const { qc, navigate, location } = setup("/learn/c/0/quiz");
    handleSessionEnded("/api/student/artifacts/a/progress", location, navigate, qc);
    expect(navigate).toHaveBeenCalledWith("/login", {
      replace: true,
      state: { from: "/learn/c/0/quiz", notice: "Session ended — please sign in again." },
    });
    expect(qc.getQueryData(["student", "session"])).toBeNull();
  });

  it("does nothing for the other area's 401 or once on a login page", () => {
    const { qc, navigate } = setup("/admin/ingestion");
    handleSessionEnded(
      "/api/student/catalog",
      { pathname: "/admin/ingestion", search: "" },
      navigate,
      qc,
    );
    handleSessionEnded("/api/admin/users", { pathname: "/admin/login", search: "" }, navigate, qc);
    expect(navigate).not.toHaveBeenCalled();
    expect(qc.getQueryData(["admin", "session"])).toEqual({ id: "a" });
  });
});
