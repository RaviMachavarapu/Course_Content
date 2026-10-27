import { useEffect, useMemo, useRef, useState } from "react";
import { Button, ErrorState, Skeleton } from "@/components";
import { PdfDownloadLink } from "@/components/PdfDownloadLink";
import { cn } from "@/lib/cn";
import { MathText } from "@/components/math/MathText";
import type { FlashcardRating } from "../api";
import { useArtifactProgress, useFlashcardRating, useStudentArtifact } from "../useWorkspace";

interface Card {
  front: string;
  back: string;
  category?: string | null;
  hint?: string | null;
}

const RATING_ORDER: Record<FlashcardRating | "none", number> = {
  hard: 0,
  none: 1,
  good: 2,
  easy: 3,
};
const RATINGS: { value: FlashcardRating; label: string; ws: string; cls: string }[] = [
  { value: "hard", label: "Hard", ws: "btn-fc4", cls: "bg-error text-on-error" },
  { value: "good", label: "Good", ws: "btn-fc5", cls: "bg-tertiary text-on-tertiary" },
  { value: "easy", label: "Easy", ws: "btn-fc6", cls: "bg-secondary text-on-secondary" },
];

export function FlashcardsViewer({
  artifactId,
  slug,
}: {
  artifactId: string;
  slug: string;
}): JSX.Element {
  const { data, isPending, isError, refetch } = useStudentArtifact(artifactId);
  const rate = useFlashcardRating(artifactId);
  const progress = useArtifactProgress(artifactId, slug);

  const cards = (data?.content_json?.cards ?? []) as Card[];
  const ratings = data?.flashcard_ratings ?? {};

  // Hard-first order, decided once when the deck loads (spec §3.11).
  const order = useMemo(() => {
    if (!data) return [];
    return cards
      .map((_, i) => i)
      .sort((a, b) => {
        const ra = RATING_ORDER[(ratings[String(a)] as FlashcardRating) ?? "none"];
        const rb = RATING_ORDER[(ratings[String(b)] as FlashcardRating) ?? "none"];
        return ra - rb || a - b;
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  const [pos, setPos] = useState(0);
  const [flipped, setFlipped] = useState(false);
  const seen = useRef<Set<number>>(new Set());

  const cardIndex = order[pos] ?? 0;
  const card = cards[cardIndex];
  const total = order.length;

  useEffect(() => {
    setFlipped(false);
    if (total > 0) {
      seen.current.add(cardIndex);
      if (seen.current.size >= total && data) progress.mutate({ completed: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pos, total]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent): void => {
      if (e.target instanceof HTMLElement && ["INPUT", "TEXTAREA"].includes(e.target.tagName))
        return;
      if (e.key === " ") {
        e.preventDefault();
        setFlipped((f) => !f);
      } else if (e.key === "ArrowRight") {
        setPos((p) => Math.min(total - 1, p + 1));
      } else if (e.key === "ArrowLeft") {
        setPos((p) => Math.max(0, p - 1));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [total]);

  if (isPending) return <Skeleton className="h-96" />;
  if (isError || !data || total === 0)
    return <ErrorState title="Flashcards aren’t ready" onRetry={() => void refetch()} />;

  const currentRating: FlashcardRating | undefined = ratings[String(cardIndex)];

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-4">
      <div className="flex justify-end">
        <PdfDownloadLink media={data.media} kind="flashcards_pdf" testid="btn-fc7" />
      </div>
      <button
        type="button"
        data-testid="btn-fc1"
        aria-label={flipped ? "Show front" : "Show answer"}
        onClick={() => setFlipped((f) => !f)}
        className="flex min-h-64 flex-col items-center justify-center gap-3 rounded-2xl border border-outline-variant bg-surface-container-lowest p-8 text-center shadow-level-1 focus-visible:outline-none focus-visible:shadow-focus"
      >
        {!flipped && card?.category && (
          <span className="rounded-full bg-tertiary-container/40 px-2 py-0.5 font-label-sm text-label-sm text-tertiary">
            <MathText text={card.category} />
          </span>
        )}
        <p className="text-headline-md font-headline-md" data-testid="fc-face">
          <MathText text={(flipped ? card?.back : card?.front) ?? ""} />
        </p>
        {!flipped && card?.hint && (
          <span className="text-label-sm text-on-surface-variant">
            Hint: <MathText text={card.hint} />
          </span>
        )}
        <span className="mt-2 text-label-sm text-on-surface-variant">
          {flipped ? "Click to flip back" : "Click or press Space to flip"}
        </span>
      </button>

      <div className="flex items-center justify-between">
        <Button
          variant="secondary"
          size="sm"
          iconLeft="chevron_left"
          data-testid="btn-fc2"
          disabled={pos === 0}
          onClick={() => setPos((p) => Math.max(0, p - 1))}
        >
          Prev
        </Button>
        <span className="font-label-md text-label-md tabular-nums text-on-surface-variant">
          {pos + 1} of {total}
        </span>
        <Button
          variant="secondary"
          size="sm"
          iconRight="chevron_right"
          data-testid="btn-fc3"
          disabled={pos >= total - 1}
          onClick={() => setPos((p) => Math.min(total - 1, p + 1))}
        >
          Next
        </Button>
      </div>

      <div className="flex justify-center gap-2">
        {RATINGS.map((r) => (
          <button
            key={r.value}
            type="button"
            data-testid={r.ws}
            aria-pressed={currentRating === r.value}
            onClick={() => rate.mutate({ cardIndex, value: r.value })}
            className={cn(
              "rounded-lg px-4 py-2 font-label-md text-label-md transition-opacity",
              "focus-visible:outline-none focus-visible:shadow-focus",
              currentRating === r.value
                ? r.cls
                : "border border-outline-variant text-on-surface-variant hover:border-tertiary",
            )}
          >
            {r.label}
          </button>
        ))}
      </div>
    </div>
  );
}
