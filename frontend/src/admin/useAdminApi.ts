import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type ArtifactType, adminApi } from "./api";
import type { OptionsByType, PromptsByType } from "./generationOptions";

export function useMcpStatus() {
  return useQuery({
    queryKey: ["admin", "mcp-status"],
    queryFn: adminApi.mcpStatus,
    refetchInterval: 30_000,
    staleTime: 25_000,
  });
}

export function useRecentJobs() {
  return useQuery({
    queryKey: ["admin", "jobs", "recent"],
    queryFn: adminApi.recentJobs,
    refetchInterval: 10_000,
    staleTime: 8_000,
  });
}

export function usePipeline(params: { page: number; status?: string; q?: string }) {
  return useQuery({
    queryKey: ["admin", "pipeline", params],
    queryFn: () => adminApi.pipeline({ ...params, page_size: 20 }),
  });
}

export function useCourses() {
  return useQuery({ queryKey: ["admin", "courses"], queryFn: adminApi.listCourses });
}

export interface IngestInput {
  target:
    | { kind: "new"; title: string; description: string; category: string }
    | { kind: "existing"; courseId: string };
  sourceUrl?: string;
  uploadIds?: string[];
  moduleTitle: string;
  types: ArtifactType[];
  options?: OptionsByType;
  prompts?: PromptsByType;
}

/** Thrown when the "new course" step succeeded but creating the module didn't:
 * the course now exists, so a retry must add the module to it rather than
 * create another (empty) course. */
export class ModuleCreateError extends Error {
  readonly cause: unknown;
  readonly createdCourseId: string;

  constructor(cause: unknown, createdCourseId: string) {
    super(cause instanceof Error ? cause.message : "Could not create the module");
    this.name = "ModuleCreateError";
    this.cause = cause;
    this.createdCourseId = createdCourseId;
  }
}

export function useIngest() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (input: IngestInput) => {
      const isNew = input.target.kind === "new";
      const courseId =
        input.target.kind === "new"
          ? (
              await adminApi.createCourse({
                title: input.target.title,
                description: input.target.description,
                category: input.target.category,
              })
            ).id
          : input.target.courseId;

      let res: Awaited<ReturnType<typeof adminApi.createModule>>;
      try {
        res = await adminApi.createModule(courseId, {
          source_url: input.sourceUrl?.trim() || undefined,
          upload_ids: input.uploadIds?.length ? input.uploadIds : undefined,
          title: input.moduleTitle,
          types: input.types,
          options: input.options,
          prompts: input.prompts,
        });
      } catch (err) {
        if (!isNew) throw err;
        void qc.invalidateQueries({ queryKey: ["admin", "courses"] });
        throw new ModuleCreateError(err, courseId);
      }
      return { courseId, moduleId: res.module.id };
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["admin", "pipeline"] });
      void qc.invalidateQueries({ queryKey: ["admin", "courses"] });
    },
  });
}
