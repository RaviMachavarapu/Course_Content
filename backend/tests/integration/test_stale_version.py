"""Review 2026-10-29 (scenario 19): a student still on deck v1 after v2 was
published must not rate or complete v2. The viewer echoes the version it
shows (`version_id` from GET /artifacts/{id}); a write for a version that is
no longer the published one is a 409 `stale_version`."""

from __future__ import annotations

import uuid

from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.artifact import Artifact
from app.models.course import Course
from app.models.enums import ArtifactType
from app.models.flashcard_rating import FlashcardRating
from app.models.module import Module
from app.models.progress import ArtifactProgress, CourseProgress
from app.pipeline import orchestrator
from app.services.publish import publish_module
from tests.integration.test_review_data_fixes import PROVIDER, _artifact, _module, _student


def _republish(db: Session, module_id: uuid.UUID, artifact_id: uuid.UUID) -> Artifact:
    orchestrator.run_artifact_generation(db, PROVIDER, artifact_id, redo_note="new deck")
    db.expire_all()
    module = db.get(Module, module_id)
    assert module is not None
    publish_module(db, module)
    db.flush()
    db.expire_all()
    artifact = db.get(Artifact, artifact_id)
    assert artifact is not None
    return artifact


def test_the_student_artifact_names_its_published_version(
    client: TestClient, db_session: Session
) -> None:
    course = Course(title="V", slug=f"v-{uuid.uuid4()}")
    module = _module(db_session, course, 0, [ArtifactType.flashcards])
    deck = _artifact(module, ArtifactType.flashcards)
    _student(client)
    body = client.get(f"/api/student/artifacts/{deck.id}").json()
    assert body["version_id"] == str(deck.published_version_id)


def test_stale_deck_page_cannot_rate_or_complete_the_new_deck(
    client: TestClient, db_session: Session
) -> None:
    course = Course(title="Stale", slug=f"stale-{uuid.uuid4()}")
    module = _module(db_session, course, 0, [ArtifactType.flashcards])
    deck = _artifact(module, ArtifactType.flashcards)
    _student(client)
    v1 = client.get(f"/api/student/artifacts/{deck.id}").json()["version_id"]

    deck = _republish(db_session, module.id, deck.id)
    assert str(deck.published_version_id) != v1

    rate = client.put(
        f"/api/student/artifacts/{deck.id}/flashcard-ratings/5",
        json={"value": "easy", "version_id": v1},
    )
    assert rate.status_code == status.HTTP_409_CONFLICT
    assert rate.json()["error"]["code"] == "stale_version"

    done = client.put(
        f"/api/student/artifacts/{deck.id}/progress", json={"completed": True, "version_id": v1}
    )
    assert done.status_code == status.HTTP_409_CONFLICT
    assert done.json()["error"]["code"] == "stale_version"

    assert (
        db_session.scalars(
            select(FlashcardRating).where(FlashcardRating.artifact_id == deck.id)
        ).all()
        == []
    )
    progress = db_session.scalars(
        select(ArtifactProgress).where(ArtifactProgress.artifact_id == deck.id)
    ).all()
    assert all(p.completed_at is None for p in progress)
    assert (
        db_session.scalars(
            select(CourseProgress).where(
                CourseProgress.course_id == course.id, CourseProgress.completed_at.is_not(None)
            )
        ).all()
        == []
    )

    # the reloaded page carries v2 and works
    v2 = client.get(f"/api/student/artifacts/{deck.id}").json()["version_id"]
    ok = client.put(
        f"/api/student/artifacts/{deck.id}/flashcard-ratings/0",
        json={"value": "easy", "version_id": v2},
    )
    assert ok.status_code == status.HTTP_200_OK
    done = client.put(
        f"/api/student/artifacts/{deck.id}/progress", json={"completed": True, "version_id": v2}
    )
    assert done.status_code == status.HTTP_200_OK
    assert done.json()["completed"] is True


def test_a_malformed_version_id_is_a_422(client: TestClient, db_session: Session) -> None:
    course = Course(title="Bad", slug=f"bad-{uuid.uuid4()}")
    module = _module(db_session, course, 0, [ArtifactType.flashcards])
    deck = _artifact(module, ArtifactType.flashcards)
    _student(client)
    r = client.put(
        f"/api/student/artifacts/{deck.id}/flashcard-ratings/0",
        json={"value": "easy", "version_id": "v1"},
    )
    assert r.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
