# Project Constitution — Shikshak Dp AI Course Content Suite

**Version:** 1.0.0
**Ratified:** 2026-09-02
**Applies to:** all code, docs, and infrastructure in this repository.

The constitution is the highest-priority ruleset. When any other document, task,
or convenience conflicts with an article here, the article wins. Amendments
require an explicit owner decision recorded in `PROJECT_FRAME.md` §16 and a
version bump here.

---

## Article I — Truthfulness over guessing

1. No feature, endpoint, library API, or external-service behaviour may be
   assumed. If it is not verified (docs read, code inspected, test run), it is an
   **Open Item** in `PROJECT_FRAME.md` §17 and blocks its dependent task.
2. The NotebookLM MCP server's tool names, parameters, and return shapes used in
   code must match its published `docs/TOOLS.md` / source at the pinned version.
   Any divergence is a bug, not a workaround.
3. UI must not display invented data. Placeholder/among-us copy is prohibited
   outside clearly-labelled fixtures and `TODO(owner)` prompt bodies.
4. If something cannot be built as specified, stop and raise it. Do not
   substitute a different behaviour silently.

## Article II — The admin/student boundary is sacred

1. Students must never reach an admin route, admin API, or any unpublished
   content. This is enforced **server-side** at the query layer, not only in the
   UI.
2. Admin and student authentication use **separate login pages and separate
   session scopes**. One cannot be used for the other.
3. Every `/api/admin/*` route has an automated test asserting rejection of
   anonymous and student callers.
4. Admin accounts are never created by self-service registration.
5. Media files are served only through an access-checked endpoint.

## Article III — Generation is reviewable, reversible, and isolated

1. Every generation or redo run produces a new **immutable `ArtifactVersion`**.
   History is never overwritten.
2. **Redo acts on exactly one artifact.** It must not re-run, alter, or
   invalidate sibling artifacts.
3. Publishing a new version must not take down the currently published version
   until the new one is explicitly published.
4. Malformed generator output results in an `error` status with a human-readable
   reason — never a published artifact containing broken content.
5. The admin's `focus_prompt` (prompt template + optional redo note) and the
   template version used are recorded on the version for provenance.

## Article IV — Async by default, never block the user

1. Content generation runs in Celery workers. No HTTP request waits on
   NotebookLM.
2. Job state is always queryable; the UI reflects `queued` / `processing` /
   `ready` / `error` honestly, including partial and mixed states.
3. NotebookLM calls are serialized/concurrency-capped to respect the single
   shared Google session and undocumented limits.
4. Transient external failures retry with bounded backoff; permanent failures
   surface to the admin with detail.

## Article V — Build against the real designs

1. The UI implements `academic_modernist/DESIGN.md` and the reference screens in
   `ai_course_content_suite/`. Colours, typography, spacing, radius, and
   elevation come from the ported Tailwind token set, not ad-hoc values.
2. **Every interactive control does something real** — no dead buttons, no
   `href="#"` placeholders. The button inventory in `spec.md` must be 100%
   satisfied and covered by an e2e test.
3. Loading, empty, and error states are designed and implemented for every
   screen, matching the design language.
4. Accessibility target is WCAG 2.1 AA: keyboard operability, visible focus, alt
   text on generated images, audio transcript, semantic structure, sufficient
   contrast.

## Article VI — Tests and Definition of Done

1. A task is **Done** only when: code + tests written, all tests pass, lint and
   type-check clean, the acceptance criteria in `tasks.md` are demonstrably met,
   `task-tracker.md` is updated, and the change runs under `FixtureProvider`
   with no live Google session.
2. Backend: unit tests for parsers, renderers, RBAC, publish logic, progress
   math; API integration tests for each endpoint group.
3. Frontend: component tests for interactive components; Playwright e2e for the
   core admin and student flows.
4. No task is started before its dependencies are Done and its Open Items are
   closed.
5. Work proceeds **one task at a time, in order**. Finish and mark a task before
   taking the next.

## Article VII — Configuration, secrets, and data

1. All environment-specific values come from environment variables / AWS Secrets
   Manager. No secrets, tokens, or real credentials in the repo or fixtures.
2. Database schema changes go through Alembic migrations, reviewed like code.
3. The file storage volume is the only place rendered binaries live; the DB
   stores logical keys and metadata. No binaries in the DB.
4. `ArtifactVersion` rows and the published + current rendered media are always
   retained; only superseded surplus media may be garbage-collected, behind a
   config flag.
5. All admin mutations are written to the audit log.

## Article VIII — Simplicity and scope discipline

1. Implement v1 scope only (`PROJECT_FRAME.md` §14 lists what is out). New scope
   requires an owner decision.
2. Prefer boring, well-understood tools already chosen in `plan.md`. Adding a
   dependency requires a one-line justification in the PR/commit.
3. The `ContentProvider` interface is the only path to NotebookLM. No direct MCP
   calls scattered through the codebase.
4. Keep modules cohesive: pipeline, rendering, auth, admin API, student API, and
   progress are separate packages with clear boundaries.

## Article IX — Observability and operability

1. Structured JSON logs carry a request id and, for worker logs, a job id.
2. MCP connectivity is health-checked on a schedule and surfaced in the admin
   header badge and `/api/admin/mcp/status`.
3. An operations runbook covers MCP re-authentication (`refresh_auth`), the DBSC
   constraint, backups, and restore.
4. Errors are captured to a Sentry-compatible sink in staging/prod.

---

### Amendment log
| Version | Date | Change |
|---------|------|--------|
| 1.0.0 | 2026-09-02 | Initial ratification. |
