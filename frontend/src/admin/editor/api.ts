import { apiFetch } from "@/lib/api";
import type { ModuleSummary } from "../api";

export interface CourseDetail {
  id: string;
  title: string;
  slug: string;
  description: string;
  category: string;
  status: string;
  cover_image_key: string | null;
  created_at: string;
  updated_at: string;
  published_at: string | null;
  modules: ModuleSummary[];
}

export const editorApi = {
  getCourse: (courseId: string) =>
    apiFetch<{ course: CourseDetail }>(`/api/admin/courses/${courseId}`).then((r) => r.course),

  renameModule: (moduleId: string, title: string) =>
    apiFetch<ModuleSummary>(`/api/admin/courses/modules/${moduleId}`, {
      method: "PATCH",
      body: { title },
    }),

  moveModule: (moduleId: string, direction: "up" | "down") =>
    apiFetch<{ course: CourseDetail }>(`/api/admin/courses/modules/${moduleId}/move`, {
      method: "POST",
      body: { direction },
    }).then((r) => r.course),

  regenerateModule: (moduleId: string) =>
    apiFetch<{ module: ModuleSummary; job_ids: string[] }>(
      `/api/admin/courses/modules/${moduleId}/regenerate`,
      { method: "POST" },
    ),

  deleteModule: (moduleId: string) =>
    apiFetch<void>(`/api/admin/courses/modules/${moduleId}`, { method: "DELETE" }),
};
