import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "@/lib/api";
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

export function useFlashcardRating(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ cardIndex, value }: { cardIndex: number; value: FlashcardRating }) =>
      workspaceApi.rateCard(id, cardIndex, value),
    onSuccess: ({ ratings }) => {
      qc.setQueryData<StudentArtifact>(["student", "artifact", id], (prev) =>
        prev ? { ...prev, flashcard_ratings: ratings } : prev,
      );
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
      if (body.completed || body.complete_module) {
        void qc.invalidateQueries({ queryKey: ["student", "workspace", slug] });
        void qc.invalidateQueries({ queryKey: ["student", "catalog"] });
        void qc.invalidateQueries({ queryKey: ["student", "artifact", id] });
      }
      return result;
    },
  });
}
