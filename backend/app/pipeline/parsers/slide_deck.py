from __future__ import annotations

from typing import Any

from app.pipeline.parsers.base import ArtifactParseError, soup, text_of, validate
from app.schemas.content import SlideDeckContent


def parse_slide_deck(html: str, extras: dict[str, Any]) -> SlideDeckContent:
    doc = soup(html)
    sections = doc.select("section.slide") or doc.find_all("section")
    if not sections:
        raise ArtifactParseError("no <section> slides found")

    slides = []
    for i, section in enumerate(sections):
        heading = section.find(["h1", "h2", "h3"])
        title = text_of(heading)
        if not title:
            raise ArtifactParseError(f"slide {i + 1} has no title heading")
        bullets = [text_of(li) for li in section.select("li") if text_of(li)]
        notes_el = section.select_one(".notes, aside")
        tags = [t.strip() for t in (section.get("data-tags") or "").split(",") if t.strip()]
        slides.append(
            {
                "title": title,
                "bullets": bullets,
                "notes": text_of(notes_el) or None,
                "tags": tags,
            }
        )

    return validate(SlideDeckContent, {"slides": slides})
