"""The generation pipeline with NotebookLM-shaped results (recorded formats).

A fake provider stands in for the MCP shim: it returns the artifact rows / html
the shim returns (fixtures from tests/fixtures/notebooklm/), serves media
downloads, and records what the pipeline asked for.
"""

from __future__ import annotations

import json
import struct
import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.cli import seed_admin
from app.models.artifact import Artifact
from app.models.artifact_version import ArtifactVersion
from app.models.course import Course
from app.models.enums import ArtifactStatus, ArtifactType, MediaFileKind, ModuleSourceType
from app.models.media_file import MediaFile
from app.models.module import Module
from app.pipeline import orchestrator
from app.pipeline.provider import (
    NotebookRef,
    ProviderError,
    ProviderHealth,
    RawArtifact,
    SourceRef,
    StudioJobRef,
    StudioStatus,
    TransientProviderError,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "notebooklm"


def _row(name: str) -> list[Any]:
    data: list[Any] = json.loads((FIXTURES / name).read_text())
    return data


def _mp4(seconds: int) -> bytes:
    body = bytes(12) + struct.pack(">II", 1000, seconds * 1000) + bytes(80)
    mvhd = struct.pack(">I4s", 8 + len(body), b"mvhd") + body
    return (
        struct.pack(">I4s", 16, b"ftyp")
        + b"M4A \0\0\0\0"
        + struct.pack(">I4s", 8 + len(mvhd), b"moov")
        + mvhd
    )


OUTLINE_ROW: list[Any] = [None] * 31
OUTLINE_ROW[30] = [
    [["A 'Technical Blueprint' look."], ["**Intro**: the course."], ["**Models**: why."]]
]


class FakeNotebookLm:
    def __init__(self, row: list[Any] | None, html: str | None = None) -> None:
        self.row, self.html = row, html
        self.status = StudioStatus.ready
        self.generated: list[tuple[ArtifactType, str, dict[str, Any]]] = []
        self.downloads: list[str] = []
        self.outline_actions: list[str | None] = []
        self.fail_downloads = False

    def create_notebook(self, title: str) -> NotebookRef:
        return NotebookRef(notebook_id="nb-1")

    def add_source(self, nb: NotebookRef, url: str) -> SourceRef:
        return SourceRef(source_id="src-1")

    def generate(
        self, nb: NotebookRef, kind: ArtifactType, focus_prompt: str, options: dict[str, Any]
    ) -> StudioJobRef:
        self.generated.append((kind, focus_prompt, options))
        return StudioJobRef(job_id=f"nlm-{kind.value}", notebook_id=nb.notebook_id, kind=kind)

    def poll(self, job: StudioJobRef) -> StudioStatus:
        return self.status

    def fetch_content(self, job: StudioJobRef) -> RawArtifact:
        return RawArtifact(
            html=self.html or "",
            extras={"artifact_id": job.job_id, "source": "notebooklm", "row": self.row},
        )

    def fetch_binary(self, job: StudioJobRef, kind: ArtifactType) -> bytes | None:
        return None

    def download(self, url: str) -> tuple[bytes, str]:
        if self.fail_downloads:
            raise ProviderError("media download failed (HTTP 403)")
        self.downloads.append(url)
        if url.endswith("=mm,140"):
            return _mp4(359), "audio/mp4"
        return b"\x89PNG\r\n\x1a\n" + url.encode(), "application/octet-stream"

    def outline_action(self, job: StudioJobRef, feedback: str | None) -> None:
        self.outline_actions.append(feedback)

    def health(self) -> ProviderHealth:
        return ProviderHealth(healthy=True, account_email=None, last_ok_at=None, detail="fake")

    def refresh_auth(self) -> None:
        return None


def _artifact(db: Session, kind: ArtifactType, options: dict[str, Any] | None = None) -> Artifact:
    course = Course(title="C", slug=f"c-{uuid.uuid4()}")
    module = Module(
        course=course,
        order_index=0,
        title="M",
        source_url="https://youtu.be/x",
        source_type=ModuleSourceType.youtube,
        notebooklm_notebook_id="nb-1",
    )
    db.add(module)
    db.flush()
    artifacts = orchestrator.ensure_artifacts(db, module)
    artifact = artifacts[kind]
    artifact.generation_options = options or {}
    db.flush()
    return artifact


def _media_kinds(db: Session, version: ArtifactVersion) -> list[tuple[MediaFileKind, int | None]]:
    rows = db.scalars(select(MediaFile).where(MediaFile.artifact_version_id == version.id))
    return sorted(((m.kind, m.page_index) for m in rows), key=lambda k: (k[0].value, k[1] or 0))


def test_slide_deck_stores_notebooklms_images_pdf_and_pptx(db_session: Session) -> None:
    provider = FakeNotebookLm(_row("slide_deck.json"))
    artifact = _artifact(db_session, ArtifactType.slide_deck, {"format": "presenter"})

    version = orchestrator.run_artifact_generation(db_session, provider, artifact.id)

    assert version is not None
    assert artifact.status is ArtifactStatus.ready
    assert len(version.content_json["slides"]) == 2
    # stored options were validated and completed before being sent
    assert provider.generated[0][2] == {
        "format": "presenter",
        "length": "default",
        "language": "en",
        "review_outline": False,
    }
    assert _media_kinds(db_session, version) == [
        (MediaFileKind.deck_pdf, None),
        (MediaFileKind.pptx, None),
        (MediaFileKind.slide_png, 0),
        (MediaFileKind.slide_png, 1),
    ]


def test_audio_is_stored_as_m4a_with_its_real_duration(db_session: Session) -> None:
    row: list[Any] = [None] * 7
    row[6] = [None, [None, 2], "https://lh3.googleusercontent.com/a=mm,140"]
    provider = FakeNotebookLm(row)
    artifact = _artifact(db_session, ArtifactType.audio_overview)

    version = orchestrator.run_artifact_generation(db_session, provider, artifact.id)

    assert version is not None
    assert version.content_json["duration_seconds"] == 359
    assert _media_kinds(db_session, version) == [(MediaFileKind.audio_m4a, None)]


def test_report_text_comes_from_notebooklm_and_the_pdf_from_us(db_session: Session) -> None:
    provider = FakeNotebookLm(_row("report_interactive.json"))
    artifact = _artifact(db_session, ArtifactType.report)

    version = orchestrator.run_artifact_generation(db_session, provider, artifact.id)

    assert version is not None
    assert version.content_json["title"].startswith("Introduction to Artificial Intelligence")
    assert provider.downloads == []
    assert _media_kinds(db_session, version) == [(MediaFileKind.report_pdf, None)]
    assert version.content_html and "<h2" in version.content_html


def test_a_failed_download_leaves_no_half_stored_version(db_session: Session) -> None:
    provider = FakeNotebookLm(_row("slide_deck.json"))
    provider.fail_downloads = True
    artifact = _artifact(db_session, ArtifactType.slide_deck)

    with pytest.raises(ProviderError):
        orchestrator.run_artifact_generation(db_session, provider, artifact.id)

    assert artifact.status is ArtifactStatus.error
    assert "403" in (artifact.last_error or "")
    assert (
        db_session.scalar(select(ArtifactVersion).where(ArtifactVersion.artifact_id == artifact.id))
        is None
    )


def test_outdated_stored_options_fail_with_a_clear_reason(db_session: Session) -> None:
    provider = FakeNotebookLm(_row("slide_deck.json"))
    artifact = _artifact(db_session, ArtifactType.audio_overview, {"language": "es"})

    with pytest.raises(ValidationError):
        orchestrator.run_artifact_generation(db_session, provider, artifact.id)

    assert artifact.status is ArtifactStatus.error
    assert "language" in (artifact.last_error or "")
    assert provider.generated == []  # nothing was sent to NotebookLM


# -- slide outline review --------------------------------------------------------
def _admin_headers(client: TestClient, db: Session) -> dict[str, str]:
    seed_admin(db, email="outline@example.com", display_name="O", password="outline-pw-12345")
    db.flush()
    client.post(
        "/api/admin/auth/login",
        json={"email": "outline@example.com", "password": "outline-pw-12345"},
    )
    return {"X-CSRF-Token": client.cookies["sdp_csrf"]}


def test_outline_review_then_proceed_builds_the_deck(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = FakeNotebookLm(OUTLINE_ROW)
    provider.status = StudioStatus.awaiting_review
    artifact = _artifact(db_session, ArtifactType.slide_deck, {"review_outline": True})

    # 1. NotebookLM drafts the outline and waits.
    assert orchestrator.run_artifact_generation(db_session, provider, artifact.id) is None
    assert artifact.status is ArtifactStatus.outline_review
    assert artifact.notebooklm_studio_id == "nlm-slide_deck"
    assert artifact.outline_json is not None
    assert artifact.outline_json["slides"] == ["**Intro**: the course.", "**Models**: why."]

    # 2. Staging shows the outline; the admin proceeds.
    monkeypatch.setattr("app.api.admin.staging.get_content_provider", lambda: provider)
    dispatched: list[tuple[Any, ...]] = []
    monkeypatch.setattr("app.api.admin.staging._dispatch", lambda *a: dispatched.append(a))
    headers = _admin_headers(client, db_session)
    staging = client.get(f"/api/admin/modules/{artifact.module_id}/staging").json()
    deck = next(a for a in staging["artifacts"] if a["type"] == "slide_deck")
    assert deck["status"] == "outline_review"
    assert deck["outline"]["slides"][0] == "**Intro**: the course."

    resp = client.post(f"/api/admin/artifacts/{artifact.id}/outline/proceed", headers=headers)
    assert resp.status_code == status.HTTP_202_ACCEPTED
    assert provider.outline_actions == [None]
    assert dispatched and dispatched[0][-1] is True  # resume=True
    db_session.expire_all()
    artifact = db_session.get(Artifact, artifact.id)
    assert artifact is not None and artifact.status is ArtifactStatus.processing

    # 3. The worker waits for the built deck — without generating again.
    provider.row, provider.status = _row("slide_deck.json"), StudioStatus.ready
    version = orchestrator.run_artifact_generation(
        db_session, provider, artifact.id, job_id=uuid.UUID(resp.json()["job"]["id"]), resume=True
    )
    assert version is not None
    assert len(provider.generated) == 1
    assert artifact.status is ArtifactStatus.ready
    assert artifact.outline_json is None and artifact.notebooklm_studio_id is None


def test_outline_feedback_is_sent_and_needs_text(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = FakeNotebookLm(OUTLINE_ROW)
    provider.status = StudioStatus.awaiting_review
    artifact = _artifact(db_session, ArtifactType.slide_deck, {"review_outline": True})
    orchestrator.run_artifact_generation(db_session, provider, artifact.id)
    monkeypatch.setattr("app.api.admin.staging.get_content_provider", lambda: provider)
    monkeypatch.setattr("app.api.admin.staging._dispatch", lambda *a: None)
    headers = _admin_headers(client, db_session)

    url = f"/api/admin/artifacts/{artifact.id}/outline/feedback"
    assert client.post(url, json={"feedback": ""}, headers=headers).status_code == 422
    resp = client.post(url, json={"feedback": "  Fewer slides  "}, headers=headers)
    assert resp.status_code == status.HTTP_202_ACCEPTED
    assert provider.outline_actions == ["Fewer slides"]


def test_outline_actions_need_an_outline_waiting(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact = _artifact(db_session, ArtifactType.slide_deck)
    monkeypatch.setattr("app.api.admin.staging.get_content_provider", lambda: FakeNotebookLm(None))
    headers = _admin_headers(client, db_session)
    resp = client.post(f"/api/admin/artifacts/{artifact.id}/outline/proceed", headers=headers)
    assert resp.status_code == status.HTTP_409_CONFLICT
    assert resp.json()["error"]["code"] == "no_outline_to_review"


def test_outline_routes_reject_anonymous_and_students(
    client: TestClient, db_session: Session
) -> None:
    artifact = _artifact(db_session, ArtifactType.slide_deck)
    for path in ("outline/proceed", "outline/feedback"):
        resp = client.post(f"/api/admin/artifacts/{artifact.id}/{path}", json={"feedback": "x"})
        assert resp.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)


# -- transient errors after creation must not regenerate -------------------------
class FlakyNotebookLm(FakeNotebookLm):
    """Fails the first `poll_failures` polls and `download_failures` downloads."""

    def __init__(self, row: list[Any], poll_failures: int = 0, download_failures: int = 0) -> None:
        super().__init__(row)
        self.poll_failures, self.download_failures = poll_failures, download_failures

    def poll(self, job: StudioJobRef) -> StudioStatus:
        if self.poll_failures:
            self.poll_failures -= 1
            raise TransientProviderError("could not acquire mcp:session within 60s")
        return super().poll(job)

    def download(self, url: str) -> tuple[bytes, str]:
        if self.download_failures:
            self.download_failures -= 1
            raise TransientProviderError("media fetch timed out")
        return super().download(url)


@pytest.fixture
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.pipeline.orchestrator.time.sleep", lambda _s: None)


@pytest.mark.usefixtures("_no_sleep")
def test_a_busy_session_while_polling_keeps_waiting(db_session: Session) -> None:
    provider = FlakyNotebookLm(_row("infographic.json"), poll_failures=2)
    artifact = _artifact(db_session, ArtifactType.infographic)

    version = orchestrator.run_artifact_generation(db_session, provider, artifact.id)

    assert version is not None
    assert len(provider.generated) == 1  # generated once, despite the failed polls


@pytest.mark.usefixtures("_no_sleep")
def test_a_failed_download_is_retried_without_generating_again(db_session: Session) -> None:
    provider = FlakyNotebookLm(_row("infographic.json"), download_failures=2)
    artifact = _artifact(db_session, ArtifactType.infographic)

    version = orchestrator.run_artifact_generation(db_session, provider, artifact.id)

    assert version is not None
    assert len(provider.generated) == 1


@pytest.mark.usefixtures("_no_sleep")
def test_persistent_download_failures_end_as_a_permanent_error(db_session: Session) -> None:
    provider = FlakyNotebookLm(_row("infographic.json"), download_failures=99)
    artifact = _artifact(db_session, ArtifactType.infographic)

    with pytest.raises(ProviderError) as info:
        orchestrator.run_artifact_generation(db_session, provider, artifact.id)

    # not Transient: Celery must not retry (that would generate it again)
    assert not isinstance(info.value, TransientProviderError)
    assert artifact.status is ArtifactStatus.error
