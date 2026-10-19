from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models.enums import ArtifactType


class CatalogCourseOut(BaseModel):
    id: uuid.UUID
    slug: str
    title: str
    description: str
    category: str
    cover_image_url: str | None = None
    module_count: int
    artifact_counts: dict[ArtifactType, int]
    total_audio_seconds: int | None = None
    percent_complete: int
    next_module_index: int


class CatalogResponse(BaseModel):
    courses: list[CatalogCourseOut]
    categories: list[str]


class WorkspaceArtifactOut(BaseModel):
    id: uuid.UUID
    type: ArtifactType
    completed: bool


class WorkspaceModuleOut(BaseModel):
    index: int
    id: uuid.UUID
    title: str
    percent_complete: int
    artifacts: list[WorkspaceArtifactOut]


class WorkspaceCourseOut(BaseModel):
    id: uuid.UUID
    slug: str
    title: str
    description: str
    percent_complete: int
    current_module_index: int
    modules: list[WorkspaceModuleOut]


class ArtifactMediaOut(BaseModel):
    kind: str
    url: str
    page_index: int | None = None


class QuizSubmitRequest(BaseModel):
    answers: dict[int, int]


class QuizResultRow(BaseModel):
    question_index: int
    selected_index: int
    correct_index: int
    is_correct: bool
    explanation: str = ""


class QuizResultOut(BaseModel):
    attempt_id: uuid.UUID
    score_percent: float
    correct_count: int
    total_count: int
    results: list[QuizResultRow]
    best_score_percent: float
    latest_score_percent: float


class QuizAttemptOut(BaseModel):
    id: uuid.UUID
    score_percent: float
    correct_count: int
    total_count: int
    submitted_at: dt.datetime | None = None


class QuizAttemptsResponse(BaseModel):
    attempts: list[QuizAttemptOut]
    best_score_percent: float | None = None
    latest_score_percent: float | None = None


class FlashcardRatingRequest(BaseModel):
    value: Literal["hard", "good", "easy"]


class FlashcardRatingsResponse(BaseModel):
    ratings: dict[int, str]


class ArtifactProgressRequest(BaseModel):
    completed: bool | None = None
    complete_module: bool = False
    slide_last_index: int | None = Field(default=None, ge=0)
    audio_position_seconds: int | None = Field(default=None, ge=0)


class ArtifactProgressResponse(BaseModel):
    completed: bool
    slide_last_index: int | None = None
    audio_position_seconds: int | None = None
    course_percent_complete: int


class StudentArtifactOut(BaseModel):
    id: uuid.UUID
    type: ArtifactType
    module_id: uuid.UUID
    module_index: int
    course_slug: str
    revision: int
    content_json: dict[str, Any] | None = None
    content_html: str | None = None
    media: list[ArtifactMediaOut]
    completed: bool
    slide_last_index: int | None = None
    audio_position_seconds: int | None = None
    flashcard_ratings: dict[int, str] = {}
