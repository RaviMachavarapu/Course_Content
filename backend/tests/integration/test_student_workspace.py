"""T032 — student course workspace shell + artifact read."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
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
    seed_admin(db, email="ws-admin@example.com", display_name="A", password="ws-admin-pw-1")
    db.flush()
    client.post(
        "/api/admin/auth/login",
        json={"email": "ws-admin@example.com", "password": "ws-admin-pw-1"},
    )
    return {"X-CSRF-Token": client.cookies["sdp_csrf"]}


def _student_id(client: TestClient) -> uuid.UUID:
    client.post(
        "/api/student/auth/register",
        json={
            "email": "ws-learner@example.com",
            "password": "ws-learner-pw-1",
            "display_name": "L",
        },
    )
    return uuid.UUID(client.get("/api/student/auth/me").json()["user"]["id"])


def _publish(client: TestClient, db: Session, h: dict[str, str], title: str) -> tuple[str, str]:
    cid = client.post("/api/admin/courses", json={"title": title}, headers=h).json()["course"]["id"]
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
    slug = module.course.slug
    publish_module(db, module)
    db.flush()
    return slug, mid


def test_workspace_returns_ordered_published_modules(
    client: TestClient, db_session: Session
) -> None:
    h = _admin_headers(client, db_session)
    slug, mid = _publish(client, db_session, h, "Workspace Course")
    _student_id(client)

    body = client.get(f"/api/student/courses/{slug}").json()
    assert body["slug"] == slug
    assert body["percent_complete"] == 0
    assert body["current_module_index"] == 0
    assert len(body["modules"]) == 1
    module = body["modules"][0]
    assert module["index"] == 0
    assert module["id"] == mid
    assert {a["type"] for a in module["artifacts"]} == {"report", "quiz", "flashcards"}
    assert all(a["completed"] is False for a in module["artifacts"])


def test_workspace_progress_reflects_completions(client: TestClient, db_session: Session) -> None:
    h = _admin_headers(client, db_session)
    slug, _mid = _publish(client, db_session, h, "Progress WS")
    sid = _student_id(client)

    art = db_session.scalars(
        select(Artifact).where(Artifact.published_version_id.is_not(None))
    ).first()
    assert art is not None
    db_session.add(
        ArtifactProgress(
            user_id=sid,
            artifact_id=art.id,
            module_id=art.module_id,
            completed_at=dt.datetime.now(dt.UTC),
        )
    )
    db_session.flush()

    body = client.get(f"/api/student/courses/{slug}").json()
    assert body["percent_complete"] == 33
    assert body["modules"][0]["percent_complete"] == 33
    done = [a for a in body["modules"][0]["artifacts"] if a["completed"]]
    assert len(done) == 1


def test_workspace_404_for_unknown_or_unpublished_course(
    client: TestClient, db_session: Session
) -> None:
    h = _admin_headers(client, db_session)
    cid = client.post("/api/admin/courses", json={"title": "Never Published"}, headers=h).json()[
        "course"
    ]["id"]
    client.post(
        f"/api/admin/courses/{cid}/modules",
        json={"source_url": "https://example.com/np", "title": "m", "types": ["report"]},
        headers=h,
    )
    slug = client.get(f"/api/admin/courses/{cid}", headers=h).json()["course"]["slug"]
    _student_id(client)

    assert client.get("/api/student/courses/does-not-exist").status_code == 404
    assert client.get(f"/api/student/courses/{slug}").status_code == 404


def test_get_artifact_returns_published_version_only(
    client: TestClient, db_session: Session
) -> None:
    h = _admin_headers(client, db_session)
    slug, _mid = _publish(client, db_session, h, "Artifact WS")
    _student_id(client)

    ws = client.get(f"/api/student/courses/{slug}").json()
    report = next(a for a in ws["modules"][0]["artifacts"] if a["type"] == "report")

    got = client.get(f"/api/student/artifacts/{report['id']}").json()
    assert got["type"] == "report"
    assert got["revision"] == 1
    assert got["module_index"] == 0
    assert got["course_slug"] == slug
    assert got["content_html"] or got["content_json"]
    assert got["completed"] is False

    assert client.get(f"/api/student/artifacts/{uuid.uuid4()}").status_code == 404


def test_get_artifact_404_when_type_not_published(client: TestClient, db_session: Session) -> None:
    h = _admin_headers(client, db_session)
    slug, mid = _publish(client, db_session, h, "Partial WS")
    _student_id(client)

    module = db_session.get(Module, uuid.UUID(mid))
    assert module is not None
    slides = next(a for a in module.artifacts if a.type is ArtifactType.slide_deck)
    assert slides.published_version_id is None

    assert client.get(f"/api/student/artifacts/{slides.id}").status_code == 404


def test_workspace_requires_student(client: TestClient, db_session: Session) -> None:
    h = _admin_headers(client, db_session)
    slug, _mid = _publish(client, db_session, h, "Auth WS")
    client.cookies.clear()
    assert client.get(f"/api/student/courses/{slug}").status_code == 401
