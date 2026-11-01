"""Recompute the cached module/course status (BR3) without lost updates.

Two jobs of one module finishing together each read the other's artifact as
still `processing` under READ COMMITTED and write a stale module status. So
each recompute first row-locks the parent (module, then course) and only then
reads the children: recomputes of one module/course run one after another,
and the last writer sees every committed child.

Lock order is always artifact → module → course (callers have already written
their artifact rows), so two recomputes can't deadlock on each other.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.artifact import Artifact
from app.models.course import Course
from app.models.module import Module
from app.models.status import derive_course_status, derive_module_status


def _lock(session: Session, model: type[Module] | type[Course], row_id: uuid.UUID) -> None:
    session.execute(select(model.id).where(model.id == row_id).with_for_update())


def recompute_module_status(session: Session, module: Module) -> None:
    session.flush()
    _lock(session, Module, module.id)
    module.status = derive_module_status(
        list(session.scalars(select(Artifact.status).where(Artifact.module_id == module.id)))
    )
    session.flush()


def recompute_course_status(session: Session, course: Course) -> None:
    session.flush()
    _lock(session, Course, course.id)
    course.status = derive_course_status(
        list(session.scalars(select(Module.status).where(Module.course_id == course.id)))
    )
    session.flush()


def recompute_status(session: Session, module: Module) -> None:
    """The module's status, then its course's."""
    recompute_module_status(session, module)
    recompute_course_status(session, module.course)
