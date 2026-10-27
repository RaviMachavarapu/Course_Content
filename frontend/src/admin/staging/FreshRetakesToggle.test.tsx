import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FreshRetakesToggle } from "./FreshRetakesToggle";

afterEach(() => vi.unstubAllGlobals());

describe("FreshRetakesToggle", () => {
  it("reflects the current value and saves via PATCH", async () => {
    const fn = vi.fn((_u: string, init?: RequestInit) => {
      const body = init?.method === "PATCH" ? { fresh_retakes: false } : { fresh_retakes: true };
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve(body),
      } as Response);
    });
    vi.stubGlobal("fetch", fn);
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <FreshRetakesToggle moduleId="m1" />
      </QueryClientProvider>,
    );
    const sw = await screen.findByRole("switch", { name: /Fresh questions on retake/ });
    expect(sw).toBeChecked();
    await userEvent.click(sw);
    await waitFor(() => expect(sw).not.toBeChecked());
    const patch = fn.mock.calls.find((c) => c[1]?.method === "PATCH");
    expect(patch?.[0]).toBe("/api/admin/modules/m1/quiz-settings");
    expect(JSON.parse(patch?.[1]?.body as string)).toEqual({ fresh_retakes: false });
  });
});
