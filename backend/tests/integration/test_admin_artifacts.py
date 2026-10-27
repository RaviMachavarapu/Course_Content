"""T026 — Artifact Inspect (spec.md §3.4)."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.cli import seed_admin
from app.models.artifact import Artifact
from app.models.course import Course
from app.models.enums import ArtifactType, ModuleSourceType
from app.models.module import Module
from app.pipeline import artifact_pdf, orchestrator
from app.pipeline.fixture import FixtureProvider
from app.render.typeset_client import TypesetResult

PROVIDER = FixtureProvider()


def _generated_report(db: Session) -> Artifact:
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
    return db.get(Artifact, jobs[0].artifact_id)


def _admin(client: TestClient, db: Session) -> None:
    seed_admin(db, email="i@example.com", display_name="I", password="inspect-admin-pw-1")
    db.flush()
    client.post(
        "/api/admin/auth/login", json={"email": "i@example.com", "password": "inspect-admin-pw-1"}
    )


def test_requires_admin(client: TestClient, db_session: Session) -> None:
    artifact = _generated_report(db_session)
    assert client.get(f"/api/admin/artifacts/{artifact.id}").status_code == 401


def test_inspect_returns_current_version_content_media_and_metadata(
    client: TestClient, db_session: Session
) -> None:
    artifact = _generated_report(db_session)
    artifact_pdf.build_version_pdfs(
        db_session,
        artifact.current_version_id,
        render=lambda *_: TypesetResult(pdf=b"%PDF-1.7", fallback="0"),
    )
    _admin(client, db_session)

    body = client.get(f"/api/admin/artifacts/{artifact.id}").json()
    assert body["artifact"]["type"] == "report"
    assert body["notebooklm_notebook_id"]
    v = body["viewing"]
    assert v["revision"] == 1
    assert v["content_json"]["title"]
    assert v["focus_prompt_used"]  # BR6 prompt captured
    assert any(m["kind"] == "report_pdf" for m in v["media"])
    assert len(body["history"]) == 1 and body["history"][0]["is_current"] is True


def test_inspect_specific_past_version(client: TestClient, db_session: Session) -> None:
    artifact = _generated_report(db_session)
    v1_id = artifact.current_version_id
    orchestrator.run_artifact_generation(db_session, PROVIDER, artifact.id, redo_note="v2")
    _admin(client, db_session)

    latest = client.get(f"/api/admin/artifacts/{artifact.id}").json()
    assert latest["viewing"]["revision"] == 2
    assert [h["revision"] for h in latest["history"]] == [2, 1]

    pinned = client.get(
        f"/api/admin/artifacts/{artifact.id}", params={"version": str(v1_id)}
    ).json()
    assert pinned["viewing"]["revision"] == 1


def test_inspect_404_for_unknown(client: TestClient, db_session: Session) -> None:
    _admin(client, db_session)
    assert client.get(f"/api/admin/artifacts/{uuid.uuid4()}").status_code == 404
