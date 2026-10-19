import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { AchievementsPage } from "./AchievementsPage";

afterEach(() => vi.unstubAllGlobals());

function installFetch(body: { earned: unknown[]; locked: unknown[] }) {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve({
        ok: true,
        status: 200,
        statusText: "200",
        json: () => Promise.resolve(body),
      } as Response),
    ),
  );
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <AchievementsPage />
    </QueryClientProvider>,
  );
}

describe("AchievementsPage", () => {
  it("renders earned badges with a date and locked badges with criteria", async () => {
    installFetch({
      earned: [
        {
          key: "course_complete",
          label: "Course Complete",
          description: "Finish every published module in a course.",
          icon: "military_tech",
          earned: true,
          earned_at: "2026-02-01T00:00:00Z",
        },
      ],
      locked: [
        {
          key: "quiz_ace",
          label: "Quiz Ace",
          description: "Score 80% or higher on any quiz.",
          icon: "workspace_premium",
          earned: false,
          earned_at: null,
        },
      ],
    });
    renderPage();

    const badges = await screen.findAllByTestId("achievement-badge");
    expect(badges).toHaveLength(2);
    expect(badges[0]).toHaveAttribute("data-earned", "true");
    expect(badges[0]).toHaveTextContent(/Earned/);
    expect(badges[1]).toHaveAttribute("data-earned", "false");
    expect(badges[1]).toHaveTextContent("Score 80% or higher on any quiz.");
    expect(badges[1]).toHaveTextContent("Locked");
  });
});
