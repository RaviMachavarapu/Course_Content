"""T007 — Argon2id password hashing helpers."""

from __future__ import annotations

from app.auth.hashing import hash_password, needs_rehash, verify_password


def test_hash_is_argon2id_and_salted() -> None:
    h1 = hash_password("s3cret-passphrase")
    h2 = hash_password("s3cret-passphrase")
    assert h1.startswith("$argon2id$")
    assert h1 != h2  # random salt


def test_verify_accepts_correct_and_rejects_wrong() -> None:
    h = hash_password("s3cret-passphrase")
    assert verify_password(h, "s3cret-passphrase") is True
    assert verify_password(h, "wrong") is False


def test_verify_never_raises_on_garbage() -> None:
    assert verify_password("not-a-hash", "whatever") is False
    assert verify_password("", "whatever") is False


def test_needs_rehash_false_for_current_params_true_for_garbage() -> None:
    assert needs_rehash(hash_password("s3cret-passphrase")) is False
    assert needs_rehash("not-a-hash") is True
