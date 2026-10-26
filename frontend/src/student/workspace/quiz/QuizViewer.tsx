import { MathText } from "@/components/math/MathText";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button, Card, ErrorState, Icon, Skeleton } from "@/components";
import { cn } from "@/lib/cn";
import type { QuizResult } from "../api";
import { useQuizSubmit, useStudentArtifact } from "../useWorkspace";

interface Question {
  question: string;
  options: string[];
}

const LETTERS = ["A", "B", "C", "D"];

export function QuizViewer({ artifactId, slug }: { artifactId: string; slug: string }): JSX.Element {
  const { data, isPending, isError, refetch } = useStudentArtifact(artifactId);
  const submit = useQuizSubmit(artifactId, slug);
  const navigate = useNavigate();

  const questions = useMemo(
    () => ((data?.content_json?.questions ?? []) as Question[]),
    [data?.content_json],
  );
  const total = questions.length;

  const [answers, setAnswers] = useState<Record<number, number>>({});
  const [current, setCurrent] = useState(0);
  const [result, setResult] = useState<QuizResult | null>(null);

  if (isPending) return <Skeleton className="h-96" />;
  if (isError || !data || total === 0)
    return <ErrorState title="Quiz isn’t ready" onRetry={() => void refetch()} />;

  if (result) return <Results result={result} questions={questions} onRetake={() => {
    setResult(null);
    setAnswers({});
    setCurrent(0);
  }} onBack={() => navigate(`/learn/${slug}`)} />;

  const q = questions[current]!;
  const answeredCount = Object.keys(answers).length;
  const allAnswered = answeredCount === total;
  const isLast = current === total - 1;

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-4">
      <div className="flex items-center justify-between">
        <span className="font-label-md text-label-md text-on-surface-variant">
          Question {current + 1} of {total}
        </span>
        <span className="font-label-sm text-label-sm text-on-surface-variant">
          {answeredCount}/{total} answered
        </span>
      </div>

      <div className="flex gap-1" aria-hidden="true">
        {questions.map((_, i) => (
          <span
            key={i}
            className={cn(
              "h-1.5 flex-1 rounded-full",
              i === current
                ? "bg-tertiary"
                : answers[i] != null
                  ? "bg-secondary"
                  : "bg-surface-container-highest",
            )}
          />
        ))}
      </div>

      <Card className="p-5">
        <p className="font-headline-md text-headline-md"><MathText text={q.question} /></p>
        <div className="mt-4 flex flex-col gap-2">
          {q.options.map((opt, oi) => {
            const selected = answers[current] === oi;
            return (
              <button
                key={oi}
                type="button"
                data-testid={`btn-qz1-${oi}`}
                aria-pressed={selected}
                onClick={() => setAnswers((a) => ({ ...a, [current]: oi }))}
                className={cn(
                  "flex items-center gap-3 rounded-lg border px-3 py-2 text-left font-body-md text-body-md transition-colors",
                  "focus-visible:outline-none focus-visible:shadow-focus",
                  selected
                    ? "border-tertiary bg-tertiary-container/30 text-on-surface"
                    : "border-outline-variant hover:border-tertiary",
                )}
              >
                <span
                  className={cn(
                    "flex h-6 w-6 shrink-0 items-center justify-center rounded-full font-label-sm text-label-sm",
                    selected ? "bg-tertiary text-on-tertiary" : "bg-surface-container-high",
                  )}
                >
                  {LETTERS[oi]}
                </span>
                <MathText text={opt} />
              </button>
            );
          })}
        </div>
      </Card>

      <div className="flex items-center justify-between">
        <Button
          variant="secondary"
          size="sm"
          iconLeft="chevron_left"
          data-testid="btn-qz2"
          disabled={current === 0}
          onClick={() => setCurrent((c) => Math.max(0, c - 1))}
        >
          Previous
        </Button>
        {isLast ? (
          <Button
            data-testid="btn-qz4"
            loading={submit.isPending}
            disabled={!allAnswered}
            onClick={() =>
              submit.mutate(answers, { onSuccess: (r) => setResult(r) })
            }
          >
            Submit
          </Button>
        ) : (
          <Button
            variant="secondary"
            size="sm"
            iconRight="chevron_right"
            data-testid="btn-qz3"
            onClick={() => setCurrent((c) => Math.min(total - 1, c + 1))}
          >
            Next Question
          </Button>
        )}
      </div>
    </div>
  );
}

function Results({
  result,
  questions,
  onRetake,
  onBack,
}: {
  result: QuizResult;
  questions: Question[];
  onRetake: () => void;
  onBack: () => void;
}): JSX.Element {
  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-4">
      <Card className="flex flex-col items-center gap-2 p-6 text-center">
        <p className="text-display-lg font-display-lg text-tertiary" data-testid="quiz-score">
          {Math.round(result.score_percent)}%
        </p>
        <p className="font-label-md text-label-md text-on-surface-variant">
          {result.correct_count} of {result.total_count} correct
        </p>
        <p className="font-label-sm text-label-sm text-on-surface-variant">
          Best {Math.round(result.best_score_percent)}% · Latest{" "}
          {Math.round(result.latest_score_percent)}%
        </p>
        <div className="mt-2 flex gap-2">
          <Button variant="secondary" size="sm" iconLeft="replay" data-testid="btn-qz5" onClick={onRetake}>
            Retake
          </Button>
          <Button size="sm" iconLeft="arrow_back" data-testid="btn-qz6" onClick={onBack}>
            Back to module
          </Button>
        </div>
      </Card>

      <div className="flex flex-col gap-3">
        {result.results.map((row) => {
          const q = questions[row.question_index]!;
          return (
            <Card key={row.question_index} className="p-4" data-testid="quiz-result-row">
              <div className="flex items-start gap-2">
                <Icon
                  name={row.is_correct ? "check_circle" : "cancel"}
                  filled
                  className={row.is_correct ? "text-secondary" : "text-error"}
                />
                <div className="flex-1">
                  <p className="font-label-lg text-label-lg"><MathText text={q.question} /></p>
                  <p className="mt-1 text-body-md text-on-surface-variant">
                    Your answer: {LETTERS[row.selected_index]}. <MathText text={q.options[row.selected_index] ?? ""} />
                  </p>
                  {!row.is_correct && (
                    <p className="text-body-md text-secondary">
                      Correct: {LETTERS[row.correct_index]}. <MathText text={q.options[row.correct_index] ?? ""} />
                    </p>
                  )}
                  {row.explanation && (
                    <p className="mt-1 text-body-sm text-on-surface-variant"><MathText text={row.explanation} /></p>
                  )}
                </div>
              </div>
            </Card>
          );
        })}
      </div>
    </div>
  );
}
