import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { mockFetch } from "@/student/auth/authTestUtils";
import { AdminResetPasswordPage } from "./AdminResetPasswordPage";

afterEach(() => vi.unstubAllGlobals());

function renderPage(initial: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[initial]}>
        <Routes>
          <Route path="/admin/reset-password" element={<AdminResetPasswordPage />} />
          <Route path="/admin/login" element={<div>ADMIN LOGIN</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("AdminResetPasswordPage", () => {
  it("shows an invalid-link message when no token is present", () => {
    renderPage("/admin/reset-password");
    expect(screen.getByText(/invalid reset link/i)).toBeInTheDocument();
  });

  it("redirects to /admin/login on success", async () => {
    mockFetch({ status: 204, body: undefined });
    renderPage("/admin/reset-password?token=abc123");
    await userEvent.type(screen.getByLabelText("New password"), "brand-new-admin-pw-2");
    await userEvent.type(screen.getByLabelText("Confirm password"), "brand-new-admin-pw-2");
    await userEvent.click(screen.getByTestId("btn-admin-reset-confirm"));
    await waitFor(() => expect(screen.getByText("ADMIN LOGIN")).toBeInTheDocument());
  });
});
