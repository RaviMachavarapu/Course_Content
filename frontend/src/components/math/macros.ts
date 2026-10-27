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
  // KaTeX's lexer drops the space after a control word; put it back where the
  // next token is a letter so `\vec v` does not become `\vecv`.
  let out = "";
  for (const t of toks.slice().reverse()) {
    if (/\\[A-Za-z]+$/.test(out) && /^[A-Za-z]/.test(t.text)) out += " ";
    out += t.text;
  }
  return out;
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

/** physics: bold upright letters; symbols (Greek) and the starred form use \boldsymbol. */
function vb(ctx: Ctx): string {
  ctx.consumeSpaces();
  let star = false;
  if (ctx.future().text === "*") {
    ctx.popToken();
    star = true;
  }
  const a = arg(ctx);
  return star || a.startsWith("\\") ? `\\boldsymbol{${a}}` : `\\mathbf{${a}}`;
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
  hour: "h",
  minute: "min",
  day: "d",
  litre: "L",
  liter: "L",
  tesla: "T",
  pascal: "Pa",
  coulomb: "C",
  farad: "F",
  henry: "H",
  radian: "rad",
  degreeCelsius: "^\\circ C",
  electronvolt: "eV",
  percent: "\\%",
};
const PREFIXES: Record<string, string> = {
  kilo: "k",
  milli: "m",
  centi: "c",
  mega: "M",
  giga: "G",
  nano: "n",
  // siunitx prints the micro sign U+00B5 (not the Greek letter mu)
  micro: "\u00b5",
};
/** Powers after a unit (`\metre\squared`) and before it (`\square\metre`). */
const POWERS: Record<string, number> = { squared: 2, cubed: 3 };
const POWER_PREFIXES: Record<string, number> = { square: 2, cubic: 3 };

/**
 * Turn a unit argument into LaTeX the way siunitx prints it by default: upright,
 * units separated by a thin space, `\per` giving the NEXT unit a negative
 * exponent (`\joule\per\kilogram\kelvin` is J kg⁻¹ K), `\square`/`\cubic`
 * before a unit and `\squared`/`\cubed` after it giving powers. Plain text
 * such as `m/s^2` is kept literally in upright type.
 */
export function unitToLatex(src: string): string {
  if (!src.includes("\\")) return `\\mathrm{${src}}`;
  const names = src.match(/\\[A-Za-z]+/g) ?? [];
  const rest = src.replace(/\\[A-Za-z]+/g, "").trim();
  if (rest) return `\\mathrm{${src}}`;
  const groups: string[] = [];
  let prefix = "";
  let negative = false; // a \per waiting for its unit
  let power = 1; // a \square / \cubic waiting for its unit
  let pending: { sym: string; exp: number } | null = null;
  const flush = () => {
    if (!pending) return;
    const e = pending.exp;
    groups.push(e === 1 ? `\\mathrm{${pending.sym}}` : `\\mathrm{${pending.sym}}^{${e}}`);
    pending = null;
  };
  for (const full of names) {
    const name = full.slice(1);
    if (name === "per") {
      flush();
      negative = true;
    } else if (name in POWER_PREFIXES) {
      flush();
      power = POWER_PREFIXES[name] ?? 1;
    } else if (name in PREFIXES) {
      flush();
      prefix += PREFIXES[name];
    } else if (name in UNITS) {
      flush();
      pending = { sym: prefix + UNITS[name], exp: negative ? -power : power };
      prefix = "";
      negative = false;
      power = 1;
    } else if (name in POWERS && pending) {
      const p = POWERS[name] ?? 1;
      pending.exp = pending.exp < 0 ? -p : p;
    } else {
      return `\\mathrm{${src}}`;
    }
  }
  flush();
  return groups.join("\\,");
}

/** siunitx number with `parse-numbers=false` (as the PDF typesets it): exactly
 * as written — `1,500`, `.5` and `1.5e3` are not reformatted. */
export function numToLatex(src: string): string {
  return `{${src.trim()}}`;
}

const SI = (ctx: Ctx): string => {
  optArg(ctx); // siunitx options are accepted and ignored
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
  "\\vb": vb,
  "\\vu": "\\mathbf{\\hat{#1}}",
  "\\expval": expval,
  "\\grad": "\\nabla",
  "\\curl": "\\nabla\\times",
  "\\divergence": "\\nabla\\cdot",
  "\\SI": SI,
  "\\qty": SI,
  "\\si": (ctx: Ctx) => (optArg(ctx), unitToLatex(arg(ctx))),
  "\\unit": (ctx: Ctx) => (optArg(ctx), unitToLatex(arg(ctx))),
  "\\num": (ctx: Ctx) => (optArg(ctx), numToLatex(arg(ctx))),
});
