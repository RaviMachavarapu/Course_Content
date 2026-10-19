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


class ProviderError(Exception):
    """A content provider failed a call."""


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

    def health(self) -> ProviderHealth: ...

    def refresh_auth(self) -> None: ...
