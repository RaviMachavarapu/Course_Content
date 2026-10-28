import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
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
