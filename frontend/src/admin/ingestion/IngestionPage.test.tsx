import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { IngestionPage } from "./IngestionPage";

afterEach(() => vi.unstubAllGlobals());

interface Handler {
  method: string;
  match: string;
  status?: number;
  body: unknown;
}

function installFetch(handlers: Handler[]): ReturnType<typeof vi.fn> {
  const fn = vi.fn((input: string | URL, init?: RequestInit): Promise<Response> => {
    const url = typeof input === "string" ? input : input.toString();
    const method = (init?.method ?? "GET").toUpperCase();
    const h = handlers.find((x) => x.method === method && url.includes(x.match));
    const status = h?.status ?? (h ? 200 : 404);
    return Promise.resolve({
      ok: status < 300,
      status,
      statusText: String(status),
      json: () => Promise.resolve(h ? h.body : { error: { code: "not_found", message: "x" } }),
    } as Response);
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/admin/ingestion"]}>
        <Routes>
          <Route path="/admin/ingestion" element={<IngestionPage />} />
          <Route path="/admin/modules/:id/staging" element={<div>STAGING PAGE</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const HEALTHY = {
  method: "GET",
  match: "/api/admin/mcp/status",
  body: { healthy: true, detail: "FixtureProvider" },
};
const NO_COURSES = { method: "GET", match: "/api/admin/courses", body: { courses: [] } };
const EMPTY_PIPELINE = {
  method: "GET",
  match: "/api/admin/pipeline",
  body: { rows: [], page: 1, page_size: 5, total: 0 },
};

describe("IngestionPage", () => {
  it("shows the form and BTN-IG6", () => {
    installFetch([HEALTHY, NO_COURSES, EMPTY_PIPELINE]);
    renderPage();
    expect(
      screen.getByRole("heading", { name: /Create New AI Course Module/i }),
    ).toBeInTheDocument();
    expect(screen.getByTestId("btn-ig6")).toHaveTextContent(/Generate Course Material/i);
    expect(screen.getByRole("heading", { name: /Recent Pipeline/i })).toBeInTheDocument();
  });

  it("blocks submit with validation and does not call the API", async () => {
    const fetchMock = installFetch([HEALTHY, NO_COURSES, EMPTY_PIPELINE]);
    renderPage();
    await userEvent.click(screen.getByTestId("btn-ig6"));
    expect(await screen.findByText(/Source URL is required/i)).toBeInTheDocument();
    expect(screen.getByText(/Course title is required/i)).toBeInTheDocument();
    const posts = fetchMock.mock.calls.filter((c) => (c[1] as RequestInit)?.method === "POST");
    expect(posts).toHaveLength(0);
  });

  it("requires at least one artifact type", async () => {
    installFetch([HEALTHY, NO_COURSES, EMPTY_PIPELINE]);
    renderPage();
    for (const t of [
      "slide_deck",
      "flashcards",
      "quiz",
      "report",
      "infographic",
      "audio_overview",
    ]) {
      await userEvent.click(screen.getByTestId(`type-${t}`));
    }
    await userEvent.click(screen.getByTestId("btn-ig6"));
    expect(await screen.findByText(/at least one artifact type/i)).toBeInTheDocument();
  });

  it("creates a course + module then redirects to staging", async () => {
    installFetch([
      HEALTHY,
      NO_COURSES,
      EMPTY_PIPELINE,
      // more specific match first — installFetch returns the first hit
      {
        method: "POST",
        match: "/api/admin/courses/c1/modules",
        status: 201,
        body: { module: { id: "m1" }, job_ids: ["j1"] },
      },
      { method: "POST", match: "/api/admin/courses", status: 201, body: { course: { id: "c1" } } },
    ]);
    renderPage();

    await userEvent.type(screen.getByLabelText("Source URL"), "https://youtu.be/abc");
    await userEvent.type(screen.getByLabelText("Course title"), "Intro to ML");
    await userEvent.type(screen.getByLabelText("Module title"), "Module 1");
    await userEvent.click(screen.getByTestId("btn-ig6"));

    await waitFor(() => expect(screen.getByText("STAGING PAGE")).toBeInTheDocument());
  });

  it("shows an options section per checked type and hides it when unchecked", async () => {
    installFetch([HEALTHY, NO_COURSES, EMPTY_PIPELINE]);
    renderPage();
    // all six checked by default
    expect(screen.getByTestId("options-audio_overview")).toBeInTheDocument();
    expect(screen.getByTestId("options-slide_deck")).toBeInTheDocument();

    await userEvent.click(screen.getByTestId("type-slide_deck"));
    expect(screen.queryByTestId("options-slide_deck")).not.toBeInTheDocument();
    expect(screen.getByTestId("options-audio_overview")).toBeInTheDocument();
  });

  it("sends per-type generation options with the create-module request", async () => {
    const fetchMock = installFetch([
      HEALTHY,
      NO_COURSES,
      EMPTY_PIPELINE,
      {
        method: "POST",
        match: "/api/admin/courses/c1/modules",
        status: 201,
        body: { module: { id: "m1" }, job_ids: ["j1"] },
      },
      { method: "POST", match: "/api/admin/courses", status: 201, body: { course: { id: "c1" } } },
    ]);
    renderPage();

    await userEvent.type(screen.getByLabelText("Source URL"), "https://youtu.be/abc");
    await userEvent.type(screen.getByLabelText("Course title"), "Intro to ML");
    await userEvent.type(screen.getByLabelText("Module title"), "Module 1");

    const audioSection = within(screen.getByTestId("options-audio_overview"));
    await userEvent.selectOptions(audioSection.getByLabelText("Format"), "brief");

    await userEvent.click(screen.getByTestId("btn-ig6"));
    await waitFor(() => expect(screen.getByText("STAGING PAGE")).toBeInTheDocument());

    const modulePost = fetchMock.mock.calls.find((c) =>
      String(c[0]).includes("/api/admin/courses/c1/modules"),
    );
    const body = JSON.parse((modulePost![1] as RequestInit).body as string);
    expect(body.options.audio_overview.format).toBe("brief");
    expect(body.options.slide_deck).toEqual({ language: "en" });
  });

  it("warns when NotebookLM is disconnected but still allows submit", async () => {
    installFetch([
      { method: "GET", match: "/api/admin/mcp/status", body: { healthy: false, detail: "down" } },
      NO_COURSES,
      EMPTY_PIPELINE,
    ]);
    renderPage();
    expect(await screen.findByText(/NotebookLM is disconnected/i)).toBeInTheDocument();
    expect(screen.getByTestId("btn-ig6")).toBeEnabled();
  });
});
