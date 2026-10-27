"""Storage key construction and validation.

Scheme (T017):
    courses/{course_id}/modules/{module_id}/artifacts/{artifact_id}/v{rev}/{kind}[.{page}][.{variant}].{ext}
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
    variant: str | None = None,
) -> str:
    """`variant` (e.g. a checksum prefix) gives a rebuilt file a new key, so a
    browser that cached the old one (media is served as immutable) gets the new."""
    ext = ext.lstrip(".")
    leaf = kind.value if page_index is None else f"{kind.value}.{page_index:04d}"
    if variant:
        leaf = f"{leaf}.{variant}"
    key = (
        f"courses/{course_id}/modules/{module_id}/artifacts/{artifact_id}"
        f"/v{revision}/{leaf}.{ext}"
    )
    return validate_key(key)


def upload_key(upload_id: uuid.UUID | str) -> str:
    """In-flight (pre-claim) chunked upload: `uploads/{id}.pdf`."""
    return validate_key(f"uploads/{upload_id}.pdf")


def source_key(
    course_id: uuid.UUID | str,
    module_id: uuid.UUID | str,
    order_index: int,
    safe_stem: str,
    part: int | None = None,
) -> str:
    """A module's source PDF (or one split part). `safe_stem` must already be
    sanitized by the caller."""
    leaf = f"{order_index:02d}-{safe_stem}" + (f".part{part}" if part is not None else "")
    return validate_key(f"courses/{course_id}/modules/{module_id}/sources/{leaf}.pdf")
