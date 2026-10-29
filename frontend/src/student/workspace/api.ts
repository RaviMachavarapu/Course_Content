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
  /** The published version shown; flashcard writes echo it (409 stale_version). */
  version_id: string;
  content_json: Record<string, unknown> | null;
  content_html: string | null;
  media: { kind: string; url: string; page_index: number | null }[];
  completed: boolean;
  slide_last_index: number | null;
  audio_position_seconds: number | null;
  flashcard_ratings: Record<string, FlashcardRating>;
}

export type FlashcardRating = "hard" | "good" | "easy";

export interface QuizCheckResult {
  index: number;
  response: number | string;
  correct: boolean;
  correct_answer: string;
  correct_index: number | null;
  explanation: string;
}

export interface QuizAttemptQuestion {
  index: number;
  type: "mcq" | "fill_blank";
  question: string;
  options: string[] | null;
  result: QuizCheckResult | null;
}

export interface QuizAttemptStart {
  status: "started" | "resumed";
  attempt_id: string;
  attempt_number: number;
  source: "studio" | "chat";
  total_count: number;
  checked_count: number;
  correct_count: number;
  started_at: string;
  questions: QuizAttemptQuestion[];
}

export interface QuizPreparing {
  status: "preparing";
  message: string;
}

export interface QuizReviewRow {
  index: number;
  type: "mcq" | "fill_blank";
  question: string;
  options: string[] | null;
  response: number | string;
  correct: boolean;
  correct_answer: string;
  correct_index: number | null;
  explanation: string;
}

export interface QuizResult {
  attempt_id: string;
  score_percent: number;
  correct_count: number;
  total_count: number;
  completed_at: string;
  review: QuizReviewRow[];
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
  /** The version the page shows: a newer published one makes this a 409. */
  version_id?: string;
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
  rateCard: (id: string, cardIndex: number, value: FlashcardRating, versionId?: string) =>
    apiFetch<{ ratings: Record<string, FlashcardRating> }>(
      `/api/student/artifacts/${id}/flashcard-ratings/${cardIndex}`,
      { method: "PUT", body: { value, version_id: versionId } },
    ),
  startQuiz: (id: string) =>
    apiFetch<QuizAttemptStart | QuizPreparing>(`/api/student/artifacts/${id}/quiz-attempts`, {
      method: "POST",
    }),
  checkQuizAnswer: (attemptId: string, index: number, response: number | string) =>
    apiFetch<QuizCheckResult>(`/api/student/quiz-attempts/${attemptId}/answers`, {
      method: "POST",
      body: { index, response },
    }),
  completeQuiz: (attemptId: string) =>
    apiFetch<QuizResult>(`/api/student/quiz-attempts/${attemptId}/complete`, { method: "POST" }),
  quizAttempts: (id: string) =>
    apiFetch<QuizAttemptsResponse>(`/api/student/artifacts/${id}/quiz-attempts`),
};
