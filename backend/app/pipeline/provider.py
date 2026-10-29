"""`ContentProvider` — the stable seam between the orchestrator and whatever is
actually generating content (live NotebookLM via MCP, or the fixture set).

Interface per plan.md §4.2. The MCP tool mapping lives in
`app/pipeline/notebooklm_mcp.py` (T016); the deterministic stand-in used for all
dev and CI is `app/pipeline/fixture.py`.
"""

from __future__ import annotations

import datetime as dt
import enum
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from app.models.enums import ArtifactType


@dataclass(frozen=True)
class NotebookRef:
    notebook_id: str


@dataclass(frozen=True)
class SourceRef:
    source_id: str


@dataclass(frozen=True)
class StudioJobRef:
    job_id: str
    notebook_id: str
    kind: ArtifactType


class StudioStatus(str, enum.Enum):
    pending = "pending"
    ready = "ready"
    failed = "failed"
    #: a slide outline is drafted and waits for review ("Review slide outline")
    awaiting_review = "awaiting_review"
    #: NotebookLM no longer knows the artifact (deleted, or its notebook is gone)
    missing = "missing"


class SourceState(str, enum.Enum):
    pending = "pending"
    ready = "ready"
    failed = "failed"


class ProviderError(Exception):
    """A content provider failed a call."""


class ProviderAuthError(ProviderError):
    """The NotebookLM Google session needs signing in again."""


class TransientProviderError(ProviderError):
    """A provider failure that is worth retrying (timeout, 5xx, locked session)."""


class GenerationTimeout(ProviderError):
    """A Studio job did not reach a terminal state within its deadline."""


@dataclass(frozen=True)
class RawArtifact:
    """What the provider hands back for a finished generation.

    `html` is the raw Studio markup the type-specific parser (T021) consumes.
    `extras` carries anything else the provider exposes — e.g. NotebookLM's
    `artifact_id` and `mind_map_tree`.
    """

    html: str
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderHealth:
    healthy: bool
    account_email: str | None
    last_ok_at: dt.datetime | None
    detail: str


@runtime_checkable
class ContentProvider(Protocol):
    def create_notebook(self, title: str) -> NotebookRef: ...

    def add_source(self, nb: NotebookRef, url: str) -> SourceRef: ...

    def add_file_source(self, nb: NotebookRef, path: str, display_name: str) -> SourceRef:
        """Upload a local file (absolute path, same in the mcp container) as a source."""
        ...

    def source_statuses(self, nb: NotebookRef) -> dict[str, SourceState]:
        """Processing state of every source in the notebook, by source id."""
        ...

    def generate(
        self,
        nb: NotebookRef,
        kind: ArtifactType,
        focus_prompt: str,
        options: dict[str, Any],
    ) -> StudioJobRef: ...

    def poll(self, job: StudioJobRef) -> StudioStatus: ...

    def fetch_content(self, job: StudioJobRef) -> RawArtifact: ...

    def fetch_binary(self, job: StudioJobRef, kind: ArtifactType) -> bytes | None: ...

    def download(self, url: str) -> tuple[bytes, str]:
        """Fetch a media URL the provider returned; (data, content type)."""
        ...

    def outline_action(self, job: StudioJobRef, feedback: str | None) -> None:
        """Revise a drafted slide outline (feedback) or build the deck (None)."""
        ...

    def query(self, nb: NotebookRef, text: str) -> str:
        """Ask the notebook's chat a question; the answer text (may wrap JSON in prose)."""
        ...

    def delete_notebook(self, nb: NotebookRef) -> None:
        """Delete a notebook for good (its sources and Studio artifacts too)."""
        ...

    def health(self) -> ProviderHealth: ...

    def refresh_auth(self) -> None: ...
