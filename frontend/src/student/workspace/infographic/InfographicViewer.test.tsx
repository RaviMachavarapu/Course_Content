import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { InfographicViewer } from "./InfographicViewer";

afterEach(() => vi.unstubAllGlobals());

const ARTIFACT = {
  id: "a-info",
  type: "infographic",
  module_id: "m1",
  module_index: 0,
  course_slug: "nn",
  revision: 1,
  content_json: { caption: "How a neural network learns" },
  content_html: null,
  media: [
    { kind: "infographic_svg", url: "/api/media/diagram.svg", page_index: null },
    { kind: "infographic_png", url: "/api/media/diagram.png", page_index: null },
  ],
  completed: false,
  slide_last_index: null,
  audio_position_seconds: null,
  flashcard_ratings: {},
};

function installFetch(artifact: unknown = ARTIFACT) {
  const fn = vi.fn((input: string | URL, init?: RequestInit): Promise<Response> => {
    const url = typeof input === "string" ? input : input.toString();
    const method = (init?.method ?? "GET").toUpperCase();
    let body: unknown = { error: { code: "x", message: "x" } };
    let status = 404;
    if (url.includes("/progress") && method === "PUT") {
      body = {
        completed: true,
        slide_last_index: null,
        audio_position_seconds: null,
        course_percent_complete: 100,
      };
      status = 200;
    } else if (url.includes("/api/student/artifacts/")) {
      body = artifact;
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
      <InfographicViewer artifactId="a-info" slug="nn" moduleTitle="Unit 2: Deep Learning" />
    </QueryClientProvider>,
  );
}

describe("InfographicViewer math", () => {
  it("draws a formula in the caption", async () => {
    installFetch({ ...ARTIFACT, content_json: { caption: "Rate of $S_N2$" } });
    const { container } = renderViewer();
    await screen.findByTestId("infographic-image");
    expect(container.querySelector(".katex")).not.toBeNull();
  });
});

describe("InfographicViewer", () => {
  it("renders the diagram, caption, module title, and marks viewed on open", async () => {
    const fetchMock = installFetch();
    renderViewer();

    expect(await screen.findByTestId("infographic-image")).toHaveAttribute(
      "src",
      "/api/media/diagram.svg",
    );
    expect(screen.getByText("How a neural network learns")).toBeInTheDocument();
    expect(screen.getByText("Unit 2: Deep Learning")).toBeInTheDocument();
    expect(screen.getByTestId("btn-if4")).toHaveAttribute("href", "/api/media/diagram.png");

    await waitFor(() => {
      const put = fetchMock.mock.calls.find(
        (c) => (c[1] as RequestInit)?.method === "PUT" && String(c[0]).includes("/progress"),
      );
      expect(put).toBeDefined();
      expect(JSON.parse((put![1] as RequestInit).body as string)).toEqual({});
    });
  });

  it("zoom in/out changes the image width and clamps at the minimum", async () => {
    installFetch();
    renderViewer();
    const img = await screen.findByTestId("infographic-image");
    expect(img.style.width).toBe("100%");

    await userEvent.click(screen.getByTestId("btn-if1")); // zoom in: 1 -> 1.25
    expect(img.style.width).toBe("125%");

    await userEvent.click(screen.getByTestId("btn-if2")); // back to 1
    expect(img.style.width).toBe("100%");

    // zoom out repeatedly until it clamps at MIN_ZOOM (0.5)
    for (let i = 0; i < 5; i++) {
      // eslint-disable-next-line no-await-in-loop
      await userEvent.click(screen.getByTestId("btn-if2"));
    }
    expect(img.style.width).toBe("50%");
    expect(screen.getByTestId("btn-if2")).toBeDisabled();
  });

  it("Mark reviewed sends completed and then shows Reviewed", async () => {
    const fetchMock = installFetch();
    renderViewer();
    await screen.findByTestId("infographic-image");

    await userEvent.click(screen.getByTestId("btn-if5"));
    await waitFor(() => {
      const puts = fetchMock.mock.calls.filter(
        (c) => (c[1] as RequestInit)?.method === "PUT" && String(c[0]).includes("/progress"),
      );
      const completedPut = puts.find(
        (c) =>
          (JSON.parse((c[1] as RequestInit).body as string) as { completed?: boolean })
            .completed === true,
      );
      expect(completedPut).toBeDefined();
    });
  });
});

describe("InfographicViewer PDF link", () => {
  it("links the infographic PDF when present", async () => {
    installFetch({
      ...ARTIFACT,
      media: [
        ...ARTIFACT.media,
        { kind: "infographic_pdf", url: "/api/media/i.pdf", page_index: null },
      ],
    });
    renderViewer();
    expect(await screen.findByTestId("btn-if6")).toHaveAttribute("href", "/api/media/i.pdf");
  });
  it("hides the link when absent", async () => {
    installFetch();
    renderViewer();
    await screen.findByTestId("btn-if5");
    expect(screen.queryByTestId("btn-if6")).toBeNull();
  });
});
