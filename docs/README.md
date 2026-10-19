# Shikshak Dp — AI Course Content Suite · Spec-Kit

Spec-Kit-style planning set for a single application with two experiences:

- **Admin** — paste a source link → NotebookLM (via the
  [`notebooklm-mcp-server`](https://github.com/moodRobotics/notebooklm-mcp-server))
  generates six learning artifacts into a private staging area → admin reviews,
  **Redo**s any single artifact (with an optional instruction), then **Publish**es.
- **Student** — a separate login into a course catalog and a per-course
  workspace to consume Slides, Flashcards, Quiz, Report, Infographic, and Audio
  Overview, with full progress tracking.

## Read in this order

| # | File | What it is |
|---|------|-----------|
| 1 | [`PROJECT_FRAME.md`](./PROJECT_FRAME.md) | The whole picture — vision, roles, concepts, workflows, architecture, data model, APIs, NFRs, risks, decisions log, open items. |
| 2 | [`constitution.md`](./constitution.md) | Non-negotiable engineering principles. |
| 3 | [`spec.md`](./spec.md) | Functional spec — user stories, screen-by-screen behaviour, business rules, API contract, the Button Inventory, acceptance criteria. |
| 4 | [`plan.md`](./plan.md) | Technical plan — concrete stack + versions, repo layout, service topology, MCP integration design, rendering, auth, phasing. |
| 5 | [`tasks.md`](./tasks.md) | 47 ordered, dependency-aware tasks with acceptance criteria. |
| 6 | [`task-tracker.md`](./task-tracker.md) | Live status board. Updated as work proceeds. |
| 7 | [`implementation.md`](./implementation.md) | Execution runbook — environment, coding standards, per-task workflow, Definition of Done. |

## Key decisions (full list in `PROJECT_FRAME.md` §16)

React SPA + FastAPI + PostgreSQL · Celery + Redis · separate admin/student login
pages · Course → Modules → 6 Artifacts · MCP generates, backend renders to real
`.pptx` / image / `.pdf` / `.mp3` · Redo is per-artifact with an optional note
and full version history · no inline editing in v1 (Inspect is read-only) ·
students self-signup, all published courses visible · local filesystem media
volume · full progress tracking · AWS deploy target · **stop for owner review
before Task T001**.

## Open items to close before the dependent tasks

O1 infographic-image retrieval · O2 audio `.mp3` + transcript retrieval · O3
non-DBSC Google account · O4 source duration · O5 achievements set · O6 student
password reset / verification · O7 course category taxonomy. See
`PROJECT_FRAME.md` §17 and `task-tracker.md`.

## Design source

`../ai_course_content_suite/` (reference screens + `code.html` per screen) and
`../ai_course_content_suite/academic_modernist/DESIGN.md` (design system). The
build must match these.
