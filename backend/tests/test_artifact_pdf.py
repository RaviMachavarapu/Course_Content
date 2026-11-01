"""Quarto PDFs for every artifact version (app/pipeline/artifact_pdf.py, the
`build_artifact_pdf` Celery task and `rebuild-pdfs`).

The typeset service is always faked here; the real one is only reached by the
opt-in live tests in test_typeset_docs.py.
"""

from __future__ import annotations

import contextlib
import io
import uuid
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app import cli
from app.cli import build_parser, rebuild_pdfs
from app.models.artifact import Artifact
from app.models.artifact_version import ArtifactVersion
from app.models.course import Course
from app.models.enums import ArtifactStatus, ArtifactType, MediaFileKind, ModuleSourceType
from app.models.media_file import MediaFile
from app.models.module import Module
from app.pipeline import artifact_pdf
from app.render.typeset_client import TypesetError, TypesetResult, TypesetUnavailable
from app.storage.service import Storage
from app.tasks import pdf as pdf_task
from tests.test_typeset_docs import FLASHCARDS, INFOGRAPHIC, QUIZ, REPORT, SLIDES

CONTENT: dict[ArtifactType, dict[str, Any]] = {
    ArtifactType.report: REPORT,
    ArtifactType.flashcards: FLASHCARDS,
    ArtifactType.quiz: QUIZ,
    ArtifactType.infographic: INFOGRAPHIC,
    ArtifactType.slide_deck: SLIDES,
    ArtifactType.audio_overview: {"duration_seconds": 30},
}


def _png(color: str = "red") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (4, 3), color).save(buf, "PNG")
    return buf.getvalue()


class FakeTypeset:
    """Stands in for `render_pdf`: records each call, returns a tiny PDF, or raises."""

    def __init__(self, fallback: str = "0", error: Exception | None = None) -> None:
        self.calls: list[tuple[str, str, dict[str, bytes]]] = []
        self.fallback = fallback
        self.error = error
        self.pdf = b"%PDF-1.7 fake " + uuid.uuid4().hex.encode()

    def __call__(self, markdown: str, title: str, images: dict[str, bytes]) -> TypesetResult:
        self.calls.append((markdown, title, images))
        if self.error is not None:
            raise self.error
        return TypesetResult(pdf=self.pdf, fallback=self.fallback)


def _version(
    db: Session,
    artifact_type: ArtifactType,
    *,
    content: dict[str, Any] | None = None,
    status: ArtifactStatus = ArtifactStatus.ready,
    module: Module | None = None,
) -> ArtifactVersion:
    if module is None:
        course = Course(title="Organic Chemistry", slug=f"c-{uuid.uuid4()}")
        module = Module(
            course=course,
            order_index=0,
            title="Substitution",
            source_url="https://youtu.be/x",
            source_type=ModuleSourceType.youtube,
        )
    artifact = Artifact(module=module, type=artifact_type, status=status)
    db.add(artifact)
    db.flush()
    version = ArtifactVersion(
        artifact_id=artifact.id,
        revision=1,
        focus_prompt_used="p",
        content_json=CONTENT[artifact_type] if content is None else content,
    )
    db.add(version)
    db.flush()
    artifact.current_version_id = version.id
    db.flush()
    return version


def _add_media(
    db: Session,
    storage: Storage,
    version: ArtifactVersion,
    kind: MediaFileKind,
    data: bytes,
    page_index: int | None = None,
) -> str:
    artifact = version.artifact
    module = artifact.module
    leaf = kind.value if page_index is None else f"{kind.value}.{page_index:04d}"
    key = (
        f"courses/{module.course_id}/modules/{module.id}/artifacts/{artifact.id}"
        f"/v{version.revision}/{leaf}.png"
    )
    stored = storage.put(key, data, "image/png")
    db.add(
        storage.build_media_file(
            stored, artifact_version_id=str(version.id), kind=kind, page_index=page_index
        )
    )
    db.flush()
    return key


def _pdfs(db: Session, version: ArtifactVersion) -> list[MediaFile]:
    db.expire_all()
    return list(
        db.scalars(
            select(MediaFile).where(
                MediaFile.artifact_version_id == version.id,
                MediaFile.kind.in_(artifact_pdf.PDF_KINDS.values()),
            )
        )
    )


@pytest.fixture
def task_sessions(
    monkeypatch: pytest.MonkeyPatch, source_step_sessions: Callable[..., Any]
) -> None:
    """Run the Celery task's sessions on the test connection."""
    monkeypatch.setattr(pdf_task, "session_scope", source_step_sessions)


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeTypeset:
    typeset = FakeTypeset()
    monkeypatch.setattr(pdf_task, "render_pdf", typeset)
    monkeypatch.setattr(artifact_pdf, "render_pdf", typeset)
    return typeset


def _run_task(version_id: uuid.UUID, retries: int = 0) -> Any:
    task = pdf_task.build_artifact_pdf
    task.push_request(retries=retries)
    try:
        return task.run(str(version_id))
    finally:
        task.pop_request()


# -- the task -----------------------------------------------------------------------
@pytest.mark.parametrize(
    "artifact_type",
    [
        ArtifactType.report,
        ArtifactType.flashcards,
        ArtifactType.quiz,
        ArtifactType.infographic,
        ArtifactType.slide_deck,
    ],
)
def test_task_stores_the_pdf_media_file_with_the_types_kind(
    db_session: Session,
    media_storage: Storage,
    task_sessions: None,
    fake: FakeTypeset,
    artifact_type: ArtifactType,
) -> None:
    version = _version(db_session, artifact_type)

    assert _run_task(version.id) == "built"

    (pdf,) = _pdfs(db_session, version)
    assert pdf.kind is artifact_pdf.PDF_KINDS[artifact_type]
    assert pdf.mime_type == "application/pdf"
    assert pdf.storage_key.endswith(".pdf")
    assert f"/artifacts/{version.artifact_id}/v1/{pdf.kind.value}." in pdf.storage_key
    assert media_storage.open(pdf.storage_key) == fake.pdf
    assert pdf.size_bytes == len(fake.pdf)
    (markdown, title, _images) = fake.calls[0]
    if artifact_type is ArtifactType.report:
        assert title == "Nucleophilic Substitution: S_N2 & More"
    else:
        assert title.startswith("Substitution: ")
    assert markdown.startswith("# ")


def test_a_quiz_also_gets_a_questions_only_pdf(
    db_session: Session, media_storage: Storage, task_sessions: None, fake: FakeTypeset
) -> None:
    """Admins get questions + answer key (quiz_pdf); students get a copy with
    the questions and options only (quiz_questions_pdf)."""
    version = _version(db_session, ArtifactType.quiz)

    assert _run_task(version.id) == "built"

    db_session.expire_all()
    kinds = sorted(m.kind.value for m in db_session.get(ArtifactVersion, version.id).media_files)
    assert kinds == ["quiz_pdf", "quiz_questions_pdf"]
    full, questions = (call[0] for call in fake.calls)
    assert "## Answer key" in full and "Bimolecular" in full
    assert "Answer key" not in questions and "Bimolecular" not in questions
    assert "Which is the rate law for $S_N2$" in questions


def test_rebuild_pdfs_builds_both_quiz_pdfs(db_session: Session, fake: FakeTypeset) -> None:
    quiz = _version(db_session, ArtifactType.quiz)

    (result,) = rebuild_pdfs(db_session, version_id=quiz.id)

    assert result[1] == "built (fallback 0)"
    db_session.expire_all()
    kinds = sorted(m.kind.value for m in db_session.get(ArtifactVersion, quiz.id).media_files)
    assert kinds == ["quiz_pdf", "quiz_questions_pdf"]


def test_slide_and_infographic_images_are_sent(
    db_session: Session, media_storage: Storage, task_sessions: None, fake: FakeTypeset
) -> None:
    deck = _version(db_session, ArtifactType.slide_deck)
    _add_media(db_session, media_storage, deck, MediaFileKind.slide_png, _png("red"), 1)
    _add_media(db_session, media_storage, deck, MediaFileKind.slide_png, _png("blue"), 0)
    info = _version(db_session, ArtifactType.infographic)
    _add_media(db_session, media_storage, info, MediaFileKind.infographic_png, _png("green"))

    _run_task(deck.id)
    _run_task(info.id)

    assert fake.calls[0][2] == {"slide-001.png": _png("blue"), "slide-002.png": _png("red")}
    assert fake.calls[1][2] == {"infographic.png": _png("green")}


def test_report_section_images_from_the_course_are_embedded(
    db_session: Session, media_storage: Storage, task_sessions: None, fake: FakeTypeset
) -> None:
    hero = _version(db_session, ArtifactType.infographic)
    key = _add_media(db_session, media_storage, hero, MediaFileKind.infographic_png, _png())
    content = {
        **REPORT,
        "sections": [{"heading": "S", "html": f'<p><img src="/api/media/{key}" alt="pic"></p>'}],
    }
    report = _version(db_session, ArtifactType.report, content=content, module=hero.artifact.module)

    _run_task(report.id)

    markdown, _title, images = fake.calls[0]
    assert images == {"image-001.png": _png()}
    assert "![](image-001.png)" in markdown


def test_a_rebuild_replaces_the_previous_pdf(
    db_session: Session,
    media_storage: Storage,
    task_sessions: None,
    fake: FakeTypeset,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    version = _version(db_session, ArtifactType.quiz)
    _run_task(version.id)
    (first,) = _pdfs(db_session, version)
    first_id, first_key = first.id, first.storage_key

    second_fake = FakeTypeset()
    monkeypatch.setattr(pdf_task, "render_pdf", second_fake)
    _run_task(version.id)

    (second,) = _pdfs(db_session, version)
    assert second.id != first_id
    assert second.storage_key != first_key  # media URLs are cached as immutable
    assert media_storage.open(second.storage_key) == second_fake.pdf
    assert not media_storage.exists(first_key)


def test_a_rebuild_of_identical_bytes_keeps_the_file(
    db_session: Session, media_storage: Storage, task_sessions: None, fake: FakeTypeset
) -> None:
    version = _version(db_session, ArtifactType.quiz)
    _run_task(version.id)
    _run_task(version.id)

    (pdf,) = _pdfs(db_session, version)
    assert media_storage.open(pdf.storage_key) == fake.pdf


def test_other_media_of_the_version_is_untouched(
    db_session: Session, media_storage: Storage, task_sessions: None, fake: FakeTypeset
) -> None:
    version = _version(db_session, ArtifactType.slide_deck)
    key = _add_media(db_session, media_storage, version, MediaFileKind.slide_png, _png(), 0)

    _run_task(version.id)

    db_session.expire_all()
    kinds = sorted(m.kind.value for m in db_session.get(ArtifactVersion, version.id).media_files)
    assert kinds == ["slide_png", "slides_handout_pdf"]
    assert media_storage.exists(key)


def test_pdf_failure_does_not_fail_artifact(
    db_session: Session,
    media_storage: Storage,
    task_sessions: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    version = _version(db_session, ArtifactType.flashcards)
    artifact_id = version.artifact_id

    # unavailable: a retry is scheduled, nothing is stored
    monkeypatch.setattr(pdf_task, "render_pdf", FakeTypeset(error=TypesetUnavailable("down")))
    scheduled: list[dict[str, Any]] = []

    def fake_retry(**kwargs: Any) -> Exception:
        scheduled.append(kwargs)
        return RuntimeError("retry")

    monkeypatch.setattr(pdf_task.build_artifact_pdf, "retry", fake_retry)
    with pytest.raises(RuntimeError, match="retry"):
        _run_task(version.id, retries=2)
    assert scheduled[0]["countdown"] == 30 * 2**2
    assert isinstance(scheduled[0]["exc"], TypesetUnavailable)

    # out of retries: give up quietly
    assert _run_task(version.id, retries=pdf_task.MAX_RETRIES) == "gave up"

    # permanent error: logged, nothing stored, no retry
    monkeypatch.setattr(pdf_task, "render_pdf", FakeTypeset(error=TypesetError("422")))
    assert _run_task(version.id) == "failed"
    assert len(scheduled) == 1

    assert _pdfs(db_session, version) == []
    artifact = db_session.get(Artifact, artifact_id)
    assert artifact is not None
    assert artifact.status is ArtifactStatus.ready
    assert artifact.last_error is None
    assert not list(media_storage._root.rglob("*.pdf"))


def test_a_failed_rebuild_keeps_the_previous_pdf(
    db_session: Session,
    media_storage: Storage,
    task_sessions: None,
    fake: FakeTypeset,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    version = _version(db_session, ArtifactType.quiz)
    _run_task(version.id)
    monkeypatch.setattr(pdf_task, "render_pdf", FakeTypeset(error=TypesetError("bad")))
    _run_task(version.id)

    (pdf,) = _pdfs(db_session, version)
    assert media_storage.open(pdf.storage_key) == fake.pdf


def test_formulas_shown_as_source_are_logged(
    db_session: Session,
    task_sessions: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    version = _version(db_session, ArtifactType.flashcards)
    monkeypatch.setattr(pdf_task, "render_pdf", FakeTypeset(fallback="2"))
    warnings: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(pdf_task.log, "warning", lambda event, **kw: warnings.append((event, kw)))

    assert _run_task(version.id) == "built"

    ((event, kw),) = warnings
    assert event == "pdf.formulas_shown_as_source"
    assert kw["version_id"] == str(version.id) and kw["fallback"] == "2"
    assert "/flashcards_pdf." in kw["key"]


def test_audio_and_missing_versions_are_skipped(
    db_session: Session, task_sessions: None, fake: FakeTypeset
) -> None:
    audio = _version(db_session, ArtifactType.audio_overview)
    assert _run_task(audio.id) == "skipped"
    assert _run_task(uuid.uuid4()) == "skipped"
    assert fake.calls == []


def test_invalid_content_is_not_retried(
    db_session: Session, task_sessions: None, fake: FakeTypeset
) -> None:
    version = _version(db_session, ArtifactType.quiz, content={"questions": []})
    assert _run_task(version.id) == "failed"
    assert fake.calls == []


# -- rebuild-pdfs ------------------------------------------------------------------------
def test_rebuild_pdfs_dry_run_writes_nothing(
    db_session: Session, media_storage: Storage, fake: FakeTypeset
) -> None:
    quiz = _version(db_session, ArtifactType.quiz)
    _version(db_session, ArtifactType.audio_overview)

    results = rebuild_pdfs(db_session, dry_run=True)

    assert fake.calls == []
    assert _pdfs(db_session, quiz) == []
    assert not list(media_storage._root.rglob("*"))
    outcomes = [outcome for _, outcome in results]
    assert outcomes == ["would build"]  # audio has no PDF and is not listed


def test_rebuild_pdfs_builds_current_and_published_versions(
    db_session: Session, fake: FakeTypeset
) -> None:
    current = _version(db_session, ArtifactType.quiz)
    artifact = current.artifact
    published = ArtifactVersion(
        artifact_id=artifact.id, revision=2, focus_prompt_used="p", content_json=QUIZ
    )
    old = ArtifactVersion(
        artifact_id=artifact.id, revision=3, focus_prompt_used="p", content_json=QUIZ
    )
    db_session.add_all([published, old])
    db_session.flush()
    artifact.published_version_id = published.id
    broken = _version(db_session, ArtifactType.flashcards, content={"cards": []})
    db_session.flush()

    results = dict(rebuild_pdfs(db_session))

    built = {k: v for k, v in results.items() if v.startswith("built")}
    assert len(built) == 2
    assert all(v == "built (fallback 0)" for v in built.values())
    assert any(str(current.id) in k for k in built)
    assert any(str(published.id) in k for k in built)
    assert not any(str(old.id) in k for k in results)
    (failed,) = [v for k, v in results.items() if str(broken.id) in k]
    assert failed.startswith("failed (")
    assert len(_pdfs(db_session, current)) == 1
    assert len(_pdfs(db_session, published)) == 1


def test_rebuild_pdfs_filters_by_type_and_version(db_session: Session, fake: FakeTypeset) -> None:
    quiz = _version(db_session, ArtifactType.quiz)
    cards = _version(db_session, ArtifactType.flashcards)

    by_type = rebuild_pdfs(db_session, dry_run=True, types=[ArtifactType.flashcards])
    assert [str(cards.id) in label for label, _ in by_type] == [True]

    by_version = rebuild_pdfs(db_session, version_id=quiz.id)
    assert len(by_version) == 1 and str(quiz.id) in by_version[0][0]
    assert by_version[0][1] == "built (fallback 0)"

    unavailable = FakeTypeset(error=TypesetUnavailable("down"))
    out = rebuild_pdfs(db_session, version_id=quiz.id, render=unavailable)
    assert out[0][1].startswith("failed (typeset service unavailable")

    audio = _version(db_session, ArtifactType.audio_overview)
    out = rebuild_pdfs(db_session, version_id=audio.id)
    assert out[0][1] == "skipped (audio_overview has no PDF)"


def test_rebuild_pdfs_parser() -> None:
    ns = build_parser().parse_args(
        ["rebuild-pdfs", "--dry-run", "--type", "quiz", "--version", str(uuid.UUID(int=1))]
    )
    assert ns.dry_run is True
    assert ns.type == "quiz"
    assert ns.version == str(uuid.UUID(int=1))


# -- fix round 1 ------------------------------------------------------------------------
def test_the_task_runs_on_its_own_pdf_queue() -> None:
    assert pdf_task.build_artifact_pdf.queue == "pdf"


def test_a_database_outage_is_retried(
    db_session: Session, task_sessions: None, fake: FakeTypeset, monkeypatch: pytest.MonkeyPatch
) -> None:
    version = _version(db_session, ArtifactType.quiz)

    def down(*_: Any) -> None:
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    monkeypatch.setattr(pdf_task, "prepare_pdfs", down)
    scheduled: list[dict[str, Any]] = []

    def fake_retry(**kwargs: Any) -> Exception:
        scheduled.append(kwargs)
        return RuntimeError("retry")

    monkeypatch.setattr(pdf_task.build_artifact_pdf, "retry", fake_retry)
    with pytest.raises(RuntimeError, match="retry"):
        _run_task(version.id, retries=1)
    assert scheduled[0]["countdown"] == 60
    assert isinstance(scheduled[0]["exc"], OperationalError)
    assert _run_task(version.id, retries=pdf_task.MAX_RETRIES) == "gave up"


def test_a_superseded_version_is_skipped(
    db_session: Session, task_sessions: None, fake: FakeTypeset
) -> None:
    old = _version(db_session, ArtifactType.quiz)
    newer = ArtifactVersion(
        artifact_id=old.artifact_id, revision=2, focus_prompt_used="p", content_json=QUIZ
    )
    db_session.add(newer)
    db_session.flush()
    old.artifact.current_version_id = newer.id
    db_session.flush()

    assert _run_task(old.id) == "skipped"
    assert fake.calls == []
    assert _pdfs(db_session, old) == []

    # still built while it is the published version
    old.artifact.published_version_id = old.id
    db_session.flush()
    assert _run_task(old.id) == "built"


class _FailingCommit:
    """session_scope stand-in whose commit fails after the body ran."""

    def __init__(self, inner: Callable[..., Any], fail_on: int) -> None:
        self.inner = inner
        self.fail_on = fail_on
        self.calls = 0

    @contextlib.contextmanager
    def __call__(self) -> Iterator[Session]:
        self.calls += 1
        with self.inner() as session:
            yield session
            if self.calls == self.fail_on:
                raise OperationalError("COMMIT", {}, Exception("connection lost"))


def test_a_failed_commit_leaves_no_orphan_file(
    db_session: Session,
    media_storage: Storage,
    source_step_sessions: Callable[..., Any],
    fake: FakeTypeset,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    version = _version(db_session, ArtifactType.quiz)
    monkeypatch.setattr(pdf_task, "session_scope", _FailingCommit(source_step_sessions, 2))
    monkeypatch.setattr(pdf_task.build_artifact_pdf, "retry", lambda **kw: RuntimeError("retry"))

    with pytest.raises(RuntimeError, match="retry"):
        _run_task(version.id)

    assert not list(media_storage._root.rglob("*.pdf"))


def test_a_failed_commit_keeps_a_previous_file_with_the_same_key(
    db_session: Session,
    media_storage: Storage,
    source_step_sessions: Callable[..., Any],
    fake: FakeTypeset,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    version = _version(db_session, ArtifactType.quiz)
    monkeypatch.setattr(pdf_task, "session_scope", source_step_sessions)
    _run_task(version.id)
    (pdf,) = _pdfs(db_session, version)
    key = pdf.storage_key

    # same bytes again (same key), and this time the commit fails
    monkeypatch.setattr(pdf_task, "session_scope", _FailingCommit(source_step_sessions, 2))
    monkeypatch.setattr(pdf_task.build_artifact_pdf, "retry", lambda **kw: RuntimeError("retry"))
    with pytest.raises(RuntimeError):
        _run_task(version.id)

    assert media_storage.open(key) == fake.pdf


def test_store_pdf_removes_its_new_file_if_the_rows_cannot_be_written(
    db_session: Session, media_storage: Storage, monkeypatch: pytest.MonkeyPatch
) -> None:
    version = _version(db_session, ArtifactType.quiz)
    monkeypatch.setattr(
        media_storage,
        "build_media_file",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db write failed")),
    )
    with pytest.raises(RuntimeError, match="db write failed"):
        artifact_pdf.store_pdf(db_session, version.id, MediaFileKind.quiz_pdf, b"%PDF-1.7 x")
    assert not list(media_storage._root.rglob("*.pdf"))


def test_rebuild_pdfs_failed_commit_leaves_no_orphan_file(
    db_session: Session,
    media_storage: Storage,
    fake: FakeTypeset,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    version = _version(db_session, ArtifactType.quiz)

    def broken_commit() -> None:
        raise OperationalError("COMMIT", {}, Exception("connection lost"))

    monkeypatch.setattr(db_session, "commit", broken_commit)
    monkeypatch.setattr(db_session, "rollback", lambda: None)

    (result,) = rebuild_pdfs(db_session, version_id=version.id)

    assert result[1].startswith("failed (OperationalError")
    assert not list(media_storage._root.rglob("*.pdf"))


def test_refresh_report_math_hints_at_rebuilding_pdfs(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    @contextlib.contextmanager
    def scope() -> Iterator[object]:
        yield object()

    monkeypatch.setattr(cli, "session_scope", scope)
    monkeypatch.setattr(cli, "get_content_provider", lambda: object())
    for outcomes, dry_run, hinted in (
        (["updated", "unchanged"], False, True),
        (["unchanged"], False, False),
        (["updated"], True, False),
    ):
        monkeypatch.setattr(
            cli,
            "refresh_report_math",
            lambda *a, _o=outcomes, **k: [(f"r{i}", o) for i, o in enumerate(_o)],
        )
        cli.main(["refresh-report-math", *(["--dry-run"] if dry_run else [])])
        out = capsys.readouterr().out
        assert (out.strip().splitlines()[-1] == cli.REBUILD_REPORT_PDFS) is hinted
        assert ("rebuild-pdfs --type report" in out) is hinted


def test_the_typeset_down_marker_makes_the_service_unavailable(
    db_session: Session,
    task_sessions: None,
    fake: FakeTypeset,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """E2E fault injection (fixture provider only): retried, then "gave up"; the
    artifact stays ready and nothing is sent to the typeset service."""
    course = Course(title="C", slug=f"c-{uuid.uuid4()}")
    module = Module(
        course=course,
        order_index=0,
        title="Week 1 [fixture:typeset-down]",
        source_url="https://youtu.be/x",
        source_type=ModuleSourceType.youtube,
    )
    version = _version(db_session, ArtifactType.report, module=module)
    scheduled: list[dict[str, Any]] = []

    def fake_retry(**kwargs: Any) -> Exception:
        scheduled.append(kwargs)
        return RuntimeError("retry")

    monkeypatch.setattr(pdf_task.build_artifact_pdf, "retry", fake_retry)
    with pytest.raises(RuntimeError, match="retry"):
        _run_task(version.id)
    assert isinstance(scheduled[0]["exc"], TypesetUnavailable)
    assert _run_task(version.id, retries=pdf_task.MAX_RETRIES) == "gave up"
    assert fake.calls == []
    assert _pdfs(db_session, version) == []
