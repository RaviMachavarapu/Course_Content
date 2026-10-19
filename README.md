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
mcp/                       notebooklm-mcp-server container + auth runbook
infra/                    Terraform skeleton (AWS) + deploy runbook
docker-compose.yml         Local dev environment
```

## Quick start (local dev)

Prereqs: Docker + Docker Compose, Node 20+, Git. A Google account is **not**
required — the default content provider is `fixture`.

```bash
cp docker-compose.override.example.yml docker-compose.override.yml
cp backend/.env.example backend/.env          # set SESSION_SECRET etc.

docker compose up -d postgres redis
docker compose run --rm api alembic upgrade head
docker compose run --rm api python -m app.cli seed-admin --email you@example.com --name "You"
docker compose run --rm api python -m app.cli seed-prompts
docker compose up                              # api :8000, web :5173, worker, beat, mailhog
```

- Student app: http://localhost:5173
- Admin app:   http://localhost:5173/admin/login
- API docs:    http://localhost:8000/api/docs

### Working on the backend without Docker

The backend targets **Python 3.12**. If your host Python is older, use the
container for tests and tooling:

```bash
docker compose run --rm api pytest
docker compose run --rm api ruff check .
```

### Working on the frontend

```bash
cd frontend
npm install
npm run dev      # Vite dev server
npm run build    # production build
npm test         # Vitest
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
