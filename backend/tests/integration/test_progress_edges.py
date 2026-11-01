"""Review 2026-10-29 (review-backend B, scenarios 20, 22, 23, 24): the Course
Complete stamp at its edges — concurrent last completions, concurrent reads of
the achievements, a course with no live artifacts, and 199 of 200."""

from __future__ import annotations

import datetime as dt
import threading
import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.api.student.me import _course_complete_at
from app.models.artifact import Artifact
from app.models.artifact_version import ArtifactVersion
from app.models.course import Course
from app.models.enums import ArtifactStatus, ArtifactType, ModuleSourceType
from app.models.module import Module
from app.models.progress import ArtifactProgress, CourseProgress
from app.models.user import User, UserRole
from app.services.progress import course_percent, record_artifact_progress

TYPES = list(ArtifactType)


def _course_with_live_artifacts(db: Session, n: int, *, live: bool = True) -> Course:
    """`n` artifacts (published unless `live` is False), as many modules as
    the one-artifact-per-type rule needs."""
    course = Course(title="Edge", slug=f"edge-{uuid.uuid4()}")
    db.add(course)
    for i in range(n):
        if i % len(TYPES) == 0:
            module = Module(
                course=course,
                order_index=i // len(TYPES),
                title=f"M{i}",
                source_url="https://youtu.be/x",
                source_type=ModuleSourceType.youtube,
            )
            db.add(module)
        artifact = Artifact(type=TYPES[i % len(TYPES)], status=ArtifactStatus.ready)
        module.artifacts.append(artifact)
        db.flush()
        if live:
            version = ArtifactVersion(revision=1, focus_prompt_used="")
            artifact.versions.append(version)
            db.flush()
            artifact.published_version_id = version.id
            artifact.status = ArtifactStatus.published
    db.flush()
    return course


def _student(db: Session) -> User:
    user = User(
        email=f"edge-{uuid.uuid4()}@example.com",
        display_name="E",
        password_hash="x",
        role=UserRole.student,
    )
    db.add(user)
    db.flush()
    return user


def _artifacts(db: Session, course: Course) -> list[Artifact]:
    return list(
        db.scalars(
            select(Artifact)
            .join(Module, Module.id == Artifact.module_id)
            .where(Module.course_id == course.id)
            .order_by(Module.order_index, Artifact.id)
        )
    )


def _stamp(db: Session, user: User, course: Course) -> dt.datetime | None:
    return db.scalar(
        select(CourseProgress.completed_at).where(
            CourseProgress.user_id == user.id, CourseProgress.course_id == course.id
        )
    )


def test_199_of_200_is_not_complete(db_session: Session) -> None:
    """Scenario 24: 99.5 % rounds to 100, but the badge needs every one."""
    course = _course_with_live_artifacts(db_session, 200)
    user = _student(db_session)
    artifacts = _artifacts(db_session, course)
    for artifact in artifacts[:199]:
        record_artifact_progress(db_session, user_id=user.id, artifact=artifact, completed=True)
    assert course_percent(db_session, user_id=user.id, course_id=course.id) == 100
    assert _stamp(db_session, user, course) is None
    assert _course_complete_at(db_session, user.id) is None

    record_artifact_progress(db_session, user_id=user.id, artifact=artifacts[199], completed=True)
    assert _stamp(db_session, user, course) is not None


def test_a_course_without_live_artifacts_is_never_complete(db_session: Session) -> None:
    """Scenario 23: no vacuous truth, on the write path or the lazy one."""
    course = _course_with_live_artifacts(db_session, 2, live=False)
    user = _student(db_session)
    for artifact in _artifacts(db_session, course):
        record_artifact_progress(db_session, user_id=user.id, artifact=artifact, completed=True)
    assert _stamp(db_session, user, course) is None
    assert _course_complete_at(db_session, user.id) is None
    assert _stamp(db_session, user, course) is None


# -- real connections (committed rows, cleaned up afterwards) ------------------


@pytest.fixture
def committed_course(
    db_engine: Engine,
) -> Iterator[tuple[sessionmaker[Session], uuid.UUID, uuid.UUID]]:
    factory = sessionmaker(bind=db_engine, expire_on_commit=False)
    with factory() as s:
        course = _course_with_live_artifacts(s, 2)
        user = _student(s)
        s.commit()
        ids = (course.id, user.id)
    try:
        yield factory, *ids
    finally:
        with factory() as s:
            s.execute(text("DELETE FROM course WHERE id = :id"), {"id": ids[0]})
            s.execute(text('DELETE FROM "user" WHERE id = :id'), {"id": ids[1]})
            s.commit()


def _run_together(*jobs: object) -> list[BaseException]:
    errors: list[BaseException] = []
    barrier = threading.Barrier(len(jobs))

    def wrap(job: object) -> None:
        try:
            barrier.wait(timeout=5)
            job()  # type: ignore[operator]
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=wrap, args=(j,)) for j in jobs]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)
    return errors


def test_concurrent_last_completions_still_earn_the_badge(
    committed_course: tuple[sessionmaker[Session], uuid.UUID, uuid.UUID],
) -> None:
    """Scenario 20: two tabs complete the last two artifacts at once. Neither
    write may see the other (READ COMMITTED); the achievements read stamps
    the badge with the later completion, and the live percentage is 100."""
    factory, course_id, user_id = committed_course
    with factory() as s:
        artifact_ids = [
            a.id
            for a in s.scalars(
                select(Artifact)
                .join(Module, Module.id == Artifact.module_id)
                .where(Module.course_id == course_id)
            )
        ]

    def complete(artifact_id: uuid.UUID) -> None:
        with factory() as s:
            artifact = s.get(Artifact, artifact_id)
            assert artifact is not None
            record_artifact_progress(s, user_id=user_id, artifact=artifact, completed=True)
            s.commit()

    errors = _run_together(*(lambda a=a: complete(a) for a in artifact_ids))
    assert not errors, errors

    with factory() as s:
        latest = max(
            s.scalars(
                select(ArtifactProgress.completed_at).where(
                    ArtifactProgress.user_id == user_id,
                    ArtifactProgress.completed_at.is_not(None),
                )
            ).all(),
            key=lambda at: at or dt.datetime.min,
        )
        assert course_percent(s, user_id=user_id, course_id=course_id) == 100
        shown = _course_complete_at(s, user_id)
        s.commit()
    with factory() as s:
        stamp = s.scalar(
            select(CourseProgress.completed_at).where(CourseProgress.user_id == user_id)
        )
    # stamped by the write that saw both, or (when neither did) lazily with
    # the later completion: either way around the moment the last one landed
    assert shown is not None and stamp == shown and latest is not None
    assert abs((shown - latest).total_seconds()) < 5


def test_concurrent_achievement_reads_stamp_once_and_keep_updated_at(
    committed_course: tuple[sessionmaker[Session], uuid.UUID, uuid.UUID],
) -> None:
    """Scenario 22: the badge was earned without a write (stamp missing);
    two achievement reads at once stamp it once and leave `updated_at`,
    which orders My Progress, alone."""
    factory, course_id, user_id = committed_course
    with factory() as s:
        for artifact in s.scalars(
            select(Artifact)
            .join(Module, Module.id == Artifact.module_id)
            .where(Module.course_id == course_id)
        ):
            record_artifact_progress(s, user_id=user_id, artifact=artifact, completed=True)
        s.execute(
            text("UPDATE course_progress SET completed_at = NULL WHERE user_id = :u"),
            {"u": user_id},
        )
        s.commit()
        updated_before = s.scalar(
            select(CourseProgress.updated_at).where(CourseProgress.user_id == user_id)
        )

    seen: list[dt.datetime | None] = []

    def read() -> None:
        with factory() as s:
            seen.append(_course_complete_at(s, user_id))
            s.commit()

    errors = _run_together(read, read)
    assert not errors, errors

    with factory() as s:
        row = s.execute(
            select(CourseProgress.completed_at, CourseProgress.updated_at).where(
                CourseProgress.user_id == user_id
            )
        ).one()
        latest = max(
            s.scalars(
                select(ArtifactProgress.completed_at).where(
                    ArtifactProgress.user_id == user_id,
                    ArtifactProgress.completed_at.is_not(None),
                )
            ).all(),
            key=lambda at: at or dt.datetime.min,
        )
    assert seen == [latest, latest]
    assert row.completed_at == latest
    assert row.updated_at == updated_before
