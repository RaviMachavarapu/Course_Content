"""T023 — redo / retry a single artifact."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.cli import seed_admin
from app.models.artifact import Artifact
from app.models.artifact_version import ArtifactVersion
from app.models.course import Course
from app.models.enums import ArtifactStatus, ArtifactType, ModuleSourceType
from app.models.module import Module
from app.pipeline import orchestrator
from app.pipeline.fixture import FixtureProvider
from app.services.prompts import seed_prompt_templates

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
    assert quiz.generation_options == {
        "quantity": "standard",
        "difficulty": "medium",
        "language": "en",
    }

    orchestrator.enqueue_artifact_regeneration(
        db_session,
        quiz.id,
        redo_note="harder please",
        options={"quantity": "more", "difficulty": "hard"},
    )
    db_session.expire_all()
    quiz = db_session.get(Artifact, quiz.id)
    assert quiz.generation_options == {"quantity": "more", "difficulty": "hard", "language": "en"}


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
        json={"note": "make it a debate", "options": {"format": "debate", "length": "short"}},
        headers=headers,
    )
    assert resp.status_code == status.HTTP_202_ACCEPTED
    db_session.expire_all()
    audio = db_session.get(Artifact, audio.id)
    assert audio.generation_options == {"format": "debate", "length": "short", "language": "en"}


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


# -- custom prompt (replaces the Settings template) ----------------------
def test_custom_prompt_replaces_the_template_and_records_no_template_version(
    db_session: Session,
) -> None:
    seed_prompt_templates(db_session)
    module = _module_with_generated(db_session, [ArtifactType.report])
    report = next(a for a in module.artifacts if a.type is ArtifactType.report)
    v1 = db_session.get(ArtifactVersion, report.current_version_id)
    assert v1 is not None and v1.prompt_template_version is not None  # template path

    orchestrator.enqueue_artifact_regeneration(
        db_session, report.id, redo_note=None, custom_prompt="  Only cover chapter 2.  "
    )
    v2 = orchestrator.run_artifact_generation(db_session, PROVIDER, report.id)
    assert report.custom_prompt == "Only cover chapter 2."
    assert v2.focus_prompt_used == "Only cover chapter 2."
    assert v2.prompt_template_id is None
    assert v2.prompt_template_version is None

    v3 = orchestrator.run_artifact_generation(db_session, PROVIDER, report.id, redo_note="Shorter")
    assert v3.focus_prompt_used == (
        "Only cover chapter 2.\n\nAdditional instruction for this revision:\nShorter"
    )


def test_blank_custom_prompt_reverts_to_the_template(db_session: Session) -> None:
    seed_prompt_templates(db_session)
    module = _module_with_generated(db_session, [ArtifactType.quiz])
    quiz = next(a for a in module.artifacts if a.type is ArtifactType.quiz)
    quiz.custom_prompt = "Custom"
    db_session.flush()

    orchestrator.enqueue_artifact_regeneration(
        db_session, quiz.id, redo_note=None, custom_prompt="   "
    )
    assert quiz.custom_prompt is None
    v = orchestrator.run_artifact_generation(db_session, PROVIDER, quiz.id)
    assert v.prompt_template_version is not None
    assert v.focus_prompt_used != "Custom"


def test_redo_without_custom_prompt_field_keeps_the_stored_text(db_session: Session) -> None:
    module = _module_with_generated(db_session, [ArtifactType.quiz])
    quiz = next(a for a in module.artifacts if a.type is ArtifactType.quiz)
    quiz.custom_prompt = "Keep me"
    db_session.flush()

    orchestrator.enqueue_artifact_regeneration(db_session, quiz.id, redo_note="note")
    assert quiz.custom_prompt == "Keep me"


def test_rerun_all_keeps_custom_prompts(db_session: Session) -> None:
    module = _module_with_generated(db_session, [ArtifactType.report])
    report = next(a for a in module.artifacts if a.type is ArtifactType.report)
    report.custom_prompt = "Keep me"
    db_session.flush()

    orchestrator.start_module_generation(db_session, PROVIDER, module.id, [ArtifactType.report])
    assert report.custom_prompt == "Keep me"


def test_redo_endpoint_sets_and_clears_the_custom_prompt(
    client: TestClient, db_session: Session
) -> None:
    module = _module_with_generated(db_session, [ArtifactType.slide_deck])
    deck = next(a for a in module.artifacts if a.type is ArtifactType.slide_deck)
    headers = _admin_headers(client, db_session)

    resp = client.post(
        f"/api/admin/artifacts/{deck.id}/redo",
        json={"note": None, "custom_prompt": "A deck for beginners"},
        headers=headers,
    )
    assert resp.status_code == status.HTTP_202_ACCEPTED
    db_session.expire_all()
    assert db_session.get(Artifact, deck.id).custom_prompt == "A deck for beginners"

    staging = client.get(f"/api/admin/modules/{module.id}/staging").json()
    by_type = {a["type"]: a for a in staging["artifacts"]}
    assert by_type["slide_deck"]["custom_prompt"] == "A deck for beginners"

    orchestrator.run_artifact_generation(db_session, PROVIDER, deck.id)  # the redo finishes
    resp = client.post(
        f"/api/admin/artifacts/{deck.id}/redo", json={"custom_prompt": ""}, headers=headers
    )
    assert resp.status_code == status.HTTP_202_ACCEPTED
    db_session.expire_all()
    assert db_session.get(Artifact, deck.id).custom_prompt is None


def test_redo_endpoint_rejects_an_over_long_custom_prompt(
    client: TestClient, db_session: Session
) -> None:
    module = _module_with_generated(db_session, [ArtifactType.report])
    report = next(a for a in module.artifacts if a.type is ArtifactType.report)
    headers = _admin_headers(client, db_session)
    resp = client.post(
        f"/api/admin/artifacts/{report.id}/redo",
        json={"custom_prompt": "x" * 4001},
        headers=headers,
    )
    assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_rerun_all_keeps_each_artifacts_options(db_session: Session) -> None:
    module = _module_with_generated(db_session, [ArtifactType.quiz])
    quiz = next(a for a in module.artifacts if a.type is ArtifactType.quiz)
    quiz.generation_options = {"quantity": "more", "difficulty": "hard", "language": "hi"}
    db_session.flush()

    orchestrator.start_module_generation(db_session, PROVIDER, module.id, [ArtifactType.quiz])
    assert quiz.generation_options == {"quantity": "more", "difficulty": "hard", "language": "hi"}


# -- one generation per artifact at a time (review 2026-10-28) ---------------------------
def test_redo_while_processing_is_409_and_queues_nothing(
    client: TestClient, db_session: Session
) -> None:
    from sqlalchemy import func, select

    from app.models.generation_job import GenerationJob

    module = _module_with_generated(db_session, [ArtifactType.report])
    report = next(a for a in module.artifacts if a.type is ArtifactType.report)
    headers = _admin_headers(client, db_session)
    url = f"/api/admin/artifacts/{report.id}/redo"
    assert client.post(url, json={}, headers=headers).status_code == status.HTTP_202_ACCEPTED

    def jobs() -> int:
        return (
            db_session.scalar(select(func.count()).where(GenerationJob.artifact_id == report.id))
            or 0
        )

    before = jobs()
    resp = client.post(url, json={"note": "again"}, headers=headers)
    assert resp.status_code == status.HTTP_409_CONFLICT
    assert resp.json()["error"]["code"] == "artifact_busy"
    assert "still generating" in resp.json()["error"]["message"]
    assert jobs() == before


def test_rerun_all_while_generating_is_409(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.api.admin.courses._dispatch_all", lambda *a, **k: None)
    module = _module_with_generated(db_session, [ArtifactType.report])
    headers = _admin_headers(client, db_session)
    url = f"/api/admin/courses/modules/{module.id}/regenerate"
    assert client.post(url, headers=headers).status_code == status.HTTP_200_OK
    resp = client.post(url, headers=headers)
    assert resp.status_code == status.HTTP_409_CONFLICT
    assert resp.json()["error"]["code"] == "module_busy"


def test_retry_after_a_timeout_resumes_the_notebooklm_artifact(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[tuple[Any, ...]] = []
    monkeypatch.setattr("app.api.admin.staging._dispatch", lambda *a: sent.append(a))
    module = _module_with_generated(db_session, [ArtifactType.report])
    report = next(a for a in module.artifacts if a.type is ArtifactType.report)
    report.status = ArtifactStatus.error
    report.notebooklm_studio_id = "nb-artifact-1"
    report.studio_request = {"focus_prompt": "p", "redo_note": None}
    db_session.flush()
    headers = _admin_headers(client, db_session)

    resp = client.post(f"/api/admin/artifacts/{report.id}/retry", headers=headers)
    assert resp.status_code == status.HTTP_202_ACCEPTED
    assert sent[-1][-1] is True  # resume
    db_session.expire_all()
    assert db_session.get(Artifact, report.id).notebooklm_studio_id == "nb-artifact-1"

    # a Redo always generates a new one
    orchestrator.run_artifact_generation(db_session, PROVIDER, report.id, resume=True)
    db_session.expire_all()
    resp = client.post(f"/api/admin/artifacts/{report.id}/redo", json={}, headers=headers)
    assert resp.status_code == status.HTTP_202_ACCEPTED
    assert sent[-1][-1] is False
