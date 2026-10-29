/** A, B, C, … for option `i` (Studio quizzes can have more than four options). */
export function optionLetter(i: number): string {
  return i >= 0 && i < 26 ? String.fromCharCode(65 + i) : String(i + 1);
}
