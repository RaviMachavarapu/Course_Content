import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type ArtifactType, adminApi } from "./api";
import type { OptionsByType } from "./generationOptions";

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

export function useRecentPipeline(limit = 5) {
  return useQuery({
    queryKey: ["admin", "pipeline", "recent", limit],
    queryFn: () => adminApi.pipeline({ page_size: limit }),
    refetchInterval: 5_000,
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
  sourceUrl: string;
  moduleTitle: string;
  types: ArtifactType[];
  options?: OptionsByType;
}

export function useIngest() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (input: IngestInput) => {
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

      const res = await adminApi.createModule(courseId, {
        source_url: input.sourceUrl,
        title: input.moduleTitle,
        types: input.types,
        options: input.options,
      });
      return { courseId, moduleId: res.module.id };
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["admin", "pipeline"] });
      void qc.invalidateQueries({ queryKey: ["admin", "courses"] });
    },
  });
}
