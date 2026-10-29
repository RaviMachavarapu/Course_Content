"""T016 — `NotebookLmMcpProvider` contract tests.

These exercise the provider's translation of `ContentProvider` calls into
HTTP calls against the mcp shim, using `httpx.MockTransport` — no live MCP
session or Google account involved. The shim's own request building is tested
against the recorded web-app requests in `mcp/shim/test/`.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from app.config import get_settings
from app.models.enums import ArtifactType
from app.pipeline.notebooklm_mcp import NotebookLmMcpProvider
from app.pipeline.provider import (
    NotebookRef,
    ProviderAuthError,
    ProviderError,
    SourceState,
    StudioJobRef,
    StudioStatus,
    TransientProviderError,
)

Handler = Callable[[httpx.Request], httpx.Response]


def _provider(handler: Handler) -> NotebookLmMcpProvider:
    provider = NotebookLmMcpProvider(get_settings())
    provider._http = httpx.Client(
        base_url=provider._base_url, transport=httpx.MockTransport(handler)
    )
    return provider


def _ok(data: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, json={"data": data})


def test_create_notebook_and_add_source() -> None:
    calls: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body)
        if body["tool"] == "notebook_create":
            return _ok({"status": "ok", "notebook_id": "nb-1", "title": body["args"]["title"]})
        if body["tool"] == "notebook_add_url":
            return _ok({"status": "ok", "source_id": "src-1"})
        raise AssertionError(f"unexpected tool {body['tool']}")

    provider = _provider(handler)
    nb = provider.create_notebook("Neural Nets")
    assert nb == NotebookRef(notebook_id="nb-1")
    src = provider.add_source(nb, "https://example.com/video")
    assert src.source_id == "src-1"
    assert calls[0] == {"tool": "notebook_create", "args": {"title": "Neural Nets"}}
    assert calls[1] == {
        "tool": "notebook_add_url",
        "args": {"notebook_id": "nb-1", "url": "https://example.com/video"},
    }


@pytest.mark.parametrize("kind", list(ArtifactType))
def test_generate_posts_kind_focus_and_options_to_studio_create(kind: ArtifactType) -> None:
    seen: list[tuple[str, dict[str, Any]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={"artifact_id": "art-1"})

    provider = _provider(handler)
    job = provider.generate(NotebookRef(notebook_id="nb-1"), kind, "make it good", {"a": "b"})
    assert job == StudioJobRef(job_id="art-1", notebook_id="nb-1", kind=kind)
    assert seen == [
        (
            "/studio/create",
            {
                "notebook_id": "nb-1",
                "kind": kind.value,
                "focus_prompt": "make it good",
                "options": {"a": "b"},
            },
        )
    ]


def test_generate_raises_when_no_artifact_id_returned() -> None:
    provider = _provider(lambda _r: httpx.Response(200, json={}))
    with pytest.raises(ProviderError, match="returned no artifact_id"):
        provider.generate(NotebookRef(notebook_id="nb-1"), ArtifactType.report, "x", {})


def test_a_request_notebooklm_rejects_is_not_retried() -> None:
    # The shim answers 422 when NotebookLM rejects the request itself.
    provider = _provider(lambda _r: httpx.Response(422, json={"error": "rejected [3]"}))
    with pytest.raises(ProviderError) as info:
        provider.generate(NotebookRef(notebook_id="nb-1"), ArtifactType.report, "x", {})
    assert not isinstance(info.value, TransientProviderError)


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (3, StudioStatus.ready),
        (6, StudioStatus.awaiting_review),
        (4, StudioStatus.failed),
        (1, StudioStatus.pending),
        (2, StudioStatus.pending),
        (None, StudioStatus.pending),
    ],
)
def test_poll_maps_notebooklm_status_codes(code: int | None, expected: StudioStatus) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/studio/artifact"
        assert dict(request.url.params) == {"notebook_id": "nb-1", "artifact_id": "art-1"}
        return httpx.Response(200, json={"status": code, "raw": None, "html": None})

    provider = _provider(handler)
    job = StudioJobRef(job_id="art-1", notebook_id="nb-1", kind=ArtifactType.report)
    assert provider.poll(job) is expected


def test_fetch_content_carries_the_artifact_row_and_html() -> None:
    row = ["art-1", "Title", 7]
    provider = _provider(
        lambda _r: httpx.Response(200, json={"status": 3, "raw": row, "html": "<div>hi</div>"})
    )
    job = StudioJobRef(job_id="art-1", notebook_id="nb-1", kind=ArtifactType.infographic)
    raw = provider.fetch_content(job)
    assert raw.html == "<div>hi</div>"
    assert raw.extras == {"artifact_id": "art-1", "source": "notebooklm", "row": row}


def test_download_returns_bytes_and_content_type() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/studio/download"
        assert request.url.params["url"] == "https://lh3.googleusercontent.com/x"
        return httpx.Response(200, content=b"\x89PNG", headers={"content-type": "image/png"})

    data, mime = _provider(handler).download("https://lh3.googleusercontent.com/x")
    assert (data, mime) == (b"\x89PNG", "image/png")


@pytest.mark.parametrize("feedback", ["Fewer slides", None])
def test_outline_action_posts_feedback_or_proceed(feedback: str | None) -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/studio/outline"
        seen.append(json.loads(request.content))
        return httpx.Response(204)

    job = StudioJobRef(job_id="art-1", notebook_id="nb-1", kind=ArtifactType.slide_deck)
    _provider(handler).outline_action(job, feedback)
    assert seen == [{"notebook_id": "nb-1", "artifact_id": "art-1", "feedback": feedback}]


def test_fetch_binary_is_unused_for_notebooklm() -> None:
    provider = _provider(lambda _r: pytest.fail("no request expected"))
    job = StudioJobRef(job_id="art-1", notebook_id="nb-1", kind=ArtifactType.audio_overview)
    assert provider.fetch_binary(job, ArtifactType.audio_overview) is None


def test_health_reports_shim_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/health"
        return httpx.Response(
            200,
            json={
                "healthy": True,
                "account_email": None,
                "last_ok_at": "2026-01-01T00:00:00+00:00",
                "detail": "notebook_list ok",
            },
        )

    provider = _provider(handler)
    health = provider.health()
    assert health.healthy is True
    assert health.detail == "notebook_list ok"


def test_health_reports_unreachable_shim() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    provider = _provider(handler)
    health = provider.health()
    assert health.healthy is False
    assert "unreachable" in health.detail


def test_refresh_auth_posts_to_shim() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(204)

    provider = _provider(handler)
    provider.refresh_auth()
    assert calls == ["/refresh-auth"]


def test_plain_4xx_from_shim_is_a_provider_error() -> None:
    provider = _provider(lambda _r: httpx.Response(400, text="bad request"))
    with pytest.raises(ProviderError, match="MCP shim error 400"):
        provider.create_notebook("x")


def test_non_object_data_is_a_provider_error() -> None:
    provider = _provider(lambda _r: httpx.Response(200, json={"data": "not-a-dict"}))
    with pytest.raises(ProviderError, match="non-object result"):
        provider.create_notebook("x")


def test_lock_already_held_is_a_transient_provider_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.pipeline.notebooklm_mcp._LOCK_WAIT_SEC", 1)
    provider = _provider(lambda _r: _ok({"notebook_id": "nb-1", "title": "x"}))
    blocking_lock = provider._redis.lock("mcp:session", timeout=5)
    assert blocking_lock.acquire(blocking=True)
    try:
        with pytest.raises(TransientProviderError, match="could not acquire"):
            provider.create_notebook("x")
    finally:
        blocking_lock.release()


def test_502_from_shim_is_a_transient_provider_error() -> None:
    provider = _provider(lambda _r: httpx.Response(502, json={"error": "tool boom"}))
    with pytest.raises(TransientProviderError, match="tool boom"):
        provider.create_notebook("x")


@pytest.mark.parametrize("code", [408, 503, 504])
def test_gateway_and_timeout_statuses_are_transient(code: int) -> None:
    provider = _provider(lambda _r: httpx.Response(code, text="<html>proxy page</html>"))
    with pytest.raises(TransientProviderError, match="proxy page"):
        provider.create_notebook("x")


def test_a_non_json_502_is_still_transient() -> None:
    provider = _provider(lambda _r: httpx.Response(502, text="<html>bad gateway</html>"))
    with pytest.raises(TransientProviderError, match="bad gateway"):
        provider.create_notebook("x")


def test_a_connector_tool_rejection_is_permanent() -> None:
    # the shim answers 422 when the tool itself reported an error (isError)
    provider = _provider(lambda _r: httpx.Response(422, json={"error": "private video"}))
    with pytest.raises(ProviderError, match="private video") as info:
        provider.add_source(NotebookRef(notebook_id="nb"), "https://youtu.be/x")
    assert not isinstance(info.value, TransientProviderError)


def test_a_connector_auth_failure_is_an_auth_error() -> None:
    provider = _provider(lambda _r: httpx.Response(401, json={"error": "sign in again"}))
    with pytest.raises(ProviderAuthError):
        provider.create_notebook("x")


_NETWORK_ERRORS = [httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError]


@pytest.mark.parametrize("error", _NETWORK_ERRORS)
@pytest.mark.parametrize(
    "call",
    [
        lambda p: p.create_notebook("x"),
        lambda p: p.poll(StudioJobRef(job_id="a", notebook_id="n", kind=ArtifactType.report)),
        lambda p: p.download("https://lh3.googleusercontent.com/x"),
        lambda p: p.add_file_source(NotebookRef(notebook_id="n"), "/data/media/a.pdf", "a.pdf"),
        lambda p: p.source_statuses(NotebookRef(notebook_id="n")),
        lambda p: p.query(NotebookRef(notebook_id="n"), "ask"),
    ],
)
def test_network_errors_and_timeouts_are_transient(
    error: type[httpx.TransportError], call: Callable[[NotebookLmMcpProvider], object]
) -> None:
    """An mcp restart or a slow shim call is worth retrying (and, while polling, waiting
    for), not a failed generation."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise error("down", request=request)

    with pytest.raises(TransientProviderError):
        call(_provider(handler))


def test_calls_outlast_the_shims_own_tool_timeout() -> None:
    from app.pipeline import notebooklm_mcp

    shim_timeout_sec = 300
    provider = NotebookLmMcpProvider(get_settings())
    try:
        assert provider._http.timeout.read is not None
        assert provider._http.timeout.read > shim_timeout_sec
        assert shim_timeout_sec < notebooklm_mcp._QUERY_TIMEOUT_SEC
        assert provider._http.timeout.read < notebooklm_mcp._LOCK_TIMEOUT_SEC
    finally:
        provider.close()


def test_the_provider_is_reused_per_process_and_closes() -> None:
    from app.config import Settings
    from app.pipeline import factory

    settings = Settings(content_provider="notebooklm")
    factory.reset_content_provider()
    try:
        first = factory.get_content_provider(settings)
        assert factory.get_content_provider(settings) is first
    finally:
        factory.reset_content_provider()
    assert first._http.is_closed


def test_lock_is_released_after_a_call() -> None:
    provider = _provider(lambda _r: _ok({"status": "ok", "notebook_id": "nb-1", "title": "x"}))
    provider.create_notebook("x")
    # the lock must be free again — acquiring it here should succeed immediately
    lock = provider._redis.lock("mcp:session", timeout=5, blocking_timeout=1)
    assert lock.acquire(blocking=True)
    lock.release()


def test_lock_is_released_even_when_the_call_raises() -> None:
    provider = _provider(lambda _r: httpx.Response(502, json={"error": "boom"}))
    with pytest.raises(TransientProviderError):
        provider.create_notebook("x")
    lock = provider._redis.lock("mcp:session", timeout=5, blocking_timeout=1)
    assert lock.acquire(blocking=True)
    lock.release()


def test_add_file_source_posts_path_and_name() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"source_id": "src-9"})

    provider = _provider(handler)
    ref = provider.add_file_source(
        NotebookRef(notebook_id="nb-1"), "/data/media/uploads/a.pdf", "a.pdf"
    )
    assert ref.source_id == "src-9"
    assert seen[0].method == "POST"
    assert seen[0].url.path == "/source/upload"
    assert json.loads(seen[0].content) == {
        "notebook_id": "nb-1",
        "path": "/data/media/uploads/a.pdf",
        "name": "a.pdf",
    }
    # long but finite: a half-open connection to the shim can't hang the job forever
    assert seen[0].extensions["timeout"]["read"] == pytest.approx(30 * 60)


def test_add_file_source_does_not_hold_the_session_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A long upload must not block other jobs' calls, so it runs outside mcp:session.
    monkeypatch.setattr("app.pipeline.notebooklm_mcp._LOCK_BLOCKING_TIMEOUT_SEC", 1)
    provider = _provider(lambda _r: httpx.Response(200, json={"source_id": "src-9"}))
    other_job = provider._redis.lock("mcp:session", timeout=5)
    assert other_job.acquire(blocking=True)
    try:
        ref = provider.add_file_source(NotebookRef(notebook_id="nb-1"), "/x.pdf", "x.pdf")
    finally:
        other_job.release()
    assert ref.source_id == "src-9"


def test_source_statuses_maps_shim_reply() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/source/status"
        assert request.url.params["notebook_id"] == "nb-1"
        return httpx.Response(
            200,
            json={
                "sources": [
                    {"id": "s1", "title": "A", "status": "pending"},
                    {"id": "s2", "title": "B", "status": "ready"},
                    {"id": "s3", "title": "C", "status": "failed"},
                ]
            },
        )

    out = _provider(handler).source_statuses(NotebookRef(notebook_id="nb-1"))
    assert out == {
        "s1": SourceState.pending,
        "s2": SourceState.ready,
        "s3": SourceState.failed,
    }


def test_add_file_source_422_is_provider_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"error": "unsupported file"})

    with pytest.raises(ProviderError) as exc:
        _provider(handler).add_file_source(NotebookRef(notebook_id="nb-1"), "/x.pdf", "x.pdf")
    assert not isinstance(exc.value, TransientProviderError)
    assert str(exc.value) == "unsupported file"


@pytest.mark.parametrize("route", ["upload", "status"])
def test_source_routes_401_is_provider_auth_error(route: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "Google session needs attention"})

    provider = _provider(handler)
    nb = NotebookRef(notebook_id="nb-1")
    with pytest.raises(ProviderAuthError) as exc:
        if route == "upload":
            provider.add_file_source(nb, "/x.pdf", "x.pdf")
        else:
            provider.source_statuses(nb)
    assert not isinstance(exc.value, TransientProviderError)
    assert str(exc.value) == "Google session needs attention"


@pytest.mark.parametrize(
    ("item", "message"),
    [
        ({"id": "s1", "status": "weird"}, "unexpected source status from the connector: 'weird'"),
        ({"id": "s1"}, "unexpected source status from the connector: None"),
        ({"status": "ready"}, "source without an id"),
    ],
)
def test_source_statuses_bad_items_are_provider_errors(item: dict[str, Any], message: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"sources": [item]})

    with pytest.raises(ProviderError, match=message):
        _provider(handler).source_statuses(NotebookRef(notebook_id="nb-1"))


def test_query_calls_notebook_query_and_returns_answer() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return _ok({"answer": "[]"})

    assert _provider(handler).query(NotebookRef(notebook_id="nb-1"), "ask") == "[]"
    assert seen == [{"tool": "notebook_query", "args": {"notebook_id": "nb-1", "query": "ask"}}]


def test_query_without_answer_is_a_provider_error() -> None:
    with pytest.raises(ProviderError):
        _provider(lambda r: _ok({"status": "ok"})).query(NotebookRef(notebook_id="nb-1"), "ask")


def test_query_timeout_is_transient() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(TransientProviderError):
        _provider(handler).query(NotebookRef(notebook_id="nb-1"), "ask")


# -- Redis trouble and the session lock (review 2026-10-29) ----------------------------
class _StubLock:
    def __init__(self, owner: _StubRedis, blocking_timeout: float | None) -> None:
        self.owner = owner
        self.blocking_timeout = blocking_timeout

    def acquire(self, blocking: bool = True) -> bool:
        if self.owner.acquire_error is not None:
            raise self.owner.acquire_error
        return True

    def release(self) -> None:
        if self.owner.release_error is not None:
            raise self.owner.release_error


class _StubRedis:
    """Stands in for the provider's Redis client (no real lock taken)."""

    def __init__(self) -> None:
        self.acquire_error: Exception | None = None
        self.release_error: Exception | None = None
        self.waits: list[float | None] = []

    def lock(self, name: str, timeout: float, blocking_timeout: float | None = None) -> _StubLock:
        self.waits.append(blocking_timeout)
        return _StubLock(self, blocking_timeout)

    def close(self) -> None:
        pass


def _stubbed(handler: Handler) -> tuple[NotebookLmMcpProvider, _StubRedis]:
    provider = _provider(handler)
    provider._redis.close()
    stub = _StubRedis()
    provider._redis = stub  # type: ignore[assignment]
    return provider, stub


@pytest.mark.parametrize(
    "error",
    [
        __import__("redis").exceptions.ConnectionError("restarting"),
        __import__("redis").exceptions.TimeoutError("slow"),
        __import__("redis").exceptions.AuthenticationError("bad password"),
    ],
    ids=["connection", "timeout", "auth"],
)
def test_redis_trouble_taking_the_session_lock_is_transient(error: Exception) -> None:
    provider, stub = _stubbed(lambda _r: _ok({"notebook_id": "nb-1"}))
    stub.acquire_error = error
    with pytest.raises(TransientProviderError, match="Redis"):
        provider.create_notebook("x")


@pytest.mark.parametrize(
    "error",
    [
        __import__("redis").exceptions.LockNotOwnedError("key gone"),
        __import__("redis").exceptions.ConnectionError("restarting"),
    ],
    ids=["lost", "down"],
)
def test_a_failed_lock_release_never_discards_a_finished_call(error: Exception) -> None:
    """Worst case from the review: /studio/create succeeded, then the release fails
    (the key vanished in a Redis restart). The NotebookLM id must still come back."""
    provider, stub = _stubbed(lambda _r: httpx.Response(200, json={"artifact_id": "art-7"}))
    stub.release_error = error
    job = provider.generate(NotebookRef(notebook_id="nb-1"), ArtifactType.report, "p", {})
    assert job.job_id == "art-7"


def test_chat_waits_briefly_for_the_session_lock_but_generation_steps_outwait_it() -> None:
    """A chat query holds the lock up to 330 s: generation calls wait longer than the
    longest holder; a chat prep gives up after 60 s (its task retries with back-off)."""
    from app.pipeline import notebooklm_mcp as m

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/call":
            return _ok({"answer": "a"})
        return httpx.Response(200, json={"status": 1, "artifact_id": "a", "sources": []})

    provider, stub = _stubbed(handler)
    nb = NotebookRef(notebook_id="nb-1")
    job = StudioJobRef(job_id="a", notebook_id="nb-1", kind=ArtifactType.report)
    provider.query(nb, "q")
    provider.poll(job)
    provider.generate(nb, ArtifactType.report, "p", {})
    provider.source_statuses(nb)
    chat, poll, create, status = stub.waits
    assert chat == m._LOCK_BLOCKING_TIMEOUT_SEC == 60
    longest_holder = max(m._QUERY_TIMEOUT_SEC, m._CHAINED_CALL_TIMEOUT_SEC)
    for wait in (poll, create, status):
        assert wait is not None and wait > longest_holder


def test_shim_endpoints_chaining_two_connector_calls_get_room_for_both() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen[request.url.path] = request.extensions["timeout"]["read"]
        return httpx.Response(200, json={"status": 1, "artifact_id": "a"})

    provider, _stub = _stubbed(handler)
    nb = NotebookRef(notebook_id="nb-1")
    provider.generate(nb, ArtifactType.report, "p", {})
    provider.poll(StudioJobRef(job_id="a", notebook_id="nb-1", kind=ArtifactType.report))
    shim_tool_timeout = 300
    assert seen["/studio/create"] > 2 * shim_tool_timeout
    assert seen["/studio/artifact"] > 2 * shim_tool_timeout
