import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AdminHeader } from "./AdminHeader";
import { NotificationsPanel } from "./NotificationsPanel";

afterEach(() => vi.unstubAllGlobals());

function installFetch(recent: unknown[]) {
  const fn = vi.fn((input: string | URL): Promise<Response> => {
    const url = typeof input === "string" ? input : input.toString();
    let body: unknown = { error: { code: "x", message: "x" } };
    let status = 404;
    if (url.includes("/api/admin/jobs/recent")) {
      body = { jobs: recent };
      status = 200;
    } else if (url.includes("/api/admin/mcp/status")) {
      body = { healthy: true, account_email: null, last_ok_at: null, detail: "ok" };
      status = 200;
    } else if (url.includes("/api/admin/auth/me")) {
      body = { user: { id: "me" } };
      status = 200;
    }
    return Promise.resolve({
      ok: status < 300,
      status,
      statusText: String(status),
      json: () => Promise.resolve(body),
    } as Response);
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

function job(over: Record<string, unknown> = {}) {
  return {
    id: crypto.randomUUID(),
    kind: "generate_artifact",
    state: "succeeded",
    artifact_type: "report",
    module_id: "m1",
    module_title: "Neural Nets",
    course_id: "c1",
    error_detail: null,
    at: new Date().toISOString(),
    ...over,
  };
}

function wrap(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("NotificationsPanel", () => {
  it("renders a deep link per job and an error line for failures", async () => {
    installFetch([
      job(),
      job({ state: "failed", artifact_type: "slide_deck", error_detail: "RenderError: pending" }),
    ]);
    wrap(<NotificationsPanel onNavigate={vi.fn()} />);

    const rows = await screen.findAllByTestId("notif-row");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveAttribute("href", "/admin/modules/m1/staging");
    expect(screen.getByText("RenderError: pending")).toBeInTheDocument();
    expect(screen.getByText("Report ready")).toBeInTheDocument();
    expect(screen.getByText("Slide Deck failed")).toBeInTheDocument();
  });

  it("shows an empty state with no activity", async () => {
    installFetch([]);
    wrap(<NotificationsPanel onNavigate={vi.fn()} />);
    expect(await screen.findByText(/No recent generation activity/)).toBeInTheDocument();
  });
});

describe("AdminHeader notifications", () => {
  it("badges the failure count and opens the panel", async () => {
    installFetch([job({ state: "failed", error_detail: "boom" }), job()]);
    wrap(<AdminHeader />);

    expect(await screen.findByTestId("notif-badge")).toHaveTextContent("1");
    await userEvent.click(screen.getByTestId("btn-ig8"));
    expect(await screen.findAllByTestId("notif-row")).toHaveLength(2);
  });
});
