import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { LoginPage } from "./LoginPage";
import userEvent from "@testing-library/user-event";
import { mockFetch, renderAuthRoute } from "./authTestUtils";

afterEach(() => vi.unstubAllGlobals());

const user = {
  id: "1",
  email: "sam@example.com",
  display_name: "Sam",
  role: "student",
  is_active: true,
  created_at: "",
};

describe("LoginPage", () => {
  it("wires BTN-SL2/SL3/SL4", () => {
    renderAuthRoute("/login");
    expect(screen.getByTestId("btn-sl2")).toHaveTextContent(/sign in/i);
    expect(screen.getByTestId("btn-sl3")).toHaveTextContent(/forgot password/i);
    expect(screen.getByTestId("btn-sl4")).toHaveTextContent(/create account/i);
  });

  it("blocks submit with client-side validation and does not call the API", async () => {
    const fetchMock = mockFetch();
    renderAuthRoute("/login");
    await userEvent.click(screen.getByTestId("btn-sl2"));
    expect(await screen.findByText(/email is required/i)).toBeInTheDocument();
    expect(screen.getByText(/password is required/i)).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("surfaces a server 401 inline", async () => {
    mockFetch({
      status: 401,
      body: { error: { code: "invalid_credentials", message: "Invalid email or password" } },
    });
    renderAuthRoute("/login");
    await userEvent.type(screen.getByLabelText("Email"), "sam@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "whatever-1234");
    await userEvent.click(screen.getByTestId("btn-sl2"));
    expect(await screen.findByRole("alert")).toHaveTextContent(/invalid email or password/i);
  });

  it("redirects to /catalog on success", async () => {
    mockFetch({ status: 200, body: { user } });
    renderAuthRoute("/login");
    await userEvent.type(screen.getByLabelText("Email"), "sam@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "correct-pw-123");
    await userEvent.click(screen.getByTestId("btn-sl2"));
    await waitFor(() => expect(screen.getByText("CATALOG PAGE")).toBeInTheDocument());
  });

  it("returns to the deep link the guard remembered, and shows a notice", async () => {
    mockFetch({ status: 200, body: { user } });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter
          initialEntries={[
            { pathname: "/login", state: { from: "/learn/nn/0/quiz", notice: "Session gone" } },
          ]}
        >
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/learn/nn/0/quiz" element={<div>DEEP LINK</div>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(screen.getByRole("status")).toHaveTextContent("Session gone");
    await userEvent.type(screen.getByLabelText("Email"), "sam@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "correct-pw-123");
    await userEvent.click(screen.getByTestId("btn-sl2"));
    await waitFor(() => expect(screen.getByText("DEEP LINK")).toBeInTheDocument());
  });
});

describe("LoginPage rate limit countdown", () => {
  afterEach(() => vi.useRealTimers());

  it("counts down from retry_after, disables submit, re-enables at 0, keeps one reset link outside the box", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const u = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    mockFetch({
      status: 429,
      body: { error: { code: "rate_limited", message: "Too many attempts.", retry_after: 65 } },
    });
    renderAuthRoute("/login");
    await u.type(screen.getByLabelText("Email"), "sam@example.com");
    await u.type(screen.getByLabelText("Password"), "whatever-1234");
    await u.click(screen.getByTestId("btn-sl2"));

    const alert = await screen.findByTestId("rate-limit-countdown");
    const live = screen.getByTestId("rate-limit-announcement");
    // announced once when the wait starts; the ticking box is not a live region
    expect(live).toHaveAttribute("aria-live", "polite");
    expect(live).toHaveTextContent(`Too many attempts. Try again in 1:05.`);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(alert).not.toHaveAttribute("aria-live");
    expect(alert).toHaveTextContent("Too many attempts — try again in 1:05");
    expect(screen.getByTestId("btn-sl2")).toBeDisabled();
    // no link inside the countdown box; screen readers still find the one reset link
    expect(within(alert).queryByRole("link")).not.toBeInTheDocument();
    const resetLinks = screen.getAllByRole("link", { name: /forgot password/i });
    expect(resetLinks).toHaveLength(1);
    expect(resetLinks[0]).toHaveAttribute("href", "/forgot-password");
    expect(resetLinks[0]).toHaveAttribute("data-testid", "btn-sl3");

    await act(() => vi.advanceTimersByTimeAsync(1000));
    expect(screen.getByTestId("rate-limit-countdown")).toHaveTextContent("try again in 1:04");
    expect(live).toHaveTextContent("Too many attempts. Try again in 1:05.");
    await act(() => vi.advanceTimersByTimeAsync(55_000));
    expect(screen.getByTestId("rate-limit-countdown")).toHaveTextContent("try again in 0:09");
    expect(screen.getByTestId("btn-sl2")).toBeDisabled();

    await act(() => vi.advanceTimersByTimeAsync(9_000));
    expect(screen.queryByTestId("rate-limit-countdown")).not.toBeInTheDocument();
    expect(screen.getByTestId("btn-sl2")).toBeEnabled();
    // announced once more when it ends
    expect(screen.getByTestId("rate-limit-announcement")).toHaveTextContent(
      "You can try signing in again.",
    );
  });

  it("has 'Remember this device' ticked by default and sends it", async () => {
    const fetchMock = mockFetch({ status: 200, body: { user } });
    renderAuthRoute("/login");
    const box = screen.getByRole("checkbox", { name: "Remember this device" });
    expect(box).toBeChecked();
    await userEvent.type(screen.getByLabelText("Email"), "sam@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "correct-pw-123");
    await userEvent.click(screen.getByTestId("btn-sl2"));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const init = (fetchMock.mock.calls[0] as unknown[])[1] as RequestInit;
    const body: unknown = JSON.parse(init.body as string);
    expect(body).toEqual({ email: "sam@example.com", password: "correct-pw-123", remember: true });
  });

  it("sends remember=false when the box is unticked", async () => {
    const fetchMock = mockFetch({ status: 200, body: { user } });
    renderAuthRoute("/login");
    await userEvent.click(screen.getByLabelText("Remember this device"));
    await userEvent.type(screen.getByLabelText("Email"), "sam@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "correct-pw-123");
    await userEvent.click(screen.getByTestId("btn-sl2"));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const init = (fetchMock.mock.calls[0] as unknown[])[1] as RequestInit;
    expect(JSON.parse(init.body as string).remember).toBe(false);
  });
});
