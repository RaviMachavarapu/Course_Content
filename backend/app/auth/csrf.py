"""CSRF protection — double-submit cookie.

On login/register we set a **non-HttpOnly** ``sdp_csrf`` cookie. The SPA reads it
and echoes the value in the ``X-CSRF-Token`` header on every state-changing
request. `csrf_protect` (a dependency) checks the two match. Safe methods are
exempt; so is the login endpoint, which cannot have a token yet.
"""

from __future__ import annotations

import secrets

from fastapi import Request, status
from starlette.responses import Response

from app.config import Settings
from app.errors import APIError

CSRF_COOKIE = "sdp_csrf"
CSRF_HEADER = "X-CSRF-Token"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})
_TOKEN_BYTES = 32


def issue_csrf_cookie(response: Response, settings: Settings) -> str:
    token = secrets.token_urlsafe(_TOKEN_BYTES)
    response.set_cookie(
        key=CSRF_COOKIE,
        value=token,
        httponly=False,  # the SPA must read it
        secure=settings.app_env != "dev",
        samesite="lax",
        path="/",
    )
    return token


def clear_csrf_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        key=CSRF_COOKIE,
        httponly=False,
        secure=settings.app_env != "dev",
        samesite="lax",
        path="/",
    )


def csrf_protect(request: Request) -> None:
    if request.method in SAFE_METHODS:
        return
    cookie = request.cookies.get(CSRF_COOKIE)
    header = request.headers.get(CSRF_HEADER)
    if not cookie or not header or not secrets.compare_digest(cookie, header):
        raise APIError(status.HTTP_403_FORBIDDEN, "csrf_failed", "Missing or invalid CSRF token")
