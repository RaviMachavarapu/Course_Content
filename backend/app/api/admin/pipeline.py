"""Admin — Recent Pipeline table / View All (spec.md §3.2, §5.2)."""

from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.admin import ADMIN_DEPENDENCIES
from app.api.deps import DbDep
from app.models.course import Course
from app.models.enums import ARTIFACT_TYPES, ModuleStatus
from app.models.module import Module
from app.schemas.pipeline import PipelineDot, PipelineResponse, PipelineRow

router = APIRouter(
    prefix="/api/admin/pipeline", tags=["admin-pipeline"], dependencies=ADMIN_DEPENDENCIES
)

_ORDER = {t: i for i, t in enumerate(ARTIFACT_TYPES)}


@router.get("", response_model=PipelineResponse)
def pipeline(
    db: DbDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(5, ge=1, le=100),
    status: ModuleStatus | None = None,
    q: str | None = None,
) -> PipelineResponse:
    stmt = (
        select(Module)
        .join(Course)
        .options(selectinload(Module.artifacts), selectinload(Module.course))
    )
    if status is not None:
        stmt = stmt.where(Module.status == status)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(Module.title.ilike(like) | Module.source_url.ilike(like))

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(Module.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    )

    return PipelineResponse(
        rows=[
            PipelineRow(
                module_id=m.id,
                course_id=m.course_id,
                course_title=m.course.title,
                module_title=m.title,
                source_url=m.source_url,
                created_at=m.created_at,
                global_status=m.status,
                dots=[
                    PipelineDot(type=a.type, status=a.status)
                    for a in sorted(m.artifacts, key=lambda a: _ORDER.get(a.type, 99))
                ],
            )
            for m in rows
        ],
        page=page,
        page_size=page_size,
        total=int(total),
    )
