import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { stagingApi } from "./api";
import type { OptionValues } from "../generationOptions";

const PENDING = new Set(["queued", "processing", "running"]);

export function useStaging(moduleId: string) {
  return useQuery({
    queryKey: ["admin", "staging", moduleId],
    queryFn: () => stagingApi.get(moduleId),
    // poll every 2.5s while anything is still resolving (spec §3.3)
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data) return 2500;
      return data.artifacts.some((a) => PENDING.has(a.status)) ? 2500 : false;
    },
  });
}

export function useRedo(moduleId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      artifactId,
      note,
      options,
      customPrompt,
    }: {
      artifactId: string;
      note: string | null;
      options?: OptionValues;
      customPrompt?: string;
    }) => stagingApi.redo(artifactId, note, options, customPrompt),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "staging", moduleId] }),
  });
}

/** Outline review: feedback revises the draft outline; without, builds the deck. */
export function useOutlineAction(moduleId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ artifactId, feedback }: { artifactId: string; feedback: string | null }) =>
      feedback
        ? stagingApi.outlineFeedback(artifactId, feedback)
        : stagingApi.outlineProceed(artifactId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "staging", moduleId] }),
  });
}

export function useRetry(moduleId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (artifactId: string) => stagingApi.retry(artifactId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "staging", moduleId] }),
  });
}

export function useInspect(artifactId: string, version?: string) {
  return useQuery({
    queryKey: ["admin", "inspect", artifactId, version ?? "current"],
    queryFn: () => stagingApi.inspect(artifactId, version),
  });
}
