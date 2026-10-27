export type Segment =
  | { kind: "text"; text: string }
  | { kind: "math"; latex: string; display: boolean; raw: string };

const isSpace = (c: string | undefined) => c === undefined || /\s/.test(c);
const isDigit = (c: string | undefined) => c !== undefined && /[0-9]/.test(c);

/**
 * Split plain text into text and formula segments. `$$…$$` is display math,
 * `$…$` inline (opening `$` followed by a non-space, closing `$` preceded by a
 * non-space and not followed by a digit); `\$` is a literal dollar;
 * `\(…\)` is inline and `\[…\]` display math (NotebookLM's style).
 */
export function splitMath(text: string): Segment[] {
  // old rows may lack the field: treat anything that isn't a string as empty
  const input = typeof text === "string" ? text : "";
  const out: Segment[] = [];
  let buf = "";
  const flush = () => {
    if (buf) out.push({ kind: "text", text: buf });
    buf = "";
  };
  let i = 0;
  while (i < input.length) {
    const c = input[i];
    if (c === "\\" && input[i + 1] === "$") {
      buf += "$";
      i += 2;
      continue;
    }
    if (c === "\\" && input[i + 1] === "\\" && (input[i + 2] === "(" || input[i + 2] === "[")) {
      buf += "\\\\"; // an escaped backslash: the bracket after it is plain text
      i += 2;
      continue;
    }
    if (c === "\\" && (input[i + 1] === "(" || input[i + 1] === "[")) {
      const display = input[i + 1] === "[";
      const end = findBracketEnd(input, i + 2, display ? "]" : ")");
      if (end > i + 2) {
        flush();
        out.push({
          kind: "math",
          latex: input.slice(i + 2, end),
          display,
          raw: input.slice(i, end + 2),
        });
        i = end + 2;
        continue;
      }
    }
    if (c === "$") {
      if (input[i + 1] === "$") {
        const end = findDisplayEnd(input, i + 2);
        if (end > i + 2) {
          flush();
          out.push({
            kind: "math",
            latex: input.slice(i + 2, end),
            display: true,
            raw: input.slice(i, end + 2),
          });
          i = end + 2;
          continue;
        }
      } else if (!isSpace(input[i + 1])) {
        const end = findInlineEnd(input, i + 1);
        if (end > 0) {
          flush();
          out.push({
            kind: "math",
            latex: input.slice(i + 1, end),
            display: false,
            raw: input.slice(i, end + 1),
          });
          i = end + 1;
          continue;
        }
      }
    }
    buf += c;
    i += 1;
  }
  flush();
  return out;
}

function findBracketEnd(s: string, from: number, close: string): number {
  for (let j = from; j < s.length - 1; j++) {
    if (s[j] === "\\") {
      if (s[j + 1] === close) return j;
      j += 1;
    }
  }
  return -1;
}

function findDisplayEnd(s: string, from: number): number {
  for (let j = from; j < s.length - 1; j++) {
    if (s[j] === "\\") {
      j += 1;
      continue;
    }
    if (s[j] === "$" && s[j + 1] === "$") return j;
  }
  return -1;
}

function findInlineEnd(s: string, from: number): number {
  for (let j = from; j < s.length; j++) {
    if (s[j] === "\\") {
      j += 1;
      continue;
    }
    if (s[j] === "$" && !isSpace(s[j - 1]) && !isDigit(s[j + 1])) return j;
  }
  return -1;
}
