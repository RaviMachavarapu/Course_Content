# NotebookLM MCP service

Wraps [`notebooklm-mcp-server`](https://github.com/moodRobotics/notebooklm-mcp-server)
so the backend worker can drive Google NotebookLM to generate the six artifacts.

> **Unofficial.** It relies on reverse-engineered internal Google APIs that can
> change without notice. Pin the version; expect occasional breakage. The
> backend always has a `FixtureProvider` fallback so development and CI never
> depend on this.

## One-time authentication

`notebooklm-mcp-server auth` opens a real Chromium window for an interactive
Google sign-in — there's no way to script this with a submitted
email/password, and this app will never ask you to type your Google password
into anything that isn't `accounts.google.com`. Since this container has no
physical screen, `entrypoint.sh` boots a virtual display (Xvfb) plus a
web-viewable VNC session (x11vnc + noVNC) so you can watch and click through
that real Chromium window from an ordinary browser tab on your own machine:

```bash
docker compose --profile mcp run --rm --service-ports mcp \
  npx -y notebooklm-mcp-server@4.0.2 auth
```

(`--service-ports` is required — `docker compose run` doesn't publish the
service's normal `ports:` otherwise.) Then open **http://localhost:6080/vnc.html**
in your regular browser, click **Connect**, and you'll see the container's
Chromium window — sign in there with the **dedicated** Google account exactly
as you would on your own machine.

On success, session cookies are written to `mcp/auth/auth.json` (git-ignored,
mounted into the container). The server auto-refreshes the rotating
`__Secure-1PSIDTS` token on startup; if the session lapses (weeks), re-run the
command above and call `refresh_auth` (Admin → Settings → NotebookLM →
Reload auth).

The same virtual display + noVNC also start when the container runs
normally (`docker compose --profile mcp up -d mcp`), so
**http://localhost:6080/vnc.html** works any time the `mcp` service is up —
handy for confirming *why* a health check is failing (an expired-session
error page, a CAPTCHA, etc.) without needing to re-run the `auth` command
just to look.

## ⚠️ DBSC limitation (Open Item O3)

Google accounts that enforce **Device Bound Session Credentials** — the default
for Workspace and most personal accounts — tie the session to device-held keys,
and exported cookies are rejected. Use a Google account **without** DBSC
enforcement, or live generation will not work. This does not block any build or
test work.

## Transport: an HTTP shim in front of a stdio server (T016)

`notebooklm-mcp-server` is stdio-only — designed to be spawned directly by an
MCP client (Claude Desktop, Cursor, etc.), not run as a network service. So
this container runs `mcp/shim/server.js`: a small Node HTTP server that
spawns the pinned `notebooklm-mcp-server` as a child process, speaks MCP to
it over stdio via the official `@modelcontextprotocol/sdk`, and re-exposes
the tool calls the backend needs as plain HTTP on `:7332`
(`app/pipeline/notebooklm_mcp.py` calls it via `MCP_ENDPOINT`).

- `POST /call {tool, args}` → `{data}` — a generic proxy to any MCP tool;
  the Python provider names the exact tool + argument shape from
  `docs/TOOLS.md` (fetched from the pinned upstream version, see below).
- `GET /health` → `{healthy, last_ok_at, detail}` — calls `notebook_list` as
  a cheap authenticated-session check (no dedicated "whoami" tool exists).
- `POST /refresh-auth` → reconnects to the MCP server so newly-rotated
  cookies (from a fresh `auth` run) are picked up without a container
  restart.

## Tools used by the backend (pinned version `4.0.2`)

Per upstream `docs/TOOLS.md` at this pin — **not yet live-verified against a
real authenticated session**, see `docs/spikes/O1-infographic.md` /
`docs/spikes/O2-audio.md`:

- `notebook_create {title}` → `{status, notebook_id, title}`
- `notebook_add_url {notebook_id, url}` → `{status, source_id}`
- `{slide_deck,flashcards,quiz,report,infographic,audio_overview}_create
  {notebook_id, source_ids, focus_prompt, ...type-specific options}` →
  `{status, artifact: {artifact_id, type, status}}` (poll for completion)
- `studio_poll {notebook_id}` → `{artifacts: [{artifact_id, title, type,
  status, content, media_url}]}` — **`media_url` is the most promising lead
  for O2 (audio) and possibly O1 (infographic image)**, but its exact
  contents (a direct file URL? auth-gated? mp3 only, or also present for
  infographic?) need a live check.
- `artifact_content_get {notebook_id, artifact_id}` → `{artifact_id, html,
  mind_map_tree}` — no image/binary field here, which is why D15
  (render our own infographic from structure) is the shipped default
  regardless of what O1 finds.
- `refresh_auth` (if exposed as an MCP tool at this pin — TOOLS.md didn't
  confirm; the shim's `/refresh-auth` reconnects either way as a fallback).

## Pinning

The exact version lives in `mcp/Dockerfile`
(`ENV NOTEBOOKLM_MCP_PACKAGE=notebooklm-mcp-server@4.0.2`) and
`mcp/shim/server.js` reads it from that env var. Bump deliberately, record
the bump in `docs/implementation.md` §Versions, and re-run the T015a/T015b
live checks — a version bump can change tool names/shapes.
