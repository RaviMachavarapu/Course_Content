import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { StagingArtifact } from "./api";
import { PublishModal } from "./PublishModal";

function art(type: string, status: string): StagingArtifact {
  return {
    id: `a-${type}`,
    type: type as StagingArtifact["type"],
    status,
    last_error: null,
    current_version: null,
    job: { state: null },
    generation_options: {},
    custom_prompt: null,
  };
}

const ARTIFACTS = [
  art("report", "ready"),
  art("quiz", "ready"),
  art("flashcards", "processing"),
  art("slide_deck", "pending"),
  art("infographic", "error"),
  art("audio_overview", "published"),
];

describe("PublishModal", () => {
  it("splits will-publish from skipped with reasons", () => {
    render(
      <PublishModal
        open
        scope="module"
        artifacts={ARTIFACTS}
        pending={false}
        onCancel={vi.fn()}
        onConfirm={vi.fn()}
      />,
    );
    expect(screen.getByText("Will publish (2)")).toBeInTheDocument();
    expect(screen.getByText("Skipped (3)")).toBeInTheDocument(); // published is neither
    expect(screen.getByText(/still generating/)).toBeInTheDocument();
    expect(screen.getByText(/not generated yet/)).toBeInTheDocument();
    expect(screen.getByText(/generation failed/)).toBeInTheDocument();
    expect(screen.getByTestId("btn-publish-confirm")).toHaveTextContent("Publish 2 artifacts");
  });

  it("disables confirm when nothing is ready", () => {
    render(
      <PublishModal
        open
        scope="course"
        artifacts={[art("report", "processing")]}
        pending={false}
        onCancel={vi.fn()}
        onConfirm={vi.fn()}
      />,
    );
    expect(screen.getByTestId("btn-publish-confirm")).toBeDisabled();
  });

  it("fires onConfirm", async () => {
    const onConfirm = vi.fn();
    render(
      <PublishModal
        open
        scope="module"
        artifacts={ARTIFACTS}
        pending={false}
        onCancel={vi.fn()}
        onConfirm={onConfirm}
      />,
    );
    await userEvent.click(screen.getByTestId("btn-publish-confirm"));
    expect(onConfirm).toHaveBeenCalledOnce();
  });
});
