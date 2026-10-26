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
    ProviderError,
    ProviderHealth,
    RawArtifact,
    SourceRef,
    SourceState,
    StudioJobRef,
    StudioStatus,
)

_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
DEFAULT_FIXTURE_ID = "sample-neural-nets"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "untitled"


class _FixtureStates(dict[str, SourceState]):
    """Source states where any `fixture-` id counts as ready.

    Each job builds a fresh `FixtureProvider`, so a resumed run must still see
    ids an earlier instance handed out.
    """

    def get(self, key: str, default: Any = None) -> Any:
        if key in self:
            return self[key]
        return SourceState.ready if key.startswith("fixture-") else default


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
        #: calls tests may assert on, e.g. ("add_file_source", notebook_id, path, name)
        self.calls: list[tuple[Any, ...]] = []
        self._source_ids: dict[str, list[str]] = {}

    # -- ContentProvider ---------------------------------------------------

    def create_notebook(self, title: str) -> NotebookRef:
        return NotebookRef(notebook_id=f"fixture-nb-{_slug(title)}")

    def add_source(self, nb: NotebookRef, url: str) -> SourceRef:
        ref = SourceRef(source_id=f"fixture-src-{_slug(url)[:40]}")
        self._remember(nb, ref)
        return ref

    def add_file_source(self, nb: NotebookRef, path: str, display_name: str) -> SourceRef:
        self.calls.append(("add_file_source", nb.notebook_id, path, display_name))
        ref = SourceRef(source_id=f"fixture-file-{_slug(display_name)}")
        self._remember(nb, ref)
        return ref

    def source_statuses(self, nb: NotebookRef) -> dict[str, SourceState]:
        return _FixtureStates(
            {sid: SourceState.ready for sid in self._source_ids.get(nb.notebook_id, [])}
        )

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

    def download(self, url: str) -> tuple[bytes, str]:
        # Fixture content is self-contained; it never hands out media URLs.
        raise ProviderError(f"FixtureProvider has no remote media ({url})")

    def outline_action(self, job: StudioJobRef, feedback: str | None) -> None:
        # Fixture generations finish immediately; they never wait for an outline.
        raise ProviderError("FixtureProvider has no slide outline to review")

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

    def _remember(self, nb: NotebookRef, ref: SourceRef) -> None:
        ids = self._source_ids.setdefault(nb.notebook_id, [])
        if ref.source_id not in ids:
            ids.append(ref.source_id)

    def _read_text(self, name: str) -> str:
        path = self._dir / name
        if not path.is_file():
            raise FileNotFoundError(f"fixture file missing: {path}")
        return path.read_text(encoding="utf-8")
