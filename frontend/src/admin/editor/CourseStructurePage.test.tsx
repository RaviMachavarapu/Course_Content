import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Toaster } from "@/components";
import { CourseStructurePage } from "./CourseStructurePage";

afterEach(() => vi.unstubAllGlobals());

const TYPES = ["slide_deck", "flashcards", "quiz", "report", "infographic", "audio_overview"];

function mod(id: string, title: string, order: number, over: Record<string, unknown> = {}) {
  return {
    id,
    order_index: order,
    title,
    source_url: `https://example.com/${id}`,
    source_files: [],
    source_type: "web",
    status: "ready",
    artifacts: TYPES.map((t) => ({ id: `${id}-${t}`, type: t, status: "ready" })),
    ...over,
  };
}

function courseBody(modules: unknown[]) {
  return {
    course: {
      id: "c1",
      title: "Deep Learning",
      slug: "deep-learning",
      description: "",
      category: "AI",
      status: "draft",
      cover_image_key: null,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
      published_at: null,
      modules,
    },
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
      <MemoryRouter initialEntries={["/admin/editor/c1"]}>
        <Routes>
          <Route path="/admin/editor/:courseId" element={<CourseStructurePage />} />
          <Route path="/admin/ingestion" element={<div>INGESTION</div>} />
        </Routes>
        <Toaster />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("CourseStructurePage", () => {
  it("renders modules in order with the breadcrumb and BTN-CE1", async () => {
    installFetch([
      { method: "GET", match: "/api/admin/courses/c1", body: courseBody([mod("m2", "Two", 1), mod("m1", "One", 0)]) },
    ]);
    renderPage();

    expect(await screen.findByRole("heading", { name: "Deep Learning" })).toBeInTheDocument();
    const rows = screen.getAllByText(/^(One|Two)$/).map((el) => el.textContent);
    expect(rows).toEqual(["One", "Two"]);
    expect(screen.getByTestId("btn-ce1")).toBeInTheDocument();
    expect(screen.getAllByTestId("btn-ce9").length).toBe(12);
  });

  it("moves a module down via the kebab menu", async () => {
    const fetchMock = installFetch([
      { method: "GET", match: "/api/admin/courses/c1", body: courseBody([mod("m1", "One", 0), mod("m2", "Two", 1)]) },
      {
        method: "POST",
        match: "/api/admin/courses/modules/m1/move",
        body: courseBody([mod("m2", "Two", 0), mod("m1", "One", 1)]),
      },
    ]);
    renderPage();
    await screen.findByRole("heading", { name: "Deep Learning" });

    const [firstKebab] = screen.getAllByTestId("btn-ce2");
    await userEvent.click(firstKebab!);
    await userEvent.click(screen.getByTestId("btn-ce6"));

    await waitFor(() => {
      const post = fetchMock.mock.calls.find(
        (c) => (c[1] as RequestInit)?.method === "POST" && String(c[0]).includes("m1/move"),
      );
      expect(post).toBeDefined();
      expect(JSON.parse((post![1] as RequestInit).body as string)).toEqual({ direction: "down" });
    });
  });

  it("renames a module through the modal", async () => {
    const fetchMock = installFetch([
      { method: "GET", match: "/api/admin/courses/c1", body: courseBody([mod("m1", "One", 0)]) },
      { method: "PATCH", match: "/api/admin/courses/modules/m1", body: { ...mod("m1", "Renamed", 0) } },
    ]);
    renderPage();
    await screen.findByRole("heading", { name: "Deep Learning" });

    await userEvent.click(screen.getByTestId("btn-ce2"));
    await userEvent.click(screen.getByTestId("btn-ce4"));
    const box = await screen.findByLabelText("Module title");
    await userEvent.clear(box);
    await userEvent.type(box, "Renamed");
    await userEvent.click(screen.getByTestId("btn-ce4-confirm"));

    await waitFor(() => {
      const patch = fetchMock.mock.calls.find(
        (c) => (c[1] as RequestInit)?.method === "PATCH" && String(c[0]).includes("modules/m1"),
      );
      expect(patch).toBeDefined();
      expect(JSON.parse((patch![1] as RequestInit).body as string)).toEqual({ title: "Renamed" });
    });
  });

  it("deletes a module after the strong confirm", async () => {
    const fetchMock = installFetch([
      { method: "GET", match: "/api/admin/courses/c1", body: courseBody([mod("m1", "One", 0)]) },
      { method: "DELETE", match: "/api/admin/courses/modules/m1", status: 204, body: null },
    ]);
    renderPage();
    await screen.findByRole("heading", { name: "Deep Learning" });

    await userEvent.click(screen.getByTestId("btn-ce2"));
    await userEvent.click(screen.getByTestId("btn-ce8"));
    expect(await screen.findByText(/cannot be undone/i)).toBeInTheDocument();
    await userEvent.click(screen.getByTestId("btn-ce8-confirm"));

    await waitFor(() => {
      const del = fetchMock.mock.calls.find(
        (c) => (c[1] as RequestInit)?.method === "DELETE" && String(c[0]).includes("modules/m1"),
      );
      expect(del).toBeDefined();
    });
  });

  it("re-runs all artifacts for a module", async () => {
    const fetchMock = installFetch([
      { method: "GET", match: "/api/admin/courses/c1", body: courseBody([mod("m1", "One", 0)]) },
      {
        method: "POST",
        match: "/api/admin/courses/modules/m1/regenerate",
        body: { module: mod("m1", "One", 0), job_ids: ["j1", "j2", "j3", "j4", "j5", "j6"] },
      },
    ]);
    renderPage();
    await screen.findByRole("heading", { name: "Deep Learning" });

    await userEvent.click(screen.getByTestId("btn-ce2"));
    await userEvent.click(screen.getByTestId("btn-ce7"));

    await waitFor(() => {
      const post = fetchMock.mock.calls.find(
        (c) =>
          (c[1] as RequestInit)?.method === "POST" && String(c[0]).includes("m1/regenerate"),
      );
      expect(post).toBeDefined();
    });
    expect(await screen.findByText(/6 artifacts regenerating/)).toBeInTheDocument();
  });
});
