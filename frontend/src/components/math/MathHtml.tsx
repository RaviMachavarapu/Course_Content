import { useMemo } from "react";
import { renderMathInHtml } from "./renderMathInHtml";

export interface MathHtmlProps {
  /** Report HTML the backend already rendered and sanitised (nh3 allowlist). */
  html: string;
  className?: string;
}

/** Sanitised report HTML with its `math-inline` / `math-display` elements drawn by KaTeX. */
export function MathHtml({ html, className }: MathHtmlProps): JSX.Element {
  // renderMathInHtml is not idempotent: always run it on the stored html.
  const rendered = useMemo(() => renderMathInHtml(html), [html]);
  return <div className={className} dangerouslySetInnerHTML={{ __html: rendered }} />;
}
