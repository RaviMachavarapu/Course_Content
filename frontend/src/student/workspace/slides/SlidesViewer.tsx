import { useEffect, useMemo, useRef, useState } from "react";
import { Button, Card, ErrorState, Icon, Skeleton } from "@/components";
import { PdfDownloadLink } from "@/components/PdfDownloadLink";
import { MathText } from "@/components/math/MathText";
import { useArtifactProgress, useStudentArtifact } from "../useWorkspace";

interface SlideNote {
  title?: string;
  notes?: string | null;
  tags?: string[];
}

export function SlidesViewer({
  artifactId,
  slug,
}: {
  artifactId: string;
  slug: string;
}): JSX.Element {
  const { data, isPending, isError, refetch } = useStudentArtifact(artifactId);
  const progress = useArtifactProgress(artifactId, slug);
  const frameRef = useRef<HTMLDivElement>(null);

  const pages = useMemo(
    () =>
      (data?.media ?? [])
        .filter((m) => m.kind === "slide_png")
        .sort((a, b) => (a.page_index ?? 0) - (b.page_index ?? 0)),
    [data?.media],
  );
  const slideNotes = (data?.content_json?.slides ?? []) as SlideNote[];
  const pptxUrl = data?.media.find((m) => m.kind === "pptx")?.url;
  const total = pages.length;

  const [index, setIndex] = useState(0);
  const started = useRef(false);
  useEffect(() => {
    if (data && !started.current) {
      started.current = true;
      const resume = data.slide_last_index ?? 0;
      setIndex(Math.min(Math.max(resume, 0), Math.max(total - 1, 0)));
    }
  }, [data, total]);

  // persist position + mark complete when the last slide is reached
  useEffect(() => {
    if (!data || total === 0) return;
    const body =
      index >= total - 1
        ? { completed: true, slide_last_index: index }
        : { slide_last_index: index };
    const t = setTimeout(() => progress.mutate(body), 400);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [index, total, data]);

  if (isPending) return <Skeleton className="h-[28rem]" />;
  if (isError || !data || total === 0)
    return (
      <ErrorState
        title="Slides aren’t ready"
        description="This deck has no rendered pages yet."
        onRetry={() => void refetch()}
      />
    );

  const current = pages[index];
  const note = slideNotes[index];
  const atStart = index === 0;
  const atEnd = index >= total - 1;

  const toggleFullscreen = () => {
    const el = frameRef.current;
    if (!el) return;
    if (document.fullscreenElement) void document.exitFullscreen();
    else void el.requestFullscreen?.();
  };

  return (
    <div className="flex flex-col gap-4 lg:flex-row">
      <div className="flex flex-1 flex-col gap-3">
        <div
          ref={frameRef}
          className="flex items-center justify-center overflow-hidden rounded-xl border border-outline-variant bg-surface-container-lowest"
        >
          {current && (
            <img
              src={current.url}
              alt={`Slide ${index + 1}${note?.title ? `: ${note.title}` : ""}`}
              data-testid="slide-image"
              className="max-h-[70vh] w-full object-contain"
            />
          )}
        </div>

        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <Button
              variant="secondary"
              size="sm"
              iconLeft="chevron_left"
              data-testid="btn-sd1"
              disabled={atStart}
              onClick={() => setIndex((i) => Math.max(0, i - 1))}
            >
              Prev
            </Button>
            <span className="font-label-md text-label-md tabular-nums text-on-surface-variant">
              Slide {index + 1} of {total}
            </span>
            <Button
              variant="secondary"
              size="sm"
              iconRight="chevron_right"
              data-testid="btn-sd2"
              disabled={atEnd}
              onClick={() => setIndex((i) => Math.min(total - 1, i + 1))}
            >
              Next
            </Button>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="sm"
              iconLeft="fullscreen"
              data-testid="btn-sd3"
              onClick={toggleFullscreen}
            >
              Fullscreen
            </Button>
            {pptxUrl && (
              <a
                href={pptxUrl}
                download
                data-testid="btn-sd4"
                className="inline-flex items-center gap-1 rounded-lg border border-outline-variant px-3 py-1.5 font-label-md text-label-md text-on-surface-variant hover:border-tertiary"
              >
                <Icon name="download" className="text-[16px]" />
                Download .pptx
              </a>
            )}
            <PdfDownloadLink
              media={data.media}
              kind="slides_handout_pdf"
              testid="btn-sd5"
              label="Handout PDF"
            />
          </div>
        </div>
      </div>

      <Card className="w-full self-start p-4 lg:w-80">
        <h3 className="font-label-md text-label-md uppercase tracking-wide text-on-surface-variant">
          Instructor Notes
        </h3>
        <p className="mt-2 whitespace-pre-line text-body-md text-on-surface">
          {note?.notes?.trim() ? <MathText text={note.notes} /> : "No notes for this slide."}
        </p>
        {note?.tags && note.tags.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1">
            {note.tags.map((tag) => (
              <span
                key={tag}
                className="rounded-full bg-tertiary-container/40 px-2 py-0.5 font-label-sm text-label-sm text-tertiary"
              >
                {tag}
              </span>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
