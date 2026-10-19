import { apiFetch } from "@/lib/api";

export type ArtifactType =
  "slide_deck" | "flashcards" | "quiz" | "report" | "infographic" | "audio_overview";

export const ARTIFACT_TYPES: ArtifactType[] = [
  "slide_deck",
  "flashcards",
  "quiz",
  "report",
  "infographic",
  "audio_overview",
];

export const ARTIFACT_LABELS: Record<ArtifactType, string> = {
  slide_deck: "Slide Deck",
  flashcards: "Flashcards",
  quiz: "Quiz",
  report: "Report",
  infographic: "Infographic",
  audio_overview: "Audio Overview",
};

export interface McpStatus {
  healthy: boolean;
  account_email: string | null;
  last_ok_at: string | null;
  detail: string;
  worker_last_heartbeat_at: string | null;
  worker_heartbeat_stale: boolean;
  jobs_succeeded: number;
  jobs_failed: number;
}

export interface CourseSummary {
  id: string;
  title: string;
  slug: string;
  category: string;
  status: string;
  module_count: number;
  updated_at: string;
  published_at: string | null;
}

export interface ArtifactSummary {
  id: string;
  type: ArtifactType;
  status: string;
}

export interface ModuleSummary {
  id: string;
  order_index: number;
  title: string;
  source_url: string;
  source_type: string;
  status: string;
  artifacts: ArtifactSummary[];
}

export interface PipelineRow {
  module_id: string;
  course_id: string;
  course_title: string;
  module_title: string;
  source_url: string;
  created_at: string;
  global_status: string;
  dots: { type: ArtifactType; status: string }[];
}

export interface PipelineResponse {
  rows: PipelineRow[];
  page: number;
  page_size: number;
  total: number;
}

export interface RecentJob {
  id: string;
  kind: string;
  state: "succeeded" | "failed";
  artifact_type: ArtifactType | null;
  module_id: string | null;
  module_title: string | null;
  course_id: string | null;
  error_detail: string | null;
  at: string;
}

export const adminApi = {
  mcpStatus: () => apiFetch<McpStatus>("/api/admin/mcp/status"),

  listCourses: () =>
    apiFetch<{ courses: CourseSummary[] }>("/api/admin/courses").then((r) => r.courses),

  createCourse: (body: { title: string; description?: string; category?: string }) =>
    apiFetch<{ course: { id: string } }>("/api/admin/courses", { method: "POST", body }).then(
      (r) => r.course,
    ),

  createModule: (
    courseId: string,
    body: {
      source_url: string;
      title: string;
      types: ArtifactType[];
      options?: Record<string, Record<string, string>>;
    },
  ) =>
    apiFetch<{ module: ModuleSummary; job_ids: string[] }>(
      `/api/admin/courses/${courseId}/modules`,
      { method: "POST", body },
    ),

  recentJobs: () =>
    apiFetch<{ jobs: RecentJob[] }>("/api/admin/jobs/recent").then((r) => r.jobs),

  pipeline: (params: { page?: number; page_size?: number; status?: string; q?: string } = {}) => {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) if (v != null && v !== "") qs.set(k, String(v));
    const suffix = qs.toString() ? `?${qs}` : "";
    return apiFetch<PipelineResponse>(`/api/admin/pipeline${suffix}`);
  },
};
