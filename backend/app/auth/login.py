"""Shared credential-login flow for both the student and admin scopes.

Rate-limits per IP and per email (scope-namespaced), verifies the password with
a generic failure, stamps `last_login_at`, opens a session, and sets the cookie.
"""

from __future__ import annotations

import datetime as dt

from fastapi import Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.cookies import set_session_cookie
from app.auth.csrf import issue_csrf_cookie
from app.auth.hashing import verify_password
from app.auth.ratelimit import RateLimiter, parse_rate
from app.auth.sessions import SessionScope, SessionStore
from app.config import Settings
from app.errors import APIError
from app.models.user import User, UserRole, normalize_email

_INVALID = APIError(
    status.HTTP_401_UNAUTHORIZED, "invalid_credentials", "Invalid email or password"
)


def login_flow(
    *,
    scope: SessionScope,
    role: UserRole,
    email: str,
    password: str,
    request: Request,
    response: Response,
    db: Session,
    store: SessionStore,
    limiter: RateLimiter,
    settings: Settings,
) -> User:
    limit, window = parse_rate(settings.login_rate_limit)
    normalized = normalize_email(email)
    ip = request.client.host if request.client else "unknown"
    ok_ip = limiter.hit(f"rl:login:{scope}:ip:{ip}", limit, window)
    ok_email = limiter.hit(f"rl:login:{scope}:email:{normalized}", limit, window)
    if not (ok_ip and ok_email):
        raise APIError(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "rate_limited",
            "Too many attempts. Try again later.",
        )

    user = db.scalar(select(User).where(User.email == normalized))
    if (
        user is None
        or user.role is not role
        or not user.is_active
        or not verify_password(user.password_hash, password)
    ):
        raise _INVALID

    user.last_login_at = dt.datetime.now(tz=dt.UTC)
    db.flush()
    token = store.create(str(user.id), scope)
    set_session_cookie(response, scope, token, store, settings)
    issue_csrf_cookie(response, settings)
    return user
