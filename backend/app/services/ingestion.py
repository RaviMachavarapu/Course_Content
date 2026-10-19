"""Source-URL validation for module ingestion (spec.md §3.2)."""

from __future__ import annotations

from urllib.parse import urlparse

from app.models.enums import ModuleSourceType

_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}
_DRIVE_HOSTS = {"drive.google.com", "docs.google.com"}

SUPPORTED_HINT = "YouTube, Google Drive, a direct .pdf link, or any http(s) web page"


def detect_source_type(url: str) -> ModuleSourceType | None:
    """Classify a source URL, or return None if the shape/host is unsupported."""
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    host = parsed.netloc.lower().split(":")[0]
    path = parsed.path.lower()

    if host in _YOUTUBE_HOSTS:
        return ModuleSourceType.youtube
    if host in _DRIVE_HOSTS:
        return ModuleSourceType.drive
    if path.endswith(".pdf"):
        return ModuleSourceType.pdf
    return ModuleSourceType.web
