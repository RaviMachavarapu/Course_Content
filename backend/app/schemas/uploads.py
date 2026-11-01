from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

from app.models.enums import SourceUploadStatus

CHUNK_SIZE = 8 * 1024 * 1024
MAX_CHUNK_BYTES = 16 * 1024 * 1024


class UploadCreate(BaseModel):
    file_name: str = Field(min_length=1, max_length=512)
    size_bytes: int = Field(gt=0, le=2**63 - 1)  # BIGINT column


class UploadCreated(BaseModel):
    upload_id: uuid.UUID
    chunk_size: int = CHUNK_SIZE


class UploadProgress(BaseModel):
    received_bytes: int


class UploadStatusOut(BaseModel):
    received_bytes: int
    status: SourceUploadStatus
