"""Review 2026-10-28 data-model Minors: flashcard ratings/completion per
published version, live course percentage and course-complete badge,
concurrent first progress writes."""

from __future__ import annotations

import threading
import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.models.artifact import Artifact
from app.models.course import Course
from app.models.enums import ArtifactStatus, ArtifactType, ModuleSourceType
from app.models.flashcard_rating import FlashcardRating
from app.models.module import Module
from app.models.progress import ArtifactProgress, CourseProgress
from app.models.user import User, UserRole
from app.pipeline import orchestrator
from app.pipeline.fixture import FixtureProvider
from app.services.progress import record_artifact_progress
from app.services.publish import publish_module

PROVIDER = FixtureProvider()


def _module(db: Session, course: Course, index: int, types: list[ArtifactType]) -> Module:
    module = Module(
        course=course,
        order_index=index,
        title=f"M{index}",
        source_url="https://youtu.be/x",
        source_type=ModuleSourceType.youtube,
    )
    db.add(module)
    db.flush()
    for job in orchestrator.start_module_generation(db, PROVIDER, module.id, types):
        orchestrator.run_artifact_generation(db, PROVIDER, job.artifact_id, job_id=job.job_id)
    db.expire_all()
    module = db.get(Module, module.id)
    assert module is not None
    publish_module(db, module)
    db.flush()
    return module


def _student(client: TestClient) -> None:
    client.cookies.clear()
    r = client.post(
        "/api/student/auth/register",
        json={
            "email": f"r-{uuid.uuid4()}@example.com",
            "password": "review-pw-1234",
            "display_name": "R",
        },
    )
    assert r.status_code in (200, 201), r.text


def _artifact(module: Module, t: ArtifactType) -> Artifact:
    return next(a for a in module.artifacts if a.type is t)


# -- flashcard ratings/completion reset on a new published version -------------
def test_republished_deck_starts_unrated_and_incomplete(
    client: TestClient, db_session: Session
) -> None:
    course = Course(title="FC", slug=f"fc-{uuid.uuid4()}")
    module = _module(db_session, course, 0, [ArtifactType.flashcards])
    deck = _artifact(module, ArtifactType.flashcards)
    v1 = deck.published_version_id
    _student(client)

    r = client.put(f"/api/student/artifacts/{deck.id}/flashcard-ratings/0", json={"value": "hard"})
    assert r.json() == {"ratings": {"0": "hard"}}
    r = client.put(f"/api/student/artifacts/{deck.id}/flashcard-ratings/0", json={"value": "easy"})
    assert r.json() == {"ratings": {"0": "easy"}}
    done = client.put(f"/api/student/artifacts/{deck.id}/progress", json={"completed": True})
    assert done.json()["completed"] is True

    # redo + republish: a different deck
    orchestrator.run_artifact_generation(db_session, PROVIDER, deck.id, redo_note="new deck")
    db_session.expire_all()
    module = db_session.get(Module, module.id)
    assert module is not None
    publish_module(db_session, module)
    db_session.flush()
    db_session.expire_all()
    deck = db_session.get(Artifact, deck.id)
    assert deck is not None and deck.published_version_id != v1

    body = client.get(f"/api/student/artifacts/{deck.id}").json()
    assert body["revision"] == 2
    assert body["flashcard_ratings"] == {}
    assert body["completed"] is False
    # the v1 rating is kept against v1, not shown for v2
    rows = db_session.scalars(select(FlashcardRating).where(FlashcardRating.artifact_id == deck.id))
    assert [r.artifact_version_id for r in rows] == [v1]

    r = client.put(f"/api/student/artifacts/{deck.id}/flashcard-ratings/1", json={"value": "good"})
    assert r.json() == {"ratings": {"1": "good"}}


def test_republishing_other_types_keeps_completion(client: TestClient, db_session: Session) -> None:
    course = Course(title="RP", slug=f"rp-{uuid.uuid4()}")
    module = _module(db_session, course, 0, [ArtifactType.report])
    report = _artifact(module, ArtifactType.report)
    _student(client)
    client.put(f"/api/student/artifacts/{report.id}/progress", json={"completed": True})
    orchestrator.run_artifact_generation(db_session, PROVIDER, report.id, redo_note="again")
    db_session.expire_all()
    module = db_session.get(Module, module.id)
    assert module is not None
    publish_module(db_session, module)
    db_session.flush()
    assert client.get(f"/api/student/artifacts/{report.id}").json()["completed"] is True


# -- live percentage + badge -------------------------------------------------
def test_me_progress_and_badge_follow_newly_published_modules(
    client: TestClient, db_session: Session
) -> None:
    course = Course(title="Live %", slug=f"live-{uuid.uuid4()}")
    m1 = _module(db_session, course, 0, [ArtifactType.report])
    report = _artifact(m1, ArtifactType.report)
    _student(client)
    client.put(f"/api/student/artifacts/{report.id}/progress", json={"completed": True})

    def me_percent() -> int:
        rows = client.get("/api/student/me/progress").json()["courses"]
        return next(r["percent_complete"] for r in rows if r["slug"] == course.slug)

    def badge() -> dict[str, object] | None:
        earned = client.get("/api/student/me/achievements").json()["earned"]
        return next((b for b in earned if b["key"] == "course_complete"), None)

    assert me_percent() == 100
    first = badge()
    assert first is not None
    # a later progress write in the course doesn't move the earned date
    client.put(f"/api/student/artifacts/{report.id}/progress", json={"slide_last_index": 1})
    assert badge() == first

    _module(db_session, course, 1, [ArtifactType.report])
    catalog = client.get("/api/student/courses").json()["courses"]
    assert next(c for c in catalog if c["slug"] == course.slug)["percent_complete"] == 50
    assert me_percent() == 50  # without any new progress write
    # the badge stays once earned, with its original date (owner decision 2026-10-29)
    assert badge() == first
    # a progress write at 50% doesn't revoke it or move the date either
    client.put(f"/api/student/artifacts/{report.id}/progress", json={"slide_last_index": 2})
    assert me_percent() == 50
    assert badge() == first


def test_course_complete_badge_survives_a_republished_deck(
    client: TestClient, db_session: Session
) -> None:
    course = Course(title="Badge FC", slug=f"bfc-{uuid.uuid4()}")
    module = _module(db_session, course, 0, [ArtifactType.flashcards])
    deck = _artifact(module, ArtifactType.flashcards)
    _student(client)
    client.put(f"/api/student/artifacts/{deck.id}/progress", json={"completed": True})

    def badge() -> dict[str, object] | None:
        earned = client.get("/api/student/me/achievements").json()["earned"]
        return next((b for b in earned if b["key"] == "course_complete"), None)

    first = badge()
    assert first is not None and first["earned_at"] is not None

    orchestrator.run_artifact_generation(db_session, PROVIDER, deck.id, redo_note="new deck")
    db_session.expire_all()
    module = db_session.get(Module, module.id)
    assert module is not None
    publish_module(db_session, module)
    db_session.flush()
    assert client.get(f"/api/student/artifacts/{deck.id}").json()["completed"] is False
    assert badge() == first

    # completing the new deck later doesn't move the earned date
    client.put(f"/api/student/artifacts/{deck.id}/progress", json={"completed": True})
    assert badge() == first


def test_course_complete_stamped_by_the_completing_write(
    client: TestClient, db_session: Session
) -> None:
    course = Course(title="Stamp", slug=f"stamp-{uuid.uuid4()}")
    module = _module(db_session, course, 0, [ArtifactType.report, ArtifactType.quiz])
    report = _artifact(module, ArtifactType.report)
    quiz = _artifact(module, ArtifactType.quiz)
    _student(client)

    def stamp() -> object:
        db_session.expire_all()
        return db_session.scalar(
            select(CourseProgress.completed_at).where(CourseProgress.course_id == course.id)
        )

    client.put(f"/api/student/artifacts/{report.id}/progress", json={"completed": True})
    assert stamp() is None  # 1 of 2
    client.put(f"/api/student/artifacts/{quiz.id}/progress", json={"completed": True})
    first = stamp()
    assert first is not None
    _module(db_session, course, 1, [ArtifactType.report])
    client.put(f"/api/student/artifacts/{report.id}/progress", json={"slide_last_index": 3})
    assert stamp() == first


def test_course_complete_without_a_write_is_stamped_once_seen(
    client: TestClient, db_session: Session
) -> None:
    """A course that became complete because an unfinished module was removed
    gets its badge on the next look, and keeps it after more modules appear."""
    course = Course(title="Removed", slug=f"rm-{uuid.uuid4()}")
    m1 = _module(db_session, course, 0, [ArtifactType.report])
    m2 = _module(db_session, course, 1, [ArtifactType.report])
    report = _artifact(m1, ArtifactType.report)
    _student(client)
    client.put(f"/api/student/artifacts/{report.id}/progress", json={"completed": True})

    def badge() -> dict[str, object] | None:
        earned = client.get("/api/student/me/achievements").json()["earned"]
        return next((b for b in earned if b["key"] == "course_complete"), None)

    assert badge() is None
    db_session.delete(m2)
    db_session.flush()
    first = badge()
    assert first is not None
    db_session.expire_all()
    row = db_session.scalars(
        select(CourseProgress).where(CourseProgress.course_id == course.id)
    ).one()
    done_at = db_session.scalar(
        select(ArtifactProgress.completed_at).where(ArtifactProgress.artifact_id == report.id)
    )
    assert row.completed_at == done_at

    _module(db_session, course, 2, [ArtifactType.report])
    assert badge() == first


# -- concurrent first writes (real connections, committed and cleaned up) -----
@pytest.fixture
def committed_artifacts(
    db_engine: Engine,
) -> Iterator[tuple[sessionmaker[Session], dict[str, uuid.UUID]]]:
    factory = sessionmaker(bind=db_engine, expire_on_commit=False)
    course = Course(title="Race", slug=f"race-{uuid.uuid4()}")
    module = Module(
        course=course,
        order_index=0,
        title="M",
        source_url="https://youtu.be/x",
        source_type=ModuleSourceType.youtube,
    )
    for t in (ArtifactType.report, ArtifactType.quiz):
        module.artifacts.append(Artifact(type=t, status=ArtifactStatus.published))
    user = User(
        email=f"race-{uuid.uuid4()}@example.com",
        display_name="R",
        password_hash="x",
        role=UserRole.student,
    )
    with factory() as s:
        s.add_all([course, user])
        s.commit()
        ids = {
            "course": course.id,
            "user": user.id,
            "report": module.artifacts[0].id,
            "quiz": module.artifacts[1].id,
        }
    try:
        yield factory, ids
    finally:
        with factory() as s:
            s.execute(text("DELETE FROM course WHERE id = :id"), {"id": ids["course"]})
            s.execute(text('DELETE FROM "user" WHERE id = :id'), {"id": ids["user"]})
            s.commit()


def test_concurrent_first_progress_writes_dont_collide(
    committed_artifacts: tuple[sessionmaker[Session], dict[str, uuid.UUID]],
) -> None:
    factory, ids = committed_artifacts
    errors: list[BaseException] = []
    barrier = threading.Barrier(4)

    def write(artifact_key: str, completed: bool) -> None:
        try:
            with factory() as s:
                artifact = s.get(Artifact, ids[artifact_key])
                assert artifact is not None
                barrier.wait(timeout=5)
                record_artifact_progress(
                    s, user_id=ids["user"], artifact=artifact, completed=completed
                )
                s.commit()
        except BaseException as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=write, args=(k, c))
        for k, c in (("report", False), ("report", True), ("quiz", False), ("quiz", True))
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)
    assert not errors, errors

    with factory() as s:
        rows = s.scalars(select(ArtifactProgress).where(ArtifactProgress.user_id == ids["user"]))
        assert sorted(r.completed_at is not None for r in rows) == [True, True]
        cp = s.scalars(select(CourseProgress).where(CourseProgress.user_id == ids["user"])).all()
        assert len(cp) == 1
