import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";

interface QuizSettings {
  fresh_retakes: boolean;
}

export function FreshRetakesToggle({ moduleId }: { moduleId: string }): JSX.Element | null {
  const qc = useQueryClient();
  const key = ["admin", "quiz-settings", moduleId];
  const url = `/api/admin/modules/${moduleId}/quiz-settings`;
  const { data } = useQuery({ queryKey: key, queryFn: () => apiFetch<QuizSettings>(url) });
  const save = useMutation({
    mutationFn: (fresh_retakes: boolean) =>
      apiFetch<QuizSettings>(url, { method: "PATCH", body: { fresh_retakes } }),
    onSuccess: (d) => qc.setQueryData(key, d),
  });
  if (!data) return null;
  return (
    <label className="flex w-fit items-center gap-2 font-label-sm text-label-sm">
      <input
        type="checkbox"
        role="switch"
        data-testid="fresh-retakes"
        checked={data.fresh_retakes}
        disabled={save.isPending}
        onChange={(e) => save.mutate(e.target.checked)}
      />
      Fresh questions on retake
      <span className="text-on-surface-variant">({data.fresh_retakes ? "on" : "off"})</span>
      {save.isError && <span className="text-error">Could not save</span>}
    </label>
  );
}
