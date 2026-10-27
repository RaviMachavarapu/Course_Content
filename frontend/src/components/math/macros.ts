/**
 * KaTeX macros for LaTeX package shorthand (physics, siunitx) that KaTeX does
 * not know. The generated PDFs typeset with the real packages, so the web pages
 * must draw the same notation. The reference look is the real-LaTeX output
 * (physics package, siunitx defaults). `\div` is deliberately NOT redefined: it
 * must stay the division sign.
 */

interface Tok {
  text: string;
}
/** The part of KaTeX's macro context the macros below use. */
interface Ctx {
  consumeArgs(n: number): Tok[][];
  consumeSpaces(): void;
  future(): Tok;
  popToken(): Tok;
}

/** Consume one braced argument and return its source text. */
function arg(ctx: Ctx): string {
  const toks = ctx.consumeArgs(1)[0] ?? [];
  return toks
    .slice()
    .reverse()
    .map((t) => t.text)
    .join("");
}

/** Optional [..] argument: returns its text or null when absent. */
function optArg(ctx: Ctx): string | null {
  ctx.consumeSpaces();
  if (ctx.future().text !== "[") return null;
  ctx.popToken();
  let out = "";
  for (let t = ctx.popToken(); t.text !== "]" && t.text !== "EOF"; t = ctx.popToken()) out += t.text;
  return out;
}

/** True when the next token opens a braced argument. */
function hasBrace(ctx: Ctx): boolean {
  ctx.consumeSpaces();
  return ctx.future().text === "{";
}

const D = "\\mathrm{d}";
const PARTIAL = "\\partial";

function power(sym: string, n: string | null): string {
  return n && n !== "1" ? `${sym}^{${n}}` : sym;
}

function dv(ctx: Ctx): string {
  const n = optArg(ctx);
  const f = arg(ctx);
  const sup = n && n !== "1" ? `^{${n}}` : "";
  if (!hasBrace(ctx)) return `\\frac{${D}${sup}}{${D} ${f}${sup}}`;
  const x = arg(ctx);
  return `\\frac{${D}${sup} ${f}}{${D} ${x}${sup}}`;
}

function pdv(ctx: Ctx): string {
  const n = optArg(ctx);
  const f = arg(ctx);
  if (!hasBrace(ctx)) return `\\frac{${power(PARTIAL, n)}}{${PARTIAL} ${f}${n && n !== "1" ? `^{${n}}` : ""}}`;
  const x = arg(ctx);
  if (hasBrace(ctx)) {
    const y = arg(ctx);
    return `\\frac{${PARTIAL}^{2} ${f}}{${PARTIAL} ${x}\\,${PARTIAL} ${y}}`;
  }
  return `\\frac{${power(PARTIAL, n)} ${f}}{${PARTIAL} ${x}${n && n !== "1" ? `^{${n}}` : ""}}`;
}

function expval(ctx: Ctx): string {
  const a = arg(ctx);
  if (hasBrace(ctx)) {
    const s = arg(ctx);
    return `\\left\\langle ${s}\\middle|${a}\\middle|${s}\\right\\rangle`;
  }
  return `\\left\\langle ${a}\\right\\rangle`;
}

// ---- siunitx -------------------------------------------------------------

const UNITS: Record<string, string> = {
  metre: "m",
  meter: "m",
  second: "s",
  gram: "g",
  kilogram: "kg",
  newton: "N",
  joule: "J",
  watt: "W",
  volt: "V",
  ampere: "A",
  ohm: "\\Omega",
  kelvin: "K",
  mole: "mol",
  hertz: "Hz",
};
const PREFIXES: Record<string, string> = {
  kilo: "k",
  milli: "m",
  centi: "c",
  mega: "M",
  giga: "G",
  nano: "n",
  micro: "\\mu ",
};
const POWERS: Record<string, number> = { squared: 2, cubed: 3 };

/**
 * Turn a unit argument into LaTeX the way siunitx prints it by default: upright,
 * units separated by a thin space, `\per` giving negative exponents. Plain text
 * such as `m/s^2` is kept literally in upright type.
 */
export function unitToLatex(src: string): string {
  if (!src.includes("\\")) return `\\mathrm{${src}}`;
  const names = src.match(/\\[A-Za-z]+/g) ?? [];
  const rest = src.replace(/\\[A-Za-z]+/g, "").trim();
  if (rest) return `\\mathrm{${src}}`;
  const groups: string[] = [];
  let prefix = "";
  let negative = false;
  let pending: { sym: string; exp: number } | null = null;
  const flush = () => {
    if (!pending) return;
    const e = negative ? -pending.exp : pending.exp;
    groups.push(e === 1 ? `\\mathrm{${pending.sym}}` : `\\mathrm{${pending.sym}}^{${e}}`);
    pending = null;
  };
  for (const full of names) {
    const name = full.slice(1);
    if (name === "per") {
      flush();
      negative = true;
    } else if (name in PREFIXES) {
      flush();
      prefix += PREFIXES[name];
    } else if (name in UNITS) {
      flush();
      pending = { sym: prefix + UNITS[name], exp: 1 };
      prefix = "";
    } else if (name in POWERS && pending) {
      pending.exp = POWERS[name] ?? 1;
    } else {
      return `\\mathrm{${src}}`;
    }
  }
  flush();
  return groups.join("\\,");
}

/** siunitx-ish number: `1.5e3` becomes 1.5 x 10^3. */
export function numToLatex(src: string): string {
  const m = /^\s*([-+]?[\d.,]+)\s*[eE]\s*([-+]?\d+)\s*$/.exec(src);
  if (m) return `${m[1]}\\times 10^{${Number(m[2])}}`;
  return src.trim();
}

const SI = (ctx: Ctx): string => {
  const n = arg(ctx);
  const u = arg(ctx);
  return `${numToLatex(n)}\\,${unitToLatex(u)}`;
};

function unitMacros(): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(UNITS)) out[`\\${k}`] = `\\mathrm{${v}}`;
  for (const [k, v] of Object.entries(PREFIXES)) out[`\\${k}`] = `\\mathrm{${v}}`;
  out["\\squared"] = "^{2}";
  out["\\cubed"] = "^{3}";
  out["\\per"] = "/";
  return out;
}

type MacroValue = string | ((ctx: Ctx) => string);

export const MATH_MACROS: Readonly<Record<string, MacroValue>> = Object.freeze({
  ...unitMacros(),
  "\\dv": dv,
  "\\pdv": pdv,
  "\\abs": "\\left|#1\\right|",
  "\\norm": "\\left\\lVert #1\\right\\rVert",
  "\\vb": "\\mathbf{#1}",
  "\\vu": "\\mathbf{\\hat{#1}}",
  "\\expval": expval,
  "\\grad": "\\nabla",
  "\\curl": "\\nabla\\times",
  "\\divergence": "\\nabla\\cdot",
  "\\SI": SI,
  "\\qty": SI,
  "\\si": (ctx: Ctx) => unitToLatex(arg(ctx)),
  "\\unit": (ctx: Ctx) => unitToLatex(arg(ctx)),
  "\\num": (ctx: Ctx) => numToLatex(arg(ctx)),
});
