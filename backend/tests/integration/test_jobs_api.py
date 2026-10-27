"""T024 — job status + module staging polling API."""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.cli import seed_admin
from app.models.course import Course
from app.models.enums import ArtifactType, GenerationJobState, ModuleSourceType
from app.models.generation_job import GenerationJob
from app.models.module import Module
from app.pipeline import artifact_pdf, orchestrator
from app.pipeline.fixture import FixtureProvider
from app.render.typeset_client import TypesetResult

PROVIDER = FixtureProvider()
GEN_TYPES = [
    ArtifactType.report,
    ArtifactType.audio_overview,
    ArtifactType.flashcards,
    ArtifactType.quiz,
]


def _admin(client: TestClient, db: Session) -> None:
    seed_admin(db, email="jobs@example.com", display_name="J", password="jobs-admin-pw-1")
    db.flush()
    client.post(
        "/api/admin/auth/login", json={"email": "jobs@example.com", "password": "jobs-admin-pw-1"}
    )


def _generated_module(db: Session) -> Module:
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
    jobs = orchestrator.start_module_generation(db, PROVIDER, module.id, GEN_TYPES)
    for job in jobs:
        orchestrator.run_artifact_generation(db, PROVIDER, job.artifact_id, job_id=job.job_id)
    return module


def test_requires_admin(client: TestClient, db_session: Session) -> None:
    module = _generated_module(db_session)
    assert client.get(f"/api/admin/modules/{module.id}/staging").status_code == 401


def test_get_job_and_404(client: TestClient, db_session: Session) -> None:
    _admin(client, db_session)
    module = _generated_module(db_session)
    job = db_session.scalars(
        sa.select(GenerationJob).where(GenerationJob.module_id == module.id)
    ).first()
    got = client.get(f"/api/admin/jobs/{job.id}")
    assert got.status_code == 200
    assert got.json()["state"] == "succeeded"
    assert client.get(f"/api/admin/jobs/{uuid.uuid4()}").status_code == status.HTTP_404_NOT_FOUND


def test_list_module_jobs_newest_first(client: TestClient, db_session: Session) -> None:
    _admin(client, db_session)
    module = _generated_module(db_session)
    resp = client.get(f"/api/admin/modules/{module.id}/jobs")
    assert resp.status_code == 200
    jobs = resp.json()["jobs"]
    assert len(jobs) == len(GEN_TYPES)
    times = [j["created_at"] for j in jobs]
    assert times == sorted(times, reverse=True)


def test_staging_shape_covers_all_states(client: TestClient, db_session: Session) -> None:
    _admin(client, db_session)
    module = _generated_module(db_session)

    # force one artifact's latest job through each state for coverage
    by_type = {a.type: a for a in module.artifacts}
    for art_type, state in (
        (ArtifactType.report, GenerationJobState.succeeded),
        (ArtifactType.quiz, GenerationJobState.running),
        (ArtifactType.flashcards, GenerationJobState.failed),
    ):
        j = db_session.scalars(
            sa.select(GenerationJob).where(GenerationJob.artifact_id == by_type[art_type].id)
        ).first()
        assert j is not None
        j.state = state
    db_session.flush()
    # the report's PDF is typeset after generation (fake service here)
    artifact_pdf.build_version_pdf(
        db_session,
        by_type[ArtifactType.report].current_version_id,
        render=lambda *_: TypesetResult(pdf=b"%PDF-1.7", fallback="0"),
    )

    resp = client.get(f"/api/admin/modules/{module.id}/staging")
    assert resp.status_code == 200
    body = resp.json()
    assert body["module"]["status"]
    assert body["module"]["course_status"]
    assert len(body["artifacts"]) == 6

    got = {a["type"]: a for a in body["artifacts"]}
    assert got["report"]["job"]["state"] == "succeeded"
    assert got["quiz"]["job"]["state"] == "running"
    assert got["flashcards"]["job"]["state"] == "failed"
    assert got["slide_deck"]["job"]["state"] is None  # never generated

    report_cv = got["report"]["current_version"]
    assert report_cv["revision"] == 1
    assert any(m["kind"] == "report_pdf" and m["url"].endswith(".pdf") for m in report_cv["media"])
    assert got["slide_deck"]["current_version"] is None


def test_staging_includes_source_files(client: TestClient, db_session: Session) -> None:
    from app.models.module_source_file import ModuleSourceFile

    _admin(client, db_session)
    module = _generated_module(db_session)
    module.source_files.append(
        ModuleSourceFile(
            order_index=0,
            file_name="book.pdf",
            size_bytes=123,
            checksum_sha256="a" * 64,
            storage_key="module-sources/book.pdf",
            page_count=9,
            parts=[{"first_page": 1}, {"first_page": 5}, {"first_page": 8}],
        )
    )
    db_session.flush()

    body = client.get(f"/api/admin/modules/{module.id}/staging").json()
    assert body["module"]["source_url"] == "https://youtu.be/x"
    assert body["module"]["source_files"] == [
        {"file_name": "book.pdf", "size_bytes": 123, "part_count": 3}
    ]
