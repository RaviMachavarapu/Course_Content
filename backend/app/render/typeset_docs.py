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

Which text is a formula follows the web exactly: plain-text fields (titles,
takeaways, cards, questions, notes, captions) use MathText's dollar rule
(frontend/src/components/math/segments.ts, ported below); report section HTML
carries its formulas as `.math-inline` / `.math-display` elements (as
renderMathInHtml reads them) and all other `$` there are literal.
"""

from __future__ import annotations

import io
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from typing import Any, NamedTuple
from urllib.parse import quote

from bs4 import BeautifulSoup, Comment, NavigableString, PageElement, Tag
from PIL import Image

from app.models.enums import ArtifactType, MediaFileKind
from app.schemas.content import (
    FlashcardsContent,
    InfographicContent,
    QuizContent,
    ReportContent,
    SlideDeckContent,
)


class StoredImage(NamedTuple):
    """One of the version's stored media files (kinds other than images are ignored)."""

    kind: MediaFileKind
    page_index: int | None
    data: bytes


class TypesetDoc(NamedTuple):
    markdown: str
    #: plain text; the service escapes it
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

#: Above this many image bytes in one document, images are re-encoded as JPEG
#: (the service caps a request at 25 MB, and base64 adds a third).
IMAGE_BUDGET_BYTES = 15 * 1024 * 1024
MAX_IMAGE_SIDE = 2000

# Sentinels while assembling inline text (NUL is stripped from all input).
_BR = "\x00b"  # hard line break
_PARA = "\x00p"  # paragraph break inside a plain-text field
_MATH_END = "\x00m"  # just after a formula

_PUNCT = re.compile(r"([!-/:-@\[-`{-~])")
_BLANK_LINES = re.compile(r"\n[ \t]*(?:\n[ \t]*)+")


# -- text and formulas ----------------------------------------------------------------
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
    content = " ".join(source.split())
    if not content:
        return ""
    longest = max((len(run) for run in re.findall(r"`+", content)), default=0)
    fence = "`" * (longest + 1)
    pad = " " if content.startswith("`") or content.endswith("`") else ""
    return f"{fence}{pad}{content}{pad}{fence}"


def _math(latex: str, display: bool, *, one_line: bool = False, inline_only: bool = False) -> str:
    src = _BLANK_LINES.sub("\n", latex.replace("\x00", "").strip())
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
    text = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n").strip()
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


# -- report section HTML -----------------------------------------------------------------
_HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_BLOCK_TAGS = _HEADINGS | {
    "p", "div", "ul", "ol", "li", "blockquote", "pre", "table", "hr", "dl", "dt", "dd",
    "figure", "figcaption", "caption", "thead", "tbody", "tfoot", "tr", "td", "th",
    "colgroup", "col",
}  # fmt: skip
_LINK_SCHEMES = ("http://", "https://", "mailto:")
_URL_SAFE = ":/?#@!$&'*+,;=%~"  # spaces, parentheses and brackets get %-encoded


@dataclass(frozen=True)
class _Ctx:
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
    m = re.fullmatch(r"(\s*)(.*?)(\s*)", inner, re.S)
    assert m is not None
    lead, core, trail = m.groups()
    return f"{lead}{mark}{core}{mark}{trail}" if core else lead + trail


def _inline_children(tag: Tag, ctx: _Ctx) -> str:
    return "".join(_inline(child, ctx) for child in tag.children)


def _inline(node: PageElement, ctx: _Ctx) -> str:
    if isinstance(node, Comment):
        return ""
    if isinstance(node, NavigableString):
        return _escape(re.sub(r"\s+", " ", str(node).replace("\x00", "")), nbsp=ctx.nbsp)
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
        return _escape(" ".join(str(node.get("alt") or "").split()))
    if name in _BLOCK_TAGS:
        return f" {_inline_children(node, ctx)} "
    return _inline_children(node, ctx)


def _blocks(children: Iterable[PageElement]) -> list[str]:
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
            out.extend(_block(child))
        else:
            buf.append(_inline(child, _Ctx()))
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


def _table(tag: Tag) -> list[str]:
    rows: list[list[str]] = []
    header = False
    for tr in tag.find_all("tr"):
        if tr.find_parent("table") is not tag:
            continue  # a nested table's row
        cells = [c for c in tr.children if isinstance(c, Tag) and c.name in ("td", "th")]
        if not rows:
            in_head = isinstance(tr.parent, Tag) and tr.parent.name == "thead"
            header = in_head or (bool(cells) and all(c.name == "th" for c in cells))
        ctx = _Ctx(one_line=True)
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
    title = _finish(_inline_children(caption, _Ctx())) if isinstance(caption, Tag) else ""
    return [title, "\n".join(lines)] if title else ["\n".join(lines)]


def _block(tag: Tag) -> list[str]:
    name = tag.name
    math = _math_class(tag)
    if math:
        formula = _finish(_math(tag.get_text(), math == "math-display"))
        return [formula] if formula else []
    if name in _HEADINGS:
        level = max(2, int(name[1]) - 1)  # level 1 is the report's section heading
        text = _finish(_inline_children(tag, _Ctx(one_line=True, inline_only=True)))
        return [f"{'#' * level} {text}"] if text else []
    if name in ("ul", "ol"):
        items = [c for c in tag.children if isinstance(c, Tag)]
        if not items:
            return []
        markers = [f"{i}." if name == "ol" else "-" for i in range(1, len(items) + 1)]
        return [_list_items(markers, [_blocks(li.children) for li in items])]
    if name == "blockquote":
        inner = "\n\n".join(_blocks(tag.children))
        quoted = "\n".join(f"> {line}" if line else ">" for line in inner.split("\n"))
        return [quoted] if inner else []
    if name == "pre":
        text = tag.get_text().replace("\x00", "").strip("\n")
        longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
        fence = "`" * max(3, longest + 1)
        return [f"{fence}\n{text}\n{fence}"]
    if name == "hr":
        return ["* * *"]
    if name == "table":
        return _table(tag)
    if name == "dt":
        term = _finish(_inline_children(tag, _Ctx(active=frozenset({"strong"}))))
        return [f"**{term}**"] if term else []
    if name in ("col", "colgroup"):
        return []
    return _blocks(tag.children)


def html_to_markdown(html: str) -> str:
    """Report section HTML (sanitised) → Markdown blocks."""
    soup = BeautifulSoup(html or "", "html.parser")
    return "\n\n".join(_blocks(soup.children))


# -- images -------------------------------------------------------------------------------
def _image_type(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    return None


def _reencode(data: bytes, fmt: str) -> bytes | None:
    try:
        with Image.open(io.BytesIO(data)) as opened:
            opened.load()
            img: Image.Image = opened
            if fmt == "JPEG":
                if img.mode in ("RGBA", "LA", "P"):
                    rgba = img.convert("RGBA")
                    img = Image.new("RGB", rgba.size, "white")
                    img.paste(rgba, mask=rgba.getchannel("A"))
                else:
                    img = img.convert("RGB")
                img.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
            out = io.BytesIO()
            img.save(out, fmt, **({"quality": 85} if fmt == "JPEG" else {}))
            return out.getvalue()
    except Exception:  # unreadable or hostile image: leave it out
        return None


def _prepare_images(named: Sequence[tuple[str, bytes]]) -> list[tuple[str, bytes] | None]:
    """(stem, bytes) → (file name, PNG/JPEG bytes), or None for an unreadable image.
    Everything is re-encoded as JPEG when the total is over IMAGE_BUDGET_BYTES."""
    out: list[tuple[str, bytes] | None] = []
    for stem, data in named:
        ext = _image_type(data)
        if ext is None:
            png = _reencode(data, "PNG")
            out.append((f"{stem}.png", png) if png else None)
        else:
            out.append((f"{stem}.{ext}", data))
    if sum(len(item[1]) for item in out if item) > IMAGE_BUDGET_BYTES:
        smaller: list[tuple[str, bytes] | None] = []
        for item in out:
            jpeg = _reencode(item[1], "JPEG") if item else None
            smaller.append((f"{item[0].rsplit('.', 1)[0]}.jpg", jpeg) if item and jpeg else None)
        out = smaller
    return out


# -- builders -----------------------------------------------------------------------------
def _join(blocks: Iterable[str]) -> str:
    return "\n\n".join(b for b in blocks if b) + "\n"


def build_report(
    content_json: dict[str, Any], media: Sequence[StoredImage], *, title: str | None = None
) -> TypesetDoc:
    c = ReportContent.model_validate(content_json)
    blocks = [f"*About {c.read_minutes} min read*"]
    if c.key_takeaways:
        blocks.append("# Key takeaways")
        bodies = [[text_to_markdown(t)] for t in c.key_takeaways]
        blocks.append(_list_items(["-"] * len(bodies), bodies))
    for section in c.sections:
        blocks.append(f"# {text_to_markdown(section.heading, one_line=True)}")
        blocks.append(html_to_markdown(section.html))
    return TypesetDoc(_join(blocks), title or c.title, {})


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
    return TypesetDoc(_join(blocks), title or "Flashcards", {})


_LETTERS = "ABCD"


def build_quiz(
    content_json: dict[str, Any], media: Sequence[StoredImage], *, title: str | None = None
) -> TypesetDoc:
    c = QuizContent.model_validate(content_json)
    blocks = ["# Questions"]
    for i, q in enumerate(c.questions, 1):
        blocks.append(f"## Question {i}")
        blocks.append(text_to_markdown(q.question))
        markers = [f"{letter}." for letter in _LETTERS[: len(q.options)]]
        blocks.append(_list_items(markers, [[text_to_markdown(o)] for o in q.options]))
    blocks.append("# Answer key")
    for i, q in enumerate(c.questions, 1):
        answer = text_to_markdown(q.options[q.correct_index])
        blocks.append(f"**{i}. {_LETTERS[q.correct_index]}:** {answer}")
        blocks.append(text_to_markdown(q.explanation))
    return TypesetDoc(_join(blocks), title or "Quiz", {})


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
    return TypesetDoc(_join(blocks), title or "Infographic", images)


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
    return TypesetDoc(_join(blocks), title or "Slides", images)


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
) -> TypesetDoc:
    """The typeset document for one artifact version. `media` is the version's
    stored files (bytes read from storage); `title` overrides the default
    (the report's own title; "Flashcards", "Quiz", "Infographic", "Slides")."""
    builder = _BUILDERS.get(artifact_type)
    if builder is None:
        raise ValueError(f"no typeset PDF for {artifact_type.value}")
    return builder(content_json, media, title=title)
