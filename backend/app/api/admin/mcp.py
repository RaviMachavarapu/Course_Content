"""Admin — content-provider (NotebookLM MCP) status (spec.md §5.4)."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Response, status
from pydantic import BaseModel

from app.api.admin import ADMIN_DEPENDENCIES
from app.api.deps import RedisDep
from app.pipeline.factory import get_content_provider
from app.services.metrics import get_system_health

router = APIRouter(prefix="/api/admin/mcp", tags=["admin-mcp"], dependencies=ADMIN_DEPENDENCIES)


class McpStatus(BaseModel):
    healthy: bool
    account_email: str | None
    last_ok_at: dt.datetime | None
    detail: str
    worker_last_heartbeat_at: dt.datetime | None
    worker_heartbeat_stale: bool
    jobs_succeeded: int
    jobs_failed: int


@router.get("/status", response_model=McpStatus)
def mcp_status(redis_client: RedisDep) -> McpStatus:
    health = get_content_provider().health()
    system = get_system_health(redis_client)
    return McpStatus(
        healthy=health.healthy,
        account_email=health.account_email,
        last_ok_at=health.last_ok_at,
        detail=health.detail,
        worker_last_heartbeat_at=system.worker_last_heartbeat_at,
        worker_heartbeat_stale=system.worker_heartbeat_stale,
        jobs_succeeded=system.jobs_succeeded,
        jobs_failed=system.jobs_failed,
    )


@router.post("/refresh-auth", status_code=status.HTTP_204_NO_CONTENT)
def refresh_auth() -> Response:
    get_content_provider().refresh_auth()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
