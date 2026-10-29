"""CSRF protection — double-submit cookie.

On login/register we set a **non-HttpOnly** ``sdp_csrf`` cookie. The SPA reads it
and echoes the value in the ``X-CSRF-Token`` header on every state-changing
request. `csrf_protect` (a dependency) checks the two match. Safe methods are
exempt; so is the login endpoint, which cannot have a token yet.

Lifetime: the cookie is persistent, as long as the longest session cookie, so a
browser restart never leaves a live session without its token. Both areas share
the one cookie (the SPA reads it by name), so:

- an authenticated ``GET /auth/me`` (either area) re-issues it — same value if
  present, a fresh one if missing — and refreshes its lifetime;
- a logout clears it only when no other area's session cookie remains.
"""

from __future__ import annotations

import secrets

from fastapi import Request, status
from starlette.responses import Response

from app.auth.sessions import COOKIE_NAMES, max_seconds
from app.config import Settings
from app.errors import APIError

CSRF_COOKIE = "sdp_csrf"
CSRF_HEADER = "X-CSRF-Token"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})
_TOKEN_BYTES = 32


def csrf_max_age(settings: Settings) -> int:
    """At least as long as any session cookie it protects."""
    return max(max_seconds(settings, "admin"), max_seconds(settings, "student"))


def issue_csrf_cookie(response: Response, settings: Settings, token: str | None = None) -> str:
    token = token or secrets.token_urlsafe(_TOKEN_BYTES)
    response.set_cookie(
        key=CSRF_COOKIE,
        value=token,
        max_age=csrf_max_age(settings),
        httponly=False,  # the SPA must read it
        secure=settings.app_env != "dev",
        samesite="lax",
        path="/",
    )
    return token


def ensure_csrf_cookie(request: Request, response: Response, settings: Settings) -> str:
    """Re-issue the cookie for an authenticated caller: keep its value if it has
    one, mint one if it's missing; either way refresh the lifetime."""
    return issue_csrf_cookie(response, settings, request.cookies.get(CSRF_COOKIE) or None)


def clear_csrf_cookie_after_logout(
    request: Request, response: Response, settings: Settings, *, logging_out: str
) -> None:
    """Delete the shared cookie unless another area's session cookie is still
    present (that session's mutations need it)."""
    others = [name for scope, name in COOKIE_NAMES.items() if scope != logging_out]
    if any(request.cookies.get(name) for name in others):
        return
    clear_csrf_cookie(response, settings)


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
