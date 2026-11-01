"""Student "Me" dashboards (spec.md §3.16) — Progress, My Listening, Achievements."""

from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload

from app.api.deps import CurrentStudent, DbDep, current_student
from app.api.student.courses import published_audio_seconds
from app.auth.csrf import csrf_protect
from app.models.artifact import Artifact
from app.models.course import Course
from app.models.enums import ArtifactType
from app.models.module import Module
from app.models.progress import ArtifactProgress, CourseProgress
from app.models.quiz_attempt import QuizAttempt
from app.schemas.me import (
    Achievement,
    AchievementsResponse,
    ListeningRow,
    MyListeningResponse,
    MyProgressCourse,
    MyProgressResponse,
)
from app.services.progress import course_percent
from app.services.visibility import is_live, live_artifacts, live_clause

router = APIRouter(
    prefix="/api/student/me",
    tags=["student-me"],
    # a student session (401 first), then CSRF on every state-changing request
    dependencies=[Depends(current_student), Depends(csrf_protect)],
)

_QUIZ_ACE_THRESHOLD = 80.0


@router.get("/progress", response_model=MyProgressResponse)
def my_progress(db: DbDep, student: CurrentStudent) -> MyProgressResponse:
    courses = db.scalars(
        select(Course)
        .join(CourseProgress, CourseProgress.course_id == Course.id)
        .where(CourseProgress.user_id == student.id)
        .order_by(CourseProgress.updated_at.desc())
    ).all()

    started_module_ids = set(
        db.scalars(select(ArtifactProgress.module_id).where(ArtifactProgress.user_id == student.id))
    )

    out: list[MyProgressCourse] = []
    for course in courses:
        modules = db.scalars(
            select(Module)
            .where(Module.course_id == course.id)
            .options(selectinload(Module.artifacts))
        ).all()
        live_modules = [m for m in modules if live_artifacts(m)]
        started = sum(1 for m in live_modules if m.id in started_module_ids)
        out.append(
            MyProgressCourse(
                id=course.id,
                slug=course.slug,
                title=course.title,
                # live, as the catalog does (the cached column goes stale when
                # a module is published or a deck republished)
                percent_complete=course_percent(db, user_id=student.id, course_id=course.id),
                modules_started=started,
                modules_total=len(live_modules),
            )
        )
    return MyProgressResponse(courses=out)


@router.get("/listening", response_model=MyListeningResponse)
def my_listening(db: DbDep, student: CurrentStudent) -> MyListeningResponse:
    # only the audio artifacts this student has opened, with their course's
    # module tree loaded up front (no per-row lazy loads)
    opened = db.execute(
        select(Artifact, ArtifactProgress)
        .join(
            ArtifactProgress,
            (ArtifactProgress.artifact_id == Artifact.id)
            & (ArtifactProgress.user_id == student.id),
        )
        .where(Artifact.type == ArtifactType.audio_overview, live_clause())
        .options(
            selectinload(Artifact.module)
            .selectinload(Module.course)
            .selectinload(Course.modules)
            .selectinload(Module.artifacts)
        )
    ).all()
    durations = published_audio_seconds(db, [artifact for artifact, _ in opened])

    rows: list[ListeningRow] = []
    for artifact, prog in opened:
        duration = durations.get(artifact.id, 0)
        position = prog.audio_position_seconds or 0
        module = artifact.module
        ordered = sorted(module.course.modules, key=lambda m: m.order_index)
        live_ids = [m.id for m in ordered if any(is_live(a) for a in m.artifacts)]
        module_index = live_ids.index(module.id) if module.id in live_ids else 0

        rows.append(
            ListeningRow(
                artifact_id=artifact.id,
                course_slug=module.course.slug,
                course_title=module.course.title,
                module_index=module_index,
                module_title=module.title,
                duration_seconds=duration,
                audio_position_seconds=position,
                percent_listened=(min(100, round(100 * position / duration)) if duration else 0),
                completed=prog.completed_at is not None,
            )
        )

    rows.sort(key=lambda r: r.course_title)
    return MyListeningResponse(rows=rows)


def _course_complete_at(db: Session, user_id: uuid.UUID) -> dt.datetime | None:
    """When the student first earned "Course Complete" in any course. Once
    earned it stays (owner decision 2026-10-29): the date is the stamp on
    `course_progress.completed_at`, set by the progress write that completed
    the course and never cleared. A course that became complete without a
    progress write (a module the student hadn't finished was removed) is
    stamped here the first time it is seen, with its latest completion."""
    stamped = db.execute(
        select(CourseProgress.id, CourseProgress.course_id, CourseProgress.completed_at).where(
            CourseProgress.user_id == user_id
        )
    ).all()
    earned = [at for _, _, at in stamped if at is not None]
    unstamped = {course_id: row_id for row_id, course_id, at in stamped if at is None}
    if unstamped:
        rows = db.execute(
            select(Module.course_id, Artifact.id)
            .join(Artifact, Artifact.module_id == Module.id)
            .where(live_clause(), Module.course_id.in_(unstamped))
        ).all()
        completed: dict[uuid.UUID, dt.datetime] = {
            artifact_id: at
            for artifact_id, at in db.execute(
                select(ArtifactProgress.artifact_id, ArtifactProgress.completed_at).where(
                    ArtifactProgress.user_id == user_id,
                    ArtifactProgress.completed_at.is_not(None),
                )
            )
            if at is not None
        }
        by_course: dict[uuid.UUID, list[uuid.UUID]] = {}
        for course_id, artifact_id in rows:
            by_course.setdefault(course_id, []).append(artifact_id)
        for course_id, artifact_ids in by_course.items():
            if all(a in completed for a in artifact_ids):
                at = max(completed[a] for a in artifact_ids)
                db.execute(
                    update(CourseProgress)
                    .where(
                        CourseProgress.id == unstamped[course_id],
                        CourseProgress.completed_at.is_(None),
                    )
                    # a read: keep updated_at (it orders My Progress)
                    .values(completed_at=at, updated_at=CourseProgress.updated_at)
                )
                earned.append(at)
    return min(earned, default=None)


@router.get("/achievements", response_model=AchievementsResponse)
def my_achievements(db: DbDep, student: CurrentStudent) -> AchievementsResponse:
    course_complete_at = _course_complete_at(db, student.id)
    quiz_ace_at = db.scalar(
        select(QuizAttempt.submitted_at)
        .where(
            QuizAttempt.user_id == student.id,
            QuizAttempt.score_percent >= _QUIZ_ACE_THRESHOLD,
        )
        .order_by(QuizAttempt.submitted_at.asc())
        .limit(1)
    )
    flashcard_streak_at = db.scalar(
        select(ArtifactProgress.completed_at)
        .join(Artifact, Artifact.id == ArtifactProgress.artifact_id)
        .where(
            ArtifactProgress.user_id == student.id,
            ArtifactProgress.completed_at.is_not(None),
            Artifact.type == ArtifactType.flashcards,
        )
        .order_by(ArtifactProgress.completed_at.asc())
        .limit(1)
    )

    badges = [
        Achievement(
            key="course_complete",
            label="Course Complete",
            description="Finish every published module in a course.",
            icon="military_tech",
            earned=course_complete_at is not None,
            earned_at=course_complete_at,
        ),
        Achievement(
            key="quiz_ace",
            label="Quiz Ace",
            description=f"Score {int(_QUIZ_ACE_THRESHOLD)}% or higher on any quiz.",
            icon="workspace_premium",
            earned=quiz_ace_at is not None,
            earned_at=quiz_ace_at,
        ),
        Achievement(
            key="flashcard_streak",
            label="Flashcard Streak",
            description="Review every card in a flashcard deck.",
            icon="local_fire_department",
            earned=flashcard_streak_at is not None,
            earned_at=flashcard_streak_at,
        ),
    ]
    return AchievementsResponse(
        earned=[b for b in badges if b.earned],
        locked=[b for b in badges if not b.earned],
    )
