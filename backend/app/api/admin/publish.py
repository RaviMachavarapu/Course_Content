"""Admin — publish a module or a whole course (spec.md §3.3, §5.3; BR2-BR5)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from app.api.admin import ADMIN_DEPENDENCIES
from app.api.deps import DbDep
from app.errors import APIError
from app.models.artifact import Artifact
from app.models.course import Course
from app.models.module import Module
from app.schemas.publish import PublishResult, SkippedArtifact
from app.services.publish import _SKIP_REASON, publish_course, publish_module

router = APIRouter(prefix="/api/admin", tags=["admin-publish"], dependencies=ADMIN_DEPENDENCIES)


def _result(
    published: list[Artifact],
    skipped: list[Artifact],
    *,
    module: Module | None,
    course: Course,
) -> PublishResult:
    return PublishResult(
        published=[a.type for a in published],
        skipped=[
            SkippedArtifact(
                type=a.type, status=a.status, reason=_SKIP_REASON.get(a.status, "not ready")
            )
            for a in skipped
        ],
        module_status=module.status if module is not None else None,
        course_status=course.status,
    )


@router.post("/modules/{module_id}/publish", response_model=PublishResult)
def publish_module_endpoint(module_id: uuid.UUID, db: DbDep) -> PublishResult:
    module = db.get(Module, module_id)
    if module is None:
        raise APIError(status.HTTP_404_NOT_FOUND, "not_found", "Module not found")
    published, skipped = publish_module(db, module)
    return _result(published, skipped, module=module, course=module.course)


@router.post("/courses/{course_id}/publish", response_model=PublishResult)
def publish_course_endpoint(course_id: uuid.UUID, db: DbDep) -> PublishResult:
    course = db.get(Course, course_id)
    if course is None:
        raise APIError(status.HTTP_404_NOT_FOUND, "not_found", "Course not found")
    published, skipped = publish_course(db, course)
    return _result(published, skipped, module=None, course=course)
