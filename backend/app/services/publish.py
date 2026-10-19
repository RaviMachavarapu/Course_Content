"""Publishing (BR2-BR5).

An artifact publishes only from `ready`: `published_version_id` is set to the
current version and its status becomes `published`. Everything else is skipped
and reported. Module/course derived status is recomputed afterwards.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.artifact import Artifact
from app.models.course import Course
from app.models.enums import ArtifactStatus, CourseStatus
from app.models.module import Module
from app.models.status import derive_course_status, derive_module_status

_SKIP_REASON = {
    ArtifactStatus.pending: "not generated yet",
    ArtifactStatus.processing: "still generating",
    ArtifactStatus.error: "generation failed",
    ArtifactStatus.published: "already published",
}


def _publish_artifacts(artifacts: list[Artifact]) -> tuple[list[Artifact], list[Artifact]]:
    published: list[Artifact] = []
    skipped: list[Artifact] = []
    for artifact in artifacts:
        if artifact.status is ArtifactStatus.ready and artifact.current_version_id is not None:
            artifact.published_version_id = artifact.current_version_id
            artifact.status = ArtifactStatus.published
            published.append(artifact)
        else:
            skipped.append(artifact)
    return published, skipped


def _recompute(session: Session, module: Module) -> None:
    session.flush()
    module.status = derive_module_status(
        list(session.scalars(select(Artifact.status).where(Artifact.module_id == module.id)))
    )
    session.flush()
    module.course.status = derive_course_status(
        list(session.scalars(select(Module.status).where(Module.course_id == module.course_id)))
    )
    _stamp_course_published(module.course)
    session.flush()


def _stamp_course_published(course: Course) -> None:
    live = {CourseStatus.published, CourseStatus.partially_published}
    if course.status in live and course.published_at is None:
        course.published_at = dt.datetime.now(tz=dt.UTC)


def publish_module(session: Session, module: Module) -> tuple[list[Artifact], list[Artifact]]:
    published, skipped = _publish_artifacts(list(module.artifacts))
    _recompute(session, module)
    return published, skipped


def publish_course(session: Session, course: Course) -> tuple[list[Artifact], list[Artifact]]:
    """BR4 — publish every `ready` artifact across all the course's modules."""
    published: list[Artifact] = []
    skipped: list[Artifact] = []
    for module in course.modules:
        p, s = _publish_artifacts(list(module.artifacts))
        published.extend(p)
        skipped.extend(s)
        session.flush()
        module.status = derive_module_status(
            list(session.scalars(select(Artifact.status).where(Artifact.module_id == module.id)))
        )
    session.flush()
    course.status = derive_course_status([m.status for m in course.modules])
    _stamp_course_published(course)
    session.flush()
    return published, skipped
