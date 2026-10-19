import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ArtifactRoute } from "./ArtifactRoute";
import { OverviewPanel } from "./OverviewPanel";
import { WorkspaceLayout } from "./WorkspaceLayout";

afterEach(() => vi.unstubAllGlobals());

const COURSE = {
  id: "c1",
  slug: "neural-nets",
  title: "Neural Networks",
  description: "Deep learning foundations",
  percent_complete: 20,
  current_module_index: 0,
  modules: [
    {
      index: 0,
      id: "m1",
      title: "Perceptrons",
      percent_complete: 33,
      artifacts: [
        { id: "a-report", type: "report", completed: true },
        { id: "a-quiz", type: "quiz", completed: false },
      ],
    },
    {
      index: 1,
      id: "m2",
      title: "Backprop",
      percent_complete: 0,
      artifacts: [{ id: "b-report", type: "report", completed: false }],
    },
  ],
};

function installFetch(over: Record<string, { status?: number; body: unknown }> = {}) {
  const fn = vi.fn((input: string | URL): Promise<Response> => {
    const url = typeof input === "string" ? input : input.toString();
    const match = Object.keys(over).find((k) => url.includes(k));
    let status = 200;
    let body: unknown = { error: { code: "x", message: "x" } };
    if (match) {
      status = over[match]!.status ?? 200;
      body = over[match]!.body;
    } else if (url.includes("/api/student/courses/neural-nets")) {
      body = COURSE;
    } else if (url.includes("/api/student/artifacts/")) {
      body = {
        id: "a-report",
        type: "report",
        module_id: "m1",
        module_index: 0,
        course_slug: "neural-nets",
        revision: 2,
        content_json: null,
        content_html: "<p>hi</p>",
        media: [],
        completed: false,
        slide_last_index: null,
        audio_position_seconds: null,
      };
    } else {
      status = 404;
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

function renderAt(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/learn/:slug" element={<WorkspaceLayout />}>
            <Route index element={<OverviewPanel />} />
            <Route path=":moduleIndex/:type" element={<ArtifactRoute />} />
          </Route>
          <Route path="/catalog" element={<div>CATALOG</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("WorkspaceLayout", () => {
  it("renders the top bar and only the published artifact links", async () => {
    installFetch();
    renderAt("/learn/neural-nets");

    expect(await screen.findByTestId("btn-ws1")).toHaveTextContent("Course Overview");
    expect(screen.getByTestId("btn-ws2")).toHaveTextContent("Back to Dashboard");
    expect(screen.getByText("20% Complete")).toBeInTheDocument();
    expect(screen.getByText("Current: Unit 1")).toBeInTheDocument();

    // module 0 publishes report + quiz only
    expect(screen.getByTestId("btn-ws8")).toBeInTheDocument(); // Report
    expect(screen.getByTestId("btn-ws6")).toBeInTheDocument(); // Quiz
    expect(screen.queryByTestId("btn-ws3")).not.toBeInTheDocument(); // Audio (unpublished)
    expect(screen.queryByTestId("btn-ws4")).not.toBeInTheDocument(); // Slides
  });

  it("Back to Dashboard routes to the catalog", async () => {
    installFetch();
    renderAt("/learn/neural-nets");
    await userEvent.click(await screen.findByTestId("btn-ws2"));
    expect(await screen.findByText("CATALOG")).toBeInTheDocument();
  });

  it("opens a published artifact view", async () => {
    installFetch();
    renderAt("/learn/neural-nets/0/report");
    expect(await screen.findByRole("heading", { name: "Report", level: 1 })).toBeInTheDocument();
    expect(screen.getByTestId("btn-rp2")).toHaveTextContent("Complete Module");
  });

  it("shows a 'Not available' panel for an unpublished type (no error)", async () => {
    installFetch();
    renderAt("/learn/neural-nets/0/audio_overview");
    expect(await screen.findByText("Not available")).toBeInTheDocument();
  });

  it("shows a friendly panel when the course is not published (404)", async () => {
    installFetch({ "/api/student/courses/neural-nets": { status: 404, body: { error: { code: "not_found", message: "x" } } } });
    renderAt("/learn/neural-nets");
    expect(await screen.findByText("Course not available")).toBeInTheDocument();
  });

  it("switches modules via the switcher", async () => {
    installFetch();
    renderAt("/learn/neural-nets/0/report");
    await screen.findByRole("heading", { name: "Report" });
    await userEvent.selectOptions(screen.getByTestId("module-switcher"), "1");
    // module 1 keeps 'report' (it publishes one)
    expect(await screen.findByText("Current: Unit 2")).toBeInTheDocument();
  });
});
