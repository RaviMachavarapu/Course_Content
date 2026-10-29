"""Per-artifact-type render step of the pipeline.

Given a parsed `content_json` (and the provider job, for binaries), produce the
media files to store. Flashcards, quiz and report are content_json with no
media (D5; the report's HTML is `report_html.build_report_html`); slides
(T018), infographic (T019) and audio have real renderers. Every type's
downloadable PDF except audio is typeset after generation
(app/pipeline/artifact_pdf.py).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.models.enums import ArtifactType, MediaFileKind
from app.pipeline.provider import ContentProvider, StudioJobRef
from app.render import RenderError
from app.render.infographic import render_infographic
from app.render.slides_pptx import render_slides


@dataclass(frozen=True)
class MediaBlob:
    kind: MediaFileKind
    data: bytes
    mime: str
    page_index: int | None = None


Renderer = Callable[[dict[str, Any], ContentProvider, StudioJobRef], list[MediaBlob]]


_PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


def _render_slides(
    content_json: dict[str, Any], _p: ContentProvider, _j: StudioJobRef
) -> list[MediaBlob]:
    rendered = render_slides(content_json)
    blobs = [
        MediaBlob(kind=MediaFileKind.pptx, data=rendered.pptx, mime=_PPTX_MIME),
        MediaBlob(kind=MediaFileKind.deck_pdf, data=rendered.deck_pdf, mime="application/pdf"),
    ]
    blobs.extend(
        MediaBlob(kind=MediaFileKind.slide_png, data=png, mime="image/png", page_index=index)
        for index, png in enumerate(rendered.slide_png)
    )
    return blobs


def _render_audio(
    _content_json: dict[str, Any], provider: ContentProvider, job: StudioJobRef
) -> list[MediaBlob]:
    mp3 = provider.fetch_binary(job, ArtifactType.audio_overview)
    if not mp3:
        raise RenderError("audio overview: provider returned no .mp3 (see Open Item O2)")
    return [MediaBlob(kind=MediaFileKind.audio_mp3, data=mp3, mime="audio/mpeg")]


def _render_infographic(
    content_json: dict[str, Any], _p: ContentProvider, _j: StudioJobRef
) -> list[MediaBlob]:
    rendered = render_infographic(content_json)
    return [
        MediaBlob(kind=MediaFileKind.infographic_svg, data=rendered.svg, mime="image/svg+xml"),
        MediaBlob(kind=MediaFileKind.infographic_png, data=rendered.png, mime="image/png"),
    ]


def _no_media(*_: object) -> list[MediaBlob]:
    return []


RENDERERS: dict[ArtifactType, Renderer] = {
    ArtifactType.slide_deck: _render_slides,
    ArtifactType.flashcards: _no_media,
    ArtifactType.quiz: _no_media,
    ArtifactType.report: _no_media,
    ArtifactType.infographic: _render_infographic,
    ArtifactType.audio_overview: _render_audio,
}
