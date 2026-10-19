import type { ArtifactType } from "../api";
import type { InspectVersion } from "../staging/api";

/** Read-only render of a version's content_json, one branch per type.
 * Deliberately plain — the student-facing renderers land in Phase 4. */
export function ContentView({
  type,
  version,
}: {
  type: ArtifactType;
  version: InspectVersion;
}): JSX.Element {
  const c: Record<string, unknown> = version.content_json ?? {};
  const str = (v: unknown): string => (typeof v === "string" ? v : "");

  if (type === "report") {
    return (
      <div
        className="prose max-w-none text-body-md [&_h1]:font-display [&_h1]:text-primary [&_h2]:font-display [&_h2]:text-primary"
        dangerouslySetInnerHTML={{ __html: version.content_html ?? "" }}
      />
    );
  }

  if (type === "slide_deck") {
    const slides = (c.slides ?? []) as { title: string; bullets: string[]; notes?: string }[];
    return (
      <ol className="flex flex-col gap-4">
        {slides.map((s, i) => (
          <li key={i} className="rounded-lg border border-outline-variant p-4">
            <p className="font-label-sm text-label-sm text-outline">Slide {i + 1}</p>
            <p className="font-headline-md text-headline-md">{s.title}</p>
            <ul className="mt-2 list-disc pl-6 text-body-md">
              {s.bullets.map((b, j) => (
                <li key={j}>{b}</li>
              ))}
            </ul>
            {s.notes && (
              <p className="mt-2 text-label-sm text-on-surface-variant">Notes: {s.notes}</p>
            )}
          </li>
        ))}
      </ol>
    );
  }

  if (type === "flashcards") {
    const cards = (c.cards ?? []) as { front: string; back: string; category?: string }[];
    return (
      <div className="grid gap-3 sm:grid-cols-2">
        {cards.map((card, i) => (
          <div key={i} className="rounded-lg border border-outline-variant p-3">
            {card.category && (
              <p className="font-label-sm text-label-sm text-outline">{card.category}</p>
            )}
            <p className="font-label-md text-label-md font-semibold">{card.front}</p>
            <p className="mt-1 text-body-md text-on-surface-variant">{card.back}</p>
          </div>
        ))}
      </div>
    );
  }

  if (type === "quiz") {
    const qs = (c.questions ?? []) as {
      question: string;
      options: string[];
      correct_index: number;
      explanation: string;
    }[];
    return (
      <ol className="flex flex-col gap-4">
        {qs.map((q, i) => (
          <li key={i} className="rounded-lg border border-outline-variant p-4">
            <p className="font-label-md text-label-md font-semibold">
              {i + 1}. {q.question}
            </p>
            <ul className="mt-2 flex flex-col gap-1">
              {q.options.map((opt, j) => (
                <li
                  key={j}
                  className={
                    j === q.correct_index
                      ? "rounded bg-secondary-container px-2 py-1 text-on-secondary-container"
                      : "px-2 py-1"
                  }
                >
                  {opt}
                  {j === q.correct_index && " ✓"}
                </li>
              ))}
            </ul>
            <p className="mt-2 text-label-sm text-on-surface-variant">{q.explanation}</p>
          </li>
        ))}
      </ol>
    );
  }

  if (type === "infographic") {
    return (
      <div className="flex flex-col gap-2">
        <p className="text-body-md text-on-surface-variant">{str(c.caption)}</p>
        <pre className="overflow-x-auto rounded-lg bg-surface-container p-4 text-label-sm">
          {str(c.diagram_source)}
        </pre>
      </div>
    );
  }

  // audio_overview
  const transcript = (c.transcript ?? []) as { t: number; text: string }[];
  const mp3 = version.media.find((m) => m.kind === "audio_mp3");
  return (
    <div className="flex flex-col gap-3">
      {mp3 && <audio controls src={mp3.url} className="w-full" />}
      <ol className="flex flex-col gap-2">
        {transcript.map((cue, i) => (
          <li key={i} className="text-body-md">
            <span className="mr-2 font-label-sm text-label-sm tabular-nums text-outline">
              {Math.floor(cue.t / 60)}:{String(Math.floor(cue.t % 60)).padStart(2, "0")}
            </span>
            {cue.text}
          </li>
        ))}
      </ol>
    </div>
  );
}
