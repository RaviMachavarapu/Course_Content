import { renderLatex } from "./katex";

/** The only classes report HTML may carry: the backend's formula markers and
 * markdown's fenced-code language tag. Everything else is dropped, so
 * untrusted content can't borrow the app's Tailwind utilities (e.g.
 * `fixed inset-0 z-50`) to draw a full-screen overlay. */
const ALLOWED_CLASS = /^(math-inline|math-display|language-[A-Za-z0-9_+#.-]+)$/;

function restrictClasses(root: HTMLElement): void {
  root.querySelectorAll("[class]").forEach((el) => {
    const kept = Array.from(el.classList).filter((c) => ALLOWED_CLASS.test(c));
    if (kept.length) el.setAttribute("class", kept.join(" "));
    else el.removeAttribute("class");
  });
}

/**
 * Prepare already-sanitized report HTML for display: restrict `class` values
 * to the allowlist above, then draw every `.math-inline` / `.math-display`
 * element with KaTeX. The element's textContent (the unescaped LaTeX) is the
 * formula; if KaTeX cannot render it the element is left unchanged.
 */
export function renderMathInHtml(html: string): string {
  if (!html.includes("class")) return html;
  const doc = new DOMParser().parseFromString(html, "text/html");
  restrictClasses(doc.body);
  doc.body.querySelectorAll(".math-inline, .math-display").forEach((el) => {
    const rendered = renderLatex(el.textContent ?? "", el.classList.contains("math-display"));
    if (rendered !== null) el.innerHTML = rendered;
  });
  return doc.body.innerHTML;
}
