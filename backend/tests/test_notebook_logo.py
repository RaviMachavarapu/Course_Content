"""Cropping NotebookLM's "Gemini Notebook" mark off generated images (owner decision
2026-10-29): detection on synthetic images (dark and light backgrounds, mark present or
absent), on corners cut from real NotebookLM output, the deck PDF / PPTX rebuild, and the
pipeline step."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont
from pptx import Presentation
from pptx.util import Emu
from pypdf import PdfReader

from app.models.enums import MediaFileKind
from app.pipeline.renderers import MediaBlob, strip_notebook_logo
from app.render import notebook_logo as nl

FIX = Path(__file__).parent / "fixtures" / "notebook_logo"

DARK = (12, 58, 110)
LIGHT = (250, 250, 250)


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    return ImageFont.load_default(size=size)


def _logo(image: Image.Image, *, scale: float = 1.0) -> tuple[int, int]:
    """Draw a "Gemini Notebook" mark like NotebookLM's in the bottom-right corner; returns
    its (top, bottom) rows."""
    w, h = image.size
    draw = ImageDraw.Draw(image)
    bg = image.getpixel((w - 2, h - 2))
    assert isinstance(bg, tuple)
    ink = (0, 0, 0) if sum(bg[:3]) > 380 else (235, 240, 245)
    font = _font(round(11 * scale))
    text = "Gemini Notebook"
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    x = w - round(11 * scale) - (right - left)
    y = h - round(12 * scale) - (bottom - top)
    draw.text((x - left, y - top), text, fill=ink, font=font)
    return y, y + (bottom - top)


def _slide(bg: tuple[int, int, int], *, size: tuple[int, int] = (1376, 768)) -> Image.Image:
    image = Image.new("RGB", size, bg)
    draw = ImageDraw.Draw(image)
    fg = (0, 0, 0) if sum(bg) > 380 else (230, 240, 255)
    draw.text((80, 60), "A slide title", fill=fg, font=_font(48))
    draw.rectangle((80, 200, 900, 520), outline=fg, width=3)
    draw.text((100, 690), "Body text near the bottom-left", fill=fg, font=_font(22))
    return image


def _png(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


def _size(png: bytes) -> tuple[int, int]:
    with Image.open(io.BytesIO(png)) as im:
        return im.size


@pytest.mark.parametrize("bg", [DARK, LIGHT], ids=["dark", "light"])
def test_the_mark_is_cropped_with_the_strip_below_it(bg: tuple[int, int, int]) -> None:
    image = _slide(bg)
    top, _bottom = _logo(image)
    result = nl.strip_logo(_png(image), label="slide")
    assert result.cropped > 0
    assert result.size == (1376, 768 - result.cropped)
    assert top - 3 <= result.size[1] <= top  # cut just above the mark
    assert result.cropped <= 768 * nl.MAX_CROP_SHARE + 1
    with Image.open(io.BytesIO(result.data)) as out:
        assert nl.is_marked(out)
        # nothing of the slide above the strip changed
        assert out.convert("RGB").tobytes() == image.crop((0, 0, 1376, result.size[1])).tobytes()


@pytest.mark.parametrize("bg", [DARK, LIGHT], ids=["dark", "light"])
def test_without_the_mark_the_image_is_unchanged(bg: tuple[int, int, int]) -> None:
    png = _png(_slide(bg))
    result = nl.strip_logo(png)
    assert result.cropped == 0 and result.data == png


@pytest.mark.parametrize(
    ("size", "scale"),
    [((1536, 2752), 2.0), ((2752, 1536), 2.0), ((2048, 2048), 2.0)],
    ids=["portrait", "landscape", "square"],
)
def test_infographic_shapes(size: tuple[int, int], scale: float) -> None:
    image = Image.new("RGB", size, LIGHT)
    ImageDraw.Draw(image).rounded_rectangle(
        (100, 100, size[0] - 100, size[1] - 300), radius=40, fill=(230, 110, 40)
    )
    top, _ = _logo(image, scale=scale)
    result = nl.strip_logo(_png(image))
    assert result.cropped > 0
    assert top - 4 <= result.size[1] <= top


def test_a_cropped_image_is_left_alone_on_a_second_run() -> None:
    image = _slide(DARK)
    _logo(image)
    once = nl.strip_logo(_png(image))
    twice = nl.strip_logo(once.data)
    assert twice.already and twice.cropped == 0 and twice.data == once.data
    # and even without the marker, nothing mark-shaped is left to find
    with Image.open(io.BytesIO(once.data)) as out:
        assert nl.find_logo(out.convert("RGB")) is None


def test_content_in_the_corner_is_not_taken_for_the_mark() -> None:
    image = _slide(DARK)
    draw = ImageDraw.Draw(image)
    # a big block of text filling the bottom-right corner, down to the edge
    for row in range(5):
        draw.text((1050, 640 + 26 * row), "Lorem ipsum dolor sit", fill="white", font=_font(22))
    assert nl.strip_logo(_png(image)).cropped == 0


def test_a_line_across_the_corner_is_not_the_mark() -> None:
    image = _slide(LIGHT)
    ImageDraw.Draw(image).line((0, 755, 1376, 755), fill=(0, 0, 0), width=2)
    assert nl.strip_logo(_png(image)).cropped == 0


def test_the_crop_never_exceeds_five_percent() -> None:
    image = _slide(DARK)
    _logo(image, scale=4.0)  # a mark far taller than NotebookLM's
    result = nl.strip_logo(_png(image))
    assert result.cropped <= 768 * nl.MAX_CROP_SHARE + 1


def test_slide_lines_just_above_the_mark_are_kept() -> None:
    image = _slide(DARK)
    top, _ = _logo(image)
    ImageDraw.Draw(image).line((0, top - 4, 1350, top - 4), fill=(200, 220, 255), width=2)
    result = nl.strip_logo(_png(image))
    assert result.cropped > 0
    assert result.size[1] >= top - 2  # the line (rows top-4..top-3) stays


# -- corners cut from real NotebookLM output (module 2, 2026-10-28) ---------------------


def _real(name: str, size: tuple[int, int]) -> Image.Image:
    corner = Image.open(FIX / name).convert("RGB")
    canvas = Image.new("RGB", size, corner.getpixel((0, 0)))  # type: ignore[arg-type]
    canvas.paste(corner, (size[0] - corner.size[0], size[1] - corner.size[1]))
    return canvas


def test_real_slide_mark_on_a_plain_background() -> None:
    image = _real("slide_corner_plain.png", (1376, 768))
    box = nl.find_logo(image)
    assert box == nl.LogoBox(left=1270, top=749, right=1365, bottom=756)
    # the slide frame's bottom line (rows 745-747) is kept
    assert nl.crop_height(image) == 748


def test_real_slide_mark_on_its_plate_goes_with_the_plate() -> None:
    """Over content NotebookLM puts the mark on a lighter rounded plate (rows 740-765):
    the crop goes above the plate so no trace of it is left."""
    image = _real("slide_corner_plate.png", (1376, 768))
    box = nl.find_logo(image)
    assert box is not None and box.top == 749
    assert nl.crop_height(image) == 740


def test_real_infographic_mark() -> None:
    image = _real("infographic_corner.png", (1536, 2752))
    box = nl.find_logo(image)
    assert box is not None and (box.top, box.bottom) == (2724, 2738)
    assert nl.crop_height(image) == 2723


# -- NotebookLM's deck PDF and PPTX (one raster image per page/slide) -------------------


def _slides_with_mark(n: int) -> list[bytes]:
    out = []
    for i in range(n):
        image = _slide(DARK if i % 2 else LIGHT)
        _logo(image)
        out.append(_png(image))
    return out


def _pptx(pngs: list[bytes]) -> bytes:
    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(16256000), Emu(9144000)
    for png in pngs:
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        slide.shapes.add_picture(io.BytesIO(png), 0, Emu(38100), Emu(16256000), Emu(9067800))
    out = io.BytesIO()
    prs.save(out)
    return out.getvalue()


def test_images_pdf_is_one_lossless_page_per_image() -> None:
    pngs = [_png(_slide(DARK)), _png(_slide(LIGHT, size=(1376, 740)))]
    pdf = nl.images_pdf(pngs)
    reader = PdfReader(io.BytesIO(pdf))
    assert [(p.mediabox.width, p.mediabox.height) for p in reader.pages] == [
        (1376, 768),
        (1376, 740),
    ]
    page = reader.pages[1].images[0].image
    assert page.size == (1376, 740)
    assert page.convert("RGB").tobytes() == _slide(LIGHT, size=(1376, 740)).tobytes()
    assert nl.raster_pdf_pages(pdf) == 2


def test_the_deck_pdf_is_rebuilt_from_the_cropped_slides() -> None:
    original = _slides_with_mark(3)
    deck = nl.images_pdf(original)
    cropped = [nl.strip_logo(p).data for p in original]
    rebuilt = nl.rebuild_deck_pdf(deck, cropped)
    heights = [p.mediabox.height for p in PdfReader(io.BytesIO(rebuilt)).pages]
    assert heights == [_size(c)[1] for c in cropped] and all(h < 768 for h in heights)


def test_a_deck_pdf_that_is_not_one_image_per_slide_is_kept() -> None:
    deck = nl.images_pdf(_slides_with_mark(2))
    assert nl.rebuild_deck_pdf(deck, _slides_with_mark(3)) == deck  # page count differs
    assert nl.raster_pdf_pages(b"not a pdf") is None


def test_pptx_pictures_are_cropped_and_refitted() -> None:
    pptx = _pptx(_slides_with_mark(2))
    out, cropped = nl.strip_pptx(pptx, label="deck")
    assert cropped == 2
    prs = Presentation(io.BytesIO(out))
    for slide in prs.slides:
        [pic] = list(slide.shapes)
        w, h = pic.image.size
        assert h < 768
        with Image.open(io.BytesIO(pic.image.blob)) as im:
            assert nl.is_marked(im)
        # fitted inside the original picture box, centred, aspect kept
        assert pic.width == 16256000
        assert abs(pic.height - round(16256000 * h / w)) <= 1
        assert pic.top >= 38100 and pic.top + pic.height <= 38100 + 9067800 + 1
        # the replaced picture is gone from the slide's relationships
        images = [r for r in slide.part.rels.values() if "image" in r.reltype]
        assert len(images) == 1
    again, n = nl.strip_pptx(out)
    assert n == 0 and again == out


def test_a_pptx_without_the_mark_is_returned_as_is() -> None:
    pptx = _pptx([_png(_slide(DARK))])
    assert nl.strip_pptx(pptx) == (pptx, 0)


# -- the pipeline step on NotebookLM's downloads ----------------------------------------


def test_strip_notebook_logo_on_a_slide_deck() -> None:
    pngs = _slides_with_mark(2)
    blobs = [
        MediaBlob(MediaFileKind.slide_png, p, "image/png", page_index=i) for i, p in enumerate(pngs)
    ]
    blobs += [
        MediaBlob(MediaFileKind.deck_pdf, nl.images_pdf(pngs), "application/pdf"),
        MediaBlob(MediaFileKind.pptx, _pptx(pngs), "application/x"),
    ]
    out = strip_notebook_logo(blobs)
    assert [b.kind for b in out] == [b.kind for b in blobs]
    slides = [b.data for b in out[:2]]
    assert all(_size(s)[1] < 768 for s in slides)
    pdf = PdfReader(io.BytesIO(out[2].data))
    assert [p.mediabox.height for p in pdf.pages] == [_size(s)[1] for s in slides]
    prs = Presentation(io.BytesIO(out[3].data))
    assert all(next(iter(s.shapes)).image.size[1] < 768 for s in prs.slides)


def test_strip_notebook_logo_keeps_what_it_cannot_read() -> None:
    blobs = [
        MediaBlob(MediaFileKind.infographic_png, b"\x89PNG not really", "image/png"),
        MediaBlob(MediaFileKind.pptx, b"not a pptx", "application/x"),
        MediaBlob(MediaFileKind.audio_m4a, b"audio", "audio/mp4"),
    ]
    assert strip_notebook_logo(blobs) == blobs


def test_strip_notebook_logo_without_a_mark_keeps_the_deck() -> None:
    pngs = [_png(_slide(DARK))]
    deck = nl.images_pdf(pngs)
    blobs = [
        MediaBlob(MediaFileKind.slide_png, pngs[0], "image/png", page_index=0),
        MediaBlob(MediaFileKind.deck_pdf, deck, "application/pdf"),
    ]
    assert strip_notebook_logo(blobs) == blobs
