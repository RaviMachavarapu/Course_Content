"""Generation orchestration (plan.md §4.3).

Pure, synchronous functions the Celery tasks (`app/tasks/generation.py`) call
inside a session. No Celery imports here so the whole flow is unit-testable
against `FixtureProvider`.
"""

from __future__ import annotations

import datetime as dt
import enum
import time
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import func, select, update
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
    MediaFileKind,
)
from app.models.generation_job import GenerationJob
from app.models.module import Module
from app.pipeline.media_probe import mp4_duration_seconds
from app.pipeline.module_sources import SourceStepError, ensure_module_sources
from app.pipeline.parsers import parse_artifact
from app.pipeline.parsers.base import ArtifactParseError
from app.pipeline.parsers.notebooklm import audio_url, parse_notebooklm, parse_outline
from app.pipeline.provider import (
    ContentProvider,
    GenerationTimeout,
    ProviderError,
    RawArtifact,
    StudioJobRef,
    StudioStatus,
    TransientProviderError,
)
from app.pipeline.renderers import RENDERERS, MediaBlob
from app.render import RenderError
from app.render.report_html import build_report_html
from app.schemas.content import AudioOverviewContent, ReportContent
from app.schemas.content_options import validate_options
from app.services.derived_status import recompute_status
from app.services.prompts import get_active_body, get_active_template
from app.storage.keys import media_key
from app.storage.service import STORAGE_EXTS, get_storage

T = TypeVar("T")

log = get_logger("orchestrator")

_POLL_INTERVAL_SEC = 3.0

#: a job in one of these states holds its artifact (at most one per artifact)
ACTIVE_JOB_STATES = (GenerationJobState.queued, GenerationJobState.running)


@dataclass(frozen=True)
class ArtifactJob:
    artifact_id: uuid.UUID
    job_id: uuid.UUID
    type: ArtifactType
    #: the Celery message to send once the transaction has committed
    dispatch: dict[str, Any] = field(default_factory=dict)


class Unset(enum.Enum):
    """Marks an optional argument the caller didn't pass (distinct from None)."""

    token = 0


UNSET = Unset.token


def _clean_prompt(text: str | None) -> str | None:
    return (text or "").strip() or None


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


class ArtifactBusy(Exception):
    """The artifact (or, for module-wide actions, one of the module's) is still
    generating; the API answers 409."""


BUSY_MESSAGE = "This artifact is still generating. Wait until it finishes or fails, then try again."


def _lock_artifact(session: Session, artifact_id: uuid.UUID) -> Artifact | None:
    """Row-lock the artifact, re-reading it (lock order: artifact → module → course)."""
    return session.get(Artifact, artifact_id, with_for_update=True, populate_existing=True)


def _cancel_lingering_jobs(session: Session, artifact_id: uuid.UUID) -> None:
    """Close queued/running jobs left on an artifact that is not processing (an older
    bug or a lost worker). Called with the artifact row locked, before a new job."""
    session.execute(
        update(GenerationJob)
        .where(GenerationJob.artifact_id == artifact_id, GenerationJob.state.in_(ACTIVE_JOB_STATES))
        .values(
            state=GenerationJobState.cancelled,
            finished_at=func.now(),
            error_detail="superseded by a newer job for this artifact",
        )
        .execution_options(synchronize_session=False)
    )


def _forget_studio_job(artifact: Artifact) -> None:
    artifact.notebooklm_studio_id = None
    artifact.studio_request = None
    artifact.outline_json = None


def dispatch_payload(
    artifact: Artifact,
    job: GenerationJob,
    *,
    redo_note: str | None = None,
    resume: bool = False,
    outline: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Store (and return) the Celery message that runs `job`: its queue, the task
    kwargs and the time limits. Kept on the job as an outbox, so a message lost on the
    way (broker down, api restart, Redis restart) can be sent again by the reaper."""
    s = get_settings()
    audio = artifact.type is ArtifactType.audio_overview
    limit = s.job_time_limit_audio_sec if audio else s.job_time_limit_text_sec
    kwargs: dict[str, Any] = {
        "artifact_id": str(artifact.id),
        "job_id": str(job.id),
        "redo_note": redo_note,
        "resume": resume,
    }
    if outline is not None:
        kwargs["outline"] = outline
    payload = {
        "queue": "audio" if audio else "text",
        "kwargs": kwargs,
        "soft_time_limit": limit,
        "time_limit": limit + 300,
    }
    job.dispatch = payload
    return payload


def _new_job(
    artifact: Artifact, kind: GenerationJobKind, requested_by: uuid.UUID | None
) -> GenerationJob:
    return GenerationJob(
        id=uuid.uuid4(),
        kind=kind,
        module_id=artifact.module_id,
        artifact_id=artifact.id,
        state=GenerationJobState.queued,
        requested_by=requested_by,
    )


CANCELLED = "Generation cancelled by an admin. Press Retry to try again."


class NotCancellable(Exception):
    """The artifact isn't generating; there is nothing to cancel."""


def cancel_generation(
    session: Session, artifact_id: uuid.UUID, *, requested_by: uuid.UUID | None = None
) -> Artifact:
    """The admin's way out of a stuck "Generating…" (a lost message, a hung call): the
    artifact's active jobs are cancelled and it shows a retryable error. A worker still
    running the job stores nothing (its job is no longer running); a NotebookLM
    artifact already requested is kept, so Retry resumes it instead of spending quota."""
    artifact = _lock_artifact(session, artifact_id)
    if artifact is None:
        raise ValueError(f"artifact {artifact_id} not found")
    if artifact.status is not ArtifactStatus.processing:
        raise NotCancellable(f"artifact is {artifact.status.value}, not generating")
    session.execute(
        update(GenerationJob)
        .where(GenerationJob.artifact_id == artifact.id, GenerationJob.state.in_(ACTIVE_JOB_STATES))
        .values(state=GenerationJobState.cancelled, finished_at=func.now(), error_detail=CANCELLED)
        .execution_options(synchronize_session=False)
    )
    artifact.status = ArtifactStatus.error
    artifact.last_error = CANCELLED
    session.flush()
    _recompute_status(session, artifact.module)
    session.flush()
    log.warning(
        "orchestrator.generation_cancelled",
        artifact_id=str(artifact_id),
        by=str(requested_by) if requested_by else None,
    )
    return artifact


def can_resume(artifact: Artifact) -> bool:
    """NotebookLM already has this artifact's generation (it timed out or failed after
    creation): a Retry polls and fetches it instead of generating it again."""
    return bool(artifact.notebooklm_studio_id) and bool(
        artifact.studio_request or artifact.outline_json
    )


def enqueue_artifact_regeneration(
    session: Session,
    artifact_id: uuid.UUID,
    *,
    redo_note: str | None,
    requested_by: uuid.UUID | None = None,
    options: dict[str, Any] | None = None,
    custom_prompt: str | None | Unset = UNSET,
    resume: bool = False,
) -> GenerationJob:
    """Queue a (re)generation of a single artifact (redo or retry).

    Creates the job row, flips the artifact to `processing`, and recomputes the
    rolled-up status. The caller dispatches `generate_artifact_task` with the
    returned job's `dispatch` payload. `published_version_id` is never touched here. `options`
    (if given) overwrites the artifact's stored `generation_options` for this
    and future generations. `custom_prompt` (if passed) does the same for the
    artifact's focus text; blank or None reverts to the Settings template.
    `resume` keeps the NotebookLM artifact already requested (Retry after a
    timeout); otherwise it is forgotten and a new one is generated.

    Raises `ArtifactBusy` while the artifact is still processing: it has a job
    queued or running, and a second one would generate it twice.
    """
    artifact = _lock_artifact(session, artifact_id)
    if artifact is None:
        raise ValueError(f"artifact {artifact_id} not found")
    if artifact.status is ArtifactStatus.processing:
        raise ArtifactBusy(BUSY_MESSAGE)
    _cancel_lingering_jobs(session, artifact.id)

    if options is not None:
        artifact.generation_options = validate_options(artifact.type, options)
    if not isinstance(custom_prompt, Unset):
        artifact.custom_prompt = _clean_prompt(custom_prompt)
    if not (resume and can_resume(artifact)):
        _forget_studio_job(artifact)

    kind = (
        GenerationJobKind.redo_artifact
        if redo_note is not None
        else GenerationJobKind.generate_artifact
    )
    job = _new_job(artifact, kind, requested_by)
    dispatch_payload(artifact, job, redo_note=redo_note, resume=resume and can_resume(artifact))
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


def request_outline_action(
    session: Session,
    artifact_id: uuid.UUID,
    *,
    feedback: str | None,
    requested_by: uuid.UUID | None = None,
) -> GenerationJob:
    """Act on a drafted slide outline: `feedback` asks NotebookLM to revise it,
    None ("Proceed") builds the deck. Queues a (resuming) job that sends the action
    to NotebookLM and waits for the result: no NotebookLM call (up to minutes behind
    the session lock) runs inside the admin's request or under the row lock. The
    caller dispatches the job's `dispatch` payload."""
    artifact = _lock_artifact(session, artifact_id)
    if artifact is None:
        raise ValueError(f"artifact {artifact_id} not found")
    if artifact.status is not ArtifactStatus.outline_review or not artifact.notebooklm_studio_id:
        raise OutlineNotAwaitingReview(f"artifact is {artifact.status.value}, not outline_review")
    _cancel_lingering_jobs(session, artifact.id)
    job = _new_job(artifact, GenerationJobKind.generate_artifact, requested_by)
    dispatch_payload(artifact, job, resume=True, outline={"feedback": _clean_prompt(feedback)})
    session.add(job)
    artifact.status = ArtifactStatus.processing
    session.flush()
    _recompute_status(session, artifact.module)
    session.flush()
    log.info(
        "orchestrator.outline_action",
        artifact_id=str(artifact_id),
        action="feedback" if feedback else "proceed",
        job_id=str(job.id),
    )
    return job


class OutlineNotAwaitingReview(Exception):
    """The artifact has no slide outline waiting for review."""


# -- generate_module -----------------------------------------------------
def start_module_generation(
    session: Session,
    provider: ContentProvider,
    module_id: uuid.UUID,
    types: Iterable[ArtifactType],
    *,
    requested_by: uuid.UUID | None = None,
    options_by_type: dict[ArtifactType, dict[str, Any]] | None = None,
    prompts_by_type: dict[ArtifactType, str] | None = None,
) -> list[ArtifactJob]:
    """Reset the module's notebook state and enqueue one `generate_artifact` job per
    requested type. Returns the (artifact, job) pairs for the caller to dispatch.
    `options_by_type` (if given) sets each artifact's stored generation
    options; any type not present gets that type's defaults.
    `prompts_by_type` sets each artifact's custom focus text (replacing the
    Settings template); a type not present, or blank, uses the template.
    Passing None for either (Re-run all) keeps what each artifact has stored
    (owner decision 2026-10-22); it is validated when the job runs.
    """
    module = session.get(Module, module_id)
    if module is None:
        raise ValueError(f"module {module_id} not found")
    # Lock the module's artifacts before touching the module (artifact → module order).
    # Re-run all resets the notebook, so no artifact of the module may be mid-generation.
    if any(
        a.status is ArtifactStatus.processing for a in lock_module_artifacts(session, module_id)
    ):
        raise ArtifactBusy(
            "An artifact of this module is still generating. Wait until it finishes or fails, "
            "then try again."
        )

    artifacts = ensure_artifacts(session, module)
    requested = list(dict.fromkeys(types)) or list(ARTIFACT_TYPES)
    # No provider calls here: the background source step (re)builds the
    # notebook and adds the sources. Clearing these makes it start fresh.
    module.notebooklm_notebook_id = None
    module.notebooklm_link_source_id = None
    module.sources_ready_at = None
    module.sources_error = None
    module.sources_failed_at = None
    for sf in module.source_files:
        # reassign (not mutate) so the JSONB column registers the change
        sf.parts = [{**part, "notebooklm_source_id": None} for part in sf.parts]

    jobs: list[ArtifactJob] = []
    for artifact_type in requested:
        artifact = artifacts[artifact_type]
        if options_by_type is not None:
            artifact.generation_options = validate_options(
                artifact_type, options_by_type.get(artifact_type, {})
            )
        elif not artifact.generation_options:
            artifact.generation_options = validate_options(artifact_type, {})
        if prompts_by_type is not None:
            artifact.custom_prompt = _clean_prompt(prompts_by_type.get(artifact_type))
        _cancel_lingering_jobs(session, artifact.id)
        _forget_studio_job(artifact)  # the notebook is rebuilt; its artifacts are gone
        artifact.status = ArtifactStatus.processing
        artifact.last_error = None
        job = _new_job(artifact, GenerationJobKind.generate_artifact, requested_by)
        payload = dispatch_payload(artifact, job)
        session.add(job)
        session.flush()
        jobs.append(
            ArtifactJob(
                artifact_id=artifact.id, job_id=job.id, type=artifact_type, dispatch=payload
            )
        )

    _recompute_status(session, module)
    session.flush()
    log.info("orchestrator.module_started", module_id=str(module_id), jobs=len(jobs))
    return jobs


def lock_module_artifacts(session: Session, module_id: uuid.UUID) -> list[Artifact]:
    """Row-lock (and re-read) every artifact of a module."""
    return list(
        session.scalars(
            select(Artifact)
            .where(Artifact.module_id == module_id)
            .order_by(Artifact.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )


# -- generate_artifact / redo_artifact --------------------------------
class JobSkipped(Exception):
    """This job must not run (or its result must not be stored): it already ran or is
    running elsewhere (a duplicate or redelivered task), it was superseded, or its
    artifact is gone. Nothing was changed; the caller treats it as a no-op."""


@dataclass
class _Plan:
    """What a claimed job needs, read in the claim transaction so the long provider
    work below runs with no transaction (and no row lock) open."""

    artifact_id: uuid.UUID
    job_id: uuid.UUID
    job_created_at: dt.datetime
    module_id: uuid.UUID
    course_id: uuid.UUID
    kind: ArtifactType
    timeout_sec: int
    resume: bool
    redo_note: str | None
    custom_prompt: str | None
    generation_options: dict[str, Any]
    studio_id: str | None
    studio_request: dict[str, Any]
    #: on resuming after an outline action: the outline the admin reviewed
    previous_outline: list[str] | None = None
    #: an outline action to send before waiting ({"feedback": str | None})
    outline: dict[str, Any] | None = None
    created_studio_job: bool = False
    request: dict[str, Any] = field(default_factory=dict)
    #: called whenever the job moves on (the worker's progress watchdog)
    progress: Callable[[], None] = field(default=lambda: None)
    last_check: float = 0.0


def run_artifact_generation(
    session: Session,
    provider: ContentProvider,
    artifact_id: uuid.UUID,
    *,
    job_id: uuid.UUID | None = None,
    redo_note: str | None = None,
    requested_by: uuid.UUID | None = None,
    resume: bool = False,
    retry_transient: bool = False,
    outline: dict[str, Any] | None = None,
    on_progress: Callable[[], None] | None = None,
) -> ArtifactVersion | None:
    """Generate (or, with `resume`, finish a NotebookLM artifact already requested:
    a reviewed slide outline, or a Retry after a timeout) one artifact. Returns the
    new version, or None when NotebookLM drafted a slide outline and is waiting for
    review (the artifact is then `outline_review`).

    Commits as it goes, in short transactions: the claim (job `queued` → `running`,
    under the artifact's row lock), the NotebookLM artifact id once requested, and the
    result. No transaction is open during the source step or NotebookLM's run.

    Raises `JobSkipped` when the job is not `queued` (already finished, or claimed by
    another delivery of the same task), so one job never generates twice. On a
    `TransientProviderError` with `retry_transient`, the job goes back to `queued`
    (the caller's retry claims it again); any other failure marks it failed.

    `outline` (resuming a slide outline): the admin's action, sent to NotebookLM first.
    `on_progress` is called whenever the run moves on; the job's state is re-read
    before generating and while polling, so a job resolved meanwhile (reaped,
    cancelled, module deleted) stops instead of spending quota.
    """
    plan = _claim(session, artifact_id, job_id, redo_note, requested_by, resume)
    plan.outline = outline
    if on_progress is not None:
        plan.progress = on_progress
    try:
        return _generate(session, provider, plan)
    except JobSkipped:
        raise
    except Exception as exc:
        if not _record_failure(session, plan, exc, retry_transient=retry_transient):
            # resolved meanwhile (reaper, or the module was deleted): nothing to report
            raise JobSkipped(f"job {plan.job_id} was resolved while it ran: {exc}") from exc
        raise


def _claim(
    session: Session,
    artifact_id: uuid.UUID,
    job_id: uuid.UUID | None,
    redo_note: str | None,
    requested_by: uuid.UUID | None,
    resume: bool,
) -> _Plan:
    artifact = _lock_artifact(session, artifact_id)
    if artifact is None:
        session.rollback()
        raise JobSkipped(f"artifact {artifact_id} no longer exists")
    job = _resolve_job(session, artifact, job_id, redo_note, requested_by)
    if job is None or job.state is not GenerationJobState.queued:
        state = "missing" if job is None else job.state.value
        session.rollback()
        raise JobSkipped(f"job {job_id} is {state}, not queued")

    job.state = GenerationJobState.running
    job.started_at = func.now()
    job.heartbeat_at = func.now()
    job.attempts += 1
    artifact.status = ArtifactStatus.processing
    artifact.last_error = None
    if not resume:
        _forget_studio_job(artifact)
    pending = dict(artifact.studio_request or artifact.outline_json or {})
    previous = (artifact.outline_json or {}).get("slides") if resume else None
    session.flush()
    plan = _Plan(
        artifact_id=artifact.id,
        job_id=job.id,
        job_created_at=job.created_at,
        module_id=artifact.module_id,
        course_id=artifact.module.course_id,
        kind=artifact.type,
        timeout_sec=settings_timeout(artifact),
        resume=resume,
        redo_note=redo_note,
        custom_prompt=artifact.custom_prompt,
        generation_options=dict(artifact.generation_options or {}),
        studio_id=artifact.notebooklm_studio_id,
        studio_request=pending,
        previous_outline=[str(x) for x in previous] if isinstance(previous, list) else None,
    )
    session.commit()
    log.info("orchestrator.job_claimed", artifact_id=str(artifact_id), job_id=str(job.id))
    return plan


def _record_failure(
    session: Session, plan: _Plan, exc: Exception, *, retry_transient: bool
) -> bool:
    """Persist a failed run (short transaction); False when the job was resolved
    meanwhile (nothing written)."""
    session.rollback()  # drop anything half-written (e.g. a version whose media failed)
    artifact = _lock_artifact(session, plan.artifact_id)
    job = session.get(GenerationJob, plan.job_id, with_for_update=True, populate_existing=True)
    if artifact is None or job is None or job.state is not GenerationJobState.running:
        session.rollback()
        return False
    if retry_transient and isinstance(exc, TransientProviderError) and not plan.created_studio_job:
        # Celery retries this job: back to queued so the retry can claim it.
        job.state = GenerationJobState.queued
        job.heartbeat_at = func.now()
        session.commit()
        log.info("orchestrator.job_requeued", job_id=str(plan.job_id), error=str(exc))
        return True

    # The source step's messages are written for admins (spec §8): show as-is.
    if isinstance(exc, SourceStepError):
        message = str(exc)
    elif isinstance(exc, SoftTimeLimitExceeded):
        message = TIME_LIMIT
    elif isinstance(exc, ArtifactParseError):
        message = f"{type(exc).__name__}: {exc}. {PARSE_RETRY_HINT}"
    else:
        message = f"{type(exc).__name__}: {exc}"
    artifact.status = ArtifactStatus.error
    artifact.last_error = message
    if isinstance(exc, StudioGenerationFailed | ArtifactParseError) or (
        plan.resume and plan.previous_outline is None and isinstance(exc, GenerationTimeout)
    ):
        # NotebookLM's artifact failed, its output can't be read (fetching it again
        # gives the same result: owner decision 2026-10-29, Retry regenerates), or
        # resuming it timed out again: a Retry must generate a new one.
        _forget_studio_job(artifact)
    job.state = GenerationJobState.failed
    job.error_detail = message
    job.finished_at = func.now()
    _recompute_status(session, artifact.module)
    session.commit()
    log.warning(
        "orchestrator.artifact_failed",
        artifact_id=str(plan.artifact_id),
        type=plan.kind.value,
        error=message,
    )
    return True


TIME_LIMIT = "Generation took too long and was stopped. Press Retry."
PARSE_RETRY_HINT = "Press Retry to generate it again"
#: how often a run re-reads its job's state while it waits on NotebookLM
_STATE_CHECK_SEC = 60.0


def _check_still_running(session: Session, plan: _Plan, *, force: bool = False) -> None:
    """`JobSkipped` when the job is no longer running (the reaper failed it, an admin
    cancelled it, the module was deleted): a run that lost its job must not generate
    (a second NotebookLM artifact, quota) or keep a worker slot polling. One cheap
    read, at most every `_STATE_CHECK_SEC` unless `force`."""
    now = time.monotonic()
    if not force and now - plan.last_check < _STATE_CHECK_SEC:
        return
    plan.last_check = now
    state = session.scalar(select(GenerationJob.state).where(GenerationJob.id == plan.job_id))
    session.commit()
    if state is not GenerationJobState.running:
        log.warning("orchestrator.job_gone", job_id=str(plan.job_id), state=str(state))
        raise JobSkipped(f"job {plan.job_id} is {state}, no longer running")


def _lock_running(session: Session, plan: _Plan) -> tuple[Artifact, GenerationJob]:
    """Re-lock the artifact and job to store a result; `JobSkipped` if the job is no
    longer running (the reaper failed it, or the module was deleted) — the result is
    then dropped, and the NotebookLM id kept for Retry stays on the artifact."""
    artifact = _lock_artifact(session, plan.artifact_id)
    job = session.get(GenerationJob, plan.job_id, with_for_update=True, populate_existing=True)
    if artifact is None or job is None or job.state is not GenerationJobState.running:
        session.rollback()
        log.warning("orchestrator.result_dropped", job_id=str(plan.job_id))
        raise JobSkipped(f"job {plan.job_id} was resolved while it ran; result not stored")
    return artifact, job


def _remember_studio_job(session: Session, plan: _Plan, studio_id: str) -> None:
    """Commit NotebookLM's artifact id straight away, so a Retry after a timeout or a
    later failure resumes it (no second generation, no quota spent)."""
    plan.created_studio_job = True
    artifact = _lock_artifact(session, plan.artifact_id)
    latest = session.scalar(
        select(GenerationJob.id)
        .where(GenerationJob.artifact_id == plan.artifact_id)
        .order_by(GenerationJob.created_at.desc(), GenerationJob.id.desc())
        .limit(1)
    )
    if artifact is not None and latest == plan.job_id:
        artifact.notebooklm_studio_id = studio_id
        artifact.studio_request = plan.request
    session.commit()


def touch_job_heartbeat(session: Session, job_id: uuid.UUID) -> None:
    """The worker running `job_id` is alive (the reaper fails jobs whose heartbeat stops)."""
    session.execute(
        update(GenerationJob)
        .where(GenerationJob.id == job_id, GenerationJob.state == GenerationJobState.running)
        .values(heartbeat_at=func.now())
        .execution_options(synchronize_session=False)
    )
    session.commit()


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
) -> GenerationJob | None:
    if job_id is not None:
        job = session.get(GenerationJob, job_id, with_for_update=True, populate_existing=True)
        return job if job is not None and job.artifact_id == artifact.id else None
    # No job given (CLI, tests): run the artifact's queued job, else a new one.
    active = session.scalar(
        select(GenerationJob)
        .where(
            GenerationJob.artifact_id == artifact.id,
            GenerationJob.state.in_(ACTIVE_JOB_STATES),
        )
        .with_for_update()
    )
    if active is not None:
        return active
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


def _prepare_request(session: Session, plan: _Plan) -> dict[str, Any]:
    """(Short transaction) the focus prompt and options for a new generation. A
    custom prompt replaces the template entirely, so no template version is
    recorded for it (Inspect shows "Custom prompt")."""
    template = None if plan.custom_prompt else get_active_template(session, plan.kind)
    base_body = plan.custom_prompt or get_active_body(session, plan.kind)
    focus_prompt = base_body
    if plan.redo_note:
        focus_prompt = (
            f"{base_body}\n\nAdditional instruction for this revision:\n{plan.redo_note.strip()}"
        )
    session.commit()  # get_active_body may self-heal a missing template
    return {
        "focus_prompt": focus_prompt,
        "redo_note": plan.redo_note,
        "template_id": str(template.id) if template else None,
        "template_version": template.version if template else None,
    }


def _generate(session: Session, provider: ContentProvider, plan: _Plan) -> ArtifactVersion | None:
    if plan.resume:
        # Finishing a NotebookLM artifact already requested: reuse what was sent.
        if not plan.studio_id:
            raise ProviderError("no NotebookLM artifact to resume for this artifact")
        plan.request = {
            "focus_prompt": str(plan.studio_request.get("focus_prompt") or ""),
            "redo_note": plan.studio_request.get("redo_note"),
            "template_id": plan.studio_request.get("template_id"),
            "template_version": plan.studio_request.get("template_version"),
        }
        options: dict[str, Any] = {}  # nothing is sent
    else:
        plan.request = _prepare_request(session, plan)
        # Stored options may predate a schema change: fill defaults, reject what
        # NotebookLM doesn't offer, before anything is sent.
        options = validate_options(plan.kind, plan.generation_options)

    plan.progress()
    # Once per module: the notebook with the module's link and PDFs, all ready.
    # It commits in its own session; no transaction of ours is open from here on.
    nb = ensure_module_sources(
        provider, plan.module_id, job_created_at=plan.job_created_at, on_progress=plan.progress
    )
    plan.progress()
    _check_still_running(session, plan, force=True)

    if plan.resume:
        assert plan.studio_id is not None
        studio_job = StudioJobRef(job_id=plan.studio_id, notebook_id=nb.notebook_id, kind=plan.kind)
        if plan.outline is not None:
            # The admin's outline action, sent here rather than in their request.
            provider.outline_action(studio_job, plan.outline.get("feedback"))
            plan.created_studio_job = True  # from here on, never requeue (no resend)
    else:
        studio_job = provider.generate(nb, plan.kind, plan.request["focus_prompt"], options)
        _remember_studio_job(session, plan, studio_job.job_id)
    plan.progress()

    def on_poll() -> None:
        plan.progress()
        _check_still_running(session, plan)

    # From here on NotebookLM has the artifact: a transient error must not fail
    # the task, or Celery's retry would generate it a second time.
    status = _await_terminal(
        provider,
        studio_job,
        plan.timeout_sec,
        previous_outline=plan.previous_outline,
        on_poll=on_poll,
    )
    raw = _without_transient_failures(lambda: provider.fetch_content(studio_job))
    plan.progress()

    if status is StudioStatus.awaiting_review:
        outline = parse_outline(raw.extras.get("row") or [])
        artifact, job = _lock_running(session, plan)
        artifact.outline_json = {**outline, **plan.request}
        artifact.notebooklm_studio_id = studio_job.job_id
        artifact.studio_request = plan.request
        artifact.status = ArtifactStatus.outline_review
        artifact.last_error = None
        job.state = GenerationJobState.succeeded
        job.finished_at = func.now()
        _recompute_status(session, artifact.module)
        session.commit()
        log.info("orchestrator.outline_review", artifact_id=str(plan.artifact_id))
        return None

    # Parse and fetch everything (no transaction open) before a version exists.
    content_json, blobs, content_html = _content_and_media(
        provider, plan.kind, raw, studio_job, on_progress=plan.progress
    )
    return _store_version(session, plan, raw, content_json, content_html, blobs)


def _store_version(
    session: Session,
    plan: _Plan,
    raw: RawArtifact,
    content_json: dict[str, Any],
    content_html: str | None,
    blobs: list[MediaBlob],
) -> ArtifactVersion:
    """(Short transaction) the new version, its media and the artifact's state. A
    failure leaves no half-stored revision: the rows roll back and files already
    written are deleted."""
    artifact, job = _lock_running(session, plan)
    revision = (
        session.scalar(
            select(func.coalesce(func.max(ArtifactVersion.revision), 0)).where(
                ArtifactVersion.artifact_id == artifact.id
            )
        )
        or 0
    ) + 1
    template_id = plan.request.get("template_id")
    version = ArtifactVersion(
        artifact_id=artifact.id,
        revision=revision,
        generation_job_id=job.id,
        prompt_template_id=uuid.UUID(template_id) if template_id else None,
        prompt_template_version=plan.request.get("template_version"),
        focus_prompt_used=plan.request["focus_prompt"],
        redo_note=plan.request.get("redo_note"),
        content_json=content_json,
        content_html=content_html,
        notebooklm_artifact_id=str(raw.extras.get("artifact_id") or "") or None,
    )
    session.add(version)
    session.flush()

    written: list[str] = []
    try:
        _store_media(session, plan, version, blobs, written)
        artifact.current_version_id = version.id
        artifact.status = ArtifactStatus.ready
        artifact.last_error = None
        _forget_studio_job(artifact)
        job.state = GenerationJobState.succeeded
        job.finished_at = func.now()
        _recompute_status(session, artifact.module)
        session.commit()
    except BaseException:
        session.rollback()
        _delete_files(written)
        raise
    log.info(
        "orchestrator.artifact_ready",
        artifact_id=str(plan.artifact_id),
        type=plan.kind.value,
        revision=version.revision,
        course=str(plan.course_id),
    )
    return version


def _delete_files(keys: list[str]) -> None:
    storage = get_storage()
    for key in keys:
        try:
            storage.delete(key)
        except (OSError, ValueError) as exc:  # pragma: no cover - best effort
            log.warning("orchestrator.media_not_deleted", key=key, error=str(exc))


_MEDIA_MIME: dict[MediaFileKind, str] = {
    MediaFileKind.slide_png: "image/png",
    MediaFileKind.deck_pdf: "application/pdf",
    MediaFileKind.pptx: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    MediaFileKind.infographic_png: "image/png",
    MediaFileKind.audio_m4a: "audio/mp4",
}


def _content_and_media(
    provider: ContentProvider,
    kind: ArtifactType,
    raw: RawArtifact,
    studio_job: StudioJobRef,
    *,
    on_progress: Callable[[], None] = lambda: None,
) -> tuple[dict[str, object], list[MediaBlob], str | None]:
    """(content_json, media to store, content_html) for a finished artifact."""
    if raw.extras.get("source") != "notebooklm":
        # FixtureProvider: Studio-style HTML, rendered by us.
        content_json = parse_artifact(kind, raw.html, raw.extras)
        blobs = RENDERERS[kind](content_json, provider, studio_job)
        return content_json, blobs, _report_html(kind, content_json) or raw.html

    row = raw.extras.get("row") or []
    if kind is ArtifactType.audio_overview:
        url = audio_url(row)
        data, _ = _without_transient_failures(lambda: provider.download(url))
        seconds = mp4_duration_seconds(data)
        if not seconds:
            # deterministic (the same file every time): Retry generates a new one
            raise ArtifactParseError("audio overview: NotebookLM's download is not a readable MP4")
        content = AudioOverviewContent(duration_seconds=max(1, round(seconds)))
        blob = MediaBlob(kind=MediaFileKind.audio_m4a, data=data, mime="audio/mp4")
        return content.model_dump(mode="json"), [blob], None

    parsed = parse_notebooklm(kind, row, raw.html)

    def fetch(url: str) -> bytes:
        data = _without_transient_failures(lambda: provider.download(url))[0]
        on_progress()
        return data

    blobs = [
        MediaBlob(
            kind=ref.kind,
            data=fetch(ref.url),
            mime=_MEDIA_MIME[ref.kind],
            page_index=ref.page_index,
        )
        for ref in parsed.media
    ]
    # NotebookLM gives a report as text only; its HTML is ours (T020).
    return parsed.content, blobs, _report_html(kind, parsed.content)


def _report_html(kind: ArtifactType, content_json: dict[str, Any]) -> str | None:
    """The report's sanitised on-screen HTML (`content_html`); None for other types."""
    if kind is not ArtifactType.report:
        return None
    return build_report_html(ReportContent.model_validate(content_json))


class StudioGenerationFailed(RenderError):
    """NotebookLM reported the generation failed: Retry must generate a new one."""


#: After an outline action, NotebookLM may still report the old outline for a moment
#: (the spike didn't observe Refine take effect at once): wait this long for the
#: status or the outline to change before accepting "awaiting review" again.
_OUTLINE_SETTLE_SEC = 120.0
#: NotebookLM may not list a brand-new artifact straight away; "missing" for longer
#: than this means it is gone (deleted, or its notebook was)
_MISSING_GRACE_SEC = 60.0


def _await_terminal(
    provider: ContentProvider,
    job: StudioJobRef,
    timeout_sec: int,
    *,
    previous_outline: list[str] | None = None,
    on_poll: Callable[[], None] = lambda: None,
) -> StudioStatus:
    """Poll until ready or awaiting outline review; raise on failure/timeout.

    `previous_outline`: resuming after an outline action. "Awaiting review" then
    counts only once NotebookLM has moved on: the status changed in between, the
    outline differs, or `_OUTLINE_SETTLE_SEC` passed."""
    start = time.monotonic()
    deadline = start + timeout_sec
    moved_on = previous_outline is None
    missing_since: float | None = None
    while True:
        try:
            status = provider.poll(job)
        except TransientProviderError as exc:
            # e.g. the session lock is busy: keep waiting within the deadline
            log.info("orchestrator.poll_retry", job=job.job_id, error=str(exc))
            status = StudioStatus.pending
        on_poll()
        if status is StudioStatus.missing:
            now = time.monotonic()
            missing_since = now if missing_since is None else missing_since
            if now - missing_since >= _MISSING_GRACE_SEC:
                raise StudioGenerationFailed(
                    "NotebookLM no longer has this artifact (deleted, or its notebook is gone)"
                )
            status = StudioStatus.pending
        else:
            missing_since = None
        if status is StudioStatus.awaiting_review and not moved_on:
            moved_on = time.monotonic() - start >= _OUTLINE_SETTLE_SEC or _current_outline(
                provider, job
            ) not in (None, previous_outline)
            if not moved_on:
                status = StudioStatus.pending
        elif status is not StudioStatus.awaiting_review:
            moved_on = True
        if status in (StudioStatus.ready, StudioStatus.awaiting_review):
            return status
        if status is StudioStatus.failed:
            raise StudioGenerationFailed("Studio reported the generation failed")
        if time.monotonic() > deadline:
            raise GenerationTimeout(f"generation exceeded {timeout_sec}s")
        time.sleep(_POLL_INTERVAL_SEC)


def _current_outline(provider: ContentProvider, job: StudioJobRef) -> list[str] | None:
    try:
        row = provider.fetch_content(job).extras.get("row") or []
        slides = parse_outline(row).get("slides")
    except (ProviderError, ArtifactParseError):
        return None
    return [str(x) for x in slides] if isinstance(slides, list) else None


_TRANSIENT_ATTEMPTS = 4


def _without_transient_failures(call: Callable[[], T]) -> T:
    """Retry a post-creation provider call in place on transient errors."""
    for attempt in range(1, _TRANSIENT_ATTEMPTS + 1):
        try:
            return call()
        except TransientProviderError as exc:
            if attempt == _TRANSIENT_ATTEMPTS:
                # Out of attempts: fail permanently rather than let the task
                # retry, which would generate the artifact again.
                raise ProviderError(f"gave up after {attempt} attempts: {exc}") from exc
            log.info("orchestrator.transient_retry", attempt=attempt, error=str(exc))
            time.sleep(_POLL_INTERVAL_SEC * attempt)
    raise AssertionError("unreachable")


def _store_media(
    session: Session,
    plan: _Plan,
    version: ArtifactVersion,
    blobs: list[MediaBlob],
    written: list[str],
) -> None:
    """Write each blob and its MediaFile row; `written` collects the keys stored so
    the caller can delete them if anything later fails."""
    if not blobs:
        return
    storage = get_storage()
    for blob in blobs:
        key = media_key(
            course_id=plan.course_id,
            module_id=plan.module_id,
            artifact_id=plan.artifact_id,
            revision=version.revision,
            kind=blob.kind,
            ext=STORAGE_EXTS[blob.kind],
            page_index=blob.page_index,
        )
        stored = storage.put(key, blob.data, blob.mime)
        written.append(key)
        session.add(
            storage.build_media_file(
                stored,
                artifact_version_id=str(version.id),
                kind=blob.kind,
                page_index=blob.page_index,
            )
        )
    session.flush()


def _recompute_status(session: Session, module: Module) -> None:
    # row-locks module then course before reading children (no lost update)
    recompute_status(session, module)
