# Quarto PDFs, KaTeX Physics Safety Net, Notation Prompt — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every artifact (report, flashcards, quiz, infographic, slide deck) gets a downloadable PDF typeset by Quarto/LaTeX with exact formulas; the web renderer understands common physics/units shorthand; the prompts steer NotebookLM to standard LaTeX.

**Architecture:** A new `typeset` compose service (Quarto + TinyTeX + LaTeX packages) exposes `POST /pdf`. After an artifact version is ready, a Celery task builds that artifact type's Markdown document from `content_json` (+ stored images), calls the service, and stores the PDF as a MediaFile of that version. PDF failures never fail the artifact. Admin and student pages show a "Download PDF" link per artifact. KaTeX gets a macro set mirroring the LaTeX `physics`/`siunitx` commands. The Flashcards/Quiz/Report prompt templates gain one more line.

**Tech Stack:** Quarto (pinned), TinyTeX + xelatex, LaTeX packages mhchem (v4), siunitx, physics, braket, chemfig, cancel; Python 3.12 (stdlib http.server or FastAPI) for the service; existing FastAPI/Celery/SQLAlchemy/React.

**Spec:** Owner-approved design in conversation, 2026-10-27 (no spec file). Evidence: `/private/tmp/claude-501/-Users-ashwinpingali-Desktop-Ravi-Course-Content-main/461ca6b1-2ea1-4013-a31c-06fe7ed2b5f1/scratchpad/notation-spike/results.md` and `quarto/header-fixed.tex` there (68 test formulas compile with 0 errors with that header).

## Global Constraints

- Exactness: the PDF typesets the same LaTeX the web page draws — never rewrite or "fix" a formula. A formula that fails to compile is shown as its original LaTeX source in monospace (`\texttt{}` with the source escaped), never dropped, and the rest of the document still builds.
- LaTeX header = the spike's `header-fixed.tex` (mhchem v4, siunitx, physics, then braket, chemfig, cancel, plus `\AtBeginDocument{\RenewCommandCopy\qty\SI}`); copy it into the repo verbatim and record its origin in a comment.
- Engine: xelatex. Unicode text (µ, →, ≤, ≥, ×, °, Greek) must appear in the PDF — use a font with full coverage (e.g. a Latin Modern/TeX Gyre or DejaVu family via fontspec); test with µ explicitly.
- PDF per type (new MediaFileKinds; `report_pdf` is reused for reports and its WeasyPrint renderer is replaced): report → title, read time, key takeaways, sections (section HTML converted to Markdown with formula elements → `$…$`/`$$…$$`); flashcards → `flashcards_pdf`: category, front, back per card; quiz → `quiz_pdf`: questions with options, then an answer key with correct option + explanation; infographic → `infographic_pdf`: the stored infographic image, then caption and description; slide deck → `slides_handout_pdf`: each stored slide image followed by that slide's notes. NotebookLM's own `deck_pdf`/`pptx` stay untouched.
- PDF building is decoupled: an artifact becomes `ready` exactly as today; a failed/unavailable typeset service only means no PDF yet (logged, retried), never an artifact error.
- New KaTeX macros mirror the real packages' output (the spike's Quarto-PDF renders are the reference): `\dv`, `\pdv` (incl. optional order/variable forms used in the spike), `\abs`, `\norm`, `\vb`, `\vu`, `\expval`, `\grad`, `\curl`, `\divergence` (NOT redefining `\div`, which must stay ÷), `\SI`, `\si`, `\qty` (siunitx meaning, as in the fixed PDF header), `\unit`, `\num`, and the unit names used in the spike (`\metre`, `\meter`, `\second`, `\kilo`, `\gram`, `\kilogram`, `\per`, `\newton`, `\joule`, `\watt`, `\volt`, `\ampere`, `\ohm`, `\kelvin`, `\mole`, `\hertz`, `\squared`, `\cubed`, `\micro`, `\milli`, `\centi`, `\mega`, `\giga`, `\nano`). Defined in the single KaTeX options module.
- Prompt line 2 (exact text), appended as a new paragraph after the existing LaTeX line in the Flashcards, Quiz and Report templates: `Use standard LaTeX (e.g. \frac{dx}{dt}, \mathrm{m/s^2}, \mathbf{F}) rather than package shorthand such as \dv, \SI or \qty.`
- Live safety: tests never reach live NotebookLM or the dev DB; the controller runs live steps.
- Commands: backend `docker compose run --rm -T api sh -c 'pytest -o addopts="" -q <paths>'` + `mypy app`; frontend `cd frontend && docker build -q --target build -t sdp-fe-build . && docker run --rm sdp-fe-build npx vitest run <paths>` + `npx tsc -p tsconfig.app.json --noEmit`. Never commit `frontend/node_modules`. Format only touched files.

## Review Focus

1. One malformed formula among many → PDF still builds; that formula shows as its source text; others typeset. → Task 3 `bad formula falls back, document builds`.
2. Typeset service down or slow → artifact still `ready`, generation unaffected, PDF retried later. → Task 5 `pdf failure does not fail artifact`.
3. Text with Unicode (µ, →, ≤) and LaTeX-special characters in plain text (`%`, `#`, `&`, `_`, `{`, `}`, `~`, `^`, `\`) → appear literally, no LaTeX error. → Task 3 `plain text specials are escaped` and Task 4 builder tests.
4. A student fetching the PDF of an unpublished version → refused (existing media rules: only published versions' MediaFiles). → Task 5 `student cannot fetch unpublished pdf`.
5. `\div` still renders ÷ after the macro shim. → Task 1 `div stays division sign`.

---

### Task 1: KaTeX physics/units macro safety net
**Files:** `frontend/src/components/math/katex.ts` (+ a macros module if cleaner), tests in `frontend/src/components/math/`.
- [ ] Tests: each macro in Global Constraints renders without `.katex-error` and with the expected structure (e.g. `\dv{x}{t}` → a fraction d x over d t; `\SI{9.8}{m/s^2}` → "9.8" + upright unit; `\qty{9.8}{\metre\per\second}` → 9.8 m s⁻¹ per siunitx default; `\abs{x}` → |x|); `div stays division sign`; existing math tests stay green.
- [ ] Implement, vitest + tsc, commit "KaTeX: physics and units shorthand macros".

### Task 2: Prompt line 2
**Files:** `backend/app/prompts/{flashcards,quiz,report}.md`, `backend/app/cli.py` (extend `add-math-prompt-line` or add `add-notation-prompt-line`, idempotent, new versions via the prompts service), tests in `backend/tests/test_cli.py`.
- [ ] Tests: exact line present in seed files after the LaTeX line; command adds one version per type once.
- [ ] Implement, full suite + mypy, commit "Prompts: prefer standard LaTeX over package shorthand".

### Task 3: `typeset` service
**Files:** Create `typeset/Dockerfile` (pinned Quarto + TinyTeX + the packages; must build on linux/amd64 and run on Apple Silicon via emulation — set `platform: linux/amd64` in compose if no arm64 build), `typeset/header.tex` (verbatim from the spike), `typeset/server.py`, `typeset/tests/`; Modify `docker-compose.yml` (service `typeset`, internal only, no published port, healthcheck).
**Produces:** `POST /pdf` JSON `{"markdown": str, "title": str, "images": {name: base64}}` → `200 application/pdf`; `422 {"error"}` only if even the fallback document can't build; `GET /health`. Markdown uses `$…$`/`$$…$$` (pandoc tex_math_dollars) and `\ce{}` etc. Image references `![](name)` resolve to the supplied images.
**Behavior:** render with Quarto (`format: pdf`, xelatex, header included); on LaTeX failure, find the failing formula(s) (compile each formula alone in a minimal doc with the same header), replace each failing one with its escaped source in `\texttt{}`, and render again. Timeout per document 120 s.
- [ ] Tests (run inside the built image): good doc → PDF (check `%PDF-` and that `pdftotext` contains expected text); `bad formula falls back, document builds` (one `$\frac{1}{$` among good formulas → PDF builds, pdftotext shows the source); `plain text specials are escaped`; µ and → present in pdftotext output; chemfig and `\ce` compile.
- [ ] Implement; build the image; run tests in it; commit "Typeset service: Quarto PDFs with exact formulas".

### Task 4: Document builders + client + media kinds
**Files:** Create `backend/app/render/typeset_docs.py` (one builder per artifact type: `content_json` + image blobs → `(markdown, title, images)`), `backend/app/render/typeset_client.py` (`render_pdf(markdown, title, images) -> bytes`, raises `TypesetUnavailable` / `TypesetError`; endpoint from settings `typeset_endpoint = "http://typeset:8080"`), migration adding MediaFileKinds `flashcards_pdf`, `quiz_pdf`, `infographic_pdf`, `slides_handout_pdf` (+ `STORAGE_EXTS`), tests.
- Report section HTML → Markdown: convert `<span class="math-inline">X</span>` → `$X$`, `<div class="math-display">X</div>` → `$$X$$` (unescaped LaTeX), rest via a small HTML→Markdown conversion that escapes Markdown/LaTeX specials in text (or send HTML for pandoc to read — choose one and test).
- [ ] Tests per builder with real NotebookLM-like samples (incl. `$S_N2$`, a `$$…$$`, `%`/`_`/`&` in plain text, µ); client tests with httpx MockTransport.
- [ ] Implement; suite + mypy; commit "Backend: Quarto document builders and typeset client".

### Task 5: Build PDFs after generation; rebuild command; drop WeasyPrint report PDF
**Files:** `backend/app/tasks/` (new Celery task `build_artifact_pdf(version_id)`, retries with back-off on `TypesetUnavailable`, logs and gives up on `TypesetError`), `backend/app/pipeline/orchestrator.py` (enqueue after a version is stored; remove report_pdf from the report renderer path), `backend/app/pipeline/renderers.py`, `backend/app/cli.py` (`rebuild-pdfs [--dry-run]` for all ready/published versions of the 5 types), tests.
- [ ] Tests: version ready → task enqueued; task stores the PDF MediaFile for that version (replacing a previous PDF of the same kind for that version); `pdf failure does not fail artifact`; `student cannot fetch unpublished pdf`; rebuild command dry-run writes nothing.
- [ ] Implement; suite + mypy; commit "Build Quarto PDFs for every artifact after generation".

### Task 6: Download links on admin and student pages
**Files:** `frontend/src/admin/staging/ArtifactCard.tsx` (media buttons), `frontend/src/admin/inspect/ContentView.tsx` or InspectPage (a Download PDF link when the version has the PDF kind), student viewers for report/flashcards/quiz/infographic/slides (a "Download PDF" link when present); tests.
- [ ] Tests: link shown with the media URL when the PDF media exists; hidden when absent.
- [ ] Implement; vitest + tsc; commit "Download PDF links for every artifact".

### Controller (after Task 6)
Build and start `typeset`; rebuild api/worker/beat/web; run migration; `rebuild-pdfs --dry-run`, then real; open the chemistry module PDFs (all 5 types) and the physics/math notation-check outputs; screenshot PDF pages.
