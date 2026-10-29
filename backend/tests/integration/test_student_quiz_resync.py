# ruff: noqa: F811  (the fixtures are imported from test_student_quiz)
"""Review 2026-10-29 (review-frontend): after a failed Check the viewer resyncs
by reading the attempt (GET), never by POSTing a start, which could open a new
attempt (and spend a fresh chat-generated set) when this one was finished
elsewhere."""

from __future__ import annotations

from typing import Any

from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.integration.test_student_quiz import (  # noqa: F401  (fixtures)
    SECRET_KEYS,
    _attempt_count,
    _attempt_set,
    _check,
    _finish,
    _identity_order,
    _no_dispatch,
    _register,
    _right,
    _setup,
    _start,
    enqueued,
)


def _get(client: TestClient, attempt_id: str) -> Any:
    return client.get(f"/api/student/quiz-attempts/{attempt_id}")


def test_reading_an_attempt_shows_checked_results_and_starts_nothing(
    client: TestClient, db_session: Session, enqueued: list[tuple[str, str]]
) -> None:
    ctx = _setup(client, db_session, enqueued)
    attempt_id = _start(client, ctx).json()["attempt_id"]
    q0 = _attempt_set(db_session, attempt_id).questions[0]
    assert _check(client, attempt_id, 0, _right(q0)).status_code == status.HTTP_200_OK
    before = _attempt_count(db_session, ctx)

    r = _get(client, attempt_id)
    assert r.status_code == status.HTTP_200_OK
    body = r.json()
    assert body["attempt_id"] == attempt_id
    assert body["status"] == "resumed"
    assert body["checked_count"] == 1
    assert body["questions"][0]["result"]["correct"] is True
    for q in body["questions"][1:]:
        assert q["result"] is None
        assert not set(q) & set(SECRET_KEYS)
    assert _attempt_count(db_session, ctx) == before


def test_a_finished_attempt_reads_as_409_and_opens_no_new_one(
    client: TestClient, db_session: Session, enqueued: list[tuple[str, str]]
) -> None:
    ctx = _setup(client, db_session, enqueued)
    attempt_id = _start(client, ctx).json()["attempt_id"]
    _finish(client, db_session, attempt_id)
    before = _attempt_count(db_session, ctx)
    r = _get(client, attempt_id)
    assert r.status_code == status.HTTP_409_CONFLICT
    assert r.json()["error"]["code"] == "attempt_completed"
    assert _attempt_count(db_session, ctx) == before


def test_someone_elses_attempt_is_a_404(
    client: TestClient, db_session: Session, enqueued: list[tuple[str, str]]
) -> None:
    ctx = _setup(client, db_session, enqueued)
    attempt_id = _start(client, ctx).json()["attempt_id"]
    _register(client, "other-learner@example.com")
    assert _get(client, attempt_id).status_code == status.HTTP_404_NOT_FOUND
