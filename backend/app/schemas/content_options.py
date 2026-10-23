"""Per-artifact-type generation options — exactly the controls NotebookLM's own
Studio dialogs offer on the connected account, recorded live on 2026-10-22
(docs/spikes/notebooklm-2026-10-capture.md). Values are forwarded to the MCP
shim, which maps them to NotebookLM's request codes (`mcp/shim/studio.js`).

Not modelled because this account's dialogs don't offer them: quiz "Include
images" and "Question types". `FixtureProvider` ignores options entirely.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

from app.models.enums import ArtifactType

#: Owner decision 2026-10-20: English plus Hindi, Telugu, Tamil, Kannada,
#: Marathi. All six were sent and accepted in the live capture.
Language = Literal["en", "hi", "te", "ta", "kn", "mr"]
Quantity = Literal["fewer", "standard", "more"]
Difficulty = Literal["easy", "medium", "hard"]
AudioFormat = Literal["deep_dive", "brief", "critique", "debate"]
AudioLength = Literal["short", "default", "long"]
SlideFormat = Literal["detailed", "presenter"]
SlideLength = Literal["short", "default"]
ReportFormat = Literal["interactive", "document"]
ReportTemplate = Literal["briefing_doc", "study_guide", "blog_post", "custom"]
Images = Literal["include", "text_only"]
Orientation = Literal["landscape", "portrait", "square"]
Detail = Literal["concise", "standard", "detailed"]
VisualStyle = Literal[
    "auto",
    "sketch_note",
    "professional",
    "bento_grid",
    "editorial",
    "instructional",
    "bricks",
    "clay",
    "anime",
    "kawaii",
    "scientific",
]


class AudioOverviewOptions(BaseModel):
    type: Literal["audio_overview"] = "audio_overview"
    format: AudioFormat = "deep_dive"
    length: AudioLength = "default"
    language: Language = "en"

    @model_validator(mode="after")
    def _length_offered_for_format(self) -> AudioOverviewOptions:
        # NotebookLM: Brief has no length control; Critique and Debate offer
        # Short and Default only.
        if self.format == "brief":
            self.length = "default"
        elif self.format != "deep_dive" and self.length == "long":
            raise ValueError(f'length "long" is not offered for the {self.format} format')
        return self


class SlideDeckOptions(BaseModel):
    type: Literal["slide_deck"] = "slide_deck"
    format: SlideFormat = "detailed"
    length: SlideLength = "default"
    language: Language = "en"
    #: NotebookLM drafts an outline and waits for review before building.
    review_outline: bool = False


class ReportOptions(BaseModel):
    type: Literal["report"] = "report"
    format: ReportFormat = "interactive"
    #: Document reports only; "custom" sends the artifact's focus text.
    template: ReportTemplate | None = None
    language: Language = "en"

    @model_validator(mode="after")
    def _template_matches_format(self) -> ReportOptions:
        if self.format == "document" and self.template is None:
            raise ValueError("a document report needs a template")
        if self.format == "interactive":
            self.template = None
        # NotebookLM offers a language choice only for "Create your own".
        if self.template != "custom" and self.language != "en":
            raise ValueError('report language can only be chosen for the "custom" template')
        return self


class FlashcardsOptions(BaseModel):
    type: Literal["flashcards"] = "flashcards"
    quantity: Quantity = "standard"
    difficulty: Difficulty = "medium"
    images: Images = "include"
    language: Language = "en"


class QuizOptions(BaseModel):
    type: Literal["quiz"] = "quiz"
    quantity: Quantity = "standard"
    difficulty: Difficulty = "medium"
    language: Language = "en"


class InfographicOptions(BaseModel):
    type: Literal["infographic"] = "infographic"
    language: Language = "en"
    orientation: Orientation = "landscape"
    detail: Detail = "standard"
    style: VisualStyle = "auto"


ArtifactOptions = Annotated[
    SlideDeckOptions
    | ReportOptions
    | FlashcardsOptions
    | QuizOptions
    | AudioOverviewOptions
    | InfographicOptions,
    Field(discriminator="type"),
]

_OPTIONS_MODEL_BY_TYPE: dict[ArtifactType, type[BaseModel]] = {
    ArtifactType.slide_deck: SlideDeckOptions,
    ArtifactType.report: ReportOptions,
    ArtifactType.flashcards: FlashcardsOptions,
    ArtifactType.quiz: QuizOptions,
    ArtifactType.audio_overview: AudioOverviewOptions,
    ArtifactType.infographic: InfographicOptions,
}


def default_options(artifact_type: ArtifactType) -> dict[str, object]:
    """The default option set for a type, as a plain dict ready to store /
    pass to `ContentProvider.generate`."""
    model = _OPTIONS_MODEL_BY_TYPE[artifact_type]
    return model().model_dump(exclude={"type"})


def validate_options(artifact_type: ArtifactType, raw: dict[str, object]) -> dict[str, object]:
    """Validate a raw options dict against the type's schema, filling in
    defaults for anything missing. Raises `pydantic.ValidationError` on a bad
    value (e.g. an unsupported enum choice or a combination NotebookLM doesn't
    offer)."""
    model = _OPTIONS_MODEL_BY_TYPE[artifact_type]
    return model(**raw).model_dump(exclude={"type"})
