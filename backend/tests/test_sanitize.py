"""T020 — HTML sanitiser: hostile inputs must not survive."""

from __future__ import annotations

import pytest

from app.pipeline.parsers._sanitize import sanitize_html

MEDIA = ("/api/media/",)


@pytest.mark.parametrize(
    "hostile",
    [
        "<script>alert(1)</script>",
        "<p>ok</p><script>steal()</script>",
        "<iframe src='https://evil.example'></iframe>",
        "<object data='x.swf'></object>",
        "<embed src='x'>",
        "<style>body{display:none}</style>",
        "<link rel='stylesheet' href='x'>",
        "<form action='/x'><input name='p'></form>",
    ],
)
def test_dangerous_elements_are_removed(hostile: str) -> None:
    out = sanitize_html(hostile)
    for bad in ("<script", "<iframe", "<object", "<embed", "<style", "<link", "<form", "<input"):
        assert bad not in out.lower()


def test_event_handlers_and_style_attrs_stripped() -> None:
    out = sanitize_html('<p onclick="evil()" style="color:red" class="keep">hi</p>')
    assert "onclick" not in out
    assert "style=" not in out
    assert 'class="keep"' in out


def test_javascript_hrefs_are_dropped() -> None:
    out = sanitize_html('<a href="javascript:alert(1)">x</a>')
    assert "javascript:" not in out


def test_external_links_get_safe_rel() -> None:
    out = sanitize_html('<a href="https://example.com">x</a>')
    assert "noopener" in out and "noreferrer" in out


def test_images_only_from_allowed_prefixes() -> None:
    html = (
        '<img src="/api/media/courses/x/hero.png" alt="ok">'
        '<img src="https://evil.example/track.gif" alt="bad">'
        "<img src=x onerror=alert(1)>"
    )
    out = sanitize_html(html, allowed_img_prefixes=MEDIA)
    assert out.count("<img") == 1
    assert "/api/media/courses/x/hero.png" in out
    assert "evil.example" not in out
    assert "onerror" not in out


def test_allowed_formatting_is_kept() -> None:
    out = sanitize_html(
        "<h2>Title</h2><p><strong>bold</strong> and <em>italic</em></p><ul><li>a</li></ul>"
    )
    assert "<h2>Title</h2>" in out
    assert "<strong>bold</strong>" in out
    assert "<li>a</li>" in out


def test_empty_input() -> None:
    assert sanitize_html("") == ""
    assert sanitize_html("   ") == ""
