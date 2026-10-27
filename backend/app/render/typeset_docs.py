"""Artifact `content_json` (+ its stored images) → a document for the typeset
service: `(markdown, title, images)`.

The service reads pandoc Markdown with raw TeX and raw HTML disabled, so:

* formulas reach it verbatim between dollars (`$…$` inline, `$$…$$` display) —
  the same LaTeX the web page draws, never rewritten. Only whitespace pandoc
  can't carry is normalised (outer spaces, blank lines inside a formula, line
  breaks inside a table cell or heading). A formula pandoc can't hold between
  dollars at all (an unescaped `$` inside, a trailing control space) is shown
  as its source in monospace — the same thing the service does with a formula
  that doesn't compile;
* every other ASCII punctuation character in text is backslash-escaped, so
  text prints literally (pandoc then escapes it for LaTeX itself).

The document title is the Markdown's top heading (so its formulas are drawn)
and, as plain text, the PDF's metadata title.

Which text is a formula follows the web exactly: plain-text fields (titles,
takeaways, cards, questions, notes, captions) use MathText's dollar rule
(frontend/src/components/math/segments.ts, ported below); report section HTML
carries its formulas as `.math-inline` / `.math-display` elements (as
renderMathInHtml reads them) and all other `$` there are literal.
"""

from __future__ import annotations

import io
import re
import uuid
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from typing import Any, NamedTuple
from urllib.parse import quote

from bs4 import BeautifulSoup, Comment, NavigableString, PageElement, Tag
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.artifact import Artifact
from app.models.artifact_version import ArtifactVersion
from app.models.enums import ArtifactType, MediaFileKind
from app.models.media_file import MediaFile
from app.models.module import Module
from app.schemas.content import (
    FlashcardsContent,
    InfographicContent,
    QuizContent,
    ReportContent,
    SlideDeckContent,
)
from app.storage.keys import InvalidKeyError, validate_key
from app.storage.service import get_storage


class StoredImage(NamedTuple):
    """One of the version's stored media files (kinds other than images are ignored)."""

    kind: MediaFileKind
    page_index: int | None
    data: bytes


class TypesetDoc(NamedTuple):
    #: starts with the title as a `#` heading (its formulas drawn)
    markdown: str
    #: plain text for the PDF's metadata (formula sources without `$`); the
    #: service doesn't print it
    title: str
    #: names used in `![](name)` → PNG/JPEG bytes
    images: dict[str, bytes]


#: the media kind each artifact type's typeset PDF is stored as
PDF_KINDS: dict[ArtifactType, MediaFileKind] = {
    ArtifactType.report: MediaFileKind.report_pdf,
    ArtifactType.flashcards: MediaFileKind.flashcards_pdf,
    ArtifactType.quiz: MediaFileKind.quiz_pdf,
    ArtifactType.infographic: MediaFileKind.infographic_pdf,
    ArtifactType.slide_deck: MediaFileKind.slides_handout_pdf,
}

#: a quiz also gets a students' copy: questions and options, no answer key
#: (its `quiz_pdf` carries the answers and is never served to students)
STUDENT_PDF_KINDS: dict[ArtifactType, MediaFileKind] = {
    ArtifactType.quiz: MediaFileKind.quiz_questions_pdf,
}

#: reads a stored media file by its storage key
MediaLoader = Callable[[str], bytes]

# Sentinels while assembling inline text (NUL is stripped from all input).
_BR = "\x00b"  # hard line break
_PARA = "\x00p"  # paragraph break inside a plain-text field
_MATH_END = "\x00m"  # just after a formula

# C0 controls other than tab/newline/CR make xelatex fail; VT/FF are line breaks.
_CONTROLS = {c: None for c in [*range(0x00, 0x09), *range(0x0E, 0x20), 0x7F]} | {
    0x0B: "\n",
    0x0C: "\n",
}
_PUNCT = re.compile(r"([!-/:-@\[-`{-~])")
_BLANK_LINES = re.compile(r"\n[ \t]*(?:\n[ \t]*)+")


# -- text and formulas ----------------------------------------------------------------
def _clean(text: str) -> str:
    """Drop control characters (and so any NUL a sentinel could collide with)."""
    return text.translate(_CONTROLS)


def _escape(text: str, *, nbsp: bool = False) -> str:
    out = _PUNCT.sub(r"\\\1", text)
    return out.replace(" ", "\\ ") if nbsp else out


def _has_unescaped(latex: str, char: str) -> bool:
    i = 0
    while i < len(latex):
        if latex[i] == "\\":
            i += 2
            continue
        if latex[i] == char:
            return True
        i += 1
    return False


def _code(source: str) -> str:
    """`source` as an inline code span (prints verbatim, monospace)."""
    content = " ".join(_clean(source).split())
    if not content:
        return ""
    longest = max((len(run) for run in re.findall(r"`+", content)), default=0)
    fence = "`" * (longest + 1)
    pad = " " if content.startswith("`") or content.endswith("`") else ""
    return f"{fence}{pad}{content}{pad}{fence}"


def _math(latex: str, display: bool, *, one_line: bool = False, inline_only: bool = False) -> str:
    src = _BLANK_LINES.sub("\n", _clean(latex).strip())
    if not src:
        return ""
    if one_line and "\n" in src:
        if _has_unescaped(src, "%"):  # a line break ends a TeX comment
            return _code(src)
        src = re.sub(r"[ \t]*\n[ \t]*", " ", src)
    trailing = len(src) - len(src.rstrip("\\"))
    if trailing % 2 or _has_unescaped(src, "$"):
        return _code(src)
    fence = "$$" if display and not inline_only else "$"
    return f"{fence}{src}{fence}{_MATH_END}"


def _finish(md: str) -> str:
    """Resolve the sentinels of one block of inline Markdown."""
    # pandoc won't close `$…$` right before a digit; an empty span separates them
    md = re.sub(f"{_MATH_END}(?=[0-9])", "[]{}", md).replace(_MATH_END, "")
    breaks = f"(?:{_BR}|{_PARA}|\\s)"
    md = re.sub(f"^{breaks}+|{breaks}+$", "", md)
    md = re.sub(f"{breaks}*{_PARA}{breaks}*", "\n\n", md)
    return re.sub(f"[ \\t]*{_BR}[ \\t]*", "\\\\\n", md)


def _split_math(text: str) -> list[tuple[bool, str, bool]]:
    """MathText's split: (is_formula, text or LaTeX, display). A port of
    `splitMath` in frontend/src/components/math/segments.ts — keep in step."""
    out: list[tuple[bool, str, bool]] = []
    buf: list[str] = []
    i, n = 0, len(text)

    def flush() -> None:
        if buf:
            out.append((False, "".join(buf), False))
            buf.clear()

    while i < n:
        c = text[i]
        if c == "\\" and i + 1 < n and text[i + 1] == "$":
            buf.append("$")
            i += 2
            continue
        if c == "\\" and text[i + 1 : i + 2] == "\\" and text[i + 2 : i + 3] in ("(", "["):
            buf.append("\\\\")  # an escaped backslash: the bracket after it is text
            i += 2
            continue
        if c == "\\" and text[i + 1 : i + 2] in ("(", "["):
            display = text[i + 1] == "["
            end = _bracket_end(text, i + 2, "]" if display else ")")
            if end > i + 2:
                flush()
                out.append((True, text[i + 2 : end], display))
                i = end + 2
                continue
        if c == "$":
            if i + 1 < n and text[i + 1] == "$":
                end = _display_end(text, i + 2)
                if end > i + 2:
                    flush()
                    out.append((True, text[i + 2 : end], True))
                    i = end + 2
                    continue
            elif i + 1 < n and not text[i + 1].isspace():
                end = _inline_end(text, i + 1)
                if end > 0:
                    flush()
                    out.append((True, text[i + 1 : end], False))
                    i = end + 1
                    continue
        buf.append(c)
        i += 1
    flush()
    return out


def _bracket_end(s: str, start: int, close: str) -> int:
    j = start
    while j < len(s) - 1:
        if s[j] == "\\":
            if s[j + 1] == close:
                return j
            j += 1
        j += 1
    return -1


def _display_end(s: str, start: int) -> int:
    j = start
    while j < len(s) - 1:
        if s[j] == "\\":
            j += 2
            continue
        if s[j] == "$" and s[j + 1] == "$":
            return j
        j += 1
    return -1


def _inline_end(s: str, start: int) -> int:
    j = start
    while j < len(s):
        if s[j] == "\\":
            j += 2
            continue
        if (
            s[j] == "$"
            and not s[j - 1].isspace()
            and not (j + 1 < len(s) and s[j + 1] in "0123456789")
        ):
            return j
        j += 1
    return -1


def text_to_markdown(text: str, *, one_line: bool = False) -> str:
    """A plain-text field (MathText on the web) as Markdown: its `$…$`/`$$…$$`
    formulas kept, everything else literal. Line breaks become hard breaks and
    blank lines paragraph breaks, unless `one_line` (headings)."""
    text = _clean(text).replace("\r\n", "\n").replace("\r", "\n").strip()
    parts: list[str] = []
    for is_math, s, display in _split_math(text):
        if is_math:
            parts.append(_math(s, display, one_line=one_line, inline_only=one_line))
            continue
        s = re.sub(r"[ \t]+", " ", _escape(s))
        if one_line:
            s = re.sub(r"\s+", " ", s)
        else:
            s = re.sub(r" ?\n(?: ?\n)+ ?", _PARA, s)
            s = re.sub(r" ?\n ?", _BR, s)
        parts.append(s)
    return _finish("".join(parts))


def plain_title(text: str) -> str:
    """A title as plain text: formula sources kept, their `$` delimiters dropped."""
    return " ".join("".join(s for _, s, _ in _split_math(_clean(text))).split())


# -- report section HTML -----------------------------------------------------------------
_HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_BLOCK_TAGS = _HEADINGS | {
    "p", "div", "ul", "ol", "li", "blockquote", "pre", "table", "hr", "dl", "dt", "dd",
    "figure", "figcaption", "caption", "thead", "tbody", "tfoot", "tr", "td", "th",
    "colgroup", "col",
}  # fmt: skip
_LINK_SCHEMES = ("http://", "https://", "mailto:")
_URL_SAFE = ":/?#@!$&'*+,;=%~"  # spaces, parentheses and brackets get %-encoded


@dataclass
class _Media:
    """Report section images: loads `/api/media/<key>` sources and collects them."""

    load: MediaLoader | None
    images: dict[str, bytes]

    def embed(self, src: str) -> str | None:
        """The name of the embedded image for `src`, or None (not ours / unreadable)."""
        if self.load is None:
            return None
        base = get_settings().public_base_url.rstrip("/")
        key = next(
            (src[len(p) :] for p in (f"{base}/api/media/", "/api/media/") if src.startswith(p)),
            None,
        )
        if not key:
            return None
        try:
            validate_key(key)
            data = self.load(key)
        except (InvalidKeyError, OSError, ValueError):
            return None
        (prepared,) = _prepare_images([(f"image-{len(self.images) + 1:03d}", data)])
        if prepared is None:
            return None
        self.images[prepared[0]] = prepared[1]
        return prepared[0]


@dataclass(frozen=True)
class _Ctx:
    media: _Media | None = None
    active: frozenset[str] = frozenset()
    nbsp: bool = False  # inside sub/sup: spaces must be escaped
    one_line: bool = False  # table cells and headings
    inline_only: bool = False  # headings: display formulas drawn inline


def _math_class(tag: Tag) -> str | None:
    classes = tag.get("class") or []
    for cls in ("math-display", "math-inline"):
        if cls in classes:
            return cls
    return None


def _wrap(mark: str, inner: str) -> str:
    """`inner` between `mark`s, with its outer spaces (incl. escaped `\\ ` and
    line breaks) moved outside — pandoc needs the marks next to text."""
    tokens = re.findall(r"\\.|\x00.|.", inner, re.S)

    def spacy(tok: str) -> bool:
        return tok.isspace() or tok in ("\\ ", _BR)

    start, end = 0, len(tokens)
    while start < end and spacy(tokens[start]):
        start += 1
    while end > start and spacy(tokens[end - 1]):
        end -= 1

    def outside(toks: list[str]) -> str:
        return "".join(" " if t == "\\ " else t for t in toks)

    lead, trail = outside(tokens[:start]), outside(tokens[end:])
    core = "".join(tokens[start:end])
    return f"{lead}{mark}{core}{mark}{trail}" if core else lead + trail


def _inline_children(tag: Tag, ctx: _Ctx) -> str:
    return "".join(_inline(child, ctx) for child in tag.children)


def _inline(node: PageElement, ctx: _Ctx) -> str:
    if isinstance(node, Comment):
        return ""
    if isinstance(node, NavigableString):
        return _escape(re.sub(r"\s+", " ", _clean(str(node))), nbsp=ctx.nbsp)
    if not isinstance(node, Tag):
        return ""
    name = node.name
    math = _math_class(node)
    if math:
        return _math(
            node.get_text(),
            math == "math-display",
            one_line=ctx.one_line,
            inline_only=ctx.inline_only,
        )
    if name == "br":
        if ctx.nbsp:  # inside sub/sup
            return "\\ "
        return " " if ctx.one_line else _BR
    marks = {"strong": "**", "b": "**", "em": "*", "i": "*", "s": "~~", "sub": "~", "sup": "^"}
    if name in marks:
        group = {"b": "strong", "i": "em"}.get(name, name)
        if group in ctx.active:
            return _inline_children(node, ctx)
        inner_ctx = replace(
            ctx, active=ctx.active | {group}, nbsp=ctx.nbsp or name in ("sub", "sup")
        )
        return _wrap(marks[name], _inline_children(node, inner_ctx))
    if name == "code":
        return _code(node.get_text())
    if name == "a":
        inner = _inline_children(node, ctx).strip()
        href = str(node.get("href") or "").strip()
        if href.startswith(_LINK_SCHEMES) and inner:
            return f"[{inner}]({quote(href, safe=_URL_SAFE)})"
        return inner
    if name == "img":
        alt = _escape(" ".join(_clean(str(node.get("alt") or "")).split()))
        embedded = ctx.media.embed(str(node.get("src") or "").strip()) if ctx.media else None
        # no alt text once embedded: pandoc would caption a lone image "Figure 1: <alt>"
        return f"![]({embedded})" if embedded else alt
    if name in _BLOCK_TAGS:
        return f" {_inline_children(node, ctx)} "
    return _inline_children(node, ctx)


def _blocks(children: Iterable[PageElement], base: _Ctx) -> list[str]:
    out: list[str] = []
    buf: list[str] = []

    def flush() -> None:
        para = _finish("".join(buf))
        buf.clear()
        if para:
            out.append(para)

    for child in children:
        if isinstance(child, Tag) and (
            child.name in _BLOCK_TAGS or _math_class(child) == "math-display"
        ):
            flush()
            out.extend(_block(child, base))
        else:
            buf.append(_inline(child, base))
    flush()
    return out


def _list_items(markers: Sequence[str], bodies: Sequence[list[str]]) -> str:
    """A Markdown list; each body is the item's blocks."""
    items = []
    for marker, blocks in zip(markers, bodies, strict=True):
        lead = marker.ljust(4) if len(marker) < 4 else f"{marker} "
        lines = "\n\n".join(blocks).split("\n")
        rest = [f"{' ' * len(lead)}{line}" if line else "" for line in lines[1:]]
        items.append("\n".join([lead + lines[0], *rest]).rstrip())
    loose = any(len(blocks) > 1 for blocks in bodies)
    return ("\n\n" if loose else "\n").join(items)


def _table(tag: Tag, base: _Ctx) -> list[str]:
    rows: list[list[str]] = []
    header = False
    for tr in tag.find_all("tr"):
        if tr.find_parent("table") is not tag:
            continue  # a nested table's row
        cells = [c for c in tr.children if isinstance(c, Tag) and c.name in ("td", "th")]
        if not rows:
            in_head = isinstance(tr.parent, Tag) and tr.parent.name == "thead"
            header = in_head or (bool(cells) and all(c.name == "th" for c in cells))
        ctx = replace(base, one_line=True)
        rows.append([_finish(_inline_children(c, ctx)) for c in cells])
    width = max((len(r) for r in rows), default=0)
    if not width:
        return []
    rows = [r + [""] * (width - len(r)) for r in rows]
    head = rows.pop(0) if header else [""] * width
    lines = [
        "| " + " | ".join(head) + " |",
        "|" + "|".join(["---"] * width) + "|",
        *("| " + " | ".join(r) + " |" for r in rows),
    ]
    caption = tag.find("caption")
    title = _finish(_inline_children(caption, base)) if isinstance(caption, Tag) else ""
    return [title, "\n".join(lines)] if title else ["\n".join(lines)]


def _block(tag: Tag, base: _Ctx) -> list[str]:
    name = tag.name
    math = _math_class(tag)
    if math:
        formula = _finish(_math(tag.get_text(), math == "math-display"))
        return [formula] if formula else []
    if name in _HEADINGS:
        # levels 1 and 2 are the document title and the report's section headings
        level = max(3, int(name[1]))
        text = _finish(_inline_children(tag, replace(base, one_line=True, inline_only=True)))
        return [f"{'#' * level} {text}"] if text else []
    if name in ("ul", "ol"):
        items = [c for c in tag.children if isinstance(c, Tag)]
        if not items:
            return []
        markers = [f"{i}." if name == "ol" else "-" for i in range(1, len(items) + 1)]
        return [_list_items(markers, [_blocks(li.children, base) for li in items])]
    if name == "blockquote":
        inner = "\n\n".join(_blocks(tag.children, base))
        quoted = "\n".join(f"> {line}" if line else ">" for line in inner.split("\n"))
        return [quoted] if inner else []
    if name == "pre":
        text = _clean(tag.get_text()).strip("\n")
        longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
        fence = "`" * max(3, longest + 1)
        return [f"{fence}\n{text}\n{fence}"]
    if name == "hr":
        return ["* * *"]
    if name == "table":
        return _table(tag, base)
    if name == "dt":
        term = _finish(_inline_children(tag, replace(base, active=frozenset({"strong"}))))
        return [f"**{term}**"] if term else []
    if name in ("col", "colgroup"):
        return []
    return _blocks(tag.children, base)


def html_to_markdown(
    html: str,
    *,
    load_media: MediaLoader | None = None,
    images: dict[str, bytes] | None = None,
) -> str:
    """Report section HTML (sanitised) → Markdown blocks.

    `<img>` with one of our media URLs (`/api/media/<key>`, optionally under
    PUBLIC_BASE_URL) is read with `load_media` and added to `images` as
    `image-NNN.png|jpg`; any other image (or without a loader) is its alt text."""
    soup = BeautifulSoup(html or "", "html.parser")
    media = _Media(load_media, images if images is not None else {})
    return "\n\n".join(_blocks(soup.children, _Ctx(media=media)))


# -- images -------------------------------------------------------------------------------
def _image_type(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    return None


def _to_png(data: bytes) -> bytes | None:
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.load()
            out = io.BytesIO()
            img.save(out, "PNG")
            return out.getvalue()
    except Exception:  # unreadable or hostile image: leave it out
        return None


def _prepare_images(named: Sequence[tuple[str, bytes]]) -> list[tuple[str, bytes] | None]:
    """(stem, bytes) → (file name, PNG/JPEG bytes) unchanged; other formats Pillow
    reads (WebP, GIF, …) become PNG; None for an unreadable image."""
    out: list[tuple[str, bytes] | None] = []
    for stem, data in named:
        ext = _image_type(data)
        if ext is None:
            png = _to_png(data)
            out.append((f"{stem}.png", png) if png else None)
        else:
            out.append((f"{stem}.{ext}", data))
    return out


# -- builders -----------------------------------------------------------------------------
def _doc(title: str, blocks: Iterable[str], images: dict[str, bytes]) -> TypesetDoc:
    """The title as the top heading (formulas drawn) and as plain metadata."""
    heading = text_to_markdown(title, one_line=True)
    body = [f"# {heading}" if heading else "", *blocks]
    return TypesetDoc("\n\n".join(b for b in body if b) + "\n", plain_title(title), images)


def course_media_loader(db: Session, course_id: uuid.UUID) -> MediaLoader:
    """Reads a stored file only if it is a MediaFile of an artifact in `course_id`;
    anything else raises (and the report prints the image's alt text)."""

    def load(key: str) -> bytes:
        owner = db.scalar(
            select(Module.course_id)
            .join(Artifact, Artifact.module_id == Module.id)
            .join(ArtifactVersion, ArtifactVersion.artifact_id == Artifact.id)
            .join(MediaFile, MediaFile.artifact_version_id == ArtifactVersion.id)
            .where(MediaFile.storage_key == key)
            .limit(1)
        )
        if owner != course_id:
            raise ValueError(f"media {key!r} is not this course's")
        return get_storage().open(key)

    return load


def build_report(
    content_json: dict[str, Any],
    media: Sequence[StoredImage],
    *,
    title: str | None = None,
    load_media: MediaLoader | None = None,
) -> TypesetDoc:
    """Section headings are numbered like the student ReportViewer. Section
    images on our media URLs are read with `load_media` (see `course_media_loader`);
    without one they print as their alt text."""
    c = ReportContent.model_validate(content_json)
    images: dict[str, bytes] = {}
    blocks = [f"*About {c.read_minutes} min read*"]
    if c.key_takeaways:
        blocks.append("## Key takeaways")
        bodies = [[text_to_markdown(t)] for t in c.key_takeaways]
        blocks.append(_list_items(["-"] * len(bodies), bodies))
    for i, section in enumerate(c.sections, 1):
        blocks.append(f"## {i}. {text_to_markdown(section.heading, one_line=True)}")
        blocks.append(html_to_markdown(section.html, load_media=load_media, images=images))
    return _doc(title or c.title, blocks, images)


def build_flashcards(
    content_json: dict[str, Any], media: Sequence[StoredImage], *, title: str | None = None
) -> TypesetDoc:
    c = FlashcardsContent.model_validate(content_json)
    blocks: list[str] = []
    for i, card in enumerate(c.cards, 1):
        blocks.append(f"## Card {i}")
        category = text_to_markdown(card.category or "")
        if category:
            blocks.append(f"**Category:** {category}")
        blocks.append(f"**Front:** {text_to_markdown(card.front)}")
        blocks.append(f"**Back:** {text_to_markdown(card.back)}")
    return _doc(title or "Flashcards", blocks, {})


_LETTERS = "ABCD"


def build_quiz(
    content_json: dict[str, Any],
    media: Sequence[StoredImage],
    *,
    title: str | None = None,
    answer_key: bool = True,
) -> TypesetDoc:
    """Questions with their options, then (unless `answer_key` is False: the
    students' copy) the answer key: correct option and explanation."""
    c = QuizContent.model_validate(content_json)
    blocks = ["## Questions"]
    for i, q in enumerate(c.questions, 1):
        blocks.append(f"### Question {i}")
        blocks.append(text_to_markdown(q.question))
        markers = [f"{letter}." for letter in _LETTERS[: len(q.options)]]
        blocks.append(_list_items(markers, [[text_to_markdown(o)] for o in q.options]))
    if not answer_key:
        return _doc(title or "Quiz", blocks, {})
    blocks.append("## Answer key")
    for i, q in enumerate(c.questions, 1):
        answer = text_to_markdown(q.options[q.correct_index])
        blocks.append(f"**{i}. {_LETTERS[q.correct_index]}:** {answer}")
        blocks.append(text_to_markdown(q.explanation))
    return _doc(title or "Quiz", blocks, {})


def build_infographic(
    content_json: dict[str, Any], media: Sequence[StoredImage], *, title: str | None = None
) -> TypesetDoc:
    c = InfographicContent.model_validate(content_json)
    blocks: list[str] = []
    images: dict[str, bytes] = {}
    png = next((m for m in media if m.kind is MediaFileKind.infographic_png), None)
    if png is not None:
        (prepared,) = _prepare_images([("infographic", png.data)])
        if prepared:
            images[prepared[0]] = prepared[1]
            blocks.append(f"![]({prepared[0]})")
    blocks.append(text_to_markdown(c.caption))
    blocks.append(text_to_markdown(c.description or ""))
    return _doc(title or "Infographic", blocks, images)


def build_slide_deck(
    content_json: dict[str, Any], media: Sequence[StoredImage], *, title: str | None = None
) -> TypesetDoc:
    """Slide images in page order, each followed by the notes of the slide at the
    same position; if the counts differ, whatever exists is included."""
    c = SlideDeckContent.model_validate(content_json)
    pngs = sorted(
        (m for m in media if m.kind is MediaFileKind.slide_png),
        key=lambda m: (m.page_index is None, m.page_index or 0),
    )
    prepared = _prepare_images([(f"slide-{i:03d}", m.data) for i, m in enumerate(pngs, 1)])
    images: dict[str, bytes] = {}
    blocks: list[str] = []
    for i in range(max(len(pngs), len(c.slides))):
        blocks.append(f"## Slide {i + 1}")
        image = prepared[i] if i < len(prepared) else None
        if image:
            images[image[0]] = image[1]
            blocks.append(f"![]({image[0]})")
        if i < len(c.slides):
            blocks.append(text_to_markdown(c.slides[i].notes or ""))
    return _doc(title or "Slides", blocks, images)


Builder = Callable[..., TypesetDoc]

_BUILDERS: dict[ArtifactType, Builder] = {
    ArtifactType.report: build_report,
    ArtifactType.flashcards: build_flashcards,
    ArtifactType.quiz: build_quiz,
    ArtifactType.infographic: build_infographic,
    ArtifactType.slide_deck: build_slide_deck,
}


def build_document(
    artifact_type: ArtifactType,
    content_json: dict[str, Any],
    media: Sequence[StoredImage],
    *,
    title: str | None = None,
    load_media: MediaLoader | None = None,
) -> TypesetDoc:
    """The typeset document for one artifact version. `media` is the version's
    stored files (bytes read from storage); `title` overrides the default
    (the report's own title; "Flashcards", "Quiz", "Infographic", "Slides").
    `load_media` reads report-section images by storage key — pass
    `course_media_loader(db, course_id)`; without it they print as alt text."""
    builder = _BUILDERS.get(artifact_type)
    if builder is None:
        raise ValueError(f"no typeset PDF for {artifact_type.value}")
    if artifact_type is ArtifactType.report:
        return builder(content_json, media, title=title, load_media=load_media)
    return builder(content_json, media, title=title)


def build_documents(
    artifact_type: ArtifactType,
    content_json: dict[str, Any],
    media: Sequence[StoredImage],
    *,
    title: str | None = None,
    load_media: MediaLoader | None = None,
) -> dict[MediaFileKind, TypesetDoc]:
    """Every typeset PDF of one artifact version by media kind, the type's
    `PDF_KINDS` one first; a quiz also gets its students' copy (questions and
    options only). Arguments as for `build_document`."""
    main = build_document(artifact_type, content_json, media, title=title, load_media=load_media)
    docs = {PDF_KINDS[artifact_type]: main}
    if artifact_type is ArtifactType.quiz:
        docs[STUDENT_PDF_KINDS[artifact_type]] = build_quiz(
            content_json, media, title=title, answer_key=False
        )
    return docs
