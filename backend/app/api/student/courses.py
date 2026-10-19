"""Student catalog API (spec.md §3.8).

    GET /api/student/courses  -> published courses, with the caller's progress
"""

from __future__ import annotations

from fastapi import APIRouter, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentStudent, DbDep
from app.errors import APIError
from app.models.artifact import Artifact
from app.models.course import Course
from app.models.enums import ARTIFACT_TYPES, ArtifactType
from app.models.module import Module
from app.models.progress import ArtifactProgress, CourseProgress
from app.schemas.student import (
    CatalogCourseOut,
    CatalogResponse,
    WorkspaceArtifactOut,
    WorkspaceCourseOut,
    WorkspaceModuleOut,
)
from app.storage.service import get_storage

_ARTIFACT_ORDER = {t: i for i, t in enumerate(ARTIFACT_TYPES)}

router = APIRouter(prefix="/api/student", tags=["student-courses"])


def _published_artifacts(module: Module) -> list[Artifact]:
    return [a for a in module.artifacts if a.published_version_id is not None]


def _audio_seconds(artifact: Artifact) -> int | None:
    version = next((v for v in artifact.versions if v.id == artifact.published_version_id), None)
    if version is None or not version.content_json:
        return None
    raw = version.content_json.get("duration_seconds")
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


@router.get("/courses", response_model=CatalogResponse)
def list_catalog(db: DbDep, student: CurrentStudent) -> CatalogResponse:
    courses = (
        db.scalars(
            select(Course)
            .options(
                selectinload(Course.modules)
                .selectinload(Module.artifacts)
                .selectinload(Artifact.versions)
            )
            .order_by(Course.published_at.desc().nullslast(), Course.title.asc())
        )
        .unique()
        .all()
    )

    completed_ids = set(
        db.scalars(
            select(ArtifactProgress.artifact_id).where(
                ArtifactProgress.user_id == student.id,
                ArtifactProgress.completed_at.is_not(None),
            )
        )
    )

    out: list[CatalogCourseOut] = []
    categories: set[str] = set()
    storage = get_storage()

    for course in courses:
        modules = sorted(course.modules, key=lambda m: m.order_index)
        live_modules = [(m, _published_artifacts(m)) for m in modules]
        live_modules = [(m, arts) for m, arts in live_modules if arts]
        if not live_modules:
            continue  # a course with zero published modules never appears

        counts: dict[ArtifactType, int] = {}
        total_published = 0
        done = 0
        audio_seconds = 0
        has_audio_duration = False
        next_module_index = 0
        found_incomplete = False

        for idx, (_module, arts) in enumerate(live_modules):
            module_incomplete = False
            for artifact in arts:
                counts[artifact.type] = counts.get(artifact.type, 0) + 1
                total_published += 1
                if artifact.id in completed_ids:
                    done += 1
                else:
                    module_incomplete = True
                if artifact.type is ArtifactType.audio_overview:
                    secs = _audio_seconds(artifact)
                    if secs is not None:
                        audio_seconds += secs
                        has_audio_duration = True
            if module_incomplete and not found_incomplete:
                next_module_index = idx
                found_incomplete = True

        percent = round(100 * done / total_published) if total_published else 0
        if course.category:
            categories.add(course.category)

        out.append(
            CatalogCourseOut(
                id=course.id,
                slug=course.slug,
                title=course.title,
                description=course.description,
                category=course.category,
                cover_image_url=(
                    storage.url_for(course.cover_image_key) if course.cover_image_key else None
                ),
                module_count=len(live_modules),
                artifact_counts=counts,
                total_audio_seconds=audio_seconds if has_audio_duration else None,
                percent_complete=percent,
                next_module_index=next_module_index,
            )
        )

    return CatalogResponse(courses=out, categories=sorted(categories))


@router.get("/courses/{slug}", response_model=WorkspaceCourseOut)
def course_workspace(slug: str, db: DbDep, student: CurrentStudent) -> WorkspaceCourseOut:
    """Workspace shell data: ordered published modules, each with its published
    artifact types + the caller's completion. 404 for a course with nothing
    published (never leak an unpublished course)."""
    course = db.scalar(
        select(Course)
        .where(Course.slug == slug)
        .options(
            selectinload(Course.modules)
            .selectinload(Module.artifacts)
            .selectinload(Artifact.versions)
        )
    )
    if course is None:
        raise APIError(status.HTTP_404_NOT_FOUND, "not_found", "Course not found")

    completed_ids = set(
        db.scalars(
            select(ArtifactProgress.artifact_id).where(
                ArtifactProgress.user_id == student.id,
                ArtifactProgress.completed_at.is_not(None),
            )
        )
    )

    modules_out: list[WorkspaceModuleOut] = []
    total = done = 0
    ordered = sorted(course.modules, key=lambda m: m.order_index)
    live = [(m, _published_artifacts(m)) for m in ordered]
    live = [(m, arts) for m, arts in live if arts]
    if not live:
        raise APIError(status.HTTP_404_NOT_FOUND, "not_found", "Course not found")

    for index, (module, arts) in enumerate(live):
        arts = sorted(arts, key=lambda a: _ARTIFACT_ORDER.get(a.type, 99))
        m_done = sum(1 for a in arts if a.id in completed_ids)
        total += len(arts)
        done += m_done
        modules_out.append(
            WorkspaceModuleOut(
                index=index,
                id=module.id,
                title=module.title,
                percent_complete=round(100 * m_done / len(arts)) if arts else 0,
                artifacts=[
                    WorkspaceArtifactOut(id=a.id, type=a.type, completed=a.id in completed_ids)
                    for a in arts
                ],
            )
        )

    current_index = 0
    progress = db.scalar(
        select(CourseProgress).where(
            CourseProgress.user_id == student.id, CourseProgress.course_id == course.id
        )
    )
    if progress is not None and progress.last_module_id is not None:
        current_index = next((m.index for m in modules_out if m.id == progress.last_module_id), 0)
    else:
        current_index = next((m.index for m in modules_out if m.percent_complete < 100), 0)

    return WorkspaceCourseOut(
        id=course.id,
        slug=course.slug,
        title=course.title,
        description=course.description,
        percent_complete=round(100 * done / total) if total else 0,
        current_module_index=current_index,
        modules=modules_out,
    )
