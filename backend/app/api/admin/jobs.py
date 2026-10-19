"""Admin job status + module staging view (spec.md §3.3, §5.3) — the polling
contract the Staging Review screen uses while artifacts generate."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status
from sqlalchemy import desc, func, select

from app.api.admin import ADMIN_DEPENDENCIES
from app.api.deps import DbDep
from app.errors import APIError
from app.models.artifact import Artifact
from app.models.enums import ARTIFACT_TYPES, GenerationJobState
from app.models.generation_job import GenerationJob
from app.models.module import Module
from app.pipeline.preview import content_preview
from app.schemas.jobs import JobListResponse, JobOut, RecentJobOut, RecentJobsResponse
from app.schemas.staging import (
    CurrentVersionOut,
    MediaOut,
    StagingArtifactOut,
    StagingModuleOut,
    StagingResponse,
)
from app.storage.service import get_storage

router = APIRouter(prefix="/api/admin", tags=["admin-jobs"], dependencies=ADMIN_DEPENDENCIES)


@router.get("/jobs/recent", response_model=RecentJobsResponse)
def recent_jobs(db: DbDep, limit: int = 15) -> RecentJobsResponse:
    """Recent finished generation jobs (succeeded / failed) for the notifications
    feed — newest first, each with a deep link to its module's staging view."""
    sort_key = func.coalesce(GenerationJob.finished_at, GenerationJob.created_at)
    rows = db.execute(
        select(GenerationJob, Module.title, Module.course_id, Artifact.type)
        .join(Module, Module.id == GenerationJob.module_id, isouter=True)
        .join(Artifact, Artifact.id == GenerationJob.artifact_id, isouter=True)
        .where(GenerationJob.state.in_([GenerationJobState.succeeded, GenerationJobState.failed]))
        .order_by(desc(sort_key))
        .limit(min(max(limit, 1), 100))
    ).all()
    return RecentJobsResponse(
        jobs=[
            RecentJobOut(
                id=job.id,
                kind=job.kind,
                state=job.state,
                artifact_type=artifact_type.value if artifact_type is not None else None,
                module_id=job.module_id,
                module_title=title,
                course_id=course_id,
                error_detail=job.error_detail,
                at=job.finished_at or job.created_at,
            )
            for job, title, course_id, artifact_type in rows
        ]
    )


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: uuid.UUID, db: DbDep) -> JobOut:
    job = db.get(GenerationJob, job_id)
    if job is None:
        raise APIError(status.HTTP_404_NOT_FOUND, "not_found", "Job not found")
    return JobOut.model_validate(job)


@router.get("/modules/{module_id}/jobs", response_model=JobListResponse)
def list_module_jobs(module_id: uuid.UUID, db: DbDep, limit: int = 50) -> JobListResponse:
    rows = db.scalars(
        select(GenerationJob)
        .where(GenerationJob.module_id == module_id)
        .order_by(desc(GenerationJob.created_at))
        .limit(min(limit, 200))
    )
    return JobListResponse(jobs=[JobOut.model_validate(j) for j in rows])


@router.get("/modules/{module_id}/staging", response_model=StagingResponse)
def module_staging(module_id: uuid.UUID, db: DbDep) -> StagingResponse:
    module = db.get(Module, module_id)
    if module is None:
        raise APIError(status.HTTP_404_NOT_FOUND, "not_found", "Module not found")

    storage = get_storage()
    by_type = {a.type: a for a in module.artifacts}
    artifacts_out: list[StagingArtifactOut] = []

    for artifact_type in ARTIFACT_TYPES:
        artifact = by_type.get(artifact_type)
        if artifact is None:
            continue

        current: CurrentVersionOut | None = None
        if artifact.current_version_id is not None:
            version = next(
                (v for v in artifact.versions if v.id == artifact.current_version_id), None
            )
            if version is not None:
                current = CurrentVersionOut(
                    id=version.id,
                    revision=version.revision,
                    redo_note=version.redo_note,
                    created_at=version.created_at,
                    preview=content_preview(artifact.type, version.content_json),
                    media=[
                        MediaOut(
                            kind=m.kind.value,
                            url=storage.url_for(m.storage_key),
                            size_bytes=m.size_bytes,
                            page_index=m.page_index,
                        )
                        for m in version.media_files
                    ],
                )

        latest_job = db.scalar(
            select(GenerationJob)
            .where(GenerationJob.artifact_id == artifact.id)
            .order_by(desc(GenerationJob.created_at))
            .limit(1)
        )
        artifacts_out.append(
            StagingArtifactOut(
                id=artifact.id,
                type=artifact.type,
                status=artifact.status,
                last_error=artifact.last_error,
                current_version=current,
                job={"state": latest_job.state if latest_job else None},
                generation_options=artifact.generation_options,
            )
        )

    return StagingResponse(
        module=StagingModuleOut(
            id=module.id,
            title=module.title,
            status=module.status,
            course_id=module.course_id,
            course_status=module.course.status,
        ),
        artifacts=artifacts_out,
    )
