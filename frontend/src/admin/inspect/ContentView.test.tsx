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
