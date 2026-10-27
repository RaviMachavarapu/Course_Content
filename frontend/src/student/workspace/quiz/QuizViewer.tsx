import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { Button, Card, ErrorState, Icon, Skeleton } from "@/components";
import { PdfDownloadLink } from "@/components/PdfDownloadLink";
import { cn } from "@/lib/cn";
import { ApiError } from "@/lib/api";
import { MathText } from "@/components/math/MathText";
import {
  type QuizAttemptQuestion,
  type QuizAttemptStart,
  type QuizCheckResult,
  type QuizResult,
  workspaceApi,
} from "../api";
import { useStudentArtifact } from "../useWorkspace";

const LETTERS = ["A", "B", "C", "D"];
const POLL_MS = 3000;
const POLL_GIVE_UP_MS = 120_000;
export const PREPARING_MESSAGE = "Preparing new questions…";
export const UNAVAILABLE_MESSAGE =
  "New questions aren't available right now — please try again later";

type Phase =
  | { kind: "loading" }
  | { kind: "preparing" }
  | { kind: "unavailable" }
  | { kind: "error" }
  | { kind: "running"; attempt: QuizAttemptStart }
  | { kind: "results"; result: QuizResult };

export function QuizViewer({
  artifactId,
  slug,
}: {
  artifactId: string;
  slug: string;
}): JSX.Element {
  const { data, isPending, isError, refetch } = useStudentArtifact(artifactId);
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [phase, setPhase] = useState<Phase>({ kind: "loading" });
  const runRef = useRef(0);

  /** Start (or resume) an attempt; while the server prepares a set, poll every 3 s. */
  const begin = useCallback(async () => {
    const run = ++runRef.current;
    setPhase({ kind: "loading" });
    let waited = 0;
    for (;;) {
      try {
        const r = await workspaceApi.startQuiz(artifactId);
        if (run !== runRef.current) return;
        if (r.status === "preparing") {
          if (waited >= POLL_GIVE_UP_MS) {
            setPhase({ kind: "unavailable" });
            return;
          }
          setPhase({ kind: "preparing" });
          await new Promise((res) => setTimeout(res, POLL_MS));
          waited += POLL_MS;
          if (run !== runRef.current) return;
          continue;
        }
        setPhase(r.questions.length === 0 ? { kind: "error" } : { kind: "running", attempt: r });
        return;
      } catch (e) {
        if (run !== runRef.current) return;
        setPhase({ kind: e instanceof ApiError && e.status === 409 ? "unavailable" : "error" });
        return;
      }
    }
  }, [artifactId]);

  useEffect(() => {
    void begin();
    return () => {
      runRef.current += 1;
    };
  }, [begin]);

  if (isPending || phase.kind === "loading") return <Skeleton className="h-96" />;
  if (isError || !data)
    return <ErrorState title="Quiz isn’t ready" onRetry={() => void refetch()} />;

  const pdf = (
    <div className="flex justify-end">
      <PdfDownloadLink media={data.media} kind="quiz_questions_pdf" testid="btn-qz7" />
    </div>
  );

  if (phase.kind === "error")
    return <ErrorState title="Quiz isn’t ready" onRetry={() => void begin()} />;

  if (phase.kind === "preparing")
    return (
      <div className="mx-auto flex max-w-2xl flex-col gap-4">
        <Card className="flex flex-col items-center gap-3 p-8 text-center" role="status">
          <Icon name="hourglass_top" className="text-tertiary" />
          <p className="font-label-lg text-label-lg">{PREPARING_MESSAGE}</p>
        </Card>
      </div>
    );

  if (phase.kind === "unavailable")
    return (
      <div className="mx-auto flex max-w-2xl flex-col gap-4">
        <Card className="flex flex-col items-center gap-3 p-8 text-center" role="alert">
          <p className="font-label-lg text-label-lg">{UNAVAILABLE_MESSAGE}</p>
          <div className="flex gap-2">
            <Button size="sm" data-testid="btn-qz9" onClick={() => void begin()}>
              Try again
            </Button>
            <Button
              variant="secondary"
              size="sm"
              iconLeft="arrow_back"
              data-testid="btn-qz6"
              onClick={() => navigate(`/learn/${slug}`)}
            >
              Back to module
            </Button>
          </div>
        </Card>
      </div>
    );

  if (phase.kind === "results")
    return (
      <div className="mx-auto flex max-w-2xl flex-col gap-4">
        {pdf}
        <Results
          result={phase.result}
          onRetake={() => void begin()}
          onBack={() => navigate(`/learn/${slug}`)}
        />
      </div>
    );

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-4">
      {pdf}
      <Attempt
        key={phase.attempt.attempt_id}
        attempt={phase.attempt}
        artifactId={artifactId}
        onDone={(result) => {
          setPhase({ kind: "results", result });
          void qc.invalidateQueries({ queryKey: ["student", "quiz-attempts", artifactId] });
          void qc.invalidateQueries({ queryKey: ["student", "workspace", slug] });
          void qc.invalidateQueries({ queryKey: ["student", "catalog"] });
          void qc.invalidateQueries({ queryKey: ["student", "artifact", artifactId] });
        }}
      />
    </div>
  );
}

function Attempt({
  attempt,
  artifactId,
  onDone,
}: {
  attempt: QuizAttemptStart;
  artifactId: string;
  onDone: (r: QuizResult) => void;
}): JSX.Element {
  const questions = attempt.questions;
  const total = questions.length;
  const [results, setResults] = useState<Record<number, QuizCheckResult>>(() => {
    const init: Record<number, QuizCheckResult> = {};
    for (const q of questions) if (q.result) init[q.index] = q.result;
    return init;
  });
  const [current, setCurrent] = useState(() => {
    const firstOpen = questions.findIndex((q) => !q.result);
    return firstOpen === -1 ? Math.max(0, total - 1) : firstOpen;
  });
  const [drafts, setDrafts] = useState<Record<number, number | string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const focusPending = useRef(false);
  const feedbackRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (focusPending.current && feedbackRef.current) {
      focusPending.current = false;
      feedbackRef.current.focus();
    }
  }, [results]);

  const q = questions[current]!;
  const res = results[q.index];
  const draft = drafts[q.index];
  const checkedCount = Object.keys(results).length;
  const isLast = current === total - 1;
  const hasDraft = typeof draft === "string" ? draft.trim() !== "" : draft != null;

  async function check() {
    if (!hasDraft || res || busy) return;
    setBusy(true);
    setError(null);
    try {
      const r = await workspaceApi.checkQuizAnswer(attempt.attempt_id, q.index, draft!);
      focusPending.current = true;
      setResults((m) => ({ ...m, [q.index]: r }));
    } catch {
      // Resync: the server may already have recorded this check (409, lost response).
      try {
        const s = await workspaceApi.startQuiz(artifactId);
        if (s.status === "preparing" || s.attempt_id !== attempt.attempt_id) throw new Error();
        const merged: Record<number, QuizCheckResult> = {};
        for (const sq of s.questions) if (sq.result) merged[sq.index] = sq.result;
        if (!merged[q.index]) throw new Error();
        focusPending.current = true;
        setResults((m) => ({ ...m, ...merged }));
      } catch {
        setError("Couldn’t check that answer — please try again.");
      }
    } finally {
      setBusy(false);
    }
  }

  async function finish() {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      onDone(await workspaceApi.completeQuiz(attempt.attempt_id));
    } catch {
      setError("Couldn’t finish the quiz — please try again.");
      setBusy(false);
    }
  }

  return (
    <>
      <div className="flex items-center justify-between">
        <span className="font-label-md text-label-md text-on-surface-variant">
          Question {current + 1} of {total}
        </span>
        <span className="font-label-sm text-label-sm text-on-surface-variant">
          {checkedCount}/{total} checked
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
                : results[i] != null
                  ? "bg-secondary"
                  : "bg-surface-container-highest",
            )}
          />
        ))}
      </div>

      <Card className="p-5">
        <p className="font-headline-md text-headline-md">
          <MathText text={q.question} />
        </p>
        {q.type === "mcq" ? (
          <McqOptions
            q={q}
            selected={typeof draft === "number" ? draft : undefined}
            res={res}
            onSelect={(oi) => setDrafts((d) => ({ ...d, [q.index]: oi }))}
          />
        ) : (
          <input
            type="text"
            data-testid="quiz-fill-input"
            aria-label="Your answer"
            maxLength={500}
            autoComplete="off"
            disabled={Boolean(res) || busy}
            value={res ? String(res.response) : typeof draft === "string" ? draft : ""}
            onChange={(e) => setDrafts((d) => ({ ...d, [q.index]: e.target.value }))}
            onKeyDown={(e) => {
              if (e.key === "Enter") void check();
            }}
            className={cn(
              "mt-4 w-full rounded-lg border bg-surface px-3 py-2 font-body-md text-body-md",
              "focus-visible:outline-none focus-visible:shadow-focus",
              res
                ? res.correct
                  ? "border-secondary"
                  : "border-error"
                : "border-outline-variant focus:border-tertiary",
            )}
          />
        )}

        <div aria-live="polite">
          {res && (
            <div
              data-testid="quiz-feedback"
              ref={feedbackRef}
              tabIndex={-1}
              className="mt-4 rounded-lg bg-surface-container p-3 focus:outline-none"
            >
              <p
                className={cn(
                  "flex items-center gap-1 font-label-lg text-label-lg",
                  res.correct ? "text-secondary" : "text-error",
                )}
              >
                <Icon name={res.correct ? "check_circle" : "cancel"} filled />
                {res.correct ? "Correct" : "Incorrect"}
              </p>
              <p className="mt-1 text-body-md">
                Correct answer: <MathText text={res.correct_answer} />
              </p>
              {res.explanation && (
                <p className="mt-1 text-body-sm text-on-surface-variant">
                  <MathText text={res.explanation} />
                </p>
              )}
            </div>
          )}
        </div>
      </Card>

      {error && (
        <p role="alert" className="text-body-md text-error">
          {error}
        </p>
      )}

      <div className="flex items-center justify-between">
        <Button
          variant="secondary"
          size="sm"
          iconLeft="chevron_left"
          data-testid="btn-qz2"
          disabled={current === 0 || busy}
          onClick={() => setCurrent((c) => Math.max(0, c - 1))}
        >
          Previous
        </Button>
        {!res ? (
          <Button
            data-testid="btn-qz8"
            loading={busy}
            disabled={!hasDraft}
            onClick={() => void check()}
          >
            Check
          </Button>
        ) : isLast ? (
          <Button data-testid="btn-qz4" loading={busy} onClick={() => void finish()}>
            Finish
          </Button>
        ) : (
          <Button
            size="sm"
            iconRight="chevron_right"
            data-testid="btn-qz3"
            disabled={busy}
            onClick={() => setCurrent((c) => Math.min(total - 1, c + 1))}
          >
            Next
          </Button>
        )}
      </div>
    </>
  );
}

function McqOptions({
  q,
  selected,
  res,
  onSelect,
}: {
  q: QuizAttemptQuestion;
  selected: number | undefined;
  res: QuizCheckResult | undefined;
  onSelect: (i: number) => void;
}): JSX.Element {
  const chosen = res ? (res.response as number) : selected;
  return (
    <div className="mt-4 flex flex-col gap-2">
      {(q.options ?? []).map((opt, oi) => {
        const isChosen = chosen === oi;
        const isRight = res != null && res.correct_index === oi;
        const isWrong = res != null && isChosen && !res.correct;
        return (
          <button
            key={oi}
            type="button"
            data-testid={`btn-qz1-${oi}`}
            aria-pressed={isChosen}
            disabled={Boolean(res)}
            onClick={() => onSelect(oi)}
            className={cn(
              "flex items-center gap-3 rounded-lg border px-3 py-2 text-left font-body-md text-body-md transition-colors",
              "focus-visible:outline-none focus-visible:shadow-focus",
              isRight
                ? "border-secondary bg-secondary-container/30 text-on-surface"
                : isWrong
                  ? "border-error text-on-surface"
                  : isChosen
                    ? "border-tertiary bg-tertiary-container/30 text-on-surface"
                    : "border-outline-variant hover:border-tertiary",
            )}
          >
            <span
              className={cn(
                "flex h-6 w-6 shrink-0 items-center justify-center rounded-full font-label-sm text-label-sm",
                isChosen ? "bg-tertiary text-on-tertiary" : "bg-surface-container-high",
              )}
            >
              {LETTERS[oi]}
            </span>
            <MathText text={opt} />
          </button>
        );
      })}
    </div>
  );
}

function Results({
  result,
  onRetake,
  onBack,
}: {
  result: QuizResult;
  onRetake: () => void;
  onBack: () => void;
}): JSX.Element {
  return (
    <>
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
          <Button
            variant="secondary"
            size="sm"
            iconLeft="replay"
            data-testid="btn-qz5"
            onClick={onRetake}
          >
            Retake
          </Button>
          <Button size="sm" iconLeft="arrow_back" data-testid="btn-qz6" onClick={onBack}>
            Back to module
          </Button>
        </div>
      </Card>

      <div className="flex flex-col gap-3">
        {result.review.map((row) => {
          const yours =
            row.type === "mcq" && typeof row.response === "number" ? (
              <>
                {LETTERS[row.response]}. <MathText text={row.options?.[row.response] ?? ""} />
              </>
            ) : (
              String(row.response)
            );
          return (
            <Card key={row.index} className="p-4" data-testid="quiz-result-row">
              <div className="flex items-start gap-2">
                <Icon
                  name={row.correct ? "check_circle" : "cancel"}
                  filled
                  className={row.correct ? "text-secondary" : "text-error"}
                />
                <div className="flex-1">
                  <p className="font-label-lg text-label-lg">
                    <MathText text={row.question} />
                  </p>
                  <p className="mt-1 text-body-md text-on-surface-variant">Your answer: {yours}</p>
                  {!row.correct && (
                    <p className="text-body-md text-secondary">
                      Correct answer:{" "}
                      {row.correct_index != null && <>{LETTERS[row.correct_index]}. </>}
                      <MathText text={row.correct_answer} />
                    </p>
                  )}
                  {row.explanation && (
                    <p className="mt-1 text-body-sm text-on-surface-variant">
                      <MathText text={row.explanation} />
                    </p>
                  )}
                </div>
              </div>
            </Card>
          );
        })}
      </div>
    </>
  );
}
