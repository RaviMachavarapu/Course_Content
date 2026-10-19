"""T033 — student artifact progress writes + course roll-up."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.cli import seed_admin
from app.models.enums import ArtifactType
from app.models.module import Module
from app.pipeline import orchestrator
from app.pipeline.fixture import FixtureProvider
from app.services.publish import publish_module

PROVIDER = FixtureProvider()
LIVE_TYPES = [ArtifactType.report, ArtifactType.quiz, ArtifactType.flashcards]


@pytest.fixture(autouse=True)
def _no_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.api.admin.courses._dispatch_all", lambda *a, **k: None)


def _setup(client: TestClient, db: Session) -> tuple[str, dict[str, str]]:
    seed_admin(db, email="pg-admin@example.com", display_name="A", password="pg-admin-pw-1")
    db.flush()
    client.post(
        "/api/admin/auth/login",
        json={"email": "pg-admin@example.com", "password": "pg-admin-pw-1"},
    )
    h = {"X-CSRF-Token": client.cookies["sdp_csrf"]}
    cid = client.post("/api/admin/courses", json={"title": "Progress"}, headers=h).json()["course"][
        "id"
    ]
    mid = client.post(
        f"/api/admin/courses/{cid}/modules",
        json={
            "source_url": "https://example.com/p",
            "title": "M1",
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
    slug = module.course.slug
    publish_module(db, module)
    db.flush()

    client.cookies.clear()
    client.post(
        "/api/student/auth/register",
        json={
            "email": "pg-learner@example.com",
            "password": "pg-learner-pw-1",
            "display_name": "L",
        },
    )
    return slug, h


def _artifact_ids(client: TestClient, slug: str) -> dict[str, str]:
    ws = client.get(f"/api/student/courses/{slug}").json()
    return {a["type"]: a["id"] for a in ws["modules"][0]["artifacts"]}


def test_completing_an_artifact_rolls_up_the_course_percentage(
    client: TestClient, db_session: Session
) -> None:
    slug, _h = _setup(client, db_session)
    ids = _artifact_ids(client, slug)

    resp = client.put(f"/api/student/artifacts/{ids['report']}/progress", json={"completed": True})
    assert resp.status_code == 200
    assert resp.json() == {
        "completed": True,
        "slide_last_index": None,
        "audio_position_seconds": None,
        "course_percent_complete": 33,
    }

    assert client.get(f"/api/student/artifacts/{ids['report']}").json()["completed"] is True
    ws = client.get(f"/api/student/courses/{slug}").json()
    assert ws["percent_complete"] == 33
    assert ws["modules"][0]["percent_complete"] == 33
    assert ws["current_module_index"] == 0


def test_completion_is_sticky_and_resume_index_persists(
    client: TestClient, db_session: Session
) -> None:
    slug, _h = _setup(client, db_session)
    ids = _artifact_ids(client, slug)

    client.put(f"/api/student/artifacts/{ids['report']}/progress", json={"completed": True})
    # a later "not complete" ping (e.g. re-open) never un-completes
    again = client.put(
        f"/api/student/artifacts/{ids['report']}/progress",
        json={"completed": False, "slide_last_index": 3},
    ).json()
    assert again["completed"] is True
    assert again["slide_last_index"] == 3
    assert again["course_percent_complete"] == 33

    got = client.get(f"/api/student/artifacts/{ids['report']}").json()
    assert got["completed"] is True
    assert got["slide_last_index"] == 3


def test_complete_module_marks_every_published_artifact(
    client: TestClient, db_session: Session
) -> None:
    slug, _h = _setup(client, db_session)
    ids = _artifact_ids(client, slug)

    resp = client.put(
        f"/api/student/artifacts/{ids['report']}/progress",
        json={"completed": True, "complete_module": True},
    ).json()
    assert resp["completed"] is True
    assert resp["course_percent_complete"] == 100

    ws = client.get(f"/api/student/courses/{slug}").json()
    assert ws["percent_complete"] == 100
    assert ws["modules"][0]["percent_complete"] == 100
    assert all(a["completed"] for a in ws["modules"][0]["artifacts"])


def test_progress_requires_student_and_valid_artifact(
    client: TestClient, db_session: Session
) -> None:
    slug, _h = _setup(client, db_session)
    ids = _artifact_ids(client, slug)

    assert client.put(f"/api/student/artifacts/{uuid.uuid4()}/progress", json={}).status_code == 404

    client.cookies.clear()
    assert (
        client.put(
            f"/api/student/artifacts/{ids['report']}/progress", json={"completed": True}
        ).status_code
        == 401
    )
