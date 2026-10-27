import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Button, ErrorState, Icon, Skeleton } from "@/components";
import { PdfDownloadLink } from "@/components/PdfDownloadLink";
import { MathText } from "@/components/math/MathText";
import { MathHtml } from "@/components/math/MathHtml";
import { useArtifactProgress, useStudentArtifact } from "../useWorkspace";

interface Section {
  heading: string;
  html: string;
}
interface ReportContent {
  title?: string;
  read_minutes?: number;
  key_takeaways?: string[];
  sections?: Section[];
}

export function ReportViewer({
  artifactId,
  slug,
}: {
  artifactId: string;
  slug: string;
}): JSX.Element {
  const { data, isPending, isError, refetch } = useStudentArtifact(artifactId);
  const progress = useArtifactProgress(artifactId, slug);
  const navigate = useNavigate();

  // opening the report counts as viewed
  useEffect(() => {
    if (data && !data.completed) progress.mutate({});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data?.id]);

  if (isPending) return <Skeleton className="h-[32rem]" />;
  if (isError || !data)
    return <ErrorState title="Report isn’t ready" onRetry={() => void refetch()} />;

  const content = (data.content_json ?? {}) as ReportContent;
  const sections = content.sections ?? [];

  return (
    <div className="relative mx-auto max-w-3xl pb-24">
      <div className="rounded-2xl bg-gradient-to-br from-tertiary-container/50 to-surface-container-low p-8">
        <div className="flex items-center gap-2 font-label-sm text-label-sm text-tertiary">
          <Icon name="schedule" className="text-[16px]" />
          {content.read_minutes ?? "—"} min read
        </div>
        <h1 className="mt-2 font-headline-lg text-headline-lg text-on-background">
          <MathText text={content.title ?? "Report"} />
        </h1>
      </div>

      {content.key_takeaways && content.key_takeaways.length > 0 && (
        <aside className="mt-6 rounded-xl border-l-4 border-tertiary bg-tertiary-container/20 p-4">
          <p className="font-label-md text-label-md uppercase tracking-wide text-tertiary">
            Key takeaways
          </p>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-body-md">
            {content.key_takeaways.map((t, i) => (
              <li key={i}>
                <MathText text={t} />
              </li>
            ))}
          </ul>
        </aside>
      )}

      <ol className="mt-8 space-y-8">
        {sections.map((s, i) => (
          <li key={i}>
            <h2 className="font-headline-md text-headline-md">
              <span className="text-tertiary">{i + 1}.</span> <MathText text={s.heading} />
            </h2>
            <SectionHtml html={s.html} />
          </li>
        ))}
      </ol>

      <div className="mt-10 flex flex-wrap items-center gap-3">
        <Button
          variant="secondary"
          iconLeft="arrow_back"
          data-testid="btn-rp1"
          onClick={() => navigate(`/learn/${slug}`)}
        >
          Previous
        </Button>
        <Button
          data-testid="btn-rp2"
          loading={progress.isPending}
          onClick={() =>
            progress.mutate(
              { completed: true, complete_module: true },
              { onSuccess: () => navigate(`/learn/${slug}`) },
            )
          }
        >
          Complete Module
        </Button>
      </div>

      <PdfDownloadLink
        media={data.media}
        kind="report_pdf"
        testid="btn-rp3"
        label="Download .pdf"
        className="fixed bottom-6 right-6 z-30 inline-flex items-center gap-2 rounded-full bg-tertiary px-5 py-3 font-label-md text-label-md text-on-tertiary shadow-level-2"
      />
    </div>
  );
}

function SectionHtml({ html }: { html: string }): JSX.Element {
  // backend renders + sanitises this HTML (nh3 allowlist, T020); math is drawn by KaTeX
  return (
    <MathHtml
      html={html}
      className="prose-report mt-2 space-y-3 text-body-md leading-relaxed text-on-surface [&_a]:text-tertiary [&_a]:underline [&_li]:ml-5 [&_li]:list-disc [&_strong]:font-semibold"
    />
  );
}
