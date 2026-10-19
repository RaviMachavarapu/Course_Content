"""Observability metrics (T043) — Redis-backed counters/gauges the admin
"System health" strip and `/api/admin/mcp/status` read from.

Deliberately simple: plain Redis keys, no metrics server/exporter. `beat`'s
periodic `app.tasks.mcp_healthcheck` task is the only writer for the MCP/
worker-heartbeat keys; `generate_artifact_task`'s Celery success/failure
signals are the only writer for the job counters.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import TYPE_CHECKING

import redis

from app.api.deps import get_redis

if TYPE_CHECKING:
    RedisClient = redis.Redis[str]
else:
    RedisClient = redis.Redis

_JOBS_SUCCEEDED_KEY = "metrics:jobs:succeeded"
_JOBS_FAILED_KEY = "metrics:jobs:failed"
_MCP_LAST_CHECKED_AT_KEY = "metrics:mcp:last_checked_at"
_MCP_LAST_HEALTHY_KEY = "metrics:mcp:last_healthy"
_WORKER_LAST_HEARTBEAT_AT_KEY = "metrics:worker:last_heartbeat_at"

# beat runs the healthcheck task on this cadence (celery_app.py); a heartbeat
# older than a few multiples of it means the worker has stopped processing
# periodic tasks, not just that it hasn't happened to run one recently.
HEARTBEAT_STALE_AFTER_SEC = 15 * 60


def record_job_result(redis_client: RedisClient, *, succeeded: bool) -> None:
    key = _JOBS_SUCCEEDED_KEY if succeeded else _JOBS_FAILED_KEY
    redis_client.incr(key)


def record_mcp_healthcheck(redis_client: RedisClient, *, healthy: bool) -> None:
    now = dt.datetime.now(tz=dt.UTC).isoformat()
    redis_client.set(_MCP_LAST_CHECKED_AT_KEY, now)
    redis_client.set(_MCP_LAST_HEALTHY_KEY, "1" if healthy else "0")
    # Successfully running at all — regardless of what it found — proves the
    # worker is alive and processing beat's periodic tasks.
    redis_client.set(_WORKER_LAST_HEARTBEAT_AT_KEY, now)


@dataclass(frozen=True)
class SystemHealth:
    jobs_succeeded: int
    jobs_failed: int
    mcp_last_checked_at: dt.datetime | None
    mcp_last_healthy: bool | None
    worker_last_heartbeat_at: dt.datetime | None
    worker_heartbeat_stale: bool


def get_system_health(redis_client: RedisClient | None = None) -> SystemHealth:
    r = redis_client or get_redis()
    succeeded = int(r.get(_JOBS_SUCCEEDED_KEY) or 0)
    failed = int(r.get(_JOBS_FAILED_KEY) or 0)
    checked_raw = r.get(_MCP_LAST_CHECKED_AT_KEY)
    healthy_raw = r.get(_MCP_LAST_HEALTHY_KEY)
    heartbeat_raw = r.get(_WORKER_LAST_HEARTBEAT_AT_KEY)

    checked_at = dt.datetime.fromisoformat(checked_raw) if checked_raw else None
    heartbeat_at = dt.datetime.fromisoformat(heartbeat_raw) if heartbeat_raw else None
    stale = True
    if heartbeat_at is not None:
        age = (dt.datetime.now(tz=dt.UTC) - heartbeat_at).total_seconds()
        stale = age > HEARTBEAT_STALE_AFTER_SEC

    return SystemHealth(
        jobs_succeeded=succeeded,
        jobs_failed=failed,
        mcp_last_checked_at=checked_at,
        mcp_last_healthy=None if healthy_raw is None else healthy_raw == "1",
        worker_last_heartbeat_at=heartbeat_at,
        worker_heartbeat_stale=stale,
    )
