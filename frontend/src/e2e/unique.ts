/**
 * A marker for titles, source links and emails that is unique across parallel
 * workers and `--repeat-each` runs: `Date.now()` alone collides when two tests
 * start in the same millisecond (two courses with one title, one email twice).
 */
export function uniqueMarker(): string {
  return `${Date.now()}${Math.random().toString(36).slice(2, 8)}`;
}
