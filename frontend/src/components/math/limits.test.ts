import { describe, expect, it } from "vitest";
import { renderLatex } from "./katex";
import { renderMathInHtml } from "./renderMathInHtml";

describe("KaTeX limits", () => {
  it("caps user-specified sizes so a formula can't cover the page", () => {
    const html = renderLatex("\\rule{5000em}{5000em}", false) ?? "";
    // the source survives in the MathML annotation; the drawn sizes are capped
    expect(html).not.toMatch(/(width|height)[:=]"?5000em/);
    expect(html).toContain("border-right-width:10em");
  });

  it("stops runaway macro expansion", () => {
    expect(renderLatex("\\def\\a{\\a\\a}\\a", false)).toBeNull();
  });
});

describe("renderMathInHtml class allowlist", () => {
  it("strips app classes (e.g. a full-screen overlay) from report html", () => {
    const out = renderMathInHtml(
      '<div class="fixed inset-0 z-50 bg-surface">Session expired <a href="https://evil">sign in</a></div>',
    );
    const doc = new DOMParser().parseFromString(out, "text/html");
    const div = doc.body.querySelector("div")!;
    expect(div.hasAttribute("class")).toBe(false);
    expect(div.textContent).toContain("Session expired");
  });

  it("keeps math and code-language classes, drops the rest from a mixed list", () => {
    const out = renderMathInHtml(
      '<span class="math-inline fixed">x</span><pre><code class="language-python z-50">a</code></pre>',
    );
    const doc = new DOMParser().parseFromString(out, "text/html");
    expect(doc.querySelector("span")!.className).toBe("math-inline");
    expect(doc.querySelector("code")!.className).toBe("language-python");
  });
});
