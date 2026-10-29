"""Review 2026-10-28 (batch C): one generation per artifact, short transactions,
resumable NotebookLM artifacts, no half-stored versions, and the stale-job reaper."""

from __future__ import annotations

import datetime as dt
import functools
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import pytest
import redis
from sqlalchemy import Engine, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.models.artifact import Artifact
from app.models.artifact_version import ArtifactVersion
from app.models.course import Course
from app.models.enums import (
    ArtifactStatus,
    ArtifactType,
    GenerationJobKind,
    GenerationJobState,
    ModuleSourceType,
)
from app.models.generation_job import GenerationJob
from app.models.module import Module
from app.pipeline import module_sources, orchestrator, reaper
from app.pipeline.fixture import FixtureProvider
from app.pipeline.provider import (
    GenerationTimeout,
    RawArtifact,
    StudioJobRef,
    StudioStatus,
    TransientProviderError,
)
from app.storage.service import Storage

HOUR = dt.timedelta(hours=1)


class Provider(FixtureProvider):
    """FixtureProvider with hooks and call counts."""

    def __init__(self) -> None:
        super().__init__()
        self.generated = 0
        self.on_generate: Callable[[], None] | None = None
        self.on_poll: Callable[[], None] | None = None
        self.statuses: list[StudioStatus] = []

    def generate(self, nb: Any, kind: ArtifactType, focus: str, options: Any) -> StudioJobRef:
        self.generated += 1
        if self.on_generate:
            self.on_generate()
        return super().generate(nb, kind, focus, options)

    def poll(self, job: StudioJobRef) -> StudioStatus:
        if self.on_poll:
            self.on_poll()
        return self.statuses.pop(0) if self.statuses else StudioStatus.ready


def _module(db: Session) -> Module:
    course = Course(title="C", slug=f"c-{uuid.uuid4()}")
    module = Module(
        course=course,
        order_index=0,
        title="M",
        source_url="https://youtu.be/x",
        source_type=ModuleSourceType.youtube,
    )
    db.add(module)
    db.flush()
    return module


def _queued(db: Session, kind: ArtifactType = ArtifactType.report) -> tuple[Artifact, uuid.UUID]:
    module = _module(db)
    jobs = orchestrator.start_module_generation(db, FixtureProvider(), module.id, [kind])
    db.flush()
    artifact = db.get(Artifact, jobs[0].artifact_id)
    assert artifact is not None
    return artifact, jobs[0].job_id


def _job(db: Session, job_id: uuid.UUID) -> GenerationJob:
    db.expire_all()
    job = db.get(GenerationJob, job_id)
    assert job is not None
    return job


# -- duplicate runs ------------------------------------------------------------------------
def test_a_second_delivery_while_the_first_runs_does_nothing(db_session: Session) -> None:
    artifact, job_id = _queued(db_session)
    provider = Provider()
    inner: list[BaseException] = []

    def second_delivery() -> None:
        try:
            orchestrator.run_artifact_generation(db_session, provider, artifact.id, job_id=job_id)
        except BaseException as exc:  # recorded for the assert
            inner.append(exc)

    provider.on_generate = second_delivery
    version = orchestrator.run_artifact_generation(db_session, provider, artifact.id, job_id=job_id)

    assert version is not None
    assert provider.generated == 1
    assert len(inner) == 1 and isinstance(inner[0], orchestrator.JobSkipped)
    assert _job(db_session, job_id).state is GenerationJobState.succeeded


@pytest.mark.parametrize("state", [GenerationJobState.succeeded, GenerationJobState.failed])
def test_a_redelivered_message_for_a_finished_job_is_a_no_op(
    db_session: Session, state: GenerationJobState
) -> None:
    artifact, job_id = _queued(db_session)
    orchestrator.run_artifact_generation(db_session, FixtureProvider(), artifact.id, job_id=job_id)
    job = _job(db_session, job_id)
    job.state = state
    db_session.flush()
    revisions = db_session.scalar(
        select(func.count()).where(ArtifactVersion.artifact_id == artifact.id)
    )

    provider = Provider()
    with pytest.raises(orchestrator.JobSkipped):
        orchestrator.run_artifact_generation(db_session, provider, artifact.id, job_id=job_id)
    assert provider.generated == 0
    assert (
        db_session.scalar(select(func.count()).where(ArtifactVersion.artifact_id == artifact.id))
        == revisions
    )


def test_at_most_one_active_job_per_artifact(db_session: Session) -> None:
    artifact, _ = _queued(db_session)
    db_session.add(
        GenerationJob(
            kind=GenerationJobKind.generate_artifact,
            module_id=artifact.module_id,
            artifact_id=artifact.id,
            state=GenerationJobState.queued,
        )
    )
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.flush()


def test_a_lingering_active_job_is_cancelled_by_a_new_request(db_session: Session) -> None:
    artifact, job_id = _queued(db_session)
    artifact.status = ArtifactStatus.error  # e.g. an older bug left the job queued
    db_session.flush()
    new = orchestrator.enqueue_artifact_regeneration(db_session, artifact.id, redo_note=None)
    assert _job(db_session, job_id).state is GenerationJobState.cancelled
    assert _job(db_session, new.id).state is GenerationJobState.queued


# -- transient errors ----------------------------------------------------------------------
def test_a_transient_error_with_retries_left_requeues_the_job(db_session: Session) -> None:
    artifact, job_id = _queued(db_session)
    provider = Provider()

    def busy() -> None:
        raise TransientProviderError("lock busy")

    provider.on_generate = busy
    with pytest.raises(TransientProviderError):
        orchestrator.run_artifact_generation(
            db_session, provider, artifact.id, job_id=job_id, retry_transient=True
        )
    assert _job(db_session, job_id).state is GenerationJobState.queued
    assert db_session.get(Artifact, artifact.id).status is ArtifactStatus.processing

    provider.on_generate = None  # Celery's retry claims it again
    assert orchestrator.run_artifact_generation(
        db_session, provider, artifact.id, job_id=job_id, retry_transient=True
    )
    assert _job(db_session, job_id).attempts == 2


def test_a_transient_error_on_the_last_retry_fails_the_job(db_session: Session) -> None:
    artifact, job_id = _queued(db_session)
    provider = Provider()

    def busy() -> None:
        raise TransientProviderError("lock busy")

    provider.on_generate = busy
    with pytest.raises(TransientProviderError):
        orchestrator.run_artifact_generation(db_session, provider, artifact.id, job_id=job_id)
    assert _job(db_session, job_id).state is GenerationJobState.failed
    assert db_session.get(Artifact, artifact.id).status is ArtifactStatus.error


# -- resume instead of regenerating ----------------------------------------------------------
def test_a_timeout_keeps_the_notebooklm_artifact_and_retry_resumes_it(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(orchestrator, "_POLL_INTERVAL_SEC", 0)
    monkeypatch.setattr(orchestrator, "settings_timeout", lambda _a: 0)
    artifact, job_id = _queued(db_session)
    provider = Provider()
    provider.statuses = [StudioStatus.pending]
    with pytest.raises(GenerationTimeout):
        orchestrator.run_artifact_generation(db_session, provider, artifact.id, job_id=job_id)
    db_session.expire_all()
    artifact = db_session.get(Artifact, artifact.id)
    assert artifact.status is ArtifactStatus.error
    assert artifact.notebooklm_studio_id
    assert artifact.studio_request and artifact.studio_request["focus_prompt"]
    assert orchestrator.can_resume(artifact)
    sent_prompt = artifact.studio_request["focus_prompt"]

    job = orchestrator.enqueue_artifact_regeneration(
        db_session, artifact.id, redo_note=None, resume=True
    )
    version = orchestrator.run_artifact_generation(
        db_session, provider, artifact.id, job_id=job.id, resume=True
    )
    assert version is not None
    assert provider.generated == 1  # resumed, not generated again
    assert version.focus_prompt_used == sent_prompt
    db_session.expire_all()
    done = db_session.get(Artifact, artifact.id)
    assert done.notebooklm_studio_id is None and done.studio_request is None


def test_a_failed_notebooklm_generation_is_not_resumed(db_session: Session) -> None:
    artifact, job_id = _queued(db_session)
    provider = Provider()
    provider.statuses = [StudioStatus.failed]
    with pytest.raises(orchestrator.StudioGenerationFailed):
        orchestrator.run_artifact_generation(db_session, provider, artifact.id, job_id=job_id)
    db_session.expire_all()
    assert not orchestrator.can_resume(db_session.get(Artifact, artifact.id))


# -- no half-stored version --------------------------------------------------------------------
def test_a_media_write_failure_leaves_no_version_and_no_files(
    db_session: Session, media_storage: Storage, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, job_id = _queued(db_session, ArtifactType.slide_deck)
    real_put = media_storage.put
    calls: list[str] = []

    def flaky_put(key: str, data: bytes, mime: str) -> Any:
        calls.append(key)
        if len(calls) == 2:
            raise OSError("disk full")
        return real_put(key, data, mime)

    monkeypatch.setattr(media_storage, "put", flaky_put)
    with pytest.raises(OSError):
        orchestrator.run_artifact_generation(db_session, Provider(), artifact.id, job_id=job_id)

    db_session.expire_all()
    assert db_session.get(Artifact, artifact.id).status is ArtifactStatus.error
    assert (
        db_session.scalar(select(func.count()).where(ArtifactVersion.artifact_id == artifact.id))
        == 0
    )
    assert not media_storage.path_for(calls[0]).exists()


# -- outline actions -------------------------------------------------------------------------
class _OutlineProvider(Provider):
    def __init__(self, outlines: list[list[str]]) -> None:
        super().__init__()
        self.outlines = outlines

    def fetch_content(self, job: StudioJobRef) -> RawArtifact:
        slides = self.outlines.pop(0) if len(self.outlines) > 1 else self.outlines[0]
        row: list[Any] = [None] * 31
        row[30] = [[["Style"], *[[s] for s in slides]]]
        return RawArtifact(html="", extras={"row": row})


def test_after_feedback_the_unrevised_outline_is_not_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(orchestrator, "_POLL_INTERVAL_SEC", 0)
    provider = _OutlineProvider([["old 1", "old 2"], ["old 1", "old 2"], ["new 1"]])
    provider.statuses = [StudioStatus.awaiting_review] * 3
    job = StudioJobRef(job_id="a", notebook_id="n", kind=ArtifactType.slide_deck)
    status = orchestrator._await_terminal(provider, job, 60, previous_outline=["old 1", "old 2"])
    assert status is StudioStatus.awaiting_review
    assert provider.statuses == []  # waited until the outline changed


def test_after_proceed_a_status_change_ends_the_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(orchestrator, "_POLL_INTERVAL_SEC", 0)
    provider = _OutlineProvider([["old"]])
    provider.statuses = [StudioStatus.awaiting_review, StudioStatus.pending, StudioStatus.ready]
    job = StudioJobRef(job_id="a", notebook_id="n", kind=ArtifactType.slide_deck)
    assert (
        orchestrator._await_terminal(provider, job, 60, previous_outline=["old"])
        is StudioStatus.ready
    )


# -- reaper ------------------------------------------------------------------------------------
def _age(db: Session, job_id: uuid.UUID, **cols: Any) -> None:
    db.execute(update(GenerationJob).where(GenerationJob.id == job_id).values(**cols))
    db.commit()


def _reap(db: Session) -> int:
    return reaper.reap_stale_jobs(db, running_after=dt.timedelta(minutes=15), queued_after=HOUR)


def _claimed(db: Session) -> tuple[Artifact, uuid.UUID]:
    """A job whose worker died right after claiming it."""
    artifact, job_id = _queued(db)
    job = _job(db, job_id)
    job.state = GenerationJobState.running
    db.commit()
    return artifact, job_id


def test_the_reaper_fails_a_running_job_whose_heartbeat_stopped(db_session: Session) -> None:
    artifact, job_id = _claimed(db_session)
    _age(db_session, job_id, heartbeat_at=func.now() - dt.timedelta(minutes=20))
    assert _reap(db_session) == 1
    job = _job(db_session, job_id)
    assert job.state is GenerationJobState.failed
    assert "Retry" in (job.error_detail or "")
    art = db_session.get(Artifact, artifact.id)
    assert art.status is ArtifactStatus.error and "Retry" in (art.last_error or "")

    # the redelivered message (4 h later) does nothing
    with pytest.raises(orchestrator.JobSkipped):
        orchestrator.run_artifact_generation(
            db_session, FixtureProvider(), artifact.id, job_id=job_id
        )


def test_the_reaper_leaves_a_job_with_a_fresh_heartbeat(db_session: Session) -> None:
    _artifact, job_id = _claimed(db_session)
    _age(db_session, job_id, heartbeat_at=func.now() - dt.timedelta(minutes=2))
    assert _reap(db_session) == 0
    assert _job(db_session, job_id).state is GenerationJobState.running


def test_the_reaper_fails_a_queued_job_nobody_picked_up(db_session: Session) -> None:
    artifact, job_id = _queued(db_session)
    _age(db_session, job_id, created_at=func.now() - 2 * HOUR)
    assert _reap(db_session) == 1
    assert _job(db_session, job_id).state is GenerationJobState.failed
    assert db_session.get(Artifact, artifact.id).status is ArtifactStatus.error


def test_the_reaper_resets_a_processing_artifact_without_a_job(db_session: Session) -> None:
    artifact, job_id = _queued(db_session)
    _job(db_session, job_id).state = GenerationJobState.cancelled
    db_session.flush()
    db_session.execute(
        update(Artifact)
        .where(Artifact.id == artifact.id)
        .values(updated_at=func.now() - HOUR)
        .execution_options(synchronize_session=False)
    )
    db_session.commit()
    assert _reap(db_session) == 1
    db_session.expire_all()
    assert db_session.get(Artifact, artifact.id).status is ArtifactStatus.error


def test_a_result_finishing_after_the_reaper_is_dropped(db_session: Session) -> None:
    artifact, job_id = _queued(db_session)
    provider = Provider()

    def reaped() -> None:
        _age(db_session, job_id, heartbeat_at=func.now() - HOUR)
        _reap(db_session)

    provider.on_poll = reaped
    with pytest.raises(orchestrator.JobSkipped):
        orchestrator.run_artifact_generation(db_session, provider, artifact.id, job_id=job_id)
    db_session.expire_all()
    art = db_session.get(Artifact, artifact.id)
    assert art.status is ArtifactStatus.error
    assert art.current_version_id is None
    assert orchestrator.can_resume(art)  # Retry fetches it, no second generation


def test_a_module_deleted_mid_generation_stores_nothing(db_session: Session) -> None:
    artifact, job_id = _queued(db_session)
    module_id = artifact.module_id
    provider = Provider()

    def delete_module() -> None:
        db_session.execute(text("DELETE FROM module WHERE id = :id"), {"id": module_id})
        db_session.commit()

    provider.on_poll = delete_module
    with pytest.raises(orchestrator.JobSkipped):
        orchestrator.run_artifact_generation(db_session, provider, artifact.id, job_id=job_id)


# -- short transactions (real commits on separate connections) -------------------------------
@pytest.fixture
def committed(
    db_engine: Engine, redis_client: redis.Redis[str], monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[sessionmaker[Session], uuid.UUID, uuid.UUID]]:
    factory = sessionmaker(bind=db_engine, expire_on_commit=False)

    @contextmanager
    def scope() -> Iterator[Session]:
        with factory() as s:
            yield s
            s.commit()

    monkeypatch.setattr(
        orchestrator,
        "ensure_module_sources",
        functools.partial(
            module_sources.ensure_module_sources, session_factory=scope, redis_client=redis_client
        ),
    )
    with factory() as s:
        module = _module(s)
        course_id = module.course_id
        jobs = orchestrator.start_module_generation(
            s, FixtureProvider(), module.id, [ArtifactType.report]
        )
        s.get(Artifact, jobs[0].artifact_id).custom_prompt = "Focus."  # no template self-heal
        s.commit()
    try:
        yield factory, jobs[0].artifact_id, jobs[0].job_id
    finally:
        with factory() as s:
            s.execute(text("DELETE FROM course WHERE id = :id"), {"id": course_id})
            s.commit()


def test_no_transaction_or_row_lock_is_held_while_notebooklm_works(
    committed: tuple[sessionmaker[Session], uuid.UUID, uuid.UUID],
) -> None:
    factory, artifact_id, job_id = committed
    seen: dict[str, Any] = {}
    provider = Provider()

    def check_from_another_connection() -> None:
        with factory() as other:
            other.execute(text("SET LOCAL lock_timeout = '1s'"))
            row = other.execute(
                text("SELECT state, started_at FROM generation_job WHERE id = :id FOR UPDATE"),
                {"id": job_id},
            ).one()
            other.execute(
                text("SELECT 1 FROM artifact WHERE id = :id FOR UPDATE NOWAIT"), {"id": artifact_id}
            )
            seen["state"], seen["started_at"] = row
            other.rollback()

    provider.on_poll = check_from_another_connection
    with factory() as session:
        assert orchestrator.run_artifact_generation(session, provider, artifact_id, job_id=job_id)
        session.commit()

    assert seen["state"] == "running"  # committed and visible while it runs
    assert seen["started_at"] is not None
