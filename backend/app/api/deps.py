"""Shared FastAPI dependencies.

Settings, Redis, session store, rate limiter, and the per-scope current-user
guards. Admin guards land in T009; RBAC/CSRF in T010.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from functools import lru_cache
from typing import TYPE_CHECKING, Annotated

import redis
from fastapi import Depends, Request, status
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    RedisClient = redis.Redis[str]
else:
    RedisClient = redis.Redis  # `redis.Redis` is only generic in the type stubs

from app.auth.ratelimit import RateLimiter
from app.auth.sessions import COOKIE_NAMES, SessionScope, SessionStore
from app.config import Settings, get_settings
from app.db.session import get_db
from app.errors import APIError
from app.models.user import User, UserRole

SettingsDep = Annotated[Settings, Depends(get_settings)]
DbDep = Annotated[Session, Depends(get_db)]


@lru_cache
def _redis_client() -> RedisClient:
    return redis.Redis.from_url(get_settings().redis_url, decode_responses=True)


def get_redis() -> RedisClient:
    return _redis_client()


RedisDep = Annotated[RedisClient, Depends(get_redis)]


def get_session_store(redis_client: RedisDep, settings: SettingsDep) -> SessionStore:
    return SessionStore(redis_client, settings)


def get_rate_limiter(redis_client: RedisDep) -> RateLimiter:
    return RateLimiter(redis_client)


#: seconds since the epoch; tests override `get_clock` with a fake clock
Clock = Callable[[], float]


def get_clock() -> Clock:
    return time.time


SessionStoreDep = Annotated[SessionStore, Depends(get_session_store)]
ClockDep = Annotated[Clock, Depends(get_clock)]
RateLimiterDep = Annotated[RateLimiter, Depends(get_rate_limiter)]


def _load_user_for_scope(
    request: Request, db: Session, store: SessionStore, role: UserRole
) -> User:
    scope: SessionScope = "student" if role is UserRole.student else "admin"
    session = store.read(scope, request.cookies.get(COOKIE_NAMES[scope]))
    unauth = APIError(status.HTTP_401_UNAUTHORIZED, "unauthorized", "Not authenticated")
    if session is None:
        raise unauth
    try:
        user = db.get(User, uuid.UUID(session.user_id))
    except ValueError:
        raise unauth from None
    if user is None or not user.is_active or user.role is not role:
        raise unauth
    return user


def current_student(request: Request, db: DbDep, store: SessionStoreDep) -> User:
    return _load_user_for_scope(request, db, store, UserRole.student)


def current_admin(request: Request, db: DbDep, store: SessionStoreDep) -> User:
    return _load_user_for_scope(request, db, store, UserRole.admin)


def current_any_user(request: Request, db: DbDep, store: SessionStoreDep) -> User:
    """Either a valid admin or a valid student session (media access)."""
    for role in (UserRole.admin, UserRole.student):
        try:
            return _load_user_for_scope(request, db, store, role)
        except APIError:
            continue
    raise APIError(status.HTTP_401_UNAUTHORIZED, "unauthorized", "Not authenticated")


CurrentStudent = Annotated[User, Depends(current_student)]
CurrentAdmin = Annotated[User, Depends(current_admin)]
CurrentAnyUser = Annotated[User, Depends(current_any_user)]

__all__ = [
    "Clock",
    "ClockDep",
    "CurrentAdmin",
    "CurrentAnyUser",
    "CurrentStudent",
    "DbDep",
    "RateLimiterDep",
    "RedisDep",
    "SessionStoreDep",
    "SettingsDep",
    "current_admin",
    "current_any_user",
    "current_student",
    "get_clock",
    "get_redis",
    "get_settings",
]
