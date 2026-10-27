"""Report renderer — `ReportContent` -> the sanitised HTML the student
workspace (S7) displays (`ArtifactVersion.content_html`).

The downloadable PDF is typeset separately from `content_json`
(app/pipeline/artifact_pdf.py).
"""

from __future__ import annotations

import html as _html

from app.config import get_settings
from app.pipeline.parsers._sanitize import sanitize_html
from app.schemas.content import ReportContent


def _media_prefixes() -> tuple[str, ...]:
    base = get_settings().public_base_url.rstrip("/")
    return (f"{base}/api/media/", "/api/media/")


def build_report_html(content: ReportContent) -> str:
    """The sanitised body HTML for the on-screen view."""
    prefixes = _media_prefixes()
    parts: list[str] = [f"<h1>{_html.escape(content.title)}</h1>"]
    parts.append(f'<p class="meta">About {content.read_minutes} min read</p>')

    if content.key_takeaways:
        items = "".join(f"<li>{_html.escape(t)}</li>" for t in content.key_takeaways)
        parts.append(f'<div class="takeaways"><h2>Key takeaways</h2><ul>{items}</ul></div>')

    for section in content.sections:
        parts.append(f"<h2>{_html.escape(section.heading)}</h2>")
        parts.append(sanitize_html(section.html, allowed_img_prefixes=prefixes))

    return "".join(parts)
