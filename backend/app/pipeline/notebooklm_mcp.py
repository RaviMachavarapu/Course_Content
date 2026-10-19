"""`NotebookLmMcpProvider` (T016) — `ContentProvider` backed by a live
NotebookLM session via `notebooklm-mcp-server`.

The server itself is stdio-only, so it runs in the separate `mcp` container
behind a thin HTTP shim (`mcp/shim/server.js`) that speaks MCP to it and
re-exposes the tool calls this provider needs. `MCP_ENDPOINT` points at that
shim (default `http://mcp:7332`, matching `docker-compose.yml`).

Tool names, argument shapes, and the `studio_poll`/`artifact_content_get`
response shapes below are taken from the pinned upstream `docs/TOOLS.md`
(`mcp/README.md` records the exact version and quotes the relevant tools) —
**not yet live-verified against a real authenticated session**. See
`docs/spikes/O1-infographic.md` and `docs/spikes/O2-audio.md` for the
verification checklist this needs before being trusted in production.

A Redis lock (`mcp:session`) serializes calls across all API/worker
processes: `notebooklm-mcp-server` holds one stdio session per shim
container, so two concurrent generations would otherwise interleave calls
against the same underlying browser session.
"""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING, Any

import httpx
import redis

from app.config import Settings
from app.models.enums import ArtifactType
from app.pipeline.provider import (
    GenerationTimeout,
    NotebookRef,
    ProviderError,
    ProviderHealth,
    RawArtifact,
    SourceRef,
    StudioJobRef,
    StudioStatus,
    TransientProviderError,
)

if TYPE_CHECKING:
    RedisClient = redis.Redis[str]
else:
    RedisClient = redis.Redis

_LOCK_KEY = "mcp:session"
_LOCK_TIMEOUT_SEC = 30 * 60  # generous — a live audio generation can be slow
_LOCK_BLOCKING_TIMEOUT_SEC = 60

_CREATE_TOOL_BY_TYPE: dict[ArtifactType, str] = {
    ArtifactType.slide_deck: "slide_deck_create",
    ArtifactType.flashcards: "flashcards_create",
    ArtifactType.quiz: "quiz_create",
    ArtifactType.report: "report_create",
    ArtifactType.infographic: "infographic_create",
    ArtifactType.audio_overview: "audio_overview_create",
}

_TERMINAL_FAILED = {"failed", "unknown"}
_TERMINAL_READY = {"completed"}


class NotebookLmMcpProvider:
    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.mcp_endpoint.rstrip("/")
        self._http = httpx.Client(base_url=self._base_url, timeout=60.0)
        self._redis: RedisClient = redis.Redis.from_url(settings.redis_url, decode_responses=True)

    # -- ContentProvider ---------------------------------------------------

    def create_notebook(self, title: str) -> NotebookRef:
        data = self._call("notebook_create", {"title": title})
        return NotebookRef(notebook_id=str(data["notebook_id"]))

    def add_source(self, nb: NotebookRef, url: str) -> SourceRef:
        data = self._call("notebook_add_url", {"notebook_id": nb.notebook_id, "url": url})
        return SourceRef(source_id=str(data["source_id"]))

    def generate(
        self,
        nb: NotebookRef,
        kind: ArtifactType,
        focus_prompt: str,
        options: dict[str, Any],
    ) -> StudioJobRef:
        tool = _CREATE_TOOL_BY_TYPE[kind]
        # `source_ids` is deliberately omitted: this app creates exactly one
        # source per notebook, and the upstream tool defaults to "every
        # source in the notebook" when it's left out (per TOOLS.md; not yet
        # confirmed live).
        args = {"notebook_id": nb.notebook_id, "focus_prompt": focus_prompt, **options}
        data = self._call(tool, args)
        artifact = data.get("artifact") or {}
        artifact_id = artifact.get("artifact_id")
        if not artifact_id:
            raise ProviderError(f"{tool} did not return an artifact_id: {data!r}")
        return StudioJobRef(job_id=str(artifact_id), notebook_id=nb.notebook_id, kind=kind)

    def poll(self, job: StudioJobRef) -> StudioStatus:
        artifact = self._poll_artifact(job)
        if artifact is None:
            return StudioStatus.pending
        status = artifact.get("status")
        if status in _TERMINAL_READY:
            return StudioStatus.ready
        if status in _TERMINAL_FAILED:
            return StudioStatus.failed
        return StudioStatus.pending

    def fetch_content(self, job: StudioJobRef) -> RawArtifact:
        data = self._call(
            "artifact_content_get",
            {"notebook_id": job.notebook_id, "artifact_id": job.job_id},
        )
        extras: dict[str, Any] = {"artifact_id": job.job_id}
        if data.get("mind_map_tree") is not None:
            extras["mind_map_tree"] = data["mind_map_tree"]
        return RawArtifact(html=str(data.get("html") or ""), extras=extras)

    def fetch_binary(self, job: StudioJobRef, kind: ArtifactType) -> bytes | None:
        if kind is not ArtifactType.audio_overview:
            # Infographic image: D15 renders our own from structure — never fetched.
            return None
        resp = self._http.get(
            "/media",
            params={"notebook_id": job.notebook_id, "artifact_id": job.job_id},
        )
        if resp.status_code == 404:
            return None
        self._raise_for_status(resp)
        return resp.content

    def health(self) -> ProviderHealth:
        try:
            resp = self._http.get("/health", timeout=10.0)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as exc:
            return ProviderHealth(
                healthy=False,
                account_email=None,
                last_ok_at=None,
                detail=f"shim unreachable: {exc}",
            )
        last_ok_at = None
        if data.get("last_ok_at"):
            last_ok_at = dt.datetime.fromisoformat(data["last_ok_at"])
        return ProviderHealth(
            healthy=bool(data.get("healthy")),
            account_email=data.get("account_email"),
            last_ok_at=last_ok_at,
            detail=str(data.get("detail") or ""),
        )

    def refresh_auth(self) -> None:
        resp = self._http.post("/refresh-auth")
        self._raise_for_status(resp)

    # -- internals ----------------------------------------------------------

    def _poll_artifact(self, job: StudioJobRef) -> dict[str, Any] | None:
        data = self._call("studio_poll", {"notebook_id": job.notebook_id})
        for artifact in data.get("artifacts") or []:
            if artifact.get("artifact_id") == job.job_id:
                return dict(artifact)
        return None

    def _call(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        lock = self._redis.lock(
            _LOCK_KEY,
            timeout=_LOCK_TIMEOUT_SEC,
            blocking_timeout=_LOCK_BLOCKING_TIMEOUT_SEC,
        )
        acquired = lock.acquire(blocking=True)
        if not acquired:
            raise TransientProviderError(
                f"could not acquire {_LOCK_KEY} within {_LOCK_BLOCKING_TIMEOUT_SEC}s"
            )
        try:
            resp = self._http.post("/call", json={"tool": tool, "args": args})
            self._raise_for_status(resp)
            body = resp.json()
            data = body.get("data")
            if not isinstance(data, dict):
                raise ProviderError(f"{tool} returned a non-object result: {body!r}")
            return data
        finally:
            lock.release()

    def _raise_for_status(self, resp: httpx.Response) -> None:
        if resp.status_code == 502:
            raise TransientProviderError(resp.json().get("error", resp.text))
        if resp.status_code == httpx.codes.REQUEST_TIMEOUT or resp.status_code >= 500:
            raise GenerationTimeout(resp.text)
        if resp.status_code >= 400:
            raise ProviderError(f"MCP shim error {resp.status_code}: {resp.text}")
