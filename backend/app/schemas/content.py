"""`artifact_version.content_json` shapes (PROJECT_FRAME.md §8.2).

Parsers (T021) produce these; renderers (T018-T020) and the student API consume
them. All are strict Pydantic models so a malformed parse fails loudly.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator


# -- slide_deck ---------------------------------------------------------------
class Slide(BaseModel):
    title: str = Field(min_length=1)
    bullets: list[str] = Field(default_factory=list)
    notes: str | None = None
    tags: list[str] = Field(default_factory=list)


class SlideDeckContent(BaseModel):
    slides: list[Slide] = Field(min_length=1)


# -- flashcards -------------------------------------------------------------
class Flashcard(BaseModel):
    front: str = Field(min_length=1)
    back: str = Field(min_length=1)
    category: str | None = None
    hint: str | None = None


class FlashcardsContent(BaseModel):
    cards: list[Flashcard] = Field(min_length=1)


# -- quiz ----------------------------------------------------------------
class QuizQuestion(BaseModel):
    question: str = Field(min_length=1)
    options: list[str] = Field(min_length=4, max_length=4)
    correct_index: int = Field(ge=0, le=3)
    explanation: str = ""
    hint: str | None = None

    @field_validator("options")
    @classmethod
    def _four_non_empty(cls, v: list[str]) -> list[str]:
        if any(not opt.strip() for opt in v):
            raise ValueError("every option must be non-empty")
        return v


class QuizContent(BaseModel):
    questions: list[QuizQuestion] = Field(min_length=1)


# -- report ----------------------------------------------------------------
class ReportSection(BaseModel):
    heading: str = Field(min_length=1)
    html: str = ""


class ReportContent(BaseModel):
    title: str = Field(min_length=1)
    read_minutes: int = Field(ge=1)
    hero_image_key: str | None = None
    key_takeaways: list[str] = Field(default_factory=list)
    sections: list[ReportSection] = Field(min_length=1)


# -- infographic ---------------------------------------------------------
class InfographicContent(BaseModel):
    """Either NotebookLM's own image (owner decision 2026-10-22: stored as
    `infographic_png` media, with its alt text as `caption` and its full text
    `description`) or, for the fixture provider, a diagram we render (D15)."""

    caption: str = ""
    description: str | None = None
    diagram_kind: str | None = Field(default=None, pattern="^(mermaid|graphviz)$")
    diagram_source: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _diagram_fields_together(self) -> InfographicContent:
        if (self.diagram_kind is None) != (self.diagram_source is None):
            raise ValueError("diagram_kind and diagram_source go together")
        return self


# -- audio_overview ------------------------------------------------------
class TranscriptCue(BaseModel):
    t: float = Field(ge=0)
    text: str = Field(min_length=1)


class AudioOverviewContent(BaseModel):
    duration_seconds: int = Field(ge=1)
    voice: str | None = None
    transcript: list[TranscriptCue] = Field(default_factory=list)
