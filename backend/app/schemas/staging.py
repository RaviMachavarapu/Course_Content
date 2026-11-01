from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import (
    ArtifactStatus,
    ArtifactType,
    CourseStatus,
    GenerationJobState,
    ModuleStatus,
)


class RedoRequest(BaseModel):
    note: str | None = Field(default=None, max_length=4000)
    #: Overrides this artifact's stored generation options for this redo (and
    #: going forward). Omit to keep whatever's already stored.
    options: dict[str, Any] | None = None
    #: Focus text that replaces the Settings template for this and future
    #: generations of this artifact. Omit to keep the stored text; send ""
    #: or null to go back to the template.
    custom_prompt: str | None = Field(default=None, max_length=4000)


class OutlineFeedbackRequest(BaseModel):
    feedback: str = Field(min_length=1, max_length=4000)


class OutlineOut(BaseModel):
    """NotebookLM's draft slide outline, while the deck waits for review."""

    style: str
    slides: list[str]


class MediaOut(BaseModel):
    kind: str
    url: str
    size_bytes: int
    page_index: int | None = None


class CurrentVersionOut(BaseModel):
    id: uuid.UUID
    revision: int
    redo_note: str | None
    created_at: dt.datetime
    media: list[MediaOut]
    preview: dict[str, Any] = {}


class StagingArtifactOut(BaseModel):
    id: uuid.UUID
    type: ArtifactType
    status: ArtifactStatus
    last_error: str | None
    current_version: CurrentVersionOut | None
    job: dict[str, GenerationJobState | None]  # {"state": ...}
    generation_options: dict[str, Any]
    custom_prompt: str | None = None
    outline: OutlineOut | None = None


class StagingModuleOut(BaseModel):
    id: uuid.UUID
    title: str
    status: ModuleStatus
    course_id: uuid.UUID
    course_status: CourseStatus


class StagingResponse(BaseModel):
    module: StagingModuleOut
    artifacts: list[StagingArtifactOut]
