"""Celery tasks for the generation pipeline.

Thin wrappers around `app.pipeline.orchestrator`: open a session, run the pure
function, dispatch the fan-out. Transient provider errors retry with backoff;
everything else isolates to the one artifact (its siblings are untouched).
A running job's heartbeat lets the reaper (`app.tasks.reap_stale_jobs`) find
jobs whose worker died, or that stopped making progress (the heartbeat thread
only beats while the run keeps moving on: `job_stall_sec`). Each message carries
Celery time limits, so a stuck call can't hold a worker slot for good.

`dispatch_jobs` sends jobs' stored messages (`GenerationJob.dispatch`); a broker
error is only logged: the reaper sends a lost message again.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from celery import Task, shared_task

from app.config import get_settings
from app.db.session import session_scope
from app.logging import get_logger
from app.pipeline.factory import get_content_provider
from app.pipeline.orchestrator import (
    JobSkipped,
    run_artifact_generation,
    touch_job_heartbeat,
)
from app.pipeline.provider import TransientProviderError
from app.render.typeset_docs import PDF_KINDS
from app.tasks.pdf import build_artifact_pdf

log = get_logger("tasks.generation")

_MAX_RETRIES = 3


def send_job(payload: dict[str, Any]) -> None:
    """Publish one job's message (`GenerationJob.dispatch`). The Celery task id
    carries the job id, so the reaper can tell whether the broker still holds it."""
    kwargs = payload["kwargs"]
    limits = {k: payload[k] for k in ("soft_time_limit", "time_limit") if payload.get(k)}
    generate_artifact_task.apply_async(
        kwargs=kwargs,
        queue=payload["queue"],
        task_id=f"gen-{kwargs['job_id']}-{uuid.uuid4().hex[:8]}",
        **limits,
    )


def dispatch_jobs(payloads: list[dict[str, Any]]) -> None:
    """Send jobs after their transaction committed. A broker error (Redis restarting,
    an auth error) is logged, never raised: the job stays queued and the reaper sends
    its stored message again (outbox)."""
    for payload in payloads:
        try:
            send_job(payload)
        except Exception as exc:
            log.warning(
                "generation.dispatch_failed",
                job_id=payload.get("kwargs", {}).get("job_id"),
                error=str(exc),
            )


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
    resume: bool = False,
    outline: dict[str, Any] | None = None,
) -> str:
    """The orchestrator commits each state change itself (claim, NotebookLM id,
    result or failure). A job that isn't `queued` any more (a duplicate or
    redelivered message, or one the reaper already failed) is a no-op."""
    provider = get_content_provider()
    pdf_version: str | None = None
    liveness = Liveness()
    with _heartbeat(job_id, liveness), session_scope() as session:
        try:
            version = run_artifact_generation(
                session,
                provider,
                uuid.UUID(artifact_id),
                job_id=uuid.UUID(job_id) if job_id else None,
                redo_note=redo_note,
                resume=resume,
                # with retries left, a transient error re-queues the job for Celery's retry
                retry_transient=self.request.retries < _MAX_RETRIES,
                outline=outline,
                on_progress=liveness.touch,
            )
        except JobSkipped as exc:
            log.info("generation.skipped", artifact_id=artifact_id, reason=str(exc))
            return "skipped"
        if version is None:
            return "outline_review"  # NotebookLM drafted a slide outline for review
        outcome = str(version.id)
        if version.artifact.type in PDF_KINDS:
            pdf_version = outcome
    if pdf_version is not None:
        _enqueue_pdf(pdf_version)
    return outcome


class Liveness:
    """When the run last moved on (the main thread touches it; the heartbeat thread
    reads it). Monotonic seconds."""

    def __init__(self) -> None:
        self.last = time.monotonic()

    def touch(self) -> None:
        self.last = time.monotonic()

    def stalled(self, limit_sec: float) -> bool:
        return time.monotonic() - self.last > limit_sec


@contextmanager
def _heartbeat(job_id: str | None, liveness: Liveness | None = None) -> Iterator[None]:
    """Touch the job's heartbeat every `job_heartbeat_sec` while it runs, from a
    thread with its own sessions: the reaper fails a running job whose heartbeat
    stopped, so its card doesn't sit on "Generating…". The beat stops when the
    worker dies, and also when the run made no progress for `job_stall_sec` (alive
    but stuck, e.g. a call that never returns)."""
    if job_id is None:
        yield
        return
    settings = get_settings()
    interval = settings.job_heartbeat_sec
    stall = settings.job_stall_sec
    stop = threading.Event()
    jid = uuid.UUID(job_id)

    def beat() -> None:
        warned = False
        while not stop.wait(interval):
            if liveness is not None and liveness.stalled(stall):
                if not warned:
                    log.warning("generation.stalled", job_id=job_id, stall_sec=stall)
                    warned = True
                continue
            warned = False
            try:
                with session_scope() as db:
                    touch_job_heartbeat(db, jid)
            except Exception as exc:  # a missed beat is fine; the next one retries
                log.warning("generation.heartbeat_failed", job_id=job_id, error=str(exc))

    thread = threading.Thread(target=beat, name=f"heartbeat-{job_id}", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=5)


def _enqueue_pdf(version_id: str) -> None:
    """Typeset the new version's PDF. Called after the generation session has
    committed, so the task always finds the version. A broker error only means
    no PDF yet (`rebuild-pdfs` builds it later), never a failed generation."""
    try:
        build_artifact_pdf.apply_async(args=[version_id], queue="pdf")
    except Exception as exc:
        log.warning("pdf.enqueue_failed", version_id=version_id, error=str(exc))
