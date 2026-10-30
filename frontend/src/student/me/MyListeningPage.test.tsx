import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MyListeningPage } from "./MyListeningPage";

afterEach(() => vi.unstubAllGlobals());

describe("MyListeningPage", () => {
  it("lists no courses and does not fetch them", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <MyListeningPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(screen.getByRole("heading", { name: "My Listening" })).toBeInTheDocument();
    expect(screen.getByTestId("btn-logout")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
