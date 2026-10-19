/**
 * Per-artifact-type generation options mirroring NotebookLM's own Studio UI
 * (Language, Length, Quantity/Difficulty, etc.) — validated backend-side
 * against `app/schemas/content_options.py`. Only fields confirmed in the
 * pinned `notebooklm-mcp-server`'s own tool docs are modeled here; see
 * `docs/spikes/O1-infographic.md` / `O2-audio.md` for what's still pending a
 * live check (e.g. slide deck's Format/Length shown on the NotebookLM web
 * page aren't confirmed as real API parameters yet).
 */
import type { ArtifactType } from "./api";

export type OptionsByType = Partial<Record<ArtifactType, Record<string, string>>>;

interface OptionField {
  key: string;
  label: string;
  choices: { value: string; label: string }[];
}

export const OPTION_FIELDS: Record<ArtifactType, OptionField[]> = {
  slide_deck: [
    {
      key: "language",
      label: "Language",
      choices: [
        { value: "en", label: "English" },
        { value: "es", label: "Spanish" },
        { value: "fr", label: "French" },
        { value: "de", label: "German" },
        { value: "hi", label: "Hindi" },
      ],
    },
  ],
  report: [
    {
      key: "language",
      label: "Language",
      choices: [
        { value: "en", label: "English" },
        { value: "es", label: "Spanish" },
        { value: "fr", label: "French" },
        { value: "de", label: "German" },
        { value: "hi", label: "Hindi" },
      ],
    },
  ],
  flashcards: [
    {
      key: "quantity",
      label: "Quantity",
      choices: [
        { value: "fewer", label: "Fewer" },
        { value: "standard", label: "Standard" },
        { value: "more", label: "More" },
      ],
    },
    {
      key: "difficulty",
      label: "Difficulty",
      choices: [
        { value: "easy", label: "Easy" },
        { value: "medium", label: "Medium" },
        { value: "hard", label: "Hard" },
      ],
    },
  ],
  quiz: [
    {
      key: "quantity",
      label: "Quantity",
      choices: [
        { value: "fewer", label: "Fewer" },
        { value: "standard", label: "Standard" },
        { value: "more", label: "More" },
      ],
    },
    {
      key: "difficulty",
      label: "Difficulty",
      choices: [
        { value: "easy", label: "Easy" },
        { value: "medium", label: "Medium" },
        { value: "hard", label: "Hard" },
      ],
    },
  ],
  audio_overview: [
    {
      key: "format",
      label: "Format",
      choices: [
        { value: "deep_dive", label: "Deep dive" },
        { value: "brief", label: "Brief" },
        { value: "critique", label: "Critique" },
        { value: "debate", label: "Debate" },
      ],
    },
    {
      key: "length",
      label: "Length",
      choices: [
        { value: "short", label: "Short" },
        { value: "default", label: "Default" },
        { value: "long", label: "Long" },
      ],
    },
    {
      key: "language",
      label: "Language",
      choices: [
        { value: "en", label: "English" },
        { value: "es", label: "Spanish" },
        { value: "fr", label: "French" },
        { value: "de", label: "German" },
        { value: "hi", label: "Hindi" },
      ],
    },
  ],
  infographic: [
    {
      key: "orientation",
      label: "Orientation",
      choices: [
        { value: "landscape", label: "Landscape" },
        { value: "portrait", label: "Portrait" },
        { value: "square", label: "Square" },
      ],
    },
    {
      key: "language",
      label: "Language",
      choices: [
        { value: "en", label: "English" },
        { value: "es", label: "Spanish" },
        { value: "fr", label: "French" },
        { value: "de", label: "German" },
        { value: "hi", label: "Hindi" },
      ],
    },
  ],
};

export const DEFAULT_OPTIONS: Record<ArtifactType, Record<string, string>> = Object.fromEntries(
  (Object.keys(OPTION_FIELDS) as ArtifactType[]).map((type) => [
    type,
    Object.fromEntries(OPTION_FIELDS[type].map((f) => [f.key, f.choices[0]!.value])),
  ]),
) as Record<ArtifactType, Record<string, string>>;

// NotebookLM's actual defaults aren't always "first choice" — set the ones
// that differ from OPTION_FIELDS[type][i].choices[0].
DEFAULT_OPTIONS.flashcards = { quantity: "standard", difficulty: "medium" };
DEFAULT_OPTIONS.quiz = { quantity: "standard", difficulty: "medium" };
DEFAULT_OPTIONS.audio_overview = { format: "deep_dive", length: "default", language: "en" };
