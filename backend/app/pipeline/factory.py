"""Provider selection from `CONTENT_PROVIDER` (plan.md §8).

The NotebookLM provider holds an HTTP connection pool and a Redis pool, so one
instance is reused per process (a forked worker builds its own) instead of a new
one per task, healthcheck and request.
"""

from __future__ import annotations

import os
import threading

from app.config import Settings, get_settings
from app.pipeline.fixture import FixtureProvider
from app.pipeline.notebooklm_mcp import NotebookLmMcpProvider
from app.pipeline.provider import ContentProvider

_lock = threading.Lock()
_cached: tuple[int, tuple[str, str], NotebookLmMcpProvider] | None = None


def get_content_provider(settings: Settings | None = None) -> ContentProvider:
    global _cached
    settings = settings or get_settings()

    if settings.content_provider == "fixture":
        return FixtureProvider()

    if settings.content_provider == "notebooklm":
        key = (settings.mcp_endpoint, settings.redis_url)
        with _lock:
            if _cached is None or _cached[0] != os.getpid() or _cached[1] != key:
                _cached = (os.getpid(), key, NotebookLmMcpProvider(settings))
            return _cached[2]

    raise RuntimeError(f"unknown CONTENT_PROVIDER: {settings.content_provider!r}")


def reset_content_provider() -> None:
    """Close and forget this process's cached provider (tests, settings reload)."""
    global _cached
    with _lock:
        if _cached is not None and _cached[0] == os.getpid():
            _cached[2].close()
        _cached = None
