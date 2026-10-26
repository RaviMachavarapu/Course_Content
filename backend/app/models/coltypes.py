"""Shared native-enum column types.

Reusing one `Enum` instance per Postgres type means SQLAlchemy emits a single
``CREATE TYPE`` even when several tables reference it.
"""

from __future__ import annotations

from sqlalchemy import Enum

from app.models.enums import (
    ArtifactStatus,
    ArtifactType,
    CourseStatus,
    FlashcardRatingValue,
    GenerationJobKind,
    GenerationJobState,
    MediaFileKind,
    ModuleSourceType,
    ModuleStatus,
    SourceUploadStatus,
)

artifact_type_enum = Enum(ArtifactType, name="artifact_type")
artifact_status_enum = Enum(ArtifactStatus, name="artifact_status")
module_status_enum = Enum(ModuleStatus, name="module_status")
module_source_type_enum = Enum(ModuleSourceType, name="module_source_type")
course_status_enum = Enum(CourseStatus, name="course_status")
generation_job_kind_enum = Enum(GenerationJobKind, name="generation_job_kind")
generation_job_state_enum = Enum(GenerationJobState, name="generation_job_state")
media_file_kind_enum = Enum(MediaFileKind, name="media_file_kind")
# NB: not "flashcard_rating" — that name collides with the table's implicit row type.
flashcard_rating_enum = Enum(FlashcardRatingValue, name="flashcard_rating_value")
source_upload_status_enum = Enum(SourceUploadStatus, name="source_upload_status")
