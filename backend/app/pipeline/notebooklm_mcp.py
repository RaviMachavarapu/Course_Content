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
from redis.exceptions import RedisError

from app.config import Settings
from app.logging import get_logger
from app.models.enums import ArtifactType
from app.pipeline.provider import (
    NotebookRef,
    ProviderAuthError,
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

log = get_logger("notebooklm_mcp")

_LOCK_KEY = "mcp:session"
_LOCK_TIMEOUT_SEC = 30 * 60  # generous — a live audio generation can be slow
#: a chat query (quiz prep) waits at most this long for the session lock; its task
#: retries with back-off, so it gives way to generations
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
#: The shim allows a connector tool call 300 s (mcp/shim/tools.js TOOL_TIMEOUT_MS).
#: Wait a little longer, so the session lock is only released once the shim has
#: really finished with its stdio call (a chat answer for ~10 questions takes ~40 s).
_SHIM_CALL_TIMEOUT_SEC = 330.0
_QUERY_TIMEOUT_SEC = _SHIM_CALL_TIMEOUT_SEC
#: /studio/create and /studio/artifact chain two connector calls in the shim
_CHAINED_CALL_TIMEOUT_SEC = 2 * 300.0 + 30.0
#: generation steps (polls, create, source status, outline) outwait the longest holder
#: of the session lock (a chained call or a chat query), so a class taking quiz retakes
#: doesn't fail generations that are fine
_LOCK_WAIT_SEC = _CHAINED_CALL_TIMEOUT_SEC + 30.0
#: an upload is one shim request (register + send up to 190 MB): long, but finite,
#: so a half-open connection can't hold the job (and the module lock) forever
_UPLOAD_TIMEOUT_SEC = 30 * 60.0
#: shim statuses worth retrying: its own transport/connect failures (502) and
#: whatever a proxy or timeout in between answers
_TRANSIENT_STATUSES = {408, 502, 503, 504}


class NotebookLmMcpProvider:
    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.mcp_endpoint.rstrip("/")
        self._http = httpx.Client(
            base_url=self._base_url, timeout=httpx.Timeout(_SHIM_CALL_TIMEOUT_SEC, connect=10.0)
        )
        self._redis: RedisClient = redis.Redis.from_url(settings.redis_url, decode_responses=True)

    def close(self) -> None:
        """Release the HTTP connections and the Redis pool."""
        self._http.close()
        self._redis.close()

    # -- ContentProvider ---------------------------------------------------

    def create_notebook(self, title: str) -> NotebookRef:
        data = self._call("notebook_create", {"title": title})
        return NotebookRef(notebook_id=str(data["notebook_id"]))

    def add_source(self, nb: NotebookRef, url: str) -> SourceRef:
        data = self._call("notebook_add_url", {"notebook_id": nb.notebook_id, "url": url})
        return SourceRef(source_id=str(data["source_id"]))

    def add_file_source(self, nb: NotebookRef, path: str, display_name: str) -> SourceRef:
        # A long but finite timeout (`_UPLOAD_TIMEOUT_SEC`). Not under the
        # session lock (same reasoning as `download`): the shim registers and sends the
        # file over plain HTTPS in one request without the connector's stdio session, and
        # an upload of up to 190 MB would otherwise block every other job's calls and
        # could outlive the lock's TTL.
        resp = self._send(
            lambda: self._http.post(
                "/source/upload",
                json={"notebook_id": nb.notebook_id, "path": path, "name": display_name},
                timeout=httpx.Timeout(_UPLOAD_TIMEOUT_SEC, connect=10.0),
            )
        )
        if resp.status_code == httpx.codes.UNPROCESSABLE_ENTITY:
            # NotebookLM rejected the file: permanent, not worth retrying.
            raise ProviderError(self._error_message(resp))
        self._raise_for_source_auth(resp)
        self._raise_for_status(resp)
        source_id = resp.json().get("source_id")
        if not source_id:
            raise ProviderError(f"/source/upload returned no source_id: {resp.text}")
        return SourceRef(source_id=str(source_id))

    def source_statuses(self, nb: NotebookRef) -> dict[str, SourceState]:
        resp = self._locked(
            lambda: self._http.get("/source/status", params={"notebook_id": nb.notebook_id})
        )
        self._raise_for_source_auth(resp)
        self._raise_for_status(resp)
        body = resp.json()
        items = body.get("sources") if isinstance(body, dict) else None
        if not isinstance(items, list):
            raise ProviderError(f"/source/status returned an unexpected result: {body!r}")
        out: dict[str, SourceState] = {}
        for item in items:
            if not isinstance(item, dict) or not item.get("id"):
                raise ProviderError(f"source without an id from the connector: {item!r}")
            value = item.get("status")
            try:
                out[str(item["id"])] = SourceState(value)
            except ValueError:
                raise ProviderError(
                    f"unexpected source status from the connector: {value!r}"
                ) from None
        return out

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
            timeout=_CHAINED_CALL_TIMEOUT_SEC,
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
        resp = self._send(
            lambda: self._http.get(
                "/studio/download", params={"url": url}, timeout=_DOWNLOAD_TIMEOUT_SEC
            )
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

    def query(self, nb: NotebookRef, text: str) -> str:
        data = self._call(
            "notebook_query",
            {"notebook_id": nb.notebook_id, "query": text},
            timeout=_QUERY_TIMEOUT_SEC,
            wait=_LOCK_BLOCKING_TIMEOUT_SEC,
        )
        answer = data.get("answer")
        if not isinstance(answer, str):
            raise ProviderError(f"notebook_query returned no answer: {data!r}")
        return answer

    def health(self) -> ProviderHealth:
        try:
            resp = self._http.get("/health", timeout=10.0)
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, dict):
                raise ValueError(f"unexpected /health reply: {data!r}")
        except (httpx.HTTPError, ValueError) as exc:
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
        resp = self._send(lambda: self._http.post("/refresh-auth"))
        self._raise_for_status(resp)

    # -- internals ----------------------------------------------------------

    def _artifact(self, job: StudioJobRef) -> dict[str, Any]:
        return self._studio(
            "GET",
            "/studio/artifact",
            params={"notebook_id": job.notebook_id, "artifact_id": job.job_id},
            timeout=_CHAINED_CALL_TIMEOUT_SEC,
        )

    def _studio(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        resp = self._locked(lambda: self._http.request(method, path, **kwargs))
        self._raise_for_status(resp)
        body = resp.json()
        if not isinstance(body, dict):
            raise ProviderError(f"{path} returned a non-object result: {body!r}")
        return body

    def _call(
        self,
        tool: str,
        args: dict[str, Any],
        *,
        timeout: float | None = None,
        wait: float | None = None,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {} if timeout is None else {"timeout": timeout}
        resp = self._locked(
            lambda: self._http.post("/call", json={"tool": tool, "args": args}, **kwargs),
            wait=wait,
        )
        self._raise_for_source_auth(resp)
        self._raise_for_status(resp)
        body = resp.json()
        data = body.get("data")
        if not isinstance(data, dict):
            raise ProviderError(f"{tool} returned a non-object result: {body!r}")
        return data

    def _locked(
        self, request: Callable[[], httpx.Response], *, wait: float | None = None
    ) -> httpx.Response:
        """Run one shim request under the shared NotebookLM session lock.

        Redis trouble taking the lock (a restart, a rotated password) is transient. A
        failed release is only logged: the call already ran, and throwing its result
        away (e.g. a new NotebookLM artifact id) would orphan it and spend quota again.
        The lock's TTL frees a key we couldn't delete."""
        if wait is None:
            wait = _LOCK_WAIT_SEC
        lock = self._redis.lock(_LOCK_KEY, timeout=_LOCK_TIMEOUT_SEC, blocking_timeout=wait)
        try:
            acquired = lock.acquire(blocking=True)
        except RedisError as exc:
            raise TransientProviderError(f"{_LOCK_KEY} unavailable (Redis: {exc})") from exc
        if not acquired:
            raise TransientProviderError(f"could not acquire {_LOCK_KEY} within {wait:.0f}s")
        try:
            return self._send(request)
        finally:
            try:
                lock.release()
            except RedisError as exc:
                log.warning("notebooklm_mcp.lock_release_failed", error=str(exc))

    @staticmethod
    def _send(request: Callable[[], httpx.Response]) -> httpx.Response:
        """A shim timeout, refused connection or dropped socket (e.g. the mcp
        container restarting) is transient: retried, or waited out while polling."""
        try:
            return request()
        except httpx.TransportError as exc:
            raise TransientProviderError(
                f"MCP shim unreachable ({type(exc).__name__}): {exc}"
            ) from exc

    def _raise_for_source_auth(self, resp: httpx.Response) -> None:
        if resp.status_code == httpx.codes.UNAUTHORIZED:
            raise ProviderAuthError(self._error_message(resp))

    @staticmethod
    def _error_message(resp: httpx.Response) -> str:
        try:
            body = resp.json()
        except ValueError:
            return resp.text
        return str(body.get("error", resp.text)) if isinstance(body, dict) else resp.text

    def _raise_for_status(self, resp: httpx.Response) -> None:
        """502/503/504/408 are transient; 401 needs signing in again; 422 is
        NotebookLM or the connector rejecting the request for good; anything else
        ≥ 400 is a provider error."""
        if resp.status_code in _TRANSIENT_STATUSES:
            raise TransientProviderError(self._error_message(resp))
        if resp.status_code == httpx.codes.UNAUTHORIZED:
            raise ProviderAuthError(self._error_message(resp))
        if resp.status_code == httpx.codes.UNPROCESSABLE_ENTITY:
            raise ProviderError(self._error_message(resp))
        if resp.status_code >= 400:
            raise ProviderError(f"MCP shim error {resp.status_code}: {resp.text}")
