# NotebookLM MCP service

Wraps [`notebooklm-mcp-server`](https://github.com/moodRobotics/notebooklm-mcp-server)
so the backend worker can drive Google NotebookLM to generate the six artifacts.

> **Unofficial.** It relies on reverse-engineered internal Google APIs that can
> change without notice. Pin the version; expect occasional breakage. The
> backend always has a `FixtureProvider` fallback so development and CI never
> depend on this.

## One-time authentication

> **Don't use `notebooklm-mcp-server auth`.** At 4.0.2 it treats NotebookLM's
> public landing page as "signed in", exits within seconds and saves a session
> with no login in it. It also targets `notebooklm.google.com`, which now
> redirects to `notebook.google.com` ("Gemini Notebook"). Verified live on
> 2026-10-22: `docs/spikes/notebooklm-2026-10-capture.md`.

Sign in with `mcp/auth-login.mjs` instead. It opens Google's sign-in page in a
real Chromium window on the container's virtual display, waits until
`notebook.google.com` is actually signed in, and saves the session in the
connector's `auth.json` format:

```bash
docker compose --profile mcp stop mcp      # the browser and the shim share ports
docker compose --profile mcp run --rm --service-ports \
  -v "$PWD/mcp/auth-login.mjs:/auth-login.mjs:ro" mcp node /auth-login.mjs
docker compose --profile mcp up -d mcp
```

While it waits, open **http://localhost:6080/vnc.html**, click **Connect** and
sign in. Type the Google password only on Google's own page. The browser
profile is kept in `mcp/auth/browser-profile`. Re-running the command with a
still-signed-in profile just re-exports the session.

Close the browser after signing in. While it's open, it rotates the same
Google session, and the connector's copy stops working after about an hour.

`mcp/auth/` holds credentials and is git-ignored (`mcp/auth/.gitignore`).

## DBSC (Open Item O3)

Earlier sign-in failures were blamed on Google's Device Bound Session
Credentials. They were actually the address change and the broken `auth`
command above. With the new address, cookies copied out of the browser work
on this account. If a different account does enforce DBSC, the connector
can't use it.

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
  A tool that reports an error answers 422 (401 if it mentions signing in);
  a dead child or transport answers 502.
- `GET /health` → `{healthy, last_ok_at, detail}` — calls `notebook_list` as
  a cheap authenticated-session check (no dedicated "whoami" tool exists).
  While another call is running it doesn't wait: it reports from the last
  successful call (healthy if within 15 minutes, detail "busy").
- `POST /refresh-auth` → drops the in-memory rotated cookies and page token
  and restarts the connector child, so a fresh `auth` run is picked up
  without a container restart (a new sign-in in auth.json also drops them).

Connector calls run one at a time over the child's stdio (`shim/session.js`);
if the child exits, the next call starts a new one.

## What the backend uses

Notebooks and sources go through the connector's own tools, via `POST /call`:
`notebook_create`, `notebook_add_url`, `notebook_get` and `notebook_list`
(the health check).

Studio goes through the shim's `/studio/*` endpoints (`shim/studio.js`). The
connector's own Studio requests use the old format, which Google rejects with
`[3]` INVALID_ARGUMENT. These endpoints send the format the web app sends
today. Every layout and option code was recorded live, and `shim/test/`
checks the builder against all 30 recorded requests
(`docker run --rm -v "$PWD/mcp/shim:/s:ro" -w /s node:20-slim node --test test/`).

| Endpoint | Does |
|---|---|
| `POST /studio/create {notebook_id, kind, focus_prompt, options}` | Starts a generation. Returns `{artifact_id}` |
| `GET /studio/artifact?notebook_id&artifact_id` | Returns `{status, raw, html}`. Status 3 = completed, 4 = failed, 6 = slide outline waiting for review |
| `POST /studio/outline {notebook_id, artifact_id, feedback?}` | With `feedback`, revises the outline. Without it, builds the deck |
| `GET /studio/download?url=` | Downloads NotebookLM media (slide PNG/PDF/PPTX, infographic PNG, audio m4a), following redirects with the Google cookies |

Errors: 401 means the Google session needs attention. 422 means NotebookLM
rejected the request (not retried). 502 means anything else (retried).

The image patches the connector's hard-coded `BASE_URL` to
`notebook.google.com` (`mcp/Dockerfile`). The build fails if that line
changes.

## Pinning

The exact version lives in `mcp/Dockerfile`
(`ENV NOTEBOOKLM_MCP_PACKAGE=notebooklm-mcp-server@4.0.2`) and
`mcp/shim/server.js` reads it from that env var. Bump deliberately, record
the bump in `docs/implementation.md` §Versions, and re-run the T015a/T015b
live checks — a version bump can change tool names/shapes.
