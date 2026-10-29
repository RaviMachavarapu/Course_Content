import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { mockFetch } from "./authTestUtils";
import { ForgotPasswordPage } from "./ForgotPasswordPage";

afterEach(() => vi.unstubAllGlobals());

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/forgot-password"]}>
        <Routes>
          <Route path="/forgot-password" element={<ForgotPasswordPage />} />
          <Route path="/login" element={<div>LOGIN PAGE</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ForgotPasswordPage", () => {
  it("blocks submit on invalid email", async () => {
    const fetchMock = mockFetch();
    renderPage();
    await userEvent.click(screen.getByTestId("btn-fp1"));
    expect(await screen.findByText(/email is required/i)).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("shows a confirmation after a successful request, without revealing whether the account exists", async () => {
    mockFetch({ status: 202, body: {} });
    renderPage();
    await userEvent.type(screen.getByLabelText("Email"), "sam@example.com");
    await userEvent.click(screen.getByTestId("btn-fp1"));
    await waitFor(() => expect(screen.getByText(/check your email/i)).toBeInTheDocument());
  });

  it.each([
    [
      {
        status: 429,
        body: { error: { code: "rate_limited", message: "Too many attempts. Try again later." } },
      },
      "Too many attempts — please try again later.",
    ],
    [
      { status: 404, body: { error: { code: "password_reset_disabled", message: "x" } } },
      "Password reset is turned off",
    ],
  ])("explains a failed request (%#)", async (reply, text) => {
    mockFetch(reply);
    renderPage();
    await userEvent.type(screen.getByLabelText("Email"), "sam@example.com");
    await userEvent.click(screen.getByTestId("btn-fp1"));
    expect(await screen.findByRole("alert")).toHaveTextContent(text);
  });
});
