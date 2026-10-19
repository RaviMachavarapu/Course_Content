"""Liveness / readiness endpoint.

`GET /healthz` → ``{"status": "ok|degraded", "db": "...", "redis": "..."}``.

The DB probe uses psycopg directly; T004 swaps it for a `SELECT 1` on the
SQLAlchemy engine once that exists.
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status
from pydantic import BaseModel

from app.api.deps import SettingsDep
from app.logging import get_logger

router = APIRouter(tags=["system"])
log = get_logger("health")


class HealthResponse(BaseModel):
    status: str
    db: str
    redis: str


def _probe_db(dsn: str) -> str:
    try:
        import psycopg

        with psycopg.connect(dsn, connect_timeout=3) as conn:
            conn.execute("SELECT 1")
        return "ok"
    except Exception as exc:  # a health probe reports any failure, never raises
        log.warning("healthz.db_probe_failed", error=repr(exc))
        return f"error: {exc.__class__.__name__}"


def _probe_redis(url: str) -> str:
    try:
        import redis

        redis.Redis.from_url(url, socket_connect_timeout=3).ping()
        return "ok"
    except Exception as exc:  # a health probe reports any failure, never raises
        log.warning("healthz.redis_probe_failed", error=repr(exc))
        return f"error: {exc.__class__.__name__}"


@router.get("/healthz", response_model=HealthResponse)
def healthz(settings: SettingsDep, response: Response) -> HealthResponse:
    db = _probe_db(settings.db_url_sync)
    redis_status = _probe_redis(settings.redis_url)
    ok = db == "ok" and redis_status == "ok"
    if not ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(status="ok" if ok else "degraded", db=db, redis=redis_status)
