# Math & Formula Rendering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Formulas, equations, chemical formulas and symbols that NotebookLM writes in flashcards, quiz and report content are drawn as real math on admin Inspect and on student pages, exactly as NotebookLM wrote them.

**Architecture:** NotebookLM emits LaTeX: `$…$` in flashcard/quiz text, and in interactive reports a run format flag (format slot 9: `1` inline formula, `2` displayed equation) that the parser currently turns into `<code>`. The backend emits formula elements (`<span class="math-inline">LATEX</span>`, `<div class="math-display">LATEX</div>`, LaTeX HTML-escaped). The frontend draws `$…$` text and those elements with KaTeX (+ mhchem). Existing reports are rebuilt by re-reading them from NotebookLM (no generation). The Flashcards/Quiz/Report prompt templates gain one instruction line.

**Tech Stack:** Python 3.12 / FastAPI / markdown-it-py (backend), React + TypeScript + Vitest (frontend), `katex@0.16.11` (+ `katex/contrib/mhchem`).

**Spec:** Owner-approved design in conversation, 2026-10-26 (no spec file). Binding decisions are restated in Global Constraints.

## Global Constraints

- Render exactly what NotebookLM wrote — never rewrite, normalise, guess or "fix" a formula. A formula KaTeX can't render (`throwOnError: false` reports an error) is shown as its ORIGINAL text, unchanged, including the `$` delimiters for `$…$` text.
- Delimiters in plain text: inline `$…$`, display `$$…$$`. Dollar rule (pandoc): an opening `$` must be followed by a non-space and a closing `$` must be preceded by a non-space and NOT followed by a digit; `\$` is a literal dollar. So "costs $5 and $10" stays text.
- Report formula elements: `<span class="math-inline">` and `<div class="math-display">`, containing only the HTML-escaped LaTeX. Real code stays `<code>`.
- KaTeX options: `throwOnError: false`, `strict: "ignore"`, `trust: false`, `output: "htmlAndMathml"`; display mode for `$$…$$` / `math-display`. Load `katex/dist/katex.min.css` once in the app entry. Load `katex/contrib/mhchem` (side-effect import) so `\ce{…}` works.
- Prompt line (exact text), appended as a new paragraph to the Flashcards, Quiz and Report templates: `Write every mathematical expression, equation, chemical formula and scientific symbol in LaTeX between $ signs (e.g. $S_N2$, $\frac{1}{2}mv^2$, $\ce{H2O}$), copied exactly from the source, never paraphrased or invented.`
- Live safety: tests never reach live NotebookLM. Only the controller runs the one-time report refresh against live NotebookLM.
- Commands: backend `docker compose run --rm -T api sh -c 'pytest -o addopts="" -q <paths>'` (+ `mypy app`); frontend `cd frontend && docker build -q --target build -t sdp-fe-build . && docker run --rm sdp-fe-build npx vitest run <paths>` and `npx tsc -p tsconfig.app.json --noEmit`. Format only touched files.

## Review Focus

1. A currency sentence ("costs $5 and $10") inside flashcards/quiz → stays plain text. → Task 3 `dollar amounts stay text`.
2. Malformed LaTeX from NotebookLM (`$\frac{1}{$`) → original text shown, page doesn't crash. → Task 3 `unrenderable formula shows original text`.
3. Markdown (Document) report math containing `_`, `*` or `\` (e.g. `$a_1 * b_1$`, `$\alpha$`) → reaches the page intact, not turned into emphasis or with backslashes eaten. → Task 1 `markdown math survives markdown rendering`.
4. HTML injection through LaTeX (`$<img src=x onerror=alert(1)>$`, or a report run containing `<script>`) → never executed; escaped. → Task 1 `formula text is escaped`, Task 3 `html in formula is not injected`.
5. A report whose NotebookLM notebook/artifact no longer exists during the one-time refresh → skipped and listed, never blanked. → Task 2 `missing artifact is skipped and listed`.

---

### Task 1: Report parser emits formula elements

**Files:** Modify `backend/app/pipeline/parsers/notebooklm.py` (`_run_html` ~172-185, `_sections_from_markdown` ~149-169, display-math runs in `_sections_from_blocks`); Test: `backend/tests/test_notebooklm_parsers.py`.

**Interfaces — Produces:** report `sections[].html` contains `<span class="math-inline">ESCAPED_LATEX</span>` / `<div class="math-display">ESCAPED_LATEX</div>`; the sanitizer (`_sanitize.py`, already allows span/div + class) keeps them.

- [ ] Tests first:
  - `test_interactive_inline_formula_becomes_math_span`: run `[0, 4, ["S_N2", [None]*9 + [1]]]` → html contains `<span class="math-inline">S_N2</span>`, not `<code>`.
  - `test_interactive_bold_formula`: format `[True, None, …, 1]` → `<strong><span class="math-inline">S_N2</span></strong>` (or the span inside strong; assert both present, no `<code>`).
  - `test_interactive_display_formula_becomes_math_div`: format slot 9 == 2 → `<div class="math-display">…</div>`.
  - `test_formula_text_is_escaped`: run text `a<b` with slot 9 == 1 → `<span class="math-inline">a&lt;b</span>`.
  - `test_markdown_math_survives_markdown_rendering`: Document markdown `"## S\nRate $k_1 * [A]_0$ and $$\\alpha_2$$ cost \\$5"` → html contains `<span class="math-inline">k_1 * [A]_0</span>`, `<div class="math-display">\alpha_2</div>` (escaped as needed), and the literal `$5`; no `<em>`.
  - `test_real_code_stays_code`: a markdown code span `` `print(x)` `` stays `<code>`.
- [ ] Implement: slot 9 → math element (1 inline span, 2 display div); for markdown, extract math spans with the Global Constraints dollar rule into placeholders before `_md.render`, then substitute the escaped math elements after rendering (before `sanitize_html`).
- [ ] Run the parser tests + full backend suite + mypy. Commit "Report parser: emit formula elements instead of code".

### Task 2: One-time re-read of existing reports

**Files:** Modify `backend/app/cli.py` (new command `refresh-report-math`); Test: `backend/tests/test_cli.py`.

**Interfaces — Consumes:** Task 1 parser; provider `fetch_content(StudioJobRef) -> RawArtifact` (see orchestrator `_generate` for how a report's raw row is fetched and parsed via `parse_notebooklm`/`_content_and_media`).
**Produces:** `python -m app.cli refresh-report-math [--dry-run]` — for every report `ArtifactVersion` with a `notebooklm_artifact_id`, re-fetch from NotebookLM using its module's `notebooklm_notebook_id`, re-parse with the Task 1 parser, and update that version's `content_json` and `content_html` in place (same revision; the NotebookLM artifact is the same, only our rendering of it changes). Prints one line per version: `updated|unchanged|skipped (<reason>)`, and a summary. Never blanks a version: any fetch/parse error → skipped, row untouched.

- [ ] Tests (FixtureProvider / fake provider): `test_refresh_updates_report_html_in_place`, `test_missing_artifact_is_skipped_and_listed`, `test_dry_run_changes_nothing`.
- [ ] Implement; run tests + full suite. Commit "CLI: refresh-report-math re-reads existing reports".

### Task 3: Frontend `MathText` (KaTeX)

**Files:** `frontend/package.json` + lockfile (`katex@0.16.11`, `@types/katex` if needed; install with `docker run --rm -v "$PWD/frontend:/app" -w /app node:20 npm install katex@0.16.11 --save-exact`); Create `frontend/src/components/math/MathText.tsx`, `frontend/src/components/math/renderMathInHtml.ts`, `frontend/src/components/math/katex.ts` (single place that imports katex + mhchem + options); tests next to them; import `katex/dist/katex.min.css` in the app entry (`frontend/src/main.tsx`).

**Interfaces — Produces:** `<MathText text={string} className? />` renders plain text with `$…$`/`$$…$$` formulas drawn; `renderMathInHtml(html: string): string` replaces `math-inline`/`math-display` element contents with KaTeX HTML (used on sanitized report HTML); both use the Global Constraints options and fallback.

- [ ] Tests: `renders inline formula` (`$S_N2$` → a `.katex` element, text has no `$`), `renders display formula`, `dollar amounts stay text`, `escaped dollar stays literal`, `unrenderable formula shows original text` (`$\frac{1}{$` → original `$\frac{1}{$` visible, no throw), `html in formula is not injected` (`$<img src=x onerror=alert(1)>$` → no `img` element), `mhchem works` (`$\ce{H2O}$` → `.katex`), `renderMathInHtml draws math elements and leaves code alone`.
- [ ] Implement; vitest + tsc. Commit "Frontend: MathText and renderMathInHtml with KaTeX".

### Task 4: Use it on admin Inspect and student pages

**Files:** `frontend/src/admin/inspect/ContentView.tsx` (flashcards front/back/category, quiz question/options/explanation, report html via `renderMathInHtml`, infographic description), `frontend/src/student/workspace/flashcards/FlashcardsViewer.tsx`, `frontend/src/student/workspace/quiz/QuizViewer.tsx` (question, options, explanation, results view), `frontend/src/student/workspace/report/ReportViewer.tsx` (`s.html` via `renderMathInHtml`); tests next to each.

- [ ] Tests: each view renders a `$S_N2$` sample as `.katex` (and the report a `math-inline` element); existing tests stay green.
- [ ] Implement; vitest (all) + tsc. Commit "Show formulas on Inspect and student pages".

### Task 5: Prompt templates

**Files:** `backend/app/prompts/flashcards.md`, `quiz.md`, `report.md` (append the exact line); `backend/app/cli.py` command `add-math-prompt-line` that, for flashcards/quiz/report, creates a new active template version (via `app.services.prompts`' existing update function) with the line appended as a new paragraph unless the active body already contains it; Test: `backend/tests/test_cli.py` / `test_prompts_service.py`.

- [ ] Tests: `test_math_line_appended_once` (running twice adds one version only), seed files contain the exact line.
- [ ] Implement; tests + full suite. Commit "Prompts: ask NotebookLM for LaTeX formulas".

### Controller (after Task 5)

Rebuild/restart web; run `refresh-report-math --dry-run` then for real on the dev DB (live NotebookLM, no generation); run `add-math-prompt-line` on the dev DB; screenshot the chemistry module's flashcards, quiz and report (Inspect + student).
