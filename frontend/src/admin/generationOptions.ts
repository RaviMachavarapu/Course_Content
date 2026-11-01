/**
 * Per-artifact-type generation options — exactly the controls NotebookLM's
 * Studio dialogs offer on the connected account, with their labels, defaults
 * and dependencies, as recorded live on 2026-10-22
 * (docs/spikes/notebooklm-2026-10-capture.md). Validated backend-side by
 * `app/schemas/content_options.py`.
 *
 * Not offered because this account's dialogs don't have them: quiz "Include
 * images" and "Question types", and the per-source "Suggested template"
 * reports.
 */
import type { ArtifactType } from "./api";

export type OptionValue = string | boolean | null;
export type OptionValues = Record<string, OptionValue>;
export type OptionsByType = Partial<Record<ArtifactType, OptionValues>>;
export type PromptsByType = Partial<Record<ArtifactType, string>>;

interface Choice {
  value: string;
  label: string;
  /** Format cards only: NotebookLM's one-line explanation. */
  description?: string;
}

export interface OptionField {
  key: string;
  label: string;
  /** dropdown, button group, explanation cards, or an on/off switch */
  control: "select" | "segmented" | "cards" | "switch";
  choices: Choice[];
  /** Choices that depend on other values (e.g. audio length by format). */
  choicesFor?: (values: OptionValues) => Choice[];
  /** Hide the field unless this holds (e.g. report template for documents). */
  visible?: (values: OptionValues) => boolean;
  /** switch only: NotebookLM's explanation under the switch */
  description?: string;
}

/** Owner decision 2026-10-20: English plus five Indian languages. */
const LANGUAGE: OptionField = {
  key: "language",
  label: "Choose language",
  control: "select",
  choices: [
    { value: "en", label: "English" },
    { value: "hi", label: "Hindi" },
    { value: "te", label: "Telugu" },
    { value: "ta", label: "Tamil" },
    { value: "kn", label: "Kannada" },
    { value: "mr", label: "Marathi" },
  ],
};

const DIFFICULTY: OptionField = {
  key: "difficulty",
  label: "Level of difficulty",
  control: "segmented",
  choices: [
    { value: "easy", label: "Easy" },
    { value: "medium", label: "Medium (default)" },
    { value: "hard", label: "Hard" },
  ],
};

const quantity = (label: string): OptionField => ({
  key: "quantity",
  label,
  control: "segmented",
  choices: [
    { value: "fewer", label: "Fewer" },
    { value: "standard", label: "Standard (default)" },
    { value: "more", label: "More" },
  ],
});

const SHORT = { value: "short", label: "Short" };
const DEFAULT_LENGTH = { value: "default", label: "Default" };
const LONG = { value: "long", label: "Long" };

export const OPTION_FIELDS: Record<ArtifactType, OptionField[]> = {
  audio_overview: [
    {
      key: "format",
      label: "Format",
      control: "cards",
      choices: [
        {
          value: "deep_dive",
          label: "Deep dive",
          description:
            "A lively conversation between two hosts, unpacking and connecting topics in your sources",
        },
        {
          value: "brief",
          label: "Brief",
          description:
            "A bite-sized overview to help you grasp the core ideas from your sources quickly",
        },
        {
          value: "critique",
          label: "Critique",
          description:
            "An expert review of your sources, offering constructive feedback to help you improve your material",
        },
        {
          value: "debate",
          label: "Debate",
          description:
            "A thoughtful debate between two hosts, illuminating different perspectives on your sources",
        },
      ],
    },
    LANGUAGE,
    {
      key: "length",
      label: "Length",
      control: "segmented",
      choices: [SHORT, DEFAULT_LENGTH, LONG],
      // Recorded: Deep dive offers Long; Critique and Debate don't; Brief has none.
      choicesFor: (v) =>
        v.format === "deep_dive" ? [SHORT, DEFAULT_LENGTH, LONG] : [SHORT, DEFAULT_LENGTH],
      visible: (v) => v.format !== "brief",
    },
  ],
  slide_deck: [
    {
      key: "format",
      label: "Format",
      control: "cards",
      choices: [
        {
          value: "detailed",
          label: "Detailed deck",
          description:
            "A comprehensive deck with full text and details, perfect for emailing or reading on its own.",
        },
        {
          value: "presenter",
          label: "Presenter slides",
          description:
            "Clean, visual slides with key talking points to support you while you speak.",
        },
      ],
    },
    LANGUAGE,
    { key: "length", label: "Length", control: "segmented", choices: [SHORT, DEFAULT_LENGTH] },
    {
      key: "review_outline",
      label: "Review slide outline",
      control: "switch",
      choices: [],
      description:
        "Preview and edit the outline before creating your slide deck. Your draft outline will be ready in Studio in a few minutes.",
    },
  ],
  report: [
    {
      key: "format",
      label: "Format",
      control: "cards",
      choices: [
        {
          value: "interactive",
          label: "Interactive",
          description:
            "An interactive report with embedded studio content (the embedded items aren't shown in this app)",
        },
        { value: "document", label: "Document", description: "A structured text-only document" },
      ],
    },
    {
      key: "template",
      label: "Template",
      control: "cards",
      choices: [
        {
          value: "custom",
          label: "Create your own",
          description: "Craft reports your way by specifying structure, style, tone and more",
        },
        {
          value: "briefing_doc",
          label: "Briefing doc",
          description: "Overview of your sources featuring key insights and quotes",
        },
        {
          value: "study_guide",
          label: "Study guide",
          description: "Short-answer quiz, suggested essay questions and glossary of key terms",
        },
        {
          value: "blog_post",
          label: "Blog post",
          description: "Insightful takeaways distilled into a highly readable article",
        },
      ],
      visible: (v) => v.format === "document",
    },
    // NotebookLM offers a language only for "Create your own".
    { ...LANGUAGE, visible: (v) => v.format === "document" && v.template === "custom" },
  ],
  flashcards: [
    quantity("Number of cards"),
    DIFFICULTY,
    {
      key: "images",
      label: "Include images",
      control: "segmented",
      choices: [
        { value: "include", label: "Include (default)" },
        { value: "text_only", label: "Text only" },
      ],
    },
    LANGUAGE,
  ],
  quiz: [quantity("Number of questions"), DIFFICULTY, LANGUAGE],
  infographic: [
    LANGUAGE,
    {
      key: "orientation",
      label: "Choose orientation",
      control: "segmented",
      choices: [
        { value: "landscape", label: "Landscape" },
        { value: "portrait", label: "Portrait" },
        { value: "square", label: "Square" },
      ],
    },
    {
      key: "style",
      label: "Choose visual style",
      control: "cards",
      choices: [
        { value: "auto", label: "Auto-select" },
        { value: "sketch_note", label: "Sketch note" },
        { value: "kawaii", label: "Kawaii" },
        { value: "clay", label: "Clay" },
        { value: "anime", label: "Anime" },
        { value: "editorial", label: "Editorial" },
        { value: "instructional", label: "Instructional" },
        { value: "bento_grid", label: "Bento grid" },
        { value: "bricks", label: "Bricks" },
        { value: "scientific", label: "Scientific" },
        { value: "professional", label: "Professional" },
      ],
    },
    {
      key: "detail",
      label: "Level of detail",
      control: "segmented",
      choices: [
        { value: "concise", label: "Concise" },
        { value: "standard", label: "Standard" },
        { value: "detailed", label: "Detailed (BETA)" },
      ],
    },
  ],
};

/** NotebookLM's own defaults per type (match the backend's). */
export const DEFAULT_OPTIONS: Record<ArtifactType, OptionValues> = {
  audio_overview: { format: "deep_dive", length: "default", language: "en" },
  slide_deck: { format: "detailed", length: "default", language: "en", review_outline: false },
  report: { format: "interactive", template: null, language: "en" },
  flashcards: { quantity: "standard", difficulty: "medium", images: "include", language: "en" },
  quiz: { quantity: "standard", difficulty: "medium", language: "en" },
  infographic: { language: "en", orientation: "landscape", detail: "standard", style: "auto" },
};

/**
 * Keep a set of values consistent with what NotebookLM offers after one of
 * them changed (e.g. Debate has no Long; only custom reports pick a language).
 */
export function normalizeOptions(type: ArtifactType, values: OptionValues): OptionValues {
  const next = { ...values };
  if (type === "audio_overview") {
    if (next.format === "brief" || (next.format !== "deep_dive" && next.length === "long")) {
      next.length = "default";
    }
  }
  if (type === "report") {
    if (next.format !== "document") next.template = null;
    if (next.template !== "custom") next.language = "en";
  }
  return next;
}

/**
 * Why these values can't be sent yet, or null. (An empty "Create your own"
 * description is fine: the Settings report template is sent instead.)
 */
export function optionsProblem(type: ArtifactType, values: OptionValues): string | null {
  if (type === "report" && values.format === "document" && !values.template) {
    return "Choose a report template.";
  }
  return null;
}

/**
 * NotebookLM's free-text box per type. Text typed here replaces the
 * Settings → Generation Prompts template for that artifact (owner decision
 * 2026-10-20). Reports have one only for "Create your own", as in NotebookLM.
 * Placeholders are NotebookLM's own where they're generic; its audio,
 * flashcard and quiz placeholders are examples drawn from the user's sources,
 * so those aren't copied.
 */
export const PROMPT_FIELDS: Partial<
  Record<
    ArtifactType,
    { label: string; placeholder: string; visible?: (v: OptionValues) => boolean }
  >
> = {
  audio_overview: {
    label: "What should the AI hosts focus on in this episode?",
    placeholder: "",
  },
  slide_deck: {
    label: "Describe the slide deck you want to create",
    placeholder:
      'Add a high-level outline, or guide the audience, style, and focus: "Create a deck for beginners using a bold and playful style with a focus on step-by-step instructions."',
  },
  report: {
    label: "Describe the kind of report to create",
    placeholder: "",
    visible: (v) => v.format === "document" && v.template === "custom",
  },
  flashcards: { label: "What should the topic be?", placeholder: "" },
  quiz: { label: "What should the topic be?", placeholder: "" },
  infographic: {
    label: "Describe the infographic you want to create",
    placeholder:
      'Guide the style, color, or focus: "Use a blue color theme and highlight the 3 key stats."',
  },
};

export const PROMPT_HINT =
  "Replaces the Settings → Generation Prompts template for this artifact. Leave empty to use the template.";
