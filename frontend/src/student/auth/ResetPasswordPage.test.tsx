import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { mockFetch } from "./authTestUtils";
import { ResetPasswordPage } from "./ResetPasswordPage";

afterEach(() => vi.unstubAllGlobals());

function renderPage(initial: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[initial]}>
        <Routes>
          <Route path="/reset-password" element={<ResetPasswordPage />} />
          <Route path="/login" element={<div>LOGIN PAGE</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ResetPasswordPage", () => {
  it("shows an invalid-link message when no token is present", () => {
    renderPage("/reset-password");
    expect(screen.getByText(/invalid reset link/i)).toBeInTheDocument();
  });

  it("blocks submit with client-side validation", async () => {
    const fetchMock = mockFetch();
    renderPage("/reset-password?token=abc123");
    await userEvent.click(screen.getByTestId("btn-reset-confirm"));
    expect(await screen.findByText(/at least 10 characters/i)).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("surfaces an invalid/expired token error from the server", async () => {
    mockFetch({
      status: 422,
      body: { error: { code: "invalid_token", message: "This reset link is invalid or has expired." } },
    });
    renderPage("/reset-password?token=abc123");
    await userEvent.type(screen.getByLabelText("New password"), "brand-new-pw-2");
    await userEvent.type(screen.getByLabelText("Confirm password"), "brand-new-pw-2");
    await userEvent.click(screen.getByTestId("btn-reset-confirm"));
    expect(await screen.findByRole("alert")).toHaveTextContent(/invalid or has expired/i);
  });

  it("redirects to /login on success", async () => {
    mockFetch({ status: 204, body: undefined });
    renderPage("/reset-password?token=abc123");
    await userEvent.type(screen.getByLabelText("New password"), "brand-new-pw-2");
    await userEvent.type(screen.getByLabelText("Confirm password"), "brand-new-pw-2");
    await userEvent.click(screen.getByTestId("btn-reset-confirm"));
    await waitFor(() => expect(screen.getByText("LOGIN PAGE")).toBeInTheDocument());
  });
});
