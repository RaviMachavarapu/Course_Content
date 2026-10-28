"""What a student may see (spec §3.3, BR5, BR8) — the one shared rule.

An artifact is live for students exactly when it has a published version
(`published_version_id IS NOT NULL`). Student-visible content is always that
published version, whatever the artifact's or its module's/course's *workflow*
status says: a redo, a re-run, a new module or a stuck job moves those to
processing / pending_review / error, but the published version stays live
until a new one is published (spec §3.3 "the student-visible content is still
the old version until re-published").

A media file is visible to a student exactly when it belongs to its artifact's
published version and is not a kind students never get (the quiz PDF with the
answer key). Draft-only content never matches either rule → 404.
"""

from __future__ import annotations

from sqlalchemy import ColumnElement

from app.models.artifact import Artifact
from app.models.enums import STUDENT_HIDDEN_MEDIA_KINDS
from app.models.media_file import MediaFile
from app.models.module import Module


def is_live(artifact: Artifact) -> bool:
    """The artifact has a published version students can open."""
    return artifact.published_version_id is not None


def live_clause() -> ColumnElement[bool]:
    """`is_live` as a SQL predicate on `Artifact`."""
    return Artifact.published_version_id.is_not(None)


def live_artifacts(module: Module) -> list[Artifact]:
    """The module's artifacts that are live for students."""
    return [a for a in module.artifacts if is_live(a)]


def media_visible_to_student(media: MediaFile, artifact: Artifact | None) -> bool:
    """`media` belongs to `artifact`'s published version and isn't admin-only."""
    return (
        artifact is not None
        and media.kind not in STUDENT_HIDDEN_MEDIA_KINDS
        and artifact.published_version_id is not None
        and artifact.published_version_id == media.artifact_version_id
    )
