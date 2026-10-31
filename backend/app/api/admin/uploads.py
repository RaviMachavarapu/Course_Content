"""Resumable chunked PDF uploads (admin). A module claims finished uploads later."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.admin import ADMIN_DEPENDENCIES
from app.api.deps import CurrentAdmin, DbDep
from app.errors import APIError
from app.models.enums import SourceUploadStatus
from app.models.source_upload import SourceUpload
from app.models.user import User
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


def _apply_chunk(
    db: Session, admin: User, upload_id: uuid.UUID, offset: int, data: bytes
) -> int | JSONResponse:
    """Sync (runs in a worker thread): lock the row, append, commit. The row
    lock is taken and released inside this one call, never across an await."""
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
    if upload.received_bytes + len(data) > upload.size_bytes:
        raise APIError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "too_many_bytes",
            f"{upload.file_name} is larger than declared",
        )

    storage = get_storage()
    try:
        upload.received_bytes = storage.append(upload.storage_key, offset, data)
    except ValueError:
        # the stored file is shorter than the bytes recorded (lost from disk): this
        # upload can never resume, so drop it; the client starts a new one
        storage.delete(upload.storage_key)
        message = f"{upload.file_name} was lost on the server; upload it again"
        db.delete(upload)
        db.commit()  # the error response must not roll the cleanup back
        raise APIError(status.HTTP_409_CONFLICT, "upload_lost", message) from None
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
    received = upload.received_bytes
    db.commit()
    return received


def _too_large() -> APIError:
    return APIError(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "chunk_too_large", "Chunk too big")


async def _read_capped(request: Request, cap: int) -> bytes:
    """The request body, read as it streams in; 413 as soon as it exceeds `cap` bytes (or
    when the declared Content-Length does), so an oversized chunk is never buffered whole.
    Nothing is written for a refused chunk: the client resumes at the recorded offset."""
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > cap:
        raise _too_large()
    body = bytearray()
    async for piece in request.stream():
        body += piece
        if len(body) > cap:
            raise _too_large()
    return bytes(body)


@router.put("/uploads/{upload_id}", response_model=UploadProgress)
async def put_chunk(
    upload_id: uuid.UUID,
    request: Request,
    db: DbDep,
    admin: CurrentAdmin,
    offset: int = Query(ge=0),
) -> UploadProgress | JSONResponse:
    data = await _read_capped(request, MAX_CHUNK_BYTES)  # first: no lock held while awaiting
    result = await run_in_threadpool(_apply_chunk, db, admin, upload_id, offset, data)
    if isinstance(result, JSONResponse):
        return result
    return UploadProgress(received_bytes=result)


@router.get("/uploads/{upload_id}", response_model=UploadStatusOut)
def get_upload(upload_id: uuid.UUID, db: DbDep, admin: CurrentAdmin) -> UploadStatusOut:
    upload = _own_upload(db, admin, upload_id)
    return UploadStatusOut(received_bytes=upload.received_bytes, status=upload.status)
