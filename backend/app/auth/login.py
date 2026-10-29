"""Shared credential-login flow for both the student and admin scopes
(login protection: docs/superpowers/specs/2026-10-29-login-protection.md).

- **Per IP**: failures only, `LOGIN_RATE_LIMIT` (default 100 per 15 min) in a
  sliding window → 429 until the oldest failure leaves the window.
- **Per email**: no hard block. The first `LOGIN_FREE_FAILURES` failures in the
  sliding `LOGIN_FAILURE_WINDOW_SEC` are free; from the next one on, the next
  attempt must wait 2, 4, 8 … s (capped at 60) after the last failure. Unknown
  emails are counted exactly like known ones.
- **Per trusted device**: an attempt carrying a valid ``sdp_device_<scope>``
  cookie for the same account (auth.device) skips the per-email delay and has
  its own counter with `LOGIN_DEVICE_FREE_FAILURES` free failures.
- An attempt made too early is a 429 ``rate_limited`` with ``retry_after`` and
  ``Retry-After``; the password isn't checked and it isn't a failure.
- A success clears the email's (and the device's) count.
- After 5 consecutive failures without a device cookie the account's owner is
  mailed (at most once an hour), after the response is sent.

Counters are Redis sorted sets of failure timestamps from the injected clock,
so tests can drive time; their Redis TTLs only clean up. The limit check and
recording the attempt are one Lua call (`_RESERVE_LUA`), so concurrent
requests can't all slip through the same opening.
"""

from __future__ import annotations

import datetime as dt
import math
import secrets
from typing import TYPE_CHECKING

from fastapi import Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.background import BackgroundTasks

from app.auth.cookies import set_device_cookie, set_session_cookie
from app.auth.csrf import issue_csrf_cookie
from app.auth.device import DEVICE_COOKIE_NAMES, issue_device_token, matches, read_device_token
from app.auth.hashing import dummy_hash, verify_password
from app.auth.ratelimit import client_ip, parse_rate
from app.auth.sessions import SessionScope, SessionStore
from app.config import Settings
from app.errors import APIError
from app.logging import get_logger
from app.models.user import User, UserRole, normalize_email
from app.services.mail import send_mail

if TYPE_CHECKING:
    from collections.abc import Callable

    import redis

    RedisClient = redis.Redis[str]
else:
    RedisClient = object

log = get_logger("auth.login")

#: consecutive failures (no device cookie) that trigger the owner's alert mail
ALERT_AFTER_FAILURES = 5
ALERT_INTERVAL_SEC = 3600
#: a run of failures is forgotten after a day without any
_STREAK_TTL_SEC = 86400
ALERT_SUBJECT = "Several failed sign-ins to your account"
_FORGOT_PATH: dict[SessionScope, str] = {
    "student": "/forgot-password",
    "admin": "/admin/forgot-password",
}


def growing_delay(failures: int, *, free: int, base: int, cap: int) -> int:
    """Seconds the next attempt must wait after the last failure: none for the
    first `free` failures, then base, 2·base, 4·base … capped at `cap`."""
    if failures <= free:
        return 0
    return int(min(base * 2 ** (failures - free - 1), cap))


#: Atomically: drop failures older than each window, decide whether this
#: attempt may run (per-IP cap; per-account growing delay), and if so record it
#: as a provisional failure in both sets — so a burst sent the moment a wait
#: ends gets exactly one password check. Returns "" when reserved, else the
#: wait in seconds.
#: KEYS: ip set, account set. ARGV: now, member, ttl, ip_limit, ip_window,
#: window, free, base, cap.
_RESERVE_LUA = """
local now = tonumber(ARGV[1])
local member = ARGV[2]
local ttl = tonumber(ARGV[3])
local ip_limit, ip_window = tonumber(ARGV[4]), tonumber(ARGV[5])
local window, free = tonumber(ARGV[6]), tonumber(ARGV[7])
local base, cap = tonumber(ARGV[8]), tonumber(ARGV[9])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - ip_window)
redis.call('ZREMRANGEBYSCORE', KEYS[2], '-inf', now - window)
local wait = 0
if redis.call('ZCARD', KEYS[1]) >= ip_limit then
  local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
  wait = tonumber(oldest[2]) + ip_window - now
end
local count = redis.call('ZCARD', KEYS[2])
if count > free then
  local delay = math.min(base * 2 ^ (count - free - 1), cap)
  local latest = redis.call('ZRANGE', KEYS[2], -1, -1, 'WITHSCORES')
  wait = math.max(wait, tonumber(latest[2]) + delay - now)
end
if wait > 0 then
  return string.format('%.6f', wait)
end
redis.call('ZADD', KEYS[1], now, member)
redis.call('ZADD', KEYS[2], now, member)
redis.call('EXPIRE', KEYS[1], ttl)
redis.call('EXPIRE', KEYS[2], ttl)
return ''
"""


def _reserve(
    redis_client: RedisClient,
    *,
    ip_key: str,
    account_key: str,
    member: str,
    now: float,
    ttl: int,
    ip_limit: int,
    ip_window: int,
    window: int,
    free: int,
    settings: Settings,
) -> float:
    """0 when the attempt is reserved (recorded as a provisional failure),
    else the seconds to wait (nothing recorded)."""
    result = redis_client.eval(  # type: ignore[no-untyped-call]  # untyped in the stubs
        _RESERVE_LUA,
        2,
        ip_key,
        account_key,
        repr(now),
        member,
        ttl,
        ip_limit,
        ip_window,
        window,
        free,
        settings.login_delay_base_sec,
        settings.login_delay_max_sec,
    )
    return float(result) if result else 0.0


def _rate_limited(wait: float) -> APIError:
    retry_after = max(1, math.ceil(wait - 1e-6))
    return APIError(
        status.HTTP_429_TOO_MANY_REQUESTS,
        "rate_limited",
        "Too many attempts. Try again later.",
        headers={"Retry-After": str(retry_after)},
        extra={"retry_after": retry_after},
    )


def _invalid(background: BackgroundTasks | None = None) -> APIError:
    return APIError(
        status.HTTP_401_UNAUTHORIZED,
        "invalid_credentials",
        "Invalid email or password",
        background=background,
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
    redis_client: RedisClient,
    settings: Settings,
    clock: Callable[[], float],
) -> User:
    now = clock()
    normalized = normalize_email(email)
    ns = f"lg:{scope}"
    ip_key = f"{ns}:ip:{client_ip(request)}"
    email_key = f"{ns}:email:{normalized}"
    ip_limit, ip_window = parse_rate(settings.login_rate_limit)
    window = settings.login_failure_window_sec
    ttl = max(ip_window, window) + settings.login_delay_max_sec

    user = db.scalar(select(User).where(User.email == normalized))
    if user is not None and (user.role is not role or not user.is_active):
        user = None
    claims = read_device_token(
        settings, request.cookies.get(DEVICE_COOKIE_NAMES[scope]), scope=scope, now=now
    )
    trusted = (
        claims is not None
        and user is not None
        and matches(settings, claims, user_id=str(user.id), password_hash=user.password_hash)
    )
    if trusted and claims is not None:
        account_key, free = f"{ns}:device:{claims.nonce}", settings.login_device_free_failures
    else:
        account_key, free = email_key, settings.login_free_failures

    # Check and reserve in one atomic step, before any work: an early attempt
    # is rejected without checking the password and isn't a failure; an
    # allowed one is recorded as a failure now, so concurrent attempts see it.
    member = f"{now}:{secrets.token_hex(8)}"
    wait = _reserve(
        redis_client,
        ip_key=ip_key,
        account_key=account_key,
        member=member,
        now=now,
        ttl=ttl,
        ip_limit=ip_limit,
        ip_window=ip_window,
        window=window,
        free=free,
        settings=settings,
    )
    if wait > 0:
        raise _rate_limited(wait)

    # Always run one Argon2 verify so "no such account" isn't faster than
    # "wrong password".
    password_ok = verify_password(user.password_hash if user else dummy_hash(), password)
    if user is None or not password_ok:
        # the reservation stays: it is this failure
        background = (
            None if trusted else _note_failure(redis_client, settings, scope, normalized, user, now)
        )
        raise _invalid(background)

    # successes never count: release the reservation, clear the account
    pipe = redis_client.pipeline()
    pipe.zrem(ip_key, member)
    pipe.delete(email_key, f"{ns}:streak:{normalized}", account_key)
    pipe.execute()
    user.last_login_at = dt.datetime.now(tz=dt.UTC)
    db.flush()
    token = store.create(str(user.id), scope)
    set_session_cookie(response, scope, token, store, settings)
    issue_csrf_cookie(response, settings)
    set_device_cookie(
        response,
        scope,
        issue_device_token(
            settings, user_id=str(user.id), scope=scope, password_hash=user.password_hash, now=now
        ),
        settings,
    )
    return user


def _note_failure(
    redis_client: RedisClient,
    settings: Settings,
    scope: SessionScope,
    email: str,
    user: User | None,
    now: float,
) -> BackgroundTasks | None:
    """Count a failure without a device cookie toward the owner's alert; the
    same Redis work for unknown emails, but only a real account gets mail."""
    streak_key = f"lg:{scope}:streak:{email}"
    alerted_key = f"lg:{scope}:alerted:{email}"
    pipe = redis_client.pipeline()
    pipe.incr(streak_key)
    # an unknown email's streak can never alert: let it go with the window
    # (same Redis work either way)
    pipe.expire(
        streak_key, _STREAK_TTL_SEC if user is not None else settings.login_failure_window_sec
    )
    pipe.get(alerted_key)
    streak, _, alerted = pipe.execute()
    if user is None or int(streak) < ALERT_AFTER_FAILURES:
        return None
    if alerted is not None and now - float(alerted) < ALERT_INTERVAL_SEC:
        return None
    redis_client.set(alerted_key, str(now), ex=ALERT_INTERVAL_SEC)
    when = dt.datetime.fromtimestamp(now, tz=dt.UTC).strftime("%Y-%m-%d %H:%M UTC")
    link = f"{settings.public_base_url}{_FORGOT_PATH[scope]}"
    tasks = BackgroundTasks()
    tasks.add_task(
        _send_alert_mail,
        settings,
        to=user.email,
        body=(
            f"Hi {user.display_name},\n\n"
            f"There have been several failed attempts to sign in to your Shikshak Dp "
            f"account ({user.email}), the latest at {when}.\n\n"
            "If this was you, there is nothing to do. If it wasn't, you can reset "
            f"your password here:\n\n{link}\n"
        ),
    )
    return tasks


def _send_alert_mail(settings: Settings, *, to: str, body: str) -> None:
    try:
        send_mail(settings, to=to, subject=ALERT_SUBJECT, body=body)
    except Exception:
        log.exception("login.alert_mail_failed", to=to)
