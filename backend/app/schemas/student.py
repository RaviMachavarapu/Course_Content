from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, StrictInt, StringConstraints

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


class QuizCheckRequest(BaseModel):
    index: int = Field(ge=0)
    # MCQ: the chosen option's position as shown in this attempt (0-3); fill-blank: the text
    response: StrictInt | Annotated[str, StringConstraints(strict=True, max_length=500)]


class QuizCheckOut(BaseModel):
    """Revealed only after the student locks an answer for this question."""

    index: int
    response: int | str
    correct: bool
    correct_answer: str
    correct_index: int | None = None  # MCQ only: position as shown in this attempt
    explanation: str = ""


class QuizQuestionOut(BaseModel):
    """A question as served before it is checked: never the answer or explanation.
    `result` is present only once this question has been checked in this attempt."""

    index: int
    type: Literal["mcq", "fill_blank"]
    question: str
    options: list[str] | None = None  # MCQ only
    result: QuizCheckOut | None = None


class QuizStartOut(BaseModel):
    status: Literal["started", "resumed"]
    attempt_id: uuid.UUID
    attempt_number: int
    source: Literal["studio", "chat"]
    total_count: int
    checked_count: int
    correct_count: int
    started_at: dt.datetime
    questions: list[QuizQuestionOut]


class QuizReviewRow(BaseModel):
    index: int
    type: Literal["mcq", "fill_blank"]
    question: str
    options: list[str] | None = None
    response: int | str
    correct: bool
    correct_answer: str
    correct_index: int | None = None
    explanation: str = ""


class QuizCompleteOut(BaseModel):
    attempt_id: uuid.UUID
    score_percent: float
    correct_count: int
    total_count: int
    completed_at: dt.datetime
    review: list[QuizReviewRow]
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
    #: the deck version the student is looking at (`StudentArtifactOut.version_id`)
    version_id: uuid.UUID | None = None


class FlashcardRatingsResponse(BaseModel):
    ratings: dict[int, str]


PG_INT_MAX = 2_147_483_647


class ArtifactProgressRequest(BaseModel):
    #: the version the student is looking at (`StudentArtifactOut.version_id`)
    version_id: uuid.UUID | None = None
    completed: bool | None = None
    complete_module: bool = False
    # the columns are INTEGER: a bigger value is a 422, not a DB overflow (500)
    slide_last_index: int | None = Field(default=None, ge=0, le=PG_INT_MAX)
    audio_position_seconds: int | None = Field(default=None, ge=0, le=PG_INT_MAX)


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
    #: the published version shown; writes echo it back (409 stale_version
    #: once another version has been published)
    version_id: uuid.UUID
    content_json: dict[str, Any] | None = None
    content_html: str | None = None
    media: list[ArtifactMediaOut]
    completed: bool
    slide_last_index: int | None = None
    audio_position_seconds: int | None = None
    flashcard_ratings: dict[int, str] = {}
