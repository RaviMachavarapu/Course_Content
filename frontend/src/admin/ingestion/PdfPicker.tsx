import { type DragEvent, useRef, useState } from "react";
import { Button, Icon, ProgressBar } from "@/components";
import { cn } from "@/lib/cn";

export interface PickedFile {
  id: string;
  file: File;
  sent: number;
  total: number;
  state: "uploading" | "done" | "error";
  uploadId?: string;
  error?: string;
}

interface PdfPickerProps {
  files: PickedFile[];
  onAdd: (files: File[]) => void;
  onRemove: (id: string) => void;
  onRetry: (id: string) => void;
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`;
  return `${(n / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

const isPdfName = (name: string): boolean => name.toLowerCase().endsWith(".pdf");

export function PdfPicker({ files, onAdd, onRemove, onRetry }: PdfPickerProps): JSX.Element {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [refusals, setRefusals] = useState<string[]>([]);

  function accept(picked: File[]): void {
    const ok = picked.filter((f) => isPdfName(f.name));
    setRefusals(picked.filter((f) => !isPdfName(f.name)).map((f) => `${f.name} is not a PDF`));
    if (ok.length > 0) onAdd(ok);
  }

  function onDrop(e: DragEvent): void {
    e.preventDefault();
    setDragging(false);
    accept(Array.from(e.dataTransfer.files));
  }

  return (
    <div className="flex flex-col gap-2">
      <div
        data-testid="pdf-dropzone"
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={cn(
          "flex flex-col items-center gap-2 rounded-lg border border-dashed px-4 py-5 text-center",
          dragging ? "border-primary bg-primary/5" : "border-outline-variant",
        )}
      >
        <Icon name="upload_file" className="text-[24px] text-on-surface-variant" />
        <p className="text-body-md text-on-surface-variant">Drop PDFs here or</p>
        <Button
          type="button"
          size="sm"
          variant="secondary"
          onClick={() => inputRef.current?.click()}
        >
          Choose PDFs
        </Button>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept=".pdf,application/pdf"
          aria-label="PDF files"
          className="hidden"
          onChange={(e) => {
            accept(Array.from(e.target.files ?? []));
            e.target.value = "";
          }}
        />
      </div>

      {refusals.map((msg) => (
        <p key={msg} role="alert" className="font-label-sm text-label-sm text-error">
          {msg}
        </p>
      ))}

      {files.length > 0 && (
        <ul className="flex flex-col gap-2">
          {files.map((f) => (
            <li
              key={f.id}
              className="flex items-center gap-3 rounded-lg border border-outline-variant/60 px-3 py-2"
            >
              <Icon
                name={
                  f.state === "done"
                    ? "check_circle"
                    : f.state === "error"
                      ? "error"
                      : "picture_as_pdf"
                }
                className={cn(
                  "text-[20px]",
                  f.state === "done" && "text-secondary",
                  f.state === "error" && "text-error",
                  f.state === "uploading" && "text-on-surface-variant",
                )}
              />
              <div className="flex min-w-0 flex-1 flex-col gap-1">
                <div className="flex items-baseline gap-2">
                  <span className="truncate font-label-md text-label-md">{f.file.name}</span>
                  <span className="shrink-0 font-label-sm text-label-sm text-on-surface-variant">
                    {formatBytes(f.file.size)}
                  </span>
                </div>
                {f.state === "uploading" && (
                  <ProgressBar value={f.total > 0 ? (f.sent / f.total) * 100 : 0} />
                )}
                {f.state === "error" && (
                  <span className="font-label-sm text-label-sm text-error">
                    {f.error ?? "Upload failed"}
                  </span>
                )}
              </div>
              {f.state === "error" && (
                <Button type="button" size="sm" variant="secondary" onClick={() => onRetry(f.id)}>
                  Retry
                </Button>
              )}
              <button
                type="button"
                aria-label={`Remove ${f.file.name}`}
                onClick={() => onRemove(f.id)}
                className="rounded p-1 text-on-surface-variant hover:bg-surface-container-high"
              >
                <Icon name="close" className="text-[18px]" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
