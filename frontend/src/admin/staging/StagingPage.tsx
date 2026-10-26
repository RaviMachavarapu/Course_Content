import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Button, ErrorState, Icon, Skeleton } from "@/components";
import { useToast } from "@/lib/store";
import { ARTIFACT_TYPES } from "../api";
import { StatusChip } from "../AdminStatus";
import { SourceSummary } from "../SourceSummary";
import { ArtifactCard } from "./ArtifactCard";
import { PublishModal } from "./PublishModal";
import { usePublish } from "./publish";
import { useOutlineAction, useRedo, useRetry, useStaging } from "./useStaging";

export function StagingPage(): JSX.Element {
  const { moduleId = "" } = useParams();
  const { data, isPending, isError, refetch } = useStaging(moduleId);
  const redo = useRedo(moduleId);
  const retry = useRetry(moduleId);
  const outline = useOutlineAction(moduleId);
  const publish = usePublish(moduleId);
  const { toast } = useToast();
  const [publishScope, setPublishScope] = useState<"module" | "course" | null>(null);

  if (isError) {
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
                  busy={redo.isPending || retry.isPending || outline.isPending}
                  onRedo={(note, options, customPrompt) =>
                    redo.mutate({ artifactId: artifact.id, note, options, customPrompt })
                  }
                  onRetry={() => retry.mutate(artifact.id)}
                  onOutline={(feedback) => outline.mutate({ artifactId: artifact.id, feedback })}
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
            if (scope === "course")
              publish.course.mutate(data.module.course_id, { onSuccess: onDone });
            else publish.module.mutate(undefined, { onSuccess: onDone });
          }}
        />
      )}
    </div>
  );
}
