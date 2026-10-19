"""Session cookie helpers — one place for the flag policy."""

from __future__ import annotations

from starlette.responses import Response

from app.auth.sessions import COOKIE_NAMES, SessionScope, SessionStore
from app.config import Settings


def set_session_cookie(
    response: Response,
    scope: SessionScope,
    token: str,
    store: SessionStore,
    settings: Settings,
) -> None:
    response.set_cookie(
        key=COOKIE_NAMES[scope],
        value=token,
        max_age=store.ttl_seconds(scope),
        httponly=True,
        secure=settings.app_env != "dev",
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response, scope: SessionScope, settings: Settings) -> None:
    response.delete_cookie(
        key=COOKIE_NAMES[scope],
        httponly=True,
        secure=settings.app_env != "dev",
        samesite="lax",
        path="/",
    )
