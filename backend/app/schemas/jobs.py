from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict

from app.models.enums import GenerationJobKind, GenerationJobState


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: GenerationJobKind
    state: GenerationJobState
    attempts: int
    error_detail: str | None = None
    module_id: uuid.UUID | None = None
    artifact_id: uuid.UUID | None = None
    created_at: dt.datetime
    started_at: dt.datetime | None = None
    finished_at: dt.datetime | None = None


class JobListResponse(BaseModel):
    jobs: list[JobOut]


class RecentJobOut(BaseModel):
    """One row in the admin notifications feed (T030)."""

    id: uuid.UUID
    kind: GenerationJobKind
    state: GenerationJobState
    artifact_type: str | None = None
    module_id: uuid.UUID | None = None
    module_title: str | None = None
    course_id: uuid.UUID | None = None
    error_detail: str | None = None
    at: dt.datetime


class RecentJobsResponse(BaseModel):
    jobs: list[RecentJobOut]


class JobEnvelope(BaseModel):
    job: JobOut
