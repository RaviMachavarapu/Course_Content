"""Access-checked media streaming (spec.md §9, §11).

Admins can fetch any media file. Students can fetch a file only when it belongs
to its artifact's **published version** and is not a kind students never get
(`STUDENT_HIDDEN_MEDIA_KINDS`: the quiz PDF with its answer key) — the shared
rule in app.services.visibility. The artifact's workflow status is ignored: a
redo in progress (or one that failed) keeps the published version's media
live (spec §3.3, BR5). Anything else → 404 (never 403 — don't reveal that the
key exists).

Responses are `private`: they need a session, so no shared cache (CDN, proxy)
may store them. Keys are versioned, so they are still `immutable`.
"""

from __future__ import annotations

from fastapi import APIRouter, status
from fastapi.responses import FileResponse
from sqlalchemy import select

from app.api.deps import CurrentAnyUser, DbDep
from app.errors import APIError
from app.models.artifact import Artifact
from app.models.artifact_version import ArtifactVersion
from app.models.media_file import MediaFile
from app.models.user import UserRole
from app.services.visibility import media_visible_to_student
from app.storage.keys import InvalidKeyError, validate_key
from app.storage.service import get_storage

router = APIRouter(prefix="/api/media", tags=["media"])

_IMMUTABLE = "private, max-age=31536000, immutable"


@router.get("/{storage_key:path}")
def get_media(storage_key: str, db: DbDep, user: CurrentAnyUser) -> FileResponse:
    not_found = APIError(status.HTTP_404_NOT_FOUND, "not_found", "Not found")
    try:
        validate_key(storage_key)
    except InvalidKeyError:
        raise not_found from None

    media = db.scalar(select(MediaFile).where(MediaFile.storage_key == storage_key))
    if media is None:
        raise not_found

    if user.role is not UserRole.admin:
        version = db.get(ArtifactVersion, media.artifact_version_id)
        artifact = db.get(Artifact, version.artifact_id) if version else None
        if not media_visible_to_student(media, artifact):
            raise not_found

    storage = get_storage()
    if not storage.exists(storage_key):
        raise not_found

    return FileResponse(
        storage.path_for(storage_key),
        media_type=media.mime_type,
        headers={"Cache-Control": _IMMUTABLE},
        filename=storage_key.rsplit("/", 1)[-1],
    )
