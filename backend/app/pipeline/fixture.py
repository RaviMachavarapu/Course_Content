"""`FixtureProvider` — a deterministic `ContentProvider` backed by canned files.

Used for every dev run and all of CI (`CONTENT_PROVIDER=fixture`, the default),
so the whole pipeline is exercisable without a Google account or the MCP
container. Generation is instant: `poll` always returns `ready`.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import Any

from app.models.enums import ArtifactType
from app.pipeline.provider import (
    NotebookRef,
    ProviderHealth,
    RawArtifact,
    SourceRef,
    StudioJobRef,
    StudioStatus,
)

_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
DEFAULT_FIXTURE_ID = "sample-neural-nets"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "untitled"


class FixtureProvider:
    def __init__(
        self,
        fixture_id: str = DEFAULT_FIXTURE_ID,
        *,
        fixtures_dir: Path | None = None,
    ) -> None:
        self.fixture_id = fixture_id
        self._dir = (fixtures_dir or _FIXTURES_DIR) / fixture_id
        if not self._dir.is_dir():
            raise FileNotFoundError(f"fixture set not found: {self._dir}")

    # -- ContentProvider ---------------------------------------------------

    def create_notebook(self, title: str) -> NotebookRef:
        return NotebookRef(notebook_id=f"fixture-nb-{_slug(title)}")

    def add_source(self, nb: NotebookRef, url: str) -> SourceRef:
        return SourceRef(source_id=f"fixture-src-{_slug(url)[:40]}")

    def generate(
        self,
        nb: NotebookRef,
        kind: ArtifactType,
        focus_prompt: str,
        options: dict[str, Any],
    ) -> StudioJobRef:
        return StudioJobRef(
            job_id=f"fixture-job-{nb.notebook_id}-{kind.value}",
            notebook_id=nb.notebook_id,
            kind=kind,
        )

    def poll(self, job: StudioJobRef) -> StudioStatus:
        return StudioStatus.ready

    def fetch_content(self, job: StudioJobRef) -> RawArtifact:
        html = self._read_text(f"{job.kind.value}.html")
        extras: dict[str, Any] = {"artifact_id": job.job_id}
        if job.kind is ArtifactType.infographic:
            extras["mind_map_tree"] = json.loads(self._read_text("infographic.mind_map.json"))
        return RawArtifact(html=html, extras=extras)

    def fetch_binary(self, job: StudioJobRef, kind: ArtifactType) -> bytes | None:
        if kind is ArtifactType.audio_overview:
            return (self._dir / "audio_overview.mp3").read_bytes()
        # Infographic image is rendered by us from structure (D15); nothing to fetch.
        return None

    def health(self) -> ProviderHealth:
        return ProviderHealth(
            healthy=True,
            account_email="fixture@localhost",
            last_ok_at=dt.datetime.now(tz=dt.UTC),
            detail=f"FixtureProvider[{self.fixture_id}]",
        )

    def refresh_auth(self) -> None:
        return None

    # -- helpers ---------------------------------------------------------

    def _read_text(self, name: str) -> str:
        path = self._dir / name
        if not path.is_file():
            raise FileNotFoundError(f"fixture file missing: {path}")
        return path.read_text(encoding="utf-8")
