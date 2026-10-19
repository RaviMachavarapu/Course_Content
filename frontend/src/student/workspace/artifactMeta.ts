import type { ArtifactType } from "../catalog/api";

export interface ArtifactMeta {
  label: string;
  icon: string;
  /** Button-inventory id (spec.md §6). */
  ws: string;
}

/** Display order in the Module Explorer (spec.md §3.9). */
export const WORKSPACE_ARTIFACT_ORDER: ArtifactType[] = [
  "audio_overview",
  "slide_deck",
  "flashcards",
  "quiz",
  "infographic",
  "report",
];

export const ARTIFACT_META: Record<ArtifactType, ArtifactMeta> = {
  audio_overview: { label: "Audio", icon: "headphones", ws: "btn-ws3" },
  slide_deck: { label: "Slides", icon: "slideshow", ws: "btn-ws4" },
  flashcards: { label: "Flashcards", icon: "style", ws: "btn-ws5" },
  quiz: { label: "Quiz", icon: "quiz", ws: "btn-ws6" },
  infographic: { label: "Infographic", icon: "schema", ws: "btn-ws7" },
  report: { label: "Report", icon: "description", ws: "btn-ws8" },
};
