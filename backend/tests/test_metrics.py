"""T043 — Redis-backed system-health metrics."""

from __future__ import annotations

import datetime as dt

from app.services.metrics import (
    HEARTBEAT_STALE_AFTER_SEC,
    get_system_health,
    record_job_result,
    record_mcp_healthcheck,
)


def test_empty_state_is_all_zero_and_stale(redis_client) -> None:  # type: ignore[no-untyped-def]
    health = get_system_health(redis_client)
    assert health.jobs_succeeded == 0
    assert health.jobs_failed == 0
    assert health.mcp_last_checked_at is None
    assert health.mcp_last_healthy is None
    assert health.worker_last_heartbeat_at is None
    assert health.worker_heartbeat_stale is True


def test_job_counters_increment_independently(redis_client) -> None:  # type: ignore[no-untyped-def]
    record_job_result(redis_client, succeeded=True)
    record_job_result(redis_client, succeeded=True)
    record_job_result(redis_client, succeeded=False)
    health = get_system_health(redis_client)
    assert health.jobs_succeeded == 2
    assert health.jobs_failed == 1


def test_healthcheck_records_health_and_heartbeat(redis_client) -> None:  # type: ignore[no-untyped-def]
    record_mcp_healthcheck(redis_client, healthy=True)
    health = get_system_health(redis_client)
    assert health.mcp_last_healthy is True
    assert health.mcp_last_checked_at is not None
    assert health.worker_last_heartbeat_at is not None
    assert health.worker_heartbeat_stale is False

    record_mcp_healthcheck(redis_client, healthy=False)
    health = get_system_health(redis_client)
    assert health.mcp_last_healthy is False


def test_stale_heartbeat_is_detected(redis_client) -> None:  # type: ignore[no-untyped-def]
    old = dt.datetime.now(tz=dt.UTC) - dt.timedelta(seconds=HEARTBEAT_STALE_AFTER_SEC + 60)
    redis_client.set("metrics:worker:last_heartbeat_at", old.isoformat())
    health = get_system_health(redis_client)
    assert health.worker_heartbeat_stale is True
