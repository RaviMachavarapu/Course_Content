import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { editorApi } from "./api";

export function useCourseStructure(courseId: string) {
  return useQuery({
    queryKey: ["admin", "editor", "course", courseId],
    queryFn: () => editorApi.getCourse(courseId),
    enabled: Boolean(courseId),
  });
}

export function useModuleOps(courseId: string) {
  const qc = useQueryClient();
  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ["admin", "editor", "course", courseId] });
    void qc.invalidateQueries({ queryKey: ["admin", "courses"] });
    void qc.invalidateQueries({ queryKey: ["admin", "pipeline"] });
  };

  const rename = useMutation({
    mutationFn: ({ moduleId, title }: { moduleId: string; title: string }) =>
      editorApi.renameModule(moduleId, title),
    onSuccess: invalidate,
  });

  const move = useMutation({
    mutationFn: ({ moduleId, direction }: { moduleId: string; direction: "up" | "down" }) =>
      editorApi.moveModule(moduleId, direction),
    onSuccess: (course) => {
      qc.setQueryData(["admin", "editor", "course", courseId], course);
      invalidate();
    },
  });

  const regenerate = useMutation({
    mutationFn: (moduleId: string) => editorApi.regenerateModule(moduleId),
    onSuccess: invalidate,
  });

  const remove = useMutation({
    mutationFn: (moduleId: string) => editorApi.deleteModule(moduleId),
    onSuccess: invalidate,
  });

  return { rename, move, regenerate, remove };
}
