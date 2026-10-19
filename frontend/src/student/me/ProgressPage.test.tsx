import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { render, screen } from "@testing-library/react";
import { ProgressPage } from "./ProgressPage";

afterEach(() => vi.unstubAllGlobals());

function installFetch(courses: unknown[]) {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve({
        ok: true,
        status: 200,
        statusText: "200",
        json: () => Promise.resolve({ courses }),
      } as Response),
    ),
  );
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <ProgressPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ProgressPage", () => {
  it("renders a row per started course with real percentages", async () => {
    installFetch([
      {
        id: "c1",
        slug: "nn",
        title: "Neural Networks",
        percent_complete: 66,
        modules_started: 2,
        modules_total: 3,
      },
    ]);
    renderPage();

    expect(await screen.findByText("Neural Networks")).toBeInTheDocument();
    expect(screen.getByText("2 of 3 units started")).toBeInTheDocument();
    expect(screen.getByText("66%")).toBeInTheDocument();
  });

  it("shows an empty state with a link to the catalog", async () => {
    installFetch([]);
    renderPage();
    expect(await screen.findByText("Nothing started yet")).toBeInTheDocument();
    expect(screen.getByText("Browse the catalog")).toHaveAttribute("href", "/catalog");
  });
});
