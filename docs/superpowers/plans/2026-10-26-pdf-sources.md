# PDF Sources for Modules Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an admin create a module from a link, one or more uploaded PDFs of any size, or both, and have NotebookLM generate every artifact from all of them.

**Architecture:**
1. The browser uploads each PDF to the backend in resumable 8 MB chunks.
2. Module creation claims the finished uploads into `module_source_file` rows.
3. The first generation job for a module builds the notebook and its sources, once, under a per-module Redis lock. It adds the link, splits any oversize PDF by page ranges, uploads each file or part through a new connector endpoint that replays NotebookLM's captured upload protocol, and waits until every source is ready.
4. Students are untouched.

**Tech Stack:** FastAPI + SQLAlchemy 2 + Alembic + Celery (backend), `pypdf` (new), Node 20 Express shim (connector), React + TypeScript + TanStack Query + Vitest + Playwright (frontend).

**Spec:** `docs/superpowers/specs/2026-10-26-pdf-sources-design.md`. Read it first; §3 holds the captured protocol.

## Global Constraints

- **Sources.** A module needs ≥1 source: a link, PDFs, or both. Any number of PDFs. Only `.pdf` files, checked by the leading bytes `%PDF-`.
- **No size limit in our app.** Over NotebookLM's per-source limit, auto-split by page ranges. Each part must be **≤ 190 MB and ≤ 450,000 words** (`source_part_max_bytes = 190 * 1024 * 1024`, `source_part_max_words = 450_000` in settings). Name each part `"<file name> (part i of n)"`.
- **Sources per notebook:** `notebook_max_sources = 300` (setting).
- **Timings and chunk sizes:**
  - Source-ready wait: 600 s per source, polling every 3 s.
  - Browser→backend chunk: 8 MB (`8 * 1024 * 1024`).
  - nginx `client_max_body_size 16m`.
  - Shim→Google pieces: 1 MB (`1048576`).
  - Abandoned-upload cleanup: 24 h after creation.
- **Live safety.** Tests never reach live NotebookLM: backend tests run with `CONTENT_PROVIDER=fixture`, which `conftest.py` already forces. Migration downgrades run only on `shikshak_test`.
- **Where tests run (no host Node):**
  - Backend: `docker compose run --rm api pytest <path> -q`
  - Shim: `docker run --rm -v "$PWD/mcp/shim:/s:ro" -w /s node:20-slim node --test test/`
  - Frontend: `cd frontend && docker build -q --target build -t sdp-fe-build . && docker run --rm sdp-fe-build npx vitest run <path>`
- **Formatting.** Format only the files you touched (`ruff`, `black` on touched Python files; `prettier --write <file>` for touched TS). Never format whole folders.
- **Error copy (exact strings, spec §8):**
  - `NotebookLM couldn't read {file}` (+ `: {reason}` when Google gives one)
  - `NotebookLM is still processing {file} after 10 minutes`
  - `{file} can't be opened (damaged or password-protected)`
  - `{file} page {n} is larger than NotebookLM's per-source limit`
  - `This module has {n} sources; NotebookLM allows at most {m} per notebook`
  - Ingestion: `Add a link or at least one PDF`, `{file} is not a PDF`, button `Uploading {i} of {n}…`
- Students never receive module PDFs: no `MediaFile` rows, and no student schema fields.

## Review Focus

1. **Two artifact jobs of a new module start at the same moment.** Sources must be added exactly once (no duplicate notebook or PDFs), and the second job must reuse the first's notebook. → Task 7, `test_parallel_jobs_add_sources_once`.
2. **A source fails, then the admin clicks Retry on one artifact.** Already-uploaded parts are not re-uploaded; only the missing or failed ones are. Jobs queued before the failure fail fast with the same message instead of re-uploading. → Task 7, `test_retry_resumes_incomplete_sources` and `test_jobs_queued_before_failure_fail_fast`.
3. **An existing link-only module (created before this feature) gets Redo or Retry.** It must not re-add its link to its existing notebook. → Task 3 migration backfill + Task 7, `test_legacy_module_skips_source_step`.
4. **The browser tab reloads or the network drops mid-upload of a large PDF.** Resume continues from `received_bytes`; a chunk at a wrong offset is rejected (409), not appended. → Task 4, `test_put_wrong_offset_conflict` and `test_resume_reports_received_bytes`.
5. **A file named `.pdf` that isn't a PDF, or a real PDF with spaces, Unicode or `../` in its name.** Non-PDFs are rejected. Odd names are stored under a safe key, but the original name is kept for display and for NotebookLM. → Task 4, `test_finished_upload_must_be_pdf` and Task 5, `test_unsafe_filename_gets_safe_key`.

---

## File Structure

| File | Responsibility |
|---|---|
| `mcp/shim/sources.js` (new) | `uploadSource()` and `sourceStatuses()`, NotebookLM's captured upload and status protocol |
| `mcp/shim/server.js` | routes `POST /source/upload`, `GET /source/status` |
| `mcp/shim/test/sources.test.mjs` (new) | protocol tests against the captured requests |
| `docker-compose.yml` | mount the `media` volume read-only into `mcp` |
| `backend/app/pipeline/pdf_split.py` (new) | `plan_parts()` and `write_parts()`: page-range splitting |
| `backend/app/models/module_source_file.py`, `backend/app/models/source_upload.py` (new) | ORM models |
| `backend/app/models/module.py` | `source_url` nullable + 4 source-step columns |
| `backend/alembic/versions/<rev>_pdf_sources.py` (new) | migration + backfill |
| `backend/app/storage/keys.py`, `backend/app/storage/service.py` | source and upload keys, `append()`, `move()` |
| `backend/app/api/admin/uploads.py` (new) | chunked upload endpoints |
| `backend/app/tasks/maintenance.py` (new) | `purge_abandoned_uploads` beat task |
| `backend/app/api/admin/courses.py`, `backend/app/schemas/courses.py` | create module with `upload_ids`; `ModuleSummary.source_files` |
| `backend/app/pipeline/provider.py`, `fixture.py`, `notebooklm_mcp.py` | `add_file_source()`, `source_statuses()` |
| `backend/app/pipeline/module_sources.py` (new) | `ensure_module_sources()`: the once-per-module source step |
| `backend/app/pipeline/orchestrator.py` | use the source step; stop creating notebooks in the request |
| `backend/app/api/admin/pipeline.py`, `staging.py`, `schemas/pipeline.py`, `schemas/staging.py` | expose `source_files` and search by file name |
| `frontend/nginx.conf` | `client_max_body_size 16m` |
| `frontend/src/admin/ingestion/chunkedUpload.ts` (new) | resumable upload client |
| `frontend/src/admin/ingestion/PdfPicker.tsx` (new) | drop zone and file list |
| `frontend/src/admin/ingestion/IngestionPage.tsx`, `frontend/src/admin/api.ts`, `useAdminApi.ts` | form integration |
| `frontend/src/admin/SourceSummary.tsx` (new) | "link · 📄 N PDFs" display used by Staging, Editor and Pipeline |

---

### Task 1: Connector: upload a file and report source status

**Files:**
- Create: `mcp/shim/sources.js`, `mcp/shim/test/sources.test.mjs`
- Modify: `mcp/shim/studio.js` (export `cookieHeader`, `remember`, `UA`, `ORIGIN`), `mcp/shim/server.js`, `mcp/Dockerfile:47` (also `COPY shim/sources.js`), `docker-compose.yml` (mcp service: add `- media:/data/media:ro`)

**Interfaces:**
- Produces (HTTP, consumed by Task 6):
  - `POST /source/upload` with `{notebook_id, path, name}` returns `200 {source_id}`. Errors use the same `studioFail` codes (401 auth, 422 rejected, 502 retryable).
  - `GET /source/status?notebook_id=` returns `200 {sources: [{id, title, status}]}`, where status is `"pending" | "ready" | "failed"`.
- Produces (JS):
  - `uploadSource(notebookId: string, filePath: string, name: string) → Promise<string /* source id */>`
  - `sourceStatuses(notebookId: string) → Promise<{id, title, status}[]>`

- [ ] **Step 1: Write failing tests** in `test/sources.test.mjs`. Stub `globalThis.fetch` and record every request; point `HOME` at a temp dir holding `.notebooklm-mcp/auth.json` = `{"cookies":"SID=x; OSID=y"}`. Stub the page-token fetch (`GET https://notebook.google.com/`) to return HTML containing `"SNlM0e":"AT"`, `"FdrFJe":"1"`, `"cfb2h":"bl"`.
  - `registers, starts, then uploads in one finalize for a small file`. With a 724-byte temp file:
    - request 1 is batchexecute with `rpcids=o4cbdc`, and its decoded params deep-equal `[[["upload-check.pdf", 3]], "NB", [2, null, [1], [1, null, null, null, null, null, null, null, null, null, [1, 3]]]]`;
    - request 2 is `POST https://notebook.google.com/upload/_/?authuser=0` with headers `x-goog-upload-command: start`, `x-goog-upload-header-content-length: 724`, `x-goog-upload-protocol: resumable`, and body `{"PROJECT_ID":"NB","SOURCE_NAME":"upload-check.pdf","SOURCE_ID":"SRC"}`;
    - request 3 goes to the returned `x-goog-upload-url` with `x-goog-upload-command: upload, finalize`, `x-goog-upload-offset: 0`, and the 724 bytes;
    - the result is `"SRC"`.

    Stubbed o4cbdc reply: `)]}'\n\n123\n[["wrb.fr","o4cbdc","[[[[\"SRC\"],\"upload-check.pdf\",[null,null,[1,2],null,3]]]]",null,null,null,"generic"]]`.
  - `uploads a 2.5 MB file in 1 MB pieces`. The upload requests carry commands `upload`, `upload`, `upload, finalize` at offsets `0`, `1048576`, `2097152`, with body lengths `1048576`, `1048576`, `524288`.
  - `throws StudioError when the final reply is not x-goog-upload-status: final`.
  - `maps source status codes`. Stub an `rLM1Ne` reply whose sources' `[null, N]` element is 5, 1, 2 and 9, and expect statuses `pending`, `pending`, `ready`, `failed`.
- [ ] **Step 2: Run them.** `docker run --rm -v "$PWD/mcp/shim:/s:ro" -w /s node:20-slim node --test test/`. Expected: the 4 new tests FAIL (module not found).
- [ ] **Step 3: Implement `mcp/shim/sources.js`.**
  - Use `rpc()` from `studio.js` for `o4cbdc` and `rLM1Ne`, with `sourcePath = /notebook/<id>`.
  - Use the captured `rLM1Ne` params exactly: `[nb, null, [2, null, [1], [1, null, null, null, null, null, null, null, null, null, [1, 3]]], null, 1, [[null, null, []]]]`.
  - Sources are at `result[0][1]`. Each source is `[[id], title, meta, [null, statusCode], …]`. Status codes: `2` → ready, `1` or `5` → pending, anything else → failed.
  - Upload requests send `Cookie: cookieHeader("notebook.google.com")`, `User-Agent: UA`, `Origin: ORIGIN`, `Referer: ORIGIN + "/"`, and call `remember(res)`.
  - Read the file with `fs.promises.open` and read only the current piece's byte range; never read the whole file into memory. Piece size is `1048576`.
- [ ] **Step 4: Add the routes in `server.js`**, using `studioFail` for errors and setting `lastOkAt` on success. Add `sources.js` to the Dockerfile COPY line, and mount the media volume in `docker-compose.yml`.
- [ ] **Step 5: Run the shim tests.** Expected: all pass (33 existing + 4 new).
- [ ] **Step 6: Commit.** `git commit -m "Connector: upload PDF sources with NotebookLM's resumable protocol"`

---

### Task 2: Page-range PDF splitter

**Files:**
- Create: `backend/app/pipeline/pdf_split.py`, `backend/tests/test_pdf_split.py`
- Modify: `backend/pyproject.toml` (add `"pypdf>=5.0,<6"`), `backend/app/config.py` (add the 3 settings from Global Constraints), then rebuild the api, worker and beat images.

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class PartPlan: first_page: int; last_page: int  # 1-based, inclusive`
  - `class PdfUnreadable(Exception)` — the message is the exact §8 copy for damaged files.
  - `class PageTooLarge(Exception)` — has a `page: int` attribute.
  - `plan_parts(path: Path, *, max_bytes: int, max_words: int) -> list[PartPlan]` returns `[PartPlan(1, n)]` when the whole file fits.
  - `write_parts(path: Path, parts: list[PartPlan], out_dir: Path, stem: str) -> list[Path]` writes `{stem}.part{i}.pdf` (1-based).

- [ ] **Step 1: Write failing tests.** Build test PDFs in a tmp dir with pypdf. Each page holds N words as text, and an image stream controls the byte size where needed.
  - `test_small_pdf_is_one_part` → `[PartPlan(1, 3)]`.
  - `test_split_by_words`: 5 pages × 100 words, `max_words=250` → `[(1,2),(3,4),(5,5)]`.
  - `test_split_by_bytes`: 4 pages of about 300 KB each, `max_bytes=700_000` → every written part's `stat().st_size <= 700_000`, and the parts cover pages 1–4 exactly once.
  - `test_scanned_pages_count_zero_words`: image-only pages produce no word-based splits.
  - `test_single_page_over_limit_raises`: `PageTooLarge` with `page == 2`.
  - `test_encrypted_or_corrupt_raises_unreadable`: a truncated file and an encrypted file both raise `PdfUnreadable`.
  - `test_write_parts_preserves_page_count`: the sum of pages across the parts equals the original page count.
- [ ] **Step 2: Run.** `docker compose run --rm api pytest tests/test_pdf_split.py -q`. Expected: FAIL (import error).
- [ ] **Step 3: Implement.** Use a greedy loop over pages:
  - Accumulate words (`len(page.extract_text().split())`, with `None` treated as 0) and an estimated size (the byte size of a single-page PDF written for that page).
  - Close the current part before the page that would exceed either limit.
  - Because shared resources make estimates inexact, `write_parts` re-checks each written part's real size. If a part is over `max_bytes`, split that range in half and recurse; a 1-page part that is still too big raises `PageTooLarge`.
- [ ] **Step 4: Run tests.** Expected: PASS.
- [ ] **Step 5: Commit.** `git commit -m "Backend: split oversize PDFs by page ranges"`

---

### Task 3: Data model and migration

**Files:**
- Create: `backend/app/models/module_source_file.py`, `backend/app/models/source_upload.py`, `backend/alembic/versions/<rev>_pdf_sources.py`
- Modify: `backend/app/models/module.py`, `backend/app/models/__init__.py`, `backend/app/models/enums.py` (add `SourceUploadStatus`: `receiving`, `complete`, `claimed`)
- Test: `backend/tests/test_models.py`, `backend/tests/test_db.py`

**Interfaces:**
- Produces:
  - `ModuleSourceFile`:
    - `id: UUID`, `module_id: UUID` (FK, cascade), `order_index: int`, `file_name: str(512)`, `size_bytes: int(BigInteger)`, `checksum_sha256: str(64)`, `storage_key: str(1024)`, `page_count: int`
    - `parts: list[dict]` (JSONB, default `[]`); each item is `{"first_page": int, "last_page": int, "storage_key": str, "notebooklm_source_id": str | None}`
    - `created_at`
    - Relationship `Module.source_files` is ordered by `order_index`, with cascade `all, delete-orphan`.
  - `SourceUpload`: `id`, `admin_id` (FK user), `file_name`, `size_bytes`, `received_bytes` (default 0), `storage_key`, `status: SourceUploadStatus`, `created_at`.
  - `Module` changes:
    - `source_url: str | None`
    - new `notebooklm_link_source_id: str | None`, `sources_ready_at: datetime | None`, `sources_error: str | None`, `sources_failed_at: datetime | None`

- [ ] **Step 1: Write failing tests.**
  - `test_module_without_link_with_source_files` (persist and reload, ordering).
  - `test_source_upload_defaults` (`received_bytes == 0`, `status == receiving`).
  - `test_migration_backfills_sources_ready_for_existing_notebooks`: at the previous revision, insert a module with a `notebooklm_notebook_id`; upgrade; check `sources_ready_at IS NOT NULL`. A module with no notebook stays NULL.
- [ ] **Step 2: Run.** `docker compose run --rm api pytest tests/test_models.py tests/test_db.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement the models and migration.** The migration:
  - creates the two tables and the `source_upload_status` enum;
  - adds the 4 module columns;
  - runs `alter_column source_url nullable=True`;
  - runs `UPDATE module SET sources_ready_at = now() WHERE notebooklm_notebook_id IS NOT NULL`.

  The downgrade reverses these. Before making `source_url` NOT NULL again it deletes modules whose `source_url IS NULL`, and a comment in the downgrade says so.
- [ ] **Step 4: Run tests, plus up/down on the test DB.** `docker compose run --rm -e DATABASE_URL=postgresql+psycopg://shikshak:shikshak@postgres:5432/shikshak_test api sh -c "alembic upgrade head && alembic downgrade -1 && alembic upgrade head"`. Expected: tests PASS and the migration round-trips cleanly.
- [ ] **Step 5: Commit.** `git commit -m "Backend: module source files, uploads, source-step columns"`

---

### Task 4: Chunked upload API, storage support, cleanup

**Files:**
- Create: `backend/app/api/admin/uploads.py`, `backend/app/schemas/uploads.py`, `backend/app/tasks/maintenance.py`, `backend/tests/integration/test_admin_uploads.py`
- Modify:
  - `backend/app/storage/keys.py`: `upload_key(upload_id) -> "uploads/{id}.pdf"` and `source_key(course_id, module_id, order_index, safe_stem, part=None)` → `courses/{c}/modules/{m}/sources/{order:02d}-{safe_stem}.pdf` or `….part{i}.pdf`
  - `backend/app/storage/service.py`: `append(key, offset: int, data: bytes) -> int` (new size; raises `ValueError` if `offset != current size`), `move(src_key, dst_key) -> None`, `sha256(key) -> str` (streamed)
  - `backend/app/main.py` (register the router)
  - `backend/app/tasks/celery_app.py` (beat entry `"uploads-purge-hourly": {"task": "app.tasks.purge_abandoned_uploads", "schedule": crontab(minute=15)}`)
  - `frontend/nginx.conf` (`client_max_body_size 16m;` in `location /api/`)
  - Test: `backend/tests/test_storage.py`

**Interfaces:**
- Produces (admin-only, CSRF like the other admin writes):
  - `POST /api/admin/uploads` with `{file_name: str(1..512), size_bytes: int > 0}` → `201 {upload_id, chunk_size: 8388608}`
  - `PUT /api/admin/uploads/{id}?offset=N` with a raw `application/octet-stream` body (≤ 16 MB) → `200 {received_bytes}`. A wrong offset gives `409 {"code":"offset_mismatch","received_bytes":R}`.
  - When `received_bytes == size_bytes`:
    - if the file starts with `%PDF-`, status becomes `complete`;
    - otherwise the file is deleted and the response is `422 {"code":"not_pdf","message":"{file_name} is not a PDF"}`.
  - `GET /api/admin/uploads/{id}` → `{received_bytes, status}`. Another admin's upload gives 404.
  - Celery task `purge_abandoned_uploads()` deletes non-`claimed` uploads older than 24 h, along with their files.

- [ ] **Step 1: Write failing tests.**
  - `test_upload_in_chunks_completes`
  - `test_put_wrong_offset_conflict`
  - `test_resume_reports_received_bytes`
  - `test_finished_upload_must_be_pdf`
  - `test_student_cannot_upload` (403)
  - `test_other_admin_cannot_see_upload` (404)
  - `test_purge_deletes_old_unclaimed_only`: a claimed or recent upload is kept.
  - In `test_storage.py`: `test_append_and_move`, `test_append_wrong_offset_raises`.
- [ ] **Step 2: Run.** `docker compose run --rm api pytest tests/integration/test_admin_uploads.py tests/test_storage.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.** Read the PUT body with `await request.body()`; chunks are ≤ 16 MB, so whole-file buffering never happens.
- [ ] **Step 4: Run tests.** Expected: PASS.
- [ ] **Step 5: Commit.** `git commit -m "Backend: resumable admin PDF uploads + hourly cleanup"`

---

### Task 5: Create module with a link and/or PDFs

**Files:**
- Modify:
  - `backend/app/schemas/courses.py`: `ModuleCreateRequest.source_url: str | None = Field(None, max_length=2048)` and `upload_ids: list[uuid.UUID] = []`. A model validator raises 422 `no_source` with `"Add a link or at least one PDF"` when both are empty.
  - `ModuleSummary`: `source_url: str | None`, `source_files: list[SourceFileOut]`.
  - `backend/app/api/admin/courses.py:150-199`
  - `backend/app/pipeline/orchestrator.py:197-248` (`start_module_generation`)
- Create: `SourceFileOut` in `backend/app/schemas/courses.py`: `{file_name: str, size_bytes: int, part_count: int}`
- Test: `backend/tests/integration/test_admin_courses.py`, `backend/tests/integration/test_access_control.py`

**Interfaces:**
- Consumes: `SourceUpload`, `ModuleSourceFile` (Task 3); `Storage.move`, `Storage.sha256`, `source_key` (Task 4).
- Produces:
  - `create_module` claims each upload: it must be `complete`, owned by this admin, and not yet claimed, otherwise 422 `bad_upload`. For each upload it moves the file to `source_key(...)`, creates a `ModuleSourceFile` (`page_count` read with pypdf, `parts=[]`), and sets the upload to `claimed`.
  - `source_type = detect_source_type(url)` if there is a link, otherwise `ModuleSourceType.pdf`.
  - `start_module_generation()` **no longer calls the provider.** It sets `module.notebooklm_notebook_id = None`, `notebooklm_link_source_id = None`, `sources_ready_at = None`, `sources_error = None`, `sources_failed_at = None`, and clears every part's `notebooklm_source_id`. This keeps today's "Re-run all builds a fresh notebook" behaviour, which the source step then performs.

- [ ] **Step 1: Write failing tests.**
  - `test_create_module_link_only` (unchanged response plus `source_files == []`)
  - `test_create_module_pdfs_only` (`source_type == "pdf"`, two `source_files` in upload order)
  - `test_create_module_link_and_pdfs`
  - `test_create_module_needs_a_source` (422 `no_source`)
  - `test_cannot_claim_incomplete_or_foreign_upload` (422 `bad_upload`)
  - `test_unsafe_filename_gets_safe_key`: `"../Ünï cödé notes.pdf"` → the key matches `sources/00-[A-Za-z0-9._-]+\.pdf$`, and `file_name` is unchanged.
  - `test_create_module_makes_no_provider_calls`: spy on the FixtureProvider.
  - In `test_access_control.py`: `test_student_cannot_fetch_module_pdf`. `GET /api/media/{storage_key}` as a student and as an anonymous client both return 404.
- [ ] **Step 2: Run.** `docker compose run --rm api pytest tests/integration/test_admin_courses.py tests/integration/test_access_control.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.** `safe_stem`: NFKD-normalise, ASCII-fold, replace runs of characters outside `[A-Za-z0-9._-]` with `-`, strip leading `.` and `-`, cap at 80 characters, and use `"file"` if the result is empty.
- [ ] **Step 4: Run tests and the whole backend suite.** `docker compose run --rm api pytest -q`. Expected: PASS. Existing tests that assert a notebook was created at module creation move to the generation path in Task 7; update them there, not here (mark them `xfail(strict=True, reason="moved to source step, Task 7")` in this commit).
- [ ] **Step 5: Commit.** `git commit -m "Backend: create modules from a link and/or uploaded PDFs"`

---

### Task 6: Provider: file sources and source status

**Files:**
- Modify: `backend/app/pipeline/provider.py`, `backend/app/pipeline/notebooklm_mcp.py`, `backend/app/pipeline/fixture.py`
- Test: `backend/tests/test_notebooklm_mcp_provider.py`, `backend/tests/test_fixture_provider.py`

**Interfaces:**
- Consumes: shim `POST /source/upload`, `GET /source/status` (Task 1).
- Produces (on the `ContentProvider` protocol):
  - `add_file_source(self, nb: NotebookRef, path: str, display_name: str) -> SourceRef`. `path` is the absolute storage path, which is the same inside the mcp container because the volume is mounted at `/data/media`.
  - `source_statuses(self, nb: NotebookRef) -> dict[str, SourceState]`, where `SourceState` is a new `StrEnum` in `provider.py`: `pending`, `ready`, `failed`.
  - `NotebookLmMcpProvider` calls both through `_locked` (the session lock). The upload request uses `timeout=None`, since uploads are bounded by Google, not by us.
  - `FixtureProvider` returns `SourceRef(f"fixture-file-{slug}")` and reports every known id as `ready`. It records the calls in `self.calls` for tests.

- [ ] **Step 1: Write failing tests** with an `httpx.MockTransport`:
  - `test_add_file_source_posts_path_and_name`
  - `test_source_statuses_maps_shim_reply`
  - `test_add_file_source_422_is_provider_error`
  - `test_fixture_file_sources_are_ready`
- [ ] **Step 2: Run.** `docker compose run --rm api pytest tests/test_notebooklm_mcp_provider.py tests/test_fixture_provider.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit.** `git commit -m "Backend: provider support for file sources and source status"`

---

### Task 7: The once-per-module source step

**Files:**
- Create: `backend/app/pipeline/module_sources.py`, `backend/tests/test_module_sources.py`
- Modify: `backend/app/pipeline/orchestrator.py:378-383`. Replace the lazy "create notebook + add_source" block with `nb = ensure_module_sources(provider, module.id, job_created_at=job.created_at)`, followed by `session.refresh(module)`.
- Modify: the tests marked `xfail` in Task 5 (rewrite them against the source step).

**Interfaces:**
- Consumes: Tasks 2, 3 and 6.
- Produces:
  - `class SourceStepError(ProviderError)` (not transient, so Celery won't auto-retry it).
  - `ensure_module_sources(provider: ContentProvider, module_id: uuid.UUID, *, job_created_at: datetime) -> NotebookRef`

**Behaviour, in order:**
1. Hold the Redis lock `module-sources:{module_id}` (`timeout=7200`, `blocking_timeout=7200`), using `redis.Redis.from_url(settings.redis_url)`.
2. Work in its own `session_scope()` and commit after every step, so parallel jobs see progress.
3. If `sources_ready_at` is set, return the notebook.
4. If `sources_failed_at` is set and `job_created_at < sources_failed_at`, raise `SourceStepError(module.sources_error)`. This is the fail-fast case.
5. Otherwise clear `sources_error` and `sources_failed_at`, then:
   1. Create the notebook if `notebooklm_notebook_id` is missing.
   2. Add the link if there is one and `notebooklm_link_source_id` is missing.
   3. For each source file with an empty `parts`, run `plan_parts`/`write_parts` (using `source_key(..., part=i)`; a single-part file uses the original key with no copy) and save `parts`.
   4. Count the total sources. If it is over `notebook_max_sources`, raise the §8 "too many" message.
   5. Upload each part whose `notebooklm_source_id` is missing, with `display_name` = the file name, or `"{file_name} (part {i} of {n})"` when n > 1.
   6. Poll `source_statuses` every 3 s until every id is `ready`, with a 600 s deadline per source counted from the moment it was added.
      - A `failed` id raises `NotebookLM couldn't read {display_name}`.
      - Reaching the deadline raises `NotebookLM is still processing {display_name} after 10 minutes`; the id is kept, so a Retry only waits again.
      - On a failed id, clear that part's id so a Retry re-uploads it.
6. Set `sources_ready_at`.
7. Map `PdfUnreadable` to the §8 damaged-file message and `PageTooLarge` to the §8 page message.
8. On any `SourceStepError`, record `sources_error` and `sources_failed_at = now()`, commit, then re-raise.

- [ ] **Step 1: Write failing tests** (FixtureProvider, with spies and a fake clock for the waits):
  - `test_link_and_pdfs_added_once_then_ready`
  - `test_parallel_jobs_add_sources_once`: two threads call it at once; the provider sees exactly 1 notebook and 1 upload per part.
  - `test_oversize_pdf_uploaded_as_named_parts`: with lowered limits, the display names are `"book.pdf (part 1 of 2)"` and `"book.pdf (part 2 of 2)"`.
  - `test_retry_resumes_incomplete_sources`: the first run fails on part 2, and the second only uploads part 2.
  - `test_jobs_queued_before_failure_fail_fast`: no provider calls; the same message.
  - `test_legacy_module_skips_source_step`: `sources_ready_at` is set, so no calls are made.
  - `test_too_many_sources_message`
  - `test_processing_timeout_message`
  - `test_damaged_pdf_message`
  - `test_rerun_all_rebuilds_notebook`: after `start_module_generation`, the next job creates a new notebook and re-uploads.
  - `test_artifact_error_shows_source_message`: through `run_artifact_generation`, `artifact.last_error` equals the §8 copy.
- [ ] **Step 2: Run.** `docker compose run --rm api pytest tests/test_module_sources.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the whole backend suite.** `docker compose run --rm api pytest -q`. Expected: all PASS, with no `xfail` left from Task 5.
- [ ] **Step 5: Commit.** `git commit -m "Backend: add a module's link and PDFs to NotebookLM once, before generating"`

---

### Task 8: Show sources on admin pages (API + shared component)

**Files:**
- Modify: `backend/app/schemas/staging.py` (`StagingModuleOut.source_url: str | None`, `source_files: list[SourceFileOut]`), `backend/app/api/admin/staging.py`, `backend/app/schemas/pipeline.py` (same two fields), `backend/app/api/admin/pipeline.py:40` (search also matches `ModuleSourceFile.file_name ILIKE` via an `EXISTS` subquery)
- Create: `frontend/src/admin/SourceSummary.tsx`, `frontend/src/admin/SourceSummary.test.tsx`
- Modify: `frontend/src/admin/api.ts` (types: `source_url: string | null`, `source_files: SourceFile[]`), `frontend/src/admin/staging/api.ts`, `frontend/src/admin/staging/StagingPage.tsx` (Sources line under the title), `frontend/src/admin/editor/ModuleRow.tsx:71-73`, `frontend/src/admin/ingestion/PipelinePage.tsx` (source column)
- Test: `backend/tests/integration/test_admin_pipeline.py` (or the existing pipeline test file), `test_admin_staging.py`

**Interfaces:**
- Produces: `<SourceSummary sourceUrl={string | null} files={SourceFile[]} />`, which renders:
  - the link text, truncated, when there is one;
  - `📄 {n} PDF` or `📄 {n} PDFs`, with `title` = the names joined by `", "`;
  - on Staging only (prop `detailed`), each name followed by ` (split into {k} parts)` when `part_count > 1`.

- [ ] **Step 1: Write failing tests.**
  - Backend: `test_staging_includes_source_files`, `test_pipeline_search_matches_pdf_name`.
  - Frontend:
    - `SourceSummary` shows the link only; `"📄 1 PDF"`; `"📄 3 PDFs"` with the title listing the names; detailed mode shows `"book.pdf (split into 3 parts)"`.
    - `ModuleRow` renders `SourceSummary` for a PDF-only module (no crash on `source_url: null`).
- [ ] **Step 2: Run** the backend and frontend commands (Global Constraints). Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run.** Expected: PASS. Also run `npx tsc -p tsconfig.app.json --noEmit` in the build image; expected: clean.
- [ ] **Step 5: Commit.** `git commit -m "Admin: show module links and PDFs on staging, editor and pipeline"`

---

### Task 9: Ingestion page: pick and upload PDFs

**Files:**
- Create: `frontend/src/admin/ingestion/chunkedUpload.ts`, `chunkedUpload.test.ts`, `PdfPicker.tsx`, `PdfPicker.test.tsx`
- Modify: `frontend/src/admin/ingestion/IngestionPage.tsx`, `IngestionPage.test.tsx`, `frontend/src/admin/api.ts` (`createModule` body: `source_url?: string`, `upload_ids?: string[]`), `frontend/src/admin/useAdminApi.ts:53-77`, `frontend/src/admin/sourceValidation.ts` (an empty link is valid)

**Interfaces:**
- Consumes: the upload endpoints (Task 4) and create-module (Task 5).
- Produces:
  - `uploadPdf(file: File, onProgress: (sent: number, total: number) => void, signal?: AbortSignal) => Promise<string /* upload_id */>`
    - POST to start; PUT 8 MB slices with `X-CSRF-Token` and `credentials: "include"`.
    - On a 409, resume from `received_bytes`.
    - Retry a failing chunk 3 times, waiting 1 s, 2 s, then 4 s.
    - A 422 `not_pdf` rejects with an `Error` whose message is the server's message.
  - `<PdfPicker files={PickedFile[]} onAdd={(files: File[]) => void} onRemove={(id) => void} onRetry={(id) => void} />`, where `PickedFile = {id, file, sent, total, state: "uploading" | "done" | "error", uploadId?, error?}`.
    - A file whose name doesn't end in `.pdf` (case-insensitive) is refused before upload with `"{name} is not a PDF"`.
  - On the Ingestion page:
    - the label becomes `"Link (optional)"` and the hint stays;
    - a `"PDF files (optional)"` section holds the picker;
    - submitting with no link and no PDFs shows `"Add a link or at least one PDF"`;
    - Create is disabled while any file is uploading, with the label `"Uploading {i} of {n}…"`;
    - the request sends `upload_ids` of the files in `done` state, in list order.

- [ ] **Step 1: Write failing tests.**
  - `chunkedUpload.test.ts` (stub fetch): slices are 8 MB with correct offsets; it resumes after a 409; it retries three times and then rejects; a 422 message surfaces.
  - `PdfPicker.test.tsx`: drop two files → two rows with name and size; `.docx` → the refusal message; ✕ removes; Retry shows on error.
  - `IngestionPage.test.tsx`: PDF-only submit sends `{upload_ids: ["u1"], source_url: undefined}`; the empty-sources message; the button is disabled with `"Uploading 1 of 2…"`; link-only submit is unchanged (the existing tests still pass).
- [ ] **Step 2: Run.** `docker run --rm sdp-fe-build npx vitest run src/admin` after rebuilding. Expected: the new tests FAIL.
- [ ] **Step 3: Implement.** Follow `IngestionPage.tsx`'s existing component and style conventions (`Input`, `Icon`, design tokens).
- [ ] **Step 4: Run** the admin tests and `tsc`. Expected: PASS, and `tsc` is clean.
- [ ] **Step 5: Commit.** `git commit -m "Admin: upload PDFs on the ingestion page"`

---

### Task 10: End-to-end test, rebuild, live checks

**Files:**
- Create: `frontend/src/e2e/admin-pdf-ingestion.spec.ts`
- Modify: `docs/spikes/notebooklm-2026-10-capture.md` (append a "Source upload (2026-10-26)" section pointing to spec §3)

- [ ] **Step 1: Write the E2E spec** (fixture provider). An admin creates a PDF-only module from `frontend/src/e2e/fixtures/sample.pdf` (a small committed PDF), reaches Staging, sees `"📄 1 PDF"`, and the artifacts reach `ready`.
- [ ] **Step 2: Run it** the same way the existing e2e specs run. Expected: PASS.
- [ ] **Step 3: Rebuild and restart.**
  1. `docker compose build api worker beat web && docker compose --profile mcp up -d --build`
  2. `docker compose run --rm api alembic upgrade head` (the dev DB, forward only)
  3. `docker compose restart web` (the nginx stale-IP 502 fix)

  Check that `curl -s localhost:5173/api/admin/auth/login` returns 405/422, not 502.
- [ ] **Step 4: Live check 1 (owner-approved).** In the admin UI, create a module in course "ML" from `upload-check.pdf` with **only Flashcards**.
  - Expected: Staging shows `📄 1 PDF`, and the flashcards are about photosynthesis.
  - Record the module id.
- [ ] **Step 5: Live check 2 (owner-approved, no generation).** Run the source step only, through `docker compose exec worker python`, calling `ensure_module_sources` on a module made with a generated PDF over 190 MB.
  - Make that PDF from repeated image pages; if pypdf output stays under the limit, lower `source_part_max_bytes` via an env override for this run.
  - Expected: two sources named `… (part 1 of 2)` and `(part 2 of 2)`, both `ready`.
  - Leave no generation running.
- [ ] **Step 6: Commit.** `git commit -m "E2E: PDF-only module; document the source upload capture"`
