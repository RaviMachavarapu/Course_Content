import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { onTestFinished } from "vitest";
import { QuizViewer } from "./QuizViewer";

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const ARTIFACT = {
  id: "a-quiz",
  type: "quiz",
  module_id: "m1",
  module_index: 0,
  course_slug: "nn",
  revision: 1,
  content_json: { questions: [] },
  content_html: null,
  media: [] as unknown[],
  completed: false,
  slide_last_index: null,
  audio_position_seconds: null,
  flashcard_ratings: {},
};

type Q = {
  index: number;
  type: "mcq" | "fill_blank";
  question: string;
  options: string[] | null;
  result: unknown;
};

const MCQ = (over: Partial<Q> = {}): Q => ({
  index: 0,
  type: "mcq",
  question: "2 + 2?",
  options: ["3", "4", "5", "6"],
  result: null,
  ...over,
});
const FILL = (over: Partial<Q> = {}): Q => ({
  index: 1,
  type: "fill_blank",
  question: "Water is made of hydrogen and ____.",
  options: null,
  result: null,
  ...over,
});

const attempt = (questions: Q[], over: Record<string, unknown> = {}) => ({
  status: "started",
  attempt_id: "at1",
  attempt_number: 1,
  source: "studio",
  total_count: questions.length,
  checked_count: questions.filter((q) => q.result).length,
  correct_count: 0,
  started_at: "2026-10-27T10:00:00Z",
  questions,
  ...over,
});

const PREPARING = { status: "preparing", message: "Preparing new questions…" };
const UNAVAILABLE = {
  status: "unavailable",
  message: "x",
  error: { code: "questions_unavailable", message: "x" },
};

const CHECKS: Record<number, unknown> = {
  0: {
    index: 0,
    response: 1,
    correct: true,
    correct_answer: "4",
    correct_index: 1,
    explanation: "Because 2 plus 2 is four.",
  },
  1: {
    index: 1,
    response: "oxygen",
    correct: true,
    correct_answer: "oxygen",
    correct_index: null,
    explanation: "Water is H2O.",
  },
};

const COMPLETE = {
  attempt_id: "at1",
  score_percent: 50,
  correct_count: 1,
  total_count: 2,
  completed_at: "2026-10-27T10:05:00Z",
  review: [
    {
      index: 0,
      type: "mcq",
      question: "2 + 2?",
      options: ["3", "4", "5", "6"],
      response: 1,
      correct: true,
      correct_answer: "4",
      correct_index: 1,
      explanation: "Because 2 plus 2 is four.",
    },
    {
      index: 1,
      type: "fill_blank",
      question: "Water is made of hydrogen and ____.",
      options: null,
      response: "helium",
      correct: false,
      correct_answer: "oxygen",
      correct_index: null,
      explanation: "Water is H2O.",
    },
  ],
  best_score_percent: 50,
  latest_score_percent: 50,
};

interface Setup {
  starts: { status: number; body: unknown }[];
  checks?: Record<number, unknown>;
  /** Per-call override for POST /answers: a response spec, or "network" to reject. */
  answers?: (call: number) => { status: number; body: unknown } | "network" | undefined;
  complete?: (call: number) => { status: number; body: unknown } | "network" | undefined;
}

function installFetch(setup: Setup) {
  const starts = [...setup.starts];
  let answerCalls = 0;
  let completeCalls = 0;
  const fn = vi.fn((input: string | URL, init?: RequestInit): Promise<Response> => {
    const url = typeof input === "string" ? input : input.toString();
    const method = (init?.method ?? "GET").toUpperCase();
    let body: unknown = { error: { code: "x", message: "x" } };
    let status = 404;
    if (url.endsWith("/quiz-attempts") && method === "POST") {
      const next = starts.length > 1 ? starts.shift()! : starts[0]!;
      ({ status, body } = next);
    } else if (url.endsWith("/answers") && setup.answers?.(answerCalls++)) {
      const o = setup.answers(answerCalls - 1)!;
      if (o === "network") return Promise.reject(new TypeError("network"));
      ({ status, body } = o);
    } else if (url.endsWith("/complete") && setup.complete?.(completeCalls++)) {
      const o = setup.complete(completeCalls - 1)!;
      if (o === "network") return Promise.reject(new TypeError("network"));
      ({ status, body } = o);
    } else if (url.endsWith("/answers")) {
      const idx = JSON.parse(init!.body as string).index as number;
      body = (setup.checks ?? CHECKS)[idx];
      status = 200;
    } else if (url.endsWith("/complete")) {
      body = COMPLETE;
      status = 200;
    } else if (url.includes("/quiz-attempts")) {
      body = { attempts: [], best_score_percent: null, latest_score_percent: null };
      status = 200;
    } else if (url.includes("/api/student/artifacts/")) {
      body = ARTIFACT;
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
      <MemoryRouter initialEntries={["/learn/nn/0/quiz"]}>
        <Routes>
          <Route path="/learn/nn/0/quiz" element={<QuizViewer artifactId="a-quiz" slug="nn" />} />
          <Route path="/learn/nn" element={<div>MODULE</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const posts = (fn: ReturnType<typeof installFetch>, suffix: string) =>
  fn.mock.calls.filter(
    (c) => (c[1] as RequestInit)?.method === "POST" && String(c[0]).endsWith(suffix),
  );

async function finishBoth() {
  await userEvent.click(await screen.findByTestId("btn-qz1-1"));
  await userEvent.click(screen.getByTestId("btn-qz8"));
  await userEvent.click(await screen.findByTestId("btn-qz3"));
  await userEvent.type(screen.getByTestId("quiz-fill-input"), "oxygen");
  await userEvent.click(screen.getByTestId("btn-qz8"));
  await userEvent.click(await screen.findByTestId("btn-qz4"));
  await screen.findByTestId("quiz-score");
}

/** Drives the whole attempt under fake timers (findBy* would hang there). */
async function finishBothFake() {
  const settle = () => act(() => vi.advanceTimersByTimeAsync(0));
  await settle();
  fireEvent.click(screen.getByTestId("btn-qz1-1"));
  fireEvent.click(screen.getByTestId("btn-qz8"));
  await settle();
  fireEvent.click(screen.getByTestId("btn-qz3"));
  fireEvent.change(screen.getByTestId("quiz-fill-input"), { target: { value: "oxygen" } });
  fireEvent.click(screen.getByTestId("btn-qz8"));
  await settle();
  fireEvent.click(screen.getByTestId("btn-qz4"));
  await settle();
  fireEvent.click(screen.getByTestId("btn-qz5")); // Retake
  await settle();
}
const flush = (ms: number) => act(() => vi.advanceTimersByTimeAsync(ms));

describe("QuizViewer check flow", () => {
  it("shows no answer data before a check and Check needs a response", async () => {
    installFetch({ starts: [{ status: 201, body: attempt([MCQ(), FILL()]) }] });
    renderViewer();
    expect(await screen.findByText("Question 1 of 2")).toBeInTheDocument();
    expect(screen.getByText("2 + 2?")).toBeInTheDocument();
    expect(screen.getByTestId("btn-qz8")).toBeDisabled();
    expect(screen.queryByText(/Correct answer/)).toBeNull();
    expect(screen.queryByText(/plus 2 is four/)).toBeNull();
    expect(screen.queryByTestId("btn-qz3")).toBeNull();
  });

  it("checks an MCQ, reveals feedback and locks the question", async () => {
    const fetchMock = installFetch({ starts: [{ status: 201, body: attempt([MCQ(), FILL()]) }] });
    renderViewer();
    await userEvent.click(await screen.findByTestId("btn-qz1-1"));
    await userEvent.click(screen.getByTestId("btn-qz8"));
    expect(await screen.findByText(/Because 2 plus 2 is four/)).toBeInTheDocument();
    expect(screen.getByTestId("quiz-feedback")).toHaveTextContent("Correct");
    expect(screen.getByTestId("quiz-feedback")).toHaveTextContent("4");
    const body = JSON.parse((posts(fetchMock, "/answers")[0]![1] as RequestInit).body as string);
    expect(body).toEqual({ index: 0, response: 1 });
    // locked
    expect(screen.queryByTestId("btn-qz8")).toBeNull();
    await userEvent.click(screen.getByTestId("btn-qz1-0"));
    expect(screen.getByTestId("btn-qz1-1")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("btn-qz1-0")).toHaveAttribute("aria-pressed", "false");
    expect(posts(fetchMock, "/answers")).toHaveLength(1);
  });

  it("checks a fill-in-the-blank with a text input and shows the blank", async () => {
    const fetchMock = installFetch({
      starts: [{ status: 201, body: attempt([MCQ(), FILL()]) }],
    });
    renderViewer();
    await userEvent.click(await screen.findByTestId("btn-qz1-1"));
    await userEvent.click(screen.getByTestId("btn-qz8"));
    await userEvent.click(await screen.findByTestId("btn-qz3"));
    expect(screen.getByText(/hydrogen and ____\./)).toBeInTheDocument();
    expect(screen.queryByTestId("btn-qz1-0")).toBeNull();
    expect(screen.getByTestId("btn-qz8")).toBeDisabled();
    await userEvent.type(screen.getByTestId("quiz-fill-input"), "oxygen");
    await userEvent.click(screen.getByTestId("btn-qz8"));
    expect(await screen.findByText(/Water is H2O/)).toBeInTheDocument();
    expect(screen.getByTestId("quiz-fill-input")).toBeDisabled();
    expect(JSON.parse((posts(fetchMock, "/answers")[1]![1] as RequestInit).body as string)).toEqual(
      { index: 1, response: "oxygen" },
    );
  });

  it("finishes: score screen with percent and review", async () => {
    const fetchMock = installFetch({
      starts: [{ status: 201, body: attempt([MCQ(), FILL()]) }],
    });
    renderViewer();
    await finishBoth();
    expect(posts(fetchMock, "/complete")).toHaveLength(1);
    expect(screen.getByTestId("quiz-score")).toHaveTextContent("50%");
    expect(screen.getByText("1 of 2 correct")).toBeInTheDocument();
    const rows = screen.getAllByTestId("quiz-result-row");
    expect(rows).toHaveLength(2);
    expect(rows[1]).toHaveTextContent("helium");
    expect(rows[1]).toHaveTextContent("oxygen");
    expect(rows[1]).toHaveTextContent("Water is H2O.");
    expect(rows[0]).toHaveTextContent("Your answer: B.");
  });

  it("Back to module navigates", async () => {
    installFetch({ starts: [{ status: 201, body: attempt([MCQ(), FILL()]) }] });
    renderViewer();
    await finishBoth();
    await userEvent.click(screen.getByTestId("btn-qz6"));
    expect(screen.getByText("MODULE")).toBeInTheDocument();
  });

  it("resumes: shows checked results and continues from the first unchecked", async () => {
    const fetchMock = installFetch({
      starts: [
        {
          status: 200,
          body: attempt([MCQ({ result: CHECKS[0] }), FILL()], { status: "resumed" }),
        },
      ],
    });
    renderViewer();
    expect(await screen.findByText("Question 2 of 2")).toBeInTheDocument();
    expect(screen.getByTestId("quiz-fill-input")).not.toBeDisabled();
    await userEvent.click(screen.getByTestId("btn-qz2")); // Previous
    expect(screen.getByText("Question 1 of 2")).toBeInTheDocument();
    expect(screen.getByText(/Because 2 plus 2 is four/)).toBeInTheDocument();
    expect(screen.getByTestId("btn-qz1-1")).toHaveAttribute("aria-pressed", "true");
    expect(posts(fetchMock, "/answers")).toHaveLength(0);
  });
});

describe("QuizViewer failures", () => {
  const START = { status: 201, body: attempt([MCQ(), FILL()]) };

  it("resyncs after a 409 already_checked and shows the recorded feedback", async () => {
    const fetchMock = installFetch({
      starts: [
        START,
        {
          status: 200,
          body: attempt([MCQ({ result: CHECKS[0] }), FILL()], { status: "resumed" }),
        },
      ],
      answers: () => ({
        status: 409,
        body: { error: { code: "already_checked", message: "already" } },
      }),
    });
    renderViewer();
    await userEvent.click(await screen.findByTestId("btn-qz1-1"));
    await userEvent.click(screen.getByTestId("btn-qz8"));
    expect(await screen.findByText(/Because 2 plus 2 is four/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(posts(fetchMock, "/quiz-attempts")).toHaveLength(2);
    expect(screen.getByTestId("quiz-feedback")).toHaveFocus();
  });

  it("shows an error when the check and the resync both fail, then retry works", async () => {
    installFetch({
      starts: [START, START],
      answers: (n) => (n === 0 ? "network" : undefined),
    });
    renderViewer();
    await userEvent.click(await screen.findByTestId("btn-qz1-1"));
    await userEvent.click(screen.getByTestId("btn-qz8"));
    expect(await screen.findByRole("alert")).toHaveTextContent(/Couldn’t check/);
    expect(screen.queryByTestId("quiz-feedback")).toBeNull();
    await userEvent.click(screen.getByTestId("btn-qz8"));
    expect(await screen.findByTestId("quiz-feedback")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("a failed Finish shows an error and can be retried", async () => {
    installFetch({
      starts: [START],
      complete: (n) =>
        n === 0 ? { status: 500, body: { error: { code: "x", message: "x" } } } : undefined,
    });
    renderViewer();
    await userEvent.click(await screen.findByTestId("btn-qz1-1"));
    await userEvent.click(screen.getByTestId("btn-qz8"));
    await userEvent.click(await screen.findByTestId("btn-qz3"));
    await userEvent.type(screen.getByTestId("quiz-fill-input"), "oxygen");
    await userEvent.click(screen.getByTestId("btn-qz8"));
    await userEvent.click(await screen.findByTestId("btn-qz4"));
    expect(await screen.findByRole("alert")).toHaveTextContent(/Couldn’t finish/);
    await userEvent.click(screen.getByTestId("btn-qz4"));
    expect(await screen.findByTestId("quiz-score")).toBeInTheDocument();
  });

  it("non-409 start error shows the error state; empty question list too", async () => {
    installFetch({ starts: [{ status: 500, body: { error: { code: "x", message: "x" } } }] });
    renderViewer();
    expect(await screen.findByText("Quiz isn’t ready")).toBeInTheDocument();
    cleanup();
    installFetch({ starts: [{ status: 201, body: attempt([]) }] });
    renderViewer();
    expect(await screen.findByText("Quiz isn’t ready")).toBeInTheDocument();
  });
});

describe("QuizViewer retake", () => {
  const FIRST = { status: 201, body: attempt([MCQ(), FILL()]) };
  const SECOND = {
    status: 201,
    body: attempt([MCQ({ question: "3 + 3?" }), FILL()], { attempt_id: "at2", attempt_number: 2 }),
  };

  it("Retake -> preparing -> polls every 3 s -> new questions", async () => {
    vi.useFakeTimers();
    installFetch({ starts: [FIRST, { status: 202, body: PREPARING }, SECOND] });
    renderViewer();
    await finishBothFake();
    expect(screen.getByText("Preparing new questions…")).toBeInTheDocument();
    await flush(2999);
    expect(screen.getByText("Preparing new questions…")).toBeInTheDocument();
    await flush(10);
    expect(screen.getByText("3 + 3?")).toBeInTheDocument();
    expect(screen.getByText("Question 1 of 2")).toBeInTheDocument();
  });

  it("Retake 409 -> unavailable message and Try again restarts", async () => {
    const fetchMock = installFetch({
      starts: [FIRST, { status: 409, body: UNAVAILABLE }, SECOND],
    });
    renderViewer();
    await finishBoth();
    await userEvent.click(screen.getByTestId("btn-qz5"));
    expect(
      await screen.findByText("New questions aren't available right now — please try again later"),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByTestId("btn-qz9"));
    expect(await screen.findByText("3 + 3?")).toBeInTheDocument();
    expect(posts(fetchMock, "/quiz-attempts")).toHaveLength(3);
  });

  it("gives up polling after 2 minutes with the unavailable message", async () => {
    vi.useFakeTimers();
    const fetchMock = installFetch({ starts: [FIRST, { status: 202, body: PREPARING }] });
    renderViewer();
    await finishBothFake();
    await flush(60_000);
    expect(screen.getByText("Preparing new questions…")).toBeInTheDocument();
    await flush(61_000);
    expect(
      screen.getByText("New questions aren't available right now — please try again later"),
    ).toBeInTheDocument();
    const count = posts(fetchMock, "/quiz-attempts").length;
    await flush(30_000);
    expect(posts(fetchMock, "/quiz-attempts")).toHaveLength(count);
  });

  it("stops polling when unmounted", async () => {
    vi.useFakeTimers();
    const fetchMock = installFetch({ starts: [{ status: 202, body: PREPARING }] });
    const { unmount } = renderViewer();
    await flush(0);
    expect(screen.getByText("Preparing new questions…")).toBeInTheDocument();
    unmount();
    const before = posts(fetchMock, "/quiz-attempts").length;
    await flush(10_000);
    expect(posts(fetchMock, "/quiz-attempts")).toHaveLength(before);
  });
});

describe("QuizViewer PDF link", () => {
  const MEDIA = [
    { kind: "quiz_pdf", url: "/api/media/answers.pdf", page_index: null },
    { kind: "quiz_questions_pdf", url: "/api/media/q.pdf", page_index: null },
  ];
  it("links the questions-only PDF on the question and score screens", async () => {
    const orig = ARTIFACT.media;
    onTestFinished(() => {
      ARTIFACT.media = orig;
    });
    ARTIFACT.media = MEDIA;
    installFetch({ starts: [{ status: 201, body: attempt([MCQ(), FILL()]) }] });
    renderViewer();
    expect(await screen.findByTestId("btn-qz7")).toHaveAttribute("href", "/api/media/q.pdf");
    await finishBoth();
    expect(screen.getByTestId("btn-qz7")).toHaveAttribute("href", "/api/media/q.pdf");
  });
  it("does not link the answer-key PDF on its own", async () => {
    const orig = ARTIFACT.media;
    onTestFinished(() => {
      ARTIFACT.media = orig;
    });
    ARTIFACT.media = [MEDIA[0]!];
    installFetch({ starts: [{ status: 201, body: attempt([MCQ(), FILL()]) }] });
    renderViewer();
    await screen.findByText("Question 1 of 2");
    expect(screen.queryByTestId("btn-qz7")).toBeNull();
  });
});

describe("QuizViewer math", () => {
  it("draws formulas in question, options, feedback and review", async () => {
    const checks = {
      0: {
        ...(CHECKS[0] as object),
        correct_answer: "$KOH$",
        explanation: "Since $S_N2$ is fast.",
      },
      1: CHECKS[1],
    };
    installFetch({
      starts: [
        {
          status: 201,
          body: attempt([
            MCQ({ question: "Rate of $S_N2$?", options: ["$S_N1$", "$KOH$", "c", "d"] }),
            FILL(),
          ]),
        },
      ],
      checks,
    });
    const { container } = renderViewer();
    await screen.findByText("Question 1 of 2");
    expect(container.querySelectorAll(".katex").length).toBe(3);
    await userEvent.click(screen.getByTestId("btn-qz1-1"));
    fireEvent.click(screen.getByTestId("btn-qz8"));
    await screen.findByTestId("quiz-feedback");
    // question 1 + 2 option formulas + correct answer + explanation, no raw dollars
    expect(container.querySelectorAll(".katex").length).toBeGreaterThanOrEqual(5);
    expect(container.textContent).not.toContain("$");
  });
});
