from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from pydantic import BaseModel

from app.models.enums import ArtifactStatus, ArtifactType
from app.schemas.staging import MediaOut


class ArtifactVersionDetail(BaseModel):
    id: uuid.UUID
    revision: int
    redo_note: str | None
    focus_prompt_used: str
    prompt_template_version: int | None
    generation_job_id: uuid.UUID | None
    notebooklm_artifact_id: str | None
    created_at: dt.datetime
    content_json: dict[str, Any] | None
    content_html: str | None
    media: list[MediaOut]


class VersionHistoryItem(BaseModel):
    id: uuid.UUID
    revision: int
    created_at: dt.datetime
    redo_note: str | None
    is_current: bool
    is_published: bool


class InspectArtifact(BaseModel):
    id: uuid.UUID
    type: ArtifactType
    status: ArtifactStatus
    module_id: uuid.UUID
    last_error: str | None


class ArtifactInspectResponse(BaseModel):
    artifact: InspectArtifact
    notebooklm_notebook_id: str | None
    viewing: ArtifactVersionDetail | None
    history: list[VersionHistoryItem]
