import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { render, screen } from "@testing-library/react";
import { mockFetchRoutes } from "@/student/auth/authTestUtils";
import { RequireAdmin } from "./guards";

afterEach(() => vi.unstubAllGlobals());

const user = (role: "admin" | "student") => ({
  id: "1",
  email: `${role}@example.com`,
  display_name: role,
  role,
  is_active: true,
  created_at: "",
});

function renderAt(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/admin" element={<RequireAdmin />}>
            <Route path="ingestion" element={<div>ADMIN INGESTION</div>} />
            <Route path="*" element={<div>ADMIN 404</div>} />
          </Route>
          <Route path="/admin/login" element={<div>ADMIN LOGIN</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const UNAUTH = { status: 401, body: { error: { code: "unauthorized", message: "x" } } };

describe("RequireAdmin", () => {
  it("renders the admin shell for a valid admin session", async () => {
    mockFetchRoutes({
      "/api/admin/auth/me": { status: 200, body: { user: user("admin") } },
      "/api/student/auth/me": UNAUTH,
    });
    renderAt("/admin/ingestion");
    expect(await screen.findByText("ADMIN INGESTION")).toBeInTheDocument();
  });

  it("redirects anonymous visitors to /admin/login", async () => {
    mockFetchRoutes({ "/api/admin/auth/me": UNAUTH, "/api/student/auth/me": UNAUTH });
    renderAt("/admin/ingestion");
    expect(await screen.findByText("ADMIN LOGIN")).toBeInTheDocument();
  });

  it("shows the student 404 (no admin chrome) for a student session (US-N3)", async () => {
    mockFetchRoutes({
      "/api/admin/auth/me": UNAUTH,
      "/api/student/auth/me": { status: 200, body: { user: user("student") } },
    });
    renderAt("/admin/secret");
    expect(await screen.findByText(/page not found/i)).toBeInTheDocument();
    expect(screen.queryByText("ADMIN INGESTION")).not.toBeInTheDocument();
    expect(screen.queryByText("ADMIN LOGIN")).not.toBeInTheDocument();
    // student chrome present, not admin
    expect(screen.getByRole("link", { name: /catalog/i })).toBeInTheDocument();
  });
});
