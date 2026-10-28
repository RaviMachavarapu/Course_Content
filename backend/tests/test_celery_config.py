"""Celery settings that keep long generation jobs from being delivered twice."""

from __future__ import annotations

from app.pipeline import module_sources
from app.tasks.celery_app import celery_app


def test_visibility_timeout_outlasts_the_module_lock_wait() -> None:
    # acks_late + Redis: a task unacked past visibility_timeout is redelivered. A job can
    # wait up to the module lock timeout (2 h) before it even starts its own work.
    assert celery_app.conf.task_acks_late is True
    timeout = celery_app.conf.broker_transport_options["visibility_timeout"]
    assert timeout == 4 * 3600
    assert timeout > module_sources._LOCK_TIMEOUT_SEC


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
