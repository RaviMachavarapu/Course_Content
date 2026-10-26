import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MathText } from "./MathText";
import { renderMathInHtml } from "./renderMathInHtml";

describe("MathText", () => {
  it("renders inline formula", () => {
    const { container } = render(<MathText text="Rate of $S_N2$ here" />);
    expect(container.querySelector(".katex")).not.toBeNull();
    expect(container.textContent).not.toContain("$");
  });
  it("renders the real NotebookLM samples", () => {
    for (const s of ["$S_N1$", "$\\beta$", "$-NO_2$", "$-\\text{NO}_2$", "$C-X$", "$KOH$", "$50:50$"]) {
      const { container, unmount } = render(<MathText text={s} />);
      expect(container.querySelector(".katex"), s).not.toBeNull();
      unmount();
    }
  });
  it("renders display formula", () => {
    const { container } = render(<MathText text="$$\frac{1}{2}mv^2$$" />);
    expect(container.querySelector(".katex-display")).not.toBeNull();
  });
  it("dollar amounts stay text", () => {
    const { container } = render(<MathText text="costs $5 and $10" />);
    expect(container.querySelector(".katex")).toBeNull();
    expect(container.textContent).toBe("costs $5 and $10");
  });
  it("escaped dollar stays literal", () => {
    const { container } = render(<MathText text={"pay \\$5 or \\$x\\$"} />);
    expect(container.querySelector(".katex")).toBeNull();
    expect(container.textContent).toBe("pay $5 or $x$");
  });
  it("unrenderable formula shows original text", () => {
    const { container } = render(<MathText text={"a $\\frac{1}{$ b"} />);
    expect(container.textContent).toBe("a $\\frac{1}{$ b");
    expect(container.querySelector(".katex")).toBeNull();
  });
  it("html in formula is not injected", () => {
    const { container } = render(<MathText text="$<img src=x onerror=alert(1)>$" />);
    expect(container.querySelector("img")).toBeNull();
  });
  it("mhchem works", () => {
    const { container } = render(<MathText text="$\ce{H2O}$" />);
    expect(container.querySelector(".katex")).not.toBeNull();
  });
});

describe("renderMathInHtml", () => {
  it("draws math elements and leaves code alone", () => {
    const out = renderMathInHtml(
      '<p>x <span class="math-inline">S_N2</span> <code>$a_1$</code></p><div class="math-display">\\alpha &lt; 2</div>',
    );
    const doc = new DOMParser().parseFromString(out, "text/html");
    expect(doc.querySelectorAll(".math-inline .katex").length).toBe(1);
    expect(doc.querySelectorAll(".math-display .katex").length).toBe(1);
    expect(doc.querySelector("code")?.textContent).toBe("$a_1$");
  });
  it("keeps original text when KaTeX cannot render", () => {
    const out = renderMathInHtml('<span class="math-inline">\\frac{1}{</span>');
    expect(out).toBe('<span class="math-inline">\\frac{1}{</span>');
  });
  it("does not inject html from formula text", () => {
    const out = renderMathInHtml('<span class="math-inline">&lt;img src=x onerror=alert(1)&gt;</span>');
    expect(new DOMParser().parseFromString(out, "text/html").querySelector("img")).toBeNull();
  });
});
