# Task List — Shikshak Dp AI Course Content Suite

**Version:** 1.0 (draft for review)
**Rules:** Execute in order. One task at a time. A task is **Done** only per
`constitution.md` Art. VI (code + tests + lint + type-check + acceptance +
`task-tracker.md` updated + runs under `FixtureProvider`). Do not start a task
whose dependencies are not Done or whose Open Items are not closed.

Legend — **Dep:** dependencies · **OI:** blocking Open Item · **AC:** acceptance
criteria · **Touches:** main paths.

---

## Phase 0 — Foundations

### T001 — Repo scaffold & tooling
- **Dep:** none
- **Touches:** `/README.md`, `backend/pyproject.toml`, `frontend/package.json`, `.editorconfig`, `.gitignore`, `.pre-commit-config.yaml`, `.github/workflows/ci.yml` (stub)
- **AC:**
  - Monorepo dirs created per `plan.md` §2.
  - `backend`: Ruff + Black + mypy configured; `pytest` runs (0 tests OK).
  - `frontend`: Vite + TS + ESLint + Prettier + Vitest configured; `npm run build` succeeds on the empty app.
  - `pre-commit` runs formatters/linters for both stacks.
  - Root `README.md` explains layout and how to run each stack.

### T002 — Dev environment (docker compose)
- **Dep:** T001
- **Touches:** `docker-compose.yml`, `docker-compose.override.example.yml`, `backend/Dockerfile`, `frontend/Dockerfile`, `mcp/Dockerfile`
- **AC:**
  - `docker compose up` starts `postgres`, `redis`, `api`, `worker`, `beat`, `web`, `mailhog` healthy.
  - `mcp` service defined but `profiles: [mcp]` (off by default).
  - `api` reachable at `:8000/healthz` → `{status:"ok", db:"ok", redis:"ok"}`.
  - `web` serves the SPA and proxies `/api` to `api`.
  - Media volume mounted at `MEDIA_ROOT`.

### T003 — FastAPI app skeleton
- **Dep:** T002
- **Touches:** `backend/app/main.py`, `config.py`, `api/deps.py`, `api/health.py`, logging setup
- **AC:**
  - App factory with settings via `pydantic-settings` (env vars from `plan.md` §8).
  - `/healthz` and `/api/openapi.json` served.
  - Structured JSON logging with a per-request `request_id` middleware.
  - CORS configured for the dev SPA origin only.

### T004 — Database layer & migrations
- **Dep:** T003
- **Touches:** `backend/app/db/`, `backend/alembic/`, `alembic.ini`
- **AC:**
  - SQLAlchemy 2.x engine + session dependency; `Base` metadata.
  - Alembic initialised; `alembic upgrade head` runs clean against compose `postgres`.
  - A trivial `app_meta` table migration proves the pipeline.
  - Test fixture spins an isolated DB / transaction rollback per test.

### T005 — Frontend scaffold, theme & UI kit
- **Dep:** T002
- **Touches:** `frontend/src/theme/`, `tailwind.config.ts`, `frontend/src/components/`, `frontend/src/app/`
- **AC:**
  - Tailwind preset built from the token block in `ai_course_content_suite/*/code.html` + `academic_modernist/DESIGN.md` (colors, fonts, radius, spacing, elevation). Public Sans + Inter + Material Symbols loaded.
  - UI kit components implemented and Vitest-covered: `Button` (primary/secondary/student), `Card`, `Chip` (status variants: processing/ready/error/published/pending), `Input`, `Select`, `Modal`, `Toast`, `Tabs`, `SidebarNav`, `TopBar`, `ProgressBar`, `Skeleton`, `EmptyState`, `ErrorState`.
  - A `/styleguide` route renders every component in every state; visual matches the design system.
  - React Router with `/admin/*` (AdminLayout) and `/*` (StudentLayout) shells; TanStack Query + Zustand wired.

### T006 — CI pipeline
- **Dep:** T001–T005
- **Touches:** `.github/workflows/ci.yml`
- **AC:**
  - Jobs: `backend` (ruff, black --check, mypy, pytest), `frontend` (eslint, tsc, vitest, build).
  - `postgres` + `redis` service containers for backend tests.
  - CI green on the scaffold.

---

## Phase 1 — Auth & RBAC

### T007 — User model, hashing, admin bootstrap
- **Dep:** T004
- **Touches:** `backend/app/models/user.py`, `app/auth/hashing.py`, `app/cli.py`, migration
- **AC:**
  - `user` table per `PROJECT_FRAME.md` §8.1.
  - Argon2id hashing helpers; unit tests for hash/verify.
  - `python -m app.cli seed-admin --email --name` creates/updates an admin (password prompt); idempotent; refuses to create a second admin silently without `--email` uniqueness.
  - `seed-admin` covered by a test.

### T008 — Session infrastructure & student auth API
- **Dep:** T007
- **Touches:** `app/auth/sessions.py`, `app/api/student/auth.py`, `app/api/deps.py`
- **AC:**
  - Redis-backed opaque sessions; `sdp_student` cookie (`HttpOnly`, `Secure`, `SameSite=Lax`), TTL from config.
  - `POST /register`, `POST /login`, `POST /logout`, `GET /me` per `spec.md` §5.1.
  - Password strength rule enforced (422 on weak); duplicate email → 409.
  - `current_student` dependency; login rate-limited (Redis bucket) per IP + email.
  - Integration tests for each endpoint + rate-limit.

### T009 — Admin auth API (separate scope)
- **Dep:** T007, T008
- **Touches:** `app/api/admin/auth.py`, `app/api/deps.py`
- **AC:**
  - `sdp_admin` cookie, distinct name/TTL; `POST /login`, `POST /logout`, `GET /me`.
  - `current_admin` requires valid `sdp_admin` **and** `role==admin`; otherwise 401.
  - No register endpoint exists under `/api/admin/*`.
  - A student's `sdp_student` cookie on `/api/admin/auth/me` → 401 (test).

### T010 — RBAC guard + CSRF + security tests
- **Dep:** T009
- **Touches:** `app/api/deps.py`, `app/auth/csrf.py`, `backend/tests/integration/test_rbac.py`
- **AC:**
  - Every `/api/admin/*` router depends on `current_admin`.
  - CSRF double-submit token required on all non-GET; missing/invalid → 403.
  - Parametrised test enumerates all registered `/api/admin/*` routes and asserts 401 for anonymous and 403/401 for a student session (US-N1).
  - Security headers middleware (`X-Content-Type-Options`, `Referrer-Policy`, `X-Frame-Options`, HSTS in prod).

### T011 — Student login & register pages
- **Dep:** T005, T008
- **Touches:** `frontend/src/student/auth/`
- **AC:**
  - `/login`, `/register` per `spec.md` §3.7; BTN-SL1..SL4 wired.
  - Client validation mirrors server; server errors surfaced inline.
  - On success, `sdp_student` set and redirect to `/catalog`.
  - Component tests + a Playwright happy-path.

### T012 — Admin login page & route protection
- **Dep:** T005, T009
- **Touches:** `frontend/src/admin/auth/`, `frontend/src/app/guards.tsx`
- **AC:**
  - `/admin/login` per `spec.md` §3.1; BTN-AL1 (+ AL2 if O6).
  - `/admin/*` without a valid admin session → redirect to `/admin/login`.
  - A logged-in student visiting `/admin/anything` gets the **student** 404, no admin chrome (US-N3).
  - Playwright: admin login → `/admin/ingestion`; student blocked from `/admin/*`.

---

## Phase 2 — Domain model & content pipeline core

### T013 — Core domain models & migrations
- **Dep:** T004
- **Touches:** `app/models/{course,module,artifact,artifact_version,media_file,generation_job,prompt_template,audit_log}.py`, `app/models/progress*.py`, migration
- **AC:**
  - All entities & constraints from `PROJECT_FRAME.md` §8 (unique `(module_id,type)`, unique active `prompt_template` per type, unique `(user_id,artifact_id)` progress, etc.).
  - Status enums for artifact/module/course; derived-status helpers with unit tests covering the transition table.
  - `alembic upgrade head` + `downgrade` clean.

### T014 — Prompt templates: seed files + Settings API
- **Dep:** T013, T010
- **Touches:** `app/prompts/{slide_deck,flashcards,quiz,report,infographic,audio_overview}.md`, `app/api/admin/prompts.py`, `app/services/prompts.py`
- **AC:**
  - Six placeholder `.md` files with clear `TODO(owner)` bodies.
  - First-run seeder inserts one active `prompt_template` per type from the files (idempotent).
  - `GET /api/admin/prompts`, `GET/PUT /api/admin/prompts/{type}`, `POST .../restore-default` per `spec.md` §5.4; PUT creates a new active version, deactivates the prior.
  - `get_active_body(type)` used by the orchestrator; unit + integration tests.

### T015 — ContentProvider interface + FixtureProvider
- **Dep:** T013
- **Touches:** `app/pipeline/provider.py`, `app/pipeline/fixture.py`, `backend/tests/fixtures/`
- **AC:**
  - `ContentProvider` protocol per `plan.md` §4.2.
  - `FixtureProvider` returns deterministic canned raw artifacts (captured NotebookLM-style HTML) for all six types + a sample `.mp3` and infographic structure, keyed by a fixture id.
  - `CONTENT_PROVIDER` env selects the provider via a factory.
  - Unit tests exercise every method of `FixtureProvider`.

### T015a — SPIKE: infographic image retrieval (Open Item O1)
- **Dep:** T015
- **OI:** O1
- **Touches:** `docs/PROJECT_FRAME.md` §17 (resolve), `docs/plan.md` §5 (adjust), spike notes in `docs/spikes/O1-infographic.md`
- **AC:**
  - Determine from the pinned MCP's `docs/TOOLS.md` + source whether the infographic artifact's rendered image is retrievable (and how).
  - Write the finding + decision to `docs/spikes/O1-infographic.md`; update O1 status to Resolved.
  - If not retrievable → confirm the "render our own SVG/PNG from structure" path (D15) is viable with a proof-of-concept.

### T015b — SPIKE: audio mp3 + transcript retrieval (Open Item O2)
- **Dep:** T015
- **OI:** O2
- **Touches:** `docs/spikes/O2-audio.md`, `docs/PROJECT_FRAME.md` §17, `docs/spec.md` §3.15
- **AC:**
  - Determine how (or whether) the audio `.mp3` and a transcript can be obtained via the MCP at the pinned version.
  - Record findings + a recommendation in `docs/spikes/O2-audio.md`.
  - **Escalate to owner** with concrete options if no download path exists; do not proceed to T018's audio path until O2 is Resolved or explicitly de-scoped.

### T016 — NotebookLmMcpProvider + MCP container
- **Dep:** T015, T015a, T015b, T002
- **Touches:** `app/pipeline/notebooklm_mcp.py`, `mcp/Dockerfile`, `mcp/README.md`
- **AC:**
  - `mcp` container runs the pinned `notebooklm-mcp-server`; `auth.json` on a mounted volume; `mcp/README.md` documents `npx notebooklm-mcp-server auth` and the **DBSC** limitation (O3).
  - `NotebookLmMcpProvider` implements every `ContentProvider` method against verified MCP tools (`plan.md` §4.2 mapping); `fetch_binary` per T015a/T015b outcome.
  - `health()` and `refresh_auth()` work; Redis lock `mcp:session` serializes calls.
  - Contract tests run against `FixtureProvider`; a manual checklist documents live verification steps (not in CI).

### T017 — Storage service
- **Dep:** T013
- **Touches:** `app/storage/`
- **AC:**
  - `put(key, bytes, mime) -> MediaFile`, `open(key)`, `delete(key)`, `url_for(key)`.
  - Key scheme: `courses/{course_id}/modules/{module_id}/artifacts/{artifact_id}/v{rev}/{kind}[.{page}].{ext}`.
  - Writes under `MEDIA_ROOT`; checksum + size recorded; path traversal rejected.
  - GC helper (`beat` task) removes media for superseded, non-published, non-current versions beyond a keep-N config; unit-tested; never touches published/current.

### T018 — Renderer: slides → pptx/png/pdf
- **Dep:** T013, T017
- **OI:** — (independent of O1/O2)
- **Touches:** `app/render/slides_pptx.py`, tests + golden files
- **AC:**
  - `render(content_json) -> {pptx, deck_pdf, slide_png[]}` using python-pptx + `soffice` + `pdftoppm`.
  - Deck uses an Academic-Modernist master (title, bullets, notes).
  - Deterministic output for a golden `content_json`; page count matches slide count.
  - `soffice` availability checked at startup; clear error if missing.

### T019 — Renderer: infographic → svg/png
- **Dep:** T013, T017, T015a
- **OI:** O1 (must be Resolved)
- **Touches:** `app/render/infographic.py`, tests
- **AC:**
  - `render(content_json) -> {infographic_svg, infographic_png}` via Mermaid CLI or Graphviz per `diagram_kind`.
  - If O1 resolved "image retrievable", also accept and store the MCP image as `infographic_png` with our SVG as fallback.
  - Golden-file test; invalid diagram source → `RenderError` with reason.

### T020 — Renderer: report → sanitized html + pdf
- **Dep:** T013, T017
- **Touches:** `app/render/report_pdf.py`, `app/pipeline/parsers/_sanitize.py`, tests
- **AC:**
  - HTML sanitiser with a strict allowlist (no `script`, `iframe`, `object`, event attrs, remote `src` except configured image host); unit tests with hostile inputs.
  - `render(content_json) -> {report_pdf}` via WeasyPrint; on-screen HTML == PDF content.
  - Read-time estimate + Key Takeaways + sections extracted.

### T021 — Parsers: MCP HTML → content_json (+ validation)
- **Dep:** T015, T016
- **Touches:** `app/pipeline/parsers/{slide_deck,flashcards,quiz,report,infographic,audio_overview}.py`, `app/schemas/content.py`, tests + captured HTML fixtures
- **AC:**
  - One parser per type producing the shapes in `PROJECT_FRAME.md` §8.2; Pydantic-validated.
  - Quiz: rejects unless every question has exactly 4 options and a marked answer → raises `ArtifactParseError("…")`.
  - Flashcards: front/back required; category optional.
  - Each parser has ≥3 fixture tests incl. a malformed input asserting a helpful error.

### T022 — Celery orchestration: generate module / artifact
- **Dep:** T014, T016, T017, T018, T019, T020, T021
- **Touches:** `app/tasks/celery_app.py`, `app/pipeline/orchestrator.py`, `app/tasks/generation.py`, tests
- **AC:**
  - `generate_module(module_id, types)` creates the notebook, adds the source, fans out capped `generate_artifact` jobs.
  - `generate_artifact` runs the pipeline (`plan.md` §4.3): build `focus_prompt` (BR6), generate→poll→fetch→parse→render→persist `ArtifactVersion`+`MediaFile`, set `ready`.
  - Failures set `Artifact.status=error` + `last_error`, job `failed`; siblings unaffected.
  - Timeouts per type (config) → `failed` with timeout reason.
  - Transient MCP errors retried with backoff (bounded).
  - Integration test end-to-end under `FixtureProvider`: module → 6 `ready` artifacts with media.

### T023 — Redo single artifact
- **Dep:** T022
- **Touches:** `app/pipeline/orchestrator.py`, `app/tasks/generation.py`, `app/api/admin/staging.py` (endpoint), tests
- **AC:**
  - `redo_artifact(artifact_id, note)` regenerates only that artifact; new `ArtifactVersion` with `revision+1`, `redo_note`, and the `focus_prompt` incl. the note.
  - `published_version_id` unchanged; sibling artifacts unchanged (asserted).
  - `POST /api/admin/artifacts/{id}/redo {note?}` → 202 with job; `POST .../retry` for `error` state.
  - Tests: redo on `ready` and on `published`; both leave published content live.

### T024 — Job status API
- **Dep:** T022
- **Touches:** `app/api/admin/jobs.py`, tests
- **AC:**
  - `GET /api/admin/jobs/{id}`, `GET /api/admin/modules/{id}/jobs`, and `GET /api/admin/modules/{id}/staging` include per-artifact `job.state`.
  - Payload shape supports the UI polling contract (`spec.md` §3.3).
  - Integration tests for queued/running/succeeded/failed.

---

## Phase 3 — Admin app

### T025 — Ingestion Portal (A1)
- **Dep:** T012, T014, T022
- **Touches:** `app/api/admin/courses.py`, `app/api/admin/pipeline.py`, `frontend/src/admin/ingestion/`
- **AC:**
  - Form + validation per `spec.md` §3.2; supported-host check for the URL.
  - New-course and existing-course paths both create a module + selected artifacts + `generate_module` job, then redirect to staging.
  - Recent Pipeline table + View All (`/admin/pipeline`, paginated/filterable).
  - MCP badge from `/api/admin/mcp/status`, 30s refresh; disconnected → warning banner, submit still queues.
  - BTN-IG1..IG11 wired; Playwright covers create→redirect and the badge states.

### T026 — Staging Review dashboard (A2) + Inspect (A4)
- **Dep:** T023, T024, T025
- **Touches:** `app/api/admin/staging.py`, `app/api/admin/artifacts.py`, `frontend/src/admin/staging/`, `frontend/src/admin/inspect/`
- **AC:**
  - Six artifact cards with correct previews per type, status chips, Generating spinner (disabled buttons), Error + Retry.
  - Redo modal with optional instruction; submit → card to Generating; polling every 2–3s until resolved.
  - Inspect view read-only for all six types incl. metadata panel + version-history dropdown (no restore).
  - Type downloads (mp3/pptx/png/pdf) stream from `/api/media/*`.
  - BTN-SR1..SR12, BTN-AI1..AI2 wired; Playwright: redo one artifact, assert only it regenerates and a new version appears.

### T027 — Publish flow
- **Dep:** T026
- **Touches:** `app/api/admin/publish.py`, `frontend/src/admin/staging/publish*`
- **AC:**
  - `POST /api/admin/modules/{id}/publish` and `POST /api/admin/courses/{id}/publish` implement BR2–BR5; return `{published:[...], skipped:[...]}`.
  - Confirmation modals list exactly what will publish and what is skipped and why.
  - Derived module/course status recomputed and shown (incl. Partially Published).
  - Publishing never alters `processing` artifacts or the previously published version until replaced.
  - Tests for 6/6, partial, and re-publish-after-redo; Playwright happy path.

### T028 — Course Editor (A3)
- **Dep:** T025
- **Touches:** `app/api/admin/courses.py` (modules sub-resource), `frontend/src/admin/editor/`
- **AC:**
  - Course list + course structure view per `spec.md` §3.5.
  - Add New Video Source (scoped ingestion), rename, reorder (persists `order_index`), re-run all, delete (cascade per BR9 with a strong confirm).
  - Per-artifact status tiles link to Inspect.
  - BTN-CE1..CE9 wired; tests for reorder persistence and cascade delete.

### T029 — Settings (A4)
- **Dep:** T014, T016
- **Touches:** `app/api/admin/settings*.py`, `frontend/src/admin/settings/`
- **AC:**
  - Generation Prompts tab: per-type editor, version display, Save (new version), Restore default.
  - NotebookLM tab: status, account email, last OK, Reload auth, re-auth instructions.
  - Audio tab: minimal voice/style options persisted and passed to `audio_overview_create`.
  - Users tab: list, Add admin, Deactivate (not self).
  - BTN-ST1..ST6 wired; test that a saved prompt is used by the next generation.

### T030 — Admin shell & notifications
- **Dep:** T012
- **Touches:** `frontend/src/admin/layout/`
- **AC:**
  - Persistent left nav + header (brand, MCP badge, notifications, avatar/logout) on every admin screen; active-route highlighting.
  - Notifications panel: polled list of recent job completions/failures with deep links to staging.
  - Responsive per the design system (dense 12-col).

---

## Phase 4 — Student app

### T031 — Catalog (S1)
- **Dep:** T011, T027
- **Touches:** `app/api/student/courses.py`, `frontend/src/student/catalog/`
- **AC:**
  - `GET /api/student/courses` returns published-only, with per-course `percent_complete` for the caller.
  - Category chips (distinct categories), search (title/description), compose as AND.
  - Course cards match `student_course_catalog_audio_portal/`: cover, duration, counts, progress bar, Start Learning → workspace at first incomplete module.
  - Empty state; BTN-CT1..CT7 wired; Playwright: filter + open course.

### T032 — Course workspace shell (S2)
- **Dep:** T031
- **Touches:** `app/api/student/courses.py` (detail), `app/api/student/modules.py`, `frontend/src/student/workspace/`
- **AC:**
  - Shell per all `student_workspace_*` designs: top bar (Course Overview, % complete, Back to Dashboard), left Module Explorer (Current Unit, module switcher, six artifact links).
  - Only published artifact types are offered; direct URL to an unavailable type shows a "not available" panel (no error).
  - Module order == admin `order_index`.
  - BTN-WS1..WS8 wired.

### T033 — Slides viewer (S3)
- **Dep:** T032
- **Touches:** `app/api/student/artifacts.py`, `frontend/src/student/workspace/slides/`
- **AC:**
  - PNG page viewer, Prev/Next (disabled at ends), "Slide N of M", Fullscreen, Instructor Notes per slide, Download .pptx.
  - Last-slide view marks `completed`; `slide_last_index` persisted + restored.
  - BTN-SD1..SD4; component + Playwright.

### T034 — Flashcards (S4)
- **Dep:** T032
- **Touches:** `app/api/student/artifacts.py`, `app/api/student/ratings.py`, `frontend/src/student/workspace/flashcards/`
- **AC:**
  - Flip on click/Space; category on front; Prev/Next; "N of M".
  - Hard/Good/Easy → `PUT .../flashcard-ratings/{cardIndex}`; selection persists and restores; next visit orders Hard-first.
  - Completing the deck marks `completed`.
  - BTN-FC1..FC6; tests incl. persistence across reload.

### T035 — Quiz (S5)
- **Dep:** T032
- **Touches:** `app/api/student/quiz.py`, `frontend/src/student/workspace/quiz/`
- **AC:**
  - Question nav, segmented progress, single-select A–D, Previous/Next, Submit (all answered).
  - `POST .../quiz-attempts` returns score + per-question correctness + stored explanation; results view renders them.
  - Retake creates a new attempt; history via `GET .../quiz-attempts`; best + latest surfaced.
  - Submitting marks `completed`.
  - BTN-QZ1..QZ6; tests for scoring math and attempt persistence.

### T036 — Infographic viewer (S6)
- **Dep:** T032, T019
- **Touches:** `frontend/src/student/workspace/infographic/`
- **AC:**
  - SVG in a zoom/pan viewport (clamped), Zoom in/out, Fullscreen, caption.
  - Download .png; Mark reviewed → `completed`.
  - BTN-IF1..IF5; component + Playwright.

### T037 — Report reading mode (S7)
- **Dep:** T032, T020
- **Touches:** `frontend/src/student/workspace/report/`
- **AC:**
  - Focus-mode layout: read time, title, hero, Key Takeaways callout, numbered sections from sanitized HTML.
  - Previous / Complete Module / Download .pdf (FAB).
  - Complete Module marks report `completed` **and** the module complete; catalog % updates immediately.
  - BTN-RP1..RP3; tests.

### T038 — Audio player (S8)
- **Dep:** T032, T015b
- **OI:** O2 (Resolved or de-scoped)
- **Touches:** `frontend/src/student/workspace/audio/`, `app/api/student/artifacts.py`
- **AC:**
  - Play/Pause, −10s/+10s, scrub with elapsed/total, speed cycle, volume, Transcript toggle (hidden if no transcript per O2), Next Lesson.
  - Position saved every ~5s + on pause (`audio_position_seconds`); resume within a few seconds; finishing marks `completed`.
  - Feeds My Listening.
  - BTN-AU1..AU8; tests for resume + speed/volume.

### T039 — Progress, My Listening, Achievements (S9)
- **Dep:** T033–T038
- **Touches:** `app/progress/`, `app/api/student/me.py`, `frontend/src/student/me/`
- **AC:**
  - `POST /api/student/artifacts/{id}/progress` upserts per-artifact state; course % recomputed per BR7 on every write.
  - `GET /api/student/me/progress|listening|achievements` per `spec.md` §3.16.
  - My Listening: audio % + Resume deep-link to position. Achievements: earned + locked (final set per O5) with criteria.
  - Values verified against real records in tests.

---

## Phase 5 — Hardening & delivery

### T040 — Access-control audit
- **Dep:** T027, T031, all student endpoints
- **Touches:** `backend/tests/integration/test_access_control.py`, `app/api/media.py`
- **AC:**
  - Automated proof of US-N1..N4: student/anon blocked from every `/api/admin/*`; student cannot fetch unpublished artifacts or their media via `/api/student/*` or `/api/media/*`.
  - Media endpoint access rules (published current version only for students) tested with hostile keys.
  - Admin SPA bundle not referenced by any student route (build-time check).

### T041 — States & design-fidelity polish
- **Dep:** T025–T039
- **Touches:** both apps
- **AC:**
  - Loading skeletons, empty states, error states on every screen, matching the design language.
  - Side-by-side review against each `screen.png`; deviations fixed or logged with owner sign-off.
  - Keyboard nav + visible focus on all controls; alt text on generated images; audio transcript present when available.

### T042 — Test suites & Button Inventory
- **Dep:** T040, T041
- **Touches:** `backend/tests/`, `frontend/src/e2e/`
- **AC:**
  - Backend coverage thresholds met for parsers, renderers, RBAC, publish, progress.
  - Playwright: full admin flow (ingest → 6 generated → redo one → publish module → publish course) and full student flow (register → catalog → consume all six → progress) under `FixtureProvider`.
  - Every row of `spec.md` §6 Button Inventory has a passing assertion; a generated report lists them green.

### T043 — Observability
- **Dep:** T022
- **Touches:** `app/main.py`, `app/tasks/`, `frontend/src/lib/telemetry.ts`
- **AC:**
  - Request id in all API logs; job id in all worker logs.
  - Sentry (BE + FE) behind `SENTRY_DSN`.
  - `beat` MCP healthcheck metric + `/api/admin/mcp/status`; job success/failure counters.
  - A basic `/admin` "System health" strip surfaces MCP + worker status.

### T044 — Seed & demo data
- **Dep:** T022
- **Touches:** `app/cli.py` (`seed-demo`), `backend/tests/fixtures/`
- **AC:**
  - `python -m app.cli seed-demo` builds a demo admin, 2 courses, several modules with all six artifacts generated via `FixtureProvider`, some published, and a demo student with partial progress.
  - Lets a reviewer exercise both apps immediately with no Google session.

### T045 — Infra skeleton & deploy runbook
- **Dep:** T002
- **Touches:** `infra/terraform/`, `infra/deploy-runbook.md`, prod `Dockerfile`s
- **AC:**
  - Terraform skeleton for AWS: ECR, ECS Fargate services (`web`,`api`,`worker`,`beat`,`mcp`), RDS, ElastiCache, EFS access points (media + mcp auth), ALB, Secrets Manager, CloudWatch log groups/alarms. `terraform validate` passes; not applied.
  - `deploy-runbook.md`: build/push, migrate, first admin, MCP auth + DBSC caveat, backups (RDS snapshots + EFS), restore, rollback. GCP mapping section.

### T046 — Documentation
- **Dep:** T042
- **Touches:** `docs/api.md` (or generated), `docs/admin-guide.md`, `docs/student-guide.md`, `docs/operations.md`
- **AC:**
  - OpenAPI exported/published; endpoint reference readable.
  - Admin guide (ingest, review, redo, publish, prompts, MCP re-auth) and student guide (catalog, workspace, each artifact) with screenshots.
  - Operations runbook consolidates MCP re-auth, DBSC, backups, GC, incident steps.

### T047 — Acceptance pass
- **Dep:** T040–T046
- **Touches:** `docs/task-tracker.md`, `docs/acceptance-report.md`
- **AC:**
  - Walk every item in `PROJECT_FRAME.md` §15 and `spec.md` §7; record pass/fail with evidence in `acceptance-report.md`.
  - All Open Items O1–O7 Resolved or owner-signed-off as de-scoped.
  - `task-tracker.md` shows every task Done; CI green; `seed-demo` reviewed end-to-end.

---

## Dependency graph (summary)

```
T001→T002→{T003→T004, T005}→T006
T004→T007→{T008→T009→T010, }
T005→{T011(+T008), T012(+T009)}
T004→T013→{T014(+T010), T015→{T015a,T015b}→T016(+T002), T017}
T013,T017→T018 ; T013,T017,T015a→T019 ; T013,T017→T020
T015,T016→T021
{T014,T016,T017,T018,T019,T020,T021}→T022→{T023,T024}
{T012,T014,T022}→T025→{T026(+T023,T024)→T027, T028} ; {T014,T016}→T029 ; T012→T030
{T011,T027}→T031→T032→{T033,T034,T035,T036(+T019),T037(+T020),T038(+T015b)}→T039
→T040→T041→T042→{T043,T044,T045,T046}→T047
```
