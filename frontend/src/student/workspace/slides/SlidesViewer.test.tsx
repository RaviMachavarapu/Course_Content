import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SlidesViewer } from "./SlidesViewer";

afterEach(() => vi.unstubAllGlobals());

function artifact(slideLastIndex: number | null = null) {
  return {
    id: "a-slides",
    type: "slide_deck",
    module_id: "m1",
    module_index: 0,
    course_slug: "nn",
    revision: 1,
    content_json: {
      slides: [
        { title: "Intro", notes: "welcome note", tags: ["overview"] },
        { title: "Middle", notes: "middle note", tags: [] },
        { title: "End", notes: "closing note", tags: ["recap"] },
      ],
    },
    content_html: null,
    media: [
      { kind: "pptx", url: "/api/media/deck.pptx", page_index: null },
      { kind: "slide_png", url: "/api/media/s0.png", page_index: 0 },
      { kind: "slide_png", url: "/api/media/s1.png", page_index: 1 },
      { kind: "slide_png", url: "/api/media/s2.png", page_index: 2 },
    ],
    completed: false,
    slide_last_index: slideLastIndex,
    audio_position_seconds: null,
  };
}

function installFetch(art: unknown) {
  const fn = vi.fn((input: string | URL, init?: RequestInit): Promise<Response> => {
    const url = typeof input === "string" ? input : input.toString();
    const method = (init?.method ?? "GET").toUpperCase();
    let body: unknown = { error: { code: "x", message: "x" } };
    let status = 404;
    if (url.includes("/progress") && method === "PUT") {
      body = {
        completed: true,
        slide_last_index: 2,
        audio_position_seconds: null,
        course_percent_complete: 50,
      };
      status = 200;
    } else if (url.includes("/api/student/artifacts/")) {
      body = art;
      status = 200;
    }
    return Promise.resolve({
      ok: status < 300,
      status,
      statusText: String(status),
      json: () => Promise.resolve(body),
    } as Response);
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

function renderViewer() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <SlidesViewer artifactId="a-slides" slug="nn" />
    </QueryClientProvider>,
  );
}

describe("SlidesViewer math", () => {
  it("draws a formula in the notes", async () => {
    const art = artifact();
    art.content_json.slides[0]!.notes = "Rate of $S_N2$";
    installFetch(art);
    const { container } = renderViewer();
    await screen.findByTestId("slide-image");
    expect(container.querySelector(".katex")).not.toBeNull();
  });
});

describe("SlidesViewer", () => {
  it("shows the first slide, counter, notes, and gates Prev at the start", async () => {
    installFetch(artifact());
    renderViewer();

    const img = await screen.findByTestId("slide-image");
    expect(img).toHaveAttribute("src", "/api/media/s0.png");
    expect(screen.getByText("Slide 1 of 3")).toBeInTheDocument();
    expect(screen.getByText("welcome note")).toBeInTheDocument();
    expect(screen.getByText("overview")).toBeInTheDocument();
    expect(screen.getByTestId("btn-sd1")).toBeDisabled();
    expect(screen.getByTestId("btn-sd2")).toBeEnabled();
    expect(screen.getByTestId("btn-sd4")).toHaveAttribute("href", "/api/media/deck.pptx");
  });

  it("navigates forward, updates notes, and marks complete on the last slide", async () => {
    const fetchMock = installFetch(artifact());
    renderViewer();
    await screen.findByTestId("slide-image");

    await userEvent.click(screen.getByTestId("btn-sd2"));
    expect(screen.getByText("Slide 2 of 3")).toBeInTheDocument();
    expect(screen.getByText("middle note")).toBeInTheDocument();

    await userEvent.click(screen.getByTestId("btn-sd2"));
    expect(screen.getByText("Slide 3 of 3")).toBeInTheDocument();
    expect(screen.getByTestId("btn-sd2")).toBeDisabled();

    await waitFor(() => {
      const put = fetchMock.mock.calls.find(
        (c) =>
          (c[1] as RequestInit)?.method === "PUT" && String(c[0]).includes("a-slides/progress"),
      );
      expect(put).toBeDefined();
      expect(JSON.parse((put![1] as RequestInit).body as string)).toEqual({
        completed: true,
        slide_last_index: 2,
      });
    });
  });

  it("resumes at slide_last_index", async () => {
    installFetch(artifact(1));
    renderViewer();
    expect(await screen.findByText("Slide 2 of 3")).toBeInTheDocument();
    expect(screen.getByTestId("slide-image")).toHaveAttribute("src", "/api/media/s1.png");
  });
});

describe("SlidesViewer handout PDF link", () => {
  it("links the handout PDF when present, leaving the pptx button", async () => {
    const a = artifact();
    a.media.push({ kind: "slides_handout_pdf", url: "/api/media/h.pdf", page_index: null });
    installFetch(a);
    renderViewer();
    expect(await screen.findByTestId("btn-sd5")).toHaveAttribute("href", "/api/media/h.pdf");
    expect(screen.getByTestId("btn-sd4")).toHaveAttribute("href", "/api/media/deck.pptx");
  });
  it("hides the link when absent", async () => {
    installFetch(artifact());
    renderViewer();
    await screen.findByTestId("slide-image");
    expect(screen.queryByTestId("btn-sd5")).toBeNull();
  });
});

describe("SlidesViewer saving", () => {
  it("saves once per position, not again every time the cached artifact updates", async () => {
    const fetchMock = installFetch(artifact());
    renderViewer();
    await screen.findByTestId("slide-image");
    await new Promise((r) => setTimeout(r, 1500));
    const puts = fetchMock.mock.calls.filter(
      (c) => (c[1] as RequestInit)?.method === "PUT" && String(c[0]).includes("/progress"),
    );
    expect(puts).toHaveLength(1);
  });
});
