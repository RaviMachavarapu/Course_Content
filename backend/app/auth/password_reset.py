"""Tokenised, single-use, 30-minute password reset (O6).

Tokens live in Redis (same pattern as sessions/CSRF — no migration needed):
`pwreset:{token} -> "{scope}:{user_id}"`, TTL 1800s. Redeeming one deletes it
immediately, so a token can never be replayed. `request_password_reset` /
`confirm_password_reset` are shared by the student and admin routers, mirroring
how `login_flow` is shared for login.
"""

from __future__ import annotations

import secrets
import uuid
from typing import TYPE_CHECKING, Literal

from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.hashing import hash_password
from app.auth.passwords import validate_password_strength
from app.config import Settings
from app.errors import APIError
from app.models.user import User, UserRole, normalize_email
from app.services.mail import send_mail

if TYPE_CHECKING:
    import redis

    RedisClient = redis.Redis[str]
else:
    RedisClient = object

ResetScope = Literal["student", "admin"]

_TTL_SECONDS = 30 * 60
_PREFIX = "pwreset"
_ROLE_BY_SCOPE: dict[ResetScope, UserRole] = {
    "student": UserRole.student,
    "admin": UserRole.admin,
}


def issue_reset_token(redis_client: RedisClient, *, user_id: uuid.UUID, scope: ResetScope) -> str:
    token = secrets.token_urlsafe(32)
    redis_client.setex(f"{_PREFIX}:{token}", _TTL_SECONDS, f"{scope}:{user_id}")
    return token


def consume_reset_token(
    redis_client: RedisClient, *, token: str, scope: ResetScope
) -> uuid.UUID | None:
    key = f"{_PREFIX}:{token}"
    raw = redis_client.get(key)
    if raw is None:
        return None
    redis_client.delete(key)
    stored_scope, _, user_id_str = raw.partition(":")
    if stored_scope != scope:
        return None
    try:
        return uuid.UUID(user_id_str)
    except ValueError:
        return None


def request_password_reset(
    db: Session,
    redis_client: RedisClient,
    settings: Settings,
    *,
    scope: ResetScope,
    email: str,
    reset_path: str,
) -> None:
    """Never reveals whether the email exists — always "succeeds" from the
    caller's point of view. Only sends mail when there's a real, active
    account for that scope."""
    user = db.scalar(
        select(User).where(User.email == normalize_email(email), User.role == _ROLE_BY_SCOPE[scope])
    )
    if user is None or not user.is_active:
        return
    token = issue_reset_token(redis_client, user_id=user.id, scope=scope)
    link = f"{settings.public_base_url}{reset_path}?token={token}"
    send_mail(
        settings,
        to=user.email,
        subject="Reset your Shikshak Dp password",
        body=(
            f"Hi {user.display_name},\n\n"
            f"Use this link to set a new password. It expires in 30 minutes "
            f"and can only be used once.\n\n{link}\n\n"
            "If you didn't request this, you can ignore this email."
        ),
    )


def confirm_password_reset(
    db: Session,
    redis_client: RedisClient,
    *,
    scope: ResetScope,
    token: str,
    new_password: str,
) -> None:
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
