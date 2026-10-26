import type { SourceFile } from "./api";

interface SourceSummaryProps {
  sourceUrl: string | null;
  files: SourceFile[];
  /** Staging only: list each PDF and note when it was split. */
  detailed?: boolean;
}

/** A module's source: its link and/or its uploaded PDFs. */
export function SourceSummary({ sourceUrl, files, detailed = false }: SourceSummaryProps) {
  return (
    <div className="min-w-0 text-label-sm text-on-surface-variant">
      {sourceUrl && <div className="truncate">{sourceUrl}</div>}
      {files.length > 0 && (
        <div title={files.map((f) => f.file_name).join(", ")}>
          {`📄 ${files.length} ${files.length === 1 ? "PDF" : "PDFs"}`}
        </div>
      )}
      {detailed && (
        <ul>
          {files.map((f) => (
            <li key={f.file_name} className="truncate">
              {f.part_count > 1 ? `${f.file_name} (split into ${f.part_count} parts)` : f.file_name}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
