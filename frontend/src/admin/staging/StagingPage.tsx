import { useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Button, ErrorState, Icon, Skeleton } from "@/components";
import { errorMessage } from "@/lib/api";
import { useToast } from "@/lib/store";
import { ARTIFACT_TYPES } from "../api";
import { StatusChip } from "../AdminStatus";
import { SourceSummary } from "../SourceSummary";
import { ArtifactCard } from "./ArtifactCard";
import { FreshRetakesToggle } from "./FreshRetakesToggle";
import { PublishModal } from "./PublishModal";
import { usePublish } from "./publish";
import { useCancel, useOutlineAction, useRedo, useRetry, useStaging } from "./useStaging";

/**
 * Run one request at a time. `pending` disables the buttons, but only after a
 * re-render: both clicks of a fast double-click can arrive before it (a second
 * Retry then gets a 409 toast, a second publish runs twice). The ref is
 * checked synchronously; `start` calls `settled` when its request ends.
 */
function useOneAtATime(): (start: (settled: () => void) => void) => void {
  const running = useRef(false);
  return (start) => {
    if (running.current) return;
    running.current = true;
    start(() => {
      running.current = false;
    });
  };
}

export function StagingPage(): JSX.Element {
  const { moduleId = "" } = useParams();
  const { data, isPending, isError, refetch } = useStaging(moduleId);
  const redo = useRedo(moduleId);
  const retry = useRetry(moduleId);
  const cancel = useCancel(moduleId);
  const outline = useOutlineAction(moduleId);
  const publish = usePublish(moduleId);
  const { toast } = useToast();
  const [publishScope, setPublishScope] = useState<"module" | "course" | null>(null);
  const failed = (title: string, err: unknown) =>
    toast({ title, description: errorMessage(err), tone: "error" });
  // One card action, and one publish, at a time (see `useOneAtATime`).
  const once = useOneAtATime();
  const oncePublish = useOneAtATime();

  // a failed poll with data already shown keeps the page (and any open
  // dialog): only a failed first load replaces it
  if (isError && !data) {
    return (
      <div className="flex-1 p-4 md:p-margin-desktop">
        <ErrorState title="Could not load staging" onRetry={() => void refetch()} />
      </div>
    );
  }

  const byType = new Map((data?.artifacts ?? []).map((a) => [a.type, a]));
  const anyReady = (data?.artifacts ?? []).some((a) => a.status === "ready");

  return (
    <div className="flex flex-1 flex-col gap-6 p-4 md:p-margin-desktop">
      {isError && (
        <p
          role="status"
          className="rounded-lg bg-surface-container-high px-3 py-2 font-label-md text-label-md text-on-surface-variant"
        >
          Couldn’t refresh the status just now.{" "}
          <button
            type="button"
            className="underline underline-offset-2"
            onClick={() => void refetch()}
          >
            Try again
          </button>
        </p>
      )}
      <div className="flex flex-col gap-3">
        <Link
          to="/admin/ingestion"
          data-testid="btn-sr1"
          className="flex w-fit items-center gap-1 font-label-sm text-label-sm text-on-surface-variant hover:text-primary"
        >
          <Icon name="arrow_back" className="text-[16px]" />
          Back to Ingestion
        </Link>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="flex items-center gap-3">
              <h1 className="font-headline-lg text-headline-lg">
                {data?.module.title ?? <Skeleton className="h-7 w-48" />}
              </h1>
              {data && <StatusChip status={data.module.status} />}
            </div>
            {data && (
              <div className="mt-1" data-testid="staging-sources">
                <SourceSummary
                  sourceUrl={data.module.source_url}
                  files={data.module.source_files}
                  detailed
                />
              </div>
            )}
            {byType.has("quiz") && (
              <div className="mt-2">
                <FreshRetakesToggle moduleId={moduleId} />
              </div>
            )}
          </div>
          <div className="flex gap-2">
            <Button
              variant="secondary"
              disabled={!anyReady}
              data-testid="btn-sr3"
              onClick={() => setPublishScope("module")}
            >
              Publish Module
            </Button>
            <Button
              disabled={!anyReady}
              data-testid="btn-sr2"
              onClick={() => setPublishScope("course")}
            >
              Publish Complete Course
            </Button>
          </div>
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 md:grid-cols-3" data-testid="artifact-grid">
        {isPending
          ? ARTIFACT_TYPES.map((t) => <Skeleton key={t} className="h-40" />)
          : ARTIFACT_TYPES.map((t) => {
              const artifact = byType.get(t);
              if (!artifact) return null;
              return (
                <ArtifactCard
                  key={t}
                  artifact={artifact}
                  busy={redo.isPending || retry.isPending || outline.isPending || cancel.isPending}
                  onRedo={(note, options, customPrompt) =>
                    once((settled) =>
                      redo.mutate(
                        { artifactId: artifact.id, note, options, customPrompt },
                        {
                          onError: (err) => failed("Couldn’t start the redo", err),
                          onSettled: settled,
                        },
                      ),
                    )
                  }
                  onRetry={() =>
                    once((settled) =>
                      retry.mutate(artifact.id, {
                        onError: (err) => failed("Couldn’t retry", err),
                        onSettled: settled,
                      }),
                    )
                  }
                  onCancel={() =>
                    once((settled) =>
                      cancel.mutate(artifact.id, {
                        onError: (err) => failed("Couldn’t cancel", err),
                        onSettled: settled,
                      }),
                    )
                  }
                  onOutline={(feedback) =>
                    once((settled) =>
                      outline.mutate(
                        { artifactId: artifact.id, feedback },
                        {
                          onError: (err) => failed("Couldn’t send the outline action", err),
                          onSettled: settled,
                        },
                      ),
                    )
                  }
                />
              );
            })}
      </div>

      {data && (
        <PublishModal
          open={publishScope !== null}
          scope={publishScope ?? "module"}
          artifacts={data.artifacts}
          pending={publish.module.isPending || publish.course.isPending}
          onCancel={() => setPublishScope(null)}
          onConfirm={() => {
            const scope = publishScope;
            const onDone = (result: { published: unknown[]; skipped: unknown[] }) => {
              setPublishScope(null);
              toast({
                title: `Published ${result.published.length} artifact${result.published.length === 1 ? "" : "s"}`,
                description: result.skipped.length
                  ? `${result.skipped.length} skipped (not ready)`
                  : undefined,
                tone: "success",
              });
            };
            // the dialog stays open on failure so the admin can retry or cancel
            const onError = (err: unknown) => failed("Publish failed", err);
            oncePublish((onSettled) => {
              if (scope === "course")
                publish.course.mutate(data.module.course_id, {
                  onSuccess: onDone,
                  onError,
                  onSettled,
                });
              else publish.module.mutate(undefined, { onSuccess: onDone, onError, onSettled });
            });
          }}
        />
      )}
    </div>
  );
}
