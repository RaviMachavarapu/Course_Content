"""HTML sanitisation for NotebookLM-returned markup.

Studio output is never trusted. Everything is passed through `nh3` (Rust
`ammonia`) with a strict allowlist before it is stored or rendered — no
``script``/``style``/``iframe``/``object``/``embed``, no event handlers, and
images only from our own access-checked media endpoint.
"""

from __future__ import annotations

from collections.abc import Iterable

import nh3
from bs4 import BeautifulSoup

ALLOWED_TAGS: set[str] = {
    "a",
    "abbr",
    "b",
    "blockquote",
    "br",
    "caption",
    "code",
    "col",
    "colgroup",
    "dd",
    "div",
    "dl",
    "dt",
    "em",
    "figcaption",
    "figure",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "i",
    "img",
    "li",
    "ol",
    "p",
    "pre",
    "s",
    "small",
    "span",
    "strong",
    "sub",
    "sup",
    "table",
    "tbody",
    "td",
    "tfoot",
    "th",
    "thead",
    "tr",
    "u",
    "ul",
}

ALLOWED_ATTRIBUTES: dict[str, set[str]] = {
    "*": {"class"},
    "a": {"href", "title"},
    "img": {"src", "alt", "title", "width", "height"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan", "scope"},
}

ALLOWED_URL_SCHEMES: set[str] = {"http", "https", "mailto"}


def sanitize_html(html: str, *, allowed_img_prefixes: Iterable[str] = ()) -> str:
    """Clean `html` against the strict allowlist.

    `<img>` elements whose `src` does not begin with one of `allowed_img_prefixes`
    (typically the app's ``/api/media/`` path) are dropped entirely. External
    `<a>` links are marked `rel="noopener noreferrer nofollow"`.
    """
    if not html or not html.strip():
        return ""

    cleaned = nh3.clean(
        html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        url_schemes=ALLOWED_URL_SCHEMES,
        link_rel="noopener noreferrer nofollow",
        strip_comments=True,
    )

    prefixes = tuple(allowed_img_prefixes)
    soup = BeautifulSoup(cleaned, "lxml")
    for img in soup.find_all("img"):
        src = (img.get("src") or "").strip()
        if not src or (prefixes and not src.startswith(prefixes)):
            img.decompose()

    body = soup.body
    return body.decode_contents() if body is not None else str(soup)
