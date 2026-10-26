"""`NotebookLmMcpProvider` (T016) — `ContentProvider` backed by a live
NotebookLM session via `notebooklm-mcp-server`.

The server itself is stdio-only, so it runs in the separate `mcp` container
behind a thin HTTP shim (`mcp/shim/server.js`) that speaks MCP to it and
re-exposes the tool calls this provider needs. `MCP_ENDPOINT` points at that
shim (default `http://mcp:7332`, matching `docker-compose.yml`).

Notebook and source calls use the connector's tools. Studio generation,
status, outline review and media downloads use the shim's `/studio/*`
endpoints, which speak the request format the NotebookLM web app uses today
(the pinned connector's own Studio requests are rejected by Google). Both were
verified live on 2026-10-22: docs/spikes/notebooklm-2026-10-capture.md.

A Redis lock (`mcp:session`) serializes calls across all API/worker
processes: `notebooklm-mcp-server` holds one stdio session per shim
container, so two concurrent generations would otherwise interleave calls
against the same underlying browser session.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
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
    SourceState,
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

# NotebookLM artifact status codes (shim's /studio/artifact).
_STATUS_COMPLETED = 3
_STATUS_FAILED = 4
_STATUS_OUTLINE_REVIEW = 6
_DOWNLOAD_TIMEOUT_SEC = 300.0


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

    def add_file_source(self, nb: NotebookRef, path: str, display_name: str) -> SourceRef:
        # No client timeout: the upload is bounded by Google, not by us.
        resp = self._locked(
            lambda: self._http.post(
                "/source/upload",
                json={"notebook_id": nb.notebook_id, "path": path, "name": display_name},
                timeout=None,
            )
        )
        if resp.status_code == httpx.codes.UNPROCESSABLE_ENTITY:
            # NotebookLM rejected the file: permanent, not worth retrying.
            raise ProviderError(self._error_message(resp))
        self._raise_for_status(resp)
        source_id = resp.json().get("source_id")
        if not source_id:
            raise ProviderError(f"/source/upload returned no source_id: {resp.text}")
        return SourceRef(source_id=str(source_id))

    def source_statuses(self, nb: NotebookRef) -> dict[str, SourceState]:
        data = self._studio("GET", "/source/status", params={"notebook_id": nb.notebook_id})
        return {str(s["id"]): SourceState(s["status"]) for s in data.get("sources", [])}

    def generate(
        self,
        nb: NotebookRef,
        kind: ArtifactType,
        focus_prompt: str,
        options: dict[str, Any],
    ) -> StudioJobRef:
        data = self._studio(
            "POST",
            "/studio/create",
            json={
                "notebook_id": nb.notebook_id,
                "kind": kind.value,
                "focus_prompt": focus_prompt,
                "options": options,
            },
        )
        artifact_id = data.get("artifact_id")
        if not artifact_id:
            raise ProviderError(f"/studio/create returned no artifact_id: {data!r}")
        return StudioJobRef(job_id=str(artifact_id), notebook_id=nb.notebook_id, kind=kind)

    def poll(self, job: StudioJobRef) -> StudioStatus:
        status = self._artifact(job).get("status")
        if status == _STATUS_COMPLETED:
            return StudioStatus.ready
        if status == _STATUS_OUTLINE_REVIEW:
            return StudioStatus.awaiting_review
        if status == _STATUS_FAILED:
            return StudioStatus.failed
        return StudioStatus.pending

    def fetch_content(self, job: StudioJobRef) -> RawArtifact:
        data = self._artifact(job)
        return RawArtifact(
            html=str(data.get("html") or ""),
            extras={"artifact_id": job.job_id, "source": "notebooklm", "row": data.get("raw")},
        )

    def fetch_binary(self, job: StudioJobRef, kind: ArtifactType) -> bytes | None:
        # NotebookLM media is fetched by URL (`download`); kept for the protocol.
        return None

    def download(self, url: str) -> tuple[bytes, str]:
        # Not under the session lock: a plain HTTPS fetch that doesn't touch the
        # connector's stdio session, and a large deck held the lock long enough
        # to time out other jobs' polls (seen live 2026-10-22).
        resp = self._http.get(
            "/studio/download", params={"url": url}, timeout=_DOWNLOAD_TIMEOUT_SEC
        )
        self._raise_for_status(resp)
        return resp.content, resp.headers.get("content-type", "application/octet-stream")

    def outline_action(self, job: StudioJobRef, feedback: str | None) -> None:
        resp = self._locked(
            lambda: self._http.post(
                "/studio/outline",
                json={
                    "notebook_id": job.notebook_id,
                    "artifact_id": job.job_id,
                    "feedback": feedback,
                },
            )
        )
        self._raise_for_status(resp)

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

    def _artifact(self, job: StudioJobRef) -> dict[str, Any]:
        return self._studio(
            "GET",
            "/studio/artifact",
            params={"notebook_id": job.notebook_id, "artifact_id": job.job_id},
        )

    def _studio(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        resp = self._locked(lambda: self._http.request(method, path, **kwargs))
        self._raise_for_status(resp)
        body = resp.json()
        if not isinstance(body, dict):
            raise ProviderError(f"{path} returned a non-object result: {body!r}")
        return body

    def _call(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        resp = self._locked(lambda: self._http.post("/call", json={"tool": tool, "args": args}))
        self._raise_for_status(resp)
        body = resp.json()
        data = body.get("data")
        if not isinstance(data, dict):
            raise ProviderError(f"{tool} returned a non-object result: {body!r}")
        return data

    def _locked(self, request: Callable[[], httpx.Response]) -> httpx.Response:
        """Run one shim request under the shared NotebookLM session lock."""
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
            return request()
        finally:
            lock.release()

    @staticmethod
    def _error_message(resp: httpx.Response) -> str:
        try:
            body = resp.json()
        except ValueError:
            return resp.text
        return str(body.get("error", resp.text)) if isinstance(body, dict) else resp.text

    def _raise_for_status(self, resp: httpx.Response) -> None:
        if resp.status_code == 502:
            raise TransientProviderError(resp.json().get("error", resp.text))
        if resp.status_code == httpx.codes.REQUEST_TIMEOUT or resp.status_code >= 500:
            raise GenerationTimeout(resp.text)
        if resp.status_code >= 400:
            raise ProviderError(f"MCP shim error {resp.status_code}: {resp.text}")
