from __future__ import annotations

from typing import Any

from app.pipeline.parsers.base import ArtifactParseError, soup, text_of, validate
from app.schemas.content import FlashcardsContent


def parse_flashcards(html: str, extras: dict[str, Any]) -> FlashcardsContent:
    doc = soup(html)
    nodes = doc.select(".card") or doc.select("[data-card]")
    if not nodes:
        raise ArtifactParseError("no .card elements found")

    cards = []
    for i, node in enumerate(nodes):
        front = text_of(node.select_one(".front, .question, dt"))
        back = text_of(node.select_one(".back, .answer, dd"))
        if not front or not back:
            raise ArtifactParseError(f"card {i + 1} is missing a front or back")
        category = node.get("data-category") or text_of(node.select_one(".category")) or None
        hint = text_of(node.select_one(".hint")) or None
        cards.append({"front": front, "back": back, "category": category, "hint": hint})

    return validate(FlashcardsContent, {"cards": cards})
