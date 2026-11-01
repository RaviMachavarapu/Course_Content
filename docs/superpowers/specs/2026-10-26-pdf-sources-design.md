# PDF sources for modules — design

Date: 2026-10-26 · Status: draft for owner review · Builds on branch `feature/notebooklm-studio-options` (PR #1)

## 1. Goal

On the admin Ingestion page, a module's source can be a link, one or more uploaded PDFs, or both. NotebookLM generates every artifact from all of the module's sources together. Students see only the published artifacts, as today.

## 2. Owner decisions (2026-10-26)

| # | Decision |
|---|---|
| D1 | A module needs at least one source: a link only, PDFs only, or a link plus PDFs. |
| D2 | Any number of PDFs per module. |
| D3 | **No size limit in our app.** A PDF over NotebookLM's per-source limit is **auto-split** into page-range parts, all added to the same notebook. |
| D4 | PDFs can be added only when creating a module (Ingestion page). No adding or removing on existing modules. |
| D5 | Students see artifacts only. The PDFs are never shown or served to students. |
| D6 | Only `.pdf` files are accepted. |
| D7 | The link field stays a single link and keeps accepting what it accepts today (YouTube, Google Drive, a direct .pdf link, any http(s) page). It becomes optional. |
| D8 | Admin pages that show a module's source show the link and/or the PDF names. |
| D9 | Real PDF upload to NotebookLM (approach "Option 1"), not text extraction. |
| D10 | Upload each PDF first, then create the module ("approach 1"). |

## 3. Why the connector needs new code (live check, 2026-10-26)

The pinned `notebooklm-mcp-server@4.0.2` cannot add a PDF:

- `notebook_add_local_file` does not upload the file. It extracts text with `pdf-parse` and calls `addTextSource`. It also crashes (`pdf is not a function`).
- `notebook_add_text` returns `{"status":"success","source_id":""}` and adds nothing (the notebook still has 0 sources).

### Captured NotebookLM upload (web app, notebook `6ed00249-…`, file `upload-check.pdf`, 724 bytes)

1. **Register the source:** `batchexecute` RPC `o4cbdc`, `source-path=/notebook/<nb>`.
   - Params: `[[["<file name>", 3]], "<notebook id>", [2, null, [1], [1, null, null, null, null, null, null, null, null, null, [1, 3]]]]`
   - Response: `[[[["<source id>"], "<file name>", [null, null, [<secs>, <nanos>], null, 3]]], …]`
2. **Start a resumable upload:** `POST https://notebook.google.com/upload/_/?authuser=0`.
   - Headers: `x-goog-upload-command: start`, `x-goog-upload-header-content-length: <bytes>`, `x-goog-upload-protocol: resumable`, `content-type: application/x-www-form-urlencoded;charset=UTF-8`.
   - Body: `{"PROJECT_ID":"<notebook id>","SOURCE_NAME":"<file name>","SOURCE_ID":"<source id>"}`
   - Response headers: `x-goog-upload-url` (the session address), `x-goog-upload-chunk-granularity: 1048576`, `x-goog-upload-status: active`.
3. **Send the bytes:** `POST <x-goog-upload-url>`.
   - Headers: `x-goog-upload-command: upload, finalize`, `x-goog-upload-offset: 0`.
   - Body: the file bytes.
   - Response: `x-goog-upload-status: final`, body `OK: Enqueued blob bytes to spanner queue for processing.`
4. **Processing:** the web app then polls the notebook (`rLM1Ne`) until the source is ready. That took about 5 s for the test file.

For large files, the same session accepts `upload` commands in 1 MB-multiple pieces (`x-goog-upload-offset` advancing), then a final `upload, finalize`. This is the standard Google resumable protocol. The live check of a split PDF (section 9) confirms it.

## 4. Data flow

1. **Pick files (Ingestion page).** Each selected PDF uploads to our backend immediately, in pieces with resumable progress. Only "is it a PDF" is checked; there is no size limit. Pieces are written straight to storage and never held in memory whole.
2. **Create.** `POST /api/admin/courses/{id}/modules` takes `source_url` (optional) and `upload_ids` (optional), and needs at least one. It creates the module, moves each finished upload to `courses/<course>/modules/<module>/sources/<n>-<file name>`, records a `module_source_file` row, and returns immediately. Adding sources to NotebookLM no longer happens inside this request.
3. **Background job (per module, before the first artifact's Studio request):**
   1. Create the notebook.
   2. Add the link with `notebook_add_url`, if there is one.
   3. For each PDF, split if needed (section 5), then upload each file or part with the captured protocol.
   4. Wait until NotebookLM reports every source ready (up to 10 min per source).
   5. Generate the artifacts as today.

   The notebook-and-sources step runs once per module, guarded by the existing `mcp:session` lock and the module's `notebooklm_notebook_id`, so parallel artifact jobs don't add sources twice.
4. **Rebuild.** If a module's notebook is missing (the existing lazy re-create path in `orchestrator._generate`), the job re-adds the link and re-uploads the PDFs from storage.

## 5. Auto-split (D3)

- NotebookLM's published per-source limits are 200 MB and 500,000 words. A PDF over either limit is split by page ranges into parts that each stay under **190 MB** and **450,000 words** (safety margins). Both values live in settings.
- Word counts come from the text of each page (`pypdf`). A page with no extractable text (a scan) counts as 0 words, so scans are split by size only.
- Parts are uploaded in page order and named `"<file name> (part i of n)"`. No page is dropped or duplicated.
- If one page alone exceeds the size limit, that is an error for that file (section 8).
- The sources-per-notebook cap is **not** something we can raise. It is checked before uploading, and the configured value defaults to 300 (the account is PRO). Going over it is an error (section 8).

## 6. Backend

- **Model `ModuleSourceFile`** (new table `module_source_file`):
  - `id`, `module_id` (FK, cascade), `order_index`, `file_name`, `size_bytes`, `checksum_sha256`, `storage_key`, `page_count`, `parts` (JSON list of `{first_page, last_page, notebooklm_source_id}`), `created_at`.
- **Module:**
  - `source_url` becomes nullable.
  - `source_type` is `pdf` when there is no link (the existing enum value). Otherwise it stays as `detect_source_type(link)`.
- **Uploads:**
  - New model `SourceUpload` (`id`, `admin_id`, `file_name`, `size_bytes`, `received_bytes`, `tmp_key`, `status`, `created_at`).
  - Admin-only endpoints:
    - `POST /api/admin/uploads` with `{file_name, size_bytes}` → `{upload_id, chunk_size}`.
    - `PUT /api/admin/uploads/{id}?offset=N` with the raw chunk body → `{received_bytes}`.
    - `GET /api/admin/uploads/{id}` → `{received_bytes}`, used to resume.
  - The upload is finished when `received_bytes == size_bytes` and the file starts with `%PDF-`.
  - A Celery beat task deletes uploads older than 24 h that no module claimed.
- **Storage:** add `put_stream`/append support so chunks go to disk without buffering the whole file. Module PDFs have **no `MediaFile` row**, so `GET /api/media/...` (which needs one) can never serve them.
- **Provider protocol:**
  - `add_source(nb, url)` stays.
  - New `add_file_source(nb, path, display_name) -> SourceRef` and `wait_sources_ready(nb, source_ids, timeout)`.
  - `FixtureProvider` implements both without network calls.
- **Connector shim** (`mcp/shim`):
  - New `POST /source/upload {notebook_id, path, name}` runs the captured 3-step protocol with the session cookies, sending files over 1 MB in 1 MB pieces.
  - New `GET /source/status?notebook_id=` reports per-source readiness.
  - The mcp container gets the `media` volume mounted read-only at the same path (`/data/media`), so the backend passes a storage path, not bytes.
- **nginx:** `client_max_body_size` set to fit one upload chunk (the chunk size is 8 MB; the limit is set to 16m).
- **Migration:** a new table, plus making `module.source_url` nullable. Down-migrations are tested on `shikshak_test` only.

## 7. Admin frontend

- **Ingestion page:**
  - "Source URL" → **"Link (optional)"**, with the same validation when filled.
  - New **"PDF files (optional)"** drop zone with a **Choose PDFs** button, allowing multiple files.
  - Each file row shows its name, size, a progress bar, **✕** to remove, and **Retry** on failure. A non-PDF file is refused with a message naming the file.
  - **Create** requires a link or at least one PDF ("Add a link or at least one PDF"). It is disabled while uploads run and shows "Uploading 2 of 3…".
- **Staging:** a **Sources** line lists the link and the PDF names, with "split into N parts" where applicable.
- **Editor module rows and Pipeline table:** show the link and/or "📄 N PDFs" (the names in a tooltip). Pipeline search also matches PDF names.
- `apiFetch` stays JSON-only. The chunk upload uses its own small `fetch` wrapper (raw body, the same credentials and CSRF handling).

## 8. Errors

Upload or processing failures mark the module's artifacts `error`, with the message below, on Staging. The existing Retry re-runs the source step if the notebook's sources are incomplete.

| Situation | Message |
|---|---|
| NotebookLM rejects a file | `NotebookLM couldn't read <file>` + Google's reason, if any |
| A source not ready after 10 min | `NotebookLM is still processing <file> after 10 minutes` |
| Corrupt or password-protected PDF | `<file> can't be opened (damaged or password-protected)` |
| A single page over the size limit | `<file> page <n> is larger than NotebookLM's per-source limit` |
| Too many sources | `This module has <n> sources; NotebookLM allows at most <m> per notebook` |
| NotebookLM signed out | The existing sign-in status, unchanged |

On the Ingestion page, chunk failures retry automatically 3 times, then show **Retry** on that file.

## 9. Testing

None of these tests touch the live NotebookLM account; backend tests are forced to use the fixture provider.

- **Shim:** the upload sends exactly the captured requests (§3), including chunked large files and `upload, finalize` on the last piece. The status endpoint parses ready and processing states.
- **Splitting:** small generated PDFs with lowered limits. Checks that parts stay under the size and word limits, that page ranges are contiguous, that no page is lost, the part names, scan PDFs, and a single oversize page.
- **Backend:**
  - Chunked upload and resume.
  - The `%PDF-` check.
  - At least one source; link-only, PDF-only and both.
  - Admin-only access to the upload endpoints.
  - **A student cannot fetch a module PDF.**
  - Abandoned-upload cleanup.
  - The orchestrator adds sources once per module; rebuild re-uploads.
  - The migration up and down, on `shikshak_test`.
- **Frontend:** the file list, progress, remove, non-PDF refusal, Create blocked until uploads finish, and the at-least-one-source message. E2E: create a PDF-only module and reach Staging.
- **Live checks at the end (owner-approved):**
  1. A module from the small test PDF with **one** Flashcards artifact (about 10% of a 5-hour window).
  2. A PDF large enough to split into 2 parts, uploaded with **no generation**.

## 10. Out of scope

- Adding or removing PDFs on existing modules.
- Viewing or downloading PDFs (admins and students).
- File types other than PDF.
- More than one link per module.
