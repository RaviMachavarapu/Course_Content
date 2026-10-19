"""Slide-deck renderer (T018): `content_json` -> `.pptx` -> deck `.pdf` -> per-slide `.png`.

Pipeline:
  1. python-pptx builds an Academic-Modernist-styled 16:9 deck (title + bullets +
     speaker notes + tag footer).
  2. `soffice --headless --convert-to pdf` rasterises it to a deck PDF.
  3. `pdftoppm -png` splits the PDF into one PNG per slide.

`soffice` / `pdftoppm` are provided by the container image (libreoffice-impress +
poppler-utils). `ensure_slide_toolchain()` is called at startup for a clear error.
"""

from __future__ import annotations

import io
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.util import Emu, Inches, Pt

from app.render import RenderError
from app.schemas.content import SlideDeckContent

_INK = RGBColor(0x1A, 0x1A, 0x1A)
_ACCENT = RGBColor(0x2B, 0x4C, 0xA8)
_MUTED = RGBColor(0x5F, 0x5F, 0x5F)
_TITLE_FONT = "DejaVu Serif"
_BODY_FONT = "DejaVu Sans"

_SUBPROCESS_TIMEOUT = 180

#: A *persistent* LibreOffice profile. The first conversion builds it (~60-90 s
#: on a cold container); every call after that reuses it and runs in ~1-2 s.
_LO_PROFILE = Path(tempfile.gettempdir()) / "sdp-libreoffice-profile"


@dataclass(frozen=True)
class RenderedSlides:
    pptx: bytes
    deck_pdf: bytes
    slide_png: list[bytes]


def _soffice() -> str:
    exe = shutil.which("soffice") or shutil.which("libreoffice")
    if exe is None:
        raise RenderError("LibreOffice (soffice) not found — slide rendering unavailable")
    return exe


def _pdftoppm() -> str:
    exe = shutil.which("pdftoppm")
    if exe is None:
        raise RenderError("pdftoppm (poppler-utils) not found — slide rendering unavailable")
    return exe


def ensure_slide_toolchain() -> None:
    """Startup probe (T018 AC). Raises `RenderError` naming what's missing."""
    _soffice()
    _pdftoppm()


def warm_up() -> None:
    """Do one throwaway render so LibreOffice builds its persistent profile now."""
    render_slides({"slides": [{"title": "warm-up", "bullets": []}]})


def build_pptx(content: SlideDeckContent) -> bytes:
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    blank = prs.slide_layouts[6]

    for slide in content.slides:
        s = prs.slides.add_slide(blank)

        bar = s.shapes.add_shape(
            MSO_SHAPE.RECTANGLE, Inches(0.7), Inches(0.55), Inches(1.6), Emu(45720)
        )
        bar.fill.solid()
        bar.fill.fore_color.rgb = _ACCENT
        bar.line.fill.background()

        title_box = s.shapes.add_textbox(Inches(0.7), Inches(0.8), Inches(12.0), Inches(1.2))
        tp = title_box.text_frame.paragraphs[0]
        tp.text = slide.title
        tp.font.size = Pt(34)
        tp.font.bold = True
        tp.font.name = _TITLE_FONT
        tp.font.color.rgb = _INK

        if slide.bullets:
            body = s.shapes.add_textbox(Inches(0.9), Inches(2.1), Inches(11.6), Inches(4.4))
            tf = body.text_frame
            tf.word_wrap = True
            for i, bullet in enumerate(slide.bullets):
                para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
                para.text = f"•  {bullet}"
                para.font.size = Pt(20)
                para.font.name = _BODY_FONT
                para.font.color.rgb = _INK
                para.space_after = Pt(10)

        if slide.tags:
            foot = s.shapes.add_textbox(Inches(0.7), Inches(6.75), Inches(12.0), Inches(0.5))
            fp = foot.text_frame.paragraphs[0]
            fp.text = "  ·  ".join(slide.tags)
            fp.font.size = Pt(12)
            fp.font.name = _BODY_FONT
            fp.font.color.rgb = _MUTED

        if slide.notes:
            s.notes_slide.notes_text_frame.text = slide.notes

    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


def _run(cmd: list[str]) -> None:
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=_SUBPROCESS_TIMEOUT)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or b"").decode("utf-8", "replace")[:400]
        raise RenderError(f"{Path(cmd[0]).name} failed: {detail}") from exc
    except subprocess.TimeoutExpired as exc:
        raise RenderError(f"{Path(cmd[0]).name} timed out") from exc


def render_slides(content_json: dict[str, object]) -> RenderedSlides:
    content = SlideDeckContent.model_validate(content_json)
    soffice = _soffice()
    pdftoppm = _pdftoppm()
    pptx_bytes = build_pptx(content)

    _LO_PROFILE.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory() as td:
        tmp = Path(td)
        deck = tmp / "deck.pptx"
        deck.write_bytes(pptx_bytes)

        _run(
            [
                soffice,
                "--headless",
                "--norestore",
                "--nolockcheck",
                f"-env:UserInstallation={_LO_PROFILE.as_uri()}",
                "--convert-to",
                "pdf",
                "--outdir",
                str(tmp),
                str(deck),
            ]
        )
        pdf = tmp / "deck.pdf"
        if not pdf.exists():
            raise RenderError("LibreOffice produced no PDF for the deck")
        pdf_bytes = pdf.read_bytes()

        _run([pdftoppm, "-png", "-r", "150", str(pdf), str(tmp / "slide")])
        pages = sorted(
            tmp.glob("slide-*.png"),
            key=lambda p: int(re.search(r"(\d+)", p.stem).group(1)),  # type: ignore[union-attr]
        )
        png_bytes = [p.read_bytes() for p in pages]

    if len(png_bytes) != len(content.slides):
        raise RenderError(
            f"rendered page count ({len(png_bytes)}) != slide count ({len(content.slides)})"
        )
    return RenderedSlides(pptx=pptx_bytes, deck_pdf=pdf_bytes, slide_png=png_bytes)
