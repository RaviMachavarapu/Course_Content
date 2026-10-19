import { apiFetch } from "@/lib/api";
import type { ArtifactType } from "../api";

export interface MediaOut {
  kind: string;
  url: string;
  size_bytes: number;
  page_index: number | null;
}

export interface CurrentVersion {
  id: string;
  revision: number;
  redo_note: string | null;
  created_at: string;
  media: MediaOut[];
  preview: Record<string, unknown>;
}

export interface StagingArtifact {
  id: string;
  type: ArtifactType;
  status: string;
  last_error: string | null;
  current_version: CurrentVersion | null;
  job: { state: string | null };
  generation_options: Record<string, string>;
}

export interface StagingResponse {
  module: {
    id: string;
    title: string;
    status: string;
    course_id: string;
    course_status: string;
  };
  artifacts: StagingArtifact[];
}

export interface VersionHistoryItem {
  id: string;
  revision: number;
  created_at: string;
  redo_note: string | null;
  is_current: boolean;
  is_published: boolean;
}

export interface InspectVersion {
  id: string;
  revision: number;
  redo_note: string | null;
  focus_prompt_used: string;
  prompt_template_version: number | null;
  generation_job_id: string | null;
  notebooklm_artifact_id: string | null;
  created_at: string;
  content_json: Record<string, unknown> | null;
  content_html: string | null;
  media: MediaOut[];
}

export interface InspectResponse {
  artifact: {
    id: string;
    type: ArtifactType;
    status: string;
    module_id: string;
    last_error: string | null;
  };
  notebooklm_notebook_id: string | null;
  viewing: InspectVersion | null;
  history: VersionHistoryItem[];
}

export const stagingApi = {
  get: (moduleId: string) => apiFetch<StagingResponse>(`/api/admin/modules/${moduleId}/staging`),

  redo: (artifactId: string, note: string | null, options?: Record<string, string>) =>
    apiFetch<{ job: { id: string; state: string } }>(`/api/admin/artifacts/${artifactId}/redo`, {
      method: "POST",
      body: { note, options },
    }),

  retry: (artifactId: string) =>
    apiFetch<{ job: { id: string; state: string } }>(`/api/admin/artifacts/${artifactId}/retry`, {
      method: "POST",
    }),

  inspect: (artifactId: string, version?: string) =>
    apiFetch<InspectResponse>(
      `/api/admin/artifacts/${artifactId}${version ? `?version=${version}` : ""}`,
    ),
};
