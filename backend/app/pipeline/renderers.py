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
from dataclasses import dataclass, replace
from typing import Any

from app.logging import get_logger
from app.models.enums import ArtifactType, MediaFileKind
from app.pipeline.provider import ContentProvider, StudioJobRef
from app.render import RenderError, notebook_logo
from app.render.infographic import render_infographic
from app.render.slides_pptx import render_slides

log = get_logger("pipeline.renderers")


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


_LOGO_IMAGE_KINDS = (MediaFileKind.slide_png, MediaFileKind.infographic_png)


def strip_notebook_logo(blobs: list[MediaBlob]) -> list[MediaBlob]:
    """NotebookLM's media with its "Gemini Notebook" mark cropped off (owner decision
    2026-10-29, `app/render/notebook_logo.py`): every slide PNG and the infographic PNG;
    the deck PDF is rebuilt from the cropped slide PNGs (its pages are those images) and
    the PPTX's slide pictures are cropped. An image without the mark, or that can't be
    read, is kept as it is: cropping never fails a generation."""
    out: list[MediaBlob] = []
    cropped = 0
    for blob in blobs:
        if blob.kind in _LOGO_IMAGE_KINDS:
            label = f"{blob.kind.value}.{blob.page_index or 0}"
            try:
                result = notebook_logo.strip_logo(blob.data, label=label)
            except Exception as exc:  # unreadable image: store it as downloaded
                log.warning("notebook_logo.image_unreadable", image=label, error=str(exc))
            else:
                if result.changed:
                    cropped += 1
                    blob = replace(blob, data=result.data, mime="image/png")
        out.append(blob)
    slides = sorted(
        (b for b in out if b.kind is MediaFileKind.slide_png), key=lambda b: b.page_index or 0
    )
    for i, blob in enumerate(out):
        try:
            if blob.kind is MediaFileKind.deck_pdf and cropped and slides:
                data = notebook_logo.rebuild_deck_pdf(
                    blob.data, [s.data for s in slides], label="deck_pdf"
                )
                out[i] = replace(blob, data=data)
            elif blob.kind is MediaFileKind.pptx:
                data, _n = notebook_logo.strip_pptx(blob.data, label="pptx")
                out[i] = replace(blob, data=data)
        except Exception as exc:  # a damaged download: store it as it came
            log.warning("notebook_logo.document_kept", kind=blob.kind.value, error=str(exc))
    return out
