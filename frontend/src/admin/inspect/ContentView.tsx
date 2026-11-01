import { asArray } from "@/lib/asArray";
import type { ArtifactType } from "../api";
import type { InspectVersion } from "../staging/api";
import { MathText } from "@/components/math/MathText";
import { MathHtml } from "@/components/math/MathHtml";

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
    // content_json, like the student report: content_html escapes $…$ as plain text
    if (!Array.isArray(c.sections)) return <ReportHtml html={version.content_html ?? ""} />;
    const sections = c.sections as { heading: string; html: string }[];
    const takeaways = asArray<string>(c.key_takeaways);
    return (
      <div className="flex flex-col gap-4">
        <h1 className="font-headline-lg text-headline-lg text-primary">
          <MathText text={str(c.title) || "Report"} />
        </h1>
        {takeaways.length > 0 && (
          <div className="rounded-lg border border-outline-variant p-4">
            <p className="font-label-sm text-label-sm text-outline">Key takeaways</p>
            <ul className="mt-1 list-disc pl-5 text-body-md">
              {takeaways.map((t, i) => (
                <li key={i}>
                  <MathText text={t} />
                </li>
              ))}
            </ul>
          </div>
        )}
        {sections.map((s, i) => (
          <section key={i}>
            <h2 className="font-headline-md text-headline-md text-primary">
              <MathText text={s.heading} />
            </h2>
            <ReportHtml html={s.html} />
          </section>
        ))}
      </div>
    );
  }

  if (type === "slide_deck") {
    const slides = asArray<{ title: string; bullets?: string[]; notes?: string }>(c.slides);
    return (
      <ol className="flex flex-col gap-4">
        {slides.map((s, i) => (
          <li key={i} className="rounded-lg border border-outline-variant p-4">
            <p className="font-label-sm text-label-sm text-outline">Slide {i + 1}</p>
            <p className="font-headline-md text-headline-md">
              <MathText text={s.title} />
            </p>
            <ul className="mt-2 list-disc pl-6 text-body-md">
              {asArray<string>(s.bullets).map((b, j) => (
                <li key={j}>
                  <MathText text={b} />
                </li>
              ))}
            </ul>
            {s.notes && (
              <p className="mt-2 text-label-sm text-on-surface-variant">
                Notes: <MathText text={s.notes} />
              </p>
            )}
          </li>
        ))}
      </ol>
    );
  }

  if (type === "flashcards") {
    const cards = asArray<{ front: string; back: string; category?: string }>(c.cards);
    return (
      <div className="grid gap-3 sm:grid-cols-2">
        {cards.map((card, i) => (
          <div key={i} className="rounded-lg border border-outline-variant p-3">
            {card.category && (
              <p className="font-label-sm text-label-sm text-outline">
                <MathText text={card.category} />
              </p>
            )}
            <p className="font-label-md text-label-md font-semibold">
              <MathText text={card.front} />
            </p>
            <p className="mt-1 text-body-md text-on-surface-variant">
              <MathText text={card.back} />
            </p>
          </div>
        ))}
      </div>
    );
  }

  if (type === "quiz") {
    const qs = asArray<{
      question: string;
      options?: string[];
      correct_index: number;
      explanation: string;
    }>(c.questions);
    return (
      <ol className="flex flex-col gap-4">
        {qs.map((q, i) => (
          <li key={i} className="rounded-lg border border-outline-variant p-4">
            <p className="font-label-md text-label-md font-semibold">
              {i + 1}. <MathText text={q.question} />
            </p>
            <ul className="mt-2 flex flex-col gap-1">
              {asArray<string>(q.options).map((opt, j) => (
                <li
                  key={j}
                  className={
                    j === q.correct_index
                      ? "rounded bg-secondary-container px-2 py-1 text-on-secondary-container"
                      : "px-2 py-1"
                  }
                >
                  <MathText text={opt} />
                  {j === q.correct_index && " ✓"}
                </li>
              ))}
            </ul>
            <p className="mt-2 text-label-sm text-on-surface-variant">
              <MathText text={q.explanation} />
            </p>
          </li>
        ))}
      </ol>
    );
  }

  if (type === "infographic") {
    const image =
      version.media.find((m) => m.kind === "infographic_png") ??
      version.media.find((m) => m.kind === "infographic_svg");
    return (
      <div className="flex flex-col gap-2">
        <p className="text-body-md text-on-surface-variant">
          <MathText text={str(c.caption)} />
        </p>
        {image ? (
          <>
            <a href={image.url} target="_blank" rel="noreferrer">
              <img
                src={image.url}
                alt={str(c.caption) || "Infographic"}
                className="w-full rounded-lg border border-outline-variant"
              />
            </a>
            <details className="text-body-md">
              <summary className="cursor-pointer text-on-surface-variant">Text description</summary>
              <p className="mt-2 whitespace-pre-line">
                <MathText text={str(c.description)} />
              </p>
            </details>
          </>
        ) : c.diagram_source ? (
          <pre className="overflow-x-auto rounded-lg bg-surface-container p-4 text-label-sm">
            {str(c.diagram_source)}
          </pre>
        ) : (
          <p className="whitespace-pre-line text-body-md">
            <MathText text={str(c.description)} />
          </p>
        )}
      </div>
    );
  }

  // audio_overview
  const transcript = asArray<{ t: number; text: string }>(c.transcript);
  const mp3 = version.media.find((m) => m.kind === "audio_mp3" || m.kind === "audio_m4a");
  return (
    <div className="flex flex-col gap-3">
      {mp3 && <audio controls src={mp3.url} className="w-full" />}
      <ol className="flex flex-col gap-2">
        {transcript.map((cue, i) => (
          <li key={i} className="text-body-md">
            <span className="mr-2 font-label-sm text-label-sm tabular-nums text-outline">
              {Math.floor(cue.t / 60)}:{String(Math.floor(cue.t % 60)).padStart(2, "0")}
            </span>
            <MathText text={cue.text} />
          </li>
        ))}
      </ol>
    </div>
  );
}

function ReportHtml({ html }: { html: string }): JSX.Element {
  return (
    <MathHtml
      html={html}
      className="prose max-w-none text-body-md [&_h1]:font-display [&_h1]:text-primary [&_h2]:font-display [&_h2]:text-primary"
    />
  );
}
