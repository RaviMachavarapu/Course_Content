import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ArtifactType } from "../api";
import { type AudioSettings, settingsApi } from "./api";

export function usePrompts() {
  return useQuery({ queryKey: ["admin", "prompts"], queryFn: settingsApi.listPrompts });
}

export function usePromptMutations() {
  const qc = useQueryClient();
  const invalidate = () => void qc.invalidateQueries({ queryKey: ["admin", "prompts"] });

  const save = useMutation({
    mutationFn: ({ type, body }: { type: ArtifactType; body: string }) =>
      settingsApi.updatePrompt(type, body),
    onSuccess: invalidate,
  });
  const restore = useMutation({
    mutationFn: (type: ArtifactType) => settingsApi.restorePrompt(type),
    onSuccess: invalidate,
  });
  return { save, restore };
}

export function useAudioSettings() {
  return useQuery({ queryKey: ["admin", "settings", "audio"], queryFn: settingsApi.getAudio });
}

export function useSaveAudio() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: AudioSettings) => settingsApi.saveAudio(body),
    onSuccess: (data) => qc.setQueryData(["admin", "settings", "audio"], data),
  });
}

export function useRefreshMcpAuth() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: settingsApi.refreshMcpAuth,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "mcp-status"] }),
  });
}

export function useAdminUsers() {
  return useQuery({ queryKey: ["admin", "users"], queryFn: settingsApi.listUsers });
}

export function useUserMutations() {
  const qc = useQueryClient();
  const invalidate = () => void qc.invalidateQueries({ queryKey: ["admin", "users"] });

  const create = useMutation({
    mutationFn: (body: { email: string; display_name: string; password: string }) =>
      settingsApi.createUser(body),
    onSuccess: invalidate,
  });
  const setActive = useMutation({
    mutationFn: ({ id, is_active }: { id: string; is_active: boolean }) =>
      settingsApi.setUserActive(id, is_active),
    onSuccess: invalidate,
  });
  return { create, setActive };
}
