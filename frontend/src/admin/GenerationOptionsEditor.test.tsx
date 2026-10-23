import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ArtifactType } from "./api";
import { GenerationOptionsEditor } from "./GenerationOptionsEditor";
import { DEFAULT_OPTIONS, optionsProblem, type OptionValues } from "./generationOptions";

/** The editor with real state, so dependent fields react like in the form. */
function Harness({
  type,
  onChange,
  withPrompt = false,
}: {
  type: ArtifactType;
  onChange?: (v: OptionValues) => void;
  withPrompt?: boolean;
}) {
  const [values, setValues] = useState<OptionValues>(DEFAULT_OPTIONS[type]);
  const [prompt, setPrompt] = useState("");
  return (
    <GenerationOptionsEditor
      type={type}
      values={values}
      onChange={(v) => {
        setValues(v);
        onChange?.(v);
      }}
      prompt={withPrompt ? prompt : undefined}
      onPromptChange={withPrompt ? setPrompt : undefined}
    />
  );
}

const lengths = () =>
  screen
    .getByRole("radiogroup", { name: "Length" })
    .querySelectorAll("[role=radio]")
    .length.valueOf();

describe("GenerationOptionsEditor", () => {
  it("renders audio format cards, length buttons and language, and calls onChange", async () => {
    const onChange = vi.fn();
    render(<Harness type="audio_overview" onChange={onChange} />);
    expect(screen.getByRole("radio", { name: "Deep dive" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(screen.getByRole("radio", { name: /^Default$/ })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(screen.getByLabelText("Choose language")).toHaveValue("en");

    await userEvent.click(screen.getByRole("radio", { name: "Debate" }));
    expect(onChange).toHaveBeenLastCalledWith({
      ...DEFAULT_OPTIONS.audio_overview,
      format: "debate",
    });
  });

  it("offers Long only for Deep dive and no length at all for Brief (as NotebookLM)", async () => {
    render(<Harness type="audio_overview" />);
    await userEvent.click(screen.getByRole("radio", { name: "Long" }));
    expect(lengths()).toBe(3);

    await userEvent.click(screen.getByRole("radio", { name: "Debate" }));
    expect(lengths()).toBe(2);
    // Long was chosen; Debate doesn't offer it, so it falls back to Default
    expect(screen.getByRole("radio", { name: /^Default$/ })).toHaveAttribute(
      "aria-checked",
      "true",
    );

    await userEvent.click(screen.getByRole("radio", { name: "Brief" }));
    expect(screen.queryByRole("radiogroup", { name: "Length" })).not.toBeInTheDocument();
  });

  it("offers English plus the five approved Indian languages, nothing else", () => {
    render(<Harness type="quiz" />);
    const labels = screen.getAllByRole("option").map((o) => o.textContent);
    expect(labels).toEqual(["English", "Hindi", "Telugu", "Tamil", "Kannada", "Marathi"]);
  });

  it("renders Number of questions and Level of difficulty for quiz", async () => {
    const onChange = vi.fn();
    render(<Harness type="quiz" onChange={onChange} />);
    expect(screen.getByRole("radiogroup", { name: "Number of questions" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Medium (default)" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    await userEvent.click(screen.getByRole("radio", { name: "More" }));
    expect(onChange).toHaveBeenLastCalledWith({ ...DEFAULT_OPTIONS.quiz, quantity: "more" });
  });

  it("slide deck has format, length and the Review slide outline switch", async () => {
    const onChange = vi.fn();
    render(<Harness type="slide_deck" onChange={onChange} />);
    expect(screen.getByRole("radio", { name: "Detailed deck" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    await userEvent.click(screen.getByRole("switch", { name: "Review slide outline" }));
    expect(onChange).toHaveBeenLastCalledWith({
      ...DEFAULT_OPTIONS.slide_deck,
      review_outline: true,
    });
  });

  it("report: templates only for Document, language and text box only for Create your own", async () => {
    render(<Harness type="report" withPrompt />);
    expect(screen.queryByRole("radiogroup", { name: "Template" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Choose language")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("radio", { name: "Document" }));
    expect(screen.getByRole("radiogroup", { name: "Template" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Choose language")).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("radio", { name: "Create your own" }));
    expect(screen.getByLabelText("Choose language")).toBeInTheDocument();
    expect(screen.getByLabelText("Describe the kind of report to create")).toBeInTheDocument();
  });

  it("a document report without a template can't be sent", () => {
    expect(optionsProblem("report", { format: "document", template: null })).toMatch(/template/);
    expect(optionsProblem("report", { format: "document", template: "study_guide" })).toBeNull();
    expect(optionsProblem("report", DEFAULT_OPTIONS.report)).toBeNull();
  });

  it("infographic offers NotebookLM's visual styles and level of detail", async () => {
    const onChange = vi.fn();
    render(<Harness type="infographic" onChange={onChange} />);
    expect(screen.getByRole("radio", { name: "Auto-select" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    await userEvent.click(screen.getByRole("radio", { name: "Kawaii" }));
    await userEvent.click(screen.getByRole("radio", { name: "Detailed (BETA)" }));
    expect(onChange).toHaveBeenLastCalledWith({
      ...DEFAULT_OPTIONS.infographic,
      style: "kawaii",
      detail: "detailed",
    });
  });

  it("shows the prompt box only when wired, with NotebookLM's label", async () => {
    const onPromptChange = vi.fn();
    const { rerender } = render(
      <GenerationOptionsEditor
        type="infographic"
        values={DEFAULT_OPTIONS.infographic}
        onChange={vi.fn()}
      />,
    );
    expect(
      screen.queryByLabelText("Describe the infographic you want to create"),
    ).not.toBeInTheDocument();

    rerender(
      <GenerationOptionsEditor
        type="infographic"
        values={DEFAULT_OPTIONS.infographic}
        onChange={vi.fn()}
        prompt=""
        onPromptChange={onPromptChange}
      />,
    );
    await userEvent.type(screen.getByLabelText("Describe the infographic you want to create"), "x");
    expect(onPromptChange).toHaveBeenCalledWith("x");
  });
});
