"""Celery task: typeset an artifact version's PDF after it is generated.

Decoupled from generation: the artifact is already `ready` when this runs, and
nothing here changes its status or last_error. An unavailable typeset service
is retried with exponential back-off (30 s, 1, 2, 4, 8, 16 min: about half an
hour in all); a permanent typeset or content error is logged and stores
nothing. `python -m app.cli rebuild-pdfs` builds any PDF that is missing.
"""

from __future__ import annotations

import uuid

from celery import Task, shared_task

from app.db.session import session_scope
from app.logging import get_logger
from app.pipeline.artifact_pdf import PdfSkipped, delete_files, prepare_pdf, store_pdf
from app.render.typeset_client import TypesetError, TypesetUnavailable, render_pdf

log = get_logger("tasks.pdf")

MAX_RETRIES = 6
RETRY_BASE_SEC = 30


@shared_task(bind=True, name="app.tasks.build_artifact_pdf", queue="text")
def build_artifact_pdf(self: Task, version_id: str) -> str:
    """Returns "built", "skipped", "failed" or "gave up" (out of retries)."""
    vid = uuid.UUID(version_id)
    try:
        # Two short sessions: none is held open while the service typesets.
        with session_scope() as session:
            source = prepare_pdf(session, vid)
        result = render_pdf(*source.doc)
        with session_scope() as session:
            stored = store_pdf(session, vid, source.kind, result.pdf)
            key = stored.media.storage_key
        delete_files(stored.stale_keys)
    except PdfSkipped as exc:
        log.info("pdf.skipped", version_id=version_id, reason=str(exc))
        return "skipped"
    except TypesetUnavailable as exc:
        retries = self.request.retries
        if retries >= MAX_RETRIES:
            log.error("pdf.gave_up", version_id=version_id, attempts=retries + 1, error=str(exc))
            return "gave up"
        countdown = RETRY_BASE_SEC * 2**retries
        log.warning("pdf.retry", version_id=version_id, countdown=countdown, error=str(exc))
        raise self.retry(exc=exc, countdown=countdown, max_retries=MAX_RETRIES) from exc
    except TypesetError as exc:
        log.error("pdf.failed", version_id=version_id, error=str(exc))
        return "failed"
    except Exception as exc:  # e.g. content_json that doesn't fit its type
        log.exception("pdf.failed", version_id=version_id, error=f"{type(exc).__name__}: {exc}")
        return "failed"

    log.info("pdf.built", version_id=version_id, key=key, fallback=result.fallback)
    if result.fallback != "0":
        log.warning("pdf.formulas_shown_as_source", version_id=version_id, fallback=result.fallback)
    return "built"
