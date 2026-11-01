import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AchievementsPage } from "./me/AchievementsPage";
import { MyListeningPage } from "./me/MyListeningPage";
import { ProgressPage } from "./me/ProgressPage";

// Owner decision 10 (2026-10-29): a Log out button on every student page
// (catalog and workspace have theirs; these are the "me" pages).

afterEach(() => vi.unstubAllGlobals());

function installFetch() {
  const fetchMock = vi.fn((input: string | URL, init?: RequestInit) => {
    const url = String(input);
    const json = (status: number, body: unknown) =>
      Promise.resolve({
        ok: status < 400,
        status,
        statusText: String(status),
        json: () => Promise.resolve(body),
      } as Response);
    if (url.includes("/api/student/auth/logout") && init?.method === "POST") return json(204, null);
    if (url.includes("/me/achievements")) return json(200, { earned: [], locked: [] });
    if (url.includes("/me/listening")) return json(200, { rows: [] });
    return json(200, { courses: [] });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const PAGES: [string, JSX.Element][] = [
  ["/progress", <ProgressPage key="p" />],
  ["/achievements", <AchievementsPage key="a" />],
  ["/my-listening", <MyListeningPage key="l" />],
];

describe.each(PAGES)("Log out on %s", (path, page) => {
  it("signs out and goes to the login page", async () => {
    const fetchMock = installFetch();
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path={path} element={page} />
            <Route path="/login" element={<div>LOGIN PAGE</div>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    const button = await screen.findByTestId("btn-logout");
    expect(button).toHaveTextContent("Log out");
    await userEvent.click(button);
    expect(await screen.findByText("LOGIN PAGE")).toBeInTheDocument();
    expect(
      fetchMock.mock.calls.some(
        ([url, init]) => String(url).includes("/auth/logout") && init?.method === "POST",
      ),
    ).toBe(true);
  });
});
