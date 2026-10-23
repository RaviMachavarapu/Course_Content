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
