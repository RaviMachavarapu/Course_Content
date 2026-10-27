"""Typeset (Quarto) PDF of one artifact version, stored as a MediaFile of it.

Pure, synchronous steps (no Celery) shared by the `build_artifact_pdf` task
(app/tasks/pdf.py) and `python -m app.cli rebuild-pdfs`:

1. `prepare_pdfs` reads the version's content and images and builds its
   documents: one per PDF kind (a quiz has two: `quiz_pdf` with the answer key
   for admins, `quiz_questions_pdf` without it for students);
2. the caller renders each with the typeset service (`render_pdf`), outside any
   lock or long-held session;
3. `store_pdf` stores each under its PDF kind, replacing a previous PDF of
   that kind for the version; the caller deletes `stale_keys` after committing,
   or calls `discard_new_file` if the commit fails.

A version that is neither its artifact's current nor published one is skipped.

None of this touches the artifact's status or last_error: a missing PDF never
makes an artifact fail.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.logging import get_logger
from app.models.artifact_version import ArtifactVersion
from app.models.enums import ArtifactType, MediaFileKind
from app.models.media_file import MediaFile
from app.render.typeset_client import TypesetResult, render_pdf
from app.render.typeset_docs import (
    PDF_KINDS,
    StoredImage,
    TypesetDoc,
    build_documents,
    course_media_loader,
)
from app.storage.keys import media_key
from app.storage.service import STORAGE_EXTS, get_storage

__all__ = [
    "PDF_KINDS",
    "BuiltPdf",
    "PdfSkipped",
    "PdfSource",
    "Render",
    "StoredPdf",
    "build_version_pdfs",
    "delete_files",
    "discard_new_file",
    "prepare_pdfs",
    "store_pdf",
]

log = get_logger("artifact_pdf")

Render = Callable[[str, str, dict[str, bytes]], TypesetResult]

#: the stored images each type's document uses (others are never read)
_IMAGE_KINDS = (MediaFileKind.slide_png, MediaFileKind.infographic_png)

#: visible title for types without their own: "<module title>: <label>"
_LABELS: dict[ArtifactType, str] = {
    ArtifactType.flashcards: "Flashcards",
    ArtifactType.quiz: "Quiz",
    ArtifactType.infographic: "Infographic",
    ArtifactType.slide_deck: "Slides",
}


class PdfSkipped(Exception):
    """This version has no PDF to build (audio, no content, or it is gone)."""


@dataclass(frozen=True)
class PdfSource:
    version_id: uuid.UUID
    kind: MediaFileKind
    doc: TypesetDoc


@dataclass(frozen=True)
class StoredPdf:
    media: MediaFile
    #: the new file's storage key
    new_key: str
    #: True when no previous row used `new_key`: if the commit fails, delete it
    fresh: bool
    #: files of the replaced PDF; delete them once the new row is committed
    stale_keys: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class BuiltPdf:
    stored: StoredPdf
    fallback: str

    @property
    def media(self) -> MediaFile:
        return self.stored.media


def prepare_pdfs(session: Session, version_id: uuid.UUID) -> list[PdfSource]:
    """The typeset documents for `version_id`, the type's `PDF_KINDS` one first.
    Raises `PdfSkipped`, or the content's validation error if its
    `content_json` doesn't fit its type."""
    version = session.get(ArtifactVersion, version_id)
    if version is None:
        raise PdfSkipped("version not found")
    artifact = version.artifact
    if artifact.type not in PDF_KINDS:
        raise PdfSkipped(f"{artifact.type.value} has no PDF")
    if version_id not in (artifact.current_version_id, artifact.published_version_id):
        raise PdfSkipped("superseded")
    if not version.content_json:
        raise PdfSkipped("version has no content")
    module = artifact.module

    storage = get_storage()
    media: list[StoredImage] = []
    for m in version.media_files:
        if m.kind not in _IMAGE_KINDS:
            continue
        try:
            media.append(StoredImage(m.kind, m.page_index, storage.open(m.storage_key)))
        except OSError as exc:
            log.warning(
                "pdf.image_unreadable",
                version_id=str(version_id),
                key=m.storage_key,
                error=str(exc),
            )

    label = _LABELS.get(artifact.type)
    docs = build_documents(
        artifact.type,
        version.content_json,
        media,
        title=f"{module.title}: {label}" if label else None,
        load_media=course_media_loader(session, module.course_id),
    )
    return [PdfSource(version_id=version_id, kind=k, doc=d) for k, d in docs.items()]


def store_pdf(
    session: Session, version_id: uuid.UUID, kind: MediaFileKind, pdf: bytes
) -> StoredPdf:
    """Store `pdf` as the version's `kind` MediaFile (flushed, not committed),
    replacing any previous one. The key carries a checksum prefix, so a changed
    PDF gets a new URL (media is served with an immutable cache header)."""
    version = session.scalars(
        select(ArtifactVersion).where(ArtifactVersion.id == version_id).with_for_update()
    ).one_or_none()
    if version is None:
        raise PdfSkipped("version not found")
    artifact = version.artifact
    module = artifact.module
    key = media_key(
        course_id=module.course_id,
        module_id=module.id,
        artifact_id=artifact.id,
        revision=version.revision,
        kind=kind,
        ext=STORAGE_EXTS[kind],
        variant=hashlib.sha256(pdf).hexdigest()[:12],
    )
    previous = list(
        session.scalars(
            select(MediaFile).where(
                MediaFile.artifact_version_id == version_id, MediaFile.kind == kind
            )
        )
    )
    fresh = all(old.storage_key != key for old in previous)
    storage = get_storage()
    stored = storage.put(key, pdf, "application/pdf")
    try:
        for old in previous:
            session.delete(old)
        session.flush()
        media = storage.build_media_file(stored, artifact_version_id=str(version_id), kind=kind)
        session.add(media)
        session.flush()
    except Exception:
        if fresh:
            delete_files([key])
        raise
    stale = [old.storage_key for old in previous if old.storage_key != key]
    return StoredPdf(media=media, new_key=key, fresh=fresh, stale_keys=stale)


def discard_new_file(stored: StoredPdf) -> None:
    """The commit of `stored` failed: remove its file unless an older row uses it."""
    if stored.fresh:
        delete_files([stored.new_key])


def delete_files(keys: Iterable[str]) -> None:
    """Remove replaced PDFs' files (after the new rows are committed)."""
    storage = get_storage()
    for key in keys:
        try:
            storage.delete(key)
        except (OSError, ValueError) as exc:
            log.warning("pdf.stale_file_not_deleted", key=key, error=str(exc))


def build_version_pdfs(
    session: Session, version_id: uuid.UUID, *, render: Render | None = None
) -> list[BuiltPdf]:
    """Prepare, render and store every PDF of the version in one session (the
    rebuild command). Raises `PdfSkipped`, `TypesetUnavailable`, `TypesetError`
    or a content error; if a later PDF fails, the files of those already
    stored are removed again (the caller rolls the rows back)."""
    built: list[BuiltPdf] = []
    try:
        for source in prepare_pdfs(session, version_id):
            result = (render or render_pdf)(*source.doc)
            stored = store_pdf(session, version_id, source.kind, result.pdf)
            built.append(BuiltPdf(stored=stored, fallback=result.fallback))
    except Exception:
        for b in built:
            discard_new_file(b.stored)
        raise
    return built
