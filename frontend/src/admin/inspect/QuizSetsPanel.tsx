import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Card, CardBody, Skeleton } from "@/components";
import { MathText } from "@/components/math/MathText";
import { apiFetch } from "@/lib/api";

export interface QuizSetQuestion {
  type?: string;
  question?: string;
  options?: string[];
  correct_index?: number;
  answer?: string;
  accepted_answers?: string[];
  explanation?: string;
}

export interface QuizSetItem {
  id: string;
  source: string;
  status: string;
  created_at: string;
  student: { display_name: string; email: string };
  question_count: number;
  kept: number;
  dropped: number;
  dropped_questions: {
    round: number | null;
    index: number | null;
    question: string;
    reason: string;
  }[];
  error: string | null;
  questions: QuizSetQuestion[];
}

export function useQuizSets(artifactId: string, enabled: boolean) {
  return useQuery({
    queryKey: ["admin", "quiz-sets", artifactId],
    queryFn: () => apiFetch<QuizSetItem[]>(`/api/admin/artifacts/${artifactId}/quiz-sets?limit=20`),
    enabled,
  });
}

function answerOf(q: QuizSetQuestion): string {
  if (q.type === "mcq" && q.options && q.correct_index !== undefined)
    return q.options[q.correct_index] ?? "";
  return q.answer ?? "";
}

function SetRow({ set }: { set: QuizSetItem }): JSX.Element {
  const [open, setOpen] = useState(false);
  return (
    <li className="border-b border-outline-variant/60 py-2 last:border-0" data-testid="quiz-set">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="flex w-full flex-wrap items-center justify-between gap-2 text-left font-label-sm text-label-sm"
      >
        <span>
          {new Date(set.created_at).toLocaleString()} · {set.student.display_name} (
          {set.student.email})
        </span>
        <span className="text-on-surface-variant">
          {set.source} · {set.status} · {set.question_count} questions · {set.kept} kept /{" "}
          {set.dropped} dropped
        </span>
      </button>
      {open && (
        <div className="mt-2 flex flex-col gap-3">
          {set.error && <p className="text-error">{set.error}</p>}
          <ol className="list-decimal space-y-2 pl-5">
            {set.questions.map((q, i) => (
              <li key={i}>
                <MathText text={q.question ?? ""} />
                {q.type === "mcq" && q.options && (
                  <ul className="ml-3 list-disc text-on-surface-variant">
                    {q.options.map((o, j) => (
                      <li key={j}>
                        <MathText text={o} />
                      </li>
                    ))}
                  </ul>
                )}
                <p className="font-semibold">
                  Answer: <MathText text={answerOf(q)} />
                </p>
                {q.explanation && (
                  <p className="text-on-surface-variant">
                    <MathText text={q.explanation} />
                  </p>
                )}
              </li>
            ))}
          </ol>
          {set.dropped_questions.length > 0 && (
            <div>
              <p className="font-label-md font-semibold">Dropped questions</p>
              <ul className="list-disc space-y-1 pl-5" data-testid="quiz-set-dropped">
                {set.dropped_questions.map((d, i) => (
                  <li key={i}>
                    <MathText text={d.question} /> <span className="text-error">— {d.reason}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </li>
  );
}

export function QuizSetsPanel({ artifactId }: { artifactId: string }): JSX.Element {
  const { data, isPending, isError } = useQuizSets(artifactId, true);
  return (
    <Card>
      <CardBody className="p-4">
        <p className="mb-2 font-label-md text-label-md font-semibold">Generated question sets</p>
        {isPending ? (
          <Skeleton lines={3} />
        ) : isError ? (
          <p className="text-label-sm text-error">Could not load generated sets.</p>
        ) : data.length === 0 ? (
          <p className="text-label-sm text-on-surface-variant">No sets generated yet.</p>
        ) : (
          <ul>
            {data.map((s) => (
              <SetRow key={s.id} set={s} />
            ))}
          </ul>
        )}
      </CardBody>
    </Card>
  );
}
