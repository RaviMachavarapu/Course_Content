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
    assert '<span class="math-inline">2^4</span>' in body  # formula run
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


# -- formulas -------------------------------------------------------------------
def _run_report(run: list[Any]) -> str:
    return _blocks_report([run])


def _blocks_report(runs: list[list[Any]]) -> str:
    from app.pipeline.parsers import notebooklm as nb

    return "".join(
        s["html"] for s in nb._sections_from_blocks([[None, None, [runs, [None, None]]]])
    )


def _fmt(bold: Any = None, italic: Any = None, slot9: Any = None) -> list[Any]:
    f: list[Any] = [None] * 10
    f[0], f[1], f[9] = bold, italic, slot9
    return f


def test_interactive_inline_formula_becomes_math_span() -> None:
    out = _run_report([0, 4, ["S_N2", [None] * 9 + [1]]])
    assert '<span class="math-inline">S_N2</span>' in out
    assert "<code>" not in out


def test_interactive_bold_formula() -> None:
    out = _run_report([0, 4, ["S_N2", _fmt(bold=True, slot9=1)]])
    assert "<strong>" in out and '<span class="math-inline">S_N2</span>' in out
    assert "<code>" not in out


def test_interactive_display_formula_becomes_math_div() -> None:
    out = _run_report([0, 4, ["\\text{R-MgX} + \\text{H}_2\\text{O}", _fmt(slot9=2)]])
    assert '<div class="math-display">\\text{R-MgX} + \\text{H}_2\\text{O}</div>' in out


def test_formula_text_is_escaped() -> None:
    out = _run_report([0, 3, ["a<b", _fmt(slot9=1)]])
    assert '<span class="math-inline">a&lt;b</span>' in out
    out = _run_report([0, 3, ["<script>x</script>", _fmt(slot9=1)]])
    assert "<script>" not in out


def _doc_html(markdown: str) -> str:
    from app.pipeline.parsers import notebooklm as nb

    _, sections = nb._sections_from_markdown(markdown)
    return "".join(s["html"] for s in sections)


def test_markdown_math_survives_markdown_rendering() -> None:
    out = _doc_html("## S\nRate $k_1 * [A]_0$ and $$\\alpha_2$$ cost \\$5")
    assert '<span class="math-inline">k_1 * [A]_0</span>' in out
    assert '<div class="math-display">\\alpha_2</div>' in out
    assert "$5" in out
    assert "<em>" not in out


def test_markdown_dollar_amounts_stay_text() -> None:
    out = _doc_html("## S\nIt costs $5 and $10 today")
    assert "math-" not in out and "$5 and $10" in out


def test_markdown_math_is_escaped() -> None:
    out = _doc_html("## S\nx $<img src=x onerror=alert(1)>$ y")
    assert "<img" not in out and "&lt;img" in out


def test_real_code_stays_code() -> None:
    out = _doc_html("## S\nCall `print(x)` now and `$a$` too")
    assert "<code>print(x)</code>" in out
    assert "<code>$a$</code>" in out
