import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FlashcardsViewer } from "./FlashcardsViewer";

afterEach(() => vi.unstubAllGlobals());

function artifact(ratings: Record<string, string> = {}) {
  return {
    id: "a-fc",
    type: "flashcards",
    module_id: "m1",
    module_index: 0,
    course_slug: "nn",
    revision: 1,
    content_json: {
      cards: [
        { front: "Q0", back: "A0", category: "Basics" },
        { front: "Q1", back: "A1", category: "Depth" },
      ],
    },
    content_html: null,
    media: [],
    completed: false,
    slide_last_index: null,
    audio_position_seconds: null,
    flashcard_ratings: ratings,
  };
}

function installFetch(art: unknown) {
  const fn = vi.fn((input: string | URL, init?: RequestInit): Promise<Response> => {
    const url = typeof input === "string" ? input : input.toString();
    const method = (init?.method ?? "GET").toUpperCase();
    let body: unknown = { error: { code: "x", message: "x" } };
    let status = 404;
    if (url.includes("/flashcard-ratings/") && method === "PUT") {
      const value = (JSON.parse((init?.body as string) ?? "{}") as { value: string }).value;
      const idx = url.match(/flashcard-ratings\/(\d+)/)?.[1] ?? "0";
      body = { ratings: { [idx]: value } };
      status = 200;
    } else if (url.includes("/progress") && method === "PUT") {
      body = {
        completed: true,
        slide_last_index: null,
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
      <FlashcardsViewer artifactId="a-fc" slug="nn" />
    </QueryClientProvider>,
  );
}

describe("FlashcardsViewer math", () => {
  it("draws formulas on both faces", async () => {
    const art = artifact();
    art.content_json.cards = [
      { front: "Rate of $S_N2$?", back: "Depends on $\\ce{H2O}$", category: "$S_N1$" },
    ];
    installFetch(art);
    const { container } = renderViewer();
    await screen.findByTestId("fc-face");
    expect(container.querySelectorAll(".katex").length).toBe(2);
    expect(screen.getByTestId("btn-fc1")).toHaveAttribute("aria-label", "Show answer");
    await userEvent.click(screen.getByTestId("btn-fc1"));
    expect(screen.getByTestId("fc-face").querySelector(".katex")).not.toBeNull();
  });
});

describe("FlashcardsViewer", () => {
  it("shows the front, flips on click, and gates Prev at the start", async () => {
    installFetch(artifact());
    renderViewer();

    expect(await screen.findByText("Q0")).toBeInTheDocument();
    expect(screen.getByText("Basics")).toBeInTheDocument();
    expect(screen.getByText("1 of 2")).toBeInTheDocument();
    expect(screen.getByTestId("btn-fc2")).toBeDisabled();

    await userEvent.click(screen.getByTestId("btn-fc1"));
    expect(screen.getByText("A0")).toBeInTheDocument();
  });

  it("rates a card and marks it pressed", async () => {
    const fetchMock = installFetch(artifact());
    renderViewer();
    await screen.findByText("Q0");

    await userEvent.click(screen.getByTestId("btn-fc4")); // Hard
    await waitFor(() => {
      const put = fetchMock.mock.calls.find(
        (c) =>
          (c[1] as RequestInit)?.method === "PUT" && String(c[0]).includes("/flashcard-ratings/0"),
      );
      expect(put).toBeDefined();
      expect(JSON.parse((put![1] as RequestInit).body as string)).toEqual({ value: "hard" });
    });
    await waitFor(() =>
      expect(screen.getByTestId("btn-fc4")).toHaveAttribute("aria-pressed", "true"),
    );
  });

  it("orders previously-Hard cards first", async () => {
    installFetch(artifact({ "1": "hard" }));
    renderViewer();
    // card 1 (rated hard) leads the deck
    expect(await screen.findByText("Q1")).toBeInTheDocument();
  });

  it("Space flips and reaching the last card completes the deck", async () => {
    const fetchMock = installFetch(artifact());
    renderViewer();
    await screen.findByText("Q0");

    await userEvent.keyboard(" ");
    expect(screen.getByText("A0")).toBeInTheDocument();

    await userEvent.click(screen.getByTestId("btn-fc3")); // Next -> card 2 (last)
    expect(screen.getByText("2 of 2")).toBeInTheDocument();

    await waitFor(() => {
      const put = fetchMock.mock.calls.find(
        (c) => (c[1] as RequestInit)?.method === "PUT" && String(c[0]).includes("/progress"),
      );
      expect(put).toBeDefined();
      expect(JSON.parse((put![1] as RequestInit).body as string)).toEqual({ completed: true });
    });
  });
});

describe("FlashcardsViewer PDF link", () => {
  const pdf = { kind: "flashcards_pdf", url: "/api/media/fc.pdf", page_index: null };
  it("links the flashcards PDF when present", async () => {
    installFetch({ ...artifact(), media: [pdf] });
    renderViewer();
    expect(await screen.findByTestId("btn-fc7")).toHaveAttribute("href", "/api/media/fc.pdf");
  });
  it("hides the link when absent", async () => {
    installFetch(artifact());
    renderViewer();
    await screen.findByTestId("btn-fc1");
    expect(screen.queryByTestId("btn-fc7")).toBeNull();
  });
});

describe("FlashcardsViewer stability", () => {
  it("keeps the current card in place after rating it", async () => {
    installFetch(artifact());
    renderViewer();
    await screen.findByText("Q0");
    await userEvent.click(screen.getByTestId("btn-fc6")); // Easy
    await waitFor(() =>
      expect(screen.getByTestId("btn-fc6")).toHaveAttribute("aria-pressed", "true"),
    );
    expect(screen.getByTestId("fc-face")).toHaveTextContent("Q0");
    expect(screen.getByText("1 of 2")).toBeInTheDocument();
  });

  it("sends completion only once per visit", async () => {
    const fetchMock = installFetch(artifact());
    renderViewer();
    await screen.findByText("Q0");
    await userEvent.click(screen.getByTestId("btn-fc3"));
    await userEvent.click(screen.getByTestId("btn-fc2"));
    await userEvent.click(screen.getByTestId("btn-fc3"));
    await new Promise((r) => setTimeout(r, 50));
    const puts = fetchMock.mock.calls.filter(
      (c) => (c[1] as RequestInit)?.method === "PUT" && String(c[0]).includes("/progress"),
    );
    expect(puts).toHaveLength(1);
  });
});
