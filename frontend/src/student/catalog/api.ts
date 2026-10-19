import { apiFetch } from "@/lib/api";

export type ArtifactType =
  | "slide_deck"
  | "flashcards"
  | "quiz"
  | "report"
  | "infographic"
  | "audio_overview";

export interface CatalogCourse {
  id: string;
  slug: string;
  title: string;
  description: string;
  category: string;
  cover_image_url: string | null;
  module_count: number;
  artifact_counts: Partial<Record<ArtifactType, number>>;
  total_audio_seconds: number | null;
  percent_complete: number;
  next_module_index: number;
}

export interface CatalogResponse {
  courses: CatalogCourse[];
  categories: string[];
}

export const catalogApi = {
  list: () => apiFetch<CatalogResponse>("/api/student/courses"),
};
