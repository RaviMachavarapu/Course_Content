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

  it("shows an empty state", async () => {
    renderPanel([]);
    expect(await screen.findByText("No sets generated yet.")).toBeInTheDocument();
  });
});
