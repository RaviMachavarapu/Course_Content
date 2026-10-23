"""NotebookLM Studio artifact data (the web app's current format) → validated
`content_json` plus the media files to download.

Every layout here was recorded live on 2026-10-22
(docs/spikes/notebooklm-2026-10-capture.md). `row` is the artifact row the MCP
shim returns from `artifact_content_get` (`raw[0]`); flashcards and quiz also
come with `html`, whose `data-app-data` attribute carries their JSON. Anything
that doesn't match what was recorded raises `ArtifactParseError` rather than
being guessed at.
"""

from __future__ import annotations

import html as html_lib
import json
import re
from dataclasses import dataclass, field
from typing import Any

from markdown_it import MarkdownIt

from app.models.enums import ArtifactType, MediaFileKind
from app.pipeline.parsers._sanitize import sanitize_html
from app.pipeline.parsers.base import ArtifactParseError, validate
from app.schemas.content import (
    FlashcardsContent,
    InfographicContent,
    QuizContent,
    ReportContent,
    SlideDeckContent,
)

_WORDS_PER_MINUTE = 200

# NotebookLM's artifact type codes, per the captured rows.
_TYPE_REPORT_DOCUMENT = 2
_TYPE_REPORT_INTERACTIVE = 11


@dataclass(frozen=True)
class MediaRef:
    """A NotebookLM URL to download and store as `kind`."""

    kind: MediaFileKind
    url: str
    page_index: int | None = None


@dataclass(frozen=True)
class NotebookLmParse:
    content: dict[str, Any]
    media: list[MediaRef] = field(default_factory=list)


def _at(value: Any, *path: int) -> Any:
    """Index into nested lists; None if any step is missing."""
    for i in path:
        if not isinstance(value, list) or len(value) <= i:
            return None
        value = value[i]
    return value


def _str_at(value: Any, *path: int) -> str | None:
    found = _at(value, *path)
    return found if isinstance(found, str) and found.strip() else None


def _app_data(html: str | None, kind: str) -> dict[str, Any]:
    match = re.search(r'data-app-data="([^"]+)"', html or "")
    if not match:
        raise ArtifactParseError(f"{kind}: no data-app-data in NotebookLM's page")
    try:
        data = json.loads(html_lib.unescape(match.group(1)))
    except json.JSONDecodeError as exc:
        raise ArtifactParseError(f"{kind}: data-app-data is not JSON ({exc})") from exc
    if not isinstance(data, dict):
        raise ArtifactParseError(f"{kind}: data-app-data is not an object")
    return data


def _read_minutes(text: str) -> int:
    return max(1, round(len(text.split()) / _WORDS_PER_MINUTE))


# -- slide deck ----------------------------------------------------------------
def _first_line(text: str) -> str:
    for line in text.splitlines():
        line = line.strip().strip("#*").strip()
        if line and not line.startswith("["):
            return line
    return ""


def parse_slide_deck(row: list[Any]) -> NotebookLmParse:
    deck = _at(row, 16)
    slides_raw = _at(deck, 2)
    if not isinstance(slides_raw, list) or not slides_raw:
        raise ArtifactParseError("slide deck: no slides in NotebookLM's data")
    slides, media = [], []
    for i, item in enumerate(slides_raw):
        image = _str_at(item, 0, 0)
        summary = _str_at(item, 1) or ""
        text = _str_at(item, 2) or ""
        if not image:
            raise ArtifactParseError(f"slide deck: slide {i + 1} has no image")
        slides.append(
            {
                "title": _first_line(text) or summary or f"Slide {i + 1}",
                "bullets": [],
                "notes": text,
            }
        )
        media.append(MediaRef(MediaFileKind.slide_png, image, page_index=i))
    pdf, pptx = _str_at(deck, 3), _str_at(deck, 4)
    if not pdf or not pptx:
        raise ArtifactParseError("slide deck: NotebookLM gave no PDF/PPTX download")
    media += [MediaRef(MediaFileKind.deck_pdf, pdf), MediaRef(MediaFileKind.pptx, pptx)]
    content = validate(SlideDeckContent, {"slides": slides}).model_dump(mode="json")
    return NotebookLmParse(content, media)


def parse_outline(row: list[Any]) -> dict[str, Any]:
    """The draft outline of a deck waiting for review (status 6)."""
    items = _at(row, 30, 0)
    if not isinstance(items, list) or len(items) < 2:
        raise ArtifactParseError("slide outline: no outline in NotebookLM's data")
    lines = [_str_at(item, 0) or "" for item in items]
    return {"style": lines[0], "slides": [line for line in lines[1:] if line]}


# -- infographic ---------------------------------------------------------------
def parse_infographic(row: list[Any]) -> NotebookLmParse:
    item = _at(row, 14, 2, 0)
    image = _str_at(item, 1, 0)
    if not image:
        raise ArtifactParseError("infographic: NotebookLM gave no image")
    content = validate(
        InfographicContent,
        {"caption": _str_at(item, 2) or "", "description": _str_at(item, 3)},
    ).model_dump(mode="json")
    return NotebookLmParse(content, [MediaRef(MediaFileKind.infographic_png, image)])


# -- report --------------------------------------------------------------------
_md = MarkdownIt("commonmark", {"html": False}).enable("table")


def _sections_from_markdown(markdown: str) -> tuple[str | None, list[dict[str, str]]]:
    """Split a Document report on its `##` headings; the `#` line is the title."""
    title: str | None = None
    sections: list[dict[str, str]] = []
    heading, buf = "Overview", list[str]()

    def flush() -> None:
        body = "\n".join(buf).strip()
        if body:
            sections.append({"heading": heading, "html": sanitize_html(_md.render(body))})

    for line in markdown.splitlines():
        if line.startswith("# ") and title is None:
            title = line[2:].strip()
        elif line.startswith("## "):
            flush()
            heading, buf = line[3:].strip(), []
        else:
            buf.append(line)
    flush()
    return title, sections


def _run_html(run: list[Any]) -> str:
    """One interactive-report text run: [start, end, [text, format?]]."""
    text = _at(run, 2, 0)
    if not isinstance(text, str):
        return ""
    out = html_lib.escape(text)
    fmt = _at(run, 2, 1)
    if isinstance(fmt, list):
        if _at(fmt, 0) is True:
            out = f"<strong>{out}</strong>"
        if _at(fmt, 1) is True:
            out = f"<em>{out}</em>"
        if _at(fmt, 9) == 1:  # observed on "2^4", "A : B :: C : ?" — inline code
            out = f"<code>{out}</code>"
    return out


def _sections_from_blocks(blocks: list[Any]) -> list[dict[str, str]]:
    """Interactive report blocks → sections split on its top-level headings.

    Observed block styles: [null,5] section heading, [null,6] subheading,
    [null,7] minor heading, [null,1] list item (+ list descriptor), and
    [null,null,true] a highlighted statement. Blocks with no text body are
    embedded Studio items, which can't be fetched separately and are skipped.
    """
    sections: list[dict[str, str]] = []
    heading, parts = "Overview", []
    open_list: str | None = None

    def close_list() -> None:
        nonlocal open_list
        if open_list:
            parts.append(f"</{open_list}>")
            open_list = None

    def flush() -> None:
        close_list()
        if parts:
            sections.append({"heading": heading, "html": sanitize_html("".join(parts))})

    for block in blocks:
        body = _at(block, 2)
        if not isinstance(body, list):
            continue  # embedded Studio item
        runs = body[0] if isinstance(body[0], list) else []
        inner = "".join(_run_html(r) for r in runs)
        style = _at(body, 1)
        level = _at(style, 1)
        if style == [None, 5]:
            flush()
            heading = html_lib.unescape(re.sub("<[^>]+>", "", inner)).strip() or heading
            parts = []
        elif style in ([None, 6], [None, 7]):
            close_list()
            tag = "h3" if level == 6 else "h4"
            parts.append(f"<{tag}>{inner}</{tag}>")
        elif style == [None, 1]:
            descriptor = _at(body, 3, 3)
            marker = descriptor.get("101") if isinstance(descriptor, dict) else "•"
            tag = "ol" if isinstance(marker, str) and marker[:1].isdigit() else "ul"
            if open_list != tag:
                close_list()
                parts.append(f"<{tag}>")
                open_list = tag
            parts.append(f"<li>{inner}</li>")
        elif style == [None, None, True]:
            close_list()
            parts.append(f"<blockquote><p>{inner}</p></blockquote>")
        elif inner:
            close_list()
            parts.append(f"<p>{inner}</p>")
    flush()
    return sections


def parse_report(row: list[Any]) -> NotebookLmParse:
    title = _str_at(row, 1)
    kind = _at(row, 2)
    if kind == _TYPE_REPORT_DOCUMENT:
        markdown = _str_at(row, 7, 0)
        if not markdown:
            raise ArtifactParseError("report: NotebookLM's document has no text")
        md_title, sections = _sections_from_markdown(markdown)
        title = md_title or title
        words = markdown
    elif kind == _TYPE_REPORT_INTERACTIVE:
        blocks = _at(row, 34, 0, 0, 0)
        if not isinstance(blocks, list):
            raise ArtifactParseError("report: NotebookLM's interactive report has no blocks")
        sections = _sections_from_blocks(blocks)
        words = " ".join(re.sub("<[^>]+>", " ", s["html"]) for s in sections)
    else:
        raise ArtifactParseError(f"report: unexpected NotebookLM artifact type {kind!r}")
    if not title:
        raise ArtifactParseError("report: NotebookLM gave no title")
    content = validate(
        ReportContent,
        {
            "title": title,
            "read_minutes": _read_minutes(words),
            "key_takeaways": [],
            "sections": sections,
        },
    ).model_dump(mode="json")
    return NotebookLmParse(content)


# -- flashcards & quiz ---------------------------------------------------------
def _block_text(side: Any, where: str) -> str:
    blocks = side.get("flashcardContentBlock") if isinstance(side, dict) else None
    if not isinstance(blocks, list):
        raise ArtifactParseError(f"flashcards: {where} has no content blocks")
    texts = []
    for b in blocks:
        if not isinstance(b, dict) or b.get("type") != "text":
            raise ArtifactParseError(
                f"flashcards: {where} has a {b.get('type') if isinstance(b, dict) else b!r} block, "
                "which this app doesn't support yet"
            )
        texts.append(str(b.get("content", "")))
    return "\n".join(t for t in texts if t.strip())


def parse_flashcards(html: str | None) -> NotebookLmParse:
    cards_raw = _app_data(html, "flashcards").get("flashcards")
    if not isinstance(cards_raw, list) or not cards_raw:
        raise ArtifactParseError("flashcards: NotebookLM gave no cards")
    cards = [
        {
            "front": _block_text(c.get("f"), f"card {i + 1} front"),
            "back": _block_text(c.get("b"), f"card {i + 1} back"),
        }
        for i, c in enumerate(cards_raw)
    ]
    content = validate(FlashcardsContent, {"cards": cards}).model_dump(mode="json")
    return NotebookLmParse(content)


def parse_quiz(html: str | None) -> NotebookLmParse:
    raw = _app_data(html, "quiz").get("quiz")
    if not isinstance(raw, list) or not raw:
        raise ArtifactParseError("quiz: NotebookLM gave no questions")
    questions = []
    for i, q in enumerate(raw):
        options = q.get("answerOptions") if isinstance(q, dict) else None
        if not isinstance(options, list) or len(options) != 4:
            raise ArtifactParseError(
                f"quiz: question {i + 1} has {len(options) if isinstance(options, list) else 0} "
                "options; the quiz player supports exactly 4"
            )
        correct = [j for j, o in enumerate(options) if o.get("isCorrect") is True]
        if len(correct) != 1:
            raise ArtifactParseError(
                f"quiz: question {i + 1} has {len(correct)} correct answers; exactly 1 is supported"
            )
        questions.append(
            {
                "question": str(q.get("question", "")),
                "options": [str(o.get("text", "")) for o in options],
                "correct_index": correct[0],
                "explanation": str(options[correct[0]].get("rationale") or ""),
                "hint": q.get("hint") or None,
            }
        )
    content = validate(QuizContent, {"questions": questions}).model_dump(mode="json")
    return NotebookLmParse(content)


# -- audio ---------------------------------------------------------------------
def audio_url(row: list[Any]) -> str:
    """The AAC (itag 140) download of an Audio Overview."""
    for url in re.findall(r"https://[^\"\\\\]+", json.dumps(_at(row, 6))):
        if url.endswith("=mm,140"):
            return str(url)
    raise ArtifactParseError("audio overview: NotebookLM gave no audio download")


def parse_notebooklm(
    kind: ArtifactType, row: list[Any] | None, html: str | None
) -> NotebookLmParse:
    """Dispatch on artifact type. Audio is handled by the caller (its content
    needs the downloaded file's duration)."""
    if kind is ArtifactType.flashcards:
        return parse_flashcards(html)
    if kind is ArtifactType.quiz:
        return parse_quiz(html)
    if not isinstance(row, list):
        raise ArtifactParseError(f"{kind.value}: NotebookLM returned no artifact data")
    if kind is ArtifactType.slide_deck:
        return parse_slide_deck(row)
    if kind is ArtifactType.infographic:
        return parse_infographic(row)
    if kind is ArtifactType.report:
        return parse_report(row)
    raise ArtifactParseError(f"{kind.value}: not parsed here")
