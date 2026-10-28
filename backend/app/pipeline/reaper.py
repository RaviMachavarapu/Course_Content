"""Resolve generation jobs whose worker is gone (run by beat every 5 minutes).

A worker killed mid-generation (restart, OOM) leaves its job `running` and the
artifact `processing`; with `acks_late` the message only comes back after the
broker's visibility timeout (4 h), and a lost broker drops `queued` messages
for good. Without this, the card sits on "Generating…" for hours.

- a `running` job whose heartbeat (touched every minute by its worker) is
  older than `job_stale_running_sec` → failed;
- a `queued` job untouched for `job_stale_queued_sec` → failed;
- an artifact still `processing` with no active job (an older bug) → error.

The artifact then shows a retryable error. Nothing is ever re-run here: a
redelivered message for a reaped job finds it `failed` and does nothing (see
`orchestrator.run_artifact_generation`), and a worker that was merely slow finds
its job resolved and drops its result (the NotebookLM id stays on the artifact,
so Retry resumes it instead of generating again).
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.logging import get_logger
from app.models.artifact import Artifact
from app.models.enums import ArtifactStatus, GenerationJobState
from app.models.generation_job import GenerationJob
from app.pipeline.orchestrator import ACTIVE_JOB_STATES
from app.services.derived_status import recompute_status

log = get_logger("reaper")

WORKER_LOST = (
    "Generation stopped: the worker running it went away (for example a restart). " "Press Retry."
)
NEVER_STARTED = "Generation never started: no worker picked the job up. Press Retry."
INTERRUPTED = "Generation was interrupted. Press Retry."


def reap_stale_jobs(
    session: Session, *, running_after: dt.timedelta, queued_after: dt.timedelta
) -> int:
    """Fail stale jobs (and their artifacts); returns how many jobs/artifacts were
    resolved. Each one commits on its own, under artifact → job row locks."""
    now = func.now()
    stale_running = and_(
        GenerationJob.state == GenerationJobState.running,
        func.coalesce(
            GenerationJob.heartbeat_at, GenerationJob.started_at, GenerationJob.created_at
        )
        < now - running_after,
    )
    stale_queued = and_(
        GenerationJob.state == GenerationJobState.queued,
        func.coalesce(GenerationJob.heartbeat_at, GenerationJob.created_at) < now - queued_after,
    )
    candidates = session.execute(
        select(GenerationJob.id, GenerationJob.artifact_id).where(or_(stale_running, stale_queued))
    ).all()
    session.commit()  # end the read; each job below gets its own short transaction

    resolved = 0
    for job_id, artifact_id in candidates:
        if _reap_job(session, job_id, artifact_id, stale_running, stale_queued):
            resolved += 1

    active = exists().where(
        GenerationJob.artifact_id == Artifact.id, GenerationJob.state.in_(ACTIVE_JOB_STATES)
    )
    orphans = session.scalars(
        select(Artifact.id).where(
            Artifact.status == ArtifactStatus.processing,
            Artifact.updated_at < now - running_after,
            ~active,
        )
    ).all()
    session.commit()
    for artifact_id in orphans:
        artifact = session.get(Artifact, artifact_id, with_for_update=True, populate_existing=True)
        still_orphan = (
            artifact is not None
            and artifact.status is ArtifactStatus.processing
            and not session.scalar(
                select(
                    exists().where(
                        GenerationJob.artifact_id == artifact_id,
                        GenerationJob.state.in_(ACTIVE_JOB_STATES),
                    )
                )
            )
        )
        if not still_orphan or artifact is None:
            session.rollback()
            continue
        artifact.status = ArtifactStatus.error
        artifact.last_error = INTERRUPTED
        recompute_status(session, artifact.module)
        session.commit()
        log.warning("reaper.artifact_reset", artifact_id=str(artifact_id))
        resolved += 1
    return resolved


def _reap_job(
    session: Session,
    job_id: uuid.UUID,
    artifact_id: uuid.UUID | None,
    stale_running: ColumnElement[bool],
    stale_queued: ColumnElement[bool],
) -> bool:
    artifact = (
        session.get(Artifact, artifact_id, with_for_update=True, populate_existing=True)
        if artifact_id is not None
        else None
    )
    # re-check under the lock: the worker may have finished or touched it meanwhile
    job = session.scalar(
        select(GenerationJob)
        .where(GenerationJob.id == job_id, or_(stale_running, stale_queued))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if job is None:
        session.rollback()
        return False
    message = WORKER_LOST if job.state is GenerationJobState.running else NEVER_STARTED
    job.state = GenerationJobState.failed
    job.error_detail = message
    job.finished_at = func.now()
    if artifact is not None and artifact.status is ArtifactStatus.processing:
        artifact.status = ArtifactStatus.error
        artifact.last_error = message
        session.flush()
        recompute_status(session, artifact.module)
    session.commit()
    log.warning("reaper.job_failed", job_id=str(job_id), artifact_id=str(artifact_id))
    return True
