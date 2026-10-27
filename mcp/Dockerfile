# syntax=docker/dockerfile:1
# NotebookLM MCP service (T016).
#
# This is an UNOFFICIAL, reverse-engineered integration (see mcp/README.md and
# docs/PROJECT_FRAME.md §12). `notebooklm-mcp-server` is stdio-only — it's
# built to be spawned directly by an MCP client (Claude Desktop, Cursor,
# etc.), not to run as a network service. `mcp/shim/server.js` is that
# client: it spawns the pinned server as a child process, speaks MCP to it
# over stdio via the official SDK, and re-exposes the handful of tool calls
# our backend needs as plain HTTP on :7332 (`MCP_ENDPOINT` in `app/config.py`).

FROM node:20-slim

# Chromium runtime deps for the (interactive, for `auth`) Google login the
# MCP server performs, plus a virtual display + web-viewable VNC session
# (see entrypoint.sh) since this container has no physical screen.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates fonts-liberation libasound2 libatk-bridge2.0-0 \
        libatk1.0-0 libc6 libcairo2 libcups2 libdbus-1-3 libexpat1 \
        libgbm1 libglib2.0-0 libgtk-3-0 libnspr4 libnss3 libpango-1.0-0 \
        libx11-6 libxcomposite1 libxdamage1 libxext6 libxfixes3 libxkbcommon0 \
        libxrandr2 wget xdg-utils \
        xvfb x11vnc novnc websockify x11-utils \
    && rm -rf /var/lib/apt/lists/*

# Pinned upstream version — bump deliberately, record the bump in
# docs/implementation.md §Versions, and re-run the T015a/T015b live checks.
ENV NOTEBOOKLM_MCP_PACKAGE=notebooklm-mcp-server@4.0.2
# Pre-fetch it into npx's cache so the first request doesn't pay a cold
# download; also fails the build loudly if the pin no longer resolves.
RUN npx -y ${NOTEBOOKLM_MCP_PACKAGE} --version || true

# NotebookLM moved to https://notebook.google.com ("Gemini Notebook");
# notebooklm.google.com now redirects there, and the server's HTTP client drops
# the Cookie header on that cross-host redirect, so every call came back
# "Authentication expired" (verified live 2026-10-22). The pinned server
# hard-codes the old address with no override, so patch it in the cached
# package — and fail the build if the line isn't there (e.g. after a bump).
RUN F="$(find /root/.npm/_npx -path '*/node_modules/notebooklm-mcp-server/dist/index.js' | head -1)" \
    && grep -q 'BASE_URL = "https://notebooklm.google.com"' "$F" \
    && sed -i 's#BASE_URL = "https://notebooklm.google.com"#BASE_URL = "https://notebook.google.com"#' "$F" \
    && grep -q 'BASE_URL = "https://notebook.google.com"' "$F"

WORKDIR /srv/shim
COPY shim/package.json .
RUN npm install --omit=dev
COPY shim/server.js shim/studio.js shim/sources.js shim/tools.js ./

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 7332 6080
ENTRYPOINT ["/entrypoint.sh"]
CMD ["node", "server.js"]
