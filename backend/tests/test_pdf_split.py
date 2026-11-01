from __future__ import annotations

import os
from itertools import pairwise
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
    assert all(p.path.stat().st_size <= 700_000 for p in out)
    covered = [n for part in out for n in range(part.first_page, part.last_page + 1)]
    assert covered == [1, 2, 3, 4]


def test_scanned_pages_count_zero_words(tmp_path: Path) -> None:
    pdf = _make_pdf(tmp_path / "a.pdf", [(0, 1000)] * 6)
    assert plan_parts(pdf, max_bytes=10_000_000, max_words=1) == [PartPlan(1, 6)]


def test_single_page_over_limit_raises(tmp_path: Path) -> None:
    pdf = _make_pdf(tmp_path / "a.pdf", [(5, 1000), (5, 500_000), (5, 1000)])
    with pytest.raises(PageTooLarge) as exc:
        plan_parts(pdf, max_bytes=200_000, max_words=1_000_000)
    assert exc.value.page == 2
    assert str(exc.value) == ("a.pdf page 2 is larger than NotebookLM's per-source limit")


def test_encrypted_or_corrupt_raises_unreadable(tmp_path: Path) -> None:
    good = _make_pdf(tmp_path / "a.pdf", [(5, 0)] * 2)
    truncated = tmp_path / "t.pdf"
    truncated.write_bytes(good.read_bytes()[:40])
    with pytest.raises(PdfUnreadable) as exc:
        plan_parts(truncated, max_bytes=10_000_000, max_words=1000)
    assert str(exc.value) == "t.pdf can't be opened (damaged or password-protected)"

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
    assert [p.path.name for p in out] == ["a.part1.pdf", "a.part2.pdf", "a.part3.pdf"]
    assert sum(len(PdfReader(p.path).pages) for p in out) == 5


def test_write_parts_halves_oversize_plan(tmp_path: Path) -> None:
    pdf = _make_pdf(tmp_path / "a.pdf", [(5, 300_000)] * 4)
    plan = [PartPlan(1, 4)]
    out = write_parts(pdf, plan, tmp_path / "out", "a", max_bytes=700_000)
    assert len(out) > len(plan)
    assert out[0].first_page == 1 and out[-1].last_page == 4
    for prev, nxt in pairwise(out):
        assert nxt.first_page == prev.last_page + 1
    for i, part in enumerate(out, start=1):
        assert part.path.name == f"a.part{i}.pdf"
        assert part.path.stat().st_size <= 700_000
        assert len(PdfReader(part.path).pages) == part.last_page - part.first_page + 1


def test_write_parts_single_page_over_limit_raises(tmp_path: Path) -> None:
    pdf = _make_pdf(tmp_path / "a.pdf", [(5, 1000), (5, 500_000)])
    with pytest.raises(PageTooLarge) as exc:
        write_parts(pdf, [PartPlan(1, 2)], tmp_path / "out", "a", max_bytes=200_000)
    assert exc.value.page == 2


def _make_shared_pdf(path: Path, pages: int, shared_blob: int, own_blob: int = 0) -> Path:
    """Every page draws one shared image XObject (shared_blob bytes); each page may also
    draw its own image of own_blob bytes."""
    w = PdfWriter()

    def _image(size: int) -> DecodedStreamObject:
        img = DecodedStreamObject()
        img.set_data(os.urandom(size))
        img.update(
            {
                NameObject("/Type"): NameObject("/XObject"),
                NameObject("/Subtype"): NameObject("/Image"),
                NameObject("/Width"): NumberObject(size),
                NameObject("/Height"): NumberObject(1),
                NameObject("/ColorSpace"): NameObject("/DeviceGray"),
                NameObject("/BitsPerComponent"): NumberObject(8),
            }
        )
        return img

    shared = w._add_object(_image(shared_blob))
    for _ in range(pages):
        page = w.add_blank_page(width=612, height=792)
        xobjects = DictionaryObject({NameObject("/Sh"): shared})
        content = "q 1 0 0 1 0 0 cm /Sh Do Q\n"
        if own_blob:
            xobjects[NameObject("/Own")] = w._add_object(_image(own_blob))
            content += "q 1 0 0 1 0 0 cm /Own Do Q\n"
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/XObject"): xobjects})
        stream = DecodedStreamObject()
        stream.set_data(content.encode())
        page[NameObject("/Contents")] = w._add_object(stream)
    with path.open("wb") as fh:
        w.write(fh)
    return path


def test_shared_resource_small_file_is_one_part(tmp_path: Path) -> None:
    pdf = _make_shared_pdf(tmp_path / "a.pdf", pages=20, shared_blob=500_000)
    assert pdf.stat().st_size < 1_000_000
    assert plan_parts(pdf, max_bytes=1_000_000, max_words=1000) == [PartPlan(1, 20)]


def test_shared_resource_large_file_measures_real_ranges(tmp_path: Path) -> None:
    # 300 KB shared + 20 x 50 KB own: a range of k pages is ~300 KB + 50 KB * k, so a 1 MB
    # limit fits ~14 pages per part. Summing single pages (~350 KB each) would give 10 parts.
    pdf = _make_shared_pdf(tmp_path / "a.pdf", pages=20, shared_blob=300_000, own_blob=50_000)
    assert pdf.stat().st_size > 1_000_000
    parts = plan_parts(pdf, max_bytes=1_000_000, max_words=1000)
    assert len(parts) == 2
    assert parts[0].first_page == 1 and parts[-1].last_page == 20
    assert parts[1].first_page == parts[0].last_page + 1
    out = write_parts(pdf, parts, tmp_path / "out", "a", max_bytes=1_000_000)
    assert len(out) == 2
    assert all(p.path.stat().st_size <= 1_000_000 for p in out)


def test_page_text_extraction_error_counts_zero_words(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pypdf import PageObject

    pdf = _make_pdf(tmp_path / "a.pdf", [(100, 0)] * 3)
    original = PageObject.extract_text
    calls = {"n": 0}

    def flaky(self: PageObject, *args: object, **kwargs: object) -> str:
        calls["n"] += 1
        if calls["n"] == 2:
            raise ValueError("bad content stream")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(PageObject, "extract_text", flaky)
    # Page 2 counts 0 words: pages 1-2 = 100 words fit a 150-word part, page 3 starts another.
    assert plan_parts(pdf, max_bytes=10_000_000, max_words=150) == [PartPlan(1, 2), PartPlan(3, 3)]
