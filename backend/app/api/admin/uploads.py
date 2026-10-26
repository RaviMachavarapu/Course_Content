"""Resumable chunked PDF uploads (admin). A module claims finished uploads later."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.api.admin import ADMIN_DEPENDENCIES
from app.api.deps import CurrentAdmin, DbDep
from app.errors import APIError
from app.models.enums import SourceUploadStatus
from app.models.source_upload import SourceUpload
from app.schemas.uploads import (
    CHUNK_SIZE,
    MAX_CHUNK_BYTES,
    UploadCreate,
    UploadCreated,
    UploadProgress,
    UploadStatusOut,
)
from app.storage.keys import upload_key
from app.storage.service import get_storage

router = APIRouter(prefix="/api/admin", tags=["admin-uploads"], dependencies=ADMIN_DEPENDENCIES)


def _own_upload(
    db: DbDep, admin: CurrentAdmin, upload_id: uuid.UUID, lock: bool = False
) -> SourceUpload:
    stmt = select(SourceUpload).where(
        SourceUpload.id == upload_id, SourceUpload.admin_id == admin.id
    )
    if lock:
        stmt = stmt.with_for_update()
    upload = db.scalar(stmt)
    if upload is None:
        raise APIError(status.HTTP_404_NOT_FOUND, "not_found", "Upload not found")
    return upload


@router.post("/uploads", status_code=status.HTTP_201_CREATED, response_model=UploadCreated)
def create_upload(body: UploadCreate, db: DbDep, admin: CurrentAdmin) -> UploadCreated:
    upload_id = uuid.uuid4()
    db.add(
        SourceUpload(
            id=upload_id,
            admin_id=admin.id,
            file_name=body.file_name,
            size_bytes=body.size_bytes,
            received_bytes=0,
            storage_key=upload_key(upload_id),
            status=SourceUploadStatus.receiving,
        )
    )
    db.flush()
    return UploadCreated(upload_id=upload_id, chunk_size=CHUNK_SIZE)


@router.put("/uploads/{upload_id}", response_model=UploadProgress)
async def put_chunk(
    upload_id: uuid.UUID,
    request: Request,
    db: DbDep,
    admin: CurrentAdmin,
    offset: int = Query(ge=0),
) -> UploadProgress | JSONResponse:
    upload = _own_upload(db, admin, upload_id, lock=True)
    if upload.status != SourceUploadStatus.receiving:
        raise APIError(status.HTTP_409_CONFLICT, "not_receiving", "Upload is already finished")
    if offset != upload.received_bytes:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "code": "offset_mismatch",
                "received_bytes": upload.received_bytes,
                "error": {
                    "code": "offset_mismatch",
                    "message": "Offset does not match bytes received",
                    "received_bytes": upload.received_bytes,
                },
            },
        )
    data = await request.body()
    if len(data) > MAX_CHUNK_BYTES:
        raise APIError(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "chunk_too_large", "Chunk too big")
    if upload.received_bytes + len(data) > upload.size_bytes:
        raise APIError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "too_many_bytes",
            f"{upload.file_name} is larger than declared",
        )

    storage = get_storage()
    upload.received_bytes = storage.append(upload.storage_key, offset, data)
    if upload.received_bytes == upload.size_bytes:
        with storage.path_for(upload.storage_key).open("rb") as fh:
            head = fh.read(5)
        if head != b"%PDF-":
            storage.delete(upload.storage_key)
            message = f"{upload.file_name} is not a PDF"
            db.delete(upload)
            db.commit()  # the error response must not roll the cleanup back
            raise APIError(status.HTTP_422_UNPROCESSABLE_ENTITY, "not_pdf", message)
        upload.status = SourceUploadStatus.complete
    db.flush()
    return UploadProgress(received_bytes=upload.received_bytes)


@router.get("/uploads/{upload_id}", response_model=UploadStatusOut)
def get_upload(upload_id: uuid.UUID, db: DbDep, admin: CurrentAdmin) -> UploadStatusOut:
    upload = _own_upload(db, admin, upload_id)
    return UploadStatusOut(received_bytes=upload.received_bytes, status=upload.status)
