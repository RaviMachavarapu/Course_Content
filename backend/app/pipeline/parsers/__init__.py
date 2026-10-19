"""NotebookLM Studio HTML → validated `content_json`.

One parser per artifact type. Every parser is defensive: on markup it can't make
sense of it raises `ArtifactParseError` with a message an admin can act on
(the artifact then lands in `error` and review is the backstop).
"""

from __future__ import annotations

from app.models.enums import ArtifactType
from app.pipeline.parsers.audio_overview import parse_audio_overview
from app.pipeline.parsers.base import ArtifactParseError
from app.pipeline.parsers.flashcards import parse_flashcards
from app.pipeline.parsers.infographic import parse_infographic
from app.pipeline.parsers.quiz import parse_quiz
from app.pipeline.parsers.report import parse_report
from app.pipeline.parsers.slide_deck import parse_slide_deck

_PARSERS = {
    ArtifactType.slide_deck: parse_slide_deck,
    ArtifactType.flashcards: parse_flashcards,
    ArtifactType.quiz: parse_quiz,
    ArtifactType.report: parse_report,
    ArtifactType.infographic: parse_infographic,
    ArtifactType.audio_overview: parse_audio_overview,
}


def parse_artifact(
    kind: ArtifactType, html: str, extras: dict[str, object] | None = None
) -> dict[str, object]:
    """Parse raw Studio HTML for `kind` and return the validated `content_json`
    (a plain dict, ready for `artifact_version.content_json`)."""
    parser = _PARSERS[kind]
    model = parser(html, extras or {})
    return model.model_dump(mode="json")


__all__ = [
    "ArtifactParseError",
    "parse_artifact",
    "parse_audio_overview",
    "parse_flashcards",
    "parse_infographic",
    "parse_quiz",
    "parse_report",
    "parse_slide_deck",
]
