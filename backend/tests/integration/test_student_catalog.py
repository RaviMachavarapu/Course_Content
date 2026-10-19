"""T031 — student catalog (published-only, per-caller progress)."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.cli import seed_admin
from app.models.artifact import Artifact
from app.models.enums import ArtifactType
from app.models.module import Module
from app.models.progress import ArtifactProgress
from app.pipeline import orchestrator
from app.pipeline.fixture import FixtureProvider
from app.services.publish import publish_module

PROVIDER = FixtureProvider()
LIVE_TYPES = [ArtifactType.report, ArtifactType.quiz, ArtifactType.flashcards]


@pytest.fixture(autouse=True)
def _no_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.api.admin.courses._dispatch_all", lambda *a, **k: None)


def _admin_headers(client: TestClient, db: Session) -> dict[str, str]:
    seed_admin(db, email="cat-admin@example.com", display_name="A", password="cat-admin-pw-1")
    db.flush()
    client.post(
        "/api/admin/auth/login",
        json={"email": "cat-admin@example.com", "password": "cat-admin-pw-1"},
    )
    return {"X-CSRF-Token": client.cookies["sdp_csrf"]}


def _register_student(client: TestClient) -> None:
    client.post(
        "/api/student/auth/register",
        json={
            "email": "learner@example.com",
            "password": "learner-pw-123",
            "display_name": "Learner",
        },
    )


def _publish_course_with_module(
    client: TestClient, db: Session, h: dict[str, str], title: str
) -> str:
    cid = client.post(
        "/api/admin/courses",
        json={"title": title, "category": "Machine Learning"},
        headers=h,
    ).json()["course"]["id"]
    mid = client.post(
        f"/api/admin/courses/{cid}/modules",
        json={
            "source_url": f"https://example.com/{title}",
            "title": f"{title} module",
            "types": [t.value for t in LIVE_TYPES],
        },
        headers=h,
    ).json()["module"]["id"]

    module = db.get(Module, uuid.UUID(mid))
    assert module is not None
    for artifact in module.artifacts:
        if artifact.type in LIVE_TYPES:
            orchestrator.run_artifact_generation(db, PROVIDER, artifact.id)
    db.expire_all()
    module = db.get(Module, uuid.UUID(mid))
    assert module is not None
    published, _skipped = publish_module(db, module)
    assert len(published) == len(LIVE_TYPES)
    db.flush()
    return cid


def test_catalog_lists_only_published_courses_with_counts(
    client: TestClient, db_session: Session
) -> None:
    h = _admin_headers(client, db_session)
    published_cid = _publish_course_with_module(client, db_session, h, "Published Course")

    # a second course with a module that never gets published
    draft_cid = client.post("/api/admin/courses", json={"title": "Draft Course"}, headers=h).json()[
        "course"
    ]["id"]
    client.post(
        f"/api/admin/courses/{draft_cid}/modules",
        json={"source_url": "https://example.com/draft", "title": "m", "types": ["report"]},
        headers=h,
    )

    _register_student(client)
    body = client.get("/api/student/courses").json()

    slugs = {c["slug"]: c for c in body["courses"]}
    assert len(body["courses"]) == 1
    course = next(iter(slugs.values()))
    assert course["title"] == "Published Course"
    assert course["module_count"] == 1
    assert course["artifact_counts"] == {"report": 1, "quiz": 1, "flashcards": 1}
    assert course["percent_complete"] == 0
    assert course["next_module_index"] == 0
    assert body["categories"] == ["Machine Learning"]
    assert str(published_cid) == course["id"]


def test_percent_complete_tracks_the_callers_progress(
    client: TestClient, db_session: Session
) -> None:
    h = _admin_headers(client, db_session)
    _publish_course_with_module(client, db_session, h, "Progress Course")
    _register_student(client)

    me = client.get("/api/student/auth/me").json()["user"]

    # mark one of the three published artifacts complete for this student
    published_artifacts = db_session.scalars(
        select(Artifact).where(Artifact.published_version_id.is_not(None))
    ).all()
    assert len(published_artifacts) == 3
    db_session.add(
        ArtifactProgress(
            user_id=uuid.UUID(me["id"]),
            artifact_id=published_artifacts[0].id,
            module_id=published_artifacts[0].module_id,
            completed_at=dt.datetime.now(dt.UTC),
        )
    )
    db_session.flush()

    course = client.get("/api/student/courses").json()["courses"][0]
    assert course["percent_complete"] == 33


def test_catalog_requires_a_student_session(client: TestClient, db_session: Session) -> None:
    h = _admin_headers(client, db_session)  # admin session only, no student
    assert client.get("/api/student/courses").status_code == status.HTTP_401_UNAUTHORIZED
    _ = h
