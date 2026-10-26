import { renderLatex } from "./katex";

/**
 * Draw every `.math-inline` / `.math-display` element of already-sanitized
 * report HTML with KaTeX. The element's textContent (the unescaped LaTeX) is
 * the formula; if KaTeX cannot render it the element is left unchanged.
 */
export function renderMathInHtml(html: string): string {
  if (!html.includes("math-")) return html;
  const doc = new DOMParser().parseFromString(html, "text/html");
  const els = doc.body.querySelectorAll(".math-inline, .math-display");
  if (els.length === 0) return html;
  els.forEach((el) => {
    const rendered = renderLatex(
      el.textContent ?? "",
      el.classList.contains("math-display"),
    );
    if (rendered !== null) el.innerHTML = rendered;
  });
  return doc.body.innerHTML;
}
