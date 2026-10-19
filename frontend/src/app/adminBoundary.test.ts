import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

/**
 * T040 — US-N3 build-time guarantee: nothing under the student source tree
 * imports admin code. The two apps are compiled into one Vite bundle (no
 * route-level code-splitting), so this is what actually keeps admin screens,
 * strings, and API shapes out of anything a student's browser has to load or
 * could statically discover — a route guard alone can't prove that.
 */
const HERE = dirname(fileURLToPath(import.meta.url));
const SRC = resolve(HERE, "..");
const STUDENT_DIR = join(SRC, "student");

const ADMIN_IMPORT = /from\s+["'](@\/admin\/|\.\.\/admin\/|\.\.\/\.\.\/admin\/)/;

function walk(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    const st = statSync(full);
    if (st.isDirectory()) out.push(...walk(full));
    else if (/\.(ts|tsx)$/.test(entry) && !/\.test\.(ts|tsx)$/.test(entry)) out.push(full);
  }
  return out;
}

describe("student/admin import boundary (US-N3)", () => {
  it("no file under src/student imports from src/admin", () => {
    const offenders = walk(STUDENT_DIR)
      .filter((file) => ADMIN_IMPORT.test(readFileSync(file, "utf-8")))
      .map((file) => file.slice(SRC.length + 1));

    expect(offenders).toEqual([]);
  });
});
