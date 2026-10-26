import { render, screen } from "@testing-library/react";
import { ContentView } from "./ContentView";
import type { InspectVersion } from "../staging/api";

function version(media: InspectVersion["media"]): InspectVersion {
  return {
    id: "v1",
    revision: 1,
    redo_note: null,
    focus_prompt_used: "",
    prompt_template_version: 1,
    generation_job_id: "job-1",
    notebooklm_artifact_id: null,
    created_at: "2026-01-01T00:00:00Z",
    content_json: { caption: "ML pillars", description: "OVERVIEW text" },
    content_html: null,
    media,
  };
}

describe("ContentView math", () => {
  const S = "Rate of $S_N2$";
  const v = (content_json: Record<string, unknown>, content_html: string | null = null) => ({
    ...version([]),
    content_json,
    content_html,
  });
  it("draws formulas for flashcards, quiz, infographic and report", () => {
    const cases: [Parameters<typeof ContentView>[0]["type"], InspectVersion][] = [
      ["flashcards", v({ cards: [{ front: S, back: S, category: S }] })],
      [
        "quiz",
        v({ questions: [{ question: S, options: [S, "b"], correct_index: 0, explanation: S }] }),
      ],
      ["infographic", v({ caption: S, description: "d" })],
      ["infographic", v({ caption: "c", description: S })],
      ["slide_deck", v({ slides: [{ title: S, bullets: [S], notes: S }] })],
      ["audio_overview", v({ transcript: [{ t: 0, text: S }] })],
      ["report", v({}, '<p><span class="math-inline">S_N2</span></p>')],
    ];
    for (const [type, ver] of cases) {
      const { container, unmount } = render(<ContentView type={type} version={ver} />);
      expect(container.querySelector(".katex"), type).not.toBeNull();
      unmount();
    }
  });
});

describe("ContentView report", () => {
  it("renders the report from content_json with formulas drawn in title, takeaways and headings", () => {
    const ver = {
      ...version([]),
      content_json: {
        title: "About $S_N2$",
        key_takeaways: ["$S_N2$ is one step"],
        sections: [
          { heading: "$S_N2$ Reactions", html: '<p>Rate <span class="math-inline">k_1</span></p>' },
        ],
      },
      content_html: "<h1>About $S_N2$</h1><ul><li>$S_N2$ is one step</li></ul>",
    };
    const { container } = render(<ContentView type="report" version={ver} />);
    expect(container.textContent).not.toContain("$");
    expect(container.querySelectorAll("h1 .katex").length).toBe(1);
    expect(container.querySelectorAll("li .katex").length).toBe(1);
    expect(container.querySelectorAll("h2 .katex").length).toBe(1);
    expect(container.querySelectorAll(".math-inline .katex").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Key takeaways")).toBeInTheDocument();
  });
});

describe("ContentView infographic", () => {
  it("shows the generated image, with the text description tucked away", () => {
    render(
      <ContentView
        type="infographic"
        version={version([
          { kind: "infographic_png", url: "/api/media/i.png", size_bytes: 1, page_index: null },
        ])}
      />,
    );
    expect(screen.getByRole("img", { name: "ML pillars" })).toHaveAttribute(
      "src",
      "/api/media/i.png",
    );
    expect(screen.getByText("Text description")).toBeInTheDocument();
  });

  it("falls back to the text description when there is no image", () => {
    render(<ContentView type="infographic" version={version([])} />);
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.getByText("OVERVIEW text")).toBeVisible();
  });
});
