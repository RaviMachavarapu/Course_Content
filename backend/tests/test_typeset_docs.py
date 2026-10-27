"""Artifact content_json → Quarto Markdown for the typeset service
(app/render/typeset_docs.py).

The Markdown is read by pandoc with raw TeX/HTML disabled: formulas must reach
it verbatim between dollars, everything else must print literally.
"""

from __future__ import annotations

import io
import json
import os
import re
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from app.models.enums import ArtifactType, MediaFileKind
from app.pipeline.parsers.notebooklm import parse_notebooklm
from app.render import typeset_docs
from app.render.typeset_docs import (
    PDF_KINDS,
    StoredImage,
    build_document,
    build_flashcards,
    build_infographic,
    build_quiz,
    build_report,
    build_slide_deck,
    html_to_markdown,
    text_to_markdown,
)

FIXTURES = Path(__file__).parent / "fixtures" / "notebooklm"


def _png(color: str = "red", size: tuple[int, int] = (4, 3)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


# -- plain text fields (MathText's dollar rule) ---------------------------------
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("What does $S_N2$ stand for?", "What does $S_N2$ stand for\\?"),
        # a stray dollar never opens a formula
        ("Costs $5 at 100% & more", "Costs \\$5 at 100\\% \\& more"),
        # `\$` is a literal dollar on the web
        ("price \\$5 and $x$", "price \\$5 and $x$"),
        ("Energy: $$E = mc^2$$", "Energy\\: $$E = mc^2$$"),
        (
            "CH_3_Br *as* `code` #1 [a] <b> |c| ~d^ @e",
            ("CH\\_3\\_Br \\*as\\* \\`code\\` \\#1 \\[a\\] \\<b\\> \\|c\\| \\~d\\^ \\@e"),
        ),
        (
            "1. not a list\n- nor this\n+ nor this",
            ("1\\. not a list\\\n\\- nor this\\\n\\+ nor this"),
        ),
        ("para one\n\n\n  para two  ", "para one\n\npara two"),
        ("C:\\path {x}", "C\\:\\\\path \\{x\\}"),
        ("20 µL → 5 ≤ 6", "20 µL → 5 ≤ 6"),
        # the web's dollar rule: a `$` before a digit doesn't close a formula
        ("an $S_N$2 reaction", "an \\$S\\_N\\$2 reaction"),
        ("Unit $\\text{H}_2$-rich", "Unit $\\text{H}_2$\\-rich"),
        ("    indented", "indented"),
    ],
)
def test_text_to_markdown(text: str, expected: str) -> None:
    assert text_to_markdown(text) == expected


def test_text_formula_with_blank_line_stays_one_formula() -> None:
    assert text_to_markdown("$$a\n\n  b$$") == "$$a\nb$$"


# -- report section HTML ---------------------------------------------------------
@pytest.mark.parametrize(
    ("html", "expected"),
    [
        (
            '<p>The <strong>rate</strong> of an <span class="math-inline">S_N2</span> '
            "reaction is 50% faster &amp; uses CH_3_Br *as* written. Costs $5 at 20 µL.</p>",
            "The **rate** of an $S_N2$ reaction is 50\\% faster \\& uses CH\\_3\\_Br "
            "\\*as\\* written\\. Costs \\$5 at 20 µL\\.",
        ),
        (
            '<div class="math-display">\\frac{d[A]}{dt} = -k[A][B]</div>',
            "$$\\frac{d[A]}{dt} = -k[A][B]$$",
        ),
        ('<p><span class="math-inline">x &lt; y &amp; z</span></p>', "$x < y & z$"),
        ("<p>1. Not a list</p>", "1\\. Not a list"),
        (
            '<ul><li>first <em>point</em></li><li>second <span class="math-inline">'
            "x</span></li></ul>",
            "-   first *point*\n-   second $x$",
        ),
        ("<ol><li>one</li><li>two</li></ol>", "1.  one\n2.  two"),
        (
            "<ul><li><p>a</p><ul><li>b</li></ul></li><li>c</li></ul>",
            "-   a\n\n    -   b\n\n-   c",
        ),
        ("<p>line one<br>line two<br></p>", "line one\\\nline two"),
        ("<h3>Sub <em>head</em></h3><p>x</p>", "## Sub *head*\n\nx"),
        ("<h4>Minor</h4>", "### Minor"),
        ("<blockquote><p>quoted</p><p>more</p></blockquote>", "> quoted\n>\n> more"),
        ("<pre><code>code `x`\n  y</code></pre>", "```\ncode `x`\n  y\n```"),
        ("<p>H<sub>2</sub>O and x<sup>a b</sup></p>", "H~2~O and x^a\\ b^"),
        ("<p>a <code>x_y</code> b</p>", "a `x_y` b"),
        (
            '<p><a href="https://example.com/a b(c)">the link</a></p>',
            "[the link](https://example.com/a%20b%28c%29)",
        ),
        ("<p><b>bold </b>next</p>", "**bold** next"),
        ("<p><strong></strong>x</p>", "x"),
        ("<hr>", "* * *"),
        (
            "<table><thead><tr><th>Ion</th><th>Charge</th></tr></thead><tbody><tr>"
            '<td><span class="math-inline">|q|</span></td><td>a | b</td></tr></tbody></table>',
            "| Ion | Charge |\n|---|---|\n| $|q|$ | a \\| b |",
        ),
        (
            "<table><tr><td>1</td><td>2</td></tr></table>",
            "|  |  |\n|---|---|\n| 1 | 2 |",
        ),
        ("loose text <i>here</i>", "loose text *here*"),
        # whitespace around a formula is not part of it
        ('<p><span class="math-inline"> x </span></p>', "$x$"),
        # what pandoc can't hold between dollars is shown as its source
        ('<p><span class="math-inline">a$b</span></p>', "`a$b`"),
        ('<p><span class="math-inline">a\\ </span></p>', "`a\\`"),
        # a blank line inside a formula would end pandoc's paragraph
        ('<div class="math-display">a\n\n b</div>', "$$a\nb$$"),
        ('<p><span class="math-inline">S_N</span>2</p>', "$S_N$[]{}2"),
    ],
)
def test_html_to_markdown(html: str, expected: str) -> None:
    assert html_to_markdown(html) == expected


# -- report ------------------------------------------------------------------------
REPORT: dict[str, Any] = {
    "title": "Nucleophilic Substitution: $S_N2$ & More",
    "read_minutes": 7,
    "key_takeaways": [
        "$S_N2$ is one step; costs $5 at 100%",
        "Rate = $k[\\text{RX}][\\text{Nu}^-]$",
    ],
    "sections": [
        {
            "heading": "1. Mechanism #1 of $S_N2$",
            "html": (
                '<p>The <strong>rate</strong> of an <span class="math-inline">S_N2</span> '
                "reaction is 50% faster &amp; uses CH_3_Br *as* is. Costs $5 at 20 µL.</p>"
                '<div class="math-display">\\frac{d[A]}{dt} = -k[A][B]</div>'
                "<p>1. Not a list</p>"
                '<ul><li>first <em>point</em></li><li>second <span class="math-inline">'
                "x &lt; y</span></li></ul>"
            ),
        },
        {
            "heading": "Table",
            "html": (
                "<table><thead><tr><th>Ion</th><th>Charge</th></tr></thead><tbody><tr>"
                '<td><span class="math-inline">|q|</span></td><td>a | b</td></tr></tbody>'
                "</table><h3>Sub</h3><p>line one<br>line two</p><ol><li>one</li><li>two</li>"
                "</ol><blockquote><p>quoted</p></blockquote><pre><code>code `x`</code></pre>"
            ),
        },
    ],
}

REPORT_MD = r"""*About 7 min read*

# Key takeaways

-   $S_N2$ is one step\; costs \$5 at 100\%
-   Rate \= $k[\text{RX}][\text{Nu}^-]$

# 1\. Mechanism \#1 of $S_N2$

The **rate** of an $S_N2$ reaction is 50\% faster \& uses CH\_3\_Br \*as\* is\. Costs \$5 at 20 µL\.

$$\frac{d[A]}{dt} = -k[A][B]$$

1\. Not a list

-   first *point*
-   second $x < y$

# Table

| Ion | Charge |
|---|---|
| $|q|$ | a \| b |

## Sub

line one\
line two

1.  one
2.  two

> quoted

```
code `x`
```
"""


def test_report_markdown() -> None:
    doc = build_report(REPORT, [])
    assert doc.markdown == REPORT_MD
    # the service treats the title as plain text
    assert doc.title == "Nucleophilic Substitution: $S_N2$ & More"
    assert doc.images == {}


def test_report_without_takeaways() -> None:
    content = {**REPORT, "key_takeaways": [], "read_minutes": 1}
    md = build_report(content, []).markdown
    assert md.startswith("*About 1 min read*\n\n# 1\\. Mechanism")
    assert "Key takeaways" not in md


# -- flashcards ----------------------------------------------------------------------
FLASHCARDS: dict[str, Any] = {
    "cards": [
        {
            "front": "What does $S_N2$ stand for?",
            "back": "Substitution, nucleophilic, bimolecular.\nRate = $k[RX][Nu]$",
            "category": "Mechanisms",
            "hint": "not printed",
        },
        {"front": "Energy: $$E = mc^2$$", "back": "Costs $5 & 10% _off_ #1"},
    ]
}

FLASHCARDS_MD = r"""## Card 1

**Category:** Mechanisms

**Front:** What does $S_N2$ stand for\?

**Back:** Substitution\, nucleophilic\, bimolecular\.\
Rate \= $k[RX][Nu]$

## Card 2

**Front:** Energy\: $$E = mc^2$$

**Back:** Costs \$5 \& 10\% \_off\_ \#1
"""


def test_flashcards_markdown() -> None:
    doc = build_flashcards(FLASHCARDS, [])
    assert doc.markdown == FLASHCARDS_MD
    assert doc.title == "Flashcards"
    assert doc.images == {}
    assert build_flashcards(FLASHCARDS, [], title="Module 3").title == "Module 3"


# -- quiz ----------------------------------------------------------------------------
QUIZ: dict[str, Any] = {
    "questions": [
        {
            "question": "Which is the rate law for $S_N2$?",
            "options": ["$k[RX]$", "$k[RX][Nu]$", "$k$", "None — costs $5"],
            "correct_index": 1,
            "explanation": "Bimolecular: both appear.",
            "hint": "two",
        },
        {
            "question": "Pick 1.",
            "options": ["a_b", "c*d", "e#f", "g%h"],
            "correct_index": 3,
            "explanation": "",
        },
    ]
}

QUIZ_MD = r"""# Questions

## Question 1

Which is the rate law for $S_N2$\?

A.  $k[RX]$
B.  $k[RX][Nu]$
C.  $k$
D.  None — costs \$5

## Question 2

Pick 1\.

A.  a\_b
B.  c\*d
C.  e\#f
D.  g\%h

# Answer key

**1. B:** $k[RX][Nu]$

Bimolecular\: both appear\.

**2. D:** g\%h
"""


def test_quiz_markdown() -> None:
    doc = build_quiz(QUIZ, [])
    assert doc.markdown == QUIZ_MD
    assert doc.title == "Quiz"


# -- infographic -----------------------------------------------------------------------
INFOGRAPHIC: dict[str, Any] = {
    "caption": "Rates of $S_N1$ vs $S_N2$",
    "description": "Line 1: 50% & more\n\nPara 2",
}


def test_infographic_markdown_with_image() -> None:
    png = _png()
    media = [
        StoredImage(MediaFileKind.infographic_svg, None, b"<svg/>"),
        StoredImage(MediaFileKind.infographic_png, None, png),
    ]
    doc = build_infographic(INFOGRAPHIC, media)
    assert doc.markdown == (
        "![](infographic.png)\n\nRates of $S_N1$ vs $S_N2$\n\nLine 1\\: 50\\% \\& more\n\nPara 2\n"
    )
    assert doc.images == {"infographic.png": png}
    assert doc.title == "Infographic"


def test_infographic_without_png_omits_the_image() -> None:
    doc = build_infographic({"caption": "Only text", "description": None}, [])
    assert doc.markdown == "Only text\n"
    assert doc.images == {}


def test_infographic_jpeg_keeps_jpeg_name() -> None:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), "blue").save(buf, "JPEG")
    doc = build_infographic(
        INFOGRAPHIC, [StoredImage(MediaFileKind.infographic_png, None, buf.getvalue())]
    )
    assert list(doc.images) == ["infographic.jpg"]
    assert doc.markdown.startswith("![](infographic.jpg)\n\n")


def test_other_image_formats_are_converted_to_png() -> None:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), "blue").save(buf, "WEBP")
    doc = build_infographic(
        INFOGRAPHIC, [StoredImage(MediaFileKind.infographic_png, None, buf.getvalue())]
    )
    assert doc.images["infographic.png"].startswith(b"\x89PNG")


def test_unreadable_image_is_omitted() -> None:
    doc = build_infographic(
        INFOGRAPHIC, [StoredImage(MediaFileKind.infographic_png, None, b"not an image")]
    )
    assert doc.images == {}
    assert "![](" not in doc.markdown


# -- slide deck ---------------------------------------------------------------------------
SLIDES: dict[str, Any] = {
    "slides": [
        {"title": "Intro", "bullets": [], "notes": "Welcome to $S_N2$.\nCosts $5."},
        {"title": "Two", "bullets": [], "notes": ""},
        {"title": "Three", "bullets": [], "notes": "Only notes"},
    ]
}


def test_slide_deck_markdown() -> None:
    first, second = _png("red"), _png("green")
    media = [
        StoredImage(MediaFileKind.slide_png, 1, second),
        StoredImage(MediaFileKind.deck_pdf, None, b"%PDF-1.7"),
        StoredImage(MediaFileKind.slide_png, 0, first),
    ]
    doc = build_slide_deck(SLIDES, media)
    assert doc.markdown == (
        "## Slide 1\n\n![](slide-001.png)\n\nWelcome to $S_N2$\\.\\\nCosts \\$5\\.\n\n"
        "## Slide 2\n\n![](slide-002.png)\n\n"
        "## Slide 3\n\nOnly notes\n"
    )
    assert doc.images == {"slide-001.png": first, "slide-002.png": second}
    assert doc.title == "Slides"


def test_large_images_are_recompressed_to_fit_the_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(typeset_docs, "IMAGE_BUDGET_BYTES", 10)
    media = [StoredImage(MediaFileKind.slide_png, i, _png(size=(3000, 2000))) for i in range(2)]
    doc = build_slide_deck(SLIDES, media)
    assert sorted(doc.images) == ["slide-001.jpg", "slide-002.jpg"]
    for data in doc.images.values():
        assert data.startswith(b"\xff\xd8\xff")
        assert max(Image.open(io.BytesIO(data)).size) <= typeset_docs.MAX_IMAGE_SIDE
    assert "![](slide-001.jpg)" in doc.markdown


# -- dispatch -------------------------------------------------------------------------------
def test_pdf_kinds_and_dispatch() -> None:
    expected = {
        ArtifactType.report: MediaFileKind.report_pdf,
        ArtifactType.flashcards: MediaFileKind.flashcards_pdf,
        ArtifactType.quiz: MediaFileKind.quiz_pdf,
        ArtifactType.infographic: MediaFileKind.infographic_pdf,
        ArtifactType.slide_deck: MediaFileKind.slides_handout_pdf,
    }
    assert expected == PDF_KINDS
    assert build_document(ArtifactType.quiz, QUIZ, []).markdown == QUIZ_MD
    assert build_document(ArtifactType.quiz, QUIZ, [], title="T").title == "T"
    with pytest.raises(ValueError):
        build_document(ArtifactType.audio_overview, {}, [])


# -- exactness: every formula reaches pandoc verbatim between dollars ----------------------
def _formulas(md: str) -> list[str]:
    return re.findall(r"\$\$(.+?)\$\$|\$([^$]+?)\$", md, re.S)


@pytest.mark.parametrize(
    ("builder", "content", "latex"),
    [
        (
            build_report,
            REPORT,
            [
                "S_N2",
                "k[\\text{RX}][\\text{Nu}^-]",
                "\\frac{d[A]}{dt} = -k[A][B]",
                "x < y",
                "|q|",
            ],
        ),
        (build_flashcards, FLASHCARDS, ["S_N2", "k[RX][Nu]", "E = mc^2"]),
        (build_quiz, QUIZ, ["S_N2", "k[RX]", "k[RX][Nu]", "k"]),
        (build_infographic, INFOGRAPHIC, ["S_N1", "S_N2"]),
        (build_slide_deck, SLIDES, ["S_N2"]),
    ],
)
def test_every_formula_is_verbatim(builder: Any, content: dict[str, Any], latex: list[str]) -> None:
    md = builder(content, []).markdown
    found = {a or b for a, b in _formulas(md.replace("\\$", ""))}
    assert set(latex) <= found
    assert found <= set(latex)


def test_recorded_notebooklm_report_formulas_are_verbatim() -> None:
    row = json.loads((FIXTURES / "report_interactive.json").read_text())
    content = parse_notebooklm(ArtifactType.report, row, None).content
    md = build_report(content, []).markdown
    from bs4 import BeautifulSoup

    for section in content["sections"]:
        soup = BeautifulSoup(section["html"], "html.parser")
        for el in soup.select(".math-inline, .math-display"):
            latex = el.get_text().strip()
            fence = "$$" if "math-display" in el["class"] else "$"
            assert f"{fence}{latex}{fence}" in md


# -- live service (opt-in) -------------------------------------------------------------------
@pytest.mark.skipif(not os.environ.get("TYPESET_URL"), reason="set TYPESET_URL to run")
@pytest.mark.parametrize(
    ("artifact_type", "content", "media"),
    [
        (ArtifactType.report, REPORT, []),
        (ArtifactType.flashcards, FLASHCARDS, []),
        (ArtifactType.quiz, QUIZ, []),
        (
            ArtifactType.infographic,
            INFOGRAPHIC,
            [StoredImage(MediaFileKind.infographic_png, None, _png(size=(40, 30)))],
        ),
        (
            ArtifactType.slide_deck,
            SLIDES,
            [StoredImage(MediaFileKind.slide_png, 0, _png(size=(40, 30)))],
        ),
    ],
)
def test_live_typeset_builds_without_fallback(
    artifact_type: ArtifactType,
    content: dict[str, Any],
    media: list[StoredImage],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import get_settings
    from app.render.typeset_client import render_pdf

    monkeypatch.setenv("TYPESET_ENDPOINT", os.environ["TYPESET_URL"])
    get_settings.cache_clear()
    try:
        doc = build_document(artifact_type, content, media)
        result = render_pdf(doc.markdown, doc.title, doc.images)
    finally:
        get_settings.cache_clear()
    assert result.pdf.startswith(b"%PDF-")
    assert result.fallback == "0"
