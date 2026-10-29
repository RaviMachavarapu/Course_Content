"""T027 — publish module / course (BR2-BR5)."""

from __future__ import annotations

import uuid

from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.cli import seed_admin
from app.models.artifact import Artifact
from app.models.course import Course
from app.models.enums import (
    ArtifactStatus,
    ArtifactType,
    CourseStatus,
    ModuleSourceType,
    ModuleStatus,
)
from app.models.module import Module
from app.pipeline import orchestrator
from app.pipeline.fixture import FixtureProvider

PROVIDER = FixtureProvider()
FIXABLE = [
    ArtifactType.report,
    ArtifactType.audio_overview,
    ArtifactType.flashcards,
    ArtifactType.quiz,
]


def _admin(client: TestClient, db: Session) -> dict[str, str]:
    seed_admin(db, email="pub@example.com", display_name="P", password="publish-admin-pw-1")
    db.flush()
    client.post(
        "/api/admin/auth/login", json={"email": "pub@example.com", "password": "publish-admin-pw-1"}
    )
    return {"X-CSRF-Token": client.cookies["sdp_csrf"]}


def _module(db: Session, types: list[ArtifactType]) -> Module:
    course = Course(title="C", slug=f"c-{uuid.uuid4()}")
    module = Module(
        course=course,
        order_index=0,
        title="M",
        source_url="https://youtu.be/x",
        source_type=ModuleSourceType.youtube,
    )
    db.add(module)
    db.flush()
    jobs = orchestrator.start_module_generation(db, PROVIDER, module.id, types)
    for job in jobs:
        orchestrator.run_artifact_generation(db, PROVIDER, job.artifact_id, job_id=job.job_id)
    db.expire_all()
    return db.get(Module, module.id)


def test_publish_module_partial_reports_skips(client: TestClient, db_session: Session) -> None:
    h = _admin(client, db_session)
    module = _module(db_session, FIXABLE)  # 4 ready, 2 pending

    resp = client.post(f"/api/admin/modules/{module.id}/publish", headers=h)
    assert resp.status_code == status.HTTP_200_OK
    body = resp.json()
    assert set(body["published"]) == {t.value for t in FIXABLE}
    skipped = {s["type"]: s for s in body["skipped"]}
    assert set(skipped) == {"slide_deck", "infographic"}
    assert skipped["slide_deck"]["reason"] == "not generated yet"
    # the two skipped types were never requested (still `pending`), so every
    # generated artifact is live: the module is published (review 2026-10-28)
    assert body["module_status"] == ModuleStatus.published.value
    assert body["course_status"] == CourseStatus.published.value

    db_session.expire_all()
    for a in db_session.get(Module, module.id).artifacts:
        if a.type in FIXABLE:
            assert a.status is ArtifactStatus.published
            assert a.published_version_id == a.current_version_id


def test_publish_all_six_makes_module_published(client: TestClient, db_session: Session) -> None:
    h = _admin(client, db_session)
    module = _module(db_session, FIXABLE)
    a_version = next(a.current_version_id for a in module.artifacts if a.current_version_id)
    # force the two renderer-less types to `ready` so all six publish
    for a in module.artifacts:
        if a.status is ArtifactStatus.pending:
            a.status = ArtifactStatus.ready
            a.current_version_id = a_version
    db_session.flush()

    body = client.post(f"/api/admin/modules/{module.id}/publish", headers=h).json()
    assert len(body["published"]) == 6 and body["skipped"] == []
    assert body["module_status"] == ModuleStatus.published.value


def test_publish_does_not_touch_processing(client: TestClient, db_session: Session) -> None:
    h = _admin(client, db_session)
    module = _module(db_session, [ArtifactType.report, ArtifactType.quiz])
    quiz = next(a for a in module.artifacts if a.type is ArtifactType.quiz)
    quiz.status = ArtifactStatus.processing
    db_session.flush()

    body = client.post(f"/api/admin/modules/{module.id}/publish", headers=h).json()
    assert body["published"] == ["report"]
    assert {s["type"]: s["reason"] for s in body["skipped"]}["quiz"] == "still generating"
    db_session.expire_all()
    assert db_session.get(Artifact, quiz.id).status is ArtifactStatus.processing


def test_republish_after_redo_advances_published_version(
    client: TestClient, db_session: Session
) -> None:
    h = _admin(client, db_session)
    module = _module(db_session, [ArtifactType.report])
    report = next(a for a in module.artifacts if a.type is ArtifactType.report)

    client.post(f"/api/admin/modules/{module.id}/publish", headers=h)
    db_session.expire_all()
    report = db_session.get(Artifact, report.id)
    v1 = report.published_version_id

    orchestrator.run_artifact_generation(db_session, PROVIDER, report.id, redo_note="v2")
    db_session.expire_all()
    report = db_session.get(Artifact, report.id)
    assert report.published_version_id == v1  # BR5 — redo doesn't move it
    assert report.current_version_id != v1

    client.post(f"/api/admin/modules/{module.id}/publish", headers=h)
    db_session.expire_all()
    report = db_session.get(Artifact, report.id)
    assert report.published_version_id == report.current_version_id != v1


def test_publish_course_across_modules_and_stamps_published_at(
    client: TestClient, db_session: Session
) -> None:
    h = _admin(client, db_session)
    m1 = _module(db_session, [ArtifactType.report])
    course = db_session.get(Course, m1.course_id)
    m2 = Module(
        course=course,
        order_index=1,
        title="M2",
        source_url="https://youtu.be/y",
        source_type=ModuleSourceType.youtube,
    )
    db_session.add(m2)
    db_session.flush()
    jobs = orchestrator.start_module_generation(db_session, PROVIDER, m2.id, [ArtifactType.quiz])
    for j in jobs:
        orchestrator.run_artifact_generation(db_session, PROVIDER, j.artifact_id, job_id=j.job_id)
    db_session.flush()

    assert course.published_at is None
    body = client.post(f"/api/admin/courses/{course.id}/publish", headers=h).json()
    assert set(body["published"]) == {"report", "quiz"}
    db_session.expire_all()
    assert db_session.get(Course, course.id).published_at is not None


def test_publish_requires_admin(client: TestClient, db_session: Session) -> None:
    module = _module(db_session, [ArtifactType.report])
    assert client.post(f"/api/admin/modules/{module.id}/publish").status_code == 401


def test_publish_unknown_module_is_404(client: TestClient, db_session: Session) -> None:
    h = _admin(client, db_session)
    resp = client.post(f"/api/admin/modules/{uuid.uuid4()}/publish", headers=h)
    assert resp.status_code == status.HTTP_404_NOT_FOUND
    assert resp.json()["error"]["code"] == "not_found"


def test_publish_unknown_course_is_404(client: TestClient, db_session: Session) -> None:
    h = _admin(client, db_session)
    resp = client.post(f"/api/admin/courses/{uuid.uuid4()}/publish", headers=h)
    assert resp.status_code == status.HTTP_404_NOT_FOUND
    assert resp.json()["error"]["code"] == "not_found"
