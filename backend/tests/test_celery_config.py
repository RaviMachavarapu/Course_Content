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
