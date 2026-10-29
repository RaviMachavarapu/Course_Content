import { Icon } from "./Icon";

const DEFAULT_CLASS =
  "inline-flex items-center gap-1.5 rounded-lg border border-outline-variant px-3 py-1.5 font-label-md text-label-md text-on-surface-variant hover:border-tertiary focus-visible:outline-none focus-visible:shadow-focus";

/** Download link for the PDF media of the given kind; renders nothing when that PDF
 * doesn't exist yet (PDFs are built shortly after generation). */
export function PdfDownloadLink({
  media,
  kind,
  testid,
  label = "Download PDF",
  className = DEFAULT_CLASS,
}: {
  media: { kind: string; url: string }[] | undefined;
  kind: string;
  testid: string;
  label?: string;
  className?: string;
}): JSX.Element | null {
  const url = media?.find((m) => m.kind === kind)?.url;
  if (!url) return null;
  return (
    <a href={url} download data-testid={testid} className={className}>
      <Icon name="download" className="text-[18px]" />
      {label}
    </a>
  );
}
