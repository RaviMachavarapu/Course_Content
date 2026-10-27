"""SQLAlchemy models.

Every model module must be imported here so Alembic autogenerate and
`Base.metadata` see the full schema.
"""

from app.models.app_meta import AppMeta
from app.models.artifact import Artifact
from app.models.artifact_version import ArtifactVersion
from app.models.audit_log import AuditLog
from app.models.course import Course
from app.models.enums import (
    ARTIFACT_TYPES,
    ArtifactStatus,
    ArtifactType,
    CourseStatus,
    FlashcardRatingValue,
    GenerationJobKind,
    GenerationJobState,
    MediaFileKind,
    ModuleSourceType,
    ModuleStatus,
    QuizSetSource,
    QuizSetStatus,
    SourceUploadStatus,
)
from app.models.flashcard_rating import FlashcardRating
from app.models.generation_job import GenerationJob
from app.models.media_file import MediaFile
from app.models.module import Module
from app.models.module_source_file import ModuleSourceFile
from app.models.progress import ArtifactProgress, CourseProgress
from app.models.prompt_template import PromptTemplate
from app.models.quiz_attempt import QuizAttempt
from app.models.quiz_question_set import QuizQuestionSet
from app.models.source_upload import SourceUpload
from app.models.status import derive_course_status, derive_module_status
from app.models.user import User, UserRole, normalize_email

__all__ = [
    "ARTIFACT_TYPES",
    "AppMeta",
    "Artifact",
    "ArtifactProgress",
    "ArtifactStatus",
    "ArtifactType",
    "ArtifactVersion",
    "AuditLog",
    "Course",
    "CourseProgress",
    "CourseStatus",
    "FlashcardRating",
    "FlashcardRatingValue",
    "GenerationJob",
    "GenerationJobKind",
    "GenerationJobState",
    "MediaFile",
    "MediaFileKind",
    "Module",
    "ModuleSourceFile",
    "ModuleSourceType",
    "ModuleStatus",
    "PromptTemplate",
    "QuizAttempt",
    "QuizQuestionSet",
    "QuizSetSource",
    "QuizSetStatus",
    "SourceUpload",
    "SourceUploadStatus",
    "User",
    "UserRole",
    "derive_course_status",
    "derive_module_status",
    "normalize_email",
]
