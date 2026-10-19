"""Provider selection from `CONTENT_PROVIDER` (plan.md §8)."""

from __future__ import annotations

from app.config import Settings, get_settings
from app.pipeline.fixture import FixtureProvider
from app.pipeline.notebooklm_mcp import NotebookLmMcpProvider
from app.pipeline.provider import ContentProvider


def get_content_provider(settings: Settings | None = None) -> ContentProvider:
    settings = settings or get_settings()

    if settings.content_provider == "fixture":
        return FixtureProvider()

    if settings.content_provider == "notebooklm":
        provider: ContentProvider = NotebookLmMcpProvider(settings)
        return provider

    raise RuntimeError(f"unknown CONTENT_PROVIDER: {settings.content_provider!r}")
