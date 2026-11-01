"""Celery settings that keep long generation jobs from being delivered twice."""

from __future__ import annotations

import importlib

import pytest

from app.pipeline import module_sources
from app.tasks.celery_app import celery_app


def test_visibility_timeout_outlasts_the_module_lock_wait() -> None:
    # acks_late + Redis: a task unacked past visibility_timeout is redelivered. A job can
    # wait up to the module lock timeout (2 h) before it even starts its own work.
    assert celery_app.conf.task_acks_late is True
    timeout = celery_app.conf.broker_transport_options["visibility_timeout"]
    assert timeout == 4 * 3600
    assert timeout > module_sources._LOCK_WAIT_SEC


def test_beat_tasks_run_on_the_maintenance_queue_not_behind_generations() -> None:
    import app.tasks  # noqa: F401  (registers every task)

    routes = celery_app.conf.task_routes
    schedule = celery_app.conf.beat_schedule
    for entry in schedule.values():
        assert routes[entry["task"]] == {"queue": "maintenance"}
        assert entry["task"] in celery_app.tasks
    by_task = {e["task"]: e for e in schedule.values()}
    assert "app.tasks.reap_stale_jobs" in by_task
    # a backlog of stale pings/reaps is dropped rather than run in a burst
    assert by_task["app.tasks.mcp_healthcheck"]["options"]["expires"] <= 300
    assert by_task["app.tasks.reap_stale_jobs"]["options"]["expires"] <= 300


def test_generation_time_limits_end_before_redelivery() -> None:
    """A job past its hard time limit is killed before the broker would redeliver it."""
    from app.config import get_settings

    s = get_settings()
    timeout = celery_app.conf.broker_transport_options["visibility_timeout"]
    for limit in (s.job_time_limit_text_sec, s.job_time_limit_audio_sec):
        assert limit + 300 < timeout
    # a stall (no progress) is noticed well before the time limit
    assert s.job_stall_sec + s.job_stale_running_sec < s.job_time_limit_text_sec


def test_beat_messages_survive_a_chat_preparation_on_the_shared_worker() -> None:
    """Reaper/healthcheck share worker-quiz with chat preps (up to ~5.5 min each):
    their messages expire just before the next cycle, not earlier."""
    by_task = {e["task"]: e for e in celery_app.conf.beat_schedule.values()}
    for name in ("app.tasks.mcp_healthcheck", "app.tasks.reap_stale_jobs"):
        assert 280 <= by_task[name]["options"]["expires"] <= 300


def test_skipped_and_outline_runs_are_not_counted_as_successes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("app.tasks.celery_app")

    counted: list[bool] = []
    monkeypatch.setattr(
        "app.services.metrics.record_job_result", lambda _r, succeeded: counted.append(succeeded)
    )
    monkeypatch.setattr("app.api.deps.get_redis", lambda: object())
    sender = type("T", (), {"name": "app.tasks.generate_artifact"})()
    for result in ("skipped", "outline_review", "9b2f..."):
        module._record_success(sender=sender, result=result)
    assert counted == [True]
