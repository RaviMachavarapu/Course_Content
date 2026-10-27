"""T026 — access-checked media streaming (spec.md §9, §11)."""

from __future__ import annotations

import uuid

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.cli import seed_admin
from app.models.artifact import Artifact
from app.models.course import Course
from app.models.enums import ArtifactStatus, ArtifactType, MediaFileKind, ModuleSourceType
from app.models.module import Module
from app.pipeline import artifact_pdf, orchestrator
from app.pipeline.fixture import FixtureProvider
from app.render.typeset_client import TypesetResult

PROVIDER = FixtureProvider()


@pytest.fixture(autouse=True)
def _no_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.api.admin.courses._dispatch_all", lambda *a, **k: None)


def _report_with_media(db: Session) -> tuple[Artifact, str]:
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
    jobs = orchestrator.start_module_generation(db, PROVIDER, module.id, [ArtifactType.report])
    orchestrator.run_artifact_generation(db, PROVIDER, jobs[0].artifact_id, job_id=jobs[0].job_id)
    db.expire_all()
    artifact = db.get(Artifact, jobs[0].artifact_id)
    # the report's PDF is typeset after generation (fake service here)
    media = artifact_pdf.build_version_pdf(
        db,
        artifact.current_version_id,
        render=lambda *_: TypesetResult(pdf=b"%PDF-1.7 report", fallback="0"),
    ).media
    assert media.kind is MediaFileKind.report_pdf
    return artifact, media.storage_key


def _login_admin(client: TestClient, db: Session) -> None:
    seed_admin(db, email="m@example.com", display_name="M", password="media-admin-pw-1")
    db.flush()
    client.post(
        "/api/admin/auth/login", json={"email": "m@example.com", "password": "media-admin-pw-1"}
    )


def test_admin_can_fetch_any_media(client: TestClient, db_session: Session) -> None:
    _, key = _report_with_media(db_session)
    _login_admin(client, db_session)
    resp = client.get(f"/api/media/{key}")
    assert resp.status_code == status.HTTP_200_OK
    assert resp.headers["content-type"] == "application/pdf"
    assert "immutable" in resp.headers["cache-control"]
    assert resp.content[:5] == b"%PDF-"


def test_anonymous_is_unauthorized(client: TestClient, db_session: Session) -> None:
    _, key = _report_with_media(db_session)
    assert client.get(f"/api/media/{key}").status_code == status.HTTP_401_UNAUTHORIZED


def test_student_denied_for_unpublished_then_allowed_when_published(
    client: TestClient, db_session: Session
) -> None:
    artifact, key = _report_with_media(db_session)
    client.post(
        "/api/student/auth/register",
        json={"email": "s@example.com", "password": "student-pw-12345", "display_name": "S"},
    )

    assert client.get(f"/api/media/{key}").status_code == status.HTTP_404_NOT_FOUND

    artifact = db_session.get(Artifact, artifact.id)
    artifact.published_version_id = artifact.current_version_id
    artifact.status = ArtifactStatus.published
    db_session.flush()

    assert client.get(f"/api/media/{key}").status_code == status.HTTP_200_OK


def test_bad_and_unknown_keys_are_404(client: TestClient, db_session: Session) -> None:
    _login_admin(client, db_session)
    assert client.get("/api/media/../etc/passwd").status_code == status.HTTP_404_NOT_FOUND
    assert client.get("/api/media/courses/x/nope.pdf").status_code == status.HTTP_404_NOT_FOUND


def test_student_cannot_fetch_unpublished_pdf(client: TestClient, db_session: Session) -> None:
    """Review focus 4: a typeset PDF follows the version's publish state. The
    published version's PDF is served; the newer, unpublished one is not."""
    artifact, published_key = _report_with_media(db_session)
    artifact = db_session.get(Artifact, artifact.id)
    artifact.published_version_id = artifact.current_version_id
    artifact.status = ArtifactStatus.published
    db_session.flush()

    # a redo makes a new current version (with its own PDF) that is not published
    orchestrator.run_artifact_generation(db_session, PROVIDER, artifact.id, redo_note="again")
    db_session.expire_all()
    artifact = db_session.get(Artifact, artifact.id)
    assert artifact.current_version_id != artifact.published_version_id
    draft_key = artifact_pdf.build_version_pdf(
        db_session,
        artifact.current_version_id,
        render=lambda *_: TypesetResult(pdf=b"%PDF-1.7 draft", fallback="0"),
    ).media.storage_key
    artifact.status = ArtifactStatus.published
    db_session.flush()

    client.post(
        "/api/student/auth/register",
        json={"email": "p@example.com", "password": "student-pw-12345", "display_name": "P"},
    )
    assert client.get(f"/api/media/{draft_key}").status_code == status.HTTP_404_NOT_FOUND
    resp = client.get(f"/api/media/{published_key}")
    assert resp.status_code == status.HTTP_200_OK
    assert resp.content == b"%PDF-1.7 report"
