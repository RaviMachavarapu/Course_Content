import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { InspectPage } from "./InspectPage";

afterEach(() => vi.unstubAllGlobals());

const V2 = {
  id: "v2",
  revision: 2,
  redo_note: "shorter",
  focus_prompt_used: "PROMPT BODY v2",
  prompt_template_version: 3,
  generation_job_id: "job-2",
  notebooklm_artifact_id: "nlm-2",
  created_at: "2026-01-02T00:00:00Z",
  content_json: {
    title: "The Report",
    read_minutes: 5,
    sections: [{ heading: "Intro", html: "<p>body</p>" }],
  },
  content_html: "<h1>The Report</h1><p>body</p>",
  media: [{ kind: "report_pdf", url: "/api/media/r.pdf", size_bytes: 1, page_index: null }],
};

const BODY = {
  artifact: { id: "a1", type: "report", status: "ready", module_id: "m1", last_error: null },
  notebooklm_notebook_id: "nb-1",
  viewing: V2,
  history: [
    {
      id: "v2",
      revision: 2,
      created_at: "2026-01-02T00:00:00Z",
      redo_note: "shorter",
      is_current: true,
      is_published: false,
    },
    {
      id: "v1",
      revision: 1,
      created_at: "2026-01-01T00:00:00Z",
      redo_note: null,
      is_current: false,
      is_published: true,
    },
  ],
};

function installFetch(byUrl: (url: string) => unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string | URL) =>
      Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve(byUrl(typeof input === "string" ? input : input.toString())),
      } as Response),
    ),
  );
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/admin/artifacts/a1"]}>
        <Routes>
          <Route path="/admin/artifacts/:artifactId" element={<InspectPage />} />
          <Route path="/admin/modules/:moduleId/staging" element={<div>STAGING</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("InspectPage", () => {
  it("renders the current version content + metadata + BTN-AI2 back link", async () => {
    installFetch(() => BODY);
    renderPage();

    expect(await screen.findByRole("heading", { name: "The Report" })).toBeInTheDocument();
    expect(screen.getByText("PROMPT BODY v2")).toBeInTheDocument();
    expect(screen.getByText("job-2")).toBeInTheDocument();
    expect(screen.getByText("nb-1")).toBeInTheDocument();
    expect(screen.getByTestId("btn-ai2")).toHaveAttribute("href", "/admin/modules/m1/staging");
  });

  it("switches version via BTN-AI1", async () => {
    installFetch((url) =>
      url.includes("version=v1") ? { ...BODY, viewing: { ...V2, revision: 1 } } : BODY,
    );
    renderPage();
    await screen.findByRole("heading", { name: "The Report" });

    await userEvent.selectOptions(screen.getByTestId("btn-ai1"), "v1");
    // metadata "Revision" row updates to 1
    await screen.findByText("1");
  });
});
