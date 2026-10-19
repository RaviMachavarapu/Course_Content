from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ArtifactType


class PromptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    artifact_type: ArtifactType
    version: int
    body: str
    is_active: bool
    updated_at: dt.datetime
    updated_by: uuid.UUID | None = None


class PromptListResponse(BaseModel):
    templates: list[PromptOut]


class PromptDetailResponse(BaseModel):
    active: PromptOut
    history: list[PromptOut]


class PromptUpdateRequest(BaseModel):
    body: str = Field(min_length=1, max_length=20_000)


class PromptResponse(BaseModel):
    template: PromptOut
