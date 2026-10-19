"""Admin — Artifact Inspect (spec.md §3.4, §5.3): read-only current/historic
version content + media + generation metadata."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status
from sqlalchemy import desc, select

from app.api.admin import ADMIN_DEPENDENCIES
from app.api.deps import DbDep
from app.errors import APIError
from app.models.artifact import Artifact
from app.models.artifact_version import ArtifactVersion
from app.schemas.artifacts import (
    ArtifactInspectResponse,
    ArtifactVersionDetail,
    InspectArtifact,
    VersionHistoryItem,
)
from app.schemas.staging import MediaOut
from app.storage.service import get_storage

router = APIRouter(
    prefix="/api/admin/artifacts", tags=["admin-artifacts"], dependencies=ADMIN_DEPENDENCIES
)


def _version_detail(version: ArtifactVersion) -> ArtifactVersionDetail:
    storage = get_storage()
    return ArtifactVersionDetail(
        id=version.id,
        revision=version.revision,
        redo_note=version.redo_note,
        focus_prompt_used=version.focus_prompt_used,
        prompt_template_version=version.prompt_template_version,
        generation_job_id=version.generation_job_id,
        notebooklm_artifact_id=version.notebooklm_artifact_id,
        created_at=version.created_at,
        content_json=version.content_json,
        content_html=version.content_html,
        media=[
            MediaOut(
                kind=m.kind.value,
                url=storage.url_for(m.storage_key),
                size_bytes=m.size_bytes,
                page_index=m.page_index,
            )
            for m in version.media_files
        ],
    )


@router.get("/{artifact_id}", response_model=ArtifactInspectResponse)
def inspect(
    artifact_id: uuid.UUID, db: DbDep, version: uuid.UUID | None = None
) -> ArtifactInspectResponse:
    artifact = db.get(Artifact, artifact_id)
    if artifact is None:
        raise APIError(status.HTTP_404_NOT_FOUND, "not_found", "Artifact not found")

    versions = list(
        db.scalars(
            select(ArtifactVersion)
            .where(ArtifactVersion.artifact_id == artifact.id)
            .order_by(desc(ArtifactVersion.revision))
        )
    )

    target_id = version or artifact.current_version_id
    viewing = next((v for v in versions if v.id == target_id), None)

    return ArtifactInspectResponse(
        artifact=InspectArtifact(
            id=artifact.id,
            type=artifact.type,
            status=artifact.status,
            module_id=artifact.module_id,
            last_error=artifact.last_error,
        ),
        notebooklm_notebook_id=artifact.module.notebooklm_notebook_id,
        viewing=_version_detail(viewing) if viewing is not None else None,
        history=[
            VersionHistoryItem(
                id=v.id,
                revision=v.revision,
                created_at=v.created_at,
                redo_note=v.redo_note,
                is_current=v.id == artifact.current_version_id,
                is_published=v.id == artifact.published_version_id,
            )
            for v in versions
        ],
    )
