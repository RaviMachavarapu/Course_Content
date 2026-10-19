import { apiFetch } from "@/lib/api";
import type { ArtifactType } from "../api";

export interface PromptTemplate {
  artifact_type: ArtifactType;
  version: number;
  body: string;
  is_active: boolean;
  updated_at: string;
  updated_by: string | null;
}

export interface PromptDetail {
  active: PromptTemplate;
  history: PromptTemplate[];
}

export interface AudioSettings {
  voice: string;
  style: string;
}

export interface AudioSettingsResponse {
  settings: AudioSettings;
  voice_choices: string[];
  style_choices: string[];
}

export interface AdminUser {
  id: string;
  email: string;
  display_name: string;
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
}

export const settingsApi = {
  listPrompts: () =>
    apiFetch<{ templates: PromptTemplate[] }>("/api/admin/prompts").then((r) => r.templates),
  getPrompt: (type: ArtifactType) => apiFetch<PromptDetail>(`/api/admin/prompts/${type}`),
  updatePrompt: (type: ArtifactType, body: string) =>
    apiFetch<{ template: PromptTemplate }>(`/api/admin/prompts/${type}`, {
      method: "PUT",
      body: { body },
    }).then((r) => r.template),
  restorePrompt: (type: ArtifactType) =>
    apiFetch<{ template: PromptTemplate }>(`/api/admin/prompts/${type}/restore-default`, {
      method: "POST",
    }).then((r) => r.template),

  refreshMcpAuth: () => apiFetch<void>("/api/admin/mcp/refresh-auth", { method: "POST" }),

  getAudio: () => apiFetch<AudioSettingsResponse>("/api/admin/settings/audio"),
  saveAudio: (body: AudioSettings) =>
    apiFetch<AudioSettingsResponse>("/api/admin/settings/audio", { method: "PUT", body }),

  listUsers: () =>
    apiFetch<{ users: AdminUser[] }>("/api/admin/users").then((r) => r.users),
  createUser: (body: { email: string; display_name: string; password: string }) =>
    apiFetch<AdminUser>("/api/admin/users", { method: "POST", body }),
  setUserActive: (id: string, is_active: boolean) =>
    apiFetch<AdminUser>(`/api/admin/users/${id}`, { method: "PATCH", body: { is_active } }),
};
