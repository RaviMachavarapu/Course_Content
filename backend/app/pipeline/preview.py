"""Tiny per-type summaries of a `content_json`, for the staging cards."""

from __future__ import annotations

from typing import Any

from app.models.enums import ArtifactType


def content_preview(
    artifact_type: ArtifactType, content_json: dict[str, Any] | None
) -> dict[str, Any]:
    if not content_json:
        return {}
    match artifact_type:
        case ArtifactType.slide_deck:
            return {"slide_count": len(content_json.get("slides", []))}
        case ArtifactType.flashcards:
            return {"card_count": len(content_json.get("cards", []))}
        case ArtifactType.quiz:
            return {"question_count": len(content_json.get("questions", []))}
        case ArtifactType.report:
            return {
                "read_minutes": content_json.get("read_minutes"),
                "section_count": len(content_json.get("sections", [])),
            }
        case ArtifactType.infographic:
            src = content_json.get("diagram_source", "")
            return {
                "diagram_kind": content_json.get("diagram_kind"),
                "line_count": src.count("\n") + 1 if src else 0,
            }
        case ArtifactType.audio_overview:
            return {
                "duration_seconds": content_json.get("duration_seconds"),
                "cue_count": len(content_json.get("transcript", [])),
            }
    return {}
