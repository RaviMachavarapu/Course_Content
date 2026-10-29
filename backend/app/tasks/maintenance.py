"""Periodic maintenance tasks (run by `beat`)."""

from __future__ import annotations

import datetime as dt
from typing import Any

import redis
from sqlalchemy import select

from app.api.deps import get_redis
from app.config import get_settings
from app.db.session import session_scope
from app.logging import get_logger
from app.models.enums import SourceUploadStatus
from app.models.module import Module
from app.models.source_upload import SourceUpload
from app.pipeline.factory import get_content_provider
from app.pipeline.provider import NotebookRef, TransientProviderError
from app.pipeline.reaper import broker_job_ids, reap_stale_jobs, redispatch_lost_jobs
from app.services.metrics import record_mcp_healthcheck
from app.storage.service import get_storage
from app.tasks.celery_app import celery_app

log = get_logger("tasks.maintenance")


@celery_app.task(name="app.tasks.mcp_healthcheck")
def mcp_healthcheck() -> bool:
    """Pings the content provider on a fixed cadence (T043). This is the
    system's only heartbeat: a successful run — whether or not the provider
    itself is healthy — proves the worker is alive and processing beat's
    periodic tasks, which `GET /api/admin/mcp/status` surfaces alongside the
    MCP connection state itself."""
    health = get_content_provider().health()
    record_mcp_healthcheck(get_redis(), healthy=health.healthy)
    log.info("mcp_healthcheck.done", healthy=health.healthy, detail=health.detail)
    return health.healthy


DELETE_NOTEBOOK_RETRIES = 3


@celery_app.task(bind=True, name="app.tasks.delete_notebook")
def delete_notebook_task(self: Any, notebook_id: str) -> str:
    """Delete a module's old NotebookLM notebook after Re-run all or a module delete
    committed (owner decision 2026-10-29: NotebookLM caps notebooks per account).
    Best effort: never touches our data; a failure is logged. Returns "deleted",
    "skipped" (still used by a module), "failed" or "gave up"."""
    with session_scope() as session:
        in_use = session.scalar(
            select(Module.id).where(Module.notebooklm_notebook_id == notebook_id).limit(1)
        )
    if in_use is not None:
        log.warning("notebook_delete.skipped_in_use", notebook_id=notebook_id)
        return "skipped"
    try:
        get_content_provider().delete_notebook(NotebookRef(notebook_id=notebook_id))
    except TransientProviderError as exc:
        retries = self.request.retries
        if retries >= DELETE_NOTEBOOK_RETRIES:
            log.warning("notebook_delete.gave_up", notebook_id=notebook_id, error=str(exc))
            return "gave up"
        raise self.retry(
            exc=exc, countdown=60 * 2**retries, max_retries=DELETE_NOTEBOOK_RETRIES
        ) from exc
    except Exception as exc:  # a provider error, a sign-in problem: logged, never raised
        log.warning(
            "notebook_delete.failed", notebook_id=notebook_id, error=f"{type(exc).__name__}: {exc}"
        )
        return "failed"
    log.info("notebook_delete.done", notebook_id=notebook_id)
    return "deleted"


def enqueue_notebook_delete(notebook_id: str | None) -> None:
    """Queue the old notebook's deletion (call after the commit). A broker error is
    logged, never raised: the admin action already succeeded."""
    if not notebook_id:
        return
    try:
        delete_notebook_task.apply_async(args=[notebook_id], queue="maintenance")
    except Exception as exc:
        log.warning("notebook_delete.enqueue_failed", notebook_id=notebook_id, error=str(exc))


@celery_app.task(name="app.tasks.media_gc")
def media_gc() -> int:
    """Delete media for superseded, non-published, non-current artifact versions
    beyond the keep-N window. Returns the number of `media_file` rows removed.
    """
    settings = get_settings()
    storage = get_storage()
    with session_scope() as session:
        removed = storage.gc_superseded_media(session, keep_last_n=settings.media_gc_keep_versions)
    log.info("media_gc.done", removed=removed)
    return removed


@celery_app.task(name="app.tasks.purge_abandoned_uploads")
def purge_abandoned_uploads() -> int:
    """Delete non-claimed chunked uploads older than 24 h, with their files."""
    cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(hours=24)
    storage = get_storage()
    with session_scope() as session:
        stale = session.scalars(
            select(SourceUpload).where(
                SourceUpload.status != SourceUploadStatus.claimed,
                SourceUpload.created_at < cutoff,
            )
        ).all()
        for upload in stale:
            storage.delete(upload.storage_key)
            session.delete(upload)
        session.flush()
        removed = len(stale)
    log.info("purge_abandoned_uploads.done", removed=removed)
    return removed


@celery_app.task(name="app.tasks.reap_stale_jobs")
def reap_stale_jobs_task() -> int:
    """Send lost generation messages again, and fail jobs whose worker is gone (see
    `app.pipeline.reaper`)."""
    from app.tasks.generation import send_job

    settings = get_settings()
    broker = redis.Redis.from_url(settings.celery_broker_url, decode_responses=True)
    try:
        with session_scope() as session:
            redispatched = redispatch_lost_jobs(
                session,
                after=dt.timedelta(seconds=settings.job_redispatch_after_sec),
                in_broker=lambda ids: broker_job_ids(broker, ids),
                send=send_job,
                max_redispatches=settings.job_max_redispatches,
            )
    finally:
        broker.close()
    if redispatched:
        log.warning("reap_stale_jobs.redispatched", jobs=redispatched)
    with session_scope() as session:
        resolved = reap_stale_jobs(
            session,
            running_after=dt.timedelta(seconds=settings.job_stale_running_sec),
            queued_after=dt.timedelta(seconds=settings.job_stale_queued_sec),
        )
    if resolved:
        log.warning("reap_stale_jobs.done", resolved=resolved)
    return resolved
