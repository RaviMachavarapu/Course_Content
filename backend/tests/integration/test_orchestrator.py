"""T022 — generation orchestration end-to-end under FixtureProvider."""

from __future__ import annotations

import contextlib
import uuid
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.artifact import Artifact
from app.models.artifact_version import ArtifactVersion
from app.models.course import Course
from app.models.enums import (
    ArtifactStatus,
    ArtifactType,
    CourseStatus,
    ModuleSourceType,
    ModuleStatus,
)
from app.models.module import Module
from app.pipeline import orchestrator
from app.pipeline.fixture import FixtureProvider
from app.pipeline.provider import GenerationTimeout, StudioStatus
from app.render import RenderError
from app.storage.service import Storage

WORKING_TYPES = [
    ArtifactType.report,
    ArtifactType.audio_overview,
    ArtifactType.flashcards,
    ArtifactType.quiz,
    ArtifactType.slide_deck,  # T018 renderer is live (LibreOffice in the image)
    ArtifactType.infographic,  # T019 renderer is live (D15: render our own via Graphviz)
]


@pytest.fixture
def provider() -> FixtureProvider:
    return FixtureProvider()


@pytest.fixture(autouse=True)
def tmp_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Storage:
    store = Storage(tmp_path, "http://localhost:5173")
    monkeypatch.setattr(orchestrator, "get_storage", lambda: store)
    return store


def _module(db: Session) -> Module:
    course = Course(title="ML 101", slug=f"ml-{uuid.uuid4()}")
    module = Module(
        course=course,
        order_index=0,
        title="Neural Networks",
        source_url="https://youtu.be/abc123",
        source_type=ModuleSourceType.youtube,
    )
    db.add(module)
    db.flush()
    return module


def _run_all(db: Session, provider: FixtureProvider, module: Module, types: list[ArtifactType]):
    jobs = orchestrator.start_module_generation(db, provider, module.id, types)
    for job in jobs:
        # failure isolates to that artifact; keep going
        with contextlib.suppress(RenderError, GenerationTimeout):
            orchestrator.run_artifact_generation(db, provider, job.artifact_id, job_id=job.job_id)
    return jobs


def test_start_module_creates_six_artifacts_notebook_and_jobs(
    db_session: Session, provider: FixtureProvider
) -> None:
    module = _module(db_session)
    jobs = orchestrator.start_module_generation(db_session, provider, module.id, WORKING_TYPES)

    assert len(module.artifacts) == 6  # BR1
    assert len(jobs) == len(WORKING_TYPES)
    assert {j.type for j in jobs} == set(WORKING_TYPES)
    # no provider calls when starting: the first job's source step builds the notebook
    assert module.notebooklm_notebook_id is None
    assert module.sources_ready_at is None

    orchestrator.run_artifact_generation(
        db_session, provider, jobs[0].artifact_id, job_id=jobs[0].job_id
    )
    db_session.refresh(module)
    assert module.notebooklm_notebook_id
    assert module.notebooklm_link_source_id
    assert module.sources_ready_at is not None


def test_full_run_produces_ready_artifacts_with_media(
    db_session: Session, provider: FixtureProvider, tmp_storage: Storage
) -> None:
    module = _module(db_session)
    _run_all(db_session, provider, module, WORKING_TYPES)
    db_session.expire_all()

    by_type = {a.type: a for a in db_session.get(Module, module.id).artifacts}
    for t in WORKING_TYPES:
        assert by_type[t].status is ArtifactStatus.ready
        assert by_type[t].current_version_id is not None

    report_v = db_session.get(ArtifactVersion, by_type[ArtifactType.report].current_version_id)
    assert report_v.content_json["title"]
    # its PDF is typeset afterwards by the build_artifact_pdf task, not here
    assert report_v.media_files == []
    assert report_v.content_html and "<h2" in report_v.content_html

    audio_v = db_session.get(
        ArtifactVersion, by_type[ArtifactType.audio_overview].current_version_id
    )
    assert {m.kind.value for m in audio_v.media_files} == {"audio_mp3"}

    # flashcards / quiz: JSON only, no media
    for t in (ArtifactType.flashcards, ArtifactType.quiz):
        v = db_session.get(ArtifactVersion, by_type[t].current_version_id)
        assert v.media_files == []
        assert v.content_json

    assert len(list(tmp_storage._root.rglob("*"))) >= 2


def test_failure_isolates_to_one_artifact(
    db_session: Session, provider: FixtureProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module(db_session)
    # every type has a real renderer now — force one to fail so this test still
    # proves failure isolation across a mixed batch
    from app.pipeline.orchestrator import RENDERERS as live_renderers

    def _boom(*_a: object, **_k: object) -> None:
        raise RenderError("simulated infographic failure")

    monkeypatch.setattr(
        "app.pipeline.orchestrator.RENDERERS",
        {**live_renderers, ArtifactType.infographic: _boom},
    )

    all_types = list(ArtifactType)
    _run_all(db_session, provider, module, all_types)
    db_session.expire_all()

    by_type = {a.type: a for a in db_session.get(Module, module.id).artifacts}
    assert by_type[ArtifactType.infographic].status is ArtifactStatus.error
    assert "simulated infographic failure" in (by_type[ArtifactType.infographic].last_error or "")
    for t in WORKING_TYPES:
        if t is ArtifactType.infographic:
            continue  # this test forces it to fail
        assert by_type[t].status is ArtifactStatus.ready
    # module + course status reflect the mix
    assert db_session.get(Module, module.id).status is ModuleStatus.error
    assert db_session.get(Course, module.course_id).status is CourseStatus.error


def test_parse_failure_marks_artifact_error_and_reraises(
    db_session: Session, provider: FixtureProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module(db_session)
    jobs = orchestrator.start_module_generation(
        db_session, provider, module.id, [ArtifactType.report, ArtifactType.quiz]
    )
    quiz_job = next(j for j in jobs if j.type is ArtifactType.quiz)

    monkeypatch.setattr(
        FixtureProvider,
        "fetch_content",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    with pytest.raises(RuntimeError, match="boom"):
        orchestrator.run_artifact_generation(
            db_session, provider, quiz_job.artifact_id, job_id=quiz_job.job_id
        )
    db_session.expire_all()

    quiz = db_session.get(Artifact, quiz_job.artifact_id)
    assert quiz.status is ArtifactStatus.error
    assert "boom" in (quiz.last_error or "")
    job = next(
        j for j in db_session.get(Module, module.id).artifacts if j.type is ArtifactType.quiz
    )
    assert job.status is ArtifactStatus.error


def test_generation_times_out(
    db_session: Session, provider: FixtureProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module(db_session)
    jobs = orchestrator.start_module_generation(
        db_session, provider, module.id, [ArtifactType.report]
    )
    monkeypatch.setattr(FixtureProvider, "poll", lambda *a, **k: StudioStatus.pending)
    monkeypatch.setattr("app.pipeline.orchestrator.settings_timeout", lambda _a: 0)

    with pytest.raises(GenerationTimeout):
        orchestrator.run_artifact_generation(
            db_session, provider, jobs[0].artifact_id, job_id=jobs[0].job_id
        )
    db_session.expire_all()
    artifact = db_session.get(Artifact, jobs[0].artifact_id)
    assert artifact.status is ArtifactStatus.error
    job_row = db_session.get(Module, module.id).artifacts
    assert any(a.type is ArtifactType.report and a.status is ArtifactStatus.error for a in job_row)
    # NotebookLM may still finish it: the admin is told Retry keeps waiting on the same one
    assert artifact.last_error == orchestrator.STILL_WORKING
    assert artifact.studio_request is not None


def test_generation_budgets_cover_slow_notebooklm_types() -> None:
    # Live slide decks have taken > 6 min (2026-10-26, 2026-10-29): every type gets
    # 30 min, audio 45 min, before the run gives up waiting.
    settings = get_settings()
    assert settings.mcp_timeout_text_sec == 30 * 60
    assert settings.mcp_timeout_audio_sec == 45 * 60
    # the waiting itself counts as progress: the stall watchdog must outlast it
    assert settings.job_stall_sec > settings.mcp_timeout_text_sec
    assert settings.job_time_limit_text_sec > settings.mcp_timeout_text_sec
    assert settings.job_time_limit_audio_sec > settings.mcp_timeout_audio_sec
