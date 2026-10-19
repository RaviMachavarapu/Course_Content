from __future__ import annotations

from pydantic import BaseModel

from app.models.enums import ArtifactStatus, ArtifactType, CourseStatus, ModuleStatus


class SkippedArtifact(BaseModel):
    type: ArtifactType
    status: ArtifactStatus
    reason: str


class PublishResult(BaseModel):
    published: list[ArtifactType]
    skipped: list[SkippedArtifact]
    module_status: ModuleStatus | None = None
    course_status: CourseStatus
