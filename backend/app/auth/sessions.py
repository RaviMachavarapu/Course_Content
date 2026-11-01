"""Redis-backed opaque sessions.

The cookie carries only a random token; all state lives in Redis under
``sess:<scope>:<token>``. Admin and student sessions use different scopes,
cookie names, and lifetimes so the two logins never cross over.

Lifetime (owner decision 2026-10-29): an idle timeout (admin 8 h, student 30
days) that authenticated requests renew, and an absolute maximum after sign-in
(admin 7 days, student 30 days). Renewal costs no write on most requests: the
TTL is pushed back only once less than half the idle window is left. The cookie
lives as long as the absolute maximum, so the browser never drops a session the
server still honours; the server ends it earlier when it goes idle.

Revocation: `revoke_user` stamps ``sess_epoch:<user_id>`` with the current time;
`read` rejects (and deletes) any session of that user created at or before the
stamp. That covers every session — including ones created before this existed —
without keeping a per-user index of tokens.
"""

from __future__ import annotations

import datetime as dt
import json
import secrets
from dataclasses import dataclass
from typing import Literal

import redis

from app.config import Settings

SessionScope = Literal["student", "admin"]

COOKIE_NAMES: dict[SessionScope, str] = {"student": "sdp_student", "admin": "sdp_admin"}
_TOKEN_BYTES = 32


@dataclass(frozen=True)
class SessionData:
    user_id: str
    scope: SessionScope
    created_at: str
    #: signed in with "Remember this device" (logging out of a session that
    #: wasn't remembered also drops the device cookie). Sessions from before
    #: the checkbox existed always set the cookie, so they count as remembered.
    remember: bool = True


def _key(scope: SessionScope, token: str) -> str:
    return f"sess:{scope}:{token}"


def _epoch_key(user_id: str) -> str:
    return f"sess_epoch:{user_id}"


def idle_seconds(settings: Settings, scope: SessionScope) -> int:
    if scope == "admin":
        return settings.admin_session_ttl_hours * 3600
    return settings.student_session_ttl_days * 86400


def max_seconds(settings: Settings, scope: SessionScope) -> int:
    if scope == "admin":
        return settings.admin_session_max_days * 86400
    return settings.student_session_max_days * 86400


class SessionStore:
    def __init__(self, client: redis.Redis[str], settings: Settings) -> None:
        self._r = client
        self._settings = settings

    def ttl_seconds(self, scope: SessionScope) -> int:
        """The idle timeout."""
        return idle_seconds(self._settings, scope)

    def max_seconds(self, scope: SessionScope) -> int:
        """The absolute maximum (also the session cookie's max-age)."""
        return max_seconds(self._settings, scope)

    def create(self, user_id: str, scope: SessionScope, *, remember: bool = False) -> str:
        token = secrets.token_urlsafe(_TOKEN_BYTES)
        payload = SessionData(
            user_id=user_id,
            scope=scope,
            created_at=dt.datetime.now(tz=dt.UTC).isoformat(),
            remember=remember,
        )
        ttl = min(self.ttl_seconds(scope), self.max_seconds(scope))
        self._r.setex(_key(scope, token), ttl, json.dumps(payload.__dict__))
        return token

    def read(self, scope: SessionScope, token: str | None) -> SessionData | None:
        if not token:
            return None
        key = _key(scope, token)
        pipe = self._r.pipeline()
        pipe.get(key)
        pipe.ttl(key)
        raw, ttl = pipe.execute()
        if raw is None:
            return None
        data = json.loads(raw)
        session = SessionData(
            user_id=data["user_id"],
            scope=data["scope"],
            created_at=data["created_at"],
            remember=bool(data.get("remember", True)),
        )
        created = dt.datetime.fromisoformat(session.created_at)
        epoch = self._r.get(_epoch_key(session.user_id))
        if epoch is not None and created <= dt.datetime.fromisoformat(epoch):
            self._r.delete(key)
            return None
        life_left = self.max_seconds(scope) - (dt.datetime.now(tz=dt.UTC) - created).total_seconds()
        if life_left <= 0:
            self._r.delete(key)
            return None
        # renew while active, but write only when less than half the idle
        # window is left, and never past the absolute maximum
        idle = self.ttl_seconds(scope)
        if ttl is not None and ttl < idle / 2:
            renewed = int(min(idle, life_left))
            if renewed > ttl:
                self._r.expire(key, max(1, renewed))
        return session

    def revoke_user(self, user_id: str) -> None:
        """Invalidate every existing session of this user, in both scopes."""
        longest = max(self.max_seconds("admin"), self.max_seconds("student"))
        self._r.setex(_epoch_key(user_id), longest, dt.datetime.now(tz=dt.UTC).isoformat())

    def destroy(self, scope: SessionScope, token: str | None) -> None:
        if token:
            self._r.delete(_key(scope, token))
