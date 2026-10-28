"""Admin — courses & modules (spec.md §3.2, §3.5, §5.2)."""

from __future__ import annotations

import contextlib
import re
import unicodedata
import uuid

from fastapi import APIRouter, BackgroundTasks, Response, status
from pypdf import PdfReader
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api.admin import ADMIN_DEPENDENCIES
from app.api.deps import CurrentAdmin, DbDep
from app.errors import APIError
from app.logging import get_logger
from app.models.course import Course
from app.models.enums import ARTIFACT_TYPES, ModuleSourceType, SourceUploadStatus
from app.models.module import Module
from app.models.module_source_file import ModuleSourceFile
from app.models.source_upload import SourceUpload
from app.pipeline import orchestrator
from app.pipeline.factory import get_content_provider
from app.schemas.courses import (
    ArtifactSummary,
    CourseCreateRequest,
    CourseDetail,
    CourseEnvelope,
    CourseListResponse,
    CoursePatchRequest,
    CourseSummary,
    ModuleCreateRequest,
    ModuleEnvelope,
    ModuleMoveRequest,
    ModulePatchRequest,
    ModuleSummary,
    SourceFileOut,
)
from app.services.derived_status import recompute_course_status
from app.services.ingestion import SUPPORTED_HINT, detect_source_type
from app.services.slugs import unique_course_slug
from app.storage.keys import module_prefix, source_key
from app.storage.service import get_storage

router = APIRouter(
    prefix="/api/admin/courses", tags=["admin-courses"], dependencies=ADMIN_DEPENDENCIES
)

_ARTIFACT_ORDER = {t: i for i, t in enumerate(ARTIFACT_TYPES)}

log = get_logger("admin.courses")


def source_files_out(module: Module) -> list[SourceFileOut]:
    return [
        SourceFileOut(
            file_name=f.file_name,
            size_bytes=f.size_bytes,
            part_count=max(1, len(f.parts)),
        )
        for f in module.source_files
    ]


def _module_summary(module: Module) -> ModuleSummary:
    arts = sorted(module.artifacts, key=lambda a: _ARTIFACT_ORDER.get(a.type, 99))
    return ModuleSummary(
        id=module.id,
        order_index=module.order_index,
        title=module.title,
        source_url=module.source_url,
        source_files=source_files_out(module),
        source_type=module.source_type.value,
        status=module.status,
        artifacts=[ArtifactSummary(id=a.id, type=a.type, status=a.status) for a in arts],
    )


def _course_detail(course: Course) -> CourseDetail:
    mods = sorted(course.modules, key=lambda m: m.order_index)
    return CourseDetail(
        id=course.id,
        title=course.title,
        slug=course.slug,
        description=course.description,
        category=course.category,
        status=course.status,
        cover_image_key=course.cover_image_key,
        created_at=course.created_at,
        updated_at=course.updated_at,
        published_at=course.published_at,
        modules=[_module_summary(m) for m in mods],
    )


def _get_course(db: Session, course_id: uuid.UUID) -> Course:
    course = db.get(Course, course_id)
    if course is None:
        raise APIError(status.HTTP_404_NOT_FOUND, "not_found", "Course not found")
    return course


@router.post("", status_code=status.HTTP_201_CREATED, response_model=CourseEnvelope)
def create_course(body: CourseCreateRequest, db: DbDep, admin: CurrentAdmin) -> CourseEnvelope:
    course = Course(
        title=body.title.strip(),
        slug=unique_course_slug(db, body.title),
        description=body.description.strip(),
        category=body.category.strip(),
        cover_image_key=body.cover_image_key,
        created_by=admin.id,
    )
    db.add(course)
    db.flush()
    return CourseEnvelope(course=_course_detail(course))


@router.get("", response_model=CourseListResponse)
def list_courses(db: DbDep) -> CourseListResponse:
    counts: dict[uuid.UUID, int] = {
        cid: int(n)
        for cid, n in db.execute(
            select(Module.course_id, func.count(Module.id)).group_by(Module.course_id)
        ).all()
    }
    rows = db.scalars(select(Course).order_by(Course.updated_at.desc()))
    return CourseListResponse(
        courses=[
            CourseSummary(
                id=c.id,
                title=c.title,
                slug=c.slug,
                category=c.category,
                status=c.status,
                module_count=int(counts.get(c.id, 0)),
                updated_at=c.updated_at,
                published_at=c.published_at,
            )
            for c in rows
        ]
    )


@router.get("/{course_id}", response_model=CourseEnvelope)
def get_course(course_id: uuid.UUID, db: DbDep) -> CourseEnvelope:
    course = db.scalar(
        select(Course)
        .where(Course.id == course_id)
        .options(selectinload(Course.modules).selectinload(Module.artifacts))
    )
    if course is None:
        raise APIError(status.HTTP_404_NOT_FOUND, "not_found", "Course not found")
    return CourseEnvelope(course=_course_detail(course))


@router.patch("/{course_id}", response_model=CourseEnvelope)
def patch_course(
    course_id: uuid.UUID, body: CoursePatchRequest, db: DbDep, _: CurrentAdmin
) -> CourseEnvelope:
    course = _get_course(db, course_id)
    if body.title is not None:
        course.title = body.title.strip()
    if body.description is not None:
        course.description = body.description.strip()
    if body.category is not None:
        course.category = body.category.strip()
    if "cover_image_key" in body.model_fields_set:
        course.cover_image_key = body.cover_image_key
    db.flush()
    return CourseEnvelope(course=_course_detail(course))


@router.post(
    "/{course_id}/modules",
    status_code=status.HTTP_201_CREATED,
    response_model=ModuleEnvelope,
)
def create_module(
    course_id: uuid.UUID,
    body: ModuleCreateRequest,
    db: DbDep,
    admin: CurrentAdmin,
    background: BackgroundTasks,
) -> ModuleEnvelope:
    course = _get_course(db, course_id)

    link = (body.source_url or "").strip() or None
    if link is None and not body.upload_ids:
        raise APIError(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "no_source", "Add a link or at least one PDF"
        )
    if link is not None:
        detected = detect_source_type(link)
        if detected is None:
            raise APIError(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "unsupported_source",
                f"That URL is not a supported source. Use {SUPPORTED_HINT}.",
            )
        source_type = detected
    else:
        source_type = ModuleSourceType.pdf

    uploads = _lock_uploads(db, body.upload_ids, admin.id)

    # two concurrent creates would both pick max+1 and hit uq_module_course_order
    db.execute(select(Course.id).where(Course.id == course.id).with_for_update())
    max_index = db.scalar(
        select(func.coalesce(func.max(Module.order_index), -1)).where(Module.course_id == course.id)
    )
    next_index = (max_index if max_index is not None else -1) + 1
    module = Module(
        course_id=course.id,
        order_index=next_index,
        title=body.title.strip(),
        source_url=link,
        source_type=source_type,
    )
    db.add(module)
    db.flush()

    provider = get_content_provider()
    jobs = orchestrator.start_module_generation(
        db,
        provider,
        module.id,
        body.types,
        requested_by=admin.id,
        options_by_type=body.options,
        prompts_by_type=body.prompts,
    )
    db.flush()
    # last step that can fail: moving files (compensated on error)
    _claim_uploads(db, course.id, module, uploads)

    dispatch = [(str(j.artifact_id), str(j.job_id), j.type.value) for j in jobs]
    background.add_task(_dispatch_all, dispatch)

    db.refresh(module)
    return ModuleEnvelope(module=_module_summary(module), job_ids=[j.job_id for j in jobs])


def _lock_uploads(db: Session, ids: list[uuid.UUID], admin_id: uuid.UUID) -> list[SourceUpload]:
    """Row-lock the uploads (the hourly purge can't delete one mid-claim) and
    check each is this admin's, complete and unclaimed. Returned in request order."""
    bad = APIError(
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        "bad_upload",
        "An uploaded PDF is missing, unfinished or already used. Upload it again.",
    )
    if len(set(ids)) != len(ids):
        raise bad
    rows = {
        u.id: u
        for u in db.scalars(select(SourceUpload).where(SourceUpload.id.in_(ids)).with_for_update())
    }
    out: list[SourceUpload] = []
    for uid in ids:
        u = rows.get(uid)
        if u is None or u.admin_id != admin_id or u.status is not SourceUploadStatus.complete:
            raise bad
        out.append(u)
    return out


def _safe_stem(file_name: str) -> str:
    stem = file_name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if stem.lower().endswith(".pdf"):
        stem = stem[:-4]
    ascii_ = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", ascii_).lstrip(".-")[:80]
    return cleaned or "file"


def _claim_uploads(
    db: Session, course_id: uuid.UUID, module: Module, uploads: list[SourceUpload]
) -> None:
    storage = get_storage()
    # read every page count before moving anything, so a damaged file fails the
    # request with nothing half-moved
    page_counts = [_page_count(upload) for upload in uploads]
    moved: list[tuple[str, str]] = []  # (original key, new key)
    try:
        for index, upload in enumerate(uploads):
            key = source_key(course_id, module.id, index, _safe_stem(upload.file_name))
            checksum = storage.sha256(upload.storage_key)
            storage.move(upload.storage_key, key)
            moved.append((upload.storage_key, key))
            db.add(
                ModuleSourceFile(
                    module_id=module.id,
                    order_index=index,
                    file_name=upload.file_name,
                    size_bytes=upload.size_bytes,
                    checksum_sha256=checksum,
                    storage_key=key,
                    page_count=page_counts[index],
                    parts=[],
                )
            )
            upload.status = SourceUploadStatus.claimed
            upload.storage_key = key
        db.flush()
        db.refresh(module)
    except BaseException:
        # the request will roll back the DB; put the files back so the uploads
        # (which revert to `complete`) are still claimable
        for original, new in reversed(moved):
            with contextlib.suppress(Exception):
                storage.move(new, original)
        raise


def _page_count(upload: SourceUpload) -> int:
    try:
        reader = PdfReader(str(get_storage().path_for(upload.storage_key)))
        if reader.is_encrypted and not reader.decrypt(""):
            raise ValueError("encrypted")
        return len(reader.pages)
    except Exception:
        raise APIError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "bad_upload",
            f"{upload.file_name} can't be opened (damaged or password-protected)",
        ) from None


def _dispatch_all(items: list[tuple[str, str, str]]) -> None:
    from app.tasks.generation import generate_artifact_task

    for artifact_id, job_id, artifact_type in items:
        generate_artifact_task.apply_async(
            kwargs={"artifact_id": artifact_id, "job_id": job_id},
            queue="audio" if artifact_type == "audio_overview" else "text",
        )


def _get_module(db: Session, module_id: uuid.UUID) -> Module:
    module = db.get(Module, module_id)
    if module is None:
        raise APIError(status.HTTP_404_NOT_FOUND, "not_found", "Module not found")
    return module


@router.patch("/modules/{module_id}", response_model=ModuleSummary)
def rename_module(
    module_id: uuid.UUID, body: ModulePatchRequest, db: DbDep, _: CurrentAdmin
) -> ModuleSummary:
    module = _get_module(db, module_id)
    module.title = body.title.strip()
    db.flush()
    return _module_summary(module)


@router.post("/modules/{module_id}/move", response_model=CourseEnvelope)
def move_module(
    module_id: uuid.UUID, body: ModuleMoveRequest, db: DbDep, _: CurrentAdmin
) -> CourseEnvelope:
    module = _get_module(db, module_id)
    siblings = sorted(
        db.scalars(select(Module).where(Module.course_id == module.course_id)),
        key=lambda m: m.order_index,
    )
    idx = next(i for i, m in enumerate(siblings) if m.id == module.id)
    swap = idx - 1 if body.direction == "up" else idx + 1
    if 0 <= swap < len(siblings):
        other = siblings[swap]
        a, b = module.order_index, other.order_index
        # three-phase via a sentinel: uq_module_course_order is checked per row
        module.order_index = -1
        db.flush()
        other.order_index = a
        db.flush()
        module.order_index = b
        db.flush()
    course = db.get(Course, module.course_id)
    assert course is not None
    return CourseEnvelope(course=_course_detail(course))


@router.post("/modules/{module_id}/regenerate", response_model=ModuleEnvelope)
def regenerate_module(
    module_id: uuid.UUID, db: DbDep, admin: CurrentAdmin, background: BackgroundTasks
) -> ModuleEnvelope:
    module = _get_module(db, module_id)
    jobs = orchestrator.start_module_generation(
        db, get_content_provider(), module.id, list(ARTIFACT_TYPES), requested_by=admin.id
    )
    db.flush()
    background.add_task(
        _dispatch_all, [(str(j.artifact_id), str(j.job_id), j.type.value) for j in jobs]
    )
    db.refresh(module)
    return ModuleEnvelope(module=_module_summary(module), job_ids=[j.job_id for j in jobs])


def _module_file_keys(module: Module) -> list[str]:
    keys = [mf.storage_key for a in module.artifacts for v in a.versions for mf in v.media_files]
    for src in module.source_files:
        keys.append(src.storage_key)
        keys.extend(p["storage_key"] for p in src.parts if p.get("storage_key"))
    return keys


def _delete_module_files(prefix: str, keys: list[str]) -> None:
    """After the delete is committed (a background task runs after the
    response, i.e. after `get_db` commits): remove the module's folder and any
    of its files stored elsewhere. Confined to MEDIA_ROOT by `Storage`."""
    storage = get_storage()
    for key in keys:
        try:
            storage.delete(key)
        except (OSError, ValueError) as exc:
            log.warning("module.file_not_deleted", key=key, error=str(exc))
    try:
        storage.delete_tree(prefix)
    except (OSError, ValueError) as exc:
        log.warning("module.files_not_deleted", prefix=prefix, error=str(exc))


@router.delete("/modules/{module_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_module(
    module_id: uuid.UUID, db: DbDep, _: CurrentAdmin, background: BackgroundTasks
) -> Response:
    module = _get_module(db, module_id)
    course = module.course
    prefix = module_prefix(course.id, module.id)
    keys = _module_file_keys(module)
    db.delete(module)  # BR9 cascade (rows); files go after commit
    db.flush()
    recompute_course_status(db, course)
    background.add_task(_delete_module_files, prefix, keys)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
