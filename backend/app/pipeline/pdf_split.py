"""Split an oversize PDF into page-range parts that fit NotebookLM's per-source limits."""

from __future__ import annotations

import io
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader, PdfWriter

from app.config import get_settings


@dataclass(frozen=True)
class PartPlan:
    first_page: int  # 1-based, inclusive
    last_page: int  # 1-based, inclusive


@dataclass(frozen=True)
class WrittenPart:
    first_page: int  # 1-based, inclusive
    last_page: int
    path: Path


class PdfUnreadable(Exception):
    """The file is damaged or password-protected."""


class PageTooLarge(Exception):
    def __init__(self, page: int, name: str = "") -> None:
        self.page = page
        prefix = f"{name} " if name else ""
        super().__init__(f"{prefix}page {page} is larger than NotebookLM's per-source limit")


def _open(path: Path) -> PdfReader:
    msg = f"{path.name} can't be opened (damaged or password-protected)"
    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted and not reader.decrypt(""):
            raise PdfUnreadable(msg)
        if len(reader.pages) == 0:
            raise PdfUnreadable(msg)
    except PdfUnreadable:
        raise
    except Exception as exc:  # pypdf raises many error types on damaged input
        raise PdfUnreadable(msg) from exc
    return reader


def _pages_size(reader: PdfReader, first: int, last: int) -> int:
    """Real byte size of a PDF holding pages first..last (1-based, inclusive)."""
    writer = PdfWriter()
    for i in range(first - 1, last):
        writer.add_page(reader.pages[i])
    buf = io.BytesIO()
    writer.write(buf)
    return buf.tell()


def plan_parts(path: Path, *, max_bytes: int, max_words: int) -> list[PartPlan]:
    reader = _open(path)
    parts: list[PartPlan] = []
    start = 1
    words = 0
    size = 0
    try:
        for n in range(1, len(reader.pages) + 1):
            page_words = len((reader.pages[n - 1].extract_text() or "").split())
            page_size = _pages_size(reader, n, n)
            if page_size > max_bytes or page_words > max_words:
                raise PageTooLarge(n, path.name)
            if n > start and (words + page_words > max_words or size + page_size > max_bytes):
                parts.append(PartPlan(start, n - 1))
                start, words, size = n, 0, 0
            words += page_words
            size += page_size
    except PageTooLarge:
        raise
    except Exception as exc:
        raise PdfUnreadable(f"{path.name} can't be opened (damaged or password-protected)") from exc
    parts.append(PartPlan(start, len(reader.pages)))
    return parts


def _render(reader: PdfReader, first: int, last: int) -> bytes:
    writer = PdfWriter()
    for i in range(first - 1, last):
        writer.add_page(reader.pages[i])
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _render_fitting(
    reader: PdfReader, part: PartPlan, max_bytes: int, name: str
) -> Iterator[tuple[PartPlan, bytes]]:
    """Yield (range, bytes) in page order; a range over max_bytes is halved and recursed."""
    data = _render(reader, part.first_page, part.last_page)
    if len(data) <= max_bytes:
        yield part, data
        return
    if part.first_page == part.last_page:
        raise PageTooLarge(part.first_page, name)
    del data
    mid = (part.first_page + part.last_page) // 2
    yield from _render_fitting(reader, PartPlan(part.first_page, mid), max_bytes, name)
    yield from _render_fitting(reader, PartPlan(mid + 1, part.last_page), max_bytes, name)


def write_parts(
    path: Path,
    parts: list[PartPlan],
    out_dir: Path,
    stem: str,
    *,
    max_bytes: int | None = None,
) -> list[WrittenPart]:
    """Write parts as {stem}.part{i}.pdf (1-based), each to disk as soon as it is rendered.

    Because shared resources make plan-time size estimates inexact, any part whose real size
    exceeds max_bytes (default: the setting) is split in half; a single page still too big
    raises PageTooLarge. The result can therefore be longer than ``parts``; each WrittenPart
    carries its own page range."""
    limit = max_bytes if max_bytes is not None else get_settings().source_part_max_bytes
    reader = _open(path)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[WrittenPart] = []
    for part in parts:
        for rng, data in _render_fitting(reader, part, limit, path.name):
            target = out_dir / f"{stem}.part{len(written) + 1}.pdf"
            target.write_bytes(data)
            written.append(WrittenPart(rng.first_page, rng.last_page, target))
    return written
