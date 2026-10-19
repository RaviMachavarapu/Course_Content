import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { render } from "@testing-library/react";
import { LoginPage } from "./LoginPage";
import { RegisterPage } from "./RegisterPage";

/** Render an auth page inside a router that also has a detectable `/catalog`. */
export function renderAuthRoute(initial: "/login" | "/register"): ReturnType<typeof render> {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[initial]}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
          <Route path="/catalog" element={<div>CATALOG PAGE</div>} />
          <Route path="/forgot-password" element={<div>FORGOT PAGE</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

interface MockResponseInit {
  status: number;
  body: unknown;
}

function toResponse(init: MockResponseInit): Response {
  return {
    ok: init.status >= 200 && init.status < 300,
    status: init.status,
    statusText: String(init.status),
    json: () => Promise.resolve(init.body),
  } as Response;
}

/** Install a `fetch` mock that returns the given responses in order. */
export function mockFetch(...responses: MockResponseInit[]): ReturnType<typeof vi.fn> {
  const fn = vi.fn((): Promise<Response> =>
    Promise.resolve(toResponse(responses.shift() ?? { status: 200, body: {} })),
  );
  vi.stubGlobal("fetch", fn);
  return fn;
}

/** Install a `fetch` mock that routes by URL substring; unmatched -> 404. */
export function mockFetchRoutes(
  routes: Record<string, MockResponseInit>,
): ReturnType<typeof vi.fn> {
  const fn = vi.fn((input: string | URL): Promise<Response> => {
    const url = typeof input === "string" ? input : input.toString();
    const key = Object.keys(routes).find((k) => url.includes(k));
    return Promise.resolve(
      toResponse(
        key ? routes[key]! : { status: 404, body: { error: { code: "not_found", message: "x" } } },
      ),
    );
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}
