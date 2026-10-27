"""T039 — student 'Me' dashboards: Progress, My Listening, Achievements."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.cli import seed_admin
from app.models.artifact import Artifact
from app.models.enums import ArtifactType
from app.models.module import Module
from app.pipeline import orchestrator
from app.pipeline.fixture import FixtureProvider
from app.services.publish import publish_module

PROVIDER = FixtureProvider()
TYPES = [
    ArtifactType.report,
    ArtifactType.quiz,
    ArtifactType.flashcards,
    ArtifactType.audio_overview,
]


@pytest.fixture(autouse=True)
def _no_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.api.admin.courses._dispatch_all", lambda *a, **k: None)


def _setup(client: TestClient, db: Session) -> tuple[str, dict[str, str]]:
    seed_admin(db, email="me-admin@example.com", display_name="A", password="me-admin-pw-1")
    db.flush()
    client.post(
        "/api/admin/auth/login",
        json={"email": "me-admin@example.com", "password": "me-admin-pw-1"},
    )
    h = {"X-CSRF-Token": client.cookies["sdp_csrf"]}
    cid = client.post("/api/admin/courses", json={"title": "Me"}, headers=h).json()["course"]["id"]
    mid = client.post(
        f"/api/admin/courses/{cid}/modules",
        json={
            "source_url": "https://example.com/me",
            "title": "M1",
            "types": [t.value for t in TYPES],
        },
        headers=h,
    ).json()["module"]["id"]
    module = db.get(Module, uuid.UUID(mid))
    assert module is not None
    for artifact in module.artifacts:
        if artifact.type in TYPES:
            orchestrator.run_artifact_generation(db, PROVIDER, artifact.id)
    db.expire_all()
    module = db.get(Module, uuid.UUID(mid))
    assert module is not None
    publish_module(db, module)
    db.flush()

    client.cookies.clear()
    client.post(
        "/api/student/auth/register",
        json={
            "email": "me-learner@example.com",
            "password": "me-learner-pw-1",
            "display_name": "L",
        },
    )
    return module.course.slug, {}


def _ids(client: TestClient, slug: str) -> dict[str, str]:
    ws = client.get(f"/api/student/courses/{slug}").json()
    return {a["type"]: a["id"] for a in ws["modules"][0]["artifacts"]}


def test_dashboards_are_empty_before_any_activity(client: TestClient, db_session: Session) -> None:
    _setup(client, db_session)
    assert client.get("/api/student/me/progress").json()["courses"] == []
    assert client.get("/api/student/me/listening").json()["rows"] == []
    ach = client.get("/api/student/me/achievements").json()
    assert ach["earned"] == []
    assert {b["key"] for b in ach["locked"]} == {"course_complete", "quiz_ace", "flashcard_streak"}


def test_progress_reflects_real_records_and_earns_course_complete(
    client: TestClient, db_session: Session
) -> None:
    slug, _ = _setup(client, db_session)
    ids = _ids(client, slug)

    client.put(
        f"/api/student/artifacts/{ids['report']}/progress",
        json={"completed": True, "complete_module": True},
    )

    prog = client.get("/api/student/me/progress").json()["courses"]
    assert len(prog) == 1
    assert prog[0]["slug"] == slug
    assert prog[0]["percent_complete"] == 100
    assert prog[0]["modules_started"] == 1
    assert prog[0]["modules_total"] == 1

    ach = client.get("/api/student/me/achievements").json()
    # complete_module also finished the flashcards + quiz siblings (BR: "Complete
    # Module" completes every published artifact) — flashcard_streak earns too.
    earned = {b["key"] for b in ach["earned"]}
    assert "course_complete" in earned
    assert all(b["earned_at"] is not None for b in ach["earned"])


def test_quiz_ace_and_flashcard_streak_achievements(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    slug, _ = _setup(client, db_session)
    ids = _ids(client, slug)

    # answers are hidden from the API (spec §3.12) -> read the correct ones
    # straight from the DB-side published version to build a full-marks attempt.
    quiz_artifact = db_session.get(Artifact, uuid.UUID(ids["quiz"]))
    assert quiz_artifact is not None
    version = next(v for v in quiz_artifact.versions if v.id == quiz_artifact.published_version_id)
    questions = version.content_json["questions"]
    monkeypatch.setattr("app.api.student.quiz.enqueue_prepare", lambda *a: None)
    started = client.post(f"/api/student/artifacts/{ids['quiz']}/quiz-attempts")
    assert started.status_code == 201
    attempt_id = started.json()["attempt_id"]
    for i, q in enumerate(questions):
        checked = client.post(
            f"/api/student/quiz-attempts/{attempt_id}/answers",
            json={"index": i, "response": q["correct_index"]},
        )
        assert checked.status_code == 200
    resp = client.post(f"/api/student/quiz-attempts/{attempt_id}/complete")
    assert resp.status_code == 200
    assert resp.json()["score_percent"] == 100.0

    client.put(f"/api/student/artifacts/{ids['flashcards']}/progress", json={"completed": True})

    ach = client.get("/api/student/me/achievements").json()
    assert {b["key"] for b in ach["earned"]} == {"quiz_ace", "flashcard_streak"}
    assert len(ach["locked"]) == 1
    assert ach["locked"][0]["key"] == "course_complete"


def test_listening_shows_percent_from_saved_position(
    client: TestClient, db_session: Session
) -> None:
    slug, _ = _setup(client, db_session)
    ids = _ids(client, slug)

    duration = client.get(f"/api/student/artifacts/{ids['audio_overview']}").json()["content_json"][
        "duration_seconds"
    ]
    halfway = duration // 2
    client.put(
        f"/api/student/artifacts/{ids['audio_overview']}/progress",
        json={"audio_position_seconds": halfway},
    )

    rows = client.get("/api/student/me/listening").json()["rows"]
    assert len(rows) == 1
    row = rows[0]
    assert row["course_slug"] == slug
    assert row["module_index"] == 0
    assert row["audio_position_seconds"] == halfway
    assert row["duration_seconds"] == duration
    assert row["percent_listened"] == round(100 * halfway / duration)
    assert row["completed"] is False


def test_me_endpoints_require_a_student(client: TestClient, db_session: Session) -> None:
    _setup(client, db_session)
    client.cookies.clear()
    assert client.get("/api/student/me/progress").status_code == 401
    assert client.get("/api/student/me/listening").status_code == 401
    assert client.get("/api/student/me/achievements").status_code == 401
