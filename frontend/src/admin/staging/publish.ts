import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import type { ArtifactType } from "../api";

export interface PublishResult {
  published: ArtifactType[];
  skipped: { type: ArtifactType; status: string; reason: string }[];
  module_status: string | null;
  course_status: string;
}

const publishModule = (moduleId: string) =>
  apiFetch<PublishResult>(`/api/admin/modules/${moduleId}/publish`, { method: "POST" });

const publishCourse = (courseId: string) =>
  apiFetch<PublishResult>(`/api/admin/courses/${courseId}/publish`, { method: "POST" });

export function usePublish(moduleId: string) {
  const qc = useQueryClient();
  const invalidate = () => qc.invalidateQueries({ queryKey: ["admin", "staging", moduleId] });
  return {
    module: useMutation({ mutationFn: () => publishModule(moduleId), onSuccess: invalidate }),
    course: useMutation({
      mutationFn: (courseId: string) => publishCourse(courseId),
      onSuccess: invalidate,
    }),
  };
}
