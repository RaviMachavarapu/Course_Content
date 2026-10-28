import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { render, screen, waitFor } from "@testing-library/react";
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
