"""Trusted-device cookie (login protection spec §1).

On every successful login the browser gets ``sdp_device_<scope>``: an
HMAC-signed token over (user id, scope, issued-at, random nonce, credential
stamp). A later login attempt presenting a valid token for the same account is
counted per device instead of per email, so an attacker hammering a known email
can't hold up the owner's own browser.

The credential stamp is derived from the stored password hash, so changing or
resetting the password invalidates every device cookie of that user without a
database column.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass

from app.auth.sessions import SessionScope
from app.config import Settings

DEVICE_COOKIE_NAMES: dict[SessionScope, str] = {
    "student": "sdp_device_student",
    "admin": "sdp_device_admin",
}
_VERSION = "v1"
_SCOPES: frozenset[str] = frozenset(DEVICE_COOKIE_NAMES)


@dataclass(frozen=True)
class DeviceClaims:
    user_id: str
    scope: SessionScope
    issued_at: int
    nonce: str
    stamp: str


def max_age_seconds(settings: Settings) -> int:
    return settings.device_cookie_max_age_days * 86400


def _mac(settings: Settings, message: str) -> bytes:
    return hmac.new(
        settings.device_cookie_secret.encode(), message.encode(), hashlib.sha256
    ).digest()


def credential_stamp(settings: Settings, password_hash: str) -> str:
    """Changes whenever the password does. Keyed, so the cookie says nothing
    about the hash itself."""
    return _mac(settings, f"stamp:{password_hash}").hex()[:16]


def _sign(settings: Settings, payload: str) -> str:
    return base64.urlsafe_b64encode(_mac(settings, f"device:{payload}")).decode().rstrip("=")


def issue_device_token(
    settings: Settings, *, user_id: str, scope: SessionScope, password_hash: str, now: float
) -> str:
    payload = ".".join(
        [
            _VERSION,
            user_id,
            scope,
            str(int(now)),
            secrets.token_urlsafe(16),
            credential_stamp(settings, password_hash),
        ]
    )
    return f"{payload}.{_sign(settings, payload)}"


def read_device_token(
    settings: Settings, token: str | None, *, scope: SessionScope, now: float
) -> DeviceClaims | None:
    """The claims of a genuine, unexpired token for this scope; else None.
    Whether it belongs to the account being signed into is `matches`."""
    if not token:
        return None
    payload, _, signature = token.rpartition(".")
    if not payload or not hmac.compare_digest(signature, _sign(settings, payload)):
        return None
    parts = payload.split(".")
    if len(parts) != 6 or parts[0] != _VERSION:
        return None
    _, user_id, token_scope, issued, nonce, stamp = parts
    if token_scope != scope or token_scope not in _SCOPES:
        return None
    try:
        issued_at = int(issued)
    except ValueError:
        return None
    if now - issued_at >= max_age_seconds(settings):
        return None
    return DeviceClaims(user_id=user_id, scope=scope, issued_at=issued_at, nonce=nonce, stamp=stamp)


def matches(
    settings: Settings, claims: DeviceClaims | None, *, user_id: str, password_hash: str
) -> bool:
    """Same account, and its password hasn't changed since the cookie was set."""
    return (
        claims is not None
        and hmac.compare_digest(claims.user_id, user_id)
        and hmac.compare_digest(claims.stamp, credential_stamp(settings, password_hash))
    )
