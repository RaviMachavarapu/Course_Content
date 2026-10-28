"""Generation orchestration (plan.md §4.3).

Pure, synchronous functions the Celery tasks (`app/tasks/generation.py`) call
inside a session. No Celery imports here so the whole flow is unit-testable
against `FixtureProvider`.
"""

from __future__ import annotations

import enum
import time
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, TypeVar

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
    MediaFileKind,
)
from app.models.generation_job import GenerationJob
from app.models.module import Module
from app.pipeline.media_probe import mp4_duration_seconds
from app.pipeline.module_sources import SourceStepError, ensure_module_sources
from app.pipeline.parsers import parse_artifact
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


@dataclass(frozen=True)
class ArtifactJob:
    artifact_id: uuid.UUID
    job_id: uuid.UUID
    type: ArtifactType


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


def enqueue_artifact_regeneration(
    session: Session,
    artifact_id: uuid.UUID,
    *,
    redo_note: str | None,
    requested_by: uuid.UUID | None = None,
    options: dict[str, Any] | None = None,
    custom_prompt: str | None | Unset = UNSET,
) -> GenerationJob:
    """Queue a (re)generation of a single artifact (redo or retry).

    Creates the job row, flips the artifact to `processing`, and recomputes the
    rolled-up status. The caller dispatches `generate_artifact_task` with the
    returned job id. `published_version_id` is never touched here. `options`
    (if given) overwrites the artifact's stored `generation_options` for this
    and future generations. `custom_prompt` (if passed) does the same for the
    artifact's focus text; blank or None reverts to the Settings template.
    """
    artifact = session.get(Artifact, artifact_id)
    if artifact is None:
        raise ValueError(f"artifact {artifact_id} not found")

    if options is not None:
        artifact.generation_options = validate_options(artifact.type, options)
    if not isinstance(custom_prompt, Unset):
        artifact.custom_prompt = _clean_prompt(custom_prompt)

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


def request_outline_action(
    session: Session,
    provider: ContentProvider,
    artifact_id: uuid.UUID,
    *,
    feedback: str | None,
    requested_by: uuid.UUID | None = None,
) -> GenerationJob:
    """Act on a drafted slide outline: `feedback` asks NotebookLM to revise it,
    None ("Proceed") builds the deck. Queues a job that waits for the result;
    the caller dispatches `generate_artifact_task` with `resume=True`."""
    artifact = session.get(Artifact, artifact_id)
    if artifact is None:
        raise ValueError(f"artifact {artifact_id} not found")
    if artifact.status is not ArtifactStatus.outline_review or not artifact.notebooklm_studio_id:
        raise OutlineNotAwaitingReview(f"artifact is {artifact.status.value}, not outline_review")
    nb_id = artifact.module.notebooklm_notebook_id or ""
    provider.outline_action(
        StudioJobRef(job_id=artifact.notebooklm_studio_id, notebook_id=nb_id, kind=artifact.type),
        _clean_prompt(feedback),
    )
    job = GenerationJob(
        kind=GenerationJobKind.generate_artifact,
        module_id=artifact.module_id,
        artifact_id=artifact.id,
        state=GenerationJobState.queued,
        requested_by=requested_by,
    )
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
    resume: bool = False,
) -> ArtifactVersion | None:
    """Generate (or, with `resume`, finish an outline-reviewed slide deck) one
    artifact. Returns the new version, or None when NotebookLM drafted a slide
    outline and is waiting for review (the artifact is then `outline_review`).
    """
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
        version = _generate(
            session, provider, artifact, job, redo_note, settings_timeout(artifact), resume=resume
        )
    except Exception as exc:
        artifact.status = ArtifactStatus.error
        # The source step's messages are written for admins (spec §8): show as-is.
        artifact.last_error = (
            str(exc) if isinstance(exc, SourceStepError) else f"{type(exc).__name__}: {exc}"
        )
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

    if version is None:
        artifact.status = ArtifactStatus.outline_review
        artifact.last_error = None
        job.state = GenerationJobState.succeeded
        job.finished_at = func.now()
        _recompute_status(session, module)
        session.flush()
        log.info("orchestrator.outline_review", artifact_id=str(artifact_id))
        return None

    artifact.current_version_id = version.id
    artifact.status = ArtifactStatus.ready
    artifact.last_error = None
    artifact.outline_json = None
    artifact.notebooklm_studio_id = None
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
    *,
    resume: bool = False,
) -> ArtifactVersion | None:
    module = artifact.module
    # Once per module: the notebook with the module's link and PDFs, all ready.
    # It commits in its own session, so pick up what it wrote.
    nb = ensure_module_sources(provider, module.id, job_created_at=job.created_at)
    session.refresh(module)

    if resume:
        # Finishing a reviewed outline: reuse what the original request sent.
        pending = artifact.outline_json or {}
        if not artifact.notebooklm_studio_id:
            raise ProviderError("no NotebookLM outline to resume for this artifact")
        studio_job = StudioJobRef(
            job_id=artifact.notebooklm_studio_id, notebook_id=nb.notebook_id, kind=artifact.type
        )
        focus_prompt = str(pending.get("focus_prompt") or "")
        redo_note = pending.get("redo_note")
        template_id = pending.get("template_id")
        template_version = pending.get("template_version")
    else:
        # A custom prompt replaces the template entirely, so no template version
        # is recorded for it (Inspect shows "Custom prompt").
        template = None if artifact.custom_prompt else get_active_template(session, artifact.type)
        base_body = artifact.custom_prompt or get_active_body(session, artifact.type)
        focus_prompt = base_body
        if redo_note:
            focus_prompt = (
                f"{base_body}\n\nAdditional instruction for this revision:\n{redo_note.strip()}"
            )
        template_id = str(template.id) if template else None
        template_version = template.version if template else None
        # Stored options may predate a schema change: fill defaults, reject what
        # NotebookLM doesn't offer, before anything is sent.
        options = validate_options(artifact.type, artifact.generation_options or {})
        studio_job = provider.generate(nb, artifact.type, focus_prompt, options)

    # From here on NotebookLM has the artifact: a transient error must not fail
    # the task, or Celery's retry would generate it a second time.
    status = _await_terminal(provider, studio_job, timeout_sec)
    raw = _without_transient_failures(lambda: provider.fetch_content(studio_job))

    if status is StudioStatus.awaiting_review:
        artifact.outline_json = {
            **parse_outline(raw.extras.get("row") or []),
            "focus_prompt": focus_prompt,
            "redo_note": redo_note,
            "template_id": template_id,
            "template_version": template_version,
        }
        artifact.notebooklm_studio_id = studio_job.job_id
        session.flush()
        return None

    # Parse and fetch everything before a version exists, so a failure leaves
    # no half-stored revision behind.
    content_json, blobs, content_html = _content_and_media(provider, artifact.type, raw, studio_job)

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
        prompt_template_id=uuid.UUID(template_id) if template_id else None,
        prompt_template_version=template_version,
        focus_prompt_used=focus_prompt,
        redo_note=redo_note,
        content_json=content_json,
        content_html=content_html,
        notebooklm_artifact_id=str(raw.extras.get("artifact_id") or "") or None,
    )
    session.add(version)
    session.flush()

    _store_media(session, artifact, version, blobs)
    return version


_MEDIA_MIME: dict[MediaFileKind, str] = {
    MediaFileKind.slide_png: "image/png",
    MediaFileKind.deck_pdf: "application/pdf",
    MediaFileKind.pptx: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    MediaFileKind.infographic_png: "image/png",
    MediaFileKind.audio_m4a: "audio/mp4",
}


def _content_and_media(
    provider: ContentProvider, kind: ArtifactType, raw: RawArtifact, studio_job: StudioJobRef
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
            raise RenderError("audio overview: NotebookLM's download is not a readable MP4")
        content = AudioOverviewContent(duration_seconds=max(1, round(seconds)))
        blob = MediaBlob(kind=MediaFileKind.audio_m4a, data=data, mime="audio/mp4")
        return content.model_dump(mode="json"), [blob], None

    parsed = parse_notebooklm(kind, row, raw.html)

    def fetch(url: str) -> bytes:
        return _without_transient_failures(lambda: provider.download(url))[0]

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


def _await_terminal(provider: ContentProvider, job: StudioJobRef, timeout_sec: int) -> StudioStatus:
    """Poll until ready or awaiting outline review; raise on failure/timeout."""
    deadline = time.monotonic() + timeout_sec
    while True:
        try:
            status = provider.poll(job)
        except TransientProviderError as exc:
            # e.g. the session lock is busy: keep waiting within the deadline
            log.info("orchestrator.poll_retry", job=job.job_id, error=str(exc))
            status = StudioStatus.pending
        if status in (StudioStatus.ready, StudioStatus.awaiting_review):
            return status
        if status is StudioStatus.failed:
            raise RenderError("Studio reported the generation failed")
        if time.monotonic() > deadline:
            raise GenerationTimeout(f"generation exceeded {timeout_sec}s")
        time.sleep(_POLL_INTERVAL_SEC)


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
    artifact: Artifact,
    version: ArtifactVersion,
    blobs: list[MediaBlob],
) -> None:
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
    session.flush()


def _recompute_status(session: Session, module: Module) -> None:
    # row-locks module then course before reading children (no lost update)
    recompute_status(session, module)
