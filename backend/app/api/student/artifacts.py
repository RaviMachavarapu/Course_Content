"""Student artifact read/progress API (spec.md §3.9+) — the published version only."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentStudent, DbDep
from app.errors import APIError
from app.models.artifact import Artifact
from app.models.course import Course
from app.models.enums import STUDENT_HIDDEN_MEDIA_KINDS, ArtifactType
from app.models.flashcard_rating import FlashcardRating
from app.models.module import Module
from app.models.progress import ArtifactProgress
from app.schemas.student import (
    ArtifactMediaOut,
    ArtifactProgressRequest,
    ArtifactProgressResponse,
    StudentArtifactOut,
)
from app.services.progress import record_artifact_progress
from app.services.visibility import is_live
from app.storage.service import get_storage

router = APIRouter(prefix="/api/student", tags=["student-artifacts"])


def _visible_artifact(db: DbDep, artifact_id: uuid.UUID) -> Artifact:
    """The artifact behind a published version, or a 404 (never a 403 — don't
    confirm an unpublished artifact exists). Course/module workflow status is
    deliberately ignored (app.services.visibility)."""
    artifact = db.scalar(
        select(Artifact)
        .where(Artifact.id == artifact_id)
        .options(
            selectinload(Artifact.versions),
            selectinload(Artifact.module)
            .selectinload(Module.course)
            .selectinload(Course.modules)
            .selectinload(Module.artifacts),
        )
    )
    if artifact is None or not is_live(artifact):
        raise APIError(status.HTTP_404_NOT_FOUND, "not_found", "Not available")
    return artifact


@router.get("/artifacts/{artifact_id}", response_model=StudentArtifactOut)
def get_artifact(artifact_id: uuid.UUID, db: DbDep, student: CurrentStudent) -> StudentArtifactOut:
    artifact = _visible_artifact(db, artifact_id)
    module = artifact.module
    version = next((v for v in artifact.versions if v.id == artifact.published_version_id), None)
    if version is None:
        raise APIError(status.HTTP_404_NOT_FOUND, "not_found", "Not available")

    ordered = sorted(module.course.modules, key=lambda m: m.order_index)
    live_ids = [m.id for m in ordered if any(is_live(a) for a in m.artifacts)]
    module_index = live_ids.index(module.id) if module.id in live_ids else 0

    storage = get_storage()
    media = [
        ArtifactMediaOut(
            kind=mf.kind.value,
            url=storage.url_for(mf.storage_key),
            page_index=mf.page_index,
        )
        for mf in sorted(
            version.media_files, key=lambda mf: (mf.page_index if mf.page_index is not None else -1)
        )
        # e.g. the quiz PDF with its answer key (students get the questions-only one)
        if mf.kind not in STUDENT_HIDDEN_MEDIA_KINDS
    ]

    prog = db.scalar(
        select(ArtifactProgress).where(
            ArtifactProgress.user_id == student.id,
            ArtifactProgress.artifact_id == artifact.id,
        )
    )

    content_json = version.content_json
    if content_json is not None and artifact.type is ArtifactType.quiz:
        # never reveal the answers before submit (spec §3.12)
        content_json = {
            **content_json,
            "questions": [
                {k: v for k, v in q.items() if k not in ("correct_index", "explanation")}
                for q in content_json.get("questions", [])
            ],
        }

    ratings: dict[int, str] = {}
    if artifact.type is ArtifactType.flashcards:
        ratings = {
            r.card_index: r.rating.value
            for r in db.scalars(
                select(FlashcardRating).where(
                    FlashcardRating.user_id == student.id,
                    FlashcardRating.artifact_id == artifact.id,
                )
            )
        }

    return StudentArtifactOut(
        id=artifact.id,
        type=artifact.type,
        module_id=module.id,
        module_index=module_index,
        course_slug=module.course.slug,
        revision=version.revision,
        content_json=content_json,
        content_html=version.content_html,
        media=media,
        completed=bool(prog and prog.completed_at is not None),
        slide_last_index=prog.slide_last_index if prog else None,
        audio_position_seconds=prog.audio_position_seconds if prog else None,
        flashcard_ratings=ratings,
    )


@router.put("/artifacts/{artifact_id}/progress", response_model=ArtifactProgressResponse)
def put_progress(
    artifact_id: uuid.UUID,
    body: ArtifactProgressRequest,
    db: DbDep,
    student: CurrentStudent,
) -> ArtifactProgressResponse:
    artifact = _visible_artifact(db, artifact_id)
    row, course_percent = record_artifact_progress(
        db,
        user_id=student.id,
        artifact=artifact,
        completed=body.completed,
        complete_module=body.complete_module,
        slide_last_index=body.slide_last_index,
        audio_position_seconds=body.audio_position_seconds,
    )
    return ArtifactProgressResponse(
        completed=row.completed_at is not None,
        slide_last_index=row.slide_last_index,
        audio_position_seconds=row.audio_position_seconds,
        course_percent_complete=course_percent,
    )
