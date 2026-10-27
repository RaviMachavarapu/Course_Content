"""Celery task: typeset an artifact version's PDF after it is generated.

Decoupled from generation: the artifact is already `ready` when this runs, and
nothing here changes its status or last_error. It runs on its own `pdf` queue
(the `worker-pdf` service, one at a time), so a slow typeset service never
takes a generation slot. An unavailable typeset service, or a database
connection error, is retried with exponential back-off (30 s, 1, 2, 4, 8,
16 min: about half an hour in all). A version that is no longer current or
published is skipped. A permanent typeset or content error is logged and
stores nothing. `python -m app.cli rebuild-pdfs` builds any PDF that is missing.
"""

from __future__ import annotations

import uuid

from celery import Task, shared_task
from sqlalchemy.exc import OperationalError

from app.db.session import session_scope
from app.logging import get_logger
from app.pipeline.artifact_pdf import (
    PdfSkipped,
    StoredPdf,
    delete_files,
    discard_new_file,
    prepare_pdf,
    store_pdf,
)
from app.render.typeset_client import TypesetError, TypesetUnavailable, render_pdf

log = get_logger("tasks.pdf")

MAX_RETRIES = 6
RETRY_BASE_SEC = 30


@shared_task(bind=True, name="app.tasks.build_artifact_pdf", queue="pdf")
def build_artifact_pdf(self: Task, version_id: str) -> str:
    """Returns "built", "skipped", "failed" or "gave up" (out of retries)."""
    vid = uuid.UUID(version_id)
    try:
        # Two short sessions: none is held open while the service typesets.
        with session_scope() as session:
            source = prepare_pdf(session, vid)
        result = render_pdf(*source.doc)
        stored: StoredPdf | None = None
        try:
            with session_scope() as session:
                stored = store_pdf(session, vid, source.kind, result.pdf)
        except Exception:
            if stored is not None:  # the commit failed: don't orphan the new file
                discard_new_file(stored)
            raise
        key = stored.new_key
        delete_files(stored.stale_keys)
    except PdfSkipped as exc:
        log.info("pdf.skipped", version_id=version_id, reason=str(exc))
        return "skipped"
    except (TypesetUnavailable, OperationalError) as exc:  # service or database away
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
