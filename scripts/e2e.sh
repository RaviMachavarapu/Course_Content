#!/usr/bin/env bash
# End-to-end tests on an isolated, throwaway stack.
#
#   scripts/e2e.sh [--grep RE] [--project student|admin] [--repeat-each N] [--keep]
#                  [-- extra playwright args]
#
# Brings up the dev stack as compose project `shikshak-e2e` with
# docker-compose.e2e.yml (FixtureProvider only, own volumes and networks, no
# host ports shared with dev; web on 127.0.0.1:5174, mailhog on :8026),
# migrates, seeds the admin the specs sign in with, runs the Playwright suite in
# the official Playwright image (version = frontend's @playwright/test) and
# tears everything down with `down -v` unless --keep.
#
# Output (git-ignored): e2e-results/report (HTML report; open index.html, or
# `npx playwright show-report e2e-results/report`), e2e-results/test-results
# (traces of failed tests: `npx playwright show-trace <trace.zip>`).
#
# Never reads docker-compose.override.yml or a root .env: the e2e stack always
# runs on the dev defaults with CONTENT_PROVIDER=fixture.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PROJECT=shikshak-e2e
RESULTS="$ROOT/e2e-results"
PW_CONTAINER="$PROJECT-playwright"
ADMIN_EMAIL=admin@example.com
ADMIN_PASSWORD=dev-admin-password-123

usage() { sed -n '2,19p' "$0" | sed 's/^# \{0,1\}//'; }

KEEP=0
PW_ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --grep) PW_ARGS+=(--grep "$2"); shift 2 ;;
    --project) PW_ARGS+=(--project "$2"); shift 2 ;;
    --repeat-each) PW_ARGS+=(--repeat-each "$2"); shift 2 ;;
    --keep) KEEP=1; shift ;;
    -h|--help) usage; exit 0 ;;
    --) shift; PW_ARGS+=("$@"); break ;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

# Only these two files, this project name, no .env, no profiles from the caller.
unset COMPOSE_FILE COMPOSE_PROFILES COMPOSE_PROJECT_NAME
compose() {
  docker compose -p "$PROJECT" --project-directory "$ROOT" --env-file /dev/null \
    -f "$ROOT/docker-compose.yml" -f "$ROOT/docker-compose.e2e.yml" "$@"
}

PW_VERSION="$(awk '/"node_modules\/@playwright\/test": \{/ {f=1} f && /"version":/ {gsub(/[",]/, "", $2); print $2; exit}' \
  "$ROOT/frontend/package-lock.json")"
if [[ -z "$PW_VERSION" ]]; then
  echo "could not read the @playwright/test version from frontend/package-lock.json" >&2
  exit 1
fi
PW_IMAGE="mcr.microsoft.com/playwright:v$PW_VERSION-noble"

cleanup() {
  local code=$?
  docker rm -f "$PW_CONTAINER" >/dev/null 2>&1 || true
  if [[ $KEEP -eq 1 ]]; then
    echo "--keep: stack left running (web http://127.0.0.1:5174, mailhog http://127.0.0.1:8026)."
    echo "Tear down: docker compose -p $PROJECT -f docker-compose.yml -f docker-compose.e2e.yml down -v"
  else
    echo "Tearing down the e2e stack ..."
    compose down -v --remove-orphans >/dev/null 2>&1 || true
  fi
  exit "$code"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

echo "== Building and starting the e2e stack ($PROJECT, fixture provider) =="
compose build
compose up -d --wait postgres redis
compose run --rm -T api alembic upgrade head
compose run --rm -T api python -m app.cli seed-admin \
  --email "$ADMIN_EMAIL" --name "E2E Admin" --password "$ADMIN_PASSWORD"
compose run --rm -T api python -m app.cli seed-prompts
# Every default-profile service (never mcp), waiting for the healthchecks.
compose up -d --wait --wait-timeout 300

echo "== Playwright $PW_VERSION =="
rm -rf "$RESULTS"
mkdir -p "$RESULTS"
docker volume create "$PROJECT-npm-cache" >/dev/null

# The suite runs from a copy of the specs + config with only @playwright/test
# installed (the host's node_modules may be for another OS). It reaches web
# over the e2e `edge` network (as http://localhost:5174, see below) and mailhog
# over `default`.
docker rm -f "$PW_CONTAINER" >/dev/null 2>&1 || true
docker create --name "$PW_CONTAINER" --init --ipc=host \
  --network "${PROJECT}_edge" \
  -e E2E_BASE_URL=http://localhost:5174 \
  -e E2E_MAILHOG_URL=http://mailhog:8025 \
  -e E2E_ADMIN_EMAIL="$ADMIN_EMAIL" \
  -e E2E_ADMIN_PASSWORD="$ADMIN_PASSWORD" \
  -e PLAYWRIGHT_HTML_OUTPUT_DIR=/results/report \
  -e PLAYWRIGHT_HTML_OPEN=never \
  -e PW_VERSION="$PW_VERSION" \
  -v "$ROOT/frontend:/src:ro" \
  -v "$RESULTS:/results" \
  -v "$PROJECT-npm-cache:/root/.npm" \
  "$PW_IMAGE" \
  bash -euc '
    mkdir -p /work/src && cd /work
    cp /src/playwright.config.ts .
    cp -r /src/src/e2e src/
    echo "{\"private\": true, \"type\": \"module\"}" > package.json
    # The app must be a secure context (crypto.randomUUID & co.), which plain
    # http is only on localhost: forward localhost:5174 here to web:80, the
    # same address the e2e web has on the host (PUBLIC_BASE_URL).
    node -e '"'"'
      const net = require("net");
      net.createServer((c) => {
        const u = net.connect(80, "web");
        c.pipe(u).pipe(c);
        c.on("error", () => u.destroy());
        u.on("error", () => c.destroy());
      }).listen(5174, "127.0.0.1");
    '"'"' &
    npm install --no-audit --no-fund --loglevel=error "@playwright/test@$PW_VERSION"
    exec npx playwright test --output=/results/test-results \
      --reporter=list,html --trace=retain-on-failure "$@"
  ' playwright ${PW_ARGS[@]+"${PW_ARGS[@]}"} >/dev/null
docker network connect "${PROJECT}_default" "$PW_CONTAINER"

set +e
docker start -a "$PW_CONTAINER"
STATUS=$?
set -e

echo "Report: $RESULTS/report/index.html   Traces: $RESULTS/test-results"
exit "$STATUS"
