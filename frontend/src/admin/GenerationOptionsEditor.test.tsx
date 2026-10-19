import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { GenerationOptionsEditor } from "./GenerationOptionsEditor";
import { DEFAULT_OPTIONS } from "./generationOptions";

describe("GenerationOptionsEditor", () => {
  it("renders the right fields for audio overview and calls onChange", async () => {
    const onChange = vi.fn();
    render(
      <GenerationOptionsEditor
        type="audio_overview"
        values={DEFAULT_OPTIONS.audio_overview}
        onChange={onChange}
      />,
    );
    expect(screen.getByLabelText("Format")).toHaveValue("deep_dive");
    expect(screen.getByLabelText("Length")).toHaveValue("default");
    expect(screen.getByLabelText("Language")).toHaveValue("en");

    await userEvent.selectOptions(screen.getByLabelText("Format"), "debate");
    expect(onChange).toHaveBeenCalledWith({ ...DEFAULT_OPTIONS.audio_overview, format: "debate" });
  });

  it("renders only Language for slide deck", () => {
    render(
      <GenerationOptionsEditor
        type="slide_deck"
        values={DEFAULT_OPTIONS.slide_deck}
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByLabelText("Language")).toBeInTheDocument();
    expect(screen.queryByLabelText("Format")).not.toBeInTheDocument();
  });

  it("renders Quantity and Difficulty for quiz/flashcards", () => {
    render(
      <GenerationOptionsEditor type="quiz" values={DEFAULT_OPTIONS.quiz} onChange={vi.fn()} />,
    );
    expect(screen.getByLabelText("Quantity")).toHaveValue("standard");
    expect(screen.getByLabelText("Difficulty")).toHaveValue("medium");
  });
});
