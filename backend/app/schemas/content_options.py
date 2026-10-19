"""Per-artifact-type generation options — the knobs NotebookLM's own Studio UI
exposes per content type, forwarded verbatim into `ContentProvider.generate`'s
`options` dict (already threaded to the real MCP tool call args in
`NotebookLmMcpProvider`).

Only fields confirmed in the pinned `notebooklm-mcp-server`'s own
`docs/TOOLS.md` are modeled here. NotebookLM's web UI shows a couple of
additional slide-deck controls (a "Format": Detailed deck / Presenter
slides, and a "Length": Short / Default) that are **not** documented on the
MCP tool itself — those are deliberately left out until a live session
confirms whether the API actually accepts them (see
`docs/spikes/O1-infographic.md` / `O2-audio.md` for the live-verification
pattern this follows). `FixtureProvider` ignores `options` entirely, so none
of this affects dev/CI behavior.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.models.enums import ArtifactType

Quantity = Literal["fewer", "standard", "more"]
Difficulty = Literal["easy", "medium", "hard"]
AudioFormat = Literal["deep_dive", "brief", "critique", "debate"]
AudioLength = Literal["short", "default", "long"]
Orientation = Literal["landscape", "portrait", "square"]


class SlideDeckOptions(BaseModel):
    type: Literal["slide_deck"] = "slide_deck"
    language: str = "en"


class ReportOptions(BaseModel):
    type: Literal["report"] = "report"
    language: str = "en"


class FlashcardsOptions(BaseModel):
    type: Literal["flashcards"] = "flashcards"
    quantity: Quantity = "standard"
    difficulty: Difficulty = "medium"


class QuizOptions(BaseModel):
    type: Literal["quiz"] = "quiz"
    quantity: Quantity = "standard"
    difficulty: Difficulty = "medium"


class AudioOverviewOptions(BaseModel):
    type: Literal["audio_overview"] = "audio_overview"
    format: AudioFormat = "deep_dive"
    length: AudioLength = "default"
    language: str = "en"


class InfographicOptions(BaseModel):
    type: Literal["infographic"] = "infographic"
    orientation: Orientation = "landscape"
    language: str = "en"


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
    value (e.g. an unsupported enum choice)."""
    model = _OPTIONS_MODEL_BY_TYPE[artifact_type]
    return model(**raw).model_dump(exclude={"type"})
