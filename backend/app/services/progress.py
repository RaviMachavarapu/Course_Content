"""Student progress writes (T033+): upsert per-artifact progress and roll the
course percentage up from it. Shared by every artifact viewer."""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.artifact import Artifact
from app.models.flashcard_rating import FlashcardRating
from app.models.module import Module
from app.models.progress import ArtifactProgress, CourseProgress
from app.services.visibility import is_live, live_clause


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _upsert_row(session: Session, user_id: uuid.UUID, artifact: Artifact) -> ArtifactProgress:
    """The caller's row for `artifact`, created if missing, row-locked. INSERT …
    ON CONFLICT DO NOTHING, so two concurrent first writes can't race into a
    unique violation (500)."""
    session.execute(
        insert(ArtifactProgress)
        .values(
            id=uuid.uuid4(),
            user_id=user_id,
            artifact_id=artifact.id,
            module_id=artifact.module_id,
        )
        .on_conflict_do_nothing(constraint="uq_artifact_progress_user_artifact")
    )
    return session.scalars(
        select(ArtifactProgress)
        .where(
            ArtifactProgress.user_id == user_id,
            ArtifactProgress.artifact_id == artifact.id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one()


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


def course_percent(session: Session, *, user_id: uuid.UUID, course_id: uuid.UUID) -> int:
    """BR7, computed live: completed ÷ published artifacts of the course."""
    done, total = _course_counts(session, user_id=user_id, course_id=course_id)
    return round(100 * done / total) if total else 0


def _course_counts(
    session: Session, *, user_id: uuid.UUID, course_id: uuid.UUID
) -> tuple[int, int]:
    """(completed, published) artifacts of the course for this student."""
    published_ids = set(
        session.scalars(
            select(Artifact.id)
            .join(Module, Module.id == Artifact.module_id)
            .where(Module.course_id == course_id, live_clause())
        )
    )
    total = len(published_ids)
    if not total:
        return 0, 0
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
    return done, total


def _recompute_course_progress(
    session: Session,
    *,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    module_id: uuid.UUID,
) -> int:
    done, total = _course_counts(session, user_id=user_id, course_id=course_id)
    percent = round(100 * done / total) if total else 0
    # exact, not the rounded percentage (199 of 200 rounds to 100)
    complete_now = _now() if total and done == total else None
    # upsert in one statement (two first writes in a course can't collide);
    # the badge stamp is kept once set (coalesce), whatever the percentage does
    stmt = insert(CourseProgress).values(
        id=uuid.uuid4(),
        user_id=user_id,
        course_id=course_id,
        percent_complete=percent,
        last_module_id=module_id,
        completed_at=complete_now,
    )
    session.execute(
        stmt.on_conflict_do_update(
            constraint="uq_course_progress_user_course",
            set_={
                "percent_complete": percent,
                "last_module_id": module_id,
                "updated_at": func.now(),
                "completed_at": func.coalesce(
                    CourseProgress.completed_at, stmt.excluded.completed_at
                ),
            },
        )
    )
    return percent


def published_ratings(
    session: Session, user_id: uuid.UUID, version_id: uuid.UUID, card_count: int
) -> dict[int, str]:
    """The caller's flashcard ratings for one published version of a deck (a
    newly published deck starts unrated), limited to its cards."""
    rows = session.execute(
        select(FlashcardRating.card_index, FlashcardRating.rating).where(
            FlashcardRating.user_id == user_id,
            FlashcardRating.artifact_version_id == version_id,
            FlashcardRating.card_index < card_count,
        )
    )
    return {index: rating.value for index, rating in rows}
