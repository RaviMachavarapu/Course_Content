"""Per-type generation options — the controls NotebookLM's Studio dialogs
offer, with their defaults and combinations, as recorded live on 2026-10-22
(see app/schemas/content_options.py)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.enums import ArtifactType
from app.schemas.content_options import default_options, validate_options


@pytest.mark.parametrize(
    ("artifact_type", "expected"),
    [
        (
            ArtifactType.slide_deck,
            {"format": "detailed", "length": "default", "language": "en", "review_outline": False},
        ),
        (ArtifactType.report, {"format": "interactive", "template": None, "language": "en"}),
        (
            ArtifactType.flashcards,
            {"quantity": "standard", "difficulty": "medium", "images": "include", "language": "en"},
        ),
        (ArtifactType.quiz, {"quantity": "standard", "difficulty": "medium", "language": "en"}),
        (
            ArtifactType.audio_overview,
            {"format": "deep_dive", "length": "default", "language": "en"},
        ),
        (
            ArtifactType.infographic,
            {"language": "en", "orientation": "landscape", "detail": "standard", "style": "auto"},
        ),
    ],
)
def test_defaults_match_notebooklm(
    artifact_type: ArtifactType, expected: dict[str, object]
) -> None:
    assert default_options(artifact_type) == expected


def test_missing_fields_are_filled_with_defaults() -> None:
    assert validate_options(ArtifactType.quiz, {"difficulty": "hard"}) == {
        "quantity": "standard",
        "difficulty": "hard",
        "language": "en",
    }


def test_fields_a_type_does_not_have_are_dropped() -> None:
    assert validate_options(ArtifactType.slide_deck, {"orientation": "portrait"}) == (
        default_options(ArtifactType.slide_deck)
    )


def test_an_unknown_value_is_rejected() -> None:
    with pytest.raises(ValidationError):
        validate_options(ArtifactType.flashcards, {"quantity": "a-lot"})


@pytest.mark.parametrize("code", ["en", "hi", "te", "ta", "kn", "mr"])
def test_language_accepts_the_owner_approved_codes(code: str) -> None:
    assert validate_options(ArtifactType.quiz, {"language": code})["language"] == code


def test_language_rejects_codes_outside_the_approved_list() -> None:
    with pytest.raises(ValidationError):
        validate_options(ArtifactType.audio_overview, {"language": "es"})


# -- audio: length depends on format ------------------------------------------
def test_deep_dive_offers_long() -> None:
    assert validate_options(ArtifactType.audio_overview, {"length": "long"})["length"] == "long"


@pytest.mark.parametrize("fmt", ["critique", "debate"])
def test_critique_and_debate_do_not_offer_long(fmt: str) -> None:
    with pytest.raises(ValidationError, match="not offered"):
        validate_options(ArtifactType.audio_overview, {"format": fmt, "length": "long"})


def test_brief_has_no_length_control() -> None:
    opts = validate_options(ArtifactType.audio_overview, {"format": "brief", "length": "short"})
    assert opts["length"] == "default"


# -- report: format, template, language ------------------------------------
def test_a_document_report_needs_a_template() -> None:
    with pytest.raises(ValidationError, match="needs a template"):
        validate_options(ArtifactType.report, {"format": "document"})


def test_an_interactive_report_drops_any_template() -> None:
    opts = validate_options(ArtifactType.report, {"template": "blog_post"})
    assert opts == {"format": "interactive", "template": None, "language": "en"}


def test_report_language_is_only_choosable_for_a_custom_report() -> None:
    custom = {"format": "document", "template": "custom", "language": "hi"}
    assert validate_options(ArtifactType.report, custom)["language"] == "hi"
    with pytest.raises(ValidationError, match="custom"):
        validate_options(
            ArtifactType.report, {"format": "document", "template": "study_guide", "language": "hi"}
        )


@pytest.mark.parametrize("style", ["auto", "kawaii", "scientific", "bento_grid"])
def test_infographic_visual_styles(style: str) -> None:
    assert validate_options(ArtifactType.infographic, {"style": style})["style"] == style
