import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ReportViewer } from "./ReportViewer";

afterEach(() => vi.unstubAllGlobals());

const ARTIFACT = {
  id: "a-report",
  type: "report",
  module_id: "m1",
  module_index: 0,
  course_slug: "nn",
  revision: 1,
  content_json: {
    title: "Neural Networks",
    read_minutes: 7,
    key_takeaways: ["Units combine non-linearly", "Depth composes features"],
    sections: [
      { heading: "How they work", html: "<p>A neuron sums <strong>weighted</strong> inputs.</p>" },
      { heading: "Why depth", html: "<p>Layers build abstractions.</p>" },
    ],
  },
  content_html: "<h1>Neural Networks</h1>",
  media: [{ kind: "report_pdf", url: "/api/media/report.pdf", page_index: null }],
  completed: false,
  slide_last_index: null,
  audio_position_seconds: null,
  flashcard_ratings: {},
};

function installFetch() {
  const fn = vi.fn((input: string | URL, init?: RequestInit): Promise<Response> => {
    const url = typeof input === "string" ? input : input.toString();
    const method = (init?.method ?? "GET").toUpperCase();
    let body: unknown = { error: { code: "x", message: "x" } };
    let status = 404;
    if (url.includes("/progress") && method === "PUT") {
      body = { completed: true, slide_last_index: null, audio_position_seconds: null, course_percent_complete: 100 };
      status = 200;
    } else if (url.includes("/api/student/artifacts/")) {
      body = ARTIFACT;
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

function renderViewer() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/learn/nn/0/report"]}>
        <Routes>
          <Route
            path="/learn/nn/0/report"
            element={<ReportViewer artifactId="a-report" slug="nn" />}
          />
          <Route path="/learn/nn" element={<div>MODULE OVERVIEW</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ReportViewer", () => {
  it("renders read time, title, takeaways and numbered sanitized sections", async () => {
    installFetch();
    renderViewer();

    expect(await screen.findByRole("heading", { name: "Neural Networks", level: 1 })).toBeInTheDocument();
    expect(screen.getByText("7 min read")).toBeInTheDocument();
    expect(screen.getByText("Units combine non-linearly")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /1\. How they work/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /2\. Why depth/ })).toBeInTheDocument();
    expect(screen.getByText("weighted")).toBeInTheDocument();
    expect(screen.getByTestId("btn-rp3")).toHaveAttribute("href", "/api/media/report.pdf");
  });

  it("marks the report viewed on open", async () => {
    const fetchMock = installFetch();
    renderViewer();
    await screen.findByRole("heading", { name: "Neural Networks", level: 1 });

    await waitFor(() => {
      const put = fetchMock.mock.calls.find(
        (c) => (c[1] as RequestInit)?.method === "PUT" && String(c[0]).includes("/progress"),
      );
      expect(put).toBeDefined();
      expect(JSON.parse((put![1] as RequestInit).body as string)).toEqual({});
    });
  });

  it("Complete Module sends complete_module and returns to the overview", async () => {
    const fetchMock = installFetch();
    renderViewer();
    await screen.findByRole("heading", { name: "Neural Networks", level: 1 });

    await userEvent.click(screen.getByTestId("btn-rp2"));
    await waitFor(() => {
      const put = fetchMock.mock.calls.find(
        (c) =>
          (c[1] as RequestInit)?.method === "PUT" &&
          String(c[0]).includes("/progress") &&
          ((JSON.parse((c[1] as RequestInit).body as string) as { complete_module?: boolean })
            .complete_module ??
            false),
      );
      expect(put).toBeDefined();
    });
    expect(await screen.findByText("MODULE OVERVIEW")).toBeInTheDocument();
  });

  it("Previous returns to the module overview", async () => {
    installFetch();
    renderViewer();
    await screen.findByRole("heading", { name: "Neural Networks", level: 1 });
    await userEvent.click(screen.getByTestId("btn-rp1"));
    expect(await screen.findByText("MODULE OVERVIEW")).toBeInTheDocument();
  });
});
