"""HTTP client for the typeset service (app/render/typeset_client.py), against
`httpx.MockTransport` — never the live service."""

from __future__ import annotations

import base64
import json
from collections.abc import Callable

import httpx
import pytest

from app.config import get_settings
from app.render.typeset_client import (
    TypesetError,
    TypesetResult,
    TypesetUnavailable,
    render_pdf,
)

Handler = Callable[[httpx.Request], httpx.Response]


def _client(handler: Handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_default_endpoint_and_timeout() -> None:
    settings = get_settings()
    assert settings.typeset_endpoint == "http://typeset:8080"
    assert settings.typeset_timeout_sec >= 180


def test_success_posts_markdown_title_and_base64_images() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            content=b"%PDF-1.7 ...",
            headers={"content-type": "application/pdf", "X-Typeset-Fallback": "2+images"},
        )

    result = render_pdf("# Hi $x$", "A & B", {"a.png": b"\x89PNG..."}, client=_client(handler))
    assert result == TypesetResult(pdf=b"%PDF-1.7 ...", fallback="2+images")
    (request,) = seen
    assert request.method == "POST"
    assert str(request.url) == "http://typeset:8080/pdf"
    body = json.loads(request.content)
    assert body == {
        "markdown": "# Hi $x$",
        "title": "A & B",
        "images": {"a.png": base64.b64encode(b"\x89PNG...").decode()},
    }


def test_endpoint_comes_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TYPESET_ENDPOINT", "http://elsewhere:9000/")
    get_settings.cache_clear()
    urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        return httpx.Response(200, content=b"%PDF-1.7")

    try:
        render_pdf("x", "t", {}, client=_client(handler))
    finally:
        get_settings.cache_clear()
    assert urls == ["http://elsewhere:9000/pdf"]


def test_missing_fallback_header_reads_as_zero() -> None:
    result = render_pdf(
        "x", "t", {}, client=_client(lambda r: httpx.Response(200, content=b"%PDF-1.7"))
    )
    assert result.fallback == "0"


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_crash_busy_or_timeout_is_unavailable(status: int) -> None:
    client = _client(lambda r: httpx.Response(status, json={"error": "busy"}))
    with pytest.raises(TypesetUnavailable, match="busy"):
        render_pdf("x", "t", {}, client=client)


def test_connect_error_is_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    with pytest.raises(TypesetUnavailable):
        render_pdf("x", "t", {}, client=_client(handler))


def test_client_timeout_is_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(TypesetUnavailable):
        render_pdf("x", "t", {}, client=_client(handler))


@pytest.mark.parametrize("status", [400, 404, 422])
def test_build_failures_are_errors(status: int) -> None:
    client = _client(lambda r: httpx.Response(status, json={"error": "build failed: bad"}))
    with pytest.raises(TypesetError, match="build failed: bad"):
        render_pdf("x", "t", {}, client=client)


def test_non_json_error_body() -> None:
    client = _client(lambda r: httpx.Response(422, text="oops"))
    with pytest.raises(TypesetError, match="422"):
        render_pdf("x", "t", {}, client=client)


def test_200_that_is_not_a_pdf_is_an_error() -> None:
    client = _client(lambda r: httpx.Response(200, content=b"<html>"))
    with pytest.raises(TypesetError):
        render_pdf("x", "t", {}, client=client)


def test_unavailable_is_not_an_error_subclass() -> None:
    # Task 5 retries TypesetUnavailable and gives up on TypesetError.
    assert not issubclass(TypesetUnavailable, TypesetError)
    assert not issubclass(TypesetError, TypesetUnavailable)
