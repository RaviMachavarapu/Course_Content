"""Student progress writes (T033+): upsert per-artifact progress and roll the
course percentage up from it. Shared by every artifact viewer."""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.artifact import Artifact
from app.models.module import Module
from app.models.progress import ArtifactProgress, CourseProgress
from app.services.visibility import is_live, live_clause


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _upsert_row(session: Session, user_id: uuid.UUID, artifact: Artifact) -> ArtifactProgress:
    row = session.scalar(
        select(ArtifactProgress).where(
            ArtifactProgress.user_id == user_id,
            ArtifactProgress.artifact_id == artifact.id,
        )
    )
    if row is None:
        row = ArtifactProgress(
            user_id=user_id, artifact_id=artifact.id, module_id=artifact.module_id
        )
        session.add(row)
    return row


def record_artifact_progress(
    session: Session,
    *,
    user_id: uuid.UUID,
    artifact: Artifact,
    completed: bool | None = None,
    complete_module: bool = False,
    slide_last_index: int | None = None,
    audio_position_seconds: int | None = None,
) -> tuple[ArtifactProgress, int]:
    """Merge the given fields into the caller's `artifact_progress` row (creating
    it if needed), then recompute `course_progress.percent_complete`. Completion
    is sticky — once `completed_at` is set it is never cleared here.
    `complete_module` also marks every published sibling artifact complete
    (the "Complete Module" action on the report, spec §3.7).

    Returns `(artifact_progress, course_percent_complete)`.
    """
    row = _upsert_row(session, user_id, artifact)

    if row.viewed_at is None:
        row.viewed_at = _now()
    if slide_last_index is not None:
        row.slide_last_index = slide_last_index
    if audio_position_seconds is not None:
        row.audio_position_seconds = max(0, audio_position_seconds)
    if (completed or complete_module) and row.completed_at is None:
        row.completed_at = _now()

    if complete_module:
        for sibling in artifact.module.artifacts:
            if sibling.id == artifact.id or not is_live(sibling):
                continue
            srow = _upsert_row(session, user_id, sibling)
            if srow.viewed_at is None:
                srow.viewed_at = _now()
            if srow.completed_at is None:
                srow.completed_at = _now()
    session.flush()

    percent = _recompute_course_progress(
        session, user_id=user_id, course_id=artifact.module.course_id, module_id=artifact.module_id
    )
    return row, percent


def _recompute_course_progress(
    session: Session,
    *,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    module_id: uuid.UUID,
) -> int:
    published_ids = set(
        session.scalars(
            select(Artifact.id)
            .join(Module, Module.id == Artifact.module_id)
            .where(Module.course_id == course_id, live_clause())
        )
    )
    total = len(published_ids)
    done = 0
    if total:
        done = (
            session.scalar(
                select(func.count())
                .select_from(ArtifactProgress)
                .where(
                    ArtifactProgress.user_id == user_id,
                    ArtifactProgress.completed_at.is_not(None),
                    ArtifactProgress.artifact_id.in_(published_ids),
                )
            )
            or 0
        )

    percent = round(100 * done / total) if total else 0

    cp = session.scalar(
        select(CourseProgress).where(
            CourseProgress.user_id == user_id, CourseProgress.course_id == course_id
        )
    )
    if cp is None:
        cp = CourseProgress(user_id=user_id, course_id=course_id)
        session.add(cp)
    cp.percent_complete = percent
    cp.last_module_id = module_id
    session.flush()
    return percent
