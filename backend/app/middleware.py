"""HTTP middleware."""

from __future__ import annotations

import time
import uuid

import structlog
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.logging import get_logger

REQUEST_ID_HEADER = "X-Request-ID"
log = get_logger("http")


class RequestContextMiddleware:
    """Assigns each request a ``request_id``, binds it (plus method and path) to
    the structlog context for the lifetime of the request, echoes it back in the
    response header, and logs one access line with status and duration.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )
        start = time.perf_counter()
        status_code = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = message.setdefault("headers", [])
                headers.append((REQUEST_ID_HEADER.encode(), request_id.encode()))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            log.info("http.request", status=status_code, duration_ms=duration_ms)
            structlog.contextvars.clear_contextvars()


class SecurityHeadersMiddleware:
    """Adds baseline security headers to every response. HSTS is emitted only in
    production (it is meaningless — and a footgun — over plain-HTTP dev)."""

    _STATIC: tuple[tuple[bytes, bytes], ...] = (
        (b"x-content-type-options", b"nosniff"),
        (b"x-frame-options", b"DENY"),
        (b"referrer-policy", b"strict-origin-when-cross-origin"),
        (b"cross-origin-opener-policy", b"same-origin"),
    )

    def __init__(self, app: ASGIApp, *, hsts: bool = False) -> None:
        self.app = app
        self._headers = list(self._STATIC)
        if hsts:
            self._headers.append(
                (b"strict-transport-security", b"max-age=63072000; includeSubDomains")
            )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                present = {name.lower() for name, _ in headers}
                headers.extend((n, v) for n, v in self._headers if n not in present)
            await send(message)

        await self.app(scope, receive, send_wrapper)
