import katex from "katex";
import "katex/contrib/mhchem";
import { MATH_MACROS } from "./macros";

/**
 * Single place that configures KaTeX. Returns the rendered HTML, or null when
 * KaTeX cannot render the formula (callers then show the original text).
 */
export function renderLatex(latex: string, displayMode: boolean): string | null {
  try {
    const html = katex.renderToString(latex, {
      throwOnError: false,
      strict: "ignore",
      trust: false,
      output: "htmlAndMathml",
      displayMode,
      // Generated content is untrusted: cap \rule / sizing commands (in em)
      // so a formula can't draw a page-covering box, and bound macro expansion.
      maxSize: 10,
      maxExpand: 1000,
      // Fresh copy per call: KaTeX writes \gdef/\newcommand results into it.
      macros: { ...MATH_MACROS },
    });
    // throwOnError:false renders errors as a red span instead of throwing.
    if (html.includes('class="katex-error"')) return null;
    return html;
  } catch {
    return null;
  }
}
