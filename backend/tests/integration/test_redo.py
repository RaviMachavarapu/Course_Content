"""T023 — redo / retry a single artifact."""

from __future__ import annotations

import uuid

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.cli import seed_admin
from app.models.artifact import Artifact
from app.models.course import Course
from app.models.enums import ArtifactStatus, ArtifactType, ModuleSourceType
from app.models.module import Module
from app.pipeline import orchestrator
from app.pipeline.fixture import FixtureProvider

PROVIDER = FixtureProvider()


@pytest.fixture(autouse=True)
def _no_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.api.admin.staging._dispatch", lambda *a, **k: None)


def _module_with_generated(db: Session, types: list[ArtifactType]) -> Module:
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
    return module


def _admin_headers(client: TestClient, db: Session) -> dict[str, str]:
    seed_admin(db, email="redo@example.com", display_name="R", password="redo-admin-pw-1")
    db.flush()
    client.post(
        "/api/admin/auth/login", json={"email": "redo@example.com", "password": "redo-admin-pw-1"}
    )
    return {"X-CSRF-Token": client.cookies["sdp_csrf"]}


# -- orchestrator-level ------------------------------------------------
def test_redo_bumps_revision_and_stores_note_without_touching_siblings(db_session: Session) -> None:
    module = _module_with_generated(db_session, [ArtifactType.report, ArtifactType.quiz])
    report = next(a for a in module.artifacts if a.type is ArtifactType.report)
    quiz = next(a for a in module.artifacts if a.type is ArtifactType.quiz)
    quiz_v1 = quiz.current_version_id

    v2 = orchestrator.run_artifact_generation(
        db_session, PROVIDER, report.id, redo_note="Make it shorter"
    )
    db_session.expire_all()

    report = db_session.get(Artifact, report.id)
    assert v2.revision == 2
    assert v2.redo_note == "Make it shorter"
    assert "Make it shorter" in v2.focus_prompt_used
    assert report.current_version_id == v2.id
    assert report.status is ArtifactStatus.ready
    # sibling untouched
    assert db_session.get(Artifact, quiz.id).current_version_id == quiz_v1


def test_redo_can_override_generation_options(db_session: Session) -> None:
    module = _module_with_generated(db_session, [ArtifactType.quiz])
    quiz = next(a for a in module.artifacts if a.type is ArtifactType.quiz)
    assert quiz.generation_options == {"quantity": "standard", "difficulty": "medium"}

    orchestrator.enqueue_artifact_regeneration(
        db_session,
        quiz.id,
        redo_note="harder please",
        options={"quantity": "more", "difficulty": "hard"},
    )
    db_session.expire_all()
    quiz = db_session.get(Artifact, quiz.id)
    assert quiz.generation_options == {"quantity": "more", "difficulty": "hard"}


def test_redo_on_published_keeps_published_version_live(db_session: Session) -> None:
    module = _module_with_generated(db_session, [ArtifactType.report])
    report = next(a for a in module.artifacts if a.type is ArtifactType.report)
    published = report.current_version_id
    report.published_version_id = published
    db_session.flush()

    v2 = orchestrator.run_artifact_generation(db_session, PROVIDER, report.id, redo_note="v2")
    db_session.expire_all()

    report = db_session.get(Artifact, report.id)
    assert report.current_version_id == v2.id
    assert report.published_version_id == published  # student still sees v1
    assert report.status is ArtifactStatus.ready


# -- API ------------------------------------------------------------
def test_redo_endpoint_queues_a_redo_job(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.api.admin.staging._dispatch", lambda *a, **k: None)
    module = _module_with_generated(db_session, [ArtifactType.report])
    report = next(a for a in module.artifacts if a.type is ArtifactType.report)
    headers = _admin_headers(client, db_session)

    resp = client.post(
        f"/api/admin/artifacts/{report.id}/redo",
        json={"note": "focus on training"},
        headers=headers,
    )
    assert resp.status_code == status.HTTP_202_ACCEPTED
    job = resp.json()["job"]
    assert job["kind"] == "redo_artifact"
    assert job["state"] == "queued"
    db_session.expire_all()
    assert db_session.get(Artifact, report.id).status is ArtifactStatus.processing


def test_redo_endpoint_accepts_option_overrides(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.api.admin.staging._dispatch", lambda *a, **k: None)
    module = _module_with_generated(db_session, [ArtifactType.audio_overview])
    audio = next(a for a in module.artifacts if a.type is ArtifactType.audio_overview)
    headers = _admin_headers(client, db_session)

    resp = client.post(
        f"/api/admin/artifacts/{audio.id}/redo",
        json={"note": "make it a debate", "options": {"format": "debate", "length": "long"}},
        headers=headers,
    )
    assert resp.status_code == status.HTTP_202_ACCEPTED
    db_session.expire_all()
    audio = db_session.get(Artifact, audio.id)
    assert audio.generation_options == {"format": "debate", "length": "long", "language": "en"}


def test_retry_only_on_error(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.api.admin.staging._dispatch", lambda *a, **k: None)
    module = _module_with_generated(db_session, [ArtifactType.report])
    report = next(a for a in module.artifacts if a.type is ArtifactType.report)
    headers = _admin_headers(client, db_session)

    # ready -> 409
    assert (
        client.post(f"/api/admin/artifacts/{report.id}/retry", headers=headers).status_code
        == status.HTTP_409_CONFLICT
    )

    report.status = ArtifactStatus.error
    report.last_error = "boom"
    db_session.flush()
    resp = client.post(f"/api/admin/artifacts/{report.id}/retry", headers=headers)
    assert resp.status_code == status.HTTP_202_ACCEPTED
    assert resp.json()["job"]["kind"] == "generate_artifact"


def test_redo_requires_admin(client: TestClient, db_session: Session) -> None:
    module = _module_with_generated(db_session, [ArtifactType.report])
    report = next(a for a in module.artifacts if a.type is ArtifactType.report)
    assert (
        client.post(f"/api/admin/artifacts/{report.id}/redo", json={}).status_code
        == status.HTTP_401_UNAUTHORIZED
    )
