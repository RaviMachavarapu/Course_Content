"""Admin authentication API (spec.md §5.1) — a scope entirely separate from the
student login. There is deliberately **no** register endpoint here (D3): admins
are created only via the `seed-admin` CLI or admin-only user management.

    POST /api/admin/auth/login                    -> 200 {user} + sdp_admin cookie
    POST /api/admin/auth/logout                   -> 204
    GET  /api/admin/auth/me                       -> 200 {user}
    POST /api/admin/auth/password-reset/request   -> 202 (O6, always — no enumeration)
    POST /api/admin/auth/password-reset/confirm   -> 204
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response, status

from app.api.deps import (
    ClockDep,
    CurrentAdmin,
    DbDep,
    RateLimiterDep,
    RedisDep,
    SessionStoreDep,
    SettingsDep,
)
from app.auth.cookies import clear_device_cookie, clear_session_cookie
from app.auth.csrf import clear_csrf_cookie_after_logout, csrf_protect, ensure_csrf_cookie
from app.auth.login import login_flow
from app.auth.password_reset import (
    confirm_password_reset,
    request_password_reset,
    trust_redeeming_browser,
)
from app.auth.ratelimit import client_ip
from app.auth.sessions import COOKIE_NAMES
from app.models.user import User, UserRole
from app.schemas.auth import LoginRequest, PasswordResetConfirmRequest, PasswordResetRequest
from app.schemas.user import UserEnvelope, UserOut

router = APIRouter(prefix="/api/admin/auth", tags=["admin-auth"])


def _envelope(user: User) -> UserEnvelope:
    return UserEnvelope(user=UserOut.model_validate(user))


@router.post("/login", response_model=UserEnvelope)
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: DbDep,
    store: SessionStoreDep,
    redis_client: RedisDep,
    settings: SettingsDep,
    clock: ClockDep,
) -> UserEnvelope:
    user = login_flow(
        scope="admin",
        role=UserRole.admin,
        email=body.email,
        password=body.password,
        remember=body.remember,
        request=request,
        response=response,
        db=db,
        store=store,
        redis_client=redis_client,
        settings=settings,
        clock=clock,
    )
    return _envelope(user)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(csrf_protect)],
)
def logout(request: Request, store: SessionStoreDep, settings: SettingsDep) -> Response:
    token = request.cookies.get(COOKIE_NAMES["admin"])
    session = store.read("admin", token)
    store.destroy("admin", token)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session_cookie(response, "admin", settings)
    if session is not None and not session.remember:
        # signed in without "Remember this device": leave nothing behind
        clear_device_cookie(response, "admin", settings)
    clear_csrf_cookie_after_logout(request, response, settings, logging_out="admin")
    return response


@router.get("/me", response_model=UserEnvelope)
def me(
    admin: CurrentAdmin, request: Request, response: Response, settings: SettingsDep
) -> UserEnvelope:
    ensure_csrf_cookie(request, response, settings)
    return _envelope(admin)


@router.post("/password-reset/request", status_code=status.HTTP_202_ACCEPTED)
def password_reset_request(
    body: PasswordResetRequest,
    request: Request,
    background: BackgroundTasks,
    db: DbDep,
    redis_client: RedisDep,
    limiter: RateLimiterDep,
    settings: SettingsDep,
) -> Response:
    request_password_reset(
        db,
        redis_client,
        settings,
        limiter,
        background,
        scope="admin",
        email=body.email,
        client_ip=client_ip(request),
        reset_path="/admin/reset-password",
    )
    return Response(status_code=status.HTTP_202_ACCEPTED)


@router.post("/password-reset/confirm", status_code=status.HTTP_204_NO_CONTENT)
def password_reset_confirm(
    body: PasswordResetConfirmRequest,
    db: DbDep,
    redis_client: RedisDep,
    settings: SettingsDep,
    store: SessionStoreDep,
    clock: ClockDep,
) -> Response:
    user = confirm_password_reset(
        db,
        redis_client,
        settings,
        store,
        scope="admin",
        token=body.token,
        new_password=body.password,
    )
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    trust_redeeming_browser(response, settings, scope="admin", user=user, now=clock())
    return response
