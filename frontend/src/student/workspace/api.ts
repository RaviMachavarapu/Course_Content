import { apiFetch } from "@/lib/api";
import type { ArtifactType } from "../catalog/api";

export interface WorkspaceArtifact {
  id: string;
  type: ArtifactType;
  completed: boolean;
}

export interface WorkspaceModule {
  index: number;
  id: string;
  title: string;
  percent_complete: number;
  artifacts: WorkspaceArtifact[];
}

export interface WorkspaceCourse {
  id: string;
  slug: string;
  title: string;
  description: string;
  percent_complete: number;
  current_module_index: number;
  modules: WorkspaceModule[];
}

export interface StudentArtifact {
  id: string;
  type: ArtifactType;
  module_id: string;
  module_index: number;
  course_slug: string;
  revision: number;
  content_json: Record<string, unknown> | null;
  content_html: string | null;
  media: { kind: string; url: string; page_index: number | null }[];
  completed: boolean;
  slide_last_index: number | null;
  audio_position_seconds: number | null;
  flashcard_ratings: Record<string, FlashcardRating>;
}

export type FlashcardRating = "hard" | "good" | "easy";

export interface QuizResultRow {
  question_index: number;
  selected_index: number;
  correct_index: number;
  is_correct: boolean;
  explanation: string;
}

export interface QuizResult {
  attempt_id: string;
  score_percent: number;
  correct_count: number;
  total_count: number;
  results: QuizResultRow[];
  best_score_percent: number;
  latest_score_percent: number;
}

export interface QuizAttempt {
  id: string;
  score_percent: number;
  correct_count: number;
  total_count: number;
  submitted_at: string | null;
}

export interface QuizAttemptsResponse {
  attempts: QuizAttempt[];
  best_score_percent: number | null;
  latest_score_percent: number | null;
}

export interface ArtifactProgressInput {
  completed?: boolean;
  complete_module?: boolean;
  slide_last_index?: number;
  audio_position_seconds?: number;
}

export interface ArtifactProgressResult {
  completed: boolean;
  slide_last_index: number | null;
  audio_position_seconds: number | null;
  course_percent_complete: number;
}

export const workspaceApi = {
  course: (slug: string) => apiFetch<WorkspaceCourse>(`/api/student/courses/${slug}`),
  artifact: (id: string) => apiFetch<StudentArtifact>(`/api/student/artifacts/${id}`),
  putProgress: (id: string, body: ArtifactProgressInput) =>
    apiFetch<ArtifactProgressResult>(`/api/student/artifacts/${id}/progress`, {
      method: "PUT",
      body,
    }),
  rateCard: (id: string, cardIndex: number, value: FlashcardRating) =>
    apiFetch<{ ratings: Record<string, FlashcardRating> }>(
      `/api/student/artifacts/${id}/flashcard-ratings/${cardIndex}`,
      { method: "PUT", body: { value } },
    ),
  submitQuiz: (id: string, answers: Record<number, number>) =>
    apiFetch<QuizResult>(`/api/student/artifacts/${id}/quiz-attempts`, {
      method: "POST",
      body: { answers },
    }),
  quizAttempts: (id: string) =>
    apiFetch<QuizAttemptsResponse>(`/api/student/artifacts/${id}/quiz-attempts`),
};
