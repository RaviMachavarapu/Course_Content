import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { mockFetch } from "@/student/auth/authTestUtils";
import { AdminLoginPage } from "./AdminLoginPage";

afterEach(() => vi.unstubAllGlobals());

const admin = {
  id: "a1",
  email: "boss@example.com",
  display_name: "Boss",
  role: "admin",
  is_active: true,
  created_at: "",
};

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/admin/login"]}>
        <Routes>
          <Route path="/admin/login" element={<AdminLoginPage />} />
          <Route path="/admin/ingestion" element={<div>ADMIN INGESTION</div>} />
          <Route path="/admin/forgot-password" element={<div>ADMIN FORGOT</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("AdminLoginPage", () => {
  it("wires BTN-AL1 and BTN-AL2, and has no register link", () => {
    mockFetch();
    renderPage();
    expect(screen.getByTestId("btn-al1")).toHaveTextContent(/sign in/i);
    expect(screen.getByTestId("btn-al2")).toHaveTextContent(/forgot password/i);
    expect(screen.queryByText(/create account/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/register/i)).not.toBeInTheDocument();
  });

  it("shows the generic error on bad credentials", async () => {
    mockFetch({
      status: 401,
      body: { error: { code: "invalid_credentials", message: "Invalid email or password" } },
    });
    renderPage();
    await userEvent.type(screen.getByLabelText("Email"), "boss@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "wrong-password-1");
    await userEvent.click(screen.getByTestId("btn-al1"));
    expect(await screen.findByRole("alert")).toHaveTextContent(/invalid email or password/i);
  });

  it("redirects into the console on success", async () => {
    mockFetch({ status: 200, body: { user: admin } });
    renderPage();
    await userEvent.type(screen.getByLabelText("Email"), "boss@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "admin-console-pw-1");
    await userEvent.click(screen.getByTestId("btn-al1"));
    await waitFor(() => expect(screen.getByText("ADMIN INGESTION")).toBeInTheDocument());
  });

  it("shows the notice it was sent with (e.g. session expired)", () => {
    mockFetch();
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={[{ pathname: "/admin/login", state: { notice: "Expired" } }]}>
          <Routes>
            <Route path="/admin/login" element={<AdminLoginPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(screen.getByRole("status")).toHaveTextContent("Expired");
  });
});

describe("AdminLoginPage rate limit countdown", () => {
  afterEach(() => vi.useRealTimers());

  it("counts down from retry_after, disables submit, re-enables at 0, keeps one reset link outside the box", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const u = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    mockFetch({
      status: 429,
      body: { error: { code: "rate_limited", message: "Too many attempts.", retry_after: 8 } },
    });
    renderPage();
    await u.type(screen.getByLabelText("Email"), "boss@example.com");
    await u.type(screen.getByLabelText("Password"), "wrong-password-1");
    await u.click(screen.getByTestId("btn-al1"));

    const alert = await screen.findByTestId("rate-limit-countdown");
    const live = screen.getByTestId("rate-limit-announcement");
    // announced once when the wait starts; the ticking box is not a live region
    expect(live).toHaveAttribute("aria-live", "polite");
    expect(live).toHaveTextContent(`Too many attempts. Try again in 0:08.`);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(alert).not.toHaveAttribute("aria-live");
    expect(alert).toHaveTextContent("Too many attempts — try again in 0:08");
    expect(screen.getByTestId("btn-al1")).toBeDisabled();
    // no link inside the countdown box; screen readers still find the one reset link
    expect(within(alert).queryByRole("link")).not.toBeInTheDocument();
    const resetLinks = screen.getAllByRole("link", { name: /forgot password/i });
    expect(resetLinks).toHaveLength(1);
    expect(resetLinks[0]).toHaveAttribute("href", "/admin/forgot-password");
    expect(resetLinks[0]).toHaveAttribute("data-testid", "btn-al2");

    await act(() => vi.advanceTimersByTimeAsync(3000));
    expect(screen.getByTestId("rate-limit-countdown")).toHaveTextContent("try again in 0:05");
    expect(live).toHaveTextContent("Too many attempts. Try again in 0:08.");
    expect(screen.getByTestId("btn-al1")).toBeDisabled();

    await act(() => vi.advanceTimersByTimeAsync(5000));
    expect(screen.queryByTestId("rate-limit-countdown")).not.toBeInTheDocument();
    expect(screen.getByTestId("btn-al1")).toBeEnabled();
    // announced once more when it ends
    expect(screen.getByTestId("rate-limit-announcement")).toHaveTextContent(
      "You can try signing in again.",
    );
  });

  it("has 'Remember this device' ticked by default and sends the choice", async () => {
    const fetchMock = mockFetch({ status: 200, body: { user: admin } });
    renderPage();
    const box = screen.getByRole("checkbox", { name: "Remember this device" });
    expect(box).toBeChecked();
    await userEvent.click(box);
    await userEvent.type(screen.getByLabelText("Email"), "boss@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "admin-pw-12345");
    await userEvent.click(screen.getByTestId("btn-al1"));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const init = (fetchMock.mock.calls[0] as unknown[])[1] as RequestInit;
    expect(JSON.parse(init.body as string)).toEqual({
      email: "boss@example.com",
      password: "admin-pw-12345",
      remember: false,
    });
  });
});
