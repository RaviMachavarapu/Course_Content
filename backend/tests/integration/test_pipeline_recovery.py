"""Worst-case recovery of the generation pipeline (review 2026-10-29, section B).

Lost dispatch messages (outbox + re-dispatch), the admin's Cancel, a worker killed
before/after generating, a run that lost its job, Redis/lock trouble, parse errors
(Retry regenerates: owner decision 6), soft time limits and publish row locks.
FixtureProvider-based fakes only; never the live connector.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from celery.exceptions import SoftTimeLimitExceeded
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.models.artifact import Artifact
from app.models.enums import ArtifactStatus, ArtifactType, GenerationJobState
from app.models.module import Module
from app.pipeline import orchestrator, reaper
from app.pipeline.fixture import FixtureProvider
from app.pipeline.parsers.base import ArtifactParseError
from app.pipeline.provider import (
    GenerationTimeout,
    RawArtifact,
    StudioJobRef,
    StudioStatus,
    TransientProviderError,
)
from app.services.publish import publish_module
from tests.integration.test_generation_jobs import Provider, _age, _job, _module, _queued
from tests.integration.test_redo import _admin_headers, _module_with_generated

MIN = dt.timedelta(minutes=1)


@pytest.fixture(autouse=True)
def _never_the_real_broker(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.tasks import generation

    def refuse(**_: Any) -> None:
        raise AssertionError("a test must not publish to the real broker")

    monkeypatch.setattr(generation.generate_artifact_task, "apply_async", refuse)


class Killed(BaseException):
    """Stands in for SIGKILL/OOM: nothing below the worker gets to record a failure."""


def _redispatch(
    db: Session,
    *,
    held: set[str] | None = None,
    broken: bool = False,
    max_redispatches: int = 3,
) -> tuple[int, list[dict[str, Any]]]:
    sent: list[dict[str, Any]] = []

    def in_broker(ids: set[str]) -> set[str]:
        if broken:
            raise ConnectionError("broker down")
        return ids & (held or set())

    n = reaper.redispatch_lost_jobs(
        db,
        after=10 * MIN,
        in_broker=in_broker,
        send=sent.append,
        max_redispatches=max_redispatches,
    )
    return n, sent


def _lose_message(db: Session, job_id: uuid.UUID) -> None:
    """The job was queued 11 minutes ago and its message never reached a worker."""
    _age(db, job_id, created_at=func.now() - 11 * MIN, heartbeat_at=None)


# -- B5: lost dispatch message -----------------------------------------------------------
def test_every_queued_job_stores_its_message(db_session: Session) -> None:
    artifact, job_id = _queued(db_session, ArtifactType.audio_overview)
    job = _job(db_session, job_id)
    assert job.dispatch is not None
    assert job.dispatch["queue"] == "audio"
    assert job.dispatch["kwargs"] == {
        "artifact_id": str(artifact.id),
        "job_id": str(job_id),
        "redo_note": None,
        "resume": False,
    }
    assert 0 < job.dispatch["soft_time_limit"] < job.dispatch["time_limit"] <= 4 * 3600


def test_a_lost_redo_message_is_sent_again_with_its_note(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Broker down at enqueue / api restarted before dispatching / Redis lost the
    queue: the job stays queued; the reaper sends its stored message again, note and
    all, and the run uses it."""
    monkeypatch.setattr("app.api.admin.staging._dispatch", lambda *_: None)  # lost
    module = _module_with_generated(db_session, [ArtifactType.report])
    report = next(a for a in module.artifacts if a.type is ArtifactType.report)
    headers = _admin_headers(client, db_session)
    resp = client.post(
        f"/api/admin/artifacts/{report.id}/redo", json={"note": "Shorter"}, headers=headers
    )
    assert resp.status_code == status.HTTP_202_ACCEPTED
    job_id = uuid.UUID(resp.json()["job"]["id"])
    _lose_message(db_session, job_id)

    n, sent = _redispatch(db_session)
    assert n == 1
    [payload] = sent
    assert payload["kwargs"]["job_id"] == str(job_id)
    assert payload["kwargs"]["redo_note"] == "Shorter"
    job = _job(db_session, job_id)
    assert job.state is GenerationJobState.queued
    assert job.dispatch is not None and job.dispatch["redispatches"] == 1
    assert job.heartbeat_at is not None

    kwargs = payload["kwargs"]
    version = orchestrator.run_artifact_generation(
        db_session,
        Provider(),
        uuid.UUID(kwargs["artifact_id"]),
        job_id=uuid.UUID(kwargs["job_id"]),
        redo_note=kwargs["redo_note"],
        resume=kwargs["resume"],
    )
    assert version is not None and version.redo_note == "Shorter"


def test_a_job_still_in_the_broker_is_a_backlog_not_lost(db_session: Session) -> None:
    """Many modules queued on two slots: a job waiting hours in the queue is kept alive
    (never failed as "never started") and not sent twice."""
    artifact, job_id = _queued(db_session)
    _age(db_session, job_id, created_at=func.now() - 7 * 60 * MIN, heartbeat_at=None)
    n, sent = _redispatch(db_session, held={str(job_id)})
    assert (n, sent) == (0, [])
    reaper.reap_stale_jobs(db_session, running_after=15 * MIN, queued_after=6 * 60 * MIN)
    assert _job(db_session, job_id).state is GenerationJobState.queued
    assert db_session.get(Artifact, artifact.id).status is ArtifactStatus.processing


def test_a_fresh_queued_job_is_left_alone(db_session: Session) -> None:
    _artifact, job_id = _queued(db_session)
    assert _redispatch(db_session) == (0, [])


def test_redispatch_gives_up_after_the_limit(db_session: Session) -> None:
    artifact, job_id = _queued(db_session)
    for attempt in range(1, 4):
        _lose_message(db_session, job_id)
        n, sent = _redispatch(db_session)
        assert (n, len(sent)) == (1, 1), attempt
    _lose_message(db_session, job_id)
    n, sent = _redispatch(db_session)
    assert (n, sent) == (1, [])
    job = _job(db_session, job_id)
    assert job.state is GenerationJobState.failed
    assert job.error_detail == reaper.NEVER_STARTED
    assert db_session.get(Artifact, artifact.id).status is ArtifactStatus.error


def test_an_unreadable_broker_redispatches_nothing(db_session: Session) -> None:
    _artifact, job_id = _queued(db_session)
    _lose_message(db_session, job_id)
    assert _redispatch(db_session, broken=True) == (0, [])
    assert _job(db_session, job_id).state is GenerationJobState.queued


def test_a_failing_resend_is_tried_again_next_cycle(db_session: Session) -> None:
    _artifact, job_id = _queued(db_session)
    _lose_message(db_session, job_id)

    def down(_payload: dict[str, Any]) -> None:
        raise ConnectionError("still down")

    n = reaper.redispatch_lost_jobs(
        db_session, after=10 * MIN, in_broker=lambda _ids: set(), send=down, max_redispatches=3
    )
    assert n == 1
    assert _job(db_session, job_id).state is GenerationJobState.queued


def test_broker_job_ids_finds_queued_and_reserved_messages(redis_client: Any) -> None:
    queued, prio, reserved, gone = (str(uuid.uuid4()) for _ in range(4))
    redis_client.rpush("text", f'{{"headers": {{"id": "gen-{queued}-ab12cd34"}}}}')
    redis_client.rpush("audio\x06\x163", f'{{"headers": {{"id": "gen-{prio}-00000000"}}}}')
    redis_client.hset(
        "unacked", "tag1", f'[{{"headers": {{"id": "gen-{reserved}-1"}}}}, "", "text"]'
    )
    assert reaper.broker_job_ids(redis_client, {queued, prio, reserved, gone}) == {
        queued,
        prio,
        reserved,
    }
    assert reaper.broker_job_ids(redis_client, set()) == set()


# -- the admin's Cancel -----------------------------------------------------------------
def test_cancel_frees_a_stuck_artifact_and_retry_starts_again(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[dict[str, Any]] = []
    monkeypatch.setattr("app.api.admin.staging._dispatch", lambda p: sent.append(p))
    module = _module_with_generated(db_session, [ArtifactType.report])
    report = next(a for a in module.artifacts if a.type is ArtifactType.report)
    headers = _admin_headers(client, db_session)
    url = f"/api/admin/artifacts/{report.id}"
    job_id = client.post(f"{url}/redo", json={}, headers=headers).json()["job"]["id"]
    assert client.post(f"{url}/redo", json={}, headers=headers).status_code == 409

    resp = client.post(f"{url}/cancel", headers=headers)
    assert resp.status_code == status.HTTP_200_OK
    assert resp.json()["status"] == "error"
    assert "Retry" in resp.json()["last_error"]
    job = _job(db_session, uuid.UUID(job_id))
    assert job.state is GenerationJobState.cancelled
    assert client.post(f"{url}/cancel", headers=headers).status_code == 409  # nothing to cancel

    assert client.post(f"{url}/retry", headers=headers).status_code == 202
    assert len(sent) == 2


def test_cancel_needs_an_admin_and_csrf(client: TestClient, db_session: Session) -> None:
    module = _module_with_generated(db_session, [ArtifactType.report])
    report = next(a for a in module.artifacts if a.type is ArtifactType.report)
    resp = client.post(f"/api/admin/artifacts/{report.id}/cancel")
    assert resp.status_code in (401, 403)
    headers = _admin_headers(client, db_session)
    assert (
        client.post(f"/api/admin/artifacts/{uuid.uuid4()}/cancel", headers=headers).status_code
        == 404
    )


def test_a_cancelled_running_job_stores_nothing_and_retry_resumes(db_session: Session) -> None:
    artifact, job_id = _queued(db_session)
    provider = Provider()

    def admin_cancels() -> None:
        orchestrator.cancel_generation(db_session, artifact.id)
        db_session.commit()

    provider.on_poll = admin_cancels
    with pytest.raises(orchestrator.JobSkipped):
        orchestrator.run_artifact_generation(db_session, provider, artifact.id, job_id=job_id)
    db_session.expire_all()
    art = db_session.get(Artifact, artifact.id)
    assert art.status is ArtifactStatus.error and art.current_version_id is None
    assert orchestrator.can_resume(art)  # NotebookLM's artifact is kept

    provider.on_poll = None
    job = orchestrator.enqueue_artifact_regeneration(
        db_session, artifact.id, redo_note=None, resume=True
    )
    assert orchestrator.run_artifact_generation(
        db_session, provider, artifact.id, job_id=job.id, resume=True
    )
    assert provider.generated == 1


# -- B1/B2: a worker killed before / after generating ----------------------------------
def test_killed_after_generating_then_reaped_then_retry_resumes(db_session: Session) -> None:
    artifact, job_id = _queued(db_session)
    provider = Provider()

    def kill() -> None:
        raise Killed()

    provider.on_poll = kill
    with pytest.raises(Killed):
        orchestrator.run_artifact_generation(db_session, provider, artifact.id, job_id=job_id)
    db_session.rollback()
    assert _job(db_session, job_id).state is GenerationJobState.running  # nobody recorded it
    _age(db_session, job_id, heartbeat_at=func.now() - 20 * MIN)
    assert reaper.reap_stale_jobs(db_session, running_after=15 * MIN, queued_after=6 * 60 * MIN)
    db_session.expire_all()
    art = db_session.get(Artifact, artifact.id)
    assert art.status is ArtifactStatus.error and art.last_error == reaper.WORKER_LOST
    assert orchestrator.can_resume(art)

    provider.on_poll = None
    job = orchestrator.enqueue_artifact_regeneration(
        db_session, artifact.id, redo_note=None, resume=True
    )
    assert orchestrator.run_artifact_generation(
        db_session, provider, artifact.id, job_id=job.id, resume=True
    )
    assert provider.generated == 1  # resumed: no second NotebookLM artifact


def test_killed_during_the_source_step_then_retry_generates(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, job_id = _queued(db_session)
    real = orchestrator.ensure_module_sources

    def killed(*_a: Any, **_k: Any) -> Any:
        raise Killed()

    monkeypatch.setattr(orchestrator, "ensure_module_sources", killed)
    provider = Provider()
    with pytest.raises(Killed):
        orchestrator.run_artifact_generation(db_session, provider, artifact.id, job_id=job_id)
    db_session.rollback()
    _age(db_session, job_id, heartbeat_at=func.now() - 20 * MIN)
    reaper.reap_stale_jobs(db_session, running_after=15 * MIN, queued_after=6 * 60 * MIN)
    db_session.expire_all()
    art = db_session.get(Artifact, artifact.id)
    assert art.status is ArtifactStatus.error and not orchestrator.can_resume(art)

    monkeypatch.setattr(orchestrator, "ensure_module_sources", real)
    job = orchestrator.enqueue_artifact_regeneration(
        db_session, artifact.id, redo_note=None, resume=True
    )
    assert orchestrator.run_artifact_generation(db_session, provider, artifact.id, job_id=job.id)
    assert provider.generated == 1


# -- B4: a run whose job was resolved meanwhile ----------------------------------------
def test_a_job_reaped_during_the_source_step_never_generates(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Heartbeat lost for 15 min (DB unreachable from the worker), the reaper failed the
    job, the admin may already have pressed Retry: the old run must not spend quota."""
    artifact, job_id = _queued(db_session)
    real = orchestrator.ensure_module_sources

    def slow_sources(*a: Any, **k: Any) -> Any:
        nb = real(*a, **k)
        _age(db_session, job_id, heartbeat_at=func.now() - 20 * MIN)
        reaper.reap_stale_jobs(db_session, running_after=15 * MIN, queued_after=6 * 60 * MIN)
        return nb

    monkeypatch.setattr(orchestrator, "ensure_module_sources", slow_sources)
    provider = Provider()
    with pytest.raises(orchestrator.JobSkipped):
        orchestrator.run_artifact_generation(db_session, provider, artifact.id, job_id=job_id)
    assert provider.generated == 0


def test_a_run_whose_job_is_gone_stops_polling(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(orchestrator, "_POLL_INTERVAL_SEC", 0)
    monkeypatch.setattr(orchestrator, "_STATE_CHECK_SEC", 0)
    artifact, job_id = _queued(db_session)
    provider = Provider()
    provider.statuses = [StudioStatus.pending] * 1000
    polls: list[int] = []

    def reaped_on_second_poll() -> None:
        polls.append(1)
        if len(polls) == 2:
            _age(db_session, job_id, heartbeat_at=func.now() - 20 * MIN)
            reaper.reap_stale_jobs(db_session, running_after=15 * MIN, queued_after=6 * 60 * MIN)

    provider.on_poll = reaped_on_second_poll
    with pytest.raises(orchestrator.JobSkipped):
        orchestrator.run_artifact_generation(db_session, provider, artifact.id, job_id=job_id)
    assert len(polls) <= 3  # stopped, instead of polling for the full timeout


def test_progress_is_reported_through_the_run(db_session: Session) -> None:
    artifact, job_id = _queued(db_session, ArtifactType.slide_deck)
    beats: list[int] = []
    orchestrator.run_artifact_generation(
        db_session, Provider(), artifact.id, job_id=job_id, on_progress=lambda: beats.append(1)
    )
    assert len(beats) >= 4  # claim, sources, generated, polled, fetched


# -- B10 + owner decision 6: a parse error -----------------------------------------------
class _Malformed(Provider):
    def __init__(self, bad_fetches: int = 1) -> None:
        super().__init__()
        self.bad_fetches = bad_fetches

    def fetch_content(self, job: StudioJobRef) -> RawArtifact:
        if self.bad_fetches:
            self.bad_fetches -= 1
            return RawArtifact(html="<html>not a report</html>", extras={"artifact_id": job.job_id})
        return super().fetch_content(job)


def test_retry_after_a_parse_error_generates_a_fresh_artifact(db_session: Session) -> None:
    artifact, job_id = _queued(db_session, ArtifactType.quiz)
    provider = _Malformed()
    with pytest.raises(ArtifactParseError):
        orchestrator.run_artifact_generation(db_session, provider, artifact.id, job_id=job_id)
    db_session.expire_all()
    art = db_session.get(Artifact, artifact.id)
    assert art.status is ArtifactStatus.error
    assert "Press Retry" in (art.last_error or "")
    assert not orchestrator.can_resume(art)  # fetching it again gives the same result

    job = orchestrator.enqueue_artifact_regeneration(
        db_session, artifact.id, redo_note=None, resume=True
    )
    assert job.dispatch is not None and job.dispatch["kwargs"]["resume"] is False
    assert orchestrator.run_artifact_generation(db_session, provider, artifact.id, job_id=job.id)
    assert provider.generated == 2


# -- B8: a resumed timeout forgets ---------------------------------------------------
def test_a_second_timeout_forgets_the_notebooklm_artifact(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(orchestrator, "_POLL_INTERVAL_SEC", 0)
    monkeypatch.setattr(orchestrator, "settings_timeout", lambda _a: 0)
    artifact, job_id = _queued(db_session)
    provider = Provider()
    provider.statuses = [StudioStatus.pending] * 2
    with pytest.raises(GenerationTimeout):
        orchestrator.run_artifact_generation(db_session, provider, artifact.id, job_id=job_id)
    db_session.expire_all()
    assert orchestrator.can_resume(db_session.get(Artifact, artifact.id))
    job = orchestrator.enqueue_artifact_regeneration(
        db_session, artifact.id, redo_note=None, resume=True
    )
    with pytest.raises(GenerationTimeout):
        orchestrator.run_artifact_generation(
            db_session, provider, artifact.id, job_id=job.id, resume=True
        )
    db_session.expire_all()
    assert not orchestrator.can_resume(db_session.get(Artifact, artifact.id))


# -- B25: an outline action whose artifact vanished ------------------------------------
def test_an_outline_action_on_a_vanished_artifact_lets_retry_regenerate(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(orchestrator, "_POLL_INTERVAL_SEC", 0)
    monkeypatch.setattr(orchestrator, "_MISSING_GRACE_SEC", 0)
    artifact, job_id = _queued(db_session, ArtifactType.slide_deck)
    orchestrator.run_artifact_generation(db_session, Provider(), artifact.id, job_id=job_id)
    db_session.expire_all()
    art = db_session.get(Artifact, artifact.id)
    art.status = ArtifactStatus.outline_review
    art.notebooklm_studio_id = "studio-1"
    art.outline_json = {"style": "s", "slides": ["a"], "focus_prompt": "p"}
    db_session.commit()

    actions: list[str | None] = []

    class Gone(Provider):
        def outline_action(self, job: StudioJobRef, feedback: str | None) -> None:
            actions.append(feedback)

    provider = Gone()
    provider.statuses = [StudioStatus.missing]
    job = orchestrator.request_outline_action(db_session, artifact.id, feedback=None)
    db_session.commit()
    with pytest.raises(orchestrator.StudioGenerationFailed):
        orchestrator.run_artifact_generation(
            db_session,
            provider,
            artifact.id,
            job_id=job.id,
            resume=True,
            outline={"feedback": None},
        )
    assert actions == [None]
    db_session.expire_all()
    art = db_session.get(Artifact, artifact.id)
    assert art.status is ArtifactStatus.error
    assert not orchestrator.can_resume(art)  # no Retry loop on a missing artifact


# -- B16: Redis restarting mid-generation ----------------------------------------------
def test_redis_restarting_while_polling_is_waited_out(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`_locked` turns a Redis error into TransientProviderError: polls keep waiting."""
    monkeypatch.setattr(orchestrator, "_POLL_INTERVAL_SEC", 0)
    artifact, job_id = _queued(db_session)
    provider = Provider()
    errors = [TransientProviderError("mcp:session unavailable (Redis: restarting)")] * 3

    def flaky() -> None:
        if errors:
            raise errors.pop()

    provider.on_poll = flaky
    assert orchestrator.run_artifact_generation(db_session, provider, artifact.id, job_id=job_id)
    assert provider.generated == 1


def test_redis_down_at_the_module_lock_requeues_the_job(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, job_id = _queued(db_session)

    def down(*_a: Any, **_k: Any) -> Any:
        raise TransientProviderError("source step lock unavailable (Redis: restarting)")

    monkeypatch.setattr(orchestrator, "ensure_module_sources", down)
    with pytest.raises(TransientProviderError):
        orchestrator.run_artifact_generation(
            db_session, Provider(), artifact.id, job_id=job_id, retry_transient=True
        )
    assert _job(db_session, job_id).state is GenerationJobState.queued  # Celery retries it
    assert db_session.get(Artifact, artifact.id).status is ArtifactStatus.processing


# -- stuck: the soft time limit -----------------------------------------------------------
def test_the_soft_time_limit_fails_the_job_and_keeps_the_notebooklm_artifact(
    db_session: Session,
) -> None:
    artifact, job_id = _queued(db_session)
    provider = Provider()

    def limit() -> None:
        raise SoftTimeLimitExceeded()

    provider.on_poll = limit
    with pytest.raises(SoftTimeLimitExceeded):
        orchestrator.run_artifact_generation(db_session, provider, artifact.id, job_id=job_id)
    db_session.expire_all()
    art = db_session.get(Artifact, artifact.id)
    assert art.status is ArtifactStatus.error
    assert art.last_error == orchestrator.TIME_LIMIT
    assert orchestrator.can_resume(art)
    assert _job(db_session, job_id).state is GenerationJobState.failed


# -- B24: publish takes the artifact row locks ------------------------------------------
@pytest.fixture
def committed_module(db_engine: Engine) -> Iterator[tuple[sessionmaker[Session], uuid.UUID]]:
    factory = sessionmaker(bind=db_engine, expire_on_commit=False)
    with factory() as s:
        module = _module(s)
        orchestrator.ensure_artifacts(s, module)
        course_id, module_id = module.course_id, module.id
        s.commit()
    try:
        yield factory, module_id
    finally:
        with factory() as s:
            s.execute(text("DELETE FROM course WHERE id = :id"), {"id": course_id})
            s.commit()


def test_publish_waits_for_a_writer_holding_an_artifact(
    committed_module: tuple[sessionmaker[Session], uuid.UUID],
) -> None:
    """A Redo (or a version being stored) holds the artifact row: publish must wait for
    it, not write a stale "published" over it."""
    factory, module_id = committed_module
    with factory() as writer, factory() as publisher:
        writer.execute(
            select(Artifact).where(Artifact.module_id == module_id).limit(1).with_for_update()
        ).all()
        publisher.execute(text("SET LOCAL lock_timeout = '300ms'"))
        module = publisher.get(Module, module_id)
        assert module is not None
        with pytest.raises(OperationalError, match="lock"):
            publish_module(publisher, module)
        publisher.rollback()
        writer.rollback()


# -- owner decision 5: the old notebook is deleted after Re-run all / module delete --------
def _with_notebook(db: Session, notebook_id: str) -> Module:
    module = _module_with_generated(db, [ArtifactType.report])
    module.notebooklm_notebook_id = notebook_id
    db.commit()
    return module


def test_rerun_all_queues_the_old_notebooks_delete_after_the_commit(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    notebook_deletes: list[str],
) -> None:
    monkeypatch.setattr("app.api.admin.courses._dispatch_all", lambda *_: None)
    module = _with_notebook(db_session, "nb-old")
    headers = _admin_headers(client, db_session)
    resp = client.post(f"/api/admin/courses/modules/{module.id}/regenerate", headers=headers)
    assert resp.status_code == status.HTTP_200_OK
    assert notebook_deletes == ["nb-old"]
    db_session.expire_all()
    assert db_session.get(Module, module.id).notebooklm_notebook_id is None


def test_a_busy_rerun_all_deletes_nothing(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    notebook_deletes: list[str],
) -> None:
    monkeypatch.setattr("app.api.admin.courses._dispatch_all", lambda *_: None)
    module = _with_notebook(db_session, "nb-old")
    headers = _admin_headers(client, db_session)
    url = f"/api/admin/courses/modules/{module.id}/regenerate"
    assert client.post(url, headers=headers).status_code == 200
    assert client.post(url, headers=headers).status_code == 409  # still generating
    assert notebook_deletes == ["nb-old"]  # only the first one


def test_module_delete_queues_its_notebooks_delete_and_never_fails_on_it(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tasks import maintenance

    def broker_down(**_: Any) -> None:
        raise ConnectionError("redis restarting")

    monkeypatch.setattr(maintenance.delete_notebook_task, "apply_async", broker_down)
    module = _with_notebook(db_session, "nb-gone")
    headers = _admin_headers(client, db_session)
    resp = client.delete(f"/api/admin/courses/modules/{module.id}", headers=headers)
    assert resp.status_code == status.HTTP_204_NO_CONTENT
    db_session.expire_all()
    assert db_session.get(Module, module.id) is None


def test_a_module_without_a_notebook_deletes_nothing(
    client: TestClient, db_session: Session, notebook_deletes: list[str]
) -> None:
    module = _module(db_session)
    db_session.commit()
    headers = _admin_headers(client, db_session)
    assert (
        client.delete(f"/api/admin/courses/modules/{module.id}", headers=headers).status_code == 204
    )
    assert notebook_deletes == []


@pytest.fixture
def delete_task(
    monkeypatch: pytest.MonkeyPatch, source_step_sessions: Any
) -> tuple[FixtureProvider, Callable[..., str]]:
    from app.tasks import maintenance

    provider = FixtureProvider()
    monkeypatch.setattr(maintenance, "session_scope", source_step_sessions)
    monkeypatch.setattr(maintenance, "get_content_provider", lambda: provider)

    def run(notebook_id: str, retries: int = 0) -> str:
        task = maintenance.delete_notebook_task
        task.push_request(retries=retries)
        try:
            return str(task.run(notebook_id))
        finally:
            task.pop_request()

    return provider, run


def test_the_delete_task_deletes_an_unused_notebook(
    db_session: Session, delete_task: tuple[FixtureProvider, Callable[..., str]]
) -> None:
    provider, run = delete_task
    assert run("nb-old") == "deleted"
    assert ("delete_notebook", "nb-old") in provider.calls


def test_the_delete_task_never_deletes_a_notebook_a_module_uses(
    db_session: Session, delete_task: tuple[FixtureProvider, Callable[..., str]]
) -> None:
    provider, run = delete_task
    module = _module(db_session)
    module.notebooklm_notebook_id = "nb-live"
    db_session.commit()
    assert run("nb-live") == "skipped"
    assert provider.calls == []


def test_the_delete_task_logs_failures_and_retries_transient_ones(
    db_session: Session,
    delete_task: tuple[FixtureProvider, Callable[..., str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from celery.exceptions import Retry

    from app.pipeline.provider import ProviderError
    from app.tasks import maintenance

    provider, run = delete_task
    errors: list[Exception] = [ProviderError("not found")]

    def delete(_nb: Any) -> None:
        raise errors[0]

    monkeypatch.setattr(provider, "delete_notebook", delete)
    assert run("nb-x") == "failed"

    errors[0] = TransientProviderError("lock busy")
    scheduled: list[dict[str, Any]] = []

    def fake_retry(**kwargs: Any) -> Retry:
        scheduled.append(kwargs)
        return Retry("retry")

    monkeypatch.setattr(maintenance.delete_notebook_task, "retry", fake_retry)
    with pytest.raises(Retry):
        run("nb-x")
    assert scheduled and scheduled[0]["countdown"] == 60
    assert run("nb-x", retries=maintenance.DELETE_NOTEBOOK_RETRIES) == "gave up"
