import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Toaster } from "@/components";
import { SettingsPage } from "./SettingsPage";

afterEach(() => vi.unstubAllGlobals());

const TYPES = ["slide_deck", "flashcards", "quiz", "report", "infographic", "audio_overview"];

function tpl(type: string, over: Record<string, unknown> = {}) {
  return {
    artifact_type: type,
    version: 1,
    body: `Prompt for ${type}`,
    is_active: true,
    updated_at: "2026-01-01T00:00:00Z",
    updated_by: null,
    ...over,
  };
}

type Handler = { method: string; match: string; status?: number; body: unknown };

function installFetch(extra: Handler[] = []) {
  const base: Handler[] = [
    { method: "GET", match: "/api/admin/prompts", body: { templates: TYPES.map((t) => tpl(t)) } },
    {
      method: "GET",
      match: "/api/admin/mcp/status",
      body: {
        healthy: true,
        account_email: "bot@example.com",
        last_ok_at: "2026-02-02T00:00:00Z",
        detail: "ok",
        worker_last_heartbeat_at: "2026-02-02T00:05:00Z",
        worker_heartbeat_stale: false,
        jobs_succeeded: 12,
        jobs_failed: 1,
      },
    },
    {
      method: "GET",
      match: "/api/admin/settings/audio",
      body: {
        settings: { voice: "default", style: "conversational" },
        voice_choices: ["default", "warm"],
        style_choices: ["conversational", "brief"],
      },
    },
    {
      method: "GET",
      match: "/api/admin/users",
      body: {
        users: [
          {
            id: "me",
            email: "root@example.com",
            display_name: "Root",
            is_active: true,
            created_at: "2026-01-01T00:00:00Z",
            last_login_at: null,
          },
          {
            id: "u2",
            email: "two@example.com",
            display_name: "Two",
            is_active: true,
            created_at: "2026-01-02T00:00:00Z",
            last_login_at: null,
          },
        ],
      },
    },
    { method: "GET", match: "/api/admin/auth/me", body: { user: { id: "me", email: "root@example.com" } } },
  ];
  const handlers = [...extra, ...base];
  const fn = vi.fn((input: string | URL, init?: RequestInit): Promise<Response> => {
    const url = typeof input === "string" ? input : input.toString();
    const method = (init?.method ?? "GET").toUpperCase();
    const h = handlers.find((x) => x.method === method && url.includes(x.match));
    const status = h?.status ?? (h ? 200 : 404);
    return Promise.resolve({
      ok: status < 300,
      status,
      statusText: String(status),
      json: () => Promise.resolve(h ? h.body : { error: { code: "x", message: "x" } }),
    } as Response);
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

function renderPage(path = "/admin/settings") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/admin/settings" element={<SettingsPage />} />
        </Routes>
        <Toaster />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("SettingsPage", () => {
  it("Generation Prompts: renders six cards and saves an edit as a new version", async () => {
    const fetchMock = installFetch([
      {
        method: "PUT",
        match: "/api/admin/prompts/report",
        body: { template: tpl("report", { version: 2, body: "edited" }) },
      },
    ]);
    renderPage();

    expect(await screen.findByRole("heading", { name: "Report" })).toBeInTheDocument();
    const box = screen.getByLabelText("Report prompt");
    await userEvent.type(box, " extra");
    await userEvent.click(screen.getByTestId("btn-st1-report"));

    await waitFor(() => {
      const put = fetchMock.mock.calls.find(
        (c) => (c[1] as RequestInit)?.method === "PUT" && String(c[0]).includes("/prompts/report"),
      );
      expect(put).toBeDefined();
      expect(JSON.parse((put![1] as RequestInit).body as string)).toEqual({
        body: "Prompt for report extra",
      });
    });
  });

  it("Generation Prompts: Restore default needs a confirm", async () => {
    const fetchMock = installFetch([
      {
        method: "POST",
        match: "/api/admin/prompts/quiz/restore-default",
        body: { template: tpl("quiz", { version: 2 }) },
      },
    ]);
    renderPage();
    await screen.findByRole("heading", { name: "Quiz" });

    await userEvent.click(screen.getByTestId("btn-st2-quiz"));
    await userEvent.click(screen.getByTestId("btn-st2-quiz-confirm"));

    await waitFor(() => {
      const post = fetchMock.mock.calls.find((c) =>
        String(c[0]).includes("/prompts/quiz/restore-default"),
      );
      expect(post).toBeDefined();
    });
  });

  it("NotebookLM: shows the account email and reloads auth", async () => {
    const fetchMock = installFetch([
      { method: "POST", match: "/api/admin/mcp/refresh-auth", status: 204, body: null },
    ]);
    renderPage("/admin/settings?tab=notebooklm");

    expect(await screen.findByText("bot@example.com")).toBeInTheDocument();
    // T043 — system health strip (worker heartbeat + job counters)
    expect(screen.getByTestId("worker-badge")).toHaveTextContent("Worker: OK");
    expect(screen.getByTestId("job-counters")).toHaveTextContent("12 succeeded · 1 failed");
    await userEvent.click(screen.getByTestId("btn-st3"));
    await waitFor(() => {
      const post = fetchMock.mock.calls.find((c) => String(c[0]).includes("/mcp/refresh-auth"));
      expect(post).toBeDefined();
    });
  });

  it("Audio: saves voice/style", async () => {
    const fetchMock = installFetch([
      {
        method: "PUT",
        match: "/api/admin/settings/audio",
        body: {
          settings: { voice: "warm", style: "conversational" },
          voice_choices: ["default", "warm"],
          style_choices: ["conversational", "brief"],
        },
      },
    ]);
    renderPage("/admin/settings?tab=audio");

    const voice = await screen.findByLabelText("Voice");
    await userEvent.selectOptions(voice, "warm");
    await userEvent.click(screen.getByTestId("btn-st4"));

    await waitFor(() => {
      const put = fetchMock.mock.calls.find(
        (c) => (c[1] as RequestInit)?.method === "PUT" && String(c[0]).includes("/settings/audio"),
      );
      expect(put).toBeDefined();
      expect(JSON.parse((put![1] as RequestInit).body as string)).toEqual({
        voice: "warm",
        style: "conversational",
      });
    });
  });

  it("Users: lists admins, blocks self-deactivation, adds an admin", async () => {
    const fetchMock = installFetch([
      {
        method: "POST",
        match: "/api/admin/users",
        status: 201,
        body: {
          id: "u3",
          email: "new@example.com",
          display_name: "New",
          is_active: true,
          created_at: "2026-03-03T00:00:00Z",
          last_login_at: null,
        },
      },
    ]);
    renderPage("/admin/settings?tab=users");

    expect(await screen.findByText("two@example.com")).toBeInTheDocument();
    expect(screen.getByTestId("btn-st6-me")).toBeDisabled();
    expect(screen.getByTestId("btn-st6-u2")).toBeEnabled();

    await userEvent.click(screen.getByTestId("btn-st5"));
    await userEvent.type(await screen.findByLabelText("Email"), "new@example.com");
    await userEvent.type(screen.getByLabelText("Display name"), "New");
    await userEvent.type(screen.getByLabelText("Temporary password"), "temp-pass-1234");
    await userEvent.click(screen.getByTestId("btn-st5-confirm"));

    await waitFor(() => {
      const post = fetchMock.mock.calls.find(
        (c) =>
          (c[1] as RequestInit)?.method === "POST" &&
          String(c[0]).endsWith("/api/admin/users"),
      );
      expect(post).toBeDefined();
      expect(JSON.parse((post![1] as RequestInit).body as string)).toEqual({
        email: "new@example.com",
        display_name: "New",
        password: "temp-pass-1234",
      });
    });
  });

  it("Users: BTN-ST6 deactivates a non-self admin", async () => {
    const fetchMock = installFetch([
      {
        method: "PATCH",
        match: "/api/admin/users/u2",
        status: 200,
        body: {
          id: "u2",
          email: "two@example.com",
          display_name: "Two",
          is_active: false,
          created_at: "2026-01-02T00:00:00Z",
          last_login_at: null,
        },
      },
    ]);
    renderPage("/admin/settings?tab=users");

    await screen.findByText("two@example.com");
    await userEvent.click(screen.getByTestId("btn-st6-u2"));

    await waitFor(() => {
      const patch = fetchMock.mock.calls.find(
        (c) =>
          (c[1] as RequestInit)?.method === "PATCH" && String(c[0]).includes("/api/admin/users/u2"),
      );
      expect(patch).toBeDefined();
      expect(JSON.parse((patch![1] as RequestInit).body as string)).toEqual({ is_active: false });
    });
  });
});
