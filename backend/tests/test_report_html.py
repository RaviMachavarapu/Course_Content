"""T020 — report renderer (sanitised HTML)."""

from __future__ import annotations

from app.render.report_html import build_report_html
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


def test_titles_are_html_escaped() -> None:
    tricky = ReportContent(
        title="A < B & C",
        read_minutes=1,
        sections=[ReportSection(heading="H", html="<p>x</p>")],
    )
    out = build_report_html(tricky)
    assert "A &lt; B &amp; C" in out
