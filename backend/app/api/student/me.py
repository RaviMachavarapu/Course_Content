"""Student "Me" dashboards (spec.md §3.16) — Progress, My Listening, Achievements."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentStudent, DbDep
from app.api.student.courses import _published_artifacts
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

router = APIRouter(prefix="/api/student/me", tags=["student-me"])

_QUIZ_ACE_THRESHOLD = 80.0


@router.get("/progress", response_model=MyProgressResponse)
def my_progress(db: DbDep, student: CurrentStudent) -> MyProgressResponse:
    rows = db.execute(
        select(CourseProgress, Course)
        .join(Course, Course.id == CourseProgress.course_id)
        .where(CourseProgress.user_id == student.id)
        .order_by(CourseProgress.updated_at.desc())
    ).all()

    started_module_ids = set(
        db.scalars(select(ArtifactProgress.module_id).where(ArtifactProgress.user_id == student.id))
    )

    out: list[MyProgressCourse] = []
    for progress, course in rows:
        modules = db.scalars(
            select(Module)
            .where(Module.course_id == course.id)
            .options(selectinload(Module.artifacts))
        ).all()
        live_modules = [m for m in modules if _published_artifacts(m)]
        started = sum(1 for m in live_modules if m.id in started_module_ids)
        out.append(
            MyProgressCourse(
                id=course.id,
                slug=course.slug,
                title=course.title,
                percent_complete=int(progress.percent_complete),
                modules_started=started,
                modules_total=len(live_modules),
            )
        )
    return MyProgressResponse(courses=out)


@router.get("/listening", response_model=MyListeningResponse)
def my_listening(db: DbDep, student: CurrentStudent) -> MyListeningResponse:
    audio_artifacts = db.scalars(
        select(Artifact)
        .where(
            Artifact.type == ArtifactType.audio_overview,
            Artifact.published_version_id.is_not(None),
        )
        .options(
            selectinload(Artifact.versions),
            selectinload(Artifact.module).selectinload(Module.course),
        )
    ).all()

    progress_by_artifact = {
        p.artifact_id: p
        for p in db.scalars(select(ArtifactProgress).where(ArtifactProgress.user_id == student.id))
    }

    rows: list[ListeningRow] = []
    for artifact in audio_artifacts:
        prog = progress_by_artifact.get(artifact.id)
        if prog is None:
            continue  # only rows the student has actually opened
        version = next(
            (v for v in artifact.versions if v.id == artifact.published_version_id), None
        )
        duration = int((version.content_json or {}).get("duration_seconds", 0)) if version else 0
        position = prog.audio_position_seconds or 0
        module = artifact.module
        ordered = sorted(module.course.modules, key=lambda m: m.order_index)
        live_ids = [
            m.id for m in ordered if any(a.published_version_id is not None for a in m.artifacts)
        ]
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


@router.get("/achievements", response_model=AchievementsResponse)
def my_achievements(db: DbDep, student: CurrentStudent) -> AchievementsResponse:
    course_complete_at = db.scalar(
        select(CourseProgress.updated_at)
        .where(CourseProgress.user_id == student.id, CourseProgress.percent_complete >= 100)
        .order_by(CourseProgress.updated_at.asc())
        .limit(1)
    )
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
