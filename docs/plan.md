# Implementation Plan — Shikshak Dp AI Course Content Suite

**Version:** 1.0 (draft for review)
**Binds:** `spec.md` behaviour to concrete technology, per `constitution.md`.

---

## 1. Technology decisions (concrete)

| Concern | Choice | Version (pin at scaffold time) | Why |
|--------|--------|-------------------------------|-----|
| Language (backend) | Python | 3.12.x | Owner choice; strong MCP/render tooling. |
| Web framework | FastAPI | ~0.115 | Async, typed, OpenAPI out of the box. |
| Validation | Pydantic | v2.x | FastAPI-native. |
| ORM / migrations | SQLAlchemy 2.x + Alembic | 2.0.x / 1.13.x | Mature, typed. |
| DB | PostgreSQL | 16.x | Owner choice; JSONB for content. |
| Task queue | Celery | 5.4.x | Owner choice. |
| Broker / result backend | Redis | 7.x | Celery pairing. |
| Periodic tasks | Celery beat | (bundled) | MCP healthcheck, media GC. |
| Password hashing | Argon2 (`argon2-cffi`) | latest | OWASP-preferred. |
| HTTP client (to MCP) | `httpx` / MCP SDK client | latest | Depends on MCP transport (§4). |
| Slide files | `python-pptx` | latest | `.pptx` authoring. |
| Slide→image/PDF | LibreOffice headless (`soffice`) | distro | `.pptx` → PNG/PDF. |
| Report PDF | WeasyPrint | latest | HTML→PDF. |
| Diagrams | Mermaid CLI (`@mermaid-js/mermaid-cli`) + Graphviz | latest | Infographic SVG/PNG. |
| HTML sanitising | `nh3` (ammonia) or `bleach` | latest | Allowlist sanitiser for NotebookLM HTML. |
| Frontend | React + Vite + TypeScript | React 18.x / Vite 5.x | Owner choice (SPA). |
| Styling | Tailwind CSS | 3.x | Port the token config from reference `code.html`. |
| Routing | React Router | 6.x | Two route trees. |
| Server state | TanStack Query | 5.x | Polling, caching. |
| UI state | Zustand | 4.x | Light local state. |
| Icons/fonts | Material Symbols Outlined, Public Sans, Inter | — | From the design system. |
| Testing (BE) | pytest, pytest-asyncio, httpx test client, factory-boy | latest | Unit + integration. |
| Testing (FE) | Vitest + React Testing Library; Playwright | latest | Component + e2e. |
| Lint/format | Ruff + Black (BE); ESLint + Prettier (FE); pre-commit | latest | Constitution Art. VI. |
| Container | Docker + docker compose | — | Dev parity + AWS images. |
| IaC | Terraform | 1.9.x | AWS skeleton. |
| Error tracking | Sentry SDK (BE + FE), opt-in via DSN | latest | Staging/prod. |
| Email (dev) | MailHog | — | Password reset testing. |

> If a pinned version is unavailable or incompatible at scaffold time, pick the
> nearest stable and record it in `implementation.md` §Versions. Do not silently
> drift.

---

## 2. Repository layout (monorepo)

```
/
├── docs/                     # this Spec-Kit set (already present)
├── ai_course_content_suite/  # reference designs (read-only input)
├── backend/
│   ├── app/
│   │   ├── main.py                 # FastAPI app factory
│   │   ├── config.py               # pydantic-settings
│   │   ├── db/                     # engine, session, base
│   │   ├── models/                 # SQLAlchemy models (§8 of PROJECT_FRAME)
│   │   ├── schemas/                # Pydantic request/response
│   │   ├── api/
│   │   │   ├── deps.py             # auth guards (admin/student), db, csrf
│   │   │   ├── admin/              # admin routers (courses, staging, settings…)
│   │   │   ├── student/            # student routers
│   │   │   └── media.py            # access-checked media stream
│   │   ├── auth/                   # sessions, cookies, hashing, rate limit
│   │   ├── pipeline/
│   │   │   ├── provider.py         # ContentProvider interface
│   │   │   ├── notebooklm_mcp.py   # NotebookLmMcpProvider
│   │   │   ├── fixture.py          # FixtureProvider
│   │   │   ├── orchestrator.py     # generate_module / generate_artifact / redo
│   │   │   └── parsers/            # html -> content_json per type (+ validation)
│   │   ├── render/
│   │   │   ├── slides_pptx.py      # json -> pptx -> png/pdf
│   │   │   ├── infographic.py      # structure -> mermaid/graphviz -> svg/png
│   │   │   └── report_pdf.py       # html -> pdf
│   │   ├── storage/                # file volume abstraction, keys, GC
│   │   ├── prompts/                # <type>.md placeholder seed files
│   │   ├── progress/               # progress + achievements logic
│   │   ├── tasks/                  # celery app + task modules
│   │   └── cli.py                  # seed-admin, seed-demo, etc.
│   ├── alembic/
│   ├── tests/
│   │   ├── unit/  integration/  fixtures/   # captured MCP HTML, canned artifacts
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── main.tsx
│   │   ├── app/                    # router, providers
│   │   ├── theme/                  # tailwind preset (ported tokens), fonts
│   │   ├── lib/                    # api client, query hooks, auth
│   │   ├── components/             # shared UI kit (Button, Card, Chip, Nav…)
│   │   ├── admin/                  # admin screens (A1–A5)
│   │   ├── student/                # student screens (S1–S9)
│   │   └── e2e/                    # Playwright specs (button inventory)
│   ├── tailwind.config.ts
│   ├── vite.config.ts
│   └── package.json
├── mcp/
│   ├── Dockerfile                  # notebooklm-mcp-server container
│   └── README.md                   # auth runbook, DBSC note
├── infra/
│   ├── terraform/                  # AWS skeleton (ECS, RDS, ElastiCache, EFS, ALB)
│   └── deploy-runbook.md
├── docker-compose.yml
├── docker-compose.override.example.yml
├── .github/workflows/ci.yml
└── README.md
```

---

## 3. Service topology

### Dev (`docker compose up`)
`postgres`, `redis`, `api` (uvicorn --reload), `worker` (celery), `beat`,
`web` (vite dev server, or nginx for prod-like), `mcp` (optional; off by default),
`mailhog`.

Default `CONTENT_PROVIDER=fixture`. Set `CONTENT_PROVIDER=notebooklm` +
`MCP_ENDPOINT=...` once `mcp` is authenticated.

### CI
`postgres` + `redis` service containers; `api`/`worker` run in the test job;
`CONTENT_PROVIDER=fixture`; no egress to Google. Jobs: BE lint+type+test, FE
lint+type+test+build, Playwright e2e against a compose stack.

### AWS (staging/prod) — target, Terraform skeleton only in v1
- **ECR**: images for `web`, `api`, `worker`, `beat`, `mcp`.
- **ECS Fargate** services: `web` (public via ALB), `api` (private), `worker`,
  `beat`, `mcp` (private, single task — shared Google session).
- **RDS PostgreSQL** (Multi-AZ optional).
- **ElastiCache Redis**.
- **EFS** access point mounted at `/data/media` on `api` + `worker` (and `mcp`
  for its `auth.json` on a separate restricted access point).
- **ALB** → `web`; `web` reverse-proxies `/api` to `api`.
- **Secrets Manager**: `DATABASE_URL`, `REDIS_URL`, `SESSION_SECRET`,
  `SENTRY_DSN`, MCP config.
- **CloudWatch** logs; alarms on worker failure rate + MCP health.
- GCP mapping (Cloud Run / Cloud SQL / Memorystore / Filestore) documented in
  `infra/deploy-runbook.md`; not implemented in v1.

---

## 4. NotebookLM MCP integration design

### 4.1 Transport
The `notebooklm-mcp-server` is an MCP server (stdio / npx). In containers we run
it as a long-lived process and speak MCP to it. Concretely:
- `mcp` container runs `npx notebooklm-mcp-server` (pinned version) with its
  `~/.notebooklm-mcp/auth.json` on a mounted volume.
- `worker` uses an MCP client library to connect (stdio via a sidecar exec, or
  the server's HTTP mode if available at the pinned version — **confirm during
  T015/T016; this is Open Item-adjacent**). The `ContentProvider` hides which.

### 4.2 `ContentProvider` interface (stable regardless of transport)
```python
class ContentProvider(Protocol):
    def create_notebook(self, title: str) -> NotebookRef: ...
    def add_source(self, nb: NotebookRef, url: str) -> SourceRef: ...
    def generate(self, nb: NotebookRef, kind: ArtifactType,
                 focus_prompt: str, options: dict) -> StudioJobRef: ...
    def poll(self, job: StudioJobRef) -> StudioStatus: ...      # pending|ready|failed
    def fetch_content(self, job: StudioJobRef) -> RawArtifact:  # {html, extras}
        ...
    def fetch_binary(self, job: StudioJobRef, kind: ArtifactType) -> bytes | None: ...
    def health(self) -> ProviderHealth: ...
    def refresh_auth(self) -> None: ...
```

Mapping to MCP tools (verified names from `docs/TOOLS.md`):
`create_notebook`→`notebook_create`; `add_source`→`notebook_add_url`;
`generate`→`{slide_deck,flashcards,quiz,report,infographic,audio_overview}_create`
with `focus_prompt`; `poll`→`studio_poll`; `fetch_content`→`artifact_content_get`
(`{artifact_id, html, mind_map_tree}`); `refresh_auth`→`refresh_auth`.
`fetch_binary` for audio `.mp3` and infographic image → **Open Items O1/O2**;
`NotebookLmMcpProvider.fetch_binary` raises `NotImplementedError` until the spike
resolves, and the orchestrator's fallbacks (render our own infographic; block
audio pending owner decision) apply.

### 4.3 Orchestration (`pipeline/orchestrator.py`)
- `generate_module(module_id, types)`:
  1. `create_notebook(module.title)` → store `notebooklm_notebook_id`.
  2. `add_source(nb, module.source_url)`.
  3. For each `type` (serialized, capped): enqueue `generate_artifact`.
- `generate_artifact(artifact_id, redo_note=None)`:
  1. Load active `prompt_template` for type; build `focus_prompt` (BR6).
  2. `generate(...)` → `poll(...)` loop with backoff until `ready`/`failed`/timeout.
  3. `fetch_content(...)` → `parsers/<type>.parse(html)` → `content_json`
     (schema-validated; raise `ArtifactParseError` with reason on failure).
  4. `render/<type>` produces media files → `storage.put(...)`.
  5. Create `ArtifactVersion` (+ `MediaFile` rows), set `Artifact.status=ready`.
  6. On any exception: `Artifact.status=error`, `last_error=str`, job `failed`.
- `redo_artifact(artifact_id, note)` = `generate_artifact` with `redo_note=note`;
  never touches `published_version_id` or siblings (Constitution III.2/III.3).

### 4.4 Concurrency & resilience
- A Redis lock (`mcp:session`) serializes NotebookLM calls.
- `MAX_MODULE_FANOUT` (default 2) in-flight artifact jobs per module.
- Per-type timeouts: text 6 min, audio 20 min (config).
- Transient MCP errors: 3 retries, exp backoff (5s→20s→60s).
- `beat` runs `mcp_healthcheck` every 60s → `mcp_status` cache row.

---

## 5. Rendering design

| Type | Steps |
|------|-------|
| Slides | `content_json.slides` → `python-pptx` deck (title + bullets + notes, Academic-Modernist-styled master) → `soffice --headless --convert-to pdf` and `--convert-to png` (per slide via PDF page split with `pdftoppm`) → `MediaFile` rows `pptx`, `deck_pdf`, `slide_png[page_index]`. |
| Infographic | `content_json.diagram_source` (Mermaid or Graphviz, chosen by `diagram_kind`) → `mmdc`/`dot` → `infographic_svg` + `infographic_png`. If O1 says NotebookLM's own image is retrievable, store it as `infographic_png` and still keep an SVG fallback. |
| Report | `content_json` → HTML template (Academic Modernist reading style) → sanitised → `report_pdf` via WeasyPrint. Store sanitised HTML in `content_html` for on-screen render. |
| Audio | store `.mp3` from `fetch_binary` as `audio_mp3` (pending O2). Transcript into `content_json.transcript` if available. |
| Flashcards / Quiz | no binary; `content_json` only. |

All renderers are pure functions of `content_json` (+ assets), unit-tested
against golden files.

---

## 6. Auth design

- **Sessions**: opaque session id in cookie → server-side session store
  (Redis, TTL). Two cookie names: `sdp_admin`, `sdp_student`; distinct paths
  (`/`), `HttpOnly`, `Secure`, `SameSite=Lax`. Admin idle TTL shorter (e.g. 8h),
  student longer (e.g. 30d "remember me").
- **Guards** (`api/deps.py`): `current_admin` (401 if no valid `sdp_admin` +
  `role==admin`), `current_student`. Admin routers depend on `current_admin`
  only.
- **CSRF**: double-submit token header on all non-GET; validated in `deps.py`.
- **Rate limiting**: Redis token bucket on `/auth/login` per IP and per email.
- **Password reset** (if O6 = enabled): tokenised, single-use, 30-min TTL,
  emailed via SMTP (MailHog dev / SES prod).
- **Admin bootstrap**: `python -m app.cli seed-admin --email --name` (prompts for
  password). Idempotent.

---

## 7. Frontend architecture

- Single Vite app, two route trees: `/admin/*` (AdminLayout) and everything else
  (StudentLayout); `/admin/login` and `/login` are bare.
- `theme/` exports a Tailwind preset built from the token block in the reference
  `code.html` files + `academic_modernist/DESIGN.md`. One shared preset; admin vs
  student differ only in layout density/accent usage per the design system.
- `components/` UI kit: `Button` (primary/secondary/student variants), `Card`,
  `Chip` (status variants), `Input`, `Select`, `Modal`, `Toast`, `Tabs`,
  `SidebarNav`, `TopBar`, `ProgressBar`, `Skeleton`, `EmptyState`, `ErrorState`.
- `lib/api.ts` typed client (generated from OpenAPI or hand-written), TanStack
  Query hooks per resource; polling hooks for staging/jobs.
- Auth: `useAuth()` reads `/auth/me`; route guards redirect to the correct login;
  a student hitting `/admin/*` gets the student 404 (no admin chrome).
- Media: `<img>`/`<audio>` point at `/api/media/{key}`.
- e2e: Playwright projects `admin` and `student`; the Button Inventory (spec §6)
  is a checklist spec.

---

## 8. Environment variables (initial set)

```
# core
APP_ENV=dev|staging|prod
SESSION_SECRET=...
DATABASE_URL=postgresql+psycopg://...
REDIS_URL=redis://...
MEDIA_ROOT=/data/media
PUBLIC_BASE_URL=http://localhost:5173

# content provider
CONTENT_PROVIDER=fixture|notebooklm
MCP_ENDPOINT=...             # when notebooklm
MCP_TIMEOUT_TEXT_SEC=360
MCP_TIMEOUT_AUDIO_SEC=1200
MAX_MODULE_FANOUT=2

# auth
ADMIN_SESSION_TTL_HOURS=8
STUDENT_SESSION_TTL_DAYS=30
LOGIN_RATE_LIMIT=10/5m

# email (optional)
SMTP_URL=smtp://mailhog:1025
PASSWORD_RESET_ENABLED=true

# observability
SENTRY_DSN=
LOG_LEVEL=info
```

---

## 9. Phasing (maps to `tasks.md`)

| Phase | Outcome | Tasks |
|-------|---------|-------|
| **P0 Foundations** | Repo, tooling, compose, FastAPI + DB skeleton, SPA + theme + UI kit, CI. | T001–T006 |
| **P1 Auth & RBAC** | Separate admin/student login, sessions, guards, login pages, route protection. | T007–T012 |
| **P2 Domain & pipeline core** | Models, prompt templates + Settings API, ContentProvider + MCP client + FixtureProvider, storage, renderers, parsers, Celery orchestration, job API. | T013–T024 |
| **P3 Admin app** | Ingestion, Staging (redo modal, inspect), Publish, Editor, Settings, shell. | T025–T030 |
| **P4 Student app** | Catalog, workspace shell, all six artifact viewers, progress + My Listening + Achievements. | T031–T039 |
| **P5 Hardening & delivery** | RBAC audit, states polish, full test suites + button inventory, observability, seed/demo, infra skeleton, docs, acceptance pass. | T040–T047 |

Spikes for Open Items **O1 (infographic image)** and **O2 (audio mp3/transcript)**
are **T015a/T015b**, scheduled inside P2 before T018–T022 land the audio/
infographic paths. **O3 (DBSC account)** is an owner action, not a code task;
`FixtureProvider` keeps P0–P5 unblocked.

---

## 10. Risks carried into the plan

See `PROJECT_FRAME.md` §12. Plan-level mitigations already baked in:
`ContentProvider` abstraction, `FixtureProvider` for all dev/CI, pinned MCP
version, defensive parsers with golden-file tests, serialized MCP access, async
everything, and Open-Item spikes gating the fragile pipeline pieces.
