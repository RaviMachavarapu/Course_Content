"""Student authentication API (spec.md §5.1).

POST /api/student/auth/register                -> 201 {user} + sdp_student cookie
POST /api/student/auth/login                    -> 200 {user} + sdp_student cookie
POST /api/student/auth/logout                   -> 204
GET  /api/student/auth/me                       -> 200 {user}
POST /api/student/auth/password-reset/request   -> 202 (O6, always — no enumeration)
POST /api/student/auth/password-reset/confirm   -> 204
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import (
    ClockDep,
    CurrentStudent,
    DbDep,
    RateLimiterDep,
    RedisDep,
    SessionStoreDep,
    SettingsDep,
)
from app.auth.cookies import (
    clear_device_cookie_after_logout,
    clear_session_cookie,
    set_session_cookie,
)
from app.auth.csrf import (
    clear_csrf_cookie_after_logout,
    csrf_protect,
    ensure_csrf_cookie,
    issue_csrf_cookie,
)
from app.auth.hashing import hash_password
from app.auth.login import login_flow
from app.auth.password_reset import (
    confirm_password_reset,
    request_password_reset,
    trust_redeeming_browser,
)
from app.auth.passwords import validate_password_strength
from app.auth.ratelimit import client_ip, parse_rate
from app.auth.sessions import COOKIE_NAMES
from app.errors import APIError
from app.models.user import User, UserRole, normalize_email
from app.schemas.auth import (
    LoginRequest,
    PasswordResetConfirmRequest,
    PasswordResetRequest,
    RegisterRequest,
)
from app.schemas.user import UserEnvelope, UserOut

router = APIRouter(prefix="/api/student/auth", tags=["student-auth"])


def _envelope(user: User) -> UserEnvelope:
    return UserEnvelope(user=UserOut.model_validate(user))


def _email_taken(db: Session, email: str) -> int:
    return db.scalar(select(func.count()).select_from(User).where(User.email == email)) or 0


@router.post("/register", status_code=status.HTTP_201_CREATED, response_model=UserEnvelope)
def register(
    body: RegisterRequest,
    request: Request,
    response: Response,
    db: DbDep,
    store: SessionStoreDep,
    limiter: RateLimiterDep,
    settings: SettingsDep,
) -> UserEnvelope:
    # every attempt counts: each one costs an Argon2 hash
    limit, window = parse_rate(settings.register_rate_limit)
    if not limiter.hit(f"rl:register:ip:{client_ip(request)}", limit, window):
        raise APIError(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "rate_limited",
            "Too many attempts. Try again later.",
        )
    validate_password_strength(body.password)
    email = normalize_email(body.email)
    taken = APIError(status.HTTP_409_CONFLICT, "email_taken", "That email is already registered")

    if _email_taken(db, email):
        raise taken

    user = User(
        email=email,
        password_hash=hash_password(body.password),
        role=UserRole.student,
        display_name=body.display_name,
    )
    # a concurrent register of the same email can win between the check and
    # this insert: the unique index decides, and the loser gets 409, not 500
    try:
        with db.begin_nested():
            db.add(user)
            db.flush()
    except IntegrityError:
        raise taken from None

    token = store.create(str(user.id), "student")
    set_session_cookie(response, "student", token, store, settings)
    issue_csrf_cookie(response, settings)
    return _envelope(user)


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
        scope="student",
        role=UserRole.student,
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
    token = request.cookies.get(COOKIE_NAMES["student"])
    session = store.read("student", token)
    store.destroy("student", token)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session_cookie(response, "student", settings)
    clear_device_cookie_after_logout(request, response, "student", session, settings)
    clear_csrf_cookie_after_logout(request, response, settings, logging_out="student")
    return response


@router.get("/me", response_model=UserEnvelope)
def me(
    student: CurrentStudent, request: Request, response: Response, settings: SettingsDep
) -> UserEnvelope:
    ensure_csrf_cookie(request, response, settings)
    return _envelope(student)


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
        scope="student",
        email=body.email,
        client_ip=client_ip(request),
        reset_path="/reset-password",
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
        scope="student",
        token=body.token,
        new_password=body.password,
    )
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    trust_redeeming_browser(response, settings, scope="student", user=user, now=clock())
    return response
