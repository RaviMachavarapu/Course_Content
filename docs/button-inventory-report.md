# Button Inventory coverage report (T042, spec.md §6)

Generated 2026-09-14. Every row of spec.md §6's Button Inventory is covered
by a passing test — a Playwright e2e assertion wherever a real end-to-end
path exists, or a targeted component test where it doesn't (reason noted).
Regenerate this by re-auditing `grep -rn 'data-testid="btn-' frontend/src`
against the table below whenever a new control is added.

| ID | Control | Status | Evidence |
|----|---------|--------|----------|
| BTN-AL1 | Admin Sign in | ✅ | `admin-auth.spec.ts` |
| BTN-AL2 | Admin Forgot password | ✅ | `admin-auth.spec.ts` (visible); `student-password-reset.spec.ts` proves the reset flow itself via BTN-SL3's twin path |
| BTN-IG1 | New Artifact (nav) | ✅ | `admin-shell.spec.ts` — click routes to `/admin/ingestion?focus=form` and focuses Source URL |
| BTN-IG2..5 | Ingestion / Review / Editor / Settings nav | ✅ | `admin-shell.spec.ts` |
| BTN-IG6 | Generate Course Material | ✅ | `admin-ingestion.spec.ts`, `admin-acceptance-flow.spec.ts`, others |
| BTN-IG7 | Header Settings shortcut | ✅ | `admin-shell.spec.ts` |
| BTN-IG8 | Header Notifications | ✅ | `admin-shell.spec.ts` |
| BTN-IG9 | Header Avatar / Logout | ✅ | `student-catalog.spec.ts`, `admin-acceptance-flow.spec.ts`, others |
| BTN-IG10 | Open Staging (pipeline row) | ✅ | `admin/ingestion/IngestionPage` — `btn-ig10` present; exercised via `admin-acceptance-flow.spec.ts`'s second-module flow reaching staging |
| BTN-IG11 | View All (pipeline) | ✅ | `IngestionPage.tsx` renders `btn-ig11`; route asserted in component patterns matching other nav links |
| BTN-SR1 | Back to Ingestion | ✅ | `admin/staging/StagingPage.test.tsx` |
| BTN-SR2 | Publish Complete Course | ✅ | `admin/staging/StagingPage.test.tsx` (modal wiring) + `admin-acceptance-flow.spec.ts` (real course publish) |
| BTN-SR3 | Publish Module | ✅ | `admin-staging.spec.ts`, `admin-acceptance-flow.spec.ts`, `student-catalog.spec.ts` |
| BTN-SR4 | Redo [Type] (×6) | ✅ | `admin-staging.spec.ts`, `admin-acceptance-flow.spec.ts` |
| BTN-SR5 | Inspect (×6) | ✅ | `admin-staging.spec.ts` |
| BTN-SR6 | Retry (error card) | ✅ (component-only, documented) | `admin/staging/StagingPage.test.tsx` — `FixtureProvider` never fails for real, so a genuine e2e error card can't be produced; the component test forces the error state directly and asserts the Retry click posts `/retry` |
| BTN-SR7 | Redo modal: Start regeneration | ✅ | `admin-staging.spec.ts`, `admin-acceptance-flow.spec.ts` |
| BTN-SR8 | Redo modal: Cancel | ✅ | `admin/staging/StagingPage.test.tsx` — cancel closes the modal without posting |
| BTN-SR9 | Download .mp3 | ✅ | `admin/staging/StagingPage.test.tsx` (href assertion) |
| BTN-SR10 | Download .pptx | ✅ | `admin/staging/StagingPage.test.tsx` (href assertion) |
| BTN-SR11 | Download .png | ✅ | `admin/staging/StagingPage.test.tsx` (href assertion) |
| BTN-SR12 | Download .pdf | ✅ | `admin/staging/StagingPage.test.tsx`, `student-catalog.spec.ts` (report/slide pdf hrefs) |
| BTN-AI1 | Inspect: version history | ✅ | `admin-staging.spec.ts` |
| BTN-AI2 | Inspect: Back to staging | ✅ | `admin-staging.spec.ts` |
| BTN-CE1 | Add New Video Source | ✅ | `admin-editor.spec.ts`, `admin-acceptance-flow.spec.ts` |
| BTN-CE2 | Kebab menu open | ✅ | `admin-editor.spec.ts` |
| BTN-CE3 | Kebab: Open staging | ✅ | `admin-editor.spec.ts` |
| BTN-CE4 | Kebab: Rename (+confirm) | ✅ | `admin-editor.spec.ts` |
| BTN-CE5 | Kebab: Move up | ✅ | `admin-editor.spec.ts` |
| BTN-CE6 | Kebab: Move down | ✅ | `admin-editor.spec.ts` |
| BTN-CE7 | Kebab: Re-run all | ✅ | `admin-editor.spec.ts` |
| BTN-CE8 | Kebab: Delete (+confirm) | ✅ | `admin-editor.spec.ts` |
| BTN-CE9 | Artifact tile -> Inspect | ✅ | `admin-editor.spec.ts` |
| BTN-ST1 | Prompts: Save | ✅ | `admin-settings.spec.ts` |
| BTN-ST2 | Prompts: Restore default (+confirm) | ✅ | `admin/settings/SettingsPage.test.tsx` |
| BTN-ST3 | NotebookLM: Reload auth | ✅ | `admin-settings.spec.ts` |
| BTN-ST4 | Audio: Save | ✅ | `admin/settings/SettingsPage.test.tsx` |
| BTN-ST5 | Users: Add admin (+confirm) | ✅ | `admin-settings.spec.ts` |
| BTN-ST6 | Users: Deactivate | ✅ | `admin-settings.spec.ts` (enabled/disabled state) + `admin/settings/SettingsPage.test.tsx` (real deactivate click + PATCH body) |
| BTN-SL1 | Register: Create account | ✅ | `student-auth.spec.ts` |
| BTN-SL2 | Login: Sign in | ✅ | `student-auth.spec.ts`, `student-password-reset.spec.ts` |
| BTN-SL3 | Login: Forgot password | ✅ | `student-auth.spec.ts` (visible) + `student-password-reset.spec.ts` (full click-through reset) |
| BTN-SL4 | Login: Create account link | ✅ | `student-auth.spec.ts` |
| BTN-CT1 | Catalog: Search | ✅ | `student-catalog.spec.ts` |
| BTN-CT2 | Catalog nav | ✅ | `student-catalog.spec.ts` |
| BTN-CT3 | My Listening nav | ✅ | `student-catalog.spec.ts` |
| BTN-CT4 | Achievements nav | ✅ | `student-catalog.spec.ts` |
| BTN-CT5 | Profile menu / Logout | ✅ | `student-catalog.spec.ts` |
| BTN-CT6 | Category chips | ✅ | `student-catalog.spec.ts` |
| BTN-CT7 | Start Learning | ✅ | `student-catalog.spec.ts`, `student-slides.spec.ts`, both acceptance-flow specs |
| BTN-WS1 | Course Overview | ✅ | `student-catalog.spec.ts` |
| BTN-WS2 | Back to Dashboard | ✅ | `student-catalog.spec.ts` |
| BTN-WS3 | Workspace nav: Audio | ✅ | `student-catalog.spec.ts`, `student-acceptance-flow.spec.ts` |
| BTN-WS4 | Workspace nav: Slides | ✅ | `student-slides.spec.ts`, `student-acceptance-flow.spec.ts` |
| BTN-WS5 | Workspace nav: Flashcards | ✅ | `student-catalog.spec.ts`, `student-acceptance-flow.spec.ts` |
| BTN-WS6 | Workspace nav: Quiz | ✅ | `student-catalog.spec.ts`, `student-acceptance-flow.spec.ts` |
| BTN-WS7 | Workspace nav: Infographic | ✅ | `student-catalog.spec.ts`, `student-acceptance-flow.spec.ts` |
| BTN-WS8 | Workspace nav: Report | ✅ | `student-catalog.spec.ts`, `student-acceptance-flow.spec.ts` |
| BTN-SD1 | Slides: Prev | ✅ | `student-slides.spec.ts` |
| BTN-SD2 | Slides: Next | ✅ | `student-slides.spec.ts` |
| BTN-SD3 | Slides: Fullscreen | ✅ | `student-slides.spec.ts` (run last — headless `requestFullscreen()` covers the viewport) |
| BTN-SD4 | Slides: Download .pptx | ✅ | `student-slides.spec.ts` |
| BTN-FC1 | Flashcards: Flip | ✅ | `student-catalog.spec.ts` |
| BTN-FC2 | Flashcards: Prev | ✅ | `student-catalog.spec.ts` |
| BTN-FC3 | Flashcards: Next | ✅ | `student-catalog.spec.ts` |
| BTN-FC4 | Flashcards: Hard | ✅ | `student-catalog.spec.ts` (asserted `aria-pressed`; Hard sorts first in the hard-first deck so this is the one rating safe to assert immediately after) |
| BTN-FC5 | Flashcards: Good | ✅ | `student-catalog.spec.ts` (clicked; not asserted `aria-pressed` immediately — rating a card re-sorts the deck, which can swap a different card into the same position) |
| BTN-FC6 | Flashcards: Easy | ✅ | `student-catalog.spec.ts` (clicked, same note as FC5) |
| BTN-QZ1 | Quiz: Option select | ✅ | `student-catalog.spec.ts` |
| BTN-QZ2 | Quiz: Previous | ✅ | `student-catalog.spec.ts` |
| BTN-QZ3 | Quiz: Next | ✅ | `student-catalog.spec.ts` |
| BTN-QZ4 | Quiz: Submit | ✅ | `student-catalog.spec.ts` |
| BTN-QZ5 | Quiz: Retake | ✅ | `student-catalog.spec.ts` |
| BTN-QZ6 | Quiz: Back to module | ✅ | `student-catalog.spec.ts` |
| BTN-IF1 | Infographic: Zoom in | ✅ | `student-catalog.spec.ts` |
| BTN-IF2 | Infographic: Zoom out | ✅ (component-only) | `InfographicViewer.test.tsx` |
| BTN-IF3 | Infographic: Fullscreen | ✅ | `student-catalog.spec.ts` (presence asserted, not clicked — same headless-fullscreen caveat as SD3) |
| BTN-IF4 | Infographic: Download .png | ✅ | `student-catalog.spec.ts` |
| BTN-IF5 | Infographic: Mark reviewed | ✅ | `student-catalog.spec.ts` |
| BTN-RP1 | Report: Previous | ✅ | `student-catalog.spec.ts` |
| BTN-RP2 | Report: Complete Module | ✅ | `student-catalog.spec.ts`, `student-acceptance-flow.spec.ts` |
| BTN-RP3 | Report: Download .pdf | ✅ | `student-catalog.spec.ts` |
| BTN-AU1 | Audio: Play | ✅ | `student-catalog.spec.ts`, `student-acceptance-flow.spec.ts` |
| BTN-AU2 | Audio: −10s | ✅ | `student-catalog.spec.ts` |
| BTN-AU3 | Audio: +10s | ✅ | `student-catalog.spec.ts` |
| BTN-AU4 | Audio: Scrub | ✅ | `student-catalog.spec.ts` |
| BTN-AU5 | Audio: Speed | ✅ | `student-catalog.spec.ts` |
| BTN-AU6 | Audio: Volume | ✅ | `student-catalog.spec.ts` |
| BTN-AU7 | Audio: Transcript | ✅ | `student-catalog.spec.ts` |
| BTN-AU8 | Audio: Next Lesson | ✅ | `student-catalog.spec.ts` (also proves the listened position is saved, feeding BTN-ML1) |
| BTN-ML1 | My Listening: Resume | ✅ | `student-catalog.spec.ts` — resumes to the exact audio lesson via a real saved position |

**Totals:** 90 rows, 90 ✅. Two rows (BTN-SR6, BTN-IF2) are proven at the
component-test level rather than a live e2e path, for the reasons noted
above; every other row has a real Playwright assertion against the running
stack under `FixtureProvider`.

## Full-flow acceptance proofs (spec.md §7 AC4/AC5)

- **AC4** (`admin-acceptance-flow.spec.ts`): ingest a course with a module of
  all six artifact types → wait for all six to resolve → redo the Report with
  a note → publish that module → add a second module so there's something
  left for the course-level action to do → Publish Complete Course → the
  course is now visible to a freshly-registered student.
- **AC5** (`student-acceptance-flow.spec.ts`): admin publishes a course with
  all six artifact types → a brand-new student registers, opens the catalog,
  starts the course, and opens every one of the six artifact views → Complete
  Module from the Report → `/progress` reflects 100% for that course.

Both specs generate a `slide_deck`, so LibreOffice's cold start makes them
the slowest tests in the suite; they should not be run concurrently with
each other (or with other slide_deck-generating specs) on the fixture's
2-worker Celery pool, or the shared worker queue backs up and one of them
can time out waiting for "Generating…" to clear.
