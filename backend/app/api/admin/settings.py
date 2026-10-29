"""Admin — Settings: admin-user management + Audio Overview defaults (spec.md §3.6).

    GET   /api/admin/users              -> admin accounts
    POST  /api/admin/users              -> create an admin (BTN-ST5)
    PATCH /api/admin/users/{id}         -> activate / deactivate (BTN-ST6; not self)
    GET   /api/admin/settings/audio     -> current voice/style + choices
    PUT   /api/admin/settings/audio     -> persist voice/style (BTN-ST4)

Generation Prompts (BTN-ST1/ST2) and NotebookLM (BTN-ST3) already have routers
(`admin_prompts`, `admin_mcp`); the Settings page just consumes them.
"""

from __future__ import annotations

import uuid
from typing import Protocol

from fastapi import APIRouter, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.admin import ADMIN_DEPENDENCIES
from app.api.deps import CurrentAdmin, DbDep, SessionStoreDep
from app.auth.hashing import hash_password
from app.auth.passwords import validate_password_strength
from app.errors import APIError
from app.models.user import User, UserRole, normalize_email
from app.schemas.settings import (
    AdminUserCreateRequest,
    AdminUserListResponse,
    AdminUserOut,
    AdminUserPatchRequest,
    AudioSettings,
    AudioSettingsResponse,
)
from app.services import settings as settings_svc

router = APIRouter(tags=["admin-settings"], dependencies=ADMIN_DEPENDENCIES)


# -- admin users ------------------------------------------------------------
@router.get("/api/admin/users", response_model=AdminUserListResponse)
def list_admins(db: DbDep) -> AdminUserListResponse:
    rows = db.scalars(
        select(User).where(User.role == UserRole.admin).order_by(User.created_at.asc())
    )
    return AdminUserListResponse(users=[AdminUserOut.model_validate(u) for u in rows])


@router.post("/api/admin/users", status_code=status.HTTP_201_CREATED, response_model=AdminUserOut)
def create_admin(body: AdminUserCreateRequest, db: DbDep, _: CurrentAdmin) -> AdminUserOut:
    email = normalize_email(body.email)
    if db.scalar(select(User).where(User.email == email)) is not None:
        raise APIError(status.HTTP_409_CONFLICT, "email_taken", "That email is already in use.")
    validate_password_strength(body.password)
    user = User(
        email=email,
        role=UserRole.admin,
        display_name=body.display_name.strip(),
        password_hash=hash_password(body.password),
    )
    db.add(user)
    db.flush()
    return AdminUserOut.model_validate(user)


class _Revoker(Protocol):
    def revoke_user(self, user_id: str) -> None: ...


@router.patch("/api/admin/users/{user_id}", response_model=AdminUserOut)
def set_admin_active(
    user_id: uuid.UUID,
    body: AdminUserPatchRequest,
    db: DbDep,
    admin: CurrentAdmin,
    store: SessionStoreDep,
) -> AdminUserOut:
    user = db.get(User, user_id)
    if user is None or user.role is not UserRole.admin:
        raise APIError(status.HTTP_404_NOT_FOUND, "not_found", "Admin not found")
    if user.id == admin.id and not body.is_active:
        raise APIError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "cannot_deactivate_self",
            "You cannot deactivate your own account.",
        )
    if not body.is_active:
        _deactivate(db, user, admin, store)
    else:
        user.is_active = True
    db.flush()
    return AdminUserOut.model_validate(user)


def _deactivate(db: Session, user: User, admin: User, store: _Revoker) -> None:
    """Lock every active admin (in id order, so two of these can't deadlock)
    before deciding: two admins deactivating each other at once would
    otherwise leave none. The acting admin must still be active once the
    locks are held."""
    active = db.scalars(
        select(User)
        .where(User.role == UserRole.admin, User.is_active.is_(True))
        .order_by(User.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).all()
    remaining = [u for u in active if u.id != user.id]
    if not remaining or all(u.id != admin.id for u in remaining):
        raise APIError(
            status.HTTP_409_CONFLICT,
            "last_active_admin",
            "At least one admin must stay active.",
        )
    user.is_active = False
    # their open sessions end now, and stay ended if the account is
    # reactivated later (a stolen laptop's session must not come back)
    store.revoke_user(str(user.id))


# -- audio overview defaults ---------------------------------------------------
@router.get("/api/admin/settings/audio", response_model=AudioSettingsResponse)
def get_audio(db: DbDep) -> AudioSettingsResponse:
    current = settings_svc.get_audio_settings(db)
    return AudioSettingsResponse(settings=AudioSettings(**current))


@router.put("/api/admin/settings/audio", response_model=AudioSettingsResponse)
def put_audio(body: AudioSettings, db: DbDep, _: CurrentAdmin) -> AudioSettingsResponse:
    norm = body.normalized()
    saved = settings_svc.set_audio_settings(db, voice=norm.voice, style=norm.style)
    return AudioSettingsResponse(settings=AudioSettings(**saved))
