import { describe, expect, it } from "vitest";
import { renderLatex } from "./katex";

function html(latex: string, display = false): string {
  const out = renderLatex(latex, display);
  expect(out, latex).not.toBeNull();
  return out as string;
}
/** Visible text of the KaTeX HTML part (MathML annotation excluded). */
function visible(latex: string): string {
  const out = html(latex);
  const m = out.match(/<span class="katex-html"[^>]*>([\s\S]*)<\/span>$/);
  return (m?.[1] ?? out).replace(/<[^>]+>/g, "");
}
function mathml(latex: string): string {
  const out = html(latex);
  return out.match(/<math[\s\S]*<\/math>/)?.[0] ?? "";
}

/** Reading order of the MathML (the HTML part lists a fraction's denominator first). */
function reading(latex: string): string {
  return mathml(latex)
    .replace(/<annotation[\s\S]*?<\/annotation>/g, "")
    .replace(/<[^>]+>/g, "");
}

describe("physics macros", () => {
  it("dv is a fraction of upright d", () => {
    const h = html("\\dv{x}{t}");
    expect(h).toContain("mfrac");
    expect(reading("\\dv{x}{t}")).toBe("dxdt");
    expect(mathml("\\dv{x}{t}")).toContain("<mi mathvariant=\"normal\">d</mi>");
  });
  it("dv with order and single-argument forms", () => {
    expect(reading("\\dv[2]{x}{t}")).toBe("d2xdt2");
    expect(reading("\\dv{x}")).toBe("ddx");
  });
  it("pdv", () => {
    expect(mathml("\\pdv{f}{x}")).toContain("∂");
    expect(reading("\\pdv{f}{x}")).toBe("∂f∂x");
    expect(reading("\\pdv[2]{f}{x}")).toBe("∂2f∂x2");
    expect(reading("\\pdv{f}{x}{y}").replace(/\s/g, "")).toBe("∂2f∂x∂y");
  });
  it("abs and norm", () => {
    expect(visible("\\abs{x}")).toBe("∣x∣");
    expect(html("\\abs{\\frac{a}{b}}")).toContain("mfrac");
    expect(mathml("\\norm{v}")).toContain("∥");
  });
  it("vb, vu", () => {
    expect(html("\\vb{F}")).toContain("mathbf");
    expect(html("\\vu{x}")).toContain("mathbf");
    expect(mathml("\\vu{x}")).toContain("^");
  });
  it("expval", () => {
    expect(visible("\\expval{A}")).toContain("⟨");
    expect(visible("\\expval{A}{\\psi}")).toBe("⟨ψ∣A∣ψ⟩");
  });
  it("vector operators", () => {
    expect(mathml("\\grad f")).toContain("∇");
    expect(mathml("\\curl \\vb{F}")).toContain("×");
    expect(mathml("\\divergence \\vb{F}")).toContain("⋅");
  });
  it("div stays division sign", () => {
    expect(visible("a \\div b")).toBe("a÷b");
  });
});

describe("siunitx macros", () => {
  it("SI with literal unit", () => {
    const v = visible("\\SI{9.8}{m/s^2}");
    expect(v).toBe("9.8m/s2");
    expect(html("\\SI{9.8}{m/s^2}")).toContain("mathrm");
  });
  it("qty with named units gives negative exponent", () => {
    expect(visible("\\qty{9.8}{\\metre\\per\\second}")).toBe("9.8ms−1");
  });
  it("prefixes, powers, si, unit, num", () => {
    expect(visible("\\si{\\kilo\\gram}")).toBe("kg");
    expect(visible("\\unit{\\metre\\squared}")).toBe("m2");
    expect(visible("\\unit{\\metre\\per\\second\\squared}")).toBe("ms−2");
    expect(visible("\\qty{3}{\\micro\\metre}")).toBe("3µm");
    expect(visible("\\num{1.5e3}")).toBe("1.5e3");
    expect(visible("\\num{12}")).toBe("12");
  });
  it("every named unit renders", () => {
    for (const u of ["metre", "meter", "second", "gram", "kilogram", "newton", "joule", "watt", "volt", "ampere", "ohm", "kelvin", "mole", "hertz"]) {
      expect(visible(`\\${u}`).length, u).toBeGreaterThan(0);
      html(`\\SI{2}{\\${u}}`);
    }
    for (const p of ["kilo", "micro", "milli", "centi", "mega", "giga", "nano"]) html(`\\SI{2}{\\${p}\\metre}`);
    html("\\SI{2}{\\metre\\cubed}");
  });
  it("macro definitions do not leak between calls", () => {
    html("\\gdef\\dv{zzz}\\dv");
    expect(reading("\\dv{x}{t}")).toBe("dxdt");
  });
});

describe("fix round 1", () => {
  it("keeps the space after control words in arguments", () => {
    for (const f of ["\\dv{\\vec v}{t}", "\\dv{\\alpha x}{t}", "\\expval{\\hat H}", "\\pdv{\\phi}{x}"]) html(f);
    expect(mathml("\\dv{\\alpha x}{t}")).toContain("α");
  });
  it("more units", () => {
    expect(visible("\\qty{5}{\\hour}")).toBe("5h");
    expect(visible("\\unit{\\kilo\\pascal}")).toBe("kPa");
    expect(visible("\\unit{\\litre}")).toBe("L");
    expect(visible("\\qty{20}{\\degreeCelsius}")).toBe("20∘C");
    expect(visible("\\unit{\\electronvolt}")).toBe("eV");
    for (const u of ["minute", "day", "tesla", "pascal", "coulomb", "farad", "henry", "radian", "percent", "liter"]) html(`\\SI{2}{\\${u}}`);
  });
  it("siunitx options are ignored", () => {
    expect(visible("\\SI[per-mode=symbol]{9.8}{m/s^2}")).toBe(visible("\\SI{9.8}{m/s^2}"));
    expect(visible("\\num[round-mode=none]{12}")).toBe("12");
    expect(visible("\\unit[x=y]{\\metre}")).toBe("m");
  });
  it("vb uses boldsymbol for symbols and star", () => {
    expect(html("\\vb{\\omega}")).toContain("boldsymbol");
    expect(mathml("\\vb{\\omega}")).toContain("ω");
    expect(html("\\vb*{a}")).toContain("boldsymbol");
    expect(html("\\vb{F}")).toContain("mathbf");
  });
});

describe("siunitx parity with the PDF (numbers as written)", () => {
  it("per applies to the next unit only", () => {
    expect(visible("\\si{\\joule\\per\\kilogram\\kelvin}")).toBe("Jkg−1K");
    expect(visible("\\unit{\\metre\\per\\second\\squared}")).toBe("ms−2");
    expect(visible("\\si{\\per\\second\\squared}")).toBe("s−2");
  });
  it("numbers print exactly as written", () => {
    expect(visible("\\num{1,500}")).toBe("1,500");
    expect(visible("\\num{12345}")).toBe("12345");
    expect(visible("\\num{.5}")).toBe(".5");
    expect(visible("\\num{1.5e3}")).toBe("1.5e3");
    expect(visible("\\SI{1,500}{\\metre}")).toBe("1,500m");
    expect(visible("\\SI{1.5e3}{\\metre}")).toBe("1.5e3m");
  });
  it("square and cubic are power prefixes inside units", () => {
    expect(visible("\\si{\\square\\metre}")).toBe("m2");
    expect(visible("\\si{\\cubic\\centi\\metre}")).toBe("cm3");
    expect(visible("\\si{\\per\\cubic\\metre}")).toBe("m−3");
    // outside a unit, \\square stays KaTeX's square symbol
    expect(visible("\\square")).toBe("□");
  });
  it("micro is the micro sign U+00B5, as siunitx prints it", () => {
    expect(visible("\\si{\\micro\\metre}")).toBe("\u00b5m");
    expect(visible("\\micro")).toBe("\u00b5");
  });
});
