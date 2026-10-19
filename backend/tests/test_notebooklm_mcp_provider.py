"""T016 — `NotebookLmMcpProvider` contract tests.

These exercise the provider's translation of `ContentProvider` calls into
HTTP calls against the mcp shim, using `httpx.MockTransport` — no live MCP
session or Google account involved. They prove the provider *shape* is
correct; they cannot prove the upstream tool argument/response shapes
assumed here match the real server (see `docs/spikes/O1-infographic.md` /
`docs/spikes/O2-audio.md` for what still needs a live check).
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
    GenerationTimeout,
    NotebookRef,
    ProviderError,
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


@pytest.mark.parametrize(
    ("kind", "tool"),
    [
        (ArtifactType.slide_deck, "slide_deck_create"),
        (ArtifactType.flashcards, "flashcards_create"),
        (ArtifactType.quiz, "quiz_create"),
        (ArtifactType.report, "report_create"),
        (ArtifactType.infographic, "infographic_create"),
        (ArtifactType.audio_overview, "audio_overview_create"),
    ],
)
def test_generate_dispatches_to_the_right_create_tool(kind: ArtifactType, tool: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["tool"] == tool
        assert body["args"]["notebook_id"] == "nb-1"
        assert body["args"]["focus_prompt"] == "make it good"
        return _ok({"status": "ok", "artifact": {"artifact_id": "art-1", "type": kind.value}})

    provider = _provider(handler)
    job = provider.generate(NotebookRef(notebook_id="nb-1"), kind, "make it good", {})
    assert job == StudioJobRef(job_id="art-1", notebook_id="nb-1", kind=kind)


def test_generate_raises_when_no_artifact_id_returned() -> None:
    provider = _provider(lambda _r: _ok({"status": "ok", "artifact": {}}))
    with pytest.raises(ProviderError, match="did not return an artifact_id"):
        provider.generate(NotebookRef(notebook_id="nb-1"), ArtifactType.report, "x", {})


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("completed", StudioStatus.ready),
        ("pending", StudioStatus.pending),
        ("in_progress", StudioStatus.pending),
        ("failed", StudioStatus.failed),
        ("unknown", StudioStatus.failed),
    ],
)
def test_poll_maps_studio_status(status: str, expected: StudioStatus) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _ok({"artifacts": [{"artifact_id": "art-1", "status": status}]})

    provider = _provider(handler)
    job = StudioJobRef(job_id="art-1", notebook_id="nb-1", kind=ArtifactType.report)
    assert provider.poll(job) is expected


def test_poll_missing_artifact_is_pending() -> None:
    provider = _provider(lambda _r: _ok({"artifacts": []}))
    job = StudioJobRef(job_id="art-1", notebook_id="nb-1", kind=ArtifactType.report)
    assert provider.poll(job) is StudioStatus.pending


def test_fetch_content_carries_mind_map_tree_when_present() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body == {
            "tool": "artifact_content_get",
            "args": {"notebook_id": "nb-1", "artifact_id": "art-1"},
        }
        return _ok({"artifact_id": "art-1", "html": "<div>hi</div>", "mind_map_tree": {"a": 1}})

    provider = _provider(handler)
    job = StudioJobRef(job_id="art-1", notebook_id="nb-1", kind=ArtifactType.infographic)
    raw = provider.fetch_content(job)
    assert raw.html == "<div>hi</div>"
    assert raw.extras == {"artifact_id": "art-1", "mind_map_tree": {"a": 1}}


def test_fetch_binary_only_calls_media_for_audio() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, content=b"id3-ish-bytes", headers={"content-type": "audio/mpeg"})

    provider = _provider(handler)
    job = StudioJobRef(job_id="art-1", notebook_id="nb-1", kind=ArtifactType.infographic)
    assert provider.fetch_binary(job, ArtifactType.infographic) is None
    assert calls == []  # D15: infographic image is never fetched from the MCP

    audio_job = StudioJobRef(job_id="art-2", notebook_id="nb-1", kind=ArtifactType.audio_overview)
    data = provider.fetch_binary(audio_job, ArtifactType.audio_overview)
    assert data == b"id3-ish-bytes"
    assert calls == ["/media"]


def test_fetch_binary_missing_media_returns_none() -> None:
    provider = _provider(lambda _r: httpx.Response(404, json={"error": "no media_url"}))
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
    monkeypatch.setattr("app.pipeline.notebooklm_mcp._LOCK_BLOCKING_TIMEOUT_SEC", 1)
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


def test_5xx_other_than_502_is_a_generation_timeout() -> None:
    provider = _provider(lambda _r: httpx.Response(504, text="gateway timeout"))
    with pytest.raises(GenerationTimeout):
        provider.create_notebook("x")


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
