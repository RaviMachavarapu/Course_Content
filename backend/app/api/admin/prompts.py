"""Admin prompt-template settings API (spec.md §5.4).

    GET  /api/admin/prompts                       -> six active templates
    GET  /api/admin/prompts/{type}               -> active + version history
    PUT  /api/admin/prompts/{type}   {body}      -> new active version
    POST /api/admin/prompts/{type}/restore-default -> revert to the seed body
"""

from __future__ import annotations

from fastapi import APIRouter, status

from app.api.admin import ADMIN_DEPENDENCIES
from app.api.deps import CurrentAdmin, DbDep
from app.errors import APIError
from app.models.enums import ARTIFACT_TYPES, ArtifactType
from app.schemas.prompts import (
    PromptDetailResponse,
    PromptListResponse,
    PromptOut,
    PromptResponse,
    PromptUpdateRequest,
)
from app.services import prompts as svc

router = APIRouter(
    prefix="/api/admin/prompts",
    tags=["admin-prompts"],
    dependencies=ADMIN_DEPENDENCIES,
)


@router.get("", response_model=PromptListResponse)
def list_active(db: DbDep) -> PromptListResponse:
    templates = []
    for artifact_type in ARTIFACT_TYPES:
        active = svc.get_active_template(db, artifact_type)
        if active is None:
            svc.get_active_body(db, artifact_type)  # self-heal
            active = svc.get_active_template(db, artifact_type)
        assert active is not None
        templates.append(PromptOut.model_validate(active))
    return PromptListResponse(templates=templates)


@router.get("/{artifact_type}", response_model=PromptDetailResponse)
def get_one(artifact_type: ArtifactType, db: DbDep) -> PromptDetailResponse:
    svc.get_active_body(db, artifact_type)  # ensure an active row exists
    history = svc.version_history(db, artifact_type)
    active = next(t for t in history if t.is_active)
    return PromptDetailResponse(
        active=PromptOut.model_validate(active),
        history=[PromptOut.model_validate(t) for t in history],
    )


@router.put("/{artifact_type}", response_model=PromptResponse)
def update(
    artifact_type: ArtifactType,
    body: PromptUpdateRequest,
    db: DbDep,
    admin: CurrentAdmin,
) -> PromptResponse:
    if not body.body.strip():
        raise APIError(status.HTTP_422_UNPROCESSABLE_ENTITY, "empty_body", "Prompt body is empty")
    template = svc.update_prompt(db, artifact_type, body.body, updated_by=admin.id)
    return PromptResponse(template=PromptOut.model_validate(template))


@router.post("/{artifact_type}/restore-default", response_model=PromptResponse)
def restore(
    artifact_type: ArtifactType,
    db: DbDep,
    admin: CurrentAdmin,
) -> PromptResponse:
    template = svc.restore_default(db, artifact_type, updated_by=admin.id)
    return PromptResponse(template=PromptOut.model_validate(template))
