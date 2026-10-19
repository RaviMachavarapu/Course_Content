# O2 — SPIKE: audio mp3 + transcript retrieval via MCP

**Status: transport verified live; the audio/transcript question itself is
still pending an authenticated session (T016, 2026-09-14).**

## Transport is now actually proven, not just documented

`docker compose --profile mcp up -d mcp` really spawns the pinned
`notebooklm-mcp-server@4.0.2` as a child process, the shim really connects
to it over stdio via the official MCP SDK, and a real tool call
(`notebook_list`, via `GET /health`) round-trips end-to-end and returns the
server's own real error:

```
$ curl http://localhost:7332/health
{"healthy":false,"last_ok_at":null,"detail":"tool notebook_list failed:
 [{\"type\":\"text\",\"text\":\"Error: Authentication expired. Run
 notebooklm-mcp-server auth to re-authenticate.\"}]"}
```

This is the *correct, expected* result before running `auth` — it proves
the entire stdio-spawn → MCP protocol → HTTP-shim chain works, and that only
the Google login step remains. Nothing about the transport, tool dispatch,
or error surfacing is hypothetical anymore.

## Question

Can the audio overview's `.mp3` and/or a time-coded transcript be obtained
via `notebooklm-mcp-server`, or only a generation handle?

## Method

Same as `O1-infographic.md`: read the pinned upstream server's own tool
documentation (`moodRobotics/notebooklm-mcp-server@4.0.2`, `docs/TOOLS.md`)
ahead of a live session, since the owner's account handoff is still pending.

## Finding (source-level, not yet live-verified)

- `audio_overview_create {notebook_id, source_ids, language, focus_prompt,
  format, length}` → `{status, artifact: {artifact_id, type, status}}` —
  a handle only, as expected; poll with `studio_poll`.
- `studio_poll {notebook_id}` → each artifact carries a `media_url` field.
  This is the concrete lead: **the mp3 is very likely fetchable from
  `media_url` once the artifact reaches `completed`.**
  `NotebookLmMcpProvider.fetch_binary` (`app/pipeline/notebooklm_mcp.py`)
  and the shim's `GET /media` endpoint (`mcp/shim/server.js`) are built on
  this assumption.
- **Transcript**: no separate transcript field or tool is documented.
  `artifact_content_get` returns `{artifact_id, html, mind_map_tree}` for
  any artifact type; for audio, `html` may or may not contain transcript
  text — not confirmed. If it doesn't, there is no path to a real
  time-coded transcript via this MCP, and the app's existing fallback
  (`app/pipeline/parsers/audio_overview.py` synthesises cue timings from
  word count when the source gives none) stays load-bearing rather than a
  gap-filler.
- **Not yet confirmed**: whether fetching `media_url` needs the MCP
  server's own session credentials (cookies it holds internally, not
  exposed via the tool interface) or is a short-lived signed URL fetchable
  with a plain GET. The shim currently assumes the latter
  (`mcp/shim/server.js`'s `/media` handler does a bare `fetch(media_url)`).
  If that's wrong, the fix is upstream-server-dependent — possibly a
  feature request to `notebooklm-mcp-server`, or fetching through the
  server's own tool interface if one exists for binary content that TOOLS.md
  didn't document.

## Decision (unchanged until live-verified)

Ship on `FixtureProvider`'s placeholder `.mp3` and synthesised transcript,
per the owner's 2026-09-04 direction — real audio fidelity is exactly what
this spike gates, and it isn't resolved yet.

## Verification checklist (manual, not in CI — do this once real auth lands)

1. `docker compose --profile mcp run --rm mcp npx -y notebooklm-mcp-server@4.0.2 auth`
2. `docker compose --profile mcp up -d mcp`
3. Create a notebook, add a real URL, call `audio_overview_create`, poll to
   `completed`.
4. `curl http://localhost:7332/media?notebook_id=...&artifact_id=...` — does
   it return real audio bytes? What's the `Content-Type`?
5. Inspect `artifact_content_get`'s `html` for that artifact — does it
   contain a transcript with any timing information?
6. Update this doc with the findings. If `media_url` fetch fails
   unauthenticated, note the exact error (401? redirect to a Google login
   page? something else) so the fix can be scoped correctly — don't guess.
7. Once confirmed, set `CONTENT_PROVIDER=notebooklm` in a dev/staging
   environment and run a real module generation end-to-end to prove the
   whole pipeline (parser, storage, audio player) against real content —
   the pipeline itself needs no changes either way (`ContentProvider` is
   already the seam).
