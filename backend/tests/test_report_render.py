"""T020 — report renderer (sanitised HTML + matching PDF)."""

from __future__ import annotations

import pytest

from app.render import RenderError
from app.render.report_pdf import build_report_html, render_report
from app.schemas.content import ReportContent, ReportSection

CONTENT = ReportContent(
    title="Neural Networks: An Overview",
    read_minutes=7,
    key_takeaways=["Units combine non-linearly", "Depth composes features"],
    sections=[
        ReportSection(
            heading="How they work", html="<p>A neuron sums <strong>weighted</strong> inputs.</p>"
        ),
        ReportSection(
            heading="Danger",
            html="<p>safe</p><script>alert(1)</script><img src='https://evil.example/x.png'>",
        ),
    ],
)


def test_build_html_is_deterministic_and_sanitised() -> None:
    a = build_report_html(CONTENT)
    b = build_report_html(CONTENT)
    assert a == b
    assert "<h1>Neural Networks: An Overview</h1>" in a
    assert "Key takeaways" in a
    assert "<strong>weighted</strong>" in a
    assert "<script" not in a.lower()
    assert "evil.example" not in a


def test_render_report_produces_a_pdf_with_matching_html() -> None:
    rendered = render_report(CONTENT)
    assert rendered.pdf[:5] == b"%PDF-"
    assert len(rendered.pdf) > 1000
    assert rendered.html == build_report_html(CONTENT)


def test_render_report_wraps_weasyprint_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Boom:
        def __init__(self, *_a: object, **_k: object) -> None:
            raise RuntimeError("bad font config")

    monkeypatch.setattr("weasyprint.HTML", _Boom)
    with pytest.raises(RenderError, match="bad font config"):
        render_report(CONTENT)


def test_render_report_empty_pdf_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Empty:
        def __init__(self, *_a: object, **_k: object) -> None:
            pass

        def write_pdf(self) -> bytes:
            return b""

    monkeypatch.setattr("weasyprint.HTML", _Empty)
    with pytest.raises(RenderError, match="no bytes"):
        render_report(CONTENT)


def test_titles_are_html_escaped() -> None:
    tricky = ReportContent(
        title="A < B & C",
        read_minutes=1,
        sections=[ReportSection(heading="H", html="<p>x</p>")],
    )
    out = build_report_html(tricky)
    assert "A &lt; B &amp; C" in out
