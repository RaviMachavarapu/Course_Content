import { useEffect, useRef, useState } from "react";
import { Button, ErrorState, Icon, Skeleton } from "@/components";
import { PdfDownloadLink } from "@/components/PdfDownloadLink";
import { MathText } from "@/components/math/MathText";
import { useArtifactProgress, useStudentArtifact } from "../useWorkspace";

const MIN_ZOOM = 0.5;
const MAX_ZOOM = 3;
const ZOOM_STEP = 1.25;

interface InfographicContent {
  caption?: string;
}

export function InfographicViewer({
  artifactId,
  slug,
  moduleTitle,
}: {
  artifactId: string;
  slug: string;
  moduleTitle?: string;
}): JSX.Element {
  const { data, isPending, isError, refetch } = useStudentArtifact(artifactId);
  const progress = useArtifactProgress(artifactId, slug);
  const frameRef = useRef<HTMLDivElement>(null);
  const [zoom, setZoom] = useState(1);

  // opening the infographic counts as viewed
  useEffect(() => {
    if (data && !data.completed) progress.mutate({});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data?.id]);

  if (isPending) return <Skeleton className="h-[32rem]" />;
  if (isError || !data)
    return <ErrorState title="Infographic isn’t ready" onRetry={() => void refetch()} />;

  const content = (data.content_json ?? {}) as InfographicContent;
  const svgUrl = data.media.find((m) => m.kind === "infographic_svg")?.url;
  const pngUrl = data.media.find((m) => m.kind === "infographic_png")?.url;
  // NotebookLM supplies its own PNG; fixture content is our rendered SVG.
  const imageUrl = svgUrl ?? pngUrl;

  const toggleFullscreen = () => {
    const el = frameRef.current;
    if (!el) return;
    if (document.fullscreenElement) void document.exitFullscreen();
    else void el.requestFullscreen?.();
  };

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-4">
      {moduleTitle && <p className="text-label-sm text-on-surface-variant">{moduleTitle}</p>}

      <div className="flex items-center justify-end gap-1">
        <Button
          variant="ghost"
          size="sm"
          data-testid="btn-if2"
          aria-label="Zoom out"
          disabled={zoom <= MIN_ZOOM}
          onClick={() => setZoom((z) => Math.max(MIN_ZOOM, z / ZOOM_STEP))}
        >
          <Icon name="zoom_out" />
        </Button>
        <Button
          variant="ghost"
          size="sm"
          data-testid="btn-if1"
          aria-label="Zoom in"
          disabled={zoom >= MAX_ZOOM}
          onClick={() => setZoom((z) => Math.min(MAX_ZOOM, z * ZOOM_STEP))}
        >
          <Icon name="zoom_in" />
        </Button>
        <Button
          variant="ghost"
          size="sm"
          data-testid="btn-if3"
          aria-label="Fullscreen"
          onClick={toggleFullscreen}
        >
          <Icon name="fullscreen" />
        </Button>
      </div>

      <div
        ref={frameRef}
        data-testid="infographic-viewport"
        className="max-h-[32rem] overflow-auto rounded-xl border border-outline-variant bg-surface-container-lowest p-6"
      >
        {imageUrl && (
          <img
            src={imageUrl}
            alt={content.caption || "Infographic"}
            data-testid="infographic-image"
            style={{ width: `${zoom * 100}%`, transition: "width 150ms" }}
            className="mx-auto max-w-none"
          />
        )}
      </div>

      {content.caption && (
        <p className="text-center text-body-md text-on-surface-variant">
          <MathText text={content.caption} />
        </p>
      )}

      <div className="flex flex-wrap items-center justify-center gap-3">
        {pngUrl && (
          <a
            href={pngUrl}
            download
            data-testid="btn-if4"
            className="inline-flex items-center gap-1.5 rounded-lg border border-outline-variant px-3 py-1.5 font-label-md text-label-md text-on-surface-variant hover:border-tertiary focus-visible:outline-none focus-visible:shadow-focus"
          >
            <Icon name="download" className="text-[16px]" />
            Download .png
          </a>
        )}
        <PdfDownloadLink media={data.media} kind="infographic_pdf" testid="btn-if6" />
        <Button
          data-testid="btn-if5"
          loading={progress.isPending}
          disabled={data.completed}
          onClick={() => progress.mutate({ completed: true })}
        >
          {data.completed ? "Reviewed" : "Mark reviewed"}
        </Button>
      </div>
    </div>
  );
}
