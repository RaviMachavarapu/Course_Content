import { render, screen } from "@testing-library/react";
import { Outlet, RouterProvider, createMemoryRouter } from "react-router-dom";
import { RouteError } from "./RouteError";
import { routes } from "./router";

function Boom(): JSX.Element {
  throw new Error("bad content");
}

describe("RouteError", () => {
  it("shows an in-shell error with a way back instead of the default crash page", async () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    const router = createMemoryRouter(
      [
        {
          path: "/learn/:slug",
          element: (
            <>
              <div>SHELL</div>
              <Outlet />
            </>
          ),
          // the child error renders inside the parent's Outlet
          children: [{ path: ":m/:t", element: <Boom />, errorElement: <RouteError /> }],
        },
      ],
      { initialEntries: ["/learn/nn/0/report"] },
    );
    render(<RouterProvider router={router} />);
    spy.mockRestore();
    expect(await screen.findByText("This page couldn’t be shown")).toBeInTheDocument();
    expect(screen.getByText("SHELL")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to Course Overview" })).toHaveAttribute(
      "href",
      "/learn/nn",
    );
  });

  it("every area has an error boundary inside its shell and at its root", () => {
    for (const path of ["/admin", "/learn/:slug", "/"]) {
      const root = routes.find((r) => r.path === path)!;
      expect(root.errorElement, path).toBeDefined();
    }
    const admin = routes.find((r) => r.path === "/admin")!;
    expect(admin.children?.[0]?.errorElement).toBeDefined();
    const student = routes.find((r) => r.path === "/")!;
    expect(student.children?.[0]?.errorElement).toBeDefined();
    const learn = routes.find((r) => r.path === "/learn/:slug")!;
    const workspace = learn.children?.[0];
    expect(workspace?.children?.[0]?.errorElement).toBeDefined();
  });
});
