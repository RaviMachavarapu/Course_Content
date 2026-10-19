from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel

from app.models.enums import ArtifactStatus, ArtifactType, ModuleStatus


class PipelineDot(BaseModel):
    type: ArtifactType
    status: ArtifactStatus


class PipelineRow(BaseModel):
    module_id: uuid.UUID
    course_id: uuid.UUID
    course_title: str
    module_title: str
    source_url: str
    created_at: dt.datetime
    global_status: ModuleStatus
    dots: list[PipelineDot]


class PipelineResponse(BaseModel):
    rows: list[PipelineRow]
    page: int
    page_size: int
    total: int
