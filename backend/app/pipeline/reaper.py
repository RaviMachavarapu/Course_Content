"""Resolve generation jobs whose worker is gone (run by beat every 5 minutes).

A worker killed mid-generation (restart, OOM) leaves its job `running` and the
artifact `processing`; with `acks_late` the message only comes back after the
broker's visibility timeout (4 h), and a lost broker drops `queued` messages
for good. Without this, the card sits on "Generating…" for hours.

- a `running` job whose heartbeat (touched every minute by its worker while the
  run makes progress) is older than `job_stale_running_sec` → failed;
- a `queued` job untouched for `job_redispatch_after_sec` (`redispatch_lost_jobs`):
  if the broker still holds its message (a real backlog) it is kept alive; if not
  (lost on the way: broker down at enqueue, an api or Redis restart) its stored
  message (`GenerationJob.dispatch`, the outbox) is sent again, up to
  `job_max_redispatches` times, then failed;
- a `queued` job untouched for `job_stale_queued_sec` → failed (backstop when the
  broker can't be read);
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
from collections.abc import Callable, Iterable
from typing import Any

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
    "Generation stopped: the worker running it went away or stopped making progress "
    "(for example a restart, or a call that never returned). Press Retry."
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


#: Celery's Redis transport: queued messages are lists named after the queue (plus a
#: suffix per priority step); messages a worker holds (running, prefetched or waiting
#: for a retry countdown) are in the `unacked` hash until acked.
_PRIORITY_SEP = "\x06\x16"
_PRIORITY_STEPS = (3, 6, 9)
GENERATION_QUEUES = ("text", "audio")


def broker_job_ids(
    client: Any, job_ids: Iterable[str], queues: Iterable[str] = GENERATION_QUEUES
) -> set[str]:
    """Which of `job_ids` the broker (a Redis client on the Celery broker db, decoded
    responses) still holds a message for: queued, or held by a worker. Each message's
    task id carries its job id (`app.tasks.generation.send_job`)."""
    wanted = set(job_ids)
    if not wanted:
        return set()
    raws: list[str] = []
    for queue in queues:
        for key in (queue, *(f"{queue}{_PRIORITY_SEP}{p}" for p in _PRIORITY_STEPS)):
            raws.extend(client.lrange(key, 0, -1))
    raws.extend(client.hvals("unacked"))
    return {jid for jid in wanted if any(jid in raw for raw in raws)}


def redispatch_lost_jobs(
    session: Session,
    *,
    after: dt.timedelta,
    in_broker: Callable[[set[str]], set[str]],
    send: Callable[[dict[str, Any]], None],
    max_redispatches: int,
) -> int:
    """Queued jobs untouched for `after`: kept alive while the broker holds their
    message, otherwise their stored message is sent again (outbox) — at most
    `max_redispatches` times, then the job fails like one nobody picked up. Returns
    how many were sent or failed. If the broker can't be read, nothing is done (the
    `job_stale_queued_sec` backstop still applies)."""
    stale = and_(
        GenerationJob.state == GenerationJobState.queued,
        GenerationJob.dispatch.is_not(None),
        func.coalesce(GenerationJob.heartbeat_at, GenerationJob.created_at) < func.now() - after,
    )
    candidates = [str(i) for i in session.scalars(select(GenerationJob.id).where(stale))]
    session.commit()
    if not candidates:
        return 0
    try:
        held = in_broker(set(candidates))
    except Exception as exc:  # broker unreachable: try again next cycle
        log.warning("reaper.broker_unreadable", error=str(exc))
        return 0

    acted = 0
    for job_id in candidates:
        payload = _claim_redispatch(
            session, uuid.UUID(job_id), stale, job_id in held, max_redispatches
        )
        if payload is None:
            continue
        acted += 1
        if payload is _FAILED:
            continue
        try:
            send(payload)
        except Exception as exc:  # still down: the next cycle tries again
            log.warning("reaper.redispatch_failed", job_id=job_id, error=str(exc))
    return acted


_FAILED: dict[str, Any] = {}


def _claim_redispatch(
    session: Session,
    job_id: uuid.UUID,
    stale: ColumnElement[bool],
    held: bool,
    max_redispatches: int,
) -> dict[str, Any] | None:
    """(Short transaction) None: nothing to send (resolved meanwhile, or still in the
    broker: kept alive); `_FAILED`: out of redispatches; else the payload to send."""
    job = session.scalar(
        select(GenerationJob)
        .where(GenerationJob.id == job_id, stale)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if job is None or job.dispatch is None:
        session.rollback()
        return None
    if held:  # waiting in a real backlog: not lost
        job.heartbeat_at = func.now()
        session.commit()
        return None
    count = int(job.dispatch.get("redispatches", 0)) + 1
    if count > max_redispatches:
        session.rollback()
        artifact_id = job.artifact_id
        resolved = _reap_job(session, job_id, artifact_id, stale, stale)
        return _FAILED if resolved else None
    job.dispatch = {**job.dispatch, "redispatches": count}
    job.heartbeat_at = func.now()
    payload = dict(job.dispatch)
    session.commit()
    log.warning("reaper.job_redispatched", job_id=str(job_id), attempt=count)
    return payload
