from __future__ import annotations

from typing import Any

from app.pipeline.parsers.base import ArtifactParseError, soup, text_of, validate
from app.schemas.content import AudioOverviewContent

#: rough spoken-word rate for synthesising cue timings when the MCP gives none
_WORDS_PER_SECOND = 2.5


def parse_audio_overview(html: str, extras: dict[str, Any]) -> AudioOverviewContent:
    doc = soup(html)
    paras = [text_of(p) for p in doc.select(".transcript p, .transcript li")]
    paras = [p for p in paras if p]
    if not paras:
        # some Studio variants return one flat blob
        blob = text_of(doc.select_one(".transcript") or doc)
        paras = [s.strip() + "." for s in blob.split(". ") if s.strip()]
    if not paras:
        raise ArtifactParseError("no transcript text found")

    cues: list[dict[str, Any]] = []
    elapsed = 0.0
    for para in paras:
        cues.append({"t": round(elapsed, 2), "text": para})
        elapsed += max(1.0, len(para.split()) / _WORDS_PER_SECOND)

    duration = int(extras.get("duration_seconds") or round(elapsed))
    return validate(
        AudioOverviewContent,
        {
            "duration_seconds": max(1, duration),
            "voice": extras.get("voice"),
            "transcript": cues,
        },
    )
