"""Generation orchestration (plan.md §4.3).

Pure, synchronous functions the Celery tasks (`app/tasks/generation.py`) call
inside a session. No Celery imports here so the whole flow is unit-testable
against `FixtureProvider`.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.logging import get_logger
from app.models.artifact import Artifact
from app.models.artifact_version import ArtifactVersion
from app.models.enums import (
    ARTIFACT_TYPES,
    ArtifactStatus,
    ArtifactType,
    GenerationJobKind,
    GenerationJobState,
)
from app.models.generation_job import GenerationJob
from app.models.module import Module
from app.models.status import derive_course_status, derive_module_status
from app.pipeline.parsers import parse_artifact
from app.pipeline.provider import (
    ContentProvider,
    GenerationTimeout,
    NotebookRef,
    StudioJobRef,
    StudioStatus,
)
from app.pipeline.renderers import RENDERERS
from app.render import RenderError
from app.schemas.content_options import validate_options
from app.services.prompts import get_active_body, get_active_template
from app.storage.keys import media_key
from app.storage.service import STORAGE_EXTS, get_storage

log = get_logger("orchestrator")

_POLL_INTERVAL_SEC = 3.0


@dataclass(frozen=True)
class ArtifactJob:
    artifact_id: uuid.UUID
    job_id: uuid.UUID
    type: ArtifactType


# -- BR1: every module always has all six artifact rows --------------------
def ensure_artifacts(session: Session, module: Module) -> dict[ArtifactType, Artifact]:
    existing = {a.type: a for a in module.artifacts}
    for artifact_type in ARTIFACT_TYPES:
        if artifact_type not in existing:
            artifact = Artifact(type=artifact_type, status=ArtifactStatus.pending)
            module.artifacts.append(artifact)
            existing[artifact_type] = artifact
    session.flush()
    return existing


def enqueue_artifact_regeneration(
    session: Session,
    artifact_id: uuid.UUID,
    *,
    redo_note: str | None,
    requested_by: uuid.UUID | None = None,
    options: dict[str, Any] | None = None,
) -> GenerationJob:
    """Queue a (re)generation of a single artifact (redo or retry).

    Creates the job row, flips the artifact to `processing`, and recomputes the
    rolled-up status. The caller dispatches `generate_artifact_task` with the
    returned job id. `published_version_id` is never touched here. `options`
    (if given) overwrites the artifact's stored `generation_options` for this
    and future generations.
    """
    artifact = session.get(Artifact, artifact_id)
    if artifact is None:
        raise ValueError(f"artifact {artifact_id} not found")

    if options is not None:
        artifact.generation_options = validate_options(artifact.type, options)

    kind = (
        GenerationJobKind.redo_artifact
        if redo_note is not None
        else GenerationJobKind.generate_artifact
    )
    job = GenerationJob(
        kind=kind,
        module_id=artifact.module_id,
        artifact_id=artifact.id,
        state=GenerationJobState.queued,
        requested_by=requested_by,
    )
    session.add(job)
    artifact.status = ArtifactStatus.processing
    artifact.last_error = None
    session.flush()
    _recompute_status(session, artifact.module)
    session.flush()
    log.info(
        "orchestrator.artifact_requeued",
        artifact_id=str(artifact_id),
        kind=kind.value,
        job_id=str(job.id),
    )
    return job


# -- generate_module -----------------------------------------------------
def start_module_generation(
    session: Session,
    provider: ContentProvider,
    module_id: uuid.UUID,
    types: Iterable[ArtifactType],
    *,
    requested_by: uuid.UUID | None = None,
    options_by_type: dict[ArtifactType, dict[str, Any]] | None = None,
) -> list[ArtifactJob]:
    """Create the notebook + source and enqueue one `generate_artifact` job per
    requested type. Returns the (artifact, job) pairs for the caller to dispatch.
    `options_by_type` (if given) sets each artifact's stored generation
    options; any type not present gets that type's defaults.
    """
    module = session.get(Module, module_id)
    if module is None:
        raise ValueError(f"module {module_id} not found")

    artifacts = ensure_artifacts(session, module)
    requested = list(dict.fromkeys(types)) or list(ARTIFACT_TYPES)
    options_by_type = options_by_type or {}

    nb = provider.create_notebook(module.title)
    module.notebooklm_notebook_id = nb.notebook_id
    provider.add_source(nb, module.source_url)

    jobs: list[ArtifactJob] = []
    for artifact_type in requested:
        artifact = artifacts[artifact_type]
        artifact.generation_options = validate_options(
            artifact_type, options_by_type.get(artifact_type, {})
        )
        artifact.status = ArtifactStatus.processing
        artifact.last_error = None
        job = GenerationJob(
            kind=GenerationJobKind.generate_artifact,
            module_id=module.id,
            artifact_id=artifact.id,
            state=GenerationJobState.queued,
            requested_by=requested_by,
        )
        session.add(job)
        session.flush()
        jobs.append(ArtifactJob(artifact_id=artifact.id, job_id=job.id, type=artifact_type))

    _recompute_status(session, module)
    session.flush()
    log.info("orchestrator.module_started", module_id=str(module_id), jobs=len(jobs))
    return jobs


# -- generate_artifact / redo_artifact --------------------------------
def run_artifact_generation(
    session: Session,
    provider: ContentProvider,
    artifact_id: uuid.UUID,
    *,
    job_id: uuid.UUID | None = None,
    redo_note: str | None = None,
    requested_by: uuid.UUID | None = None,
) -> ArtifactVersion:
    artifact = session.get(Artifact, artifact_id)
    if artifact is None:
        raise ValueError(f"artifact {artifact_id} not found")
    module = artifact.module
    course = module.course

    job = _resolve_job(session, artifact, job_id, redo_note, requested_by)
    job.state = GenerationJobState.running
    job.started_at = func.now()
    job.attempts += 1
    artifact.status = ArtifactStatus.processing
    session.flush()

    try:
        version = _generate(session, provider, artifact, job, redo_note, settings_timeout(artifact))
    except Exception as exc:
        artifact.status = ArtifactStatus.error
        artifact.last_error = f"{type(exc).__name__}: {exc}"
        job.state = GenerationJobState.failed
        job.error_detail = artifact.last_error
        job.finished_at = func.now()
        _recompute_status(session, module)
        session.flush()
        log.warning(
            "orchestrator.artifact_failed",
            artifact_id=str(artifact_id),
            type=artifact.type.value,
            error=artifact.last_error,
        )
        raise

    artifact.current_version_id = version.id
    artifact.status = ArtifactStatus.ready
    artifact.last_error = None
    job.state = GenerationJobState.succeeded
    job.finished_at = func.now()
    _recompute_status(session, module)
    session.flush()
    log.info(
        "orchestrator.artifact_ready",
        artifact_id=str(artifact_id),
        type=artifact.type.value,
        revision=version.revision,
        course=str(course.id),
    )
    return version


# -- internals ----------------------------------------------------------
def settings_timeout(artifact: Artifact) -> int:
    s = get_settings()
    if artifact.type is ArtifactType.audio_overview:
        return s.mcp_timeout_audio_sec
    return s.mcp_timeout_text_sec


def _resolve_job(
    session: Session,
    artifact: Artifact,
    job_id: uuid.UUID | None,
    redo_note: str | None,
    requested_by: uuid.UUID | None,
) -> GenerationJob:
    if job_id is not None:
        job = session.get(GenerationJob, job_id)
        if job is not None:
            return job
    kind = (
        GenerationJobKind.redo_artifact
        if redo_note is not None
        else GenerationJobKind.generate_artifact
    )
    job = GenerationJob(
        kind=kind,
        module_id=artifact.module_id,
        artifact_id=artifact.id,
        state=GenerationJobState.queued,
        requested_by=requested_by,
    )
    session.add(job)
    session.flush()
    return job


def _generate(
    session: Session,
    provider: ContentProvider,
    artifact: Artifact,
    job: GenerationJob,
    redo_note: str | None,
    timeout_sec: int,
) -> ArtifactVersion:
    module = artifact.module
    nb = NotebookRef(notebook_id=module.notebooklm_notebook_id or "")
    if not nb.notebook_id:
        nb = provider.create_notebook(module.title)
        module.notebooklm_notebook_id = nb.notebook_id
        provider.add_source(nb, module.source_url)

    template = get_active_template(session, artifact.type)
    base_body = get_active_body(session, artifact.type)
    focus_prompt = base_body
    if redo_note:
        focus_prompt = (
            f"{base_body}\n\nAdditional instruction for this revision:\n{redo_note.strip()}"
        )

    studio_job = provider.generate(nb, artifact.type, focus_prompt, artifact.generation_options)
    _await_ready(provider, studio_job, timeout_sec)
    raw = provider.fetch_content(studio_job)
    content_json = parse_artifact(artifact.type, raw.html, raw.extras)

    revision = (
        session.scalar(
            select(func.coalesce(func.max(ArtifactVersion.revision), 0)).where(
                ArtifactVersion.artifact_id == artifact.id
            )
        )
        or 0
    ) + 1

    version = ArtifactVersion(
        artifact_id=artifact.id,
        revision=revision,
        generation_job_id=job.id,
        prompt_template_id=template.id if template else None,
        prompt_template_version=template.version if template else None,
        focus_prompt_used=focus_prompt,
        redo_note=redo_note,
        content_json=content_json,
        content_html=raw.html,
        notebooklm_artifact_id=str(raw.extras.get("artifact_id") or "") or None,
    )
    session.add(version)
    session.flush()

    _render_and_store(session, provider, artifact, version, studio_job, content_json)
    return version


def _await_ready(provider: ContentProvider, job: StudioJobRef, timeout_sec: int) -> None:
    deadline = time.monotonic() + timeout_sec
    while True:
        status = provider.poll(job)
        if status is StudioStatus.ready:
            return
        if status is StudioStatus.failed:
            raise RenderError("Studio reported the generation failed")
        if time.monotonic() > deadline:
            raise GenerationTimeout(f"generation exceeded {timeout_sec}s")
        time.sleep(_POLL_INTERVAL_SEC)


def _render_and_store(
    session: Session,
    provider: ContentProvider,
    artifact: Artifact,
    version: ArtifactVersion,
    studio_job: StudioJobRef,
    content_json: dict[str, object],
) -> None:
    blobs = RENDERERS[artifact.type](content_json, provider, studio_job)
    if not blobs:
        return
    storage = get_storage()
    module = artifact.module
    for blob in blobs:
        key = media_key(
            course_id=module.course_id,
            module_id=module.id,
            artifact_id=artifact.id,
            revision=version.revision,
            kind=blob.kind,
            ext=STORAGE_EXTS[blob.kind],
            page_index=blob.page_index,
        )
        stored = storage.put(key, blob.data, blob.mime)
        session.add(
            storage.build_media_file(
                stored,
                artifact_version_id=str(version.id),
                kind=blob.kind,
                page_index=blob.page_index,
            )
        )
        if blob.content_html is not None:
            version.content_html = blob.content_html
    session.flush()


def _recompute_status(session: Session, module: Module) -> None:
    session.flush()
    artifact_statuses = list(
        session.scalars(select(Artifact.status).where(Artifact.module_id == module.id))
    )
    module.status = derive_module_status(artifact_statuses)
    session.flush()
    module_statuses = list(
        session.scalars(select(Module.status).where(Module.course_id == module.course_id))
    )
    module.course.status = derive_course_status(module_statuses)
    session.flush()
