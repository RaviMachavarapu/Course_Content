"""T021 — Studio HTML parsers → validated content_json."""

from __future__ import annotations

import pytest

from app.models.enums import ArtifactType
from app.pipeline.fixture import FixtureProvider
from app.pipeline.parsers import ArtifactParseError, parse_artifact
from app.pipeline.parsers.audio_overview import parse_audio_overview
from app.pipeline.parsers.flashcards import parse_flashcards
from app.pipeline.parsers.infographic import parse_infographic
from app.pipeline.parsers.quiz import parse_quiz
from app.pipeline.parsers.report import parse_report
from app.pipeline.parsers.slide_deck import parse_slide_deck

_PROVIDER = FixtureProvider()


def _fixture(kind: ArtifactType) -> tuple[str, dict]:
    nb = _PROVIDER.create_notebook("t")
    raw = _PROVIDER.fetch_content(_PROVIDER.generate(nb, kind, "", {}))
    return raw.html, raw.extras


# -- happy paths (every type) ------------------------------------------------
def test_parse_artifact_dispatch_covers_all_types() -> None:
    for kind in ArtifactType:
        html, extras = _fixture(kind)
        result = parse_artifact(kind, html, extras)
        assert isinstance(result, dict) and result


def test_slide_deck_fixture() -> None:
    html, extras = _fixture(ArtifactType.slide_deck)
    deck = parse_slide_deck(html, extras)
    assert len(deck.slides) == 5
    assert deck.slides[0].title == "What you'll learn"
    assert deck.slides[0].bullets


def test_flashcards_fixture() -> None:
    html, extras = _fixture(ArtifactType.flashcards)
    cards = parse_flashcards(html, extras)
    assert len(cards.cards) == 6
    assert cards.cards[0].category == "Basics"
    assert cards.cards[0].hint


def test_quiz_fixture_resolves_correct_index() -> None:
    html, extras = _fixture(ArtifactType.quiz)
    quiz = parse_quiz(html, extras)
    assert [q.correct_index for q in quiz.questions] == [1, 2, 2]
    assert all(len(q.options) == 4 for q in quiz.questions)


def test_report_fixture_extracts_sections_and_read_time() -> None:
    html, extras = _fixture(ArtifactType.report)
    report = parse_report(html, extras)
    assert report.title.startswith("Neural Networks")
    assert report.read_minutes >= 1
    assert len(report.key_takeaways) == 5
    assert any(s.heading == "Implications" for s in report.sections)


def test_infographic_fixture_builds_mermaid() -> None:
    html, extras = _fixture(ArtifactType.infographic)
    info = parse_infographic(html, extras)
    assert info.diagram_kind == "mermaid"
    assert info.diagram_source.startswith("flowchart TD")
    assert "-->" in info.diagram_source


def test_infographic_falls_back_to_html_without_tree() -> None:
    html, _ = _fixture(ArtifactType.infographic)
    info = parse_infographic(html, {})  # no mind_map_tree
    assert "flowchart TD" in info.diagram_source


def test_audio_overview_fixture_synthesises_cues() -> None:
    html, extras = _fixture(ArtifactType.audio_overview)
    audio = parse_audio_overview(html, extras)
    assert audio.duration_seconds >= 1
    assert len(audio.transcript) >= 3
    assert audio.transcript[0].t == 0.0
    assert audio.transcript[1].t > 0


# -- malformed inputs -----------------------------------------------------
def test_empty_html_raises() -> None:
    with pytest.raises(ArtifactParseError, match="empty"):
        parse_slide_deck("   ", {})


def test_slide_without_title_raises() -> None:
    with pytest.raises(ArtifactParseError, match="title"):
        parse_slide_deck("<section class='slide'><ul><li>x</li></ul></section>", {})


def test_flashcard_missing_back_raises() -> None:
    with pytest.raises(ArtifactParseError, match="front or back"):
        parse_flashcards("<div class='card'><div class='front'>Q</div></div>", {})


def test_quiz_wrong_option_count_raises() -> None:
    bad = "<div class='question'><p class='prompt'>Q</p><ol><li>a</li><li>b</li></ol></div>"
    with pytest.raises(ArtifactParseError, match="exactly 4"):
        parse_quiz(bad, {})


def test_quiz_missing_answer_raises() -> None:
    bad = (
        "<div class='question'><p class='prompt'>Q</p>"
        "<ol class='options'><li>a</li><li>b</li><li>c</li><li>d</li></ol></div>"
    )
    with pytest.raises(ArtifactParseError, match="marked answer"):
        parse_quiz(bad, {})


def test_quiz_no_question_blocks_raises() -> None:
    with pytest.raises(ArtifactParseError, match="no .question blocks"):
        parse_quiz("<div class='studio-artifact'><p>nothing here</p></div>", {})


def test_quiz_answer_falls_back_to_1_based_text_when_no_data_attr() -> None:
    html = (
        "<div class='question'><p class='prompt'>Q</p>"
        "<ol class='options'><li>a</li><li>b</li><li>c</li><li>d</li></ol>"
        "<p class='answer'>Answer: 3</p></div>"
    )
    quiz = parse_quiz(html, {})
    assert quiz.questions[0].correct_index == 2  # 1-based "3" -> 0-based 2


def test_quiz_answer_text_with_no_digit_raises() -> None:
    html = (
        "<div class='question'><p class='prompt'>Q</p>"
        "<ol class='options'><li>a</li><li>b</li><li>c</li><li>d</li></ol>"
        "<p class='answer'>see above</p></div>"
    )
    with pytest.raises(ArtifactParseError, match="could not read the marked answer"):
        parse_quiz(html, {})


def test_quiz_answer_out_of_range_raises() -> None:
    html = (
        "<div class='question'><p class='prompt'>Q</p>"
        "<ol class='options'><li>a</li><li>b</li><li>c</li><li>d</li></ol>"
        "<p class='answer'>Answer: 9</p></div>"
    )
    with pytest.raises(ArtifactParseError, match="out of range"):
        parse_quiz(html, {})


def test_report_without_title_raises() -> None:
    with pytest.raises(ArtifactParseError, match="title"):
        parse_report("<div class='studio-artifact'><p>body</p></div>", {})


def test_infographic_without_nodes_raises() -> None:
    with pytest.raises(ArtifactParseError, match="mind_map_tree"):
        parse_infographic("<div class='studio-artifact'></div>", {})


def test_audio_without_transcript_raises() -> None:
    with pytest.raises(ArtifactParseError, match="transcript"):
        parse_audio_overview("<div class='studio-artifact'></div>", {})
