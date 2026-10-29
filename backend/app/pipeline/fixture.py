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


_FIXTURE_FACTS = [
    "Paris is the capital and largest city of France.",
    "Mars is often called the Red Planet because of its iron oxide dust.",
    "A hexagon is a polygon that has exactly six sides.",
    "Plants absorb carbon dioxide from the air during photosynthesis.",
    "Water is a molecule made of two hydrogen atoms and one oxygen atom.",
    "The chemical symbol for the element gold is Au.",
    "A triangle is a polygon with three sides and three angles.",
]
#: stands in for a module's PDF text: every fixture source_quote is a sentence of it
FIXTURE_SOURCE_TEXT = "Fixture course notes. " + " ".join(_FIXTURE_FACTS) + " End of notes."


def _fixture_chat_answer() -> str:
    """A canned chat answer: prose around a JSON array of 4 MCQ + 3 fill-blank questions
    (7 distinct questions). Each `source_quote` is a sentence of `FIXTURE_SOURCE_TEXT`, so it
    validates fully with that text and with `source_text=None`."""
    mcq = [
        ("What is the capital of France?", ["Paris", "Lyon", "Nice", "Lille"], 0),
        ("Which planet is known as the Red Planet?", ["Venus", "Mars", "Jupiter", "Saturn"], 1),
        ("How many sides does a hexagon have?", ["Five", "Six", "Seven", "Eight"], 1),
        (
            "Which gas do plants absorb for photosynthesis?",
            ["Oxygen", "Nitrogen", "Carbon dioxide", "Helium"],
            2,
        ),
    ]
    blanks = [
        ("Water is made of hydrogen and ____.", "oxygen", ["Oxygen"]),
        ("The chemical symbol for gold is ____.", "Au", []),
        ("A triangle has ____ sides.", "three", ["3"]),
    ]
    items: list[dict[str, Any]] = [
        {
            "type": "mcq",
            "question": q,
            "options": opts,
            "correct_index": ci,
            "explanation": f"The answer is {opts[ci]}.",
            "source_quote": _FIXTURE_FACTS[i],
        }
        for i, (q, opts, ci) in enumerate(mcq)
    ]
    items += [
        {
            "type": "fill_blank",
            "question": q,
            "answer": a,
            "accepted_answers": acc,
            "explanation": f"The answer is {a}.",
            "source_quote": _FIXTURE_FACTS[len(mcq) + j],
        }
        for j, (q, a, acc) in enumerate(blanks)
    ]
    return "Here are your questions:\n" + json.dumps(items, indent=2)


FIXTURE_CHAT_ANSWER = _fixture_chat_answer()


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

    def query(self, nb: NotebookRef, text: str) -> str:
        self.calls.append(("query", nb.notebook_id, text))
        return FIXTURE_CHAT_ANSWER

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
