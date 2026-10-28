"""Password hashing — Argon2id via argon2-cffi.

`PasswordHasher`'s defaults are Argon2id with OWASP-aligned parameters. Hashes
are self-describing (`$argon2id$v=19$m=...`), so parameter upgrades are handled
transparently by `verify_password` + `needs_rehash`.
"""

from __future__ import annotations

import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

_hasher = PasswordHasher()
_dummy_hash: str | None = None


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """True iff `password` matches `password_hash`. Never raises."""
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError, ValueError):
        return False


def dummy_hash() -> str:
    """A real Argon2 hash of a random secret, for verifying against when there
    is no account — so an unknown email costs the same time as a wrong password."""
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = _hasher.hash(secrets.token_urlsafe(16))
    return _dummy_hash


def needs_rehash(password_hash: str) -> bool:
    """True when the stored hash was made with weaker-than-current parameters."""
    try:
        return _hasher.check_needs_rehash(password_hash)
    except (InvalidHashError, ValueError):
        return True
