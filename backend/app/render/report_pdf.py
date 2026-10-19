"""Report renderer — `ReportContent` -> sanitised HTML + a matching PDF.

The same sanitised HTML string is what the student workspace (S7) displays and
what WeasyPrint turns into the downloadable `.pdf`, so on-screen == PDF.
"""

from __future__ import annotations

import html as _html
from dataclasses import dataclass

from app.config import get_settings
from app.pipeline.parsers._sanitize import sanitize_html
from app.render import RenderError
from app.schemas.content import ReportContent

_STYLE = """
  @page { size: A4; margin: 22mm 20mm; }
  body { font-family: "Inter", "Public Sans", system-ui, sans-serif;
         color: #191c1e; line-height: 1.6; font-size: 11pt; }
  h1 { font-family: "Public Sans", system-ui, sans-serif; color: #142d6a;
       font-size: 22pt; margin: 0 0 4pt; }
  h2 { font-family: "Public Sans", system-ui, sans-serif; color: #142d6a;
       font-size: 14pt; margin: 18pt 0 6pt; }
  .meta { color: #444650; font-size: 9pt; margin-bottom: 14pt; }
  .takeaways { background: #eceef0; border-radius: 8px; padding: 10pt 14pt; margin: 12pt 0; }
  .takeaways h2 { margin-top: 0; font-size: 12pt; }
  a { color: #142d6a; }
  img { max-width: 100%; }
  table { border-collapse: collapse; width: 100%; }
  td, th { border: 1px solid #c5c6d2; padding: 4pt 6pt; text-align: left; }
"""


@dataclass(frozen=True)
class RenderedReport:
    html: str  # sanitised body HTML for on-screen display (S7)
    pdf: bytes  # A4 PDF, identical content


def _media_prefixes() -> tuple[str, ...]:
    base = get_settings().public_base_url.rstrip("/")
    return (f"{base}/api/media/", "/api/media/")


def build_report_html(content: ReportContent) -> str:
    """The sanitised body HTML shared by the on-screen view and the PDF."""
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


def render_report(content: ReportContent) -> RenderedReport:
    body = build_report_html(content)
    document = (
        f"<!doctype html><html><head><meta charset='utf-8'><style>{_STYLE}</style>"
        f"</head><body>{body}</body></html>"
    )
    try:
        from weasyprint import HTML  # imported lazily: heavy native deps

        pdf = HTML(string=document).write_pdf()
    except Exception as exc:
        raise RenderError(f"report PDF render failed: {exc}") from exc
    if not pdf:
        raise RenderError("report PDF render produced no bytes")
    return RenderedReport(html=body, pdf=pdf)
