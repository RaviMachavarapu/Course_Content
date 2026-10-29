import { Fragment, useMemo } from "react";
import { renderLatex } from "./katex";
import { splitMath } from "./segments";

export interface MathTextProps {
  text: string;
  className?: string;
}

/** Plain text with `$…$` / `$$…$$` formulas drawn by KaTeX. */
export function MathText({ text, className }: MathTextProps) {
  const parts = useMemo(
    () =>
      splitMath(text).map((seg) => {
        if (seg.kind === "text") return { ...seg, html: null as string | null };
        return { ...seg, html: renderLatex(seg.latex, seg.display) };
      }),
    [text],
  );
  return (
    <span className={className}>
      {parts.map((p, i) => {
        if (p.kind === "text") return <Fragment key={i}>{p.text}</Fragment>;
        if (p.html === null) return <Fragment key={i}>{p.raw}</Fragment>;
        return (
          <span
            key={i}
            className={p.display ? "math-display" : "math-inline"}
            style={p.display ? { display: "block" } : undefined}
            dangerouslySetInnerHTML={{ __html: p.html }}
          />
        );
      })}
    </span>
  );
}
