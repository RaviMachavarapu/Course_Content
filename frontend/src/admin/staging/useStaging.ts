import { type QueryClient, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { stagingApi } from "./api";
import type { OptionValues } from "../generationOptions";

const PENDING = new Set(["queued", "processing", "running"]);

/** After publish / redo / retry / outline actions: refresh this module's
 * staging view and every admin list that shows module or course status. */
export function invalidateAfterModuleChange(qc: QueryClient, moduleId: string): Promise<unknown> {
  return Promise.all([
    qc.invalidateQueries({ queryKey: ["admin", "staging", moduleId] }),
    qc.invalidateQueries({ queryKey: ["admin", "courses"] }),
    qc.invalidateQueries({ queryKey: ["admin", "pipeline"] }),
    qc.invalidateQueries({ queryKey: ["admin", "editor"] }),
  ]);
}

/** Poll every 2.5 s while anything is still resolving (spec §3.3). A failed
 * first load (module deleted → 404, session ended → 401) stops polling; the
 * page offers a retry instead. */
export function stagingPollInterval(
  data: { artifacts: { status: string }[] } | undefined,
  status: "pending" | "error" | "success",
): number | false {
  if (!data) return status === "error" ? false : 2500;
  return data.artifacts.some((a) => PENDING.has(a.status)) ? 2500 : false;
}

export function useStaging(moduleId: string) {
  return useQuery({
    queryKey: ["admin", "staging", moduleId],
    queryFn: () => stagingApi.get(moduleId),
    refetchInterval: (query) => stagingPollInterval(query.state.data, query.state.status),
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
    onSuccess: () => invalidateAfterModuleChange(qc, moduleId),
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
    onSuccess: () => invalidateAfterModuleChange(qc, moduleId),
  });
}

export function useRetry(moduleId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (artifactId: string) => stagingApi.retry(artifactId),
    onSuccess: () => invalidateAfterModuleChange(qc, moduleId),
  });
}

export function useInspect(artifactId: string, version?: string) {
  return useQuery({
    queryKey: ["admin", "inspect", artifactId, version ?? "current"],
    queryFn: () => stagingApi.inspect(artifactId, version),
  });
}
