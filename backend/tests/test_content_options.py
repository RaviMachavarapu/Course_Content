"""Per-type generation options (validated against notebooklm-mcp-server's
documented tool parameters — see app/schemas/content_options.py)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.enums import ArtifactType
from app.schemas.content_options import default_options, validate_options


@pytest.mark.parametrize(
    ("artifact_type", "expected"),
    [
        (ArtifactType.slide_deck, {"language": "en"}),
        (ArtifactType.report, {"language": "en"}),
        (ArtifactType.flashcards, {"quantity": "standard", "difficulty": "medium"}),
        (ArtifactType.quiz, {"quantity": "standard", "difficulty": "medium"}),
        (
            ArtifactType.audio_overview,
            {"format": "deep_dive", "length": "default", "language": "en"},
        ),
        (ArtifactType.infographic, {"orientation": "landscape", "language": "en"}),
    ],
)
def test_default_options_match_notebooklm_documented_defaults(
    artifact_type: ArtifactType, expected: dict[str, str]
) -> None:
    assert default_options(artifact_type) == expected


def test_validate_options_fills_in_missing_fields() -> None:
    assert validate_options(ArtifactType.quiz, {"difficulty": "hard"}) == {
        "quantity": "standard",
        "difficulty": "hard",
    }


def test_validate_options_rejects_an_unknown_enum_value() -> None:
    with pytest.raises(ValidationError):
        validate_options(ArtifactType.flashcards, {"quantity": "a-lot"})


def test_validate_options_ignores_fields_the_type_does_not_support() -> None:
    # slide_deck has no "orientation" field — extra keys are simply dropped,
    # not an error (pydantic's default "ignore" extra policy).
    assert validate_options(ArtifactType.slide_deck, {"orientation": "portrait"}) == {
        "language": "en"
    }
