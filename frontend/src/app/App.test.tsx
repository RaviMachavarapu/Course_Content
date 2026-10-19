import { render, screen } from "@testing-library/react";
import { App } from "./App";

afterEach(() => vi.unstubAllGlobals());

describe("App", () => {
  it("sends an unauthenticated visitor from the root to the student login", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve({
          ok: false,
          status: 401,
          statusText: "401",
          json: () => Promise.resolve({ error: { code: "unauthorized", message: "x" } }),
        } as Response),
      ),
    );
    render(<App />);
    expect(await screen.findByRole("button", { name: "Sign in" })).toBeInTheDocument();
  });
});
