"""Rendering: content_json -> real files (.pptx, .pdf, .png, .svg).

T018 slides (pptx/png/pdf), T019 infographic (svg/png), T020 report (pdf).
"""


class RenderError(Exception):
    """A renderer could not produce its output."""
