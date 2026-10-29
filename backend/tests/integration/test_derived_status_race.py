"""Review 2026-10-28: two jobs of one module finishing together must not leave
the module `processing` (lost update in the derived-status recompute).

Uses two real connections (committed rows, cleaned up afterwards): the
per-test rolled-back transaction can't show cross-transaction behaviour."""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

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
from app.services.derived_status import recompute_status


@pytest.fixture
def committed_module(db_engine: Engine) -> Iterator[tuple[sessionmaker[Session], uuid.UUID]]:
    factory = sessionmaker(bind=db_engine, expire_on_commit=False)
    course = Course(title="Race", slug=f"race-{uuid.uuid4()}", status=CourseStatus.processing)
    module = Module(
        course=course,
        order_index=0,
        title="M",
        source_url="https://youtu.be/x",
        source_type=ModuleSourceType.youtube,
        status=ModuleStatus.processing,
    )
    for t in (ArtifactType.report, ArtifactType.quiz):
        module.artifacts.append(Artifact(type=t, status=ArtifactStatus.processing))
    with factory() as s:
        s.add(course)
        s.commit()
        module_id, course_id = module.id, course.id
    try:
        yield factory, module_id
    finally:
        with factory() as s:
            s.execute(text("DELETE FROM course WHERE id = :id"), {"id": course_id})
            s.commit()


def _finish(session: Session, module_id: uuid.UUID, artifact_type: ArtifactType) -> None:
    module = session.get(Module, module_id)
    assert module is not None
    artifact = next(a for a in module.artifacts if a.type is artifact_type)
    artifact.status = ArtifactStatus.ready
    session.flush()
    recompute_status(session, module)


def test_two_jobs_finishing_together_leave_the_module_pending_review(
    committed_module: tuple[sessionmaker[Session], uuid.UUID],
) -> None:
    factory, module_id = committed_module
    errors: list[BaseException] = []

    t1 = factory()
    _finish(t1, module_id, ArtifactType.report)  # holds the module lock, uncommitted

    def second() -> None:
        try:
            with factory() as t2:
                t2.execute(text("SET LOCAL lock_timeout = '10s'"))
                _finish(t2, module_id, ArtifactType.quiz)
                t2.commit()
        except BaseException as exc:  # surfaced below
            errors.append(exc)

    worker = threading.Thread(target=second)
    worker.start()
    time.sleep(0.5)  # let the second job read/wait while the first is uncommitted
    t1.commit()
    t1.close()
    worker.join(timeout=15)
    assert not worker.is_alive()
    assert not errors, errors

    with factory() as s:
        module = s.get(Module, module_id)
        assert module is not None
        assert module.status is ModuleStatus.pending_review
        assert module.course.status is CourseStatus.pending_review
