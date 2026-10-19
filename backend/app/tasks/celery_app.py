"""Celery app factory.

T022 layers on per-queue routing (`text` / `audio`) and retry/backoff for the
generation pipeline. Task modules live under `app.tasks.*` and are autodiscovered.
"""

from __future__ import annotations

import os
from typing import Any

import structlog
from celery import Celery
from celery.schedules import crontab
from celery.signals import task_failure, task_postrun, task_prerun, task_success, worker_ready

_BROKER = os.environ.get("CELERY_BROKER_URL", "redis://redis:6379/1")
_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "redis://redis:6379/2")

celery_app = Celery("shikshak_dp", broker=_BROKER, backend=_BACKEND)
celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_track_started=True,
    broker_connection_retry_on_startup=True,
    timezone="UTC",
    task_default_queue="celery",
    beat_schedule={
        "media-gc-nightly": {
            "task": "app.tasks.media_gc",
            "schedule": crontab(hour=3, minute=30),
        },
        "mcp-healthcheck": {
            "task": "app.tasks.mcp_healthcheck",
            "schedule": crontab(minute="*/5"),
        },
    },
)


def _init_sentry() -> None:
    from app.config import get_settings

    dsn = get_settings().sentry_dsn
    if not dsn:
        return
    import sentry_sdk
    from sentry_sdk.integrations.celery import CeleryIntegration

    sentry_sdk.init(dsn=dsn, integrations=[CeleryIntegration()], traces_sample_rate=0.0)


_init_sentry()


@celery_app.task(name="app.tasks.ping")
def ping() -> str:
    """Trivial liveness task used by T012's smoke test."""
    return "pong"


@worker_ready.connect
def _warm_slide_toolchain(**_: object) -> None:
    """Pay LibreOffice's one-time profile-build cost at worker boot, not on the
    first student's slide deck (T018)."""
    try:
        from app.render.slides_pptx import warm_up

        warm_up()
    except Exception:
        pass


# -- observability (T043): job id in every worker log line, generation job
# success/failure counters ---------------------------------------------------

_GENERATION_TASK_NAME = "app.tasks.generate_artifact"


@task_prerun.connect
def _bind_job_id(task_id: str, task: Any, kwargs: dict[str, Any], **_: object) -> None:
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        job_id=kwargs.get("job_id") or task_id,
        task=getattr(task, "name", None),
    )


@task_postrun.connect
def _clear_job_id(**_: object) -> None:
    structlog.contextvars.clear_contextvars()


@task_success.connect
def _record_success(sender: Any = None, **_: object) -> None:
    if getattr(sender, "name", None) != _GENERATION_TASK_NAME:
        return
    from app.api.deps import get_redis
    from app.services.metrics import record_job_result

    record_job_result(get_redis(), succeeded=True)


@task_failure.connect
def _record_failure(sender: Any = None, **_: object) -> None:
    if getattr(sender, "name", None) != _GENERATION_TASK_NAME:
        return
    from app.api.deps import get_redis
    from app.services.metrics import record_job_result

    record_job_result(get_redis(), succeeded=False)
