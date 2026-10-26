from __future__ import annotations

import os
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    NumberObject,
)

from app.pipeline.pdf_split import PageTooLarge, PartPlan, PdfUnreadable, plan_parts, write_parts


def _make_pdf(path: Path, pages: list[tuple[int, int]]) -> Path:
    """Each page is (words, blob_bytes). blob_bytes of incompressible data go in an XObject."""
    w = PdfWriter()
    font = w._add_object(
        DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
    )
    for words, blob in pages:
        page = w.add_blank_page(width=612, height=792)
        res = DictionaryObject()
        res[NameObject("/Font")] = DictionaryObject({NameObject("/F1"): font})
        content = ""
        if words:
            content += "BT /F1 8 Tf 10 780 Td (" + " ".join(["word"] * words) + ") Tj ET\n"
        if blob:
            img = DecodedStreamObject()
            img.set_data(os.urandom(blob))
            img.update(
                {
                    NameObject("/Type"): NameObject("/XObject"),
                    NameObject("/Subtype"): NameObject("/Image"),
                    NameObject("/Width"): NumberObject(blob),
                    NameObject("/Height"): NumberObject(1),
                    NameObject("/ColorSpace"): NameObject("/DeviceGray"),
                    NameObject("/BitsPerComponent"): NumberObject(8),
                }
            )
            res[NameObject("/XObject")] = DictionaryObject({NameObject("/Im1"): w._add_object(img)})
            content += "q 1 0 0 1 0 0 cm /Im1 Do Q\n"
        stream = DecodedStreamObject()
        stream.set_data(content.encode())
        page[NameObject("/Resources")] = res
        page[NameObject("/Contents")] = w._add_object(stream)
    with path.open("wb") as fh:
        w.write(fh)
    return path


def test_small_pdf_is_one_part(tmp_path: Path) -> None:
    pdf = _make_pdf(tmp_path / "a.pdf", [(10, 0)] * 3)
    assert plan_parts(pdf, max_bytes=10_000_000, max_words=1000) == [PartPlan(1, 3)]


def test_split_by_words(tmp_path: Path) -> None:
    pdf = _make_pdf(tmp_path / "a.pdf", [(100, 0)] * 5)
    assert plan_parts(pdf, max_bytes=10_000_000, max_words=250) == [
        PartPlan(1, 2),
        PartPlan(3, 4),
        PartPlan(5, 5),
    ]


def test_split_by_bytes(tmp_path: Path) -> None:
    pdf = _make_pdf(tmp_path / "a.pdf", [(5, 300_000)] * 4)
    parts = plan_parts(pdf, max_bytes=700_000, max_words=1_000_000)
    assert len(parts) > 1
    out = write_parts(pdf, parts, tmp_path / "out", "a", max_bytes=700_000)
    assert all(p.stat().st_size <= 700_000 for p in out)
    covered = [n for part in parts for n in range(part.first_page, part.last_page + 1)]
    assert covered == [1, 2, 3, 4]


def test_scanned_pages_count_zero_words(tmp_path: Path) -> None:
    pdf = _make_pdf(tmp_path / "a.pdf", [(0, 1000)] * 6)
    assert plan_parts(pdf, max_bytes=10_000_000, max_words=1) == [PartPlan(1, 6)]


def test_single_page_over_limit_raises(tmp_path: Path) -> None:
    pdf = _make_pdf(tmp_path / "a.pdf", [(5, 1000), (5, 500_000), (5, 1000)])
    with pytest.raises(PageTooLarge) as exc:
        plan_parts(pdf, max_bytes=200_000, max_words=1_000_000)
    assert exc.value.page == 2


def test_encrypted_or_corrupt_raises_unreadable(tmp_path: Path) -> None:
    good = _make_pdf(tmp_path / "a.pdf", [(5, 0)] * 2)
    truncated = tmp_path / "t.pdf"
    truncated.write_bytes(good.read_bytes()[:40])
    with pytest.raises(PdfUnreadable):
        plan_parts(truncated, max_bytes=10_000_000, max_words=1000)

    w = PdfWriter(clone_from=str(good))
    w.encrypt("secret", algorithm="AES-128")
    enc = tmp_path / "e.pdf"
    with enc.open("wb") as fh:
        w.write(fh)
    with pytest.raises(PdfUnreadable):
        plan_parts(enc, max_bytes=10_000_000, max_words=1000)


def test_write_parts_preserves_page_count(tmp_path: Path) -> None:
    pdf = _make_pdf(tmp_path / "a.pdf", [(100, 0)] * 5)
    parts = plan_parts(pdf, max_bytes=10_000_000, max_words=250)
    out = write_parts(pdf, parts, tmp_path / "out", "a")
    assert [p.name for p in out] == ["a.part1.pdf", "a.part2.pdf", "a.part3.pdf"]
    assert sum(len(PdfReader(p).pages) for p in out) == 5
