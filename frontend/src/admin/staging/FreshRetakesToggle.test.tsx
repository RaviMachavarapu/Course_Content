import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FreshRetakesToggle } from "./FreshRetakesToggle";

afterEach(() => vi.unstubAllGlobals());

function reply(ok: boolean, body: unknown): Promise<Response> {
  return Promise.resolve({
    ok,
    status: ok ? 200 : 500,
    statusText: ok ? "OK" : "Server Error",
    json: () => Promise.resolve(body),
  } as Response);
}

function renderToggle() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <FreshRetakesToggle moduleId="m1" />
    </QueryClientProvider>,
  );
}

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

  it("shows an error line when the setting can't be loaded", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => reply(false, { error: { code: "boom", message: "boom" } })),
    );
    renderToggle();
    expect(await screen.findByText("Couldn't load the quiz setting")).toBeInTheDocument();
    expect(screen.queryByRole("switch")).not.toBeInTheDocument();
  });

  it("is disabled while saving and shows Could not save when the PATCH fails", async () => {
    let failPatch: () => void = () => {};
    vi.stubGlobal(
      "fetch",
      vi.fn((_u: string, init?: RequestInit) =>
        init?.method === "PATCH"
          ? new Promise<Response>((resolve) => {
              failPatch = () =>
                resolve({
                  ok: false,
                  status: 500,
                  statusText: "Server Error",
                  json: () => Promise.resolve({ error: { code: "boom", message: "boom" } }),
                } as Response);
            })
          : reply(true, { fresh_retakes: true }),
      ),
    );
    renderToggle();
    const sw = await screen.findByRole("switch", { name: /Fresh questions on retake/ });
    await userEvent.click(sw);
    await waitFor(() => expect(sw).toBeDisabled());
    failPatch();
    expect(await screen.findByText("Could not save")).toBeInTheDocument();
    expect(sw).not.toBeDisabled();
    expect(sw).toBeChecked();
  });
});
