"""Filesystem-backed media storage + a GC helper for superseded versions."""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.logging import get_logger
from app.models.artifact import Artifact
from app.models.artifact_version import ArtifactVersion
from app.models.enums import MediaFileKind
from app.models.media_file import MediaFile
from app.storage.keys import validate_key

log = get_logger("storage")

#: canonical file extension per media kind
STORAGE_EXTS: dict[MediaFileKind, str] = {
    MediaFileKind.pptx: "pptx",
    MediaFileKind.slide_png: "png",
    MediaFileKind.deck_pdf: "pdf",
    MediaFileKind.report_pdf: "pdf",
    MediaFileKind.infographic_png: "png",
    MediaFileKind.infographic_svg: "svg",
    MediaFileKind.audio_mp3: "mp3",
    MediaFileKind.audio_m4a: "m4a",
    MediaFileKind.cover: "png",
    MediaFileKind.hero: "png",
    MediaFileKind.flashcards_pdf: "pdf",
    MediaFileKind.quiz_pdf: "pdf",
    MediaFileKind.quiz_questions_pdf: "pdf",
    MediaFileKind.infographic_pdf: "pdf",
    MediaFileKind.slides_handout_pdf: "pdf",
}


@dataclass(frozen=True)
class StoredFile:
    key: str
    mime_type: str
    size_bytes: int
    checksum_sha256: str


class Storage:
    def __init__(self, root: Path | str, public_base_url: str) -> None:
        self._root = Path(root).resolve()
        self._public_base_url = public_base_url.rstrip("/")
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        validate_key(key)
        path = (self._root / key).resolve()
        if path != self._root and self._root not in path.parents:
            raise ValueError(f"resolved path escapes MEDIA_ROOT: {key!r}")
        return path

    def put(self, key: str, data: bytes, mime: str) -> StoredFile:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        stored = StoredFile(
            key=key,
            mime_type=mime,
            size_bytes=len(data),
            checksum_sha256=hashlib.sha256(data).hexdigest(),
        )
        log.info("storage.put", key=key, size=stored.size_bytes)
        return stored

    def append(self, key: str, offset: int, data: bytes) -> int:
        """Write `data` at `offset` and return the new size.

        `offset` must not exceed the current size (a missing file has size 0),
        otherwise `ValueError`. If the file is longer than `offset` (a previous
        write landed on disk but the caller never recorded it), it is truncated
        to `offset` first, so a retry at the recorded offset self-heals.
        """
        path = self._path(key)
        size = path.stat().st_size if path.is_file() else 0
        if offset > size:
            raise ValueError(f"offset {offset} is beyond current size {size} for {key!r}")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("r+b" if size else "wb") as fh:
            fh.truncate(offset)
            fh.seek(offset)
            fh.write(data)
        return offset + len(data)

    def move(self, src_key: str, dst_key: str) -> None:
        src, dst = self._path(src_key), self._path(dst_key)
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.replace(dst)

    def sha256(self, key: str) -> str:
        digest = hashlib.sha256()
        with self._path(key).open("rb") as fh:
            while block := fh.read(1024 * 1024):
                digest.update(block)
        return digest.hexdigest()

    def path_for(self, key: str) -> Path:
        """Absolute filesystem path for `key` (validated). For FileResponse etc."""
        return self._path(key)

    def open(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def delete(self, key: str) -> bool:
        path = self._path(key)
        if not path.is_file():
            return False
        path.unlink()
        log.info("storage.delete", key=key)
        return True

    def delete_tree(self, prefix: str) -> bool:
        """Remove the folder `prefix` (a validated key inside MEDIA_ROOT, never
        the root itself) with everything under it."""
        path = self._path(prefix)
        if path == self._root:
            raise ValueError("refusing to delete MEDIA_ROOT")
        if not path.is_dir():
            return False
        shutil.rmtree(path)
        log.info("storage.delete_tree", prefix=prefix)
        return True

    def url_for(self, key: str) -> str:
        validate_key(key)
        return f"{self._public_base_url}/api/media/{key}"

    def build_media_file(
        self,
        stored: StoredFile,
        *,
        artifact_version_id: str,
        kind: MediaFileKind,
        page_index: int | None = None,
    ) -> MediaFile:
        """Construct (but do not persist) a `MediaFile` row from a `StoredFile`."""
        return MediaFile(
            artifact_version_id=artifact_version_id,
            kind=kind,
            storage_key=stored.key,
            mime_type=stored.mime_type,
            size_bytes=stored.size_bytes,
            checksum_sha256=stored.checksum_sha256,
            page_index=page_index,
        )

    # -- garbage collection ------------------------------------------------

    def gc_superseded_media(self, session: Session, *, keep_last_n: int) -> int:
        """Delete media for artifact versions that are neither the current nor
        the published version, keeping only the newest `keep_last_n` such
        versions per artifact. Returns the number of `media_file` rows removed.
        Never touches the current or published version.
        """
        removed = 0
        for artifact in session.scalars(select(Artifact)):
            protected = {artifact.current_version_id, artifact.published_version_id}
            versions = list(
                session.scalars(
                    select(ArtifactVersion)
                    .where(ArtifactVersion.artifact_id == artifact.id)
                    .order_by(ArtifactVersion.revision.desc())
                )
            )
            superseded = [v for v in versions if v.id not in protected]
            for version in superseded[keep_last_n:]:
                for media in list(version.media_files):
                    self.delete(media.storage_key)
                    session.delete(media)
                    removed += 1
        if removed:
            session.flush()
            log.info("storage.gc", removed=removed, keep_last_n=keep_last_n)
        return removed


@lru_cache
def get_storage() -> Storage:
    settings = get_settings()
    return Storage(settings.media_root, settings.public_base_url)


def clear_storage_cache() -> None:  # pragma: no cover - test helper
    get_storage.cache_clear()
