import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QuizSetsPanel } from "./QuizSetsPanel";

afterEach(() => vi.unstubAllGlobals());

const SET = {
  id: "s1",
  source: "chat",
  status: "used",
  created_at: "2026-01-02T00:00:00Z",
  student: { display_name: "Stu Dent", email: "s@example.com" },
  question_count: 1,
  kept: 1,
  dropped: 1,
  dropped_questions: [{ round: 1, index: 2, question: "Bad one?", reason: "duplicate of seen" }],
  error: null,
  warning: null,
  questions: [
    {
      type: "mcq",
      question: "What is 2+2?",
      options: ["3", "4", "5", "6"],
      correct_index: 1,
      explanation: "Because.",
    },
  ],
};

function renderPanel(sets: unknown[]) {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(sets) } as Response),
    ),
  );
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <QuizSetsPanel artifactId="a1" />
    </QueryClientProvider>,
  );
}

describe("QuizSetsPanel", () => {
  it("lists sets collapsed, then expands to answers and dropped reasons", async () => {
    renderPanel([SET]);
    expect(await screen.findByText(/Stu Dent/)).toBeInTheDocument();
    expect(screen.getByText(/1 kept \/ 1 dropped/)).toBeInTheDocument();
    expect(screen.queryByText("Bad one?")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Stu Dent/ }));
    expect(screen.getByText("What is 2+2?")).toBeInTheDocument();
    expect(screen.getByText(/Answer:/)).toHaveTextContent("Answer: 4");
    expect(screen.getByText("Bad one?")).toBeInTheDocument();
    expect(screen.getByText(/duplicate of seen/)).toBeInTheDocument();
  });

  it("shows the re-ask warning in the expanded set", async () => {
    renderPanel([{ ...SET, warning: "GenerationTimeout: chat took too long" }]);
    await userEvent.click(await screen.findByRole("button", { name: /Stu Dent/ }));
    expect(screen.getByTestId("quiz-set-warning")).toHaveTextContent(
      "GenerationTimeout: chat took too long",
    );
  });

  it("shows no warning line when there is none", async () => {
    renderPanel([SET]);
    await userEvent.click(await screen.findByRole("button", { name: /Stu Dent/ }));
    expect(screen.queryByTestId("quiz-set-warning")).not.toBeInTheDocument();
  });

  it("flags a kept question whose quote is not in the PDFs (link source)", async () => {
    renderPanel([
      {
        ...SET,
        unverified_questions: [
          {
            round: 1,
            index: 0,
            question: "What is 2+2?",
            reason: "quote not verified (link source)",
          },
        ],
      },
    ]);
    expect(await screen.findByText(/1 quote not verified/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Stu Dent/ }));
    expect(screen.getByTestId("quiz-set-unverified")).toHaveTextContent(
      "quote not verified (link source)",
    );
  });

  it("shows no flag for verified questions or an older API reply", async () => {
    renderPanel([SET]);
    await userEvent.click(await screen.findByRole("button", { name: /Stu Dent/ }));
    expect(screen.queryByTestId("quiz-set-unverified")).not.toBeInTheDocument();
    expect(screen.queryByText(/quote not verified/)).not.toBeInTheDocument();
  });

  it("shows an empty state", async () => {
    renderPanel([]);
    expect(await screen.findByText("No sets generated yet.")).toBeInTheDocument();
  });
});
