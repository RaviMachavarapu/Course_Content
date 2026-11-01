import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { ProgressPage } from "./ProgressPage";

afterEach(() => vi.unstubAllGlobals());

describe("ProgressPage", () => {
  it("lists no courses and does not fetch them", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <ProgressPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(screen.getByRole("heading", { name: "Progress" })).toBeInTheDocument();
    expect(screen.getByTestId("btn-logout")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
