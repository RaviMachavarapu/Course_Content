from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.models.enums import ArtifactStatus, ArtifactType, CourseStatus, ModuleStatus
from app.storage.keys import InvalidKeyError, validate_key


def _valid_cover_key(key: str | None) -> str | None:
    """A malformed key would 500 the student catalog (`url_for` validates)."""
    if key is None:
        return None
    try:
        return validate_key(key)
    except InvalidKeyError as exc:
        raise ValueError("cover_image_key is not a valid storage key") from exc


#: a storage key (course.cover_image_key is VARCHAR(512))
CoverImageKey = Annotated[str | None, Field(max_length=512), AfterValidator(_valid_cover_key)]


class CourseCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    description: str = Field(default="", max_length=10_000)
    category: str = Field(default="", max_length=120)
    cover_image_key: CoverImageKey = None


class CoursePatchRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=10_000)
    category: str | None = Field(default=None, max_length=120)
    #: an explicit null clears the cover; leaving the field out keeps it
    cover_image_key: CoverImageKey = None


class ModuleCreateRequest(BaseModel):
    #: A link, PDFs (`upload_ids`), or both. "At least one" is enforced in the
    #: endpoint so the error carries the `no_source` code, not `validation_error`.
    source_url: str | None = Field(default=None, max_length=2048)
    upload_ids: list[uuid.UUID] = Field(default_factory=list)
    title: str = Field(min_length=1, max_length=300)
    types: list[ArtifactType] = Field(min_length=1)
    #: Per-type generation options (language, quantity/difficulty, audio
    #: format/length, infographic orientation), keyed by the type's string
    #: value. Validated against app.schemas.content_options's per-type
    #: models; any type omitted here gets that type's defaults.
    options: dict[ArtifactType, dict[str, Any]] = Field(default_factory=dict)
    #: Per-type focus text. A non-empty entry replaces that type's Settings
    #: prompt template; omitted or blank means "use the template".
    prompts: dict[ArtifactType, Annotated[str, Field(max_length=4000)]] = Field(
        default_factory=dict
    )


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


class SourceFileOut(BaseModel):
    file_name: str
    size_bytes: int
    part_count: int


class ModuleSummary(BaseModel):
    id: uuid.UUID
    order_index: int
    title: str
    source_url: str | None
    source_files: list[SourceFileOut]
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
