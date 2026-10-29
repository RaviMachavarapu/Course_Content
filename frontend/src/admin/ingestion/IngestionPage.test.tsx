import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { IngestionPage } from "./IngestionPage";
import { uploadPdf } from "./chunkedUpload";

vi.mock("./chunkedUpload", () => ({ uploadPdf: vi.fn() }));

beforeEach(() => {
  vi.mocked(uploadPdf).mockReset();
});
afterEach(() => vi.unstubAllGlobals());

interface Handler {
  method: string;
  match: string;
  status?: number;
  body: unknown;
}

function installFetch(handlers: Handler[]): ReturnType<typeof vi.fn> {
  const fn = vi.fn((input: string | URL, init?: RequestInit): Promise<Response> => {
    const url = typeof input === "string" ? input : input.toString();
    const method = (init?.method ?? "GET").toUpperCase();
    const h = handlers.find((x) => x.method === method && url.includes(x.match));
    const status = h?.status ?? (h ? 200 : 404);
    return Promise.resolve({
      ok: status < 300,
      status,
      statusText: String(status),
      json: () => Promise.resolve(h ? h.body : { error: { code: "not_found", message: "x" } }),
    } as Response);
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/admin/ingestion"]}>
        <Routes>
          <Route path="/admin/ingestion" element={<IngestionPage />} />
          <Route path="/admin/modules/:id/staging" element={<div>STAGING PAGE</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const HEALTHY = {
  method: "GET",
  match: "/api/admin/mcp/status",
  body: { healthy: true, detail: "FixtureProvider" },
};
const NO_COURSES = { method: "GET", match: "/api/admin/courses", body: { courses: [] } };
const EMPTY_PIPELINE = {
  method: "GET",
  match: "/api/admin/pipeline",
  body: { rows: [], page: 1, page_size: 5, total: 0 },
};

describe("IngestionPage", () => {
  it("shows the form and BTN-IG6", () => {
    installFetch([HEALTHY, NO_COURSES, EMPTY_PIPELINE]);
    renderPage();
    expect(
      screen.getByRole("heading", { name: /Create New AI Course Module/i }),
    ).toBeInTheDocument();
    expect(screen.getByTestId("btn-ig6")).toHaveTextContent(/Generate Course Material/i);
    expect(screen.getByRole("heading", { name: /Recent Pipeline/i })).toBeInTheDocument();
  });

  it("blocks submit with validation and does not call the API", async () => {
    const fetchMock = installFetch([HEALTHY, NO_COURSES, EMPTY_PIPELINE]);
    renderPage();
    await userEvent.click(screen.getByTestId("btn-ig6"));
    expect(await screen.findByText("Add a link or at least one PDF")).toBeInTheDocument();
    expect(screen.getByText(/Course title is required/i)).toBeInTheDocument();
    const posts = fetchMock.mock.calls.filter((c) => (c[1] as RequestInit)?.method === "POST");
    expect(posts).toHaveLength(0);
  });

  it("requires at least one artifact type", async () => {
    installFetch([HEALTHY, NO_COURSES, EMPTY_PIPELINE]);
    renderPage();
    for (const t of [
      "slide_deck",
      "flashcards",
      "quiz",
      "report",
      "infographic",
      "audio_overview",
    ]) {
      await userEvent.click(screen.getByTestId(`type-${t}`));
    }
    await userEvent.click(screen.getByTestId("btn-ig6"));
    expect(await screen.findByText(/at least one artifact type/i)).toBeInTheDocument();
  });

  it("creates a course + module then redirects to staging", async () => {
    installFetch([
      HEALTHY,
      NO_COURSES,
      EMPTY_PIPELINE,
      // more specific match first — installFetch returns the first hit
      {
        method: "POST",
        match: "/api/admin/courses/c1/modules",
        status: 201,
        body: { module: { id: "m1" }, job_ids: ["j1"] },
      },
      { method: "POST", match: "/api/admin/courses", status: 201, body: { course: { id: "c1" } } },
    ]);
    renderPage();

    await userEvent.type(screen.getByLabelText("Link (optional)"), "https://youtu.be/abc");
    await userEvent.type(screen.getByLabelText("Course title"), "Intro to ML");
    await userEvent.type(screen.getByLabelText("Module title"), "Module 1");
    await userEvent.click(screen.getByTestId("btn-ig6"));

    await waitFor(() => expect(screen.getByText("STAGING PAGE")).toBeInTheDocument());
  });

  it("shows an options section per checked type and hides it when unchecked", async () => {
    installFetch([HEALTHY, NO_COURSES, EMPTY_PIPELINE]);
    renderPage();
    // all six checked by default
    expect(screen.getByTestId("options-audio_overview")).toBeInTheDocument();
    expect(screen.getByTestId("options-slide_deck")).toBeInTheDocument();

    await userEvent.click(screen.getByTestId("type-slide_deck"));
    expect(screen.queryByTestId("options-slide_deck")).not.toBeInTheDocument();
    expect(screen.getByTestId("options-audio_overview")).toBeInTheDocument();
  });

  it("sends per-type generation options with the create-module request", async () => {
    const fetchMock = installFetch([
      HEALTHY,
      NO_COURSES,
      EMPTY_PIPELINE,
      {
        method: "POST",
        match: "/api/admin/courses/c1/modules",
        status: 201,
        body: { module: { id: "m1" }, job_ids: ["j1"] },
      },
      { method: "POST", match: "/api/admin/courses", status: 201, body: { course: { id: "c1" } } },
    ]);
    renderPage();

    await userEvent.type(screen.getByLabelText("Link (optional)"), "https://youtu.be/abc");
    await userEvent.type(screen.getByLabelText("Course title"), "Intro to ML");
    await userEvent.type(screen.getByLabelText("Module title"), "Module 1");

    const audioSection = within(screen.getByTestId("options-audio_overview"));
    await userEvent.click(audioSection.getByRole("radio", { name: "Brief" }));
    await userEvent.type(
      within(screen.getByTestId("options-quiz")).getByLabelText("What should the topic be?"),
      "  Chapter 2 only  ",
    );

    await userEvent.click(screen.getByTestId("btn-ig6"));
    await waitFor(() => expect(screen.getByText("STAGING PAGE")).toBeInTheDocument());

    const modulePost = fetchMock.mock.calls.find((c) =>
      String(c[0]).includes("/api/admin/courses/c1/modules"),
    );
    const body = JSON.parse((modulePost![1] as RequestInit).body as string);
    expect(body.options.audio_overview.format).toBe("brief");
    expect(body.options.slide_deck).toEqual({
      format: "detailed",
      length: "default",
      language: "en",
      review_outline: false,
    });
    // only non-blank prompts are sent, trimmed; the rest use the template
    expect(body.prompts).toEqual({ quiz: "Chapter 2 only" });
  });

  it("blocks submit until a document report has a template", async () => {
    const fetchMock = installFetch([HEALTHY, NO_COURSES, EMPTY_PIPELINE]);
    renderPage();
    await userEvent.type(screen.getByLabelText("Link (optional)"), "https://youtu.be/abc");
    await userEvent.type(screen.getByLabelText("Course title"), "Intro to ML");
    await userEvent.type(screen.getByLabelText("Module title"), "Module 1");
    const report = within(screen.getByTestId("options-report"));
    await userEvent.click(report.getByRole("radio", { name: "Document" }));

    await userEvent.click(screen.getByTestId("btn-ig6"));
    expect(await report.findByText("Choose a report template.")).toBeInTheDocument();
    expect(
      fetchMock.mock.calls.some((c) => (c[1] as RequestInit | undefined)?.method === "POST"),
    ).toBe(false);

    await userEvent.click(report.getByRole("radio", { name: "Study guide" }));
    expect(report.queryByText("Choose a report template.")).not.toBeInTheDocument();
  });

  it("warns when NotebookLM is disconnected but still allows submit", async () => {
    installFetch([
      { method: "GET", match: "/api/admin/mcp/status", body: { healthy: false, detail: "down" } },
      NO_COURSES,
      EMPTY_PIPELINE,
    ]);
    renderPage();
    expect(await screen.findByText(/NotebookLM is disconnected/i)).toBeInTheDocument();
    expect(screen.getByTestId("btn-ig6")).toBeEnabled();
  });
});

describe("IngestionPage PDF sources", () => {
  const MODULE_OK = [
    {
      method: "POST",
      match: "/api/admin/courses/c1/modules",
      status: 201,
      body: { module: { id: "m1" }, job_ids: ["j1"] },
    },
    { method: "POST", match: "/api/admin/courses", status: 201, body: { course: { id: "c1" } } },
  ];

  function pdf(name: string): File {
    return new File(["%PDF-"], name, { type: "application/pdf" });
  }

  async function fillRest() {
    await userEvent.type(screen.getByLabelText("Course title"), "Intro to ML");
    await userEvent.type(screen.getByLabelText("Module title"), "Module 1");
  }

  function addPdfs(...names: string[]) {
    fireEvent.drop(screen.getByTestId("pdf-dropzone"), {
      dataTransfer: { files: names.map(pdf) },
    });
  }

  it("labels the link optional and has a PDF section", () => {
    installFetch([HEALTHY, NO_COURSES, EMPTY_PIPELINE]);
    renderPage();
    expect(screen.getByLabelText("Link (optional)")).toBeInTheDocument();
    expect(
      screen.getByText("YouTube, Google Drive, a direct .pdf link, or a web page"),
    ).toBeInTheDocument();
    expect(screen.getByText("PDF files (optional)")).toBeInTheDocument();
  });

  it("submits PDF-only with upload_ids and no source_url", async () => {
    vi.mocked(uploadPdf).mockResolvedValue("u1");
    const fetchMock = installFetch([HEALTHY, NO_COURSES, EMPTY_PIPELINE, ...MODULE_OK]);
    renderPage();
    await fillRest();
    addPdfs("a.pdf");
    await waitFor(() => expect(screen.getByTestId("btn-ig6")).toHaveTextContent(/Generate/));
    await userEvent.click(screen.getByTestId("btn-ig6"));
    await waitFor(() => expect(screen.getByText("STAGING PAGE")).toBeInTheDocument());

    const post = fetchMock.mock.calls.find((c) =>
      String(c[0]).includes("/api/admin/courses/c1/modules"),
    );
    const body = JSON.parse((post![1] as RequestInit).body as string);
    expect(body.upload_ids).toEqual(["u1"]);
    expect(body.source_url).toBeUndefined();
  });

  it("blocks submit while a PDF failed, then sends the rest in list order", async () => {
    vi.mocked(uploadPdf)
      .mockResolvedValueOnce("u1")
      .mockRejectedValueOnce(new Error("b.pdf is not a PDF"))
      .mockResolvedValueOnce("u3");
    const fetchMock = installFetch([HEALTHY, NO_COURSES, EMPTY_PIPELINE, ...MODULE_OK]);
    renderPage();
    await fillRest();
    addPdfs("a.pdf", "b.pdf", "c.pdf");
    expect(await screen.findByText("b.pdf is not a PDF")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId("btn-ig6")).toHaveTextContent(/Generate/));
    await userEvent.click(screen.getByTestId("btn-ig6"));
    expect(await screen.findByText("Retry or remove b.pdf")).toBeInTheDocument();
    expect(
      fetchMock.mock.calls.some((c) => (c[1] as RequestInit | undefined)?.method === "POST"),
    ).toBe(false);

    await userEvent.click(screen.getByRole("button", { name: "Remove b.pdf" }));
    expect(screen.queryByText("Retry or remove b.pdf")).not.toBeInTheDocument();
    await userEvent.click(screen.getByTestId("btn-ig6"));
    await waitFor(() => expect(screen.getByText("STAGING PAGE")).toBeInTheDocument());
    const post = fetchMock.mock.calls.find((c) =>
      String(c[0]).includes("/api/admin/courses/c1/modules"),
    );
    expect(JSON.parse((post![1] as RequestInit).body as string).upload_ids).toEqual(["u1", "u3"]);
  });

  it("names only the first failed PDF", async () => {
    vi.mocked(uploadPdf)
      .mockRejectedValueOnce(new Error("a.pdf is not a PDF"))
      .mockRejectedValueOnce(new Error("b.pdf is not a PDF"));
    installFetch([HEALTHY, NO_COURSES, EMPTY_PIPELINE]);
    renderPage();
    await userEvent.type(screen.getByLabelText("Link (optional)"), "https://youtu.be/abc");
    await fillRest();
    addPdfs("a.pdf", "b.pdf");
    expect(await screen.findByText("b.pdf is not a PDF")).toBeInTheDocument();
    await userEvent.click(screen.getByTestId("btn-ig6"));
    expect(await screen.findByText("Retry or remove a.pdf")).toBeInTheDocument();
    expect(screen.queryByText("Retry or remove b.pdf")).not.toBeInTheDocument();
  });

  it("shows the empty-sources message and does not POST", async () => {
    const fetchMock = installFetch([HEALTHY, NO_COURSES, EMPTY_PIPELINE]);
    renderPage();
    await fillRest();
    await userEvent.click(screen.getByTestId("btn-ig6"));
    expect(await screen.findByText("Add a link or at least one PDF")).toBeInTheDocument();
    expect(
      fetchMock.mock.calls.some((c) => (c[1] as RequestInit | undefined)?.method === "POST"),
    ).toBe(false);
  });

  it("still validates a non-empty link", async () => {
    installFetch([HEALTHY, NO_COURSES, EMPTY_PIPELINE]);
    renderPage();
    await userEvent.type(screen.getByLabelText("Link (optional)"), "not a url");
    await userEvent.click(screen.getByTestId("btn-ig6"));
    expect(await screen.findByText(/Enter a valid http\(s\) URL/)).toBeInTheDocument();
  });

  it("disables Create with 'Uploading 1 of 2…' while files upload", async () => {
    vi.mocked(uploadPdf).mockReturnValue(new Promise(() => {}));
    installFetch([HEALTHY, NO_COURSES, EMPTY_PIPELINE]);
    renderPage();
    addPdfs("a.pdf", "b.pdf");
    await waitFor(() =>
      expect(screen.getByTestId("btn-ig6")).toHaveTextContent("Uploading 1 of 2…"),
    );
    expect(screen.getByTestId("btn-ig6")).toBeDisabled();
  });

  it("link-only submit sends no upload_ids", async () => {
    const fetchMock = installFetch([HEALTHY, NO_COURSES, EMPTY_PIPELINE, ...MODULE_OK]);
    renderPage();
    await userEvent.type(screen.getByLabelText("Link (optional)"), "https://youtu.be/abc");
    await fillRest();
    await userEvent.click(screen.getByTestId("btn-ig6"));
    await waitFor(() => expect(screen.getByText("STAGING PAGE")).toBeInTheDocument());
    const post = fetchMock.mock.calls.find((c) =>
      String(c[0]).includes("/api/admin/courses/c1/modules"),
    );
    const body = JSON.parse((post![1] as RequestInit).body as string);
    expect(body.source_url).toBe("https://youtu.be/abc");
    expect(body.upload_ids).toBeUndefined();
  });

  it("retrying after the module step failed reuses the course it already created", async () => {
    let moduleCalls = 0;
    const fn = vi.fn((input: string | URL, init?: RequestInit): Promise<Response> => {
      const url = typeof input === "string" ? input : input.toString();
      const method = (init?.method ?? "GET").toUpperCase();
      let status = 200;
      let body: unknown = { error: { code: "not_found", message: "x" } };
      if (method === "POST" && url.includes("/api/admin/courses/c1/modules")) {
        moduleCalls += 1;
        [status, body] =
          moduleCalls === 1
            ? [502, { error: { code: "bad_gateway", message: "Bad gateway" } }]
            : [201, { module: { id: "m1" }, job_ids: ["j1"] }];
      } else if (method === "POST" && url.includes("/api/admin/courses")) {
        [status, body] = [201, { course: { id: "c1" } }];
      } else if (url.includes("/api/admin/mcp/status")) body = HEALTHY.body;
      else if (url.includes("/api/admin/pipeline")) body = EMPTY_PIPELINE.body;
      else if (url.includes("/api/admin/courses"))
        body = {
          courses:
            moduleCalls > 0
              ? [
                  {
                    id: "c1",
                    title: "Intro to ML",
                    slug: "intro",
                    status: "draft",
                    module_count: 0,
                  },
                ]
              : [],
        };
      else status = 404;
      return Promise.resolve({
        ok: status < 300,
        status,
        statusText: String(status),
        json: () => Promise.resolve(body),
      } as Response);
    });
    vi.stubGlobal("fetch", fn);
    renderPage();

    await userEvent.type(screen.getByLabelText("Link (optional)"), "https://youtu.be/abc");
    await userEvent.type(screen.getByLabelText("Course title"), "Intro to ML");
    await userEvent.type(screen.getByLabelText("Module title"), "Module 1");
    await userEvent.click(screen.getByTestId("btn-ig6"));

    expect(await screen.findByText(/was created/i)).toBeInTheDocument();
    await userEvent.click(screen.getByTestId("btn-ig6"));
    await waitFor(() => expect(screen.getByText("STAGING PAGE")).toBeInTheDocument());

    const coursePosts = fn.mock.calls.filter(
      (c) => c[1]?.method === "POST" && String(c[0]).endsWith("/api/admin/courses"),
    );
    expect(coursePosts).toHaveLength(1);
    expect(moduleCalls).toBe(2);
  });
});
