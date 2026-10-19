# Implementation Runbook — Shikshak Dp AI Course Content Suite

**Version:** 1.0 (draft for review)
**Purpose:** how tasks in `tasks.md` are actually executed — environment,
standards, the per-task workflow, and Definition of Done. This is the
`/speckit implementation` companion: the spec says *what*, the plan says *with
what*, this says *how we work*.

---

## 1. Prerequisites (developer machine)

- Docker + Docker Compose
- Python 3.12 + `uv` or `pipx` (for local tooling outside containers)
- Node 20 LTS + npm
- `git`
- Optional for live NotebookLM: a **Google account WITHOUT DBSC enforcement**
  (Workspace and most personal accounts enforce Device Bound Session
  Credentials, which makes exported cookies unusable — see `PROJECT_FRAME.md`
  §12 and Open Item O3). **Not required** for any build/test work — the
  `FixtureProvider` covers everything.

---

## 2. First-time setup

```bash
git clone <repo> && cd <repo>
cp docker-compose.override.example.yml docker-compose.override.yml
cp backend/.env.example backend/.env          # fill SESSION_SECRET etc.
docker compose up -d postgres redis
docker compose run --rm api alembic upgrade head
docker compose run --rm api python -m app.cli seed-admin --email you@example.com --name "You"
docker compose up                              # api, worker, beat, web, mailhog
# SPA: http://localhost:5173   API: http://localhost:8000
# Admin login: http://localhost:5173/admin/login
```

Content provider defaults to `fixture`. To use live NotebookLM later (T016;
pinned at `notebooklm-mcp-server@4.0.2`, see `mcp/README.md`):

```bash
docker compose --profile mcp run --rm mcp npx -y notebooklm-mcp-server@4.0.2 auth   # interactive Google login
docker compose --profile mcp up -d mcp   # shim + pinned server on :7332
# then set CONTENT_PROVIDER=notebooklm in backend/.env (MCP_ENDPOINT already
# defaults to http://mcp:7332), restart worker
```

Load demo content any time (Phase 5 task T044):

```bash
docker compose run --rm api python -m app.cli seed-demo
```

---

## 3. Coding standards

### Backend (Python)
- Ruff + Black + mypy (strict on `app/`); no `# type: ignore` without a reason.
- FastAPI routers thin; logic in `services/` / `pipeline/` / `render/`.
- Pydantic schemas for every request and response; never return ORM objects.
- All DB writes in a transaction; Alembic migration for every schema change,
  with a working `downgrade`.
- No direct MCP calls outside `app/pipeline/`. The only entry point is
  `ContentProvider`.
- Sanitise all NotebookLM HTML through `pipeline/parsers/_sanitize.py` before
  storing or rendering.
- Errors: raise typed exceptions (`ArtifactParseError`, `RenderError`,
  `ProviderError`); map to HTTP in one place.

### Frontend (TypeScript / React)
- ESLint + Prettier + `tsc --noEmit`; no `any` without a comment.
- All styling via the Tailwind preset tokens (`theme/`). No hard-coded hex/px
  outside the preset.
- Server state via TanStack Query hooks in `lib/`; components don't call `fetch`.
- Every interactive element is a real control with an accessible name and a
  working handler. No `href="#"`, no disabled-looking dead buttons
  (Constitution Art. V.2).
- Loading = `Skeleton`, empty = `EmptyState`, failure = `ErrorState` — on every
  screen.
- Keyboard: all actions reachable and operable; visible focus ring from the
  design system.

### Shared
- Conventional Commits (`feat:`, `fix:`, `test:`, `chore:`, `docs:`), one task
  per branch (`t013-domain-models`), reference the task id in the PR/commit.
- No secrets in the repo. `*.env` git-ignored; `*.env.example` committed.
- Adding a dependency requires a one-line justification in the commit body.

---

## 4. Per-task workflow

For each task, in `tasks.md` order:

1. **Check the gate.** All `Dep:` tasks are ✅ in `task-tracker.md`; all `OI:`
   Open Items for this task are Resolved (or owner-signed-off as de-scoped). If
   not, stop and report — do not start.
2. **Set status 🟨** in `task-tracker.md` (with your name + date).
3. **Branch** `t<NNN>-<slug>`.
4. **Write tests first** where practical (parsers, renderers, RBAC, publish,
   progress math). For UI, write the component/Playwright assertions from the
   task's AC and the Button Inventory rows it covers.
5. **Implement** to satisfy every AC bullet. Keep scope to the task; note any
   discovered adjacent work as a new candidate task rather than doing it inline.
6. **Verify locally:** `ruff`, `black --check`, `mypy`, `pytest`; `eslint`,
   `tsc`, `vitest`, `npm run build`; relevant Playwright specs. All green.
7. **Run under `FixtureProvider`** end-to-end for anything pipeline-adjacent.
8. **Self-review against the design** (`ai_course_content_suite/*/screen.png` +
   `academic_modernist/DESIGN.md`) for any UI task.
9. **Update `task-tracker.md`:** status ✅, fill Notes/Evidence (PR link, test
   names, screenshots). Update the Open Items / Blockers / Change log sections if
   affected.
10. **Open a PR**; on merge, move to the next task.

Never run two tasks in parallel. If a task turns out to be blocked mid-way, set
🚧, record the blocker in `task-tracker.md` → Blockers, and surface it to the
owner.

---

## 5. Definition of Done (per task)

A task is **Done** when **all** of:

- [ ] Every AC bullet in `tasks.md` for the task is demonstrably met.
- [ ] Code + tests written; new logic has unit coverage; endpoints have
      integration coverage; UI has component tests and any Button-Inventory
      Playwright assertions it introduces.
- [ ] `ruff` / `black` / `mypy` clean; `eslint` / `tsc` clean; all suites pass
      locally and in CI.
- [ ] Runs correctly with `CONTENT_PROVIDER=fixture` and **no** Google session.
- [ ] No secrets added; env additions documented in `.env.example` and
      `plan.md` §8.
- [ ] Migrations (if any) `upgrade` + `downgrade` cleanly.
- [ ] `task-tracker.md` updated (status, evidence, change log).
- [ ] For UI: reviewed side-by-side with the reference design; deviations fixed
      or logged with owner sign-off.

---

## 6. Definition of Done (whole project — T047)

- [ ] `PROJECT_FRAME.md` §15 acceptance list: every item passes, evidenced in
      `docs/acceptance-report.md`.
- [ ] `spec.md` §7 roll-up passes, including the §6 Button Inventory 100% green.
- [ ] Full admin e2e: login → ingest source → 6 artifacts generated → redo one
      (with a note) → publish module → publish complete course.
- [ ] Full student e2e: register → catalog (filter/search) → open course →
      consume slides / flashcards / quiz / infographic / report / audio →
      progress reflected in catalog %, My Listening, Achievements.
- [ ] Security: automated proof that students/anon cannot reach `/api/admin/*`
      or any unpublished content or media.
- [ ] All Open Items O1–O7 Resolved or owner-signed-off de-scoped (⏭️ with a
      link).
- [ ] `seed-demo` gives a reviewer a working end-to-end system with no Google
      session.
- [ ] Docs delivered: OpenAPI reference, admin guide, student guide, operations
      runbook; `infra/terraform` `validate`s.
- [ ] CI green on `main`.

---

## 7. Placeholder: system prompts

`backend/app/prompts/` holds one file per artifact type:

```
slide_deck.md   flashcards.md   quiz.md
report.md       infographic.md  audio_overview.md
```

Each begins with:

```md
<!-- TODO(owner): replace this placeholder with the real system prompt.
     This text is passed to NotebookLM as `focus_prompt`. No application
     behaviour depends on the wording. -->
```

The owner supplies final prompt text later; it is edited thereafter through
**Admin → Settings → Generation Prompts** (which versions each change). T014
seeds the DB from these files on first run.

---

## 8. Handling Open Items during the build

| Item | Handling |
|------|----------|
| O1, O2 | Dedicated spike tasks (T015a/T015b) produce `docs/spikes/O1-infographic.md` / `O2-audio.md` with findings + decision, and flip the item to Resolved in `PROJECT_FRAME.md` §17 and `task-tracker.md`. Dependent tasks (T019/T018-audio/T036/T038) stay ⬜ until then. |
| O3 | Owner action. Track in `task-tracker.md`. Build proceeds on fixtures regardless; only *live* MCP verification waits. |
| O4, O5, O6, O7 | Small product decisions. Each task that needs one (T028, T039, T008/T011, T025/T031) checks the item at gate time; if still open, ask the owner then, with the proposed default from `spec.md`. |

---

## 9. What to do when reality diverges from these docs

Per `constitution.md` Art. I: if the MCP, a library, or a design cannot support
what a task's AC describes, **stop**. Record the divergence in the task's
tracker Notes, raise it to the owner with options, and only proceed once a
decision is recorded in `PROJECT_FRAME.md` §16/§17. Do not substitute alternative
behaviour silently.
