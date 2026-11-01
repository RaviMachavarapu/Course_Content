import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CatalogPage } from "./CatalogPage";

afterEach(() => vi.unstubAllGlobals());

function installFetch() {
  const fetchMock = vi.fn((input: string | URL, init?: RequestInit) =>
    Promise.resolve({
      ok: true,
      status: String(input).includes("/auth/logout") && init?.method === "POST" ? 204 : 200,
      statusText: "200",
      json: () => Promise.resolve(null),
    } as Response),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/catalog"]}>
        <Routes>
          <Route path="/catalog" element={<CatalogPage />} />
          <Route path="/login" element={<div>LOGIN</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("CatalogPage", () => {
  it("lists no courses and does not fetch them", () => {
    const fetchMock = installFetch();
    renderPage();
    expect(screen.getByRole("heading", { name: "Course Catalogs" })).toBeInTheDocument();
    expect(screen.queryByTestId("course-card")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Search courses")).not.toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("logs out from the profile menu", async () => {
    installFetch();
    renderPage();
    await userEvent.click(screen.getByTestId("btn-ct5"));
    await userEvent.click(screen.getByRole("button", { name: /Log out/ }));
    expect(await screen.findByText("LOGIN")).toBeInTheDocument();
  });
});
