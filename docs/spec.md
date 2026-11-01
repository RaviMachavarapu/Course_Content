# Functional Specification — Shikshak Dp AI Course Content Suite

**Version:** 1.0 (draft for review)
**Companion docs:** `PROJECT_FRAME.md` (context), `constitution.md` (rules),
`plan.md` (how), `tasks.md` (order).

This spec defines **what the system does** — observable behaviour, per screen,
with acceptance criteria. It is stack-agnostic; `plan.md` binds it to concrete
technology.

---

## 1. Actors

- **Admin** — the product owner and any additional admin accounts. Single trust
  level (no admin sub-roles in v1).
- **Student** — a self-registered learner.
- **System / Worker** — asynchronous generation and rendering.
- **NotebookLM (via MCP)** — external content generator.

---

## 2. User stories

### Admin
- **US-A1** As an admin I log in through a dedicated admin login page so that my
  access is separate from students'.
- **US-A2** As an admin I paste a source link and choose which of the six
  artifact types to generate, creating a new course or adding a module to an
  existing one.
- **US-A3** As an admin I watch generation progress per artifact without the page
  blocking.
- **US-A4** As an admin I review each generated artifact privately before any
  student can see it.
- **US-A5** As an admin I click **Redo** on a single artifact I don't like,
  optionally typing an instruction, and only that artifact regenerates.
- **US-A6** As an admin I **Publish** a module, or **Publish Complete Course**,
  and only the artifacts that are ready go live.
- **US-A7** As an admin I edit the system prompt for each artifact type in
  Settings, and future generations use the new text.
- **US-A8** As an admin I see whether the NotebookLM connection is healthy and
  can trigger a re-auth reload.
- **US-A9** As an admin I manage the course/module structure (rename, reorder,
  delete, re-run) from a Course Editor.
- **US-A10** As an admin I can create another admin account (no self-signup).

### Student
- **US-S1** As a visitor I register and log in through the student login page.
- **US-S2** As a student I browse all published courses, filter by category, and
  search.
- **US-S3** As a student I open a course and navigate its modules and the six
  artifact types.
- **US-S4** As a student I step through slides with speaker notes and download
  the deck.
- **US-S5** As a student I flip flashcards and rate each one Hard/Good/Easy.
- **US-S6** As a student I take a quiz, submit, and see my score with
  explanations; I can retake it.
- **US-S7** As a student I read the report in focus mode, mark the module
  complete, and download the PDF.
- **US-S8** As a student I zoom and pan the infographic and download the image.
- **US-S9** As a student I play the audio overview with scrub, ±10s, speed, and
  a transcript, and it resumes where I left off.
- **US-S10** As a student I see my progress reflected in the catalog, My
  Listening, and Achievements.

### Negative / security
- **US-N1** A student session on any `/api/admin/*` route gets `403`.
- **US-N2** An anonymous request for an unpublished artifact or its media gets
  `404`/`403` and no content.
- **US-N3** The admin SPA is not discoverable from the student app.
- **US-N4** A Redo or failed regeneration never removes or alters the currently
  published version, nor any sibling artifact.

---

## 3. Screen specifications

Notation: **[BTN-x]** marks a control tracked in the Button Inventory (§6).

### 3.1 Admin — Login (`/admin/login`)
- Fields: email, password. **[BTN-AL1] Sign in**.
- On success: set `sdp_admin` session cookie, redirect to `/admin/ingestion`.
- On failure: inline error "Invalid email or password." Rate-limited after N
  attempts (config), with backoff messaging.
- No "register" link. A **[BTN-AL2] Forgot password** link if O6 resolves to
  "reset enabled".
- Acceptance:
  - Valid admin creds → lands on Ingestion.
  - Student creds → same "Invalid email or password" (no role disclosure).
  - Visiting `/admin/*` without a valid admin cookie → redirect to `/admin/login`.

### 3.2 Admin — Ingestion Portal (`/admin/ingestion`)
Layout per `admin_ingestion_portal/`.
- Header: brand, **NotebookLM MCP: Connected|Disconnected** badge (from
  `/api/admin/mcp/status`, refreshed on load + every 30s), settings icon
  **[BTN-IG7]**, notifications **[BTN-IG8]**, avatar menu **[BTN-IG9]** (Logout).
- Left nav: **[BTN-IG1] New Artifact** (scrolls to / focuses the form),
  **[BTN-IG2] Ingestion**, **[BTN-IG3] Review**, **[BTN-IG4] Editor**,
  **[BTN-IG5] Settings**.
- **Create New AI Course Module** form:
  - **Source URL** — required, validated for URL shape and supported host
    (`youtube.com`/`youtu.be`, generic `http(s)`, `drive.google.com`, direct
    `.pdf`). Invalid → inline message, submit disabled.
  - **Target** — radio: *New course* (title, description, category [free text,
    O7], cover image upload optional) or *Existing course* (searchable select) +
    **Module title** (required).
  - **Artifacts to Generate** — six checkboxes, all checked by default; at least
    one required.
  - **[BTN-IG6] Generate Course Material** — disabled until valid. On click:
    `POST /api/admin/courses/{id}/modules` (creating the course first if new),
    which creates the Module and one Artifact per checked type (`queued`), starts
    a `generate_module` job, then redirects to
    `/admin/modules/{moduleId}/staging`.
- **Recent Pipeline** table (latest 5): Source Title/URL, Date, six status dots
  (colour per artifact status), Global Status chip, **[BTN-IG10] Open Staging**
  per row. **[BTN-IG11] View All** → `/admin/pipeline` (paginated, filter by
  status, search by title/URL).
- Acceptance:
  - Submitting a valid form creates exactly one module with the selected
    artifacts and redirects to its staging page.
  - Unchecking all artifact types disables submit.
  - The new module appears in Recent Pipeline with status **Processing** and dots
    reflecting per-artifact state.
  - Badge shows **Disconnected** when `/api/admin/mcp/status` reports unhealthy;
    submitting is still allowed (jobs queue and will run when healthy) but a
    warning banner explains the delay.

### 3.3 Admin — Staging Review (`/admin/modules/{id}/staging`)
Layout per `admin_staging_review_dashboard/`.
- Header: **[BTN-SR1] Back to Ingestion**; module title; **Status** chip
  (Processing / Pending Review / Partially Published / Published / Error);
  **[BTN-SR2] Publish Complete Course** (green) — enabled when the course has ≥1
  `ready` artifact; opens a confirmation modal listing exactly which artifacts
  will publish and which are skipped (not ready).
- **[BTN-SR3] Publish Module** — publishes this module's `ready` artifacts;
  confirmation modal as above, scoped to the module.
- Six artifact cards (Slide Deck, Interactive Quiz, Study Flashcards, Audio
  Overview, Concept Infographic, Executive Report). Per card:
  - Type-appropriate preview (rendered from the current version).
  - Status chip: **READY** / **Generating…** (spinner; buttons disabled) /
    **Error** (message + **[BTN-SR6] Retry**).
  - **[BTN-SR4] Redo _[Type]_** → modal:
    - Optional multi-line **Instruction** field ("What should change?").
    - **[BTN-SR7] Start regeneration** / **[BTN-SR8] Cancel**.
    - On confirm: `POST /api/admin/artifacts/{id}/redo` with `{ note }`; card
      switches to **Generating…**; polling begins.
  - **[BTN-SR5] Inspect** → `/admin/artifacts/{id}` read-only viewer.
  - Type-specific download when a version exists: **[BTN-SR9]** Audio `.mp3`,
    **[BTN-SR10]** Slides `.pptx`, **[BTN-SR11]** Infographic `.png`,
    **[BTN-SR12]** Report `.pdf`. (Audio from NotebookLM is `.m4a`.)
  - **Outline review** (slide deck generated with *Review slide outline* on):
    NotebookLM drafts an outline and waits. The card shows the outline,
    a feedback box with **[BTN-SR14] Send feedback** (NotebookLM revises the
    outline) and **[BTN-SR15] Proceed** (NotebookLM builds the deck):
    `POST /api/admin/artifacts/{id}/outline/feedback` `{ feedback }` /
    `POST /api/admin/artifacts/{id}/outline/proceed`. Owner decision 2026-10-22.
- While any card is `queued`/`processing`, poll
  `GET /api/admin/modules/{id}/staging` every 2–3s; stop when all resolved.
- Acceptance:
  - Redo on card X sets only X to Generating; cards Y/Z unchanged; a new
    `ArtifactVersion` is created for X with `redo_note` stored.
  - Publish Module with 4/6 ready → those 4 become `published`, module status
    **Partially Published**, the modal disclosed exactly that.
  - Publishing does not change any artifact still `processing`.
  - Redoing a `published` artifact → new version `ready`; the student-visible
    content is still the old version until re-published.
  - Error card shows the backend's reason string; Retry re-enqueues.

### 3.4 Admin — Artifact Inspect (`/admin/artifacts/{id}`)
- Read-only render of the current version, identical in content to the student
  view for that type (slides carousel + notes, flashcard list, quiz with answers
  marked, report HTML, infographic SVG, audio player + transcript).
- Metadata panel: version/revision number, created-at, job id, prompt template
  version used, `focus_prompt` used, redo note (if any), NotebookLM notebook /
  artifact ids.
- **[BTN-AI1] Version history** dropdown — list revisions; selecting one renders
  that older version read-only (no restore in v1).
- **[BTN-AI2] Back to staging**.
- Acceptance: no editing controls exist; switching versions changes only the
  preview; downloads reflect the selected version.

### 3.5 Admin — Course Editor (`/admin/editor`, `/admin/editor/{courseId}`)
Layout per `admin_course_content_architecture/`.
- `/admin/editor` — course list (title, module count, status, updated). Click →
  `/admin/editor/{courseId}`.
- Course view: breadcrumb **Course Editor › Structure**; course title;
  **[BTN-CE1] Add New Video Source** → ingestion form pre-scoped to this course.
- Ordered module rows: index + title, source URL + duration (O4), status chip,
  **[BTN-CE2] kebab menu**: **[BTN-CE3] Open staging**, **[BTN-CE4] Rename**,
  **[BTN-CE5] Move up** / **[BTN-CE6] Move down**, **[BTN-CE7] Re-run all**,
  **[BTN-CE8] Delete** (confirm; blocks if published — must unpublish first, or
  confirm cascade per O-follow-up; default: allow delete with a strong confirm
  that also removes student-visible content).
- Under each row: six artifact tiles with per-artifact status; **[BTN-CE9]** tile
  click → that artifact's Inspect view.
- Acceptance:
  - Reorder persists `order_index` and reflects in the student Module Explorer
    order.
  - Delete removes the module, its artifacts, versions, media, and any published
    visibility; a confirm dialog states this.
  - Re-run all enqueues a fresh `generate_module` (new versions; old ones remain
    in history; published stay live until republish).

### 3.6 Admin — Settings (`/admin/settings`)
- Tabs: **Generation Prompts**, **NotebookLM**, **Audio**, **Users**.
- **Generation Prompts**: one card per artifact type — current body (textarea),
  version number, last edited by/at. **[BTN-ST1] Save** (creates a new active
  `prompt_template` version), **[BTN-ST2] Restore default** (confirm).
- **NotebookLM**: connection status, account email (read-only), last successful
  call time, **[BTN-ST3] Reload auth** (`POST /api/admin/mcp/refresh-auth`),
  copyable re-auth instructions (`npx notebooklm-mcp-server auth`).
- **Audio**: default voice/style params passed to `audio_overview_create`
  (minimal set), **[BTN-ST4] Save**.
- **Users**: admin list; **[BTN-ST5] Add admin** (email, name, temp password or
  invite per O6); **[BTN-ST6] Deactivate** per row (cannot deactivate self).
- Acceptance:
  - Saving a prompt makes the next generation/redo use the new body; existing
    versions record the version they used.
  - Restore default reverts the active body to the seeded placeholder and bumps
    the version.

### 3.7 Student — Login & Register (`/login`, `/register`)
- **Register**: display name, email, password (strength rule), confirm.
  **[BTN-SL1] Create account** → on success, auto-login (`sdp_student` cookie),
  redirect to `/catalog`. Duplicate email → inline error.
- **Login**: email, password. **[BTN-SL2] Sign in** → `/catalog`.
  **[BTN-SL3] Forgot password** (O6). Link **[BTN-SL4] Create account**.
- Acceptance:
  - A student account can never authenticate against `/admin/*`.
  - Password reset (if enabled) emails a tokenised link (mailhog in dev).

### 3.8 Student — Catalog (`/catalog`)
Layout per `student_course_catalog_audio_portal/`.
- Header: brand, **[BTN-CT1] search** (filters cards by title/description as you
  type), nav **[BTN-CT2] Catalog** / **[BTN-CT3] My Listening** / **[BTN-CT4]
  Achievements**, **[BTN-CT5] profile menu** (Logout).
- **[BTN-CT6] Category chips**: "All" + each distinct category; selecting filters
  the grid.
- Course cards: cover, total audio duration, title, description, artifact counts,
  **X% Complete** + bar (from `/api/student/me/progress`), **[BTN-CT7] Start
  Learning** → `/learn/{courseSlug}` (opens first/next incomplete module).
- Only `published` courses appear. Empty state when none.
- Acceptance:
  - A course with zero published modules does not appear.
  - Percent complete matches the student's actual progress records.
  - Search + category filter compose (AND).

### 3.9 Student — Course Workspace shell (`/learn/{courseSlug}`)
Shared by all `student_workspace_*` screens.
- Top bar: **Individual Course** label, **[BTN-WS1] Course Overview** link,
  **X% Complete**, **[BTN-WS2] Back to Dashboard** → `/catalog`.
- Left **Module Explorer**: "Current: Unit N"; a module switcher; then six items
  **[BTN-WS3..8]** Audio / Slides / Flashcards / Quiz / Infographic / Report.
  Items for artifacts not published are hidden (default, O-follow-up) — never
  shown as broken.
- Selecting `{module, type}` routes to `/learn/{courseSlug}/{moduleIndex}/{type}`
  and loads `GET /api/student/artifacts/{id}` (published version only).
- Acceptance:
  - Navigating to a `type` with no published artifact is not offered; a direct
    URL to it returns the workspace with a "not available" panel, no error.
  - The module order matches the admin's `order_index`.

### 3.10 Student — Slides (`/learn/.../slide_deck`)
Layout per `student_workspace_slide_deck_updated/`.
- Slide image viewer; **[BTN-SD1] ‹ Prev**, **[BTN-SD2] Next ›**, "Slide N of M",
  **[BTN-SD3] Fullscreen**.
- **Instructor Notes** panel: the current slide's `notes` + tags.
- **[BTN-SD4] Download .pptx**.
- Progress: viewing the last slide marks the artifact `completed`; `slide_last_index`
  persisted for resume.
- Acceptance: navigation wraps are disabled at ends; fullscreen toggles; notes
  update per slide; download streams the stored `.pptx`.

### 3.11 Student — Flashcards (`/learn/.../flashcards`)
Layout per `student_workspace_flashcards_updated/`.
- Flip card on **[BTN-FC1] click / Space**; category tag on front; **[BTN-FC2]
  Prev**, **[BTN-FC3] Next**, "N of M".
- **[BTN-FC4] Hard**, **[BTN-FC5] Good**, **[BTN-FC6] Easy** — `PUT
  .../flashcard-ratings/{cardIndex}`; selected state persists and is restored on
  return; ratings influence card order (Hard first) on next visit.
- Progress: rating/viewing all cards marks `completed`.
- Acceptance: rating persists across reload; deck order reflects prior ratings;
  keyboard: Space flips, arrows navigate.

### 3.12 Student — Quiz (`/learn/.../quiz`)
Layout per `student_workspace_interactive_quiz_updated/`.
- "Question N of M", segmented progress; question; four options A–D (single
  select) **[BTN-QZ1]**; **[BTN-QZ2] Previous**, **[BTN-QZ3] Next Question**;
  **[BTN-QZ4] Submit** on the last question (enabled when all answered, or allow
  partial with a warning — default: require all).
- On submit: `POST .../quiz-attempts`; results view — score %, correct count,
  per-question right/wrong with the stored `explanation`. **[BTN-QZ5] Retake**
  resets to Q1 (new attempt row). **[BTN-QZ6] Back to module**.
- Progress: submitting marks `completed`; best and latest score stored.
- Acceptance: answers are not revealed before submit; explanations shown after;
  every attempt is persisted and retrievable; retake creates a new attempt.

### 3.13 Student — Infographic (`/learn/.../infographic`)
Layout per `student_workspace_high_fidelity_infographic/`.
- SVG diagram in a zoom/pan viewport; **[BTN-IF1] Zoom in**, **[BTN-IF2] Zoom
  out**, **[BTN-IF3] Fullscreen**; caption text below.
- **[BTN-IF4] Download .png**.
- Progress: opening marks `viewed`; a "Mark as reviewed" affordance or scroll-to-
  caption marks `completed` (default: explicit **[BTN-IF5] Mark reviewed**).
- Acceptance: zoom clamped to sane min/max; pan within bounds; PNG download
  streams the stored file.

### 3.14 Student — Report (`/learn/.../report`)
Layout per `student_workspace_executive_report_updated/`.
- **Reading Focus Mode** header, estimated read time, title, hero image, **Key
  Takeaways** callout, numbered sections (sanitized HTML).
- **[BTN-RP1] Previous**, **[BTN-RP2] Complete Module**, **[BTN-RP3] Download
  .pdf** (FAB).
- **Complete Module** → marks the report `completed` **and** the module
  complete; recomputes course %.
- Acceptance: HTML is sanitized (no scripts/remote objects); Complete Module
  updates catalog % immediately; PDF matches on-screen content.

### 3.15 Student — Audio (`/learn/.../audio_overview`)
Layout per `student_workspace_audio_experience/`.
- Big **[BTN-AU1] Play/Pause**; **[BTN-AU2] −10s**, **[BTN-AU3] +10s**;
  **[BTN-AU4] scrub bar** with elapsed/total; **[BTN-AU5] speed** cycle
  (1x/1.25x/1.5x/2x); **[BTN-AU6] volume**; **[BTN-AU7] Transcript** toggle
  (panel with time-synced lines, O2); **[BTN-AU8] Next Lesson**.
- Playback position saved every ~5s and on pause to `audio_position_seconds`;
  restored on return. Finishing marks `completed`. Feeds **My Listening**.
- Acceptance: resume returns to within a few seconds of last position; speed and
  volume changes take effect immediately; transcript line highlights with
  playback (if transcript available; otherwise the toggle is hidden).

### 3.16 Student — My Listening (`/me/listening`) & Achievements (`/me/achievements`)
- **My Listening**: list of courses/modules with audio, showing % listened and a
  **[BTN-ML1] Resume** button that deep-links to the audio view at the saved
  position.
- **Achievements**: earned badges — course completed, quiz score ≥ threshold,
  flashcard streak (final set per O5). Locked badges shown greyed with criteria.
- Acceptance: values derive from real progress records; Resume lands at the
  correct module + position.

---

## 4. Business rules

- **BR1** A Module always has exactly six Artifact rows (one per type). Types not
  chosen at creation start as `draft` and can be generated later from the Editor.
- **BR2** An Artifact can be published only from `ready`.
- **BR3** Publishing sets `published_version_id = current_version_id` and
  `status = published`. The course/module derived status recomputes.
- **BR4** "Publish Complete Course" publishes every `ready` artifact across all
  the course's modules in one transaction; `processing`/`error`/`draft`
  artifacts are skipped and reported.
- **BR5** Redo/regeneration never mutates `published_version_id`.
- **BR6** A generation run's `focus_prompt` = active prompt template body, plus
  `"\n\n[Regeneration instruction]: " + note` when a redo note is present.
- **BR7** Course % complete = completed artifacts across published modules ÷
  total published artifacts in the course (rounded). Recomputed on each progress
  write.
- **BR8** Only `published` courses/modules/artifacts are returned by any
  `/api/student/*` endpoint or `/api/media/*` for a student.
- **BR9** Deleting a module cascades to its artifacts, versions, media, progress,
  quiz attempts, and flashcard ratings, and removes student visibility.
- **BR10** MCP calls are serialized; module fan-out respects a max in-flight cap
  (config, default 2).
- **BR11** A generation job that exceeds its timeout (config, audio longer) is
  marked `failed` with a timeout reason; the artifact goes `error`.

---

## 5. API contract (detail)

All requests/responses JSON unless noted. Auth via session cookie. Errors use
`{ "error": { "code": "...", "message": "..." } }` with appropriate HTTP status.

### 5.1 Auth
| Method | Path | Body | 2xx | Errors |
|--------|------|------|-----|--------|
| POST | `/api/student/auth/register` | `{email,password,display_name}` | `201 {user}` + cookie | 409 email taken, 422 weak password |
| POST | `/api/student/auth/login` | `{email,password}` | `200 {user}` + cookie | 401 |
| POST | `/api/student/auth/logout` | — | `204` | — |
| GET | `/api/student/auth/me` | — | `200 {user}` | 401 |
| POST | `/api/admin/auth/login` | `{email,password}` | `200 {user}` + cookie | 401 |
| POST | `/api/admin/auth/logout` | — | `204` | — |
| GET | `/api/admin/auth/me` | — | `200 {user}` | 401 |

### 5.2 Admin — courses / modules
| Method | Path | Notes |
|--------|------|-------|
| POST | `/api/admin/courses` | `{title,description,category,cover?}` → `201 {course}` |
| GET | `/api/admin/courses` | list w/ derived status + module counts |
| GET | `/api/admin/courses/{id}` | course + ordered modules + per-artifact status |
| PATCH | `/api/admin/courses/{id}` | title/description/category/cover |
| POST | `/api/admin/courses/{id}/modules` | `{source_url,title,types:[...]}` → `201 {module}` + starts `generate_module` |
| PATCH | `/api/admin/modules/{id}` | `{title?,order_index?}` |
| DELETE | `/api/admin/modules/{id}` | cascade (BR9); `204` |
| POST | `/api/admin/modules/{id}/regenerate` | re-run all six (or existing) types |
| GET | `/api/admin/pipeline?status=&q=&page=` | Recent Pipeline / View All |

### 5.3 Admin — staging / redo / publish / jobs
| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/admin/modules/{id}/staging` | `{module, artifacts:[{type,status,current_version:{...},job:{state}}]}` |
| GET | `/api/admin/artifacts/{id}` | inspect payload + `versions:[...]` + media URLs |
| GET | `/api/admin/artifacts/{id}/versions/{rev}` | one historical version |
| POST | `/api/admin/artifacts/{id}/redo` | `{note?}` → `202 {job}` |
| POST | `/api/admin/artifacts/{id}/retry` | re-enqueue after `error` → `202 {job}` |
| POST | `/api/admin/modules/{id}/publish` | `→ 200 {published:[...], skipped:[...]}` |
| POST | `/api/admin/courses/{id}/publish` | Publish Complete Course; same shape |
| GET | `/api/admin/jobs/{id}` | `{state,attempts,error_detail,timestamps}` |
| GET | `/api/admin/modules/{id}/jobs` | recent jobs for polling |

### 5.4 Admin — settings
| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/admin/prompts` | six active templates |
| GET | `/api/admin/prompts/{type}` | active + version history |
| PUT | `/api/admin/prompts/{type}` | `{body}` → new active version |
| POST | `/api/admin/prompts/{type}/restore-default` | revert to seed |
| GET | `/api/admin/mcp/status` | `{healthy,account_email,last_ok_at,detail}` |
| POST | `/api/admin/mcp/refresh-auth` | triggers `refresh_auth` |
| GET/POST | `/api/admin/users` · PATCH `/api/admin/users/{id}` | admin user mgmt |

### 5.5 Student
| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/student/courses` | published only; `+progress` |
| GET | `/api/student/courses/{slug}` | modules + which artifact types are available |
| GET | `/api/student/modules/{id}` | published artifacts only |
| GET | `/api/student/artifacts/{id}` | published version content + media URLs |
| POST | `/api/student/artifacts/{id}/progress` | `{viewed?,completed?,audio_position_seconds?,slide_last_index?}` |
| POST | `/api/student/artifacts/{id}/quiz-attempts` | `{answers:[index...]}` → `{score_percent,results:[...]}` |
| GET | `/api/student/artifacts/{id}/quiz-attempts` | attempt history |
| PUT | `/api/student/artifacts/{id}/flashcard-ratings/{cardIndex}` | `{rating}` |
| GET | `/api/student/me/progress` | per-course % + per-artifact state |
| GET | `/api/student/me/listening` | audio progress + resume points |
| GET | `/api/student/me/achievements` | earned + locked badges |

### 5.6 Media
| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/media/{key}` | access-checked stream; `Cache-Control` for immutable renders; `404` if not permitted |

---

## 6. Button / control inventory (must be 100% functional — Constitution Art. V.2)

| ID | Screen | Control | Wired action |
|----|--------|---------|--------------|
| BTN-AL1 | Admin login | Sign in | admin auth |
| BTN-AL2 | Admin login | Forgot password | reset flow (if O6) |
| BTN-IG1 | Ingestion | New Artifact | focus form |
| BTN-IG2..5 | Ingestion nav | Ingestion / Review / Editor / Settings | route |
| BTN-IG6 | Ingestion | Generate Course Material | create module + job |
| BTN-IG7..9 | Ingestion header | Settings / Notifications / Avatar(Logout) | route / panel / logout |
| BTN-IG10 | Ingestion | Open Staging (row) | route to staging |
| BTN-IG11 | Ingestion | View All | route to pipeline list |
| BTN-SR1 | Staging | Back to Ingestion | route |
| BTN-SR2 | Staging | Publish Complete Course | course publish + modal |
| BTN-SR3 | Staging | Publish Module | module publish + modal |
| BTN-SR4 | Staging | Redo _[Type]_ (×6) | open redo modal |
| BTN-SR5 | Staging | Inspect (×6) | route to inspect |
| BTN-SR6 | Staging | Retry (error card) | retry job |
| BTN-SR7/8 | Redo modal | Start regeneration / Cancel | redo POST / close |
| BTN-SR9..12 | Staging | Download mp3 (m4a) / pptx / png / pdf | media stream |
| BTN-SR14 | Staging (outline review) | Send feedback | outline feedback POST |
| BTN-SR15 | Staging (outline review) | Proceed | outline proceed POST |
| BTN-AI1 | Inspect | Version history | switch version preview |
| BTN-AI2 | Inspect | Back to staging | route |
| BTN-CE1 | Editor | Add New Video Source | scoped ingestion form |
| BTN-CE2..8 | Editor | kebab: Open staging / Rename / Move up / Move down / Re-run all / Delete | respective API |
| BTN-CE9 | Editor | artifact tile | route to inspect |
| BTN-ST1/2 | Settings/Prompts | Save / Restore default | prompt version APIs |
| BTN-ST3 | Settings/NotebookLM | Reload auth | refresh-auth |
| BTN-ST4 | Settings/Audio | Save | audio options |
| BTN-ST5/6 | Settings/Users | Add admin / Deactivate | user APIs |
| BTN-SL1 | Register | Create account | student register |
| BTN-SL2 | Login | Sign in | student auth |
| BTN-SL3 | Login | Forgot password | reset (if O6) |
| BTN-SL4 | Login | Create account | route to register |
| BTN-CT1 | Catalog | Search | filter grid |
| BTN-CT2..4 | Catalog nav | Catalog / My Listening / Achievements | route |
| BTN-CT5 | Catalog | Profile menu (Logout) | menu / logout |
| BTN-CT6 | Catalog | Category chips | filter grid |
| BTN-CT7 | Catalog | Start Learning | open course workspace |
| BTN-WS1 | Workspace | Course Overview | overview panel/route |
| BTN-WS2 | Workspace | Back to Dashboard | route to catalog |
| BTN-WS3..8 | Workspace nav | Audio/Slides/Flashcards/Quiz/Infographic/Report | route to artifact view |
| BTN-SD1..4 | Slides | Prev / Next / Fullscreen / Download .pptx | viewer + media |
| BTN-FC1..6 | Flashcards | Flip / Prev / Next / Hard / Good / Easy | flip + nav + rating PUT |
| BTN-QZ1..6 | Quiz | Option select / Previous / Next / Submit / Retake / Back | quiz flow + attempt POST |
| BTN-IF1..5 | Infographic | Zoom in / Zoom out / Fullscreen / Download .png / Mark reviewed | viewer + media + progress |
| BTN-RP1..3 | Report | Previous / Complete Module / Download .pdf | nav + progress + media |
| BTN-AU1..8 | Audio | Play / −10s / +10s / Scrub / Speed / Volume / Transcript / Next Lesson | player + progress |
| BTN-ML1 | My Listening | Resume | deep-link to audio at position |

Every row above is covered by a Playwright assertion in the e2e suite.

---

## 7. Acceptance criteria roll-up (Definition of "spec satisfied")

1. All screens in §3 render per the reference designs and pass the Button
   Inventory e2e.
2. All Business Rules in §4 hold, proven by backend tests.
3. All negative stories US-N1..N4 pass.
4. The full admin flow (ingest → 6 generated → redo one → publish module → publish
   course) works end-to-end under `FixtureProvider`.
5. The full student flow (register → catalog → consume all six → progress
   reflected) works end-to-end under `FixtureProvider`.
6. Every Open Item O1–O7 is either resolved or its dependent behaviour is
   explicitly de-scoped with owner sign-off.
