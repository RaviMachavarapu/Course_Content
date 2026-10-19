import { apiFetch } from "@/lib/api";

export interface MyProgressCourse {
  id: string;
  slug: string;
  title: string;
  percent_complete: number;
  modules_started: number;
  modules_total: number;
}

export interface ListeningRow {
  artifact_id: string;
  course_slug: string;
  course_title: string;
  module_index: number;
  module_title: string;
  duration_seconds: number;
  audio_position_seconds: number;
  percent_listened: number;
  completed: boolean;
}

export interface Achievement {
  key: string;
  label: string;
  description: string;
  icon: string;
  earned: boolean;
  earned_at: string | null;
}

export const meApi = {
  progress: () =>
    apiFetch<{ courses: MyProgressCourse[] }>("/api/student/me/progress").then(
      (r) => r.courses,
    ),
  listening: () =>
    apiFetch<{ rows: ListeningRow[] }>("/api/student/me/listening").then((r) => r.rows),
  achievements: () =>
    apiFetch<{ earned: Achievement[]; locked: Achievement[] }>(
      "/api/student/me/achievements",
    ),
};
