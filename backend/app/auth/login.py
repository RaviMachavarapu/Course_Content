"""Shared credential-login flow for both the student and admin scopes.

Rate-limits *failed* attempts per client IP and per email (scope-namespaced; a
success clears the email's count), verifies the password with a generic failure
and constant work, stamps `last_login_at`, opens a session, and sets the cookie.
"""

from __future__ import annotations

import datetime as dt

from fastapi import Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.cookies import set_session_cookie
from app.auth.csrf import issue_csrf_cookie
from app.auth.hashing import dummy_hash, verify_password
from app.auth.ratelimit import RateLimiter, client_ip, parse_rate
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
    ip_key = f"rl:login:{scope}:ip:{client_ip(request)}"
    email_key = f"rl:login:{scope}:email:{normalized}"
    # Only failures count: a class logging in from one school NAT must not
    # trip the limit. Check before doing any work, count after a failure.
    if limiter.peek(ip_key) >= limit or limiter.peek(email_key) >= limit:
        raise APIError(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "rate_limited",
            "Too many attempts. Try again later.",
        )

    user = db.scalar(select(User).where(User.email == normalized))
    if user is not None and (user.role is not role or not user.is_active):
        user = None
    # Always run one Argon2 verify so "no such account" isn't faster than
    # "wrong password".
    password_ok = verify_password(user.password_hash if user else dummy_hash(), password)
    if user is None or not password_ok:
        limiter.hit(ip_key, limit, window)
        limiter.hit(email_key, limit, window)
        raise _INVALID

    limiter.reset(email_key)
    user.last_login_at = dt.datetime.now(tz=dt.UTC)
    db.flush()
    token = store.create(str(user.id), scope)
    set_session_cookie(response, scope, token, store, settings)
    issue_csrf_cookie(response, settings)
    return user
