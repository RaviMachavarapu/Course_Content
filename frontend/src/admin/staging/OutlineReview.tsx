import { useState } from "react";
import { Button } from "@/components";
import type { StagingOutline } from "./api";

interface Props {
  outline: StagingOutline;
  busy: boolean;
  onFeedback: (feedback: string) => void;
  onProceed: () => void;
}

/** "**Title**: description" (NotebookLM's outline line) → bold title + text. */
function OutlineLine({ line }: { line: string }): JSX.Element {
  const match = line.match(/^\*\*(.+?)\*\*:?\s*(.*)$/s);
  if (!match) return <>{line}</>;
  return (
    <>
      <strong className="text-on-surface">{match[1]}</strong>
      {match[2] ? `: ${match[2]}` : null}
    </>
  );
}

/**
 * NotebookLM's draft slide outline ("Review slide outline"), with its two
 * actions: send feedback to revise it, or proceed to build the deck.
 */
export function OutlineReview({ outline, busy, onFeedback, onProceed }: Props): JSX.Element {
  const [feedback, setFeedback] = useState("");
  return (
    <div className="flex flex-col gap-3" data-testid="outline-review">
      {outline.style && <p className="text-label-sm text-on-surface-variant">{outline.style}</p>}
      <ol className="flex max-h-64 list-decimal flex-col gap-1 overflow-y-auto pl-5 text-label-sm text-on-surface-variant">
        {outline.slides.map((line, i) => (
          <li key={i}>
            <OutlineLine line={line} />
          </li>
        ))}
      </ol>
      <label className="flex flex-col gap-1 font-label-sm text-label-sm text-on-surface-variant">
        Add feedback to refine the outline
        <textarea
          rows={2}
          maxLength={4000}
          value={feedback}
          onChange={(e) => setFeedback(e.target.value)}
          className="rounded-lg border border-outline-variant bg-surface-container-lowest px-3 py-2 text-body-md text-on-surface focus:shadow-focus focus:outline-none"
        />
      </label>
      <div className="flex flex-wrap gap-2">
        <Button
          size="sm"
          variant="secondary"
          disabled={busy || !feedback.trim()}
          onClick={() => onFeedback(feedback.trim())}
          data-testid="btn-sr14"
        >
          Send feedback
        </Button>
        <Button size="sm" disabled={busy} onClick={onProceed} data-testid="btn-sr15">
          Proceed
        </Button>
      </div>
    </div>
  );
}
