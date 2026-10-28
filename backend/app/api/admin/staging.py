"""Admin staging: redo / retry a single artifact (spec.md §3.3, §5.3)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, status
from pydantic import ValidationError

from app.api.admin import ADMIN_DEPENDENCIES
from app.api.deps import CurrentAdmin, DbDep
from app.errors import APIError, invalid_input
from app.models.artifact import Artifact
from app.models.enums import ArtifactStatus, ArtifactType
from app.pipeline.factory import get_content_provider
from app.pipeline.orchestrator import (
    UNSET,
    OutlineNotAwaitingReview,
    Unset,
    enqueue_artifact_regeneration,
    request_outline_action,
)
from app.pipeline.provider import ProviderError
from app.schemas.jobs import JobEnvelope, JobOut
from app.schemas.staging import OutlineFeedbackRequest, RedoRequest

router = APIRouter(prefix="/api/admin", tags=["admin-staging"], dependencies=ADMIN_DEPENDENCIES)


def _dispatch(
    artifact_id: str, job_id: str, redo_note: str | None, is_audio: bool, resume: bool = False
) -> None:
    from app.tasks.generation import generate_artifact_task

    generate_artifact_task.apply_async(
        kwargs={
            "artifact_id": artifact_id,
            "job_id": job_id,
            "redo_note": redo_note,
            "resume": resume,
        },
        queue="audio" if is_audio else "text",
    )


def _requeue(
    db: DbDep,
    admin: CurrentAdmin,
    background: BackgroundTasks,
    artifact_id: uuid.UUID,
    redo_note: str | None,
    options: dict[str, Any] | None = None,
    custom_prompt: str | None | Unset = UNSET,
) -> JobEnvelope:
    artifact = db.get(Artifact, artifact_id)
    if artifact is None:
        raise APIError(status.HTTP_404_NOT_FOUND, "not_found", "Artifact not found")

    try:
        job = enqueue_artifact_regeneration(
            db,
            artifact_id,
            redo_note=redo_note,
            requested_by=admin.id,
            options=options,
            custom_prompt=custom_prompt,
        )
    except ValidationError as exc:  # the admin's generation options
        raise invalid_input(exc) from None
    db.flush()
    background.add_task(
        _dispatch,
        str(artifact_id),
        str(job.id),
        redo_note,
        artifact.type is ArtifactType.audio_overview,
    )
    return JobEnvelope(job=JobOut.model_validate(job))


@router.post(
    "/artifacts/{artifact_id}/redo",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobEnvelope,
)
def redo_artifact(
    artifact_id: uuid.UUID,
    body: RedoRequest,
    db: DbDep,
    admin: CurrentAdmin,
    background: BackgroundTasks,
) -> JobEnvelope:
    note = (body.note or "").strip() or None
    custom_prompt = body.custom_prompt if "custom_prompt" in body.model_fields_set else UNSET
    return _requeue(db, admin, background, artifact_id, note, body.options, custom_prompt)


@router.post(
    "/artifacts/{artifact_id}/retry",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobEnvelope,
)
def retry_artifact(
    artifact_id: uuid.UUID,
    db: DbDep,
    admin: CurrentAdmin,
    background: BackgroundTasks,
) -> JobEnvelope:
    artifact = db.get(Artifact, artifact_id)
    if artifact is None:
        raise APIError(status.HTTP_404_NOT_FOUND, "not_found", "Artifact not found")
    if artifact.status is not ArtifactStatus.error:
        raise APIError(
            status.HTTP_409_CONFLICT,
            "not_retryable",
            f"Artifact is {artifact.status.value}, not error",
        )
    return _requeue(db, admin, background, artifact_id, None)


def _outline_action(
    db: DbDep,
    admin: CurrentAdmin,
    background: BackgroundTasks,
    artifact_id: uuid.UUID,
    feedback: str | None,
) -> JobEnvelope:
    try:
        job = request_outline_action(
            db,
            get_content_provider(),
            artifact_id,
            feedback=feedback,
            requested_by=admin.id,
        )
    except ValueError as exc:
        raise APIError(status.HTTP_404_NOT_FOUND, "not_found", "Artifact not found") from exc
    except OutlineNotAwaitingReview as exc:
        raise APIError(status.HTTP_409_CONFLICT, "no_outline_to_review", str(exc)) from exc
    except ProviderError as exc:
        raise APIError(status.HTTP_502_BAD_GATEWAY, "provider_error", str(exc)) from exc
    db.flush()
    background.add_task(_dispatch, str(artifact_id), str(job.id), None, False, True)
    return JobEnvelope(job=JobOut.model_validate(job))


@router.post(
    "/artifacts/{artifact_id}/outline/feedback",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobEnvelope,
)
def outline_feedback(
    artifact_id: uuid.UUID,
    body: OutlineFeedbackRequest,
    db: DbDep,
    admin: CurrentAdmin,
    background: BackgroundTasks,
) -> JobEnvelope:
    """NotebookLM revises the draft slide outline from this feedback."""
    return _outline_action(db, admin, background, artifact_id, body.feedback.strip())


@router.post(
    "/artifacts/{artifact_id}/outline/proceed",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobEnvelope,
)
def outline_proceed(
    artifact_id: uuid.UUID,
    db: DbDep,
    admin: CurrentAdmin,
    background: BackgroundTasks,
) -> JobEnvelope:
    """NotebookLM builds the slide deck from the draft outline."""
    return _outline_action(db, admin, background, artifact_id, None)
