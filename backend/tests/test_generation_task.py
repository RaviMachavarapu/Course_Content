"""generate_artifact_task must persist a failure instead of rolling it back.

Before this, the orchestrator marked the artifact `error` and re-raised, and
the task's `session_scope()` rolled that back — the staging card stayed on
"Generating…" forever (seen live 2026-10-22).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest

from app.models.enums import ArtifactType
from app.pipeline.provider import ProviderError, TransientProviderError
from app.tasks import generation


class _Scope:
    """Stand-in for session_scope that records commit vs rollback."""

    def __init__(self) -> None:
        self.outcome: str | None = None

    @contextmanager
    def __call__(self) -> Iterator[object]:
        try:
            yield object()
            self.outcome = "commit"
        except Exception:
            self.outcome = "rollback"
            raise


def _run(monkeypatch: pytest.MonkeyPatch, exc: Exception, retries: int) -> _Scope:
    scope = _Scope()
    monkeypatch.setattr(generation, "session_scope", scope)
    monkeypatch.setattr(generation, "get_content_provider", lambda: object())

    def boom(*_: Any, **__: Any) -> None:
        raise exc

    monkeypatch.setattr(generation, "run_artifact_generation", boom)
    task = generation.generate_artifact_task
    task.push_request(retries=retries)
    try:
        with pytest.raises(type(exc)):
            task._orig_run(str(uuid.uuid4()))  # type: ignore[attr-defined]
    finally:
        task.pop_request()
    return scope


def test_a_permanent_failure_is_committed(monkeypatch: pytest.MonkeyPatch) -> None:
    scope = _run(monkeypatch, ProviderError("bad response"), retries=0)
    assert scope.outcome == "commit"


def test_a_transient_failure_with_retries_left_is_rolled_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = _run(monkeypatch, TransientProviderError("timeout"), retries=0)
    assert scope.outcome == "rollback"


def test_a_transient_failure_on_the_last_retry_is_committed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = _run(monkeypatch, TransientProviderError("timeout"), retries=generation._MAX_RETRIES)
    assert scope.outcome == "commit"


# -- the PDF build is enqueued after the version is committed ---------------------
class _Version:
    def __init__(self, artifact_type: ArtifactType) -> None:
        self.id = uuid.uuid4()
        self.artifact = type("A", (), {"type": artifact_type})()


def _generate(
    monkeypatch: pytest.MonkeyPatch, result: _Version | None
) -> tuple[_Scope, list[tuple[dict[str, Any], str | None]]]:
    scope = _Scope()
    monkeypatch.setattr(generation, "session_scope", scope)
    monkeypatch.setattr(generation, "get_content_provider", lambda: object())
    monkeypatch.setattr(generation, "run_artifact_generation", lambda *a, **k: result)
    enqueued: list[tuple[dict[str, Any], str | None]] = []

    def apply_async(**kwargs: Any) -> None:
        enqueued.append((kwargs, scope.outcome))

    monkeypatch.setattr(generation.build_artifact_pdf, "apply_async", apply_async)
    task = generation.generate_artifact_task
    task.push_request(retries=0)
    try:
        task._orig_run(str(uuid.uuid4()))  # type: ignore[attr-defined]
    finally:
        task.pop_request()
    return scope, enqueued


@pytest.mark.parametrize(
    "artifact_type",
    [
        ArtifactType.report,
        ArtifactType.flashcards,
        ArtifactType.quiz,
        ArtifactType.infographic,
        ArtifactType.slide_deck,
    ],
)
def test_a_ready_version_enqueues_its_pdf_after_commit(
    monkeypatch: pytest.MonkeyPatch, artifact_type: ArtifactType
) -> None:
    version = _Version(artifact_type)
    _, enqueued = _generate(monkeypatch, version)
    assert enqueued == [({"args": [str(version.id)], "queue": "pdf"}, "commit")]


def test_audio_and_outline_review_enqueue_no_pdf(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _generate(monkeypatch, _Version(ArtifactType.audio_overview))[1] == []
    assert _generate(monkeypatch, None)[1] == []


def test_a_broker_error_does_not_fail_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(**_: Any) -> None:
        raise ConnectionError("redis down")

    scope = _Scope()
    version = _Version(ArtifactType.quiz)
    monkeypatch.setattr(generation, "session_scope", scope)
    monkeypatch.setattr(generation, "get_content_provider", lambda: object())
    monkeypatch.setattr(generation, "run_artifact_generation", lambda *a, **k: version)
    monkeypatch.setattr(generation.build_artifact_pdf, "apply_async", broken)
    task = generation.generate_artifact_task
    task.push_request(retries=0)
    try:
        assert task._orig_run(str(uuid.uuid4())) == str(version.id)  # type: ignore[attr-defined]
    finally:
        task.pop_request()
    assert scope.outcome == "commit"
