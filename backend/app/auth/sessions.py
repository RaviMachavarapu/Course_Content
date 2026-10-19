"""Redis-backed opaque sessions.

The cookie carries only a random token; all state lives in Redis under
``sess:<scope>:<token>`` and expires with a sliding TTL. Admin and student
sessions use different scopes, cookie names, and TTLs so the two logins never
cross over.
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


def _key(scope: SessionScope, token: str) -> str:
    return f"sess:{scope}:{token}"


class SessionStore:
    def __init__(self, client: redis.Redis[str], settings: Settings) -> None:
        self._r = client
        self._settings = settings

    def ttl_seconds(self, scope: SessionScope) -> int:
        if scope == "admin":
            return self._settings.admin_session_ttl_hours * 3600
        return self._settings.student_session_ttl_days * 86400

    def create(self, user_id: str, scope: SessionScope) -> str:
        token = secrets.token_urlsafe(_TOKEN_BYTES)
        payload = SessionData(
            user_id=user_id,
            scope=scope,
            created_at=dt.datetime.now(tz=dt.UTC).isoformat(),
        )
        self._r.setex(_key(scope, token), self.ttl_seconds(scope), json.dumps(payload.__dict__))
        return token

    def read(self, scope: SessionScope, token: str | None) -> SessionData | None:
        if not token:
            return None
        raw = self._r.get(_key(scope, token))
        if raw is None:
            return None
        # sliding expiry
        self._r.expire(_key(scope, token), self.ttl_seconds(scope))
        data = json.loads(raw)
        return SessionData(
            user_id=data["user_id"], scope=data["scope"], created_at=data["created_at"]
        )

    def destroy(self, scope: SessionScope, token: str | None) -> None:
        if token:
            self._r.delete(_key(scope, token))
