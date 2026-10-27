"""HTTP client for the internal `typeset` service (pandoc + xelatex PDFs).

`POST {typeset_endpoint}/pdf` with `{"markdown", "title", "images": {name: base64}}`
returns the PDF; the `X-Typeset-Fallback` header says how many formulas had to
be shown as source (`0`, `<n>`, `<n>+images` or `all`), with `+glyphs`
appended when a character had no glyph in any font (the task logs any marker
other than `0` as a warning).

`TypesetUnavailable` is transient (service down, busy, out of time, or a
500 crash): retry
later. `TypesetError` is permanent for this document: don't retry.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass

import httpx

from app.config import get_settings

# 500 too: an unexpected service crash is worth another try later.
_RETRYABLE = {
    httpx.codes.INTERNAL_SERVER_ERROR,
    httpx.codes.BAD_GATEWAY,
    httpx.codes.SERVICE_UNAVAILABLE,
    httpx.codes.GATEWAY_TIMEOUT,
}


class TypesetUnavailable(Exception):
    """The service can't be reached, is busy, or ran out of time; retry later."""


class TypesetError(Exception):
    """The service rejected the request or couldn't build the document."""


@dataclass(frozen=True)
class TypesetResult:
    pdf: bytes
    #: the service's `X-Typeset-Fallback` header
    fallback: str


def _error_message(resp: httpx.Response) -> str:
    try:
        data = resp.json()
    except ValueError:
        data = None
    detail = data.get("error") if isinstance(data, dict) else None
    return f"typeset service returned {resp.status_code}: {detail or resp.text[:500]}"


def render_pdf(
    markdown: str,
    title: str,
    images: dict[str, bytes],
    *,
    client: httpx.Client | None = None,
) -> TypesetResult:
    """Typeset `markdown` (pandoc Markdown, formulas in `$…$`/`$$…$$`) into a PDF.

    `title` is plain-text PDF metadata (the service doesn't print it). `images` maps the names used
    in `![](name)` to PNG/JPEG/PDF bytes. `client` is for tests.
    """
    settings = get_settings()
    url = f"{settings.typeset_endpoint.rstrip('/')}/pdf"
    payload = {
        "markdown": markdown,
        "title": title,
        "images": {name: base64.b64encode(data).decode("ascii") for name, data in images.items()},
    }
    timeout = httpx.Timeout(settings.typeset_timeout_sec, connect=10.0)
    try:
        if client is None:
            with httpx.Client(timeout=timeout) as own:
                resp = own.post(url, json=payload)
        else:
            resp = client.post(url, json=payload, timeout=timeout)
    except httpx.TransportError as exc:  # connect errors and timeouts included
        raise TypesetUnavailable(f"typeset service unreachable: {exc!r}") from exc

    if resp.status_code in _RETRYABLE:
        raise TypesetUnavailable(_error_message(resp))
    if resp.status_code != httpx.codes.OK:
        raise TypesetError(_error_message(resp))
    if not resp.content.startswith(b"%PDF-"):
        raise TypesetError("typeset service returned 200 without a PDF")
    return TypesetResult(pdf=resp.content, fallback=resp.headers.get("X-Typeset-Fallback", "0"))
