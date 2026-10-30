"""Crop NotebookLM's "Gemini Notebook" logo strip off generated images.

NotebookLM stamps a small "Gemini Notebook" mark in the bottom-right corner of every slide
image and infographic (slides 1376x768: rows ~749-756, x ~1270-1365; a 1536x2752
infographic: rows ~2725-2739, x ~1334-1525). Owner decisions 2026-10-29: crop the whole
image just above the mark (the bottom strip goes); but where NotebookLM drew the mark on
its lighter plate over the slide's content (text on the same rows), cover only the mark
with the plate's colour so no text is clipped. SynthID is not touched.

Detection (`find_logo_top`), pure Pillow: in the bottom-right corner band (the bottom
`MAX_CROP_SHARE` of the height, the right `REGION_WIDTH_SHARE` of the width) a pixel is
"ink" when its colour differs from both its row's and its column's median colour (so a
background of any colour, a gradient, and the slide's own lines running across the band are
not ink, while a short run of text is). The lowest cluster of ink rows must look like the
mark: flush right (a small right margin), a short wide strip of text, a little above the
bottom edge, with clean rows below it. Anything else is "no logo": the image is left
unchanged (logged).

`strip_logo` crops one PNG; `strip_logo_from_media` applies it to a version's media
(slide PNGs, the infographic PNG) and rebuilds NotebookLM's own deck PDF and PPTX, whose
pages/slides are just those raster images, from the cropped pictures.
"""

from __future__ import annotations

import io
import re
from collections.abc import Sequence
from dataclasses import dataclass

from PIL import Image
from PIL.PngImagePlugin import PngInfo
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pypdf import PdfReader

from app.logging import get_logger

log = get_logger("render.notebook_logo")

#: never crop more than this share of the image height
MAX_CROP_SHARE = 0.05
#: the corner band searched: the right share of the width
REGION_WIDTH_SHARE = 0.2
#: a channel difference that counts as ink (0-255)
INK_DIFF = 48
#: a fainter difference that still belongs to the mark's anti-aliased top edge
EDGE_DIFF = 16


@dataclass(frozen=True)
class LogoBox:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def height(self) -> int:
        return self.bottom - self.top + 1

    @property
    def width(self) -> int:
        return self.right - self.left + 1


def _pixels(region: Image.Image) -> list[tuple[int, int, int]]:
    data = region.tobytes()
    return [(data[i], data[i + 1], data[i + 2]) for i in range(0, len(data), 3)]


def _median(values: list[int]) -> int:
    s = sorted(values)
    return s[len(s) // 2]


def _ink_mask(pixels: list[tuple[int, int, int]], w: int, h: int, diff: int) -> list[list[bool]]:
    """`h` rows of `w` flags: the pixel differs (max channel) from its row's and its
    column's median colour by more than `diff`."""
    rows = [pixels[y * w : (y + 1) * w] for y in range(h)]
    row_med = [tuple(_median([p[c] for p in row]) for c in range(3)) for row in rows]
    col_med = [
        tuple(_median([rows[y][x][c] for y in range(h)]) for c in range(3)) for x in range(w)
    ]

    def far(p: tuple[int, int, int], m: tuple[int, ...]) -> bool:
        return max(abs(p[0] - m[0]), abs(p[1] - m[1]), abs(p[2] - m[2])) > diff

    return [
        [far(rows[y][x], row_med[y]) and far(rows[y][x], col_med[x]) for x in range(w)]
        for y in range(h)
    ]


def find_logo(image: Image.Image) -> LogoBox | None:
    """The mark's bounding box (full-image coordinates), or None when the corner holds
    nothing shaped like it."""
    width, height = image.size
    band_h = max(8, int(height * MAX_CROP_SHARE))
    band_w = max(16, int(width * REGION_WIDTH_SHARE))
    if band_h >= height or band_w >= width:
        return None
    x0, y0 = width - band_w, height - band_h
    region = image.convert("RGB").crop((x0, y0, width, height))
    mask = _ink_mask(_pixels(region), band_w, band_h, INK_DIFF)

    # the lowest cluster of ink rows: grown upwards while each row's ink stays within the
    # cluster's columns (the slide's own content above the mark is not part of it); one
    # blank row is allowed inside the mark (an i-dot at a larger scale)
    def extent(y: int) -> tuple[int, int] | None:
        xs = [x for x in range(band_w) if mask[y][x]]
        return (xs[0], xs[-1]) if len(xs) >= 2 else None

    bottom = next((y for y in range(band_h - 1, -1, -1) if extent(y)), None)
    if bottom is None:
        return None
    first = extent(bottom)
    assert first is not None
    left, right = first
    tol = max(2, width // 200)
    top, y = bottom, bottom - 1
    while y >= 0:
        span = extent(y)
        if span is None:
            above = extent(y - 1) if y > 0 else None
            if above is None or not (left - tol <= above[0] and above[1] <= right + tol):
                break
            y -= 1
            continue
        if top == bottom or (left - tol <= span[0] and span[1] <= right + tol):
            top, left, right = y, min(left, span[0]), max(right, span[1])
            y -= 1
            continue
        break
    if y < 0:  # the ink reaches the top of the band: content, not a small mark
        return None
    ink = sum(sum(mask[yy][left : right + 1]) for yy in range(top, bottom + 1))
    box = LogoBox(left=x0 + left, top=y0 + top, right=x0 + right, bottom=y0 + bottom)
    if not _looks_like_logo(box, ink, width, height):
        return None
    return _refine_top(box, x0, y0, band_w, band_h, region)


def _looks_like_logo(box: LogoBox, ink: int, width: int, height: int) -> bool:
    right_margin = width - 1 - box.right
    bottom_margin = height - 1 - box.bottom
    return (
        right_margin <= max(6, int(width * 0.03))
        and 0.02 * width <= box.width <= 0.25 * width
        and 3 <= box.height <= max(6, int(height * 0.03))
        and 0.03 <= box.height / box.width <= 0.3
        and 1 <= bottom_margin <= max(4, int(height * 0.03))
        and 0.08 <= ink / (box.width * box.height) <= 0.9
    )


def _refine_top(
    box: LogoBox,
    x0: int,
    y0: int,
    band_w: int,
    band_h: int,
    region: Image.Image,
) -> LogoBox:
    """Move the top up over the mark's faint anti-aliased edge (at most 2 rows)."""
    faint = _ink_mask(_pixels(region), band_w, band_h, EDGE_DIFF)
    top = box.top - y0
    for _ in range(2):
        row = top - 1
        if row < 0 or not any(faint[row][box.left - x0 : box.right - x0 + 1]):
            break
        top = row
    return LogoBox(box.left, y0 + top, box.right, box.bottom)


#: a row belongs to the mark's backing plate when this share of its pixels (over the mark's
#: columns) is within PLATE_DIFF of the row below it
PLATE_SHARE = 0.8
PLATE_DIFF = 16


def plate_top(image: Image.Image, box: LogoBox) -> int:
    """The top row of the rounded plate NotebookLM puts behind the mark when it sits over
    content (slides: ~9 rows above an 8-row mark, a slightly lighter shade), else
    `box.top - 1`. Walks up from the row above the mark while each row is uniform with
    the row below it (over the mark's columns), for at most 1.5 mark heights + 2 rows; when
    no edge is found within that (a plain or slowly shaded background) there is no plate."""
    rgb = image.convert("RGB")
    px = rgb.load()
    assert px is not None
    cols = range(box.left, box.right + 1)
    cap = int(box.height * 1.5) + 2

    def row(y: int) -> list[tuple[int, int, int]]:
        return [px[x, y] for x in cols]  # type: ignore[misc]

    def median(colors: list[tuple[int, int, int]]) -> tuple[int, int, int]:
        return (
            _median([c[0] for c in colors]),
            _median([c[1] for c in colors]),
            _median([c[2] for c in colors]),
        )

    start = box.top - 1
    if start <= 0:
        return box.top
    ref = median(row(start))
    y = start - 1
    while y >= 0 and start - y <= cap:
        colors = row(y)
        near = sum(1 for c in colors if max(abs(c[i] - ref[i]) for i in range(3)) <= PLATE_DIFF)
        if near < PLATE_SHARE * len(colors):
            return y + 1 if y + 1 < start else start
        ref = median(colors)
        y -= 1
    return start  # no edge within reach: no plate


def crop_height(image: Image.Image) -> int | None:
    """The height to crop the image to (the rows above the mark), or None when no mark is
    found or the crop would take more than `MAX_CROP_SHARE`."""
    box = find_logo(image)
    if box is None:
        return None
    keep = box.top - 1
    if image.size[1] - keep > image.size[1] * MAX_CROP_SHARE + 1 or keep <= 0:
        return None
    return keep


#: PNG text chunk marking an image this module already cropped (re-runs skip it)
MARK_KEY = "shikshak-notebook-logo"
MARK_VALUE = "cropped"  # also set on a covered image


def is_marked(image: Image.Image) -> bool:
    return getattr(image, "text", {}).get(MARK_KEY) == MARK_VALUE


def _png(image: Image.Image) -> bytes:
    info = PngInfo()
    info.add_text(MARK_KEY, MARK_VALUE)
    out = io.BytesIO()
    image.save(out, "PNG", pnginfo=info)
    return out.getvalue()


@dataclass(frozen=True)
class Stripped:
    data: bytes
    #: rows removed from the bottom (0: not cropped)
    cropped: int
    size: tuple[int, int]
    #: already cleaned by an earlier run (marked): unchanged
    already: bool = False
    #: the mark sat on its plate over content: covered with the plate's colour, not cropped
    covered: bool = False

    @property
    def changed(self) -> bool:
        return self.cropped > 0 or self.covered


def plate_min_rows(box: LogoBox) -> int:
    """A plate is a band of this many uniform rows above the mark (NotebookLM's: ~9 over an
    8-row mark); a slide's own line a few rows above the mark is not one."""
    return max(4, box.height // 2)


def _area_color(
    px: object, xs: range, ys: range, size: tuple[int, int]
) -> tuple[int, int, int] | None:
    """The median colour of the pixels in columns `xs` x rows `ys` (clipped to the image);
    None when that is empty."""
    w, h = size
    colors = [
        px[x, y]  # type: ignore[index]
        for y in ys
        if 0 <= y < h
        for x in xs
        if 0 <= x < w
    ]
    if not colors:
        return None
    return (
        _median([c[0] for c in colors]),
        _median([c[1] for c in colors]),
        _median([c[2] for c in colors]),
    )


def _near(a: tuple[int, int, int], b: tuple[int, int, int]) -> bool:
    return max(abs(a[i] - b[i]) for i in range(3)) <= PLATE_DIFF


def is_plate(image: Image.Image, box: LogoBox, plate: int) -> bool:
    """Whether rows `plate`..`box.top - 1` are NotebookLM's plate behind the mark, not just
    the background below a slide's footer line or text (PR #2 review finding 4). The plate
    (slides: a lighter rounded band from ~9 rows above the mark to ~9 below, a few pixels
    wider than the mark) must:
    - be at least `plate_min_rows` high above the mark (and at most the walk's reach);
    - differ from the background just above it (a band of about the mark's height, over the
      mark's columns, above the plate's top edge): a footer line over a plain background
      has the same colour on both sides;
    - continue below the mark (its bottom padding) and to the left of the mark's columns
      (the plate is wider than the mark)."""
    above = box.top - plate
    if above < plate_min_rows(box) or above > int(box.height * 1.5) + 2:
        return False
    rgb = image.convert("RGB")
    px = rgb.load()
    assert px is not None
    size = rgb.size
    cols = range(box.left, box.right + 1)
    shade = _area_color(px, cols, range(plate, box.top), size)
    # skip the plate's edge row (anti-aliased); a line of the slide's own a row or two
    # thick is a minority of this band, so its median is the background
    background = _area_color(px, cols, range(plate - 2 - box.height, plate - 1), size)
    pad = max(2, box.height // 4)
    below = _area_color(px, cols, range(box.bottom + 2, box.bottom + 2 + pad), size)
    left = _area_color(
        px, range(box.left - 2 - pad, box.left - 2), range(box.top, box.bottom + 1), size
    )
    if shade is None or background is None or below is None or left is None:
        return False
    return not _near(shade, background) and _near(shade, below) and _near(shade, left)


#: margin (px) around the mark's box that is covered with the plate's colour
COVER_PAD = 2


def cover_logo(image: Image.Image, box: LogoBox, plate: int) -> Image.Image:
    """`image` with the mark's box (plus `COVER_PAD`) filled with the plate's colour (the
    median of the plate's rows above the mark, over the mark's columns)."""
    rgb = image.convert("RGB")
    px = rgb.load()
    assert px is not None
    shades = [px[x, y] for y in range(plate, box.top) for x in range(box.left, box.right + 1)]
    color = tuple(_median([c[i] for c in shades]) for i in range(3))  # type: ignore[index]
    w, h = rgb.size
    left, top = max(0, box.left - COVER_PAD), max(0, box.top - COVER_PAD)
    right, bottom = min(w - 1, box.right + COVER_PAD), min(h - 1, box.bottom + COVER_PAD)
    rgb.paste(color, (left, top, right + 1, bottom + 1))
    return rgb


def strip_logo(png: bytes, *, label: str = "") -> Stripped:
    """`png` with the mark removed (and marked, so a later run leaves it alone): the bottom
    strip holding it is cropped off; but when the mark sits on its plate over content (the
    slide's text runs on the same rows, so a crop would clip it) only the mark is covered
    with the plate's colour (owner decision 2026-10-29). Unchanged (logged) when no mark is
    found or it was cleaned before."""
    with Image.open(io.BytesIO(png)) as im:
        im.load()
        if is_marked(im):
            return Stripped(png, 0, im.size, already=True)
        box = find_logo(im)
        if box is not None:
            plate = plate_top(im, box)
            if is_plate(im, box, plate):
                covered = cover_logo(im, box, plate)
                log.info("notebook_logo.covered", image=label, rows=f"{box.top}-{box.bottom}")
                return Stripped(_png(covered), 0, covered.size, covered=True)
        keep = crop_height(im)
        if keep is None:
            log.info("notebook_logo.not_found", image=label, size=f"{im.size[0]}x{im.size[1]}")
            return Stripped(png, 0, im.size)
        cropped = im.crop((0, 0, im.size[0], keep))
        log.info("notebook_logo.cropped", image=label, rows=im.size[1] - keep)
        return Stripped(_png(cropped), im.size[1] - keep, cropped.size)


# -- NotebookLM's deck PDF and PPTX: raster pages/slides --------------------------------


def _png_idat(rgb: Image.Image) -> bytes:
    """The zlib stream of `rgb` encoded as a PNG (filtered scanlines): embedded in a PDF as
    FlateDecode with PNG predictors, it is lossless and about PNG-sized."""
    buf = io.BytesIO()
    rgb.save(buf, "PNG", compress_level=6)
    data = buf.getvalue()
    pos, idat = 8, bytearray()
    while pos < len(data):
        length = int.from_bytes(data[pos : pos + 4], "big")
        kind = data[pos + 4 : pos + 8]
        if kind == b"IDAT":
            idat += data[pos + 8 : pos + 8 + length]
        pos += 12 + length
    return bytes(idat)


def images_pdf(pngs: Sequence[bytes]) -> bytes:
    """A PDF with one page per image, each page the image's size in pixels (as NotebookLM's
    deck PDF: 1 px = 1 pt), lossless (Flate, RGB)."""
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    catalog = add(b"")  # filled in below
    pages = add(b"")
    kids: list[int] = []
    for i, png in enumerate(pngs):
        with Image.open(io.BytesIO(png)) as im:
            rgb = im.convert("RGB")
            w, h = rgb.size
            data = _png_idat(rgb)
        img = add(
            b"<< /Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace /DeviceRGB "
            b"/BitsPerComponent 8 /Filter /FlateDecode "
            b"/DecodeParms << /Predictor 15 /Colors 3 /BitsPerComponent 8 /Columns %d >> "
            b"/Length %d >>\nstream\n%s\nendstream" % (w, h, w, len(data), data)
        )
        content = b"q\n%d 0 0 %d 0 0 cm\n/Im%d Do\nQ\n" % (w, h, i)
        stream = add(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(content), content))
        kids.append(
            add(
                b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %d %d] "
                b"/Resources << /XObject << /Im%d %d 0 R >> >> /Contents %d 0 R >>"
                % (pages, w, h, i, img, stream)
            )
        )
    objects[catalog - 1] = b"<< /Type /Catalog /Pages %d 0 R >>" % pages
    objects[pages - 1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (
        b" ".join(b"%d 0 R" % k for k in kids),
        len(kids),
    )
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for n, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n%s\nendobj\n" % (n, body))
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1))
    for off in offsets:
        out.write(b"%010d 00000 n \n" % off)
    out.write(
        b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n"
        % (len(objects) + 1, catalog, xref)
    )
    return out.getvalue()


_DRAW_IMAGE_RE = re.compile(rb"^\s*q\s+[\d.]+\s+0\s+0\s+[\d.]+\s+0\s+0\s+cm\s+/\S+\s+Do\s+Q\s*$")


def raster_pdf_pages(pdf: bytes) -> int | None:
    """The page count when every page of `pdf` is exactly one full-page image (NotebookLM's
    deck PDF: `q W 0 0 H 0 0 cm /Im1 Do Q`), else None (text, vector content, or unreadable:
    such a PDF is not rebuilt from images)."""
    try:
        reader = PdfReader(io.BytesIO(pdf))
        for page in reader.pages:
            contents = page.get_contents()
            if contents is None or len(page.images) != 1:
                return None
            if not _DRAW_IMAGE_RE.match(contents.get_data()):
                return None
        return len(reader.pages)
    except Exception:  # pypdf raises many error types on damaged input
        return None


def rebuild_deck_pdf(pdf: bytes, slide_pngs: Sequence[bytes], *, label: str = "") -> bytes:
    """NotebookLM's deck PDF rebuilt from the (cropped) slide images when its pages are just
    those images, one per slide; otherwise `pdf` unchanged (logged)."""
    pages = raster_pdf_pages(pdf)
    if pages is None or pages != len(slide_pngs):
        log.warning(
            "notebook_logo.deck_pdf_kept",
            pdf=label,
            reason="pages are not one image per slide" if pages is None else "page count",
            pages=pages,
            slides=len(slide_pngs),
        )
        return pdf
    return images_pdf(slide_pngs)


def strip_pptx(pptx: bytes, *, label: str = "") -> tuple[bytes, int]:
    """NotebookLM's PPTX (each slide one full-slide picture) with the mark cropped off every
    picture that carries it; a cropped picture is refitted, centred, inside the box the
    original occupied (aspect kept). Returns (pptx, pictures cropped); `pptx` unchanged when
    none was."""
    prs = Presentation(io.BytesIO(pptx))
    cropped = 0
    for number, slide in enumerate(prs.slides, start=1):
        for shape in list(slide.shapes):
            if shape.shape_type != MSO_SHAPE_TYPE.PICTURE:
                continue
            try:
                result = strip_logo(shape.image.blob, label=f"{label} slide {number}")
            except Exception as exc:  # an unreadable picture: leave it
                log.warning("notebook_logo.picture_unreadable", pptx=label, error=str(exc))
                continue
            if not result.changed:
                continue
            element = shape._element
            old_rid = element.blip_rId
            _part, rid = slide.part.get_or_add_image_part(io.BytesIO(result.data))
            element.blipFill.blip.rEmbed = rid
            if old_rid and old_rid != rid:
                slide.part.drop_rel(old_rid)
            box_left, box_top = int(shape.left or 0), int(shape.top or 0)
            box_w, box_h = int(shape.width or 0), int(shape.height or 0)
            img_w, img_h = result.size
            if box_w and box_h:
                scale = min(box_w / img_w, box_h / img_h)
                new_w, new_h = round(img_w * scale), round(img_h * scale)
                shape.left = box_left + (box_w - new_w) // 2
                shape.top = box_top + (box_h - new_h) // 2
                shape.width, shape.height = new_w, new_h
            cropped += 1
    if not cropped:
        return pptx, 0
    out = io.BytesIO()
    prs.save(out)
    return out.getvalue(), cropped
