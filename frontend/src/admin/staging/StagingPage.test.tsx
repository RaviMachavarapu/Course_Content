import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StagingPage } from "./StagingPage";

afterEach(() => vi.unstubAllGlobals());

const TYPES = ["slide_deck", "flashcards", "quiz", "report", "infographic", "audio_overview"];

function artifact(type: string, over: Record<string, unknown> = {}) {
  return {
    id: `a-${type}`,
    type,
    status: "ready",
    last_error: null,
    current_version: {
      id: `v-${type}`,
      revision: 1,
      redo_note: null,
      created_at: "2026-01-01T00:00:00Z",
      media:
        type === "report"
          ? [{ kind: "report_pdf", url: "/api/media/x.pdf", size_bytes: 9, page_index: null }]
          : type === "slide_deck"
            ? [{ kind: "pptx", url: "/api/media/x.pptx", size_bytes: 9, page_index: null }]
            : type === "audio_overview"
              ? [{ kind: "audio_mp3", url: "/api/media/x.mp3", size_bytes: 9, page_index: null }]
              : type === "infographic"
                ? [{ kind: "infographic_png", url: "/api/media/x.png", size_bytes: 9, page_index: null }]
                : [],
      preview:
        type === "quiz"
          ? { question_count: 10 }
          : type === "report"
            ? { read_minutes: 7, section_count: 4 }
            : {},
    },
    job: { state: "succeeded" },
    generation_options: {},
    ...over,
  };
}

function stagingBody(over: Record<string, unknown>[] = []) {
  const map = new Map(over.map((a) => [a.type, a]));
  return {
    module: {
      id: "m1",
      title: "Neural Nets",
      status: "pending_review",
      course_id: "c1",
      course_status: "pending_review",
    },
    artifacts: TYPES.map((t) => map.get(t) ?? artifact(t)),
  };
}

function installFetch(
  handlers: { method: string; match: string; status?: number; body: unknown }[],
) {
  const fn = vi.fn((input: string | URL, init?: RequestInit): Promise<Response> => {
    const url = typeof input === "string" ? input : input.toString();
    const method = (init?.method ?? "GET").toUpperCase();
    const h = handlers.find((x) => x.method === method && url.includes(x.match));
    const status = h?.status ?? (h ? 200 : 404);
    return Promise.resolve({
      ok: status < 300,
      status,
      statusText: String(status),
      json: () => Promise.resolve(h ? h.body : { error: { code: "x", message: "x" } }),
    } as Response);
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/admin/modules/m1/staging"]}>
        <Routes>
          <Route path="/admin/modules/:moduleId/staging" element={<StagingPage />} />
          <Route path="/admin/artifacts/:artifactId" element={<div>INSPECT</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("StagingPage", () => {
  it("renders the six artifact cards with previews and BTN-SR1", async () => {
    installFetch([{ method: "GET", match: "/staging", body: stagingBody() }]);
    renderPage();
    expect(await screen.findByRole("heading", { name: "Neural Nets" })).toBeInTheDocument();
    expect(screen.getByTestId("btn-sr1")).toBeInTheDocument();
    expect(screen.getAllByTestId("btn-sr4")).toHaveLength(6); // Redo per card
    expect(screen.getByText(/10 questions/)).toBeInTheDocument();
    expect(screen.getByText(/7 min read/)).toBeInTheDocument();
    expect(screen.getByTestId("btn-sr12")).toHaveAttribute("href", "/api/media/x.pdf");
    expect(screen.getByTestId("btn-sr9")).toHaveAttribute("href", "/api/media/x.mp3");
    expect(screen.getByTestId("btn-sr10")).toHaveAttribute("href", "/api/media/x.pptx");
    expect(screen.getByTestId("btn-sr11")).toHaveAttribute("href", "/api/media/x.png");
  });

  it("opens the redo modal and posts the note", async () => {
    const fetchMock = installFetch([
      { method: "GET", match: "/staging", body: stagingBody() },
      {
        method: "POST",
        match: "/api/admin/artifacts/a-report/redo",
        status: 202,
        body: { job: { id: "j", state: "queued" } },
      },
    ]);
    renderPage();
    await screen.findByRole("heading", { name: "Neural Nets" });

    await userEvent.click(screen.getByRole("button", { name: "Redo Report" }));
    await userEvent.type(await screen.findByRole("textbox"), "make it shorter");
    await userEvent.click(screen.getByTestId("btn-sr7"));

    await waitFor(() => {
      const post = fetchMock.mock.calls.find(
        (c) => (c[1] as RequestInit)?.method === "POST" && String(c[0]).includes("a-report/redo"),
      );
      expect(post).toBeDefined();
      expect(JSON.parse((post![1] as RequestInit).body as string)).toEqual({
        note: "make it shorter",
        options: { language: "en" },
      });
    });
  });

  it("redo modal lets you change options before starting", async () => {
    const fetchMock = installFetch([
      { method: "GET", match: "/staging", body: stagingBody() },
      {
        method: "POST",
        match: "/api/admin/artifacts/a-quiz/redo",
        status: 202,
        body: { job: { id: "j", state: "queued" } },
      },
    ]);
    renderPage();
    await screen.findByRole("heading", { name: "Neural Nets" });

    await userEvent.click(screen.getByRole("button", { name: "Redo Quiz" }));
    await userEvent.selectOptions(await screen.findByLabelText("Difficulty"), "hard");
    await userEvent.click(screen.getByTestId("btn-sr7"));

    await waitFor(() => {
      const post = fetchMock.mock.calls.find(
        (c) => (c[1] as RequestInit)?.method === "POST" && String(c[0]).includes("a-quiz/redo"),
      );
      expect(post).toBeDefined();
      const body = JSON.parse((post![1] as RequestInit).body as string);
      expect(body.options).toEqual({ quantity: "standard", difficulty: "hard" });
    });
  });

  it("shows Retry on an error card and posts a retry on click", async () => {
    const fetchMock = installFetch([
      {
        method: "GET",
        match: "/staging",
        body: stagingBody([
          artifact("quiz", { status: "error", last_error: "bad markup", current_version: null }),
        ]),
      },
      {
        method: "POST",
        match: "/api/admin/artifacts/a-quiz/retry",
        status: 202,
        body: { job: { id: "j", state: "queued" } },
      },
    ]);
    renderPage();
    await screen.findByRole("heading", { name: "Neural Nets" });
    expect(screen.getByText("bad markup")).toBeInTheDocument();
    expect(screen.getByTestId("btn-sr6")).toHaveTextContent(/retry/i);

    await userEvent.click(screen.getByTestId("btn-sr6"));
    await waitFor(() => {
      const post = fetchMock.mock.calls.find(
        (c) => (c[1] as RequestInit)?.method === "POST" && String(c[0]).includes("a-quiz/retry"),
      );
      expect(post).toBeDefined();
    });
  });

  it("wires BTN-SR2 (Publish Complete Course) to the course-scoped confirm modal", async () => {
    installFetch([{ method: "GET", match: "/staging", body: stagingBody() }]);
    renderPage();
    await screen.findByRole("heading", { name: "Neural Nets" });
    await userEvent.click(screen.getByTestId("btn-sr2"));
    expect(await screen.findByRole("heading", { name: /publish complete course/i })).toBeInTheDocument();
  });

  it("BTN-SR8 cancels the redo modal without posting", async () => {
    const fetchMock = installFetch([{ method: "GET", match: "/staging", body: stagingBody() }]);
    renderPage();
    await screen.findByRole("heading", { name: "Neural Nets" });
    await userEvent.click(screen.getByRole("button", { name: "Redo Report" }));
    await screen.findByRole("textbox");
    await userEvent.click(screen.getByTestId("btn-sr8"));
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.some((c) => (c[1] as RequestInit)?.method === "POST")).toBe(false);
  });
});
