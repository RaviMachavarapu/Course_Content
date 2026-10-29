"""Spec §3.3 / BR5 regression (review 2026-10-28, Critical): a published version
stays live for students — the artifact, its media and its quiz — whatever a
redo, re-run, new module or stuck job does to the artifact/module/course
workflow status. Draft-only content still 404s."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

import app.api.student.quiz as quiz_api
from app.models.artifact import Artifact
from app.models.course import Course
from app.models.enums import (
    ArtifactStatus,
    ArtifactType,
    CourseStatus,
    ModuleSourceType,
)
from app.models.media_file import MediaFile
from app.models.module import Module
from app.models.quiz_attempt import QuizAttempt
from app.models.quiz_question_set import QuizQuestionSet
from app.pipeline import orchestrator
from app.pipeline.fixture import FixtureProvider
from app.services.publish import publish_module

PROVIDER = FixtureProvider()
TYPES = [ArtifactType.quiz, ArtifactType.report, ArtifactType.audio_overview]


class _KeepOrder:
    def shuffle(self, x: list[Any]) -> None:
        return None


@pytest.fixture(autouse=True)
def _quiz_stubs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(quiz_api, "_rng", _KeepOrder())
    monkeypatch.setattr("app.api.student.quiz.enqueue_prepare", lambda *a, **k: None)


def _module(db: Session, course: Course, index: int) -> Module:
    module = Module(
        course=course,
        order_index=index,
        title=f"M{index}",
        source_url="https://youtu.be/x",
        source_type=ModuleSourceType.youtube,
    )
    db.add(module)
    db.flush()
    return module


def _published_course(db: Session) -> tuple[Course, Module, dict[ArtifactType, Artifact]]:
    course = Course(title="Vis", slug=f"vis-{uuid.uuid4()}")
    module = _module(db, course, 0)
    jobs = orchestrator.start_module_generation(db, PROVIDER, module.id, TYPES)
    for job in jobs:
        orchestrator.run_artifact_generation(db, PROVIDER, job.artifact_id, job_id=job.job_id)
    db.expire_all()
    module = db.get(Module, module.id)
    assert module is not None
    publish_module(db, module)
    db.flush()
    by_type = {a.type: a for a in module.artifacts if a.type in TYPES}
    assert module.course.status is CourseStatus.published
    return module.course, module, by_type


def _student(client: TestClient) -> None:
    client.cookies.clear()
    resp = client.post(
        "/api/student/auth/register",
        json={
            "email": f"v-{uuid.uuid4()}@example.com",
            "password": "vis-pw-123456",
            "display_name": "V",
        },
    )
    assert resp.status_code in (200, 201), resp.text


def _media_paths(client: TestClient, artifact_id: uuid.UUID) -> list[str]:
    body = client.get(f"/api/student/artifacts/{artifact_id}").json()
    return [m["url"].split("/api/media/", 1)[1] for m in body["media"]]


def _assert_live(
    client: TestClient, by_type: dict[ArtifactType, Artifact], audio_keys: list[str]
) -> None:
    for artifact in by_type.values():
        resp = client.get(f"/api/student/artifacts/{artifact.id}")
        assert resp.status_code == 200, (artifact.type, resp.text)
        assert resp.json()["revision"] == 1
        progress = client.put(f"/api/student/artifacts/{artifact.id}/progress", json={})
        assert progress.status_code == 200, progress.text
    assert audio_keys
    for key in audio_keys:
        assert client.get(f"/api/media/{key}").status_code == 200, key


def _answer_all(client: TestClient, db: Session, attempt_id: str) -> None:
    attempt = db.get(QuizAttempt, uuid.UUID(attempt_id))
    assert attempt is not None and attempt.question_set_id is not None
    qs = db.get(QuizQuestionSet, attempt.question_set_id)
    assert qs is not None
    for i, q in enumerate(qs.questions):
        right = q["correct_index"] if q.get("type", "mcq") == "mcq" else q["answer"]
        resp = client.post(
            f"/api/student/quiz-attempts/{attempt_id}/answers",
            json={"index": i, "response": right},
        )
        assert resp.status_code == 200, resp.text


def test_redo_of_published_artifacts_keeps_the_published_version_live(
    client: TestClient, db_session: Session
) -> None:
    course, module, by_type = _published_course(db_session)
    _student(client)
    audio_keys = _media_paths(client, by_type[ArtifactType.audio_overview].id)
    quiz_id = by_type[ArtifactType.quiz].id
    started = client.post(f"/api/student/artifacts/{quiz_id}/quiz-attempts")
    assert started.status_code == 201, started.text
    attempt_id = started.json()["attempt_id"]

    # Redo every published artifact: the module and course go to `processing`.
    for t in TYPES:
        orchestrator.enqueue_artifact_regeneration(db_session, by_type[t].id, redo_note="again")
    db_session.flush()
    db_session.expire_all()
    assert db_session.get(Course, course.id).status is CourseStatus.processing  # type: ignore[union-attr]

    _assert_live(client, by_type, audio_keys)
    # a student halfway through the quiz can still finish it
    _answer_all(client, db_session, attempt_id)
    done = client.post(f"/api/student/quiz-attempts/{attempt_id}/complete")
    assert done.status_code == 200, done.text

    # The redo finishes: a new `ready` version, course `pending_review`.
    for t in TYPES:
        orchestrator.run_artifact_generation(db_session, PROVIDER, by_type[t].id, redo_note="x")
    db_session.expire_all()
    assert db_session.get(Course, course.id).status is CourseStatus.pending_review  # type: ignore[union-attr]
    audio = db_session.get(Artifact, by_type[ArtifactType.audio_overview].id)
    assert audio is not None and audio.status is ArtifactStatus.ready
    assert audio.current_version_id != audio.published_version_id

    _assert_live(client, by_type, audio_keys)  # still revision 1 and its media
    again = client.post(f"/api/student/artifacts/{quiz_id}/quiz-attempts")
    assert again.status_code in (201, 202), again.text

    # the new (draft) version's media stays hidden
    draft_keys = list(
        db_session.scalars(
            select(MediaFile.storage_key).where(
                MediaFile.artifact_version_id == audio.current_version_id
            )
        )
    )
    assert draft_keys
    for key in draft_keys:
        assert client.get(f"/api/media/{key}").status_code == 404


def test_failed_redo_keeps_the_published_media_live(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, by_type = _published_course(db_session)
    _student(client)
    audio_keys = _media_paths(client, by_type[ArtifactType.audio_overview].id)
    audio_id = by_type[ArtifactType.audio_overview].id
    orchestrator.enqueue_artifact_regeneration(db_session, audio_id, redo_note="again")

    def boom(*a: Any, **k: Any) -> None:
        raise RuntimeError("studio down")

    monkeypatch.setattr(orchestrator, "_generate", boom)
    with pytest.raises(RuntimeError):
        orchestrator.run_artifact_generation(db_session, PROVIDER, audio_id, redo_note="again")
    db_session.expire_all()
    assert db_session.get(Artifact, audio_id).status is ArtifactStatus.error  # type: ignore[union-attr]

    _assert_live(client, by_type, audio_keys)


def test_new_module_generating_keeps_the_live_course_visible(
    client: TestClient, db_session: Session
) -> None:
    course, _, by_type = _published_course(db_session)
    _student(client)
    audio_keys = _media_paths(client, by_type[ArtifactType.audio_overview].id)
    m2 = _module(db_session, course, 1)
    orchestrator.start_module_generation(db_session, PROVIDER, m2.id, [ArtifactType.report])
    db_session.flush()
    db_session.expire_all()
    assert db_session.get(Course, course.id).status is CourseStatus.processing  # type: ignore[union-attr]

    _assert_live(client, by_type, audio_keys)
    ws = client.get(f"/api/student/courses/{course.slug}").json()
    assert len(ws["modules"]) == 1  # the generating module isn't shown


def test_never_published_artifact_still_404s(client: TestClient, db_session: Session) -> None:
    course = Course(title="Draft", slug=f"draft-{uuid.uuid4()}")
    module = _module(db_session, course, 0)
    (job,) = orchestrator.start_module_generation(
        db_session, PROVIDER, module.id, [ArtifactType.audio_overview]
    )
    orchestrator.run_artifact_generation(db_session, PROVIDER, job.artifact_id, job_id=job.job_id)
    db_session.expire_all()
    artifact = db_session.get(Artifact, job.artifact_id)
    assert artifact is not None and artifact.status is ArtifactStatus.ready
    keys = list(
        db_session.scalars(
            select(MediaFile.storage_key).where(
                MediaFile.artifact_version_id == artifact.current_version_id
            )
        )
    )
    _student(client)
    assert client.get(f"/api/student/artifacts/{artifact.id}").status_code == 404
    assert keys
    for key in keys:
        assert client.get(f"/api/media/{key}").status_code == 404
    assert client.get(f"/api/student/courses/{course.slug}").status_code == 404
