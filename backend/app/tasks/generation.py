"""Celery tasks for the generation pipeline.

Thin wrappers around `app.pipeline.orchestrator`: open a session, run the pure
function, dispatch the fan-out. Transient provider errors retry with backoff;
everything else isolates to the one artifact (its siblings are untouched).
A running job's heartbeat lets the reaper (`app.tasks.reap_stale_jobs`) find
jobs whose worker died.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from celery import Task, shared_task

from app.config import get_settings
from app.db.session import session_scope
from app.logging import get_logger
from app.models.enums import ArtifactType
from app.pipeline.factory import get_content_provider
from app.pipeline.orchestrator import (
    JobSkipped,
    run_artifact_generation,
    start_module_generation,
    touch_job_heartbeat,
)
from app.pipeline.provider import TransientProviderError
from app.render.typeset_docs import PDF_KINDS
from app.tasks.pdf import build_artifact_pdf

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
    resume: bool = False,
) -> str:
    """The orchestrator commits each state change itself (claim, NotebookLM id,
    result or failure). A job that isn't `queued` any more (a duplicate or
    redelivered message, or one the reaper already failed) is a no-op."""
    provider = get_content_provider()
    pdf_version: str | None = None
    with _heartbeat(job_id), session_scope() as session:
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


@contextmanager
def _heartbeat(job_id: str | None) -> Iterator[None]:
    """Touch the job's heartbeat every `job_heartbeat_sec` while it runs, from a
    thread with its own sessions: the reaper fails a running job whose heartbeat
    stopped (worker killed), so its card doesn't sit on "Generating…"."""
    if job_id is None:
        yield
        return
    interval = get_settings().job_heartbeat_sec
    stop = threading.Event()
    jid = uuid.UUID(job_id)

    def beat() -> None:
        while not stop.wait(interval):
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
