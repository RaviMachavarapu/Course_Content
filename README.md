# Shikshak Dp — AI Course Content Suite

Single application, two experiences:

- **Admin** — paste a source link (YouTube / web / Drive / PDF). The backend
  drives Google NotebookLM through the
  [`notebooklm-mcp-server`](https://github.com/moodRobotics/notebooklm-mcp-server)
  to generate six learning artifacts (Slide Deck, Flashcards, Quiz, Report,
  Infographic, Audio Overview) into a **private staging area**. The admin
  reviews each one, clicks **Redo** (optionally with an instruction) to
  regenerate a single artifact, and **Publish** when satisfied.
- **Student** — a separate login into a course catalog and a per-course
  workspace to consume the six artifacts, with full progress tracking.

## Repository layout

```
docs/                     Spec-Kit planning set (start at docs/README.md)
ai_course_content_suite/  Reference UI designs (read-only input)
backend/                  FastAPI + SQLAlchemy + Celery (Python 3.12, runs in Docker)
frontend/                 React + Vite + TypeScript + Tailwind SPA
mcp/                      notebooklm-mcp-server container + auth runbook
typeset/                  Markdown + LaTeX -> PDF service (pandoc + xelatex)
docker-compose.yml        Local dev environment
```

## Quick start (local dev)

Prereqs: Docker + Docker Compose (2.24+), Git. A Google account is **not**
required — the default content provider is `fixture`.

```bash
# Optional: local overrides (Vite dev server with hot reload, live NotebookLM).
# Without it, `web` serves the nginx production build.
cp docker-compose.override.example.yml docker-compose.override.yml

docker compose up -d postgres redis
docker compose run --rm api alembic upgrade head
docker compose run --rm api python -m app.cli seed-admin --email you@example.com --name "You"
docker compose run --rm api python -m app.cli seed-prompts
docker compose up -d
```

Configuration comes from the environment set in `docker-compose.yml`
(`x-backend-env`); every setting and its default is in `backend/app/config.py`.
`backend/.env` (copy of `backend/.env.example`, git-ignored) is optional and
only fills in values the compose file does not set.

- Student app: http://localhost:5173
- Admin app:   http://localhost:5173/admin/login
- API docs:    http://localhost:8000/api/docs
- MailHog:     http://localhost:8025 (password-reset mail)

All published ports are bound to 127.0.0.1 (the stack uses dev credentials).

### Services

| Service | Role |
|---------|------|
| `web` | nginx: the built SPA on :5173, proxies `/api/` to `api` |
| `api` | FastAPI on :8000 |
| `worker` | Celery: generation (`celery`, `text`, `audio` queues) |
| `worker-pdf` | Celery: typeset PDFs (`pdf` queue, one at a time) |
| `worker-quiz` | Celery: fresh quiz question sets for students (`quiz` queue, one at a time) |
| `beat` | Celery beat: periodic maintenance |
| `typeset` | Markdown + LaTeX formulas -> PDF; internal only, no published port |
| `postgres`, `redis`, `mailhog` | infrastructure |
| `mcp` | live NotebookLM connector; off by default (`docker compose --profile mcp up -d mcp`, sign-in: `mcp/README.md`) |

Typeset service tests (run in its image):

```bash
docker compose build typeset
docker run --rm --init --network none shikshak-dp-typeset python3 -m pytest -q /app/tests
```

### Working on the backend without Docker

The backend targets **Python 3.12**. If your host Python is older, use the
container for tests and tooling:

```bash
docker compose run --rm api pytest
docker compose run --rm api ruff check .
```

### Working on the frontend

No host Node needed: the override example runs the Vite dev server in the
`web` container. Tests run in the build image:

```bash
docker build --target build -t sdp-fe-build frontend
docker run --rm sdp-fe-build npm test     # Vitest
```

## Development workflow

Work proceeds **one task at a time, in order**, tracked in
[`docs/task-tracker.md`](docs/task-tracker.md). Each task's acceptance criteria
and the project rules live in [`docs/`](docs/README.md):

| Doc | Purpose |
|-----|---------|
| `docs/PROJECT_FRAME.md` | Whole-system frame |
| `docs/constitution.md` | Non-negotiable engineering rules |
| `docs/spec.md` | Functional spec + Button Inventory |
| `docs/plan.md` | Technical plan + stack |
| `docs/tasks.md` | 47 ordered tasks |
| `docs/task-tracker.md` | Live status |
| `docs/implementation.md` | Execution runbook + Definition of Done |
