"""Storage key construction and validation.

Scheme (T017):
    courses/{course_id}/modules/{module_id}/artifacts/{artifact_id}/v{rev}/{kind}[.{page}].{ext}
"""

from __future__ import annotations

import re
import uuid

from app.models.enums import MediaFileKind

_SEGMENT = r"[A-Za-z0-9][A-Za-z0-9._-]*"
_KEY_RE = re.compile(rf"^{_SEGMENT}(?:/{_SEGMENT})*$")


class InvalidKeyError(ValueError):
    """A storage key is malformed or attempts path traversal."""


def validate_key(key: str) -> str:
    """Return `key` unchanged if safe; otherwise raise `InvalidKeyError`."""
    if not key or key != key.strip():
        raise InvalidKeyError("key is empty or has surrounding whitespace")
    if key.startswith("/") or key.endswith("/") or "//" in key:
        raise InvalidKeyError(f"bad slashes in key: {key!r}")
    if "\\" in key or "\x00" in key:
        raise InvalidKeyError(f"illegal character in key: {key!r}")
    if any(seg in ("", ".", "..") for seg in key.split("/")):
        raise InvalidKeyError(f"path traversal in key: {key!r}")
    if not _KEY_RE.match(key):
        raise InvalidKeyError(f"key does not match the allowed pattern: {key!r}")
    return key


def media_key(
    *,
    course_id: uuid.UUID,
    module_id: uuid.UUID,
    artifact_id: uuid.UUID,
    revision: int,
    kind: MediaFileKind,
    ext: str,
    page_index: int | None = None,
) -> str:
    ext = ext.lstrip(".")
    leaf = kind.value if page_index is None else f"{kind.value}.{page_index:04d}"
    key = (
        f"courses/{course_id}/modules/{module_id}/artifacts/{artifact_id}"
        f"/v{revision}/{leaf}.{ext}"
    )
    return validate_key(key)
