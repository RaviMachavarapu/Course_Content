import { type QueryClient, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "@/lib/api";
import { useUIStore } from "@/lib/store";
import {
  type ArtifactProgressInput,
  type FlashcardRating,
  type StudentArtifact,
  workspaceApi,
} from "./api";

export function useWorkspaceCourse(slug: string) {
  return useQuery({
    queryKey: ["student", "workspace", slug],
    queryFn: () => workspaceApi.course(slug),
    enabled: Boolean(slug),
    retry: (count, err) => !(err instanceof ApiError && err.status === 404) && count < 2,
  });
}

export function useStudentArtifact(id: string | undefined) {
  return useQuery({
    queryKey: ["student", "artifact", id],
    queryFn: () => workspaceApi.artifact(id as string),
    enabled: Boolean(id),
    retry: (count, err) => !(err instanceof ApiError && err.status === 404) && count < 2,
  });
}

export function isStaleVersion(err: unknown): boolean {
  return err instanceof ApiError && err.status === 409 && err.code === "stale_version";
}

/** Another version was published while this page showed the old one: say so
 * and load the new one (the write was refused, nothing was saved). */
function reloadStale(qc: QueryClient, id: string, slug?: string): void {
  const type = qc.getQueryData<StudentArtifact>(["student", "artifact", id])?.type;
  useUIStore.getState().pushToast({
    tone: "info",
    title:
      type === "flashcards"
        ? "This deck was updated — reloading"
        : "This lesson was updated — reloading",
  });
  void qc.invalidateQueries({ queryKey: ["student", "artifact", id] });
  if (slug) void qc.invalidateQueries({ queryKey: ["student", "workspace", slug] });
}

export function useFlashcardRating(id: string, slug?: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      cardIndex,
      value,
      versionId,
    }: {
      cardIndex: number;
      value: FlashcardRating;
      versionId?: string;
    }) => workspaceApi.rateCard(id, cardIndex, value, versionId),
    onSuccess: ({ ratings }) => {
      qc.setQueryData<StudentArtifact>(["student", "artifact", id], (prev) =>
        prev ? { ...prev, flashcard_ratings: ratings } : prev,
      );
    },
    onError: (err) => {
      if (isStaleVersion(err)) reloadStale(qc, id, slug);
    },
  });
}

export function useQuizAttempts(id: string, enabled = true) {
  return useQuery({
    queryKey: ["student", "quiz-attempts", id],
    queryFn: () => workspaceApi.quizAttempts(id),
    enabled: Boolean(id) && enabled,
  });
}

/** Persist per-artifact progress; refresh the shell + catalog on completion. */
export function useArtifactProgress(id: string, slug: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ArtifactProgressInput) => workspaceApi.putProgress(id, body),
    onSuccess: (result, body) => {
      // Keep the cached artifact in step with what the server saved, so coming
      // back to this deck/episode resumes from the latest position (not the one
      // from the first load) and doesn't then overwrite it.
      qc.setQueryData<StudentArtifact>(["student", "artifact", id], (prev) =>
        prev
          ? {
              ...prev,
              completed: result.completed,
              slide_last_index: result.slide_last_index,
              audio_position_seconds: result.audio_position_seconds,
            }
          : prev,
      );
      void qc.invalidateQueries({ queryKey: ["student", "me"] });
      if (body.completed || body.complete_module) {
        void qc.invalidateQueries({ queryKey: ["student", "workspace", slug] });
        void qc.invalidateQueries({ queryKey: ["student", "catalog"] });
        void qc.invalidateQueries({ queryKey: ["student", "artifact", id] });
      }
      return result;
    },
    onError: (err) => {
      if (isStaleVersion(err)) reloadStale(qc, id, slug);
    },
  });
}
