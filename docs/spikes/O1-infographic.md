# O1 — SPIKE: infographic image retrieval via MCP

**Status: transport verified live (see O2-audio.md); the image-retrieval
question itself is still pending an authenticated session (T016, 2026-09-14).**

## Question

Is the infographic artifact's *rendered image* retrievable via
`notebooklm-mcp-server`, or only the diagram structure?

## Method

The owner obtained MCP access (a non-DBSC Google account) but hasn't
completed the live-auth handoff yet. Rather than block, this spike reads the
pinned upstream server's own tool documentation
(`moodRobotics/notebooklm-mcp-server@4.0.2`, `docs/TOOLS.md`) to determine
what's *documented* as retrievable, ahead of confirming it against a real
session.

## Finding (source-level, not yet live-verified)

- `artifact_content_get {notebook_id, artifact_id}` → `{artifact_id, html,
  mind_map_tree}`. No image or binary field. For an infographic artifact,
  this gives the mind-map *structure* only — matches the original
  assumption behind D15.
- `studio_poll {notebook_id}` → each artifact in the result carries a
  `media_url` field, generically, for every artifact type — not documented
  as audio-only. This is new information: it's plausible an infographic's
  `media_url` points at a rendered image, which `artifact_content_get`
  doesn't expose. **Not confirmed** — TOOLS.md doesn't say what `media_url`
  contains per type, and it could just as easily be `null`/absent for
  non-audio artifacts.

## Decision (unchanged)

D15 (PROJECT_FRAME.md — owner choice, not contingent on this spike) stays
the shipped default regardless of what a live check finds: the backend
renders its own infographic from `content_json`'s structure via Graphviz
(`app/render/infographic.py`, T019, done). That renderer has no dependency
on `notebooklm-mcp-server` at all and needs no changes here.

## What a live check would add

If `studio_poll`'s `media_url` does resolve to a rendered infographic image
for a real generation, that unlocks the *optional* enhancement named in
T019/T016's AC: prefer the MCP's own image when available, falling back to
D15's render. This is additive, not a replacement — `NotebookLmMcpProvider`
already correctly returns `None` from `fetch_binary` for non-audio types
(see `app/pipeline/notebooklm_mcp.py`), so nothing regresses if this is
never revisited.

## Verification checklist (manual, not in CI — do this once real auth lands)

1. `docker compose --profile mcp run --rm mcp npx -y notebooklm-mcp-server@4.0.2 auth`
2. `docker compose --profile mcp up -d mcp`
3. Create a notebook, add a real URL, call `infographic_create`, poll to
   `completed`.
4. Inspect the completed artifact's `media_url` from `studio_poll`'s
   response directly (e.g. `curl -X POST http://localhost:7332/call -d
   '{"tool":"studio_poll","args":{"notebook_id":"..."}}'`). Is it present?
   Does it 200 with an image? Update this doc with the answer and, if
   positive, file the enhancement to `fetch_binary`/`_render_infographic`
   to prefer it.
