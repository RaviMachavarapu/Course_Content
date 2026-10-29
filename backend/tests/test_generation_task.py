"""generate_artifact_task: retry/skip contract around the orchestrator.

The orchestrator commits every state change itself (claim, failure, result), so
a failure is persisted whatever the task's own session does. The task decides
only whether a transient error may re-queue the job (retries left) and treats a
job that can't be claimed (`JobSkipped`: duplicate or redelivered message) as a
no-op.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest

from app.models.enums import ArtifactType
from app.pipeline.orchestrator import JobSkipped
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


def _call(
    monkeypatch: pytest.MonkeyPatch, effect: Any, retries: int
) -> tuple[list[dict[str, Any]], Any]:
    seen: list[dict[str, Any]] = []
    monkeypatch.setattr(generation, "session_scope", _Scope())
    monkeypatch.setattr(generation, "get_content_provider", lambda: object())

    def run(*_: Any, **kwargs: Any) -> Any:
        seen.append(kwargs)
        if isinstance(effect, Exception):
            raise effect
        return effect

    monkeypatch.setattr(generation, "run_artifact_generation", run)
    task = generation.generate_artifact_task
    task.push_request(retries=retries)
    try:
        return seen, task._orig_run(str(uuid.uuid4()))  # type: ignore[attr-defined]
    finally:
        task.pop_request()


def test_a_transient_error_may_requeue_only_while_retries_are_left(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(TransientProviderError):
        _call(monkeypatch, TransientProviderError("timeout"), retries=0)
    seen, _ = _call(monkeypatch, None, retries=0)
    assert seen[0]["retry_transient"] is True
    seen, _ = _call(monkeypatch, None, retries=generation._MAX_RETRIES)
    assert seen[0]["retry_transient"] is False


def test_a_permanent_failure_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ProviderError):
        _call(monkeypatch, ProviderError("bad response"), retries=0)


def test_a_job_that_cannot_be_claimed_is_a_no_op(monkeypatch: pytest.MonkeyPatch) -> None:
    _, outcome = _call(monkeypatch, JobSkipped("job is succeeded, not queued"), retries=0)
    assert outcome == "skipped"


def test_the_heartbeat_thread_stops_with_the_task(monkeypatch: pytest.MonkeyPatch) -> None:
    import threading

    beats: list[uuid.UUID] = []
    monkeypatch.setattr(
        generation, "get_settings", lambda: type("S", (), {"job_heartbeat_sec": 0.01})()
    )
    monkeypatch.setattr(generation, "touch_job_heartbeat", lambda _db, jid: beats.append(jid))
    monkeypatch.setattr(generation, "session_scope", _Scope())
    job_id = uuid.uuid4()
    with generation._heartbeat(str(job_id)):
        deadline = threading.Event()
        deadline.wait(0.1)
    count = len(beats)
    threading.Event().wait(0.05)
    assert count >= 1 and set(beats) == {job_id}
    assert len(beats) == count  # stopped
    assert not [t for t in threading.enumerate() if t.name == f"heartbeat-{job_id}"]


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
    monkeypatch.setattr(generation, "_heartbeat", lambda _job_id: _no_heartbeat())
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


@contextmanager
def _no_heartbeat() -> Iterator[None]:
    yield
