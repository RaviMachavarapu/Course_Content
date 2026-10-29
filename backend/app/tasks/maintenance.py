"""Periodic maintenance tasks (run by `beat`)."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select

from app.api.deps import get_redis
from app.config import get_settings
from app.db.session import session_scope
from app.logging import get_logger
from app.models.enums import SourceUploadStatus
from app.models.source_upload import SourceUpload
from app.pipeline.factory import get_content_provider
from app.pipeline.reaper import reap_stale_jobs
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
    """Fail generation jobs whose worker is gone (see `app.pipeline.reaper`)."""
    settings = get_settings()
    with session_scope() as session:
        resolved = reap_stale_jobs(
            session,
            running_after=dt.timedelta(seconds=settings.job_stale_running_sec),
            queued_after=dt.timedelta(seconds=settings.job_stale_queued_sec),
        )
    if resolved:
        log.warning("reap_stale_jobs.done", resolved=resolved)
    return resolved
