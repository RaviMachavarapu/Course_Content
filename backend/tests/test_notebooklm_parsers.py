"""NotebookLM artifact data → content_json + media (app/pipeline/parsers/notebooklm.py).

Fixtures in tests/fixtures/notebooklm/ are trimmed copies of real NotebookLM
responses recorded on 2026-10-22 (fewer items; URLs and ids replaced).
"""

from __future__ import annotations

import html
import json
import struct
from pathlib import Path
from typing import Any

import pytest

from app.models.enums import ArtifactType, MediaFileKind
from app.pipeline.media_probe import mp4_duration_seconds
from app.pipeline.parsers.base import ArtifactParseError
from app.pipeline.parsers.notebooklm import audio_url, parse_notebooklm, parse_outline

FIXTURES = Path(__file__).parent / "fixtures" / "notebooklm"


def _row(name: str) -> list[Any]:
    data: list[Any] = json.loads((FIXTURES / name).read_text())
    return data


def _html(name: str) -> str:
    return (FIXTURES / name).read_text()


def _page(app_data: dict[str, Any]) -> str:
    return f'<div data-app-data="{html.escape(json.dumps(app_data), quote=True)}"></div>'


def test_slide_deck_keeps_notebooklm_images_pdf_and_pptx() -> None:
    parsed = parse_notebooklm(ArtifactType.slide_deck, _row("slide_deck.json"), None)
    slides = parsed.content["slides"]
    assert len(slides) == 2
    assert slides[0]["title"] == "THE BLUEPRINT OF THOUGHT"
    assert slides[0]["notes"].startswith("THE BLUEPRINT OF THOUGHT")
    kinds = [(m.kind, m.page_index) for m in parsed.media]
    assert kinds == [
        (MediaFileKind.slide_png, 0),
        (MediaFileKind.slide_png, 1),
        (MediaFileKind.deck_pdf, None),
        (MediaFileKind.pptx, None),
    ]


def test_infographic_is_notebooklms_image_with_its_text() -> None:
    parsed = parse_notebooklm(ArtifactType.infographic, _row("infographic.json"), None)
    assert parsed.content["caption"].startswith("An infographic outlining")
    assert parsed.content["description"].startswith("DEMYSTIFYING AI")
    assert parsed.content["diagram_kind"] is None
    assert [m.kind for m in parsed.media] == [MediaFileKind.infographic_png]


def test_interactive_report_becomes_sections_with_formatting() -> None:
    parsed = parse_notebooklm(ArtifactType.report, _row("report_interactive.json"), None)
    content = parsed.content
    assert content["title"].startswith("Introduction to Artificial Intelligence")
    headings = [s["heading"] for s in content["sections"]]
    assert headings[:2] == [
        "Introduction",
        "What is Artificial Intelligence? Models, Representations, and Methods",
    ]
    body = "".join(s["html"] for s in content["sections"])
    assert "<strong>Define</strong>" in body  # bold run
    assert "<em>6.034</em>" in body  # italic run
    assert "<code>2^4</code>" in body  # code run
    assert "<h3>The Power of Representation</h3>" in body  # [null,6] subheading
    assert "<ul><li>" in body  # bullet list
    assert "<blockquote>" in body  # [null,null,true] highlighted statement
    assert parsed.media == []  # the PDF is rendered by us


def test_document_report_markdown_becomes_sections() -> None:
    parsed = parse_notebooklm(ArtifactType.report, _row("report_document.json"), None)
    content = parsed.content
    assert content["title"].startswith("Briefing Document")
    assert content["sections"][0]["heading"] == "Executive Summary"
    assert "<strong>" in content["sections"][0]["html"]
    assert content["read_minutes"] >= 1


def test_flashcards_from_the_pages_app_data() -> None:
    parsed = parse_notebooklm(ArtifactType.flashcards, None, _html("flashcards.html"))
    cards = parsed.content["cards"]
    assert len(cards) == 3
    assert cards[0]["front"] and cards[0]["back"]


def test_an_image_flashcard_block_is_reported_not_dropped() -> None:
    side = {"flashcardContentBlock": [{"type": "image"}]}
    page = _page({"flashcards": [{"f": side, "b": {"flashcardContentBlock": []}, "c": 1}]})
    with pytest.raises(ArtifactParseError, match="doesn't support yet"):
        parse_notebooklm(ArtifactType.flashcards, None, page)


def test_quiz_maps_the_correct_option_its_rationale_and_hint() -> None:
    parsed = parse_notebooklm(ArtifactType.quiz, None, _html("quiz.html"))
    q = parsed.content["questions"][0]
    assert len(q["options"]) == 4
    assert 0 <= q["correct_index"] <= 3
    assert q["explanation"]
    assert q["hint"]


def test_a_quiz_question_without_exactly_four_options_is_rejected() -> None:
    page = _page({"quiz": [{"question": "Q", "answerOptions": [{"text": "a", "isCorrect": True}]}]})
    with pytest.raises(ArtifactParseError, match="exactly 4"):
        parse_notebooklm(ArtifactType.quiz, None, page)


def test_outline_lists_the_style_and_one_line_per_slide() -> None:
    row: list[Any] = [None] * 31
    row[30] = [
        [
            ["This slide deck employs a 'Technical Blueprint' aesthetic."],
            ["**Introduction to Artificial Intelligence**: This title slide introduces it."],
            ["**Beyond 'Thinking'**: This slide redefines intelligence."],
        ]
    ]
    outline = parse_outline(row)
    assert outline["style"].startswith("This slide deck employs")
    assert len(outline["slides"]) == 2


def test_audio_url_picks_the_aac_download() -> None:
    row: list[Any] = [None] * 7
    row[6] = [
        None,
        ["focus", 1],
        "https://lh3.googleusercontent.com/x=mm,hls",
        "https://lh3.googleusercontent.com/x=mm,140",
    ]
    assert audio_url(row) == "https://lh3.googleusercontent.com/x=mm,140"


def _mp4(timescale: int, duration: int) -> bytes:
    # version 0 mvhd: version+flags, creation, modification, timescale, duration, …
    mvhd_body = bytes(4) + bytes(8) + struct.pack(">II", timescale, duration) + bytes(80)
    mvhd = struct.pack(">I4s", 8 + len(mvhd_body), b"mvhd") + mvhd_body
    moov = struct.pack(">I4s", 8 + len(mvhd), b"moov") + mvhd
    ftyp = struct.pack(">I4s", 16, b"ftyp") + b"M4A \x00\x00\x00\x00"
    return ftyp + moov


def test_mp4_duration_is_read_from_mvhd() -> None:
    assert mp4_duration_seconds(_mp4(44100, 44100 * 359)) == pytest.approx(359.0)
    assert mp4_duration_seconds(b"not an mp4") is None
