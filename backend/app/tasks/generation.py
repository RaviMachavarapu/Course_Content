"""Celery tasks for the generation pipeline.

Thin wrappers around `app.pipeline.orchestrator`: open a session, run the pure
function, dispatch the fan-out. Transient provider errors retry with backoff;
everything else isolates to the one artifact (its siblings are untouched).
"""

from __future__ import annotations

import uuid

from celery import Task, shared_task

from app.db.session import session_scope
from app.logging import get_logger
from app.models.enums import ArtifactType
from app.pipeline.factory import get_content_provider
from app.pipeline.orchestrator import run_artifact_generation, start_module_generation
from app.pipeline.provider import TransientProviderError

log = get_logger("tasks.generation")

_MAX_RETRIES = 3


@shared_task(name="app.tasks.generate_module", queue="text")
def generate_module_task(module_id: str, types: list[str] | None = None) -> list[str]:
    wanted = [ArtifactType(t) for t in types] if types else list(ArtifactType)
    provider = get_content_provider()
    with session_scope() as session:
        jobs = start_module_generation(session, provider, uuid.UUID(module_id), wanted)
        dispatch = [(str(j.artifact_id), str(j.job_id), j.type) for j in jobs]

    for artifact_id, job_id, artifact_type in dispatch:
        queue = "audio" if artifact_type is ArtifactType.audio_overview else "text"
        generate_artifact_task.apply_async(
            kwargs={"artifact_id": artifact_id, "job_id": job_id}, queue=queue
        )
    return [d[1] for d in dispatch]


@shared_task(
    bind=True,
    name="app.tasks.generate_artifact",
    queue="text",
    autoretry_for=(TransientProviderError,),
    retry_backoff=True,
    retry_backoff_max=120,
    retry_jitter=True,
    max_retries=_MAX_RETRIES,
)
def generate_artifact_task(
    self: Task,
    artifact_id: str,
    job_id: str | None = None,
    redo_note: str | None = None,
) -> str:
    provider = get_content_provider()
    with session_scope() as session:
        version = run_artifact_generation(
            session,
            provider,
            uuid.UUID(artifact_id),
            job_id=uuid.UUID(job_id) if job_id else None,
            redo_note=redo_note,
        )
        return str(version.id)
