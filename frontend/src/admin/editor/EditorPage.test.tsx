import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { render, screen } from "@testing-library/react";
import { EditorPage } from "./EditorPage";

afterEach(() => vi.unstubAllGlobals());

function installFetch(body: unknown, status = 200) {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve({
        ok: status < 300,
        status,
        statusText: String(status),
        json: () => Promise.resolve(body),
      } as Response),
    ),
  );
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/admin/editor"]}>
        <Routes>
          <Route path="/admin/editor" element={<EditorPage />} />
          <Route path="/admin/editor/:courseId" element={<div>STRUCTURE</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("EditorPage", () => {
  it("lists courses linking to their structure view", async () => {
    installFetch({
      courses: [
        {
          id: "c1",
          title: "Deep Learning",
          slug: "dl",
          category: "AI",
          status: "draft",
          module_count: 3,
          updated_at: "2026-01-01T00:00:00Z",
          published_at: null,
        },
      ],
    });
    renderPage();

    const link = await screen.findByTestId("editor-course-link");
    expect(link).toHaveTextContent("Deep Learning");
    expect(link).toHaveAttribute("href", "/admin/editor/c1");
    expect(screen.getByText("3")).toBeInTheDocument();
  });

  it("shows an empty state when there are no courses", async () => {
    installFetch({ courses: [] });
    renderPage();
    expect(await screen.findByText("No courses yet")).toBeInTheDocument();
  });
});
