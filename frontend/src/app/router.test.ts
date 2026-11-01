import { routes } from "./router";

describe("routes", () => {
  it.each([
    "/login",
    "/register",
    "/forgot-password",
    "/reset-password",
    "/admin/login",
    "/admin/forgot-password",
    "/admin/reset-password",
  ])("%s has an error boundary", (path) => {
    expect(routes.find((r) => r.path === path)?.errorElement).toBeTruthy();
  });

  it("serves the style guide only in development builds", () => {
    const styleguide = routes.some((r) => r.path === "/styleguide");
    expect(styleguide).toBe(import.meta.env.DEV);
  });
});
