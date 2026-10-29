"""Publishing (BR2-BR5).

An artifact publishes only from `ready`: `published_version_id` is set to the
current version and its status becomes `published`. Everything else is skipped
and reported. Module/course derived status is recomputed afterwards.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models.artifact import Artifact
from app.models.course import Course
from app.models.enums import ArtifactStatus, ArtifactType, CourseStatus
from app.models.module import Module
from app.models.progress import ArtifactProgress
from app.services.derived_status import (
    recompute_course_status,
    recompute_module_status,
    recompute_status,
)

_SKIP_REASON = {
    ArtifactStatus.pending: "not generated yet",
    ArtifactStatus.processing: "still generating",
    ArtifactStatus.error: "generation failed",
    ArtifactStatus.published: "already published",
}


def _reset_flashcard_completion(session: Session, artifact: Artifact) -> None:
    """A newly published deck starts fresh: ratings are per version (so they
    reset by themselves) and completion is cleared (owner decision 2026-10-28)."""
    session.execute(
        update(ArtifactProgress)
        .where(ArtifactProgress.artifact_id == artifact.id)
        .values(completed_at=None)
        .execution_options(synchronize_session="fetch")
    )


def _publish_artifacts(
    session: Session, artifacts: list[Artifact]
) -> tuple[list[Artifact], list[Artifact]]:
    published: list[Artifact] = []
    skipped: list[Artifact] = []
    for artifact in artifacts:
        if artifact.status is ArtifactStatus.ready and artifact.current_version_id is not None:
            previous = artifact.published_version_id
            if (
                artifact.type is ArtifactType.flashcards
                and previous is not None
                and previous != artifact.current_version_id
            ):
                _reset_flashcard_completion(session, artifact)
            artifact.published_version_id = artifact.current_version_id
            artifact.status = ArtifactStatus.published
            published.append(artifact)
        else:
            skipped.append(artifact)
    return published, skipped


def _recompute(session: Session, module: Module) -> None:
    recompute_status(session, module)
    _stamp_course_published(module.course)
    session.flush()


def _stamp_course_published(course: Course) -> None:
    live = {CourseStatus.published, CourseStatus.partially_published}
    if course.status in live and course.published_at is None:
        course.published_at = dt.datetime.now(tz=dt.UTC)


def publish_module(session: Session, module: Module) -> tuple[list[Artifact], list[Artifact]]:
    published, skipped = _publish_artifacts(session, list(module.artifacts))
    _recompute(session, module)
    return published, skipped


def publish_course(session: Session, course: Course) -> tuple[list[Artifact], list[Artifact]]:
    """BR4 — publish every `ready` artifact across all the course's modules."""
    published: list[Artifact] = []
    skipped: list[Artifact] = []
    for module in course.modules:
        p, s = _publish_artifacts(session, list(module.artifacts))
        published.extend(p)
        skipped.extend(s)
        recompute_module_status(session, module)
    recompute_course_status(session, course)
    _stamp_course_published(course)
    session.flush()
    return published, skipped
