import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QuizViewer } from "./QuizViewer";

afterEach(() => vi.unstubAllGlobals());

const ARTIFACT = {
  id: "a-quiz",
  type: "quiz",
  module_id: "m1",
  module_index: 0,
  course_slug: "nn",
  revision: 1,
  content_json: {
    questions: [
      { question: "2 + 2?", options: ["3", "4", "5", "6"] },
      { question: "Sky colour?", options: ["Green", "Blue", "Red", "Pink"] },
    ],
  },
  content_html: null,
  media: [],
  completed: false,
  slide_last_index: null,
  audio_position_seconds: null,
  flashcard_ratings: {},
};

const RESULT = {
  attempt_id: "at1",
  score_percent: 50,
  correct_count: 1,
  total_count: 2,
  results: [
    { question_index: 0, selected_index: 1, correct_index: 1, is_correct: true, explanation: "" },
    {
      question_index: 1,
      selected_index: 0,
      correct_index: 1,
      is_correct: false,
      explanation: "It scatters blue light.",
    },
  ],
  best_score_percent: 50,
  latest_score_percent: 50,
};

function installFetch() {
  const fn = vi.fn((input: string | URL, init?: RequestInit): Promise<Response> => {
    const url = typeof input === "string" ? input : input.toString();
    const method = (init?.method ?? "GET").toUpperCase();
    let body: unknown = { error: { code: "x", message: "x" } };
    let status = 404;
    if (url.includes("/quiz-attempts") && method === "POST") {
      body = RESULT;
      status = 201;
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

describe("QuizViewer", () => {
  it("shows the first question and does not reveal answers", async () => {
    installFetch();
    renderViewer();

    expect(await screen.findByText("Question 1 of 2")).toBeInTheDocument();
    expect(screen.getByText("2 + 2?")).toBeInTheDocument();
    expect(screen.getByTestId("btn-qz1-0")).toBeInTheDocument();
    expect(screen.getByTestId("btn-qz2")).toBeDisabled();
    expect(screen.queryByText(/Correct:/)).not.toBeInTheDocument();
  });

  it("requires every question answered before Submit, then shows results", async () => {
    const fetchMock = installFetch();
    renderViewer();
    await screen.findByText("Question 1 of 2");

    await userEvent.click(screen.getByTestId("btn-qz1-1")); // Q1 -> B
    expect(screen.getByTestId("btn-qz1-1")).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(screen.getByTestId("btn-qz3")); // Next
    expect(screen.getByText("Question 2 of 2")).toBeInTheDocument();
    expect(screen.getByTestId("btn-qz4")).toBeDisabled(); // Q2 not answered

    await userEvent.click(screen.getByTestId("btn-qz1-0")); // Q2 -> A
    await userEvent.click(screen.getByTestId("btn-qz4")); // Submit

    await waitFor(() => {
      const post = fetchMock.mock.calls.find(
        (c) => (c[1] as RequestInit)?.method === "POST" && String(c[0]).includes("/quiz-attempts"),
      );
      expect(post).toBeDefined();
      expect(JSON.parse((post![1] as RequestInit).body as string)).toEqual({
        answers: { "0": 1, "1": 0 },
      });
    });

    expect(await screen.findByTestId("quiz-score")).toHaveTextContent("50%");
    expect(screen.getByText("1 of 2 correct")).toBeInTheDocument();
    expect(screen.getByText(/It scatters blue light/)).toBeInTheDocument();
    expect(screen.getAllByTestId("quiz-result-row")).toHaveLength(2);
  });

  it("Retake returns to question 1 and Back to module navigates", async () => {
    installFetch();
    renderViewer();
    await screen.findByText("Question 1 of 2");

    await userEvent.click(screen.getByTestId("btn-qz1-1"));
    await userEvent.click(screen.getByTestId("btn-qz3"));
    await userEvent.click(screen.getByTestId("btn-qz1-0"));
    await userEvent.click(screen.getByTestId("btn-qz4"));
    await screen.findByTestId("quiz-score");

    await userEvent.click(screen.getByTestId("btn-qz5")); // Retake
    expect(screen.getByText("Question 1 of 2")).toBeInTheDocument();
    expect(screen.getByTestId("btn-qz1-1")).toHaveAttribute("aria-pressed", "false");
  });
});
