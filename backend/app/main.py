"""FastAPI application entrypoint and factory.

Wires settings, structured logging, the request-context middleware, CORS for the
SPA origin, and the health router. Feature routers (auth, courses, staging,
student) are added by their respective tasks.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from app.api import health, media
from app.api.admin import artifacts as admin_artifacts
from app.api.admin import auth as admin_auth
from app.api.admin import courses as admin_courses
from app.api.admin import jobs as admin_jobs
from app.api.admin import mcp as admin_mcp
from app.api.admin import pipeline as admin_pipeline
from app.api.admin import prompts as admin_prompts
from app.api.admin import publish as admin_publish
from app.api.admin import settings as admin_settings
from app.api.admin import staging as admin_staging
from app.api.student import artifacts as student_artifacts
from app.api.student import auth as student_auth
from app.api.student import courses as student_courses
from app.api.student import me as student_me
from app.api.student import quiz as student_quiz
from app.api.student import ratings as student_ratings
from app.config import Settings, get_settings
from app.errors import install_error_handlers
from app.logging import configure_logging, get_logger
from app.middleware import RequestContextMiddleware, SecurityHeadersMiddleware

log = get_logger("app")


def _probe_slide_toolchain() -> None:
    """T018: warn loudly at startup if slide rendering can't work (the
    slide_deck pipeline then fails per-artifact, in isolation)."""
    from app.render import RenderError
    from app.render.slides_pptx import ensure_slide_toolchain

    try:
        ensure_slide_toolchain()
    except RenderError as exc:
        log.warning("app.slide_toolchain_unavailable", detail=str(exc))


def _probe_infographic_toolchain() -> None:
    """T019: same probe for the Graphviz-based infographic renderer."""
    from app.render import RenderError
    from app.render.infographic import ensure_infographic_toolchain

    try:
        ensure_infographic_toolchain()
    except RenderError as exc:
        log.warning("app.infographic_toolchain_unavailable", detail=str(exc))


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    log.info(
        "app.startup",
        env=settings.app_env,
        content_provider=settings.content_provider,
    )
    _probe_slide_toolchain()
    _probe_infographic_toolchain()
    yield
    log.info("app.shutdown")


def _init_sentry(settings: Settings) -> None:
    """No-op unless SENTRY_DSN is set (T043) — safe to call in every env."""
    if not settings.sentry_dsn:
        return
    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        integrations=[FastApiIntegration()],
        traces_sample_rate=0.0,
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    _init_sentry(settings)

    app = FastAPI(
        title="Shikshak Dp — AI Course Content Suite",
        version="0.1.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=_lifespan,
    )
    app.state.settings = settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.is_prod)

    install_error_handlers(app)

    app.include_router(health.router)
    app.include_router(student_auth.router)
    app.include_router(student_courses.router)
    app.include_router(student_artifacts.router)
    app.include_router(student_ratings.router)
    app.include_router(student_quiz.router)
    app.include_router(student_me.router)
    app.include_router(admin_auth.router)
    app.include_router(admin_prompts.router)
    app.include_router(admin_staging.router)
    app.include_router(admin_jobs.router)
    app.include_router(admin_courses.router)
    app.include_router(admin_pipeline.router)
    app.include_router(admin_mcp.router)
    app.include_router(admin_artifacts.router)
    app.include_router(admin_publish.router)
    app.include_router(admin_settings.router)
    app.include_router(media.router)

    return app


app = create_app()
