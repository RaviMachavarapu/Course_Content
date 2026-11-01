"""Uniform error envelope.

Every error response is ``{"error": {"code": "...", "message": "..."}}`` with an
appropriate HTTP status (spec.md §5). `APIError` is the raise-site type; the
handlers below also normalise FastAPI's built-in `HTTPException` and request
validation errors into the same shape.

Only *request input* is a 422: FastAPI's `RequestValidationError`, or a pydantic
`ValidationError` that a handler deliberately converts with `invalid_input`
(e.g. per-type generation options validated deeper than the body schema). Any
other `ValidationError` — say a response model built from malformed stored
data — is a server bug: a logged 500 ``internal_error`` (Sentry sees it).
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.background import BackgroundTask
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.logging import get_logger

log = get_logger("errors")


class APIError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        headers: dict[str, str] | None = None,
        fields: list[dict[str, Any]] | None = None,
        extra: dict[str, Any] | None = None,
        background: BackgroundTask | None = None,
    ) -> None:
        """`extra` adds fields to the error object (e.g. ``retry_after``);
        `background` runs after the error response is sent (e.g. a mail that
        must not change the response or its timing)."""
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.headers = headers
        self.fields = fields
        self.extra = extra
        self.background = background


def _fields(exc: ValidationError | RequestValidationError) -> list[dict[str, Any]]:
    return [
        {"loc": list(err["loc"]), "msg": err["msg"], "type": err["type"]} for err in exc.errors()
    ]


def invalid_input(exc: ValidationError) -> APIError:
    """A pydantic error about the *client's* input → the same 422 envelope as a
    bad request body."""
    return APIError(
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        "validation_error",
        "Request body failed validation",
        fields=_fields(exc),
    )


def _envelope(code: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, **extra}}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(APIError)
    async def _api_error(_: Request, exc: APIError) -> JSONResponse:
        extra = dict(exc.extra or {})
        if exc.fields is not None:
            extra["fields"] = exc.fields
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(exc.code, exc.message, **extra),
            headers=exc.headers,
            background=exc.background,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {
            status.HTTP_401_UNAUTHORIZED: "unauthorized",
            status.HTTP_403_FORBIDDEN: "forbidden",
            status.HTTP_404_NOT_FOUND: "not_found",
            status.HTTP_409_CONFLICT: "conflict",
            status.HTTP_429_TOO_MANY_REQUESTS: "rate_limited",
        }.get(exc.status_code, "error")
        detail = exc.detail if isinstance(exc.detail, str) else code
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(code, detail),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=_envelope(
                "validation_error", "Request body failed validation", fields=_fields(exc)
            ),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        """Anything unhandled (including a stray pydantic `ValidationError`) is a
        server error: log it with the traceback, answer with the envelope and
        nothing internal. Starlette re-raises after this, so Sentry and the
        server log still see it."""
        log.error("http.unhandled_exception", path=request.url.path, exc_info=exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_envelope("internal_error", "Something went wrong on our side."),
        )
