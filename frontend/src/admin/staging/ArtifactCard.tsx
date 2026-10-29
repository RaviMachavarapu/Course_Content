import { useState } from "react";
import { Link } from "react-router-dom";
import { Button, Card, CardBody, Chip, Icon } from "@/components";
import { ARTIFACT_LABELS, type ArtifactType } from "../api";
import { STATUS_LABELS, toChipStatus } from "../statusMap";
import type { StagingArtifact } from "./api";
import { OutlineReview } from "./OutlineReview";
import { RedoModal } from "./RedoModal";
import type { OptionValues } from "../generationOptions";

const ICON: Record<ArtifactType, string> = {
  slide_deck: "slideshow",
  flashcards: "style",
  quiz: "quiz",
  report: "description",
  infographic: "account_tree",
  audio_overview: "graphic_eq",
};

const DOWNLOAD: Partial<Record<string, { label: string; testid: string }>> = {
  audio_mp3: { label: ".mp3", testid: "btn-sr9" },
  audio_m4a: { label: ".m4a", testid: "btn-sr9" },
  pptx: { label: ".pptx", testid: "btn-sr10" },
  infographic_png: { label: ".png", testid: "btn-sr11" },
  report_pdf: { label: ".pdf", testid: "btn-sr12" },
  deck_pdf: { label: ".pdf", testid: "btn-sr12" },
  flashcards_pdf: { label: "flashcards .pdf", testid: "btn-sr16" },
  quiz_pdf: { label: "quiz .pdf", testid: "btn-sr17" },
  // the students' copy: questions and options, no answer key
  quiz_questions_pdf: { label: "questions .pdf", testid: "btn-sr20" },
  infographic_pdf: { label: "infographic .pdf", testid: "btn-sr18" },
  slides_handout_pdf: { label: "handout .pdf", testid: "btn-sr19" },
};

const n = (v: unknown): string => (typeof v === "number" ? String(v) : "—");
const s = (v: unknown, fallback: string): string => (typeof v === "string" ? v : fallback);

function previewText(type: ArtifactType, p: Record<string, unknown>): string {
  switch (type) {
    case "slide_deck":
      return `${n(p.slide_count)} slides`;
    case "flashcards":
      return `${n(p.card_count)} cards`;
    case "quiz":
      return `${n(p.question_count)} questions`;
    case "report":
      return `${n(p.read_minutes)} min read · ${n(p.section_count)} sections`;
    case "infographic":
      return p.image
        ? "NotebookLM image"
        : `${s(p.diagram_kind, "diagram")} · ${n(p.line_count)} lines`;
    case "audio_overview": {
      const secs = typeof p.duration_seconds === "number" ? p.duration_seconds : 0;
      return `${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, "0")}`;
    }
  }
}

interface Props {
  artifact: StagingArtifact;
  busy: boolean;
  onRedo: (note: string | null, options: OptionValues, customPrompt: string) => void;
  onRetry: () => void;
  onOutline: (feedback: string | null) => void;
}

export function ArtifactCard({ artifact, busy, onRedo, onRetry, onOutline }: Props): JSX.Element {
  const [modalOpen, setModalOpen] = useState(false);
  const label = ARTIFACT_LABELS[artifact.type];
  const isGenerating = ["queued", "processing", "running"].includes(artifact.status);
  const isError = artifact.status === "error";
  const cv = artifact.current_version;

  return (
    <Card variant="elevated">
      <CardBody className="flex flex-col gap-3 p-4">
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-2">
            <Icon name={ICON[artifact.type]} className="text-primary" />
            <h3 className="font-label-md text-label-md font-semibold">{label}</h3>
          </div>
          {isGenerating ? (
            <span className="inline-flex items-center gap-1 font-label-sm text-label-sm text-tertiary">
              <Icon name="progress_activity" className="animate-spin text-[16px]" />
              Generating…
            </span>
          ) : (
            <Chip status={toChipStatus(artifact.status)}>
              {STATUS_LABELS[artifact.status] ?? undefined}
            </Chip>
          )}
        </div>

        {isError ? (
          <div className="rounded-lg bg-error-container/40 px-3 py-2 text-label-sm text-on-error-container">
            {artifact.last_error ?? "Generation failed."}
          </div>
        ) : artifact.status === "outline_review" && artifact.outline ? (
          <OutlineReview
            outline={artifact.outline}
            busy={busy}
            onFeedback={(text) => onOutline(text)}
            onProceed={() => onOutline(null)}
          />
        ) : (
          <p className="text-body-md text-on-surface-variant">
            {cv ? previewText(artifact.type, cv.preview) : "Not generated yet."}
            {cv && cv.revision > 1 && (
              <span className="ml-2 text-label-sm text-outline">rev {cv.revision}</span>
            )}
          </p>
        )}

        <div className="mt-auto flex flex-wrap gap-2 pt-2">
          {isError ? (
            <Button
              size="sm"
              variant="secondary"
              iconLeft="refresh"
              onClick={onRetry}
              disabled={busy}
              data-testid="btn-sr6"
            >
              Retry
            </Button>
          ) : (
            <Button
              size="sm"
              variant="secondary"
              iconLeft="restart_alt"
              disabled={isGenerating || busy}
              onClick={() => setModalOpen(true)}
              data-testid="btn-sr4"
            >
              Redo {label}
            </Button>
          )}
          <Link
            to={`/admin/artifacts/${artifact.id}`}
            data-testid="btn-sr5"
            className="inline-flex items-center gap-1 rounded-lg border border-outline-variant px-3 py-1.5 font-label-sm text-label-sm text-on-surface-variant hover:bg-surface-container-low"
          >
            <Icon name="visibility" className="text-[16px]" />
            Inspect
          </Link>
          {cv?.media.map((m) => {
            const d = DOWNLOAD[m.kind];
            if (!d) return null;
            return (
              <a
                key={m.kind}
                href={m.url}
                data-testid={d.testid}
                className="inline-flex items-center gap-1 rounded-lg border border-outline-variant px-3 py-1.5 font-label-sm text-label-sm text-on-surface hover:bg-surface-container-low"
              >
                <Icon name="download" className="text-[16px]" />
                {d.label}
              </a>
            );
          })}
        </div>
      </CardBody>

      <RedoModal
        open={modalOpen}
        type={artifact.type}
        typeLabel={label}
        pending={busy}
        initialOptions={artifact.generation_options}
        initialPrompt={artifact.custom_prompt ?? ""}
        onCancel={() => setModalOpen(false)}
        onStart={(note, options, customPrompt) => {
          setModalOpen(false);
          onRedo(note, options, customPrompt);
        }}
      />
    </Card>
  );
}
