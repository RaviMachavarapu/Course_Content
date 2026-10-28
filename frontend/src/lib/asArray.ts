/** `v` when it is an array, else `[]`. Content JSON comes from parsers and
 * older rows, so a field typed as a list may be missing or a different shape:
 * render nothing for it instead of crashing the screen. */
export function asArray<T = unknown>(v: unknown): T[] {
  return Array.isArray(v) ? (v as T[]) : [];
}
