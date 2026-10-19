"""Admin staging: redo / retry a single artifact (spec.md §3.3, §5.3)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, status

from app.api.admin import ADMIN_DEPENDENCIES
from app.api.deps import CurrentAdmin, DbDep
from app.errors import APIError
from app.models.artifact import Artifact
from app.models.enums import ArtifactStatus, ArtifactType
from app.pipeline.orchestrator import enqueue_artifact_regeneration
from app.schemas.jobs import JobEnvelope, JobOut
from app.schemas.staging import RedoRequest

router = APIRouter(prefix="/api/admin", tags=["admin-staging"], dependencies=ADMIN_DEPENDENCIES)


def _dispatch(artifact_id: str, job_id: str, redo_note: str | None, is_audio: bool) -> None:
    from app.tasks.generation import generate_artifact_task

    generate_artifact_task.apply_async(
        kwargs={"artifact_id": artifact_id, "job_id": job_id, "redo_note": redo_note},
        queue="audio" if is_audio else "text",
    )


def _requeue(
    db: DbDep,
    admin: CurrentAdmin,
    background: BackgroundTasks,
    artifact_id: uuid.UUID,
    redo_note: str | None,
    options: dict[str, Any] | None = None,
) -> JobEnvelope:
    artifact = db.get(Artifact, artifact_id)
    if artifact is None:
        raise APIError(status.HTTP_404_NOT_FOUND, "not_found", "Artifact not found")

    job = enqueue_artifact_regeneration(
        db, artifact_id, redo_note=redo_note, requested_by=admin.id, options=options
    )
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
    return _requeue(db, admin, background, artifact_id, note, body.options)


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
