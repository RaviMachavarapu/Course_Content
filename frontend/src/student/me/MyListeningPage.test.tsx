import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { render, screen } from "@testing-library/react";
import { MyListeningPage } from "./MyListeningPage";

afterEach(() => vi.unstubAllGlobals());

function installFetch(rows: unknown[]) {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve({
        ok: true,
        status: 200,
        statusText: "200",
        json: () => Promise.resolve({ rows }),
      } as Response),
    ),
  );
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <MyListeningPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("MyListeningPage", () => {
  it("shows a Resume link that deep-links to the saved audio position", async () => {
    installFetch([
      {
        artifact_id: "a1",
        course_slug: "nn",
        course_title: "Neural Networks",
        module_index: 2,
        module_title: "Backprop",
        duration_seconds: 300,
        audio_position_seconds: 90,
        percent_listened: 30,
        completed: false,
      },
    ]);
    renderPage();

    expect(await screen.findByText("Neural Networks")).toBeInTheDocument();
    expect(screen.getByText("Backprop")).toBeInTheDocument();
    expect(screen.getByText("1:30 / 5:00")).toBeInTheDocument();
    expect(screen.getByTestId("btn-ml1")).toHaveAttribute("href", "/learn/nn/2/audio_overview");
  });

  it("shows an empty state with nothing listened to", async () => {
    installFetch([]);
    renderPage();
    expect(await screen.findByText("Nothing playing yet")).toBeInTheDocument();
  });
});
