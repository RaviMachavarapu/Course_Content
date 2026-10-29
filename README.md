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

Login protection (both areas; see `docs/superpowers/specs/2026-10-29-login-protection.md`):

- `LOGIN_RATE_LIMIT` (default `100/15m`): failed logins per client IP; successes never count.
- `LOGIN_FREE_FAILURES` (5), `LOGIN_FAILURE_WINDOW_SEC` (900), `LOGIN_DELAY_BASE_SEC` (2),
  `LOGIN_DELAY_MAX_SEC` (60): per email, after 5 failures in 15 minutes each further
  attempt waits 2, 4, 8 … 60 s (429 with `retry_after`) instead of a hard lock-out.
- `DEVICE_COOKIE_SECRET`, `DEVICE_COOKIE_MAX_AGE_DAYS` (180), `LOGIN_DEVICE_FREE_FAILURES`
  (10): a browser that has signed in before carries a signed `sdp_device_<area>` cookie and
  is not held up by failures elsewhere. **`DEVICE_COOKIE_SECRET` must be set to a random
  value of at least 32 characters outside dev** (the app refuses to start otherwise); changing it only signs
  everyone's devices out of the trusted state.
- `REGISTER_RATE_LIMIT` (`100/1h`) and `PASSWORD_RESET_RATE_LIMIT` (`30/1h`) per client IP;
  reset mail is capped at 3 per hour per address.

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
| `media-init` | one-shot, before the backend services: gives the `media` volume to the backend's unprivileged user (uid/gid 10001); api, workers and beat run as that user, never root |
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

## Production checklist

`docker-compose.yml` is the dev stack. Its secrets and public address have
obviously-dev defaults that a root `.env` overrides; with `APP_ENV` set to
`staging` or `prod` the api, workers and beat **refuse to start** while any of
them is a dev or missing value (`backend/app/config.py`).

1. **Secrets.** `cp .env.example .env`, then `scripts/gen-secrets` and paste its
   three lines over the `<generate>` placeholders (no python3? any
   `python3 -c 'import secrets; print(secrets.token_urlsafe(32))'` equivalent
   works; keep values URL-safe). `.env` is git-ignored: never commit it, keep a
   copy in a password manager.
   The guard requires: `DATABASE_URL` with a password that isn't `shikshak`;
   `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` with a password
   that isn't the dev one; `DEVICE_COOKIE_SECRET` of 32+ characters (not the
   dev one); `PUBLIC_BASE_URL` on https and not localhost; in prod a real
   `SMTP_URL` or `PASSWORD_RESET_ENABLED=false`.
2. **`APP_ENV=prod`** (or `staging`): Secure cookies, HSTS (prod), no
   `/api/docs`.
3. **Database password.** `POSTGRES_PASSWORD` only applies when the `pgdata`
   volume is created. On an existing volume change it in the database first:
   `docker compose exec postgres psql -U shikshak -c "ALTER USER shikshak PASSWORD '<new>'"`,
   then set it in `.env` and `docker compose up -d`.
4. **Redis password.** `REDIS_PASSWORD` in `.env`; redis and every backend
   service must be recreated together (`docker compose up -d`). Recreating
   redis signs everyone out and drops queued Celery messages.
5. **HTTPS.** Put a TLS-terminating reverse proxy in front of `web`
   (127.0.0.1:5173) and set `PUBLIC_BASE_URL` / `CORS_ORIGINS` to the https
   address. Outside dev the session, CSRF and device cookies are `Secure`, so
   plain http can't sign in. The api trusts `X-Forwarded-For` only from `web`;
   if your proxy sits in front of nginx, configure nginx `real_ip` for it or
   every client shares one login rate-limit bucket.
6. **Ports.** Everything is published on 127.0.0.1 only. In production publish
   only `web` (to the TLS proxy); drop the postgres (5432), redis (6379), api
   (8000) and mailhog ports, e.g. `ports: !reset []` in a production override.
   Keep mcp's 7332/6080 on localhost and reach noVNC through an SSH tunnel.
7. **Non-root.** api, workers and beat run as uid/gid 10001 (`backend/Dockerfile`);
   `media-init` fixes the media volume's ownership before they start. For a
   one-off root shell use `docker compose run --rm --user 0 api sh`. On a Linux
   host the dev `./backend:/app` bind mount is owned by your user, so tools that
   write caches there (pytest, ruff, mypy) need `--user "$(id -u)"` or a
   writable checkout; Docker Desktop (macOS) needs nothing.
8. **Dev-only bits.** In a production override remove the api's `--reload`,
   the `./backend:/app` bind mounts (the image has the code) and mailhog, and
   set the login/sign-up limits in `.env` (the compose defaults are loose for
   e2e runs; `.env.example` has the app defaults).
9. **Backups.** The database and the `media` volume (uploaded PDFs and every
   generated artifact file) together:
   ```bash
   mkdir -p backups
   docker compose exec -T postgres pg_dump -U shikshak -Fc shikshak > backups/db-$(date +%F).dump
   docker run --rm -v shikshak-dp_media:/data:ro -v "$PWD/backups:/backup" alpine \
     tar czf /backup/media-$(date +%F).tgz -C /data .
   ```
   Test a restore; keep the copies off the host.
10. **mcp (live NotebookLM) auth.** `mcp/auth/` holds a signed-in Google session
   (`auth.json` and the browser profile): it is git-ignored, must never be
   committed, copied into backups others can read, or baked into an image.
   Keep it `chmod 700`, run the `mcp` profile only where needed, and sign in
   with `mcp/auth-login.mjs` (`mcp/README.md`). If the host is compromised,
   sign that Google account out of all sessions.

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
