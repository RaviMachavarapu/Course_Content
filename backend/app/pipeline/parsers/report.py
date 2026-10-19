from __future__ import annotations

from typing import Any

from app.pipeline.parsers.base import ArtifactParseError, soup, text_of, validate
from app.schemas.content import ReportContent

_WORDS_PER_MINUTE = 200


def parse_report(html: str, extras: dict[str, Any]) -> ReportContent:
    doc = soup(html)
    root = doc.select_one(".studio-artifact") or doc.body or doc

    title = text_of(root.find(["h1", "h2"]))
    if not title:
        raise ArtifactParseError("report has no <h1> title")

    key_takeaways = [text_of(li) for li in root.select(".key-points li, .key-takeaways li")]

    sections: list[dict[str, str]] = []
    summary = root.select_one(".executive-summary")
    if summary is not None:
        sections.append({"heading": "Executive summary", "html": str(summary)})

    for heading in root.find_all("h2"):
        parts: list[str] = []
        for sib in heading.find_next_siblings():
            if sib.name in ("h1", "h2"):
                break
            classes = sib.get("class", []) or []
            if "key-points" in classes or "key-takeaways" in classes:
                continue
            parts.append(str(sib))
        sections.append({"heading": text_of(heading), "html": "".join(parts)})

    if not sections:
        raise ArtifactParseError("report has no sections")

    word_count = len(text_of(root).split())
    read_minutes = max(1, round(word_count / _WORDS_PER_MINUTE))

    return validate(
        ReportContent,
        {
            "title": title,
            "read_minutes": read_minutes,
            "hero_image_key": extras.get("hero_image_key"),
            "key_takeaways": key_takeaways,
            "sections": sections,
        },
    )
