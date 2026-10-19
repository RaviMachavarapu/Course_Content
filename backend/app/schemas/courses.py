from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ArtifactStatus, ArtifactType, CourseStatus, ModuleStatus


class CourseCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    description: str = Field(default="", max_length=10_000)
    category: str = Field(default="", max_length=120)
    cover_image_key: str | None = None


class CoursePatchRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=10_000)
    category: str | None = Field(default=None, max_length=120)
    cover_image_key: str | None = None


class ModuleCreateRequest(BaseModel):
    source_url: str = Field(min_length=1, max_length=2048)
    title: str = Field(min_length=1, max_length=300)
    types: list[ArtifactType] = Field(min_length=1)
    #: Per-type generation options (language, quantity/difficulty, audio
    #: format/length, infographic orientation), keyed by the type's string
    #: value. Validated against app.schemas.content_options's per-type
    #: models; any type omitted here gets that type's defaults.
    options: dict[ArtifactType, dict[str, Any]] = Field(default_factory=dict)


class ModulePatchRequest(BaseModel):
    title: str = Field(min_length=1, max_length=300)


class ModuleMoveRequest(BaseModel):
    direction: Literal["up", "down"]


class CourseSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    slug: str
    category: str
    status: CourseStatus
    module_count: int
    updated_at: dt.datetime
    published_at: dt.datetime | None = None


class ArtifactSummary(BaseModel):
    id: uuid.UUID
    type: ArtifactType
    status: ArtifactStatus


class ModuleSummary(BaseModel):
    id: uuid.UUID
    order_index: int
    title: str
    source_url: str
    source_type: str
    status: ModuleStatus
    artifacts: list[ArtifactSummary]


class CourseDetail(BaseModel):
    id: uuid.UUID
    title: str
    slug: str
    description: str
    category: str
    status: CourseStatus
    cover_image_key: str | None
    created_at: dt.datetime
    updated_at: dt.datetime
    published_at: dt.datetime | None
    modules: list[ModuleSummary]


class CourseListResponse(BaseModel):
    courses: list[CourseSummary]


class CourseEnvelope(BaseModel):
    course: CourseDetail


class ModuleEnvelope(BaseModel):
    module: ModuleSummary
    job_ids: list[uuid.UUID]
