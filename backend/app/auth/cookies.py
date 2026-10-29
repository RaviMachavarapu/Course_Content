"""Session cookie helpers — one place for the flag policy."""

from __future__ import annotations

from starlette.responses import Response

from app.auth.device import DEVICE_COOKIE_NAMES, max_age_seconds
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


def set_device_cookie(
    response: Response, scope: SessionScope, token: str, settings: Settings
) -> None:
    """The trusted-device cookie (auth.device): long-lived, never read by JS."""
    response.set_cookie(
        key=DEVICE_COOKIE_NAMES[scope],
        value=token,
        max_age=max_age_seconds(settings),
        httponly=True,
        secure=settings.app_env != "dev",
        samesite="lax",
        path="/",
    )


def clear_device_cookie(response: Response, scope: SessionScope, settings: Settings) -> None:
    response.delete_cookie(
        key=DEVICE_COOKIE_NAMES[scope],
        httponly=True,
        secure=settings.app_env != "dev",
        samesite="lax",
        path="/",
    )
