"""Tokenised, single-use, 30-minute password reset (O6).

Tokens live in Redis (same pattern as sessions/CSRF — no migration needed):
`pwreset:{token} -> "{scope}:{user_id}"`, TTL 1800s. Redeeming one is an atomic
GETDEL, so a token can never be used twice, even concurrently. A user has at most
one live token: `pwreset_user:{scope}:{user_id}` points at it, and issuing a
new one deletes the previous. A successful reset revokes all the user's
sessions. `request_password_reset` / `confirm_password_reset` are shared by the
student and admin routers, mirroring how `login_flow` is shared for login.
"""

from __future__ import annotations

import secrets
import uuid
from typing import TYPE_CHECKING, Literal

from fastapi import BackgroundTasks, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.cookies import set_device_cookie
from app.auth.device import issue_device_token
from app.auth.hashing import hash_password
from app.auth.passwords import validate_password_strength
from app.auth.ratelimit import RateLimiter, parse_rate
from app.auth.sessions import SessionStore
from app.config import Settings
from app.errors import APIError
from app.logging import get_logger
from app.models.user import User, UserRole, normalize_email
from app.services.mail import send_mail

if TYPE_CHECKING:
    import redis

    RedisClient = redis.Redis[str]
else:
    RedisClient = object

log = get_logger("auth.password_reset")

ResetScope = Literal["student", "admin"]

_TTL_SECONDS = 30 * 60
#: reset mails one address can receive per hour (beyond: silently none)
PER_EMAIL_REQUESTS_PER_HOUR = 3
_PREFIX = "pwreset"
_ROLE_BY_SCOPE: dict[ResetScope, UserRole] = {
    "student": UserRole.student,
    "admin": UserRole.admin,
}


def _user_key(scope: ResetScope, user_id: uuid.UUID) -> str:
    return f"{_PREFIX}_user:{scope}:{user_id}"


def issue_reset_token(redis_client: RedisClient, *, user_id: uuid.UUID, scope: ResetScope) -> str:
    token = secrets.token_urlsafe(32)
    redis_client.setex(f"{_PREFIX}:{token}", _TTL_SECONDS, f"{scope}:{user_id}")
    previous = redis_client.set(_user_key(scope, user_id), token, ex=_TTL_SECONDS, get=True)
    if previous:
        redis_client.delete(f"{_PREFIX}:{previous}")
    return token


def consume_reset_token(
    redis_client: RedisClient, *, token: str, scope: ResetScope
) -> uuid.UUID | None:
    raw = redis_client.getdel(f"{_PREFIX}:{token}")
    if raw is None:
        return None
    stored_scope, _, user_id_str = raw.partition(":")
    try:
        user_id = uuid.UUID(user_id_str)
    except ValueError:
        return None
    if stored_scope in _ROLE_BY_SCOPE:
        _forget_pointer(redis_client, _user_key(stored_scope, user_id), token)
    if stored_scope != scope:
        return None
    return user_id


def _forget_pointer(redis_client: RedisClient, key: str, token: str) -> None:
    if redis_client.get(key) == token:
        redis_client.delete(key)


def _ensure_enabled(settings: Settings) -> None:
    if not settings.password_reset_enabled:
        raise APIError(
            status.HTTP_404_NOT_FOUND,
            "password_reset_disabled",
            "Password reset is not available. Contact your administrator.",
        )


def request_password_reset(
    db: Session,
    redis_client: RedisClient,
    settings: Settings,
    limiter: RateLimiter,
    background: BackgroundTasks,
    *,
    scope: ResetScope,
    email: str,
    client_ip: str,
    reset_path: str,
) -> None:
    """Never reveals whether the email exists: the response is the same 202 for
    a real account, an unknown email, a capped email and a mail failure. Mail
    goes out as a background task after the response is sent, so an SMTP round
    trip (or outage) can't be timed or turn into a 500.

    Limits: per client IP → 429 (says nothing about any account); per email →
    silently stop sending (stops mail-bombing one inbox from many IPs)."""
    _ensure_enabled(settings)
    limit, window = parse_rate(settings.password_reset_rate_limit)
    if not limiter.hit(f"rl:pwreset:{scope}:ip:{client_ip}", limit, window):
        raise APIError(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "rate_limited",
            "Too many attempts. Try again later.",
        )
    normalized = normalize_email(email)
    if not limiter.hit(f"rl:pwreset:{scope}:email:{normalized}", PER_EMAIL_REQUESTS_PER_HOUR, 3600):
        return
    user = db.scalar(
        select(User).where(User.email == normalized, User.role == _ROLE_BY_SCOPE[scope])
    )
    if user is None or not user.is_active:
        return
    token = issue_reset_token(redis_client, user_id=user.id, scope=scope)
    link = f"{settings.public_base_url}{reset_path}?token={token}"
    background.add_task(
        _send_reset_mail,
        settings,
        to=user.email,
        body=(
            f"Hi {user.display_name},\n\n"
            f"Use this link to set a new password. It expires in 30 minutes "
            f"and can only be used once.\n\n{link}\n\n"
            "If you didn't request this, you can ignore this email."
        ),
    )


def _send_reset_mail(settings: Settings, *, to: str, body: str) -> None:
    try:
        send_mail(settings, to=to, subject="Reset your Shikshak Dp password", body=body)
    except Exception:
        log.exception("pwreset.mail_failed", to=to)


def confirm_password_reset(
    db: Session,
    redis_client: RedisClient,
    settings: Settings,
    sessions: SessionStore,
    *,
    scope: ResetScope,
    token: str,
    new_password: str,
) -> User:
    """Set the new password and sign every session out. Returns the user: the
    caller marks the redeeming browser as a trusted device (owner decision
    2026-10-29), since opening the mailed link proves the account is theirs."""
    _ensure_enabled(settings)
    validate_password_strength(new_password)
    user_id = consume_reset_token(redis_client, token=token, scope=scope)
    if user_id is None:
        raise APIError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "invalid_token",
            "This reset link is invalid or has expired.",
        )
    user = db.get(User, user_id)
    if user is None or user.role is not _ROLE_BY_SCOPE[scope]:
        raise APIError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "invalid_token",
            "This reset link is invalid or has expired.",
        )
    user.password_hash = hash_password(new_password)
    db.flush()
    # whoever held a session (perhaps the reason for the reset) is signed out
    sessions.revoke_user(str(user.id))
    return user


def trust_redeeming_browser(
    response: Response, settings: Settings, *, scope: ResetScope, user: User, now: float
) -> None:
    """A fresh device cookie, stamped with the new password, for the browser
    that completed the reset (every other device cookie stopped matching)."""
    set_device_cookie(
        response,
        scope,
        issue_device_token(
            settings, user_id=str(user.id), scope=scope, password_hash=user.password_hash, now=now
        ),
        settings,
    )
