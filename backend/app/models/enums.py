"""Enumerations shared across the domain model (PROJECT_FRAME.md §8.1)."""

from __future__ import annotations

import enum


class _StrEnum(str, enum.Enum):
    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return str(self.value)


class ArtifactType(_StrEnum):
    slide_deck = "slide_deck"
    flashcards = "flashcards"
    quiz = "quiz"
    report = "report"
    infographic = "infographic"
    audio_overview = "audio_overview"


#: The six types every module always carries (BR1), in canonical display order.
ARTIFACT_TYPES: tuple[ArtifactType, ...] = tuple(ArtifactType)


class ArtifactStatus(_StrEnum):
    pending = "pending"  # row exists, nothing generated yet
    processing = "processing"  # a generation/redo job is running
    ready = "ready"  # generated + parsed, awaiting review/publish
    error = "error"  # generation or parsing failed
    published = "published"  # visible to students (BR2/BR3)
    #: NotebookLM drafted a slide outline and waits for the admin to refine
    #: it or proceed ("Review slide outline"); not publishable.
    outline_review = "outline_review"


class ModuleStatus(_StrEnum):
    processing = "processing"
    pending_review = "pending_review"
    partially_published = "partially_published"
    published = "published"
    error = "error"


class CourseStatus(_StrEnum):
    draft = "draft"
    processing = "processing"
    pending_review = "pending_review"
    partially_published = "partially_published"
    published = "published"
    error = "error"


class ModuleSourceType(_StrEnum):
    youtube = "youtube"
    web = "web"
    drive = "drive"
    pdf = "pdf"


class GenerationJobKind(_StrEnum):
    generate_module = "generate_module"
    generate_artifact = "generate_artifact"
    redo_artifact = "redo_artifact"


class GenerationJobState(_StrEnum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


class MediaFileKind(_StrEnum):
    pptx = "pptx"
    slide_png = "slide_png"
    deck_pdf = "deck_pdf"
    report_pdf = "report_pdf"
    infographic_png = "infographic_png"
    infographic_svg = "infographic_svg"
    audio_mp3 = "audio_mp3"
    #: NotebookLM's Audio Overview download is audio/mp4 (AAC), not mp3.
    audio_m4a = "audio_m4a"
    cover = "cover"
    hero = "hero"
    #: typeset (Quarto) PDFs of the artifact's content; `report_pdf` is the report's.
    flashcards_pdf = "flashcards_pdf"
    quiz_pdf = "quiz_pdf"
    infographic_pdf = "infographic_pdf"
    slides_handout_pdf = "slides_handout_pdf"


class FlashcardRatingValue(_StrEnum):
    hard = "hard"
    good = "good"
    easy = "easy"


class SourceUploadStatus(_StrEnum):
    receiving = "receiving"
    complete = "complete"
    claimed = "claimed"
