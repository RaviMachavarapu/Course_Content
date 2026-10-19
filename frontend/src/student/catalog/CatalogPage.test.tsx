import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CatalogPage } from "./CatalogPage";

afterEach(() => vi.unstubAllGlobals());

function course(over: Record<string, unknown> = {}) {
  return {
    id: crypto.randomUUID(),
    slug: "neural-nets",
    title: "Neural Networks",
    description: "Deep learning foundations",
    category: "Machine Learning",
    cover_image_url: null,
    module_count: 3,
    artifact_counts: { audio_overview: 3, quiz: 3 },
    total_audio_seconds: 900,
    percent_complete: 40,
    next_module_index: 1,
    ...over,
  };
}

function installFetch(body: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve({
        ok: true,
        status: 200,
        statusText: "200",
        json: () => Promise.resolve(body),
      } as Response),
    ),
  );
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/catalog"]}>
        <Routes>
          <Route path="/catalog" element={<CatalogPage />} />
          <Route path="/learn/:slug" element={<div>WORKSPACE</div>} />
          <Route path="/login" element={<div>LOGIN</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("CatalogPage", () => {
  it("renders course cards with counts and progress", async () => {
    installFetch({
      courses: [course()],
      categories: ["Machine Learning"],
    });
    renderPage();

    expect(await screen.findByText("Neural Networks")).toBeInTheDocument();
    expect(screen.getByText(/3 Audio Tracks · 3 Quizzes/)).toBeInTheDocument();
    expect(screen.getByText("40% Complete")).toBeInTheDocument();
    expect(screen.getByText("15 min")).toBeInTheDocument();
  });

  it("filters by search and category together (AND)", async () => {
    installFetch({
      courses: [
        course({ title: "Neural Networks", category: "Machine Learning", slug: "nn" }),
        course({ title: "Roman History", category: "History", slug: "rome" }),
        course({ title: "Neural History of Art", category: "History", slug: "art" }),
      ],
      categories: ["History", "Machine Learning"],
    });
    renderPage();
    await screen.findByText("Neural Networks");

    await userEvent.type(screen.getAllByLabelText("Search courses")[0]!, "neural");
    expect(screen.getAllByTestId("course-card")).toHaveLength(2);

    await userEvent.click(screen.getByRole("button", { name: "History", pressed: false }));
    expect(screen.getAllByTestId("course-card")).toHaveLength(1);
    expect(screen.getByText("Neural History of Art")).toBeInTheDocument();
  });

  it("Start Learning routes to the workspace", async () => {
    installFetch({ courses: [course({ slug: "neural-nets" })], categories: [] });
    renderPage();
    await screen.findByText("Neural Networks");

    await userEvent.click(screen.getByTestId("btn-ct7"));
    expect(await screen.findByText("WORKSPACE")).toBeInTheDocument();
  });

  it("shows an empty state when there are no courses", async () => {
    installFetch({ courses: [], categories: [] });
    renderPage();
    expect(await screen.findByText("No courses yet")).toBeInTheDocument();
  });
});
