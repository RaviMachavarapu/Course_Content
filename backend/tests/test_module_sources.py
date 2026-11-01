"""The once-per-module source step: a module's link and PDFs reach NotebookLM
exactly once, before any artifact is generated (spec §4 step 3-4, §5, §8).

FixtureProvider only (spied); a fake clock makes the source-ready waits instant.
"""

from __future__ import annotations

import datetime as dt
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from typing import Any

import pytest
import redis
import sqlalchemy as sa
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.models.artifact import Artifact
from app.models.course import Course
from app.models.enums import ArtifactStatus, ArtifactType, ModuleSourceType
from app.models.module import Module
from app.models.module_source_file import ModuleSourceFile
from app.pipeline import module_sources, orchestrator
from app.pipeline.fixture import FixtureProvider
from app.pipeline.module_sources import (
    SourceStepError,
    ensure_module_sources,
    part_display_name,
)
from app.pipeline.provider import (
    NotebookRef,
    ProviderError,
    SourceRef,
    SourceState,
    StudioJobRef,
    TransientProviderError,
    UncertainProviderError,
)
from app.storage.keys import source_key
from app.storage.service import Storage
from tests.test_pdf_split import _make_pdf

LINK = "https://youtu.be/abc123"
#: a job queued after any recorded failure (the normal case)
LATER = dt.datetime(2100, 1, 1, tzinfo=dt.UTC)
#: a job queued before a recorded failure
EARLIER = dt.datetime(2000, 1, 1, tzinfo=dt.UTC)

Sessions = Callable[[], AbstractContextManager[Session]]


class SpyProvider(FixtureProvider):
    """FixtureProvider that records every source-step call and can misbehave."""

    def __init__(self) -> None:
        super().__init__()
        self.notebooks: list[str] = []
        self.links: list[str] = []
        self.status_polls = 0
        #: display names whose upload NotebookLM rejects (with this reason)
        self.reject: dict[str, str] = {}
        #: display names whose source NotebookLM reports as failed / never ready
        self.fail_state: set[str] = set()
        self.never_ready: set[str] = set()
        #: display names whose source NotebookLM stops listing (for this many polls; -1 = always)
        self.unlisted: dict[str, int] = {}
        #: called once just before the named provider method runs (e.g. a concurrent Re-run all)
        self.before: dict[str, Callable[[], None]] = {}
        self._names: dict[str, str] = {}  # source id -> display name
        self.create_delay = 0.0
        self.generated: list[ArtifactType] = []
        #: raised by `delete_source` (after recording the call)
        self.delete_error: Exception | None = None

    def create_notebook(self, title: str) -> NotebookRef:
        if self.create_delay:
            time.sleep(self.create_delay)  # real sleep: widens the race window
        self.notebooks.append(title)
        return NotebookRef(notebook_id=f"nb-{uuid.uuid4().hex[:8]}")

    def add_source(self, nb: NotebookRef, url: str) -> SourceRef:
        self.links.append(url)
        return super().add_source(nb, url)

    def add_file_source(self, nb: NotebookRef, path: str, display_name: str) -> SourceRef:
        if hook := self.before.pop("add_file_source", None):
            hook()
        if display_name in self.reject:
            raise ProviderError(self.reject[display_name])
        ref = super().add_file_source(nb, path, display_name)
        self._names[ref.source_id] = display_name
        return ref

    def source_statuses(self, nb: NotebookRef) -> dict[str, SourceState]:
        if hook := self.before.pop("source_statuses", None):
            hook()
        self.status_polls += 1
        states = super().source_statuses(nb)
        for sid in states:
            name = self._names.get(sid)
            if name in self.fail_state:
                states[sid] = SourceState.failed
            elif name in self.never_ready:
                states[sid] = SourceState.pending
        hidden = set()
        for sid in list(states):
            name = self._names.get(sid)
            if name in self.unlisted and self.unlisted[name] != 0:
                self.unlisted[name] -= 1
                hidden.add(sid)
        if hidden:
            # a plain dict: an id NotebookLM doesn't list is simply absent
            return {sid: st for sid, st in states.items() if sid not in hidden}
        return states

    def generate(
        self, nb: NotebookRef, kind: ArtifactType, focus_prompt: str, options: dict[str, Any]
    ) -> StudioJobRef:
        self.generated.append(kind)
        return super().generate(nb, kind, focus_prompt, options)

    def delete_source(self, nb: NotebookRef, source_id: str) -> None:
        super().delete_source(nb, source_id)
        if self.delete_error is not None:
            raise self.delete_error

    @property
    def deletes(self) -> list[tuple[str, str]]:
        return [(c[1], c[2]) for c in self.calls if c[0] == "delete_source"]

    @property
    def uploads(self) -> list[str]:
        return [c[3] for c in self.calls if c[0] == "add_file_source"]

    def source_calls(self) -> int:
        return len(self.notebooks) + len(self.links) + len(self.uploads) + self.status_polls


@pytest.fixture
def provider() -> SpyProvider:
    return SpyProvider()


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    now = [1000.0]

    def sleep(seconds: float) -> None:
        now[0] += seconds

    monkeypatch.setattr(module_sources, "_now", lambda: now[0])
    monkeypatch.setattr(module_sources, "_sleep", sleep)
    return now


def _text_pdf(path: Path, pages: int = 2, words: int = 10) -> bytes:
    _make_pdf(path, [(words, 0)] * pages)
    return path.read_bytes()


def _module(
    db: Session,
    storage: Storage,
    tmp_path: Path,
    *,
    link: str | None = LINK,
    pdfs: list[tuple[str, bytes]] = (),  # type: ignore[assignment]
) -> Module:
    course = Course(title="ML 101", slug=f"ml-{uuid.uuid4()}")
    module = Module(
        course=course,
        order_index=0,
        title="Neural Networks",
        source_url=link,
        source_type=ModuleSourceType.youtube if link else ModuleSourceType.pdf,
    )
    db.add(module)
    db.flush()
    for i, (name, data) in enumerate(pdfs):
        key = source_key(course.id, module.id, i, name.removesuffix(".pdf"))
        storage.put(key, data, "application/pdf")
        db.add(
            ModuleSourceFile(
                module_id=module.id,
                order_index=i,
                file_name=name,
                size_bytes=len(data),
                checksum_sha256="0" * 64,
                storage_key=key,
                page_count=1,
                parts=[],
            )
        )
    db.flush()
    db.refresh(module)
    return module


@pytest.fixture
def run(
    db_session: Session,
    source_step_sessions: Sessions,
    redis_client: redis.Redis[str],
    clock: list[float],
) -> Callable[..., NotebookRef]:
    def _run(
        provider: SpyProvider, module: Module, *, job_created_at: dt.datetime = LATER
    ) -> NotebookRef:
        try:
            return ensure_module_sources(
                provider,
                module.id,
                job_created_at=job_created_at,
                session_factory=source_step_sessions,
                redis_client=redis_client,
            )
        finally:
            db_session.expire_all()

    return _run


def _parts(module: Module) -> list[dict[str, Any]]:
    return [p for sf in module.source_files for p in sf.parts]


# -- tests -----------------------------------------------------------------
def test_link_and_pdfs_added_once_then_ready(
    db_session: Session,
    media_storage: Storage,
    tmp_path: Path,
    provider: SpyProvider,
    run: Callable[..., NotebookRef],
) -> None:
    a = _text_pdf(tmp_path / "a.pdf")
    b = _text_pdf(tmp_path / "b.pdf")
    module = _module(db_session, media_storage, tmp_path, pdfs=[("a.pdf", a), ("b.pdf", b)])

    nb = run(provider, module)

    assert len(provider.notebooks) == 1
    assert provider.links == [LINK]
    assert provider.uploads == ["a.pdf", "b.pdf"]
    module = db_session.get(Module, module.id)
    assert module.notebooklm_notebook_id == nb.notebook_id
    assert module.notebooklm_link_source_id
    assert module.sources_ready_at is not None
    assert module.sources_error is None
    for sf in module.source_files:
        # small files are uploaded as-is, from their original key
        assert len(sf.parts) == 1
        assert sf.parts[0]["storage_key"] == sf.storage_key
        assert sf.parts[0]["notebooklm_source_id"]
    paths = [c[2] for c in provider.calls if c[0] == "add_file_source"]
    assert paths == [str(media_storage.path_for(sf.storage_key)) for sf in module.source_files]

    calls = provider.source_calls()
    assert run(provider, module) == nb
    assert provider.source_calls() == calls  # second job: nothing added again


def test_parallel_jobs_add_sources_once(
    db_engine: Engine,
    media_storage: Storage,
    tmp_path: Path,
    redis_client: redis.Redis[str],
    clock: list[float],
) -> None:
    # Two threads need two real connections, so this test commits for real on
    # the test database and deletes what it created afterwards.
    factory = sessionmaker(bind=db_engine, expire_on_commit=False)

    @contextmanager
    def sessions() -> Iterator[Session]:
        s = factory()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    provider = SpyProvider()
    provider.create_delay = 0.3
    data = _text_pdf(tmp_path / "a.pdf")
    with sessions() as db:
        module = _module(db, media_storage, tmp_path, pdfs=[("a.pdf", data)])
        module_id, course_id = module.id, module.course_id

    try:
        barrier = threading.Barrier(2)
        results: list[object] = []

        def job() -> None:
            barrier.wait()
            try:
                results.append(
                    ensure_module_sources(
                        provider,
                        module_id,
                        job_created_at=LATER,
                        session_factory=sessions,
                        redis_client=redis_client,
                    )
                )
            except Exception as exc:  # surfaced by the assertion below
                results.append(exc)

        threads = [threading.Thread(target=job) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert len(results) == 2
        assert all(isinstance(r, NotebookRef) for r in results), results
        assert results[0] == results[1]
        assert len(provider.notebooks) == 1
        assert provider.links == [LINK]
        assert provider.uploads == ["a.pdf"]
    finally:
        with sessions() as db:
            db.execute(sa.delete(Course).where(Course.id == course_id))


def test_oversize_pdf_uploaded_as_named_parts(
    db_session: Session,
    media_storage: Storage,
    tmp_path: Path,
    provider: SpyProvider,
    run: Callable[..., NotebookRef],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "source_part_max_words", 250)
    data = _text_pdf(tmp_path / "book.pdf", pages=4, words=100)
    module = _module(db_session, media_storage, tmp_path, link=None, pdfs=[("book.pdf", data)])

    run(provider, module)

    assert provider.uploads == ["book (part 1 of 2).pdf", "book (part 2 of 2).pdf"]
    module = db_session.get(Module, module.id)
    sf = module.source_files[0]
    assert [(p["first_page"], p["last_page"]) for p in sf.parts] == [(1, 2), (3, 4)]
    keys = [p["storage_key"] for p in sf.parts]
    assert keys == [
        source_key(module.course_id, module.id, 0, "book", part=1),
        source_key(module.course_id, module.id, 0, "book", part=2),
    ]
    paths = [c[2] for c in provider.calls if c[0] == "add_file_source"]
    assert paths == [str(media_storage.path_for(k)) for k in keys]
    # the original plus the two parts, and no leftover temp files
    sources_dir = media_storage.path_for(sf.storage_key).parent
    assert sorted(p.name for p in sources_dir.iterdir()) == sorted(
        [Path(sf.storage_key).name, *(Path(k).name for k in keys)]
    )


def test_upper_case_pdf_parts_end_in_pdf(
    db_session: Session,
    media_storage: Storage,
    tmp_path: Path,
    provider: SpyProvider,
    run: Callable[..., NotebookRef],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # NotebookLM refuses (HTTP 400) a source name that doesn't end in .pdf
    monkeypatch.setattr(get_settings(), "source_part_max_words", 250)
    data = _text_pdf(tmp_path / "notes.pdf", pages=4, words=100)
    module = _module(db_session, media_storage, tmp_path, link=None, pdfs=[("Notes.PDF", data)])

    run(provider, module)

    assert provider.uploads == ["Notes (part 1 of 2).pdf", "Notes (part 2 of 2).pdf"]


def test_part_display_name() -> None:
    assert part_display_name("book.pdf", 1, 1) == "book.pdf"
    assert part_display_name("Notes.PDF", 1, 1) == "Notes.PDF"
    assert part_display_name("book.pdf", 2, 3) == "book (part 2 of 3).pdf"
    assert part_display_name("Notes.PDF", 1, 2) == "Notes (part 1 of 2).pdf"
    assert part_display_name("scan", 1, 2) == "scan (part 1 of 2).pdf"


def test_retry_resumes_incomplete_sources(
    db_session: Session,
    media_storage: Storage,
    tmp_path: Path,
    provider: SpyProvider,
    run: Callable[..., NotebookRef],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "source_part_max_words", 250)
    data = _text_pdf(tmp_path / "book.pdf", pages=4, words=100)
    module = _module(db_session, media_storage, tmp_path, pdfs=[("book.pdf", data)])
    provider.reject["book (part 2 of 2).pdf"] = "Unsupported file"

    with pytest.raises(SourceStepError) as err:
        run(provider, module)
    message = "NotebookLM couldn't read book (part 2 of 2).pdf: Unsupported file"
    assert str(err.value) == message
    module = db_session.get(Module, module.id)
    assert module.sources_error == message
    assert module.sources_failed_at is not None
    assert module.sources_ready_at is None
    parts = _parts(module)
    assert parts[0]["notebooklm_source_id"] and not parts[1]["notebooklm_source_id"]

    provider.reject.clear()
    before = len(provider.uploads)
    nb = run(provider, module)  # the Retry: a job queued after the failure

    assert provider.uploads[before:] == ["book (part 2 of 2).pdf"]
    assert len(provider.notebooks) == 1 and provider.links == [LINK]
    module = db_session.get(Module, module.id)
    assert module.notebooklm_notebook_id == nb.notebook_id
    assert module.sources_ready_at is not None
    assert module.sources_error is None and module.sources_failed_at is None
    assert all(p["notebooklm_source_id"] for p in _parts(module))


def test_failed_source_is_reuploaded_on_retry(
    db_session: Session,
    media_storage: Storage,
    tmp_path: Path,
    provider: SpyProvider,
    run: Callable[..., NotebookRef],
) -> None:
    module = _module(
        db_session, media_storage, tmp_path, pdfs=[("a.pdf", _text_pdf(tmp_path / "a.pdf"))]
    )
    provider.fail_state.add("a.pdf")

    with pytest.raises(SourceStepError, match=r"^NotebookLM couldn't read a\.pdf$"):
        run(provider, module)
    module = db_session.get(Module, module.id)
    assert _parts(module)[0]["notebooklm_source_id"] is None  # cleared → re-upload

    provider.fail_state.clear()
    run(provider, module)
    assert provider.uploads == ["a.pdf", "a.pdf"]
    assert db_session.get(Module, module.id).sources_ready_at is not None


def test_a_failed_source_is_deleted_from_the_notebook_before_the_re_add(
    db_session: Session,
    media_storage: Storage,
    tmp_path: Path,
    provider: SpyProvider,
    run: Callable[..., NotebookRef],
) -> None:
    """Owner decision 2026-10-31: the failed copy doesn't stay beside the new one
    (it would count toward the notebook's source cap)."""
    module = _module(
        db_session, media_storage, tmp_path, pdfs=[("a.pdf", _text_pdf(tmp_path / "a.pdf"))]
    )
    provider.fail_state.add("a.pdf")
    with pytest.raises(SourceStepError):
        run(provider, module)
    nb = db_session.get(Module, module.id).notebooklm_notebook_id
    failed_id = next(sid for sid, name in provider._names.items() if name == "a.pdf")
    assert provider.deletes == [(nb, failed_id)]  # only the failed source, not the link

    provider.fail_state.clear()
    run(provider, module)
    assert provider.uploads == ["a.pdf", "a.pdf"]
    assert provider.deletes == [(nb, failed_id)]


def test_a_failed_delete_does_not_block_the_re_add(
    db_session: Session,
    media_storage: Storage,
    tmp_path: Path,
    provider: SpyProvider,
    run: Callable[..., NotebookRef],
) -> None:
    module = _module(
        db_session, media_storage, tmp_path, pdfs=[("a.pdf", _text_pdf(tmp_path / "a.pdf"))]
    )
    provider.fail_state.add("a.pdf")
    provider.delete_error = ProviderError("source already gone")
    with pytest.raises(SourceStepError, match=r"^NotebookLM couldn't read a\.pdf$"):
        run(provider, module)
    module = db_session.get(Module, module.id)
    assert _parts(module)[0]["notebooklm_source_id"] is None

    provider.fail_state.clear()
    run(provider, module)
    assert provider.uploads == ["a.pdf", "a.pdf"]


def test_jobs_queued_before_failure_fail_fast(
    db_session: Session,
    media_storage: Storage,
    tmp_path: Path,
    provider: SpyProvider,
    run: Callable[..., NotebookRef],
) -> None:
    module = _module(
        db_session, media_storage, tmp_path, pdfs=[("a.pdf", _text_pdf(tmp_path / "a.pdf"))]
    )
    provider.reject["a.pdf"] = "Too big"
    with pytest.raises(SourceStepError) as first:
        run(provider, module)
    failed_at = db_session.get(Module, module.id).sources_failed_at

    later_provider = SpyProvider()
    with pytest.raises(SourceStepError) as second:
        run(later_provider, module, job_created_at=EARLIER)

    assert str(second.value) == str(first.value) == "NotebookLM couldn't read a.pdf: Too big"
    assert later_provider.source_calls() == 0
    assert later_provider.calls == []
    # failing fast doesn't move the failure time (later jobs still retry)
    assert db_session.get(Module, module.id).sources_failed_at == failed_at


@pytest.mark.parametrize("step", ["create_notebook", "add_source", "add_file_source"])
def test_an_uncertain_source_call_fails_the_step_with_its_own_message(
    db_session: Session,
    media_storage: Storage,
    tmp_path: Path,
    provider: SpyProvider,
    run: Callable[..., NotebookRef],
    step: str,
) -> None:
    """NotebookLM may have made the notebook or source anyway: the step fails (no
    automatic retry, jobs queued before fail fast) and admins see the message as-is."""
    module = _module(
        db_session, media_storage, tmp_path, pdfs=[("a.pdf", _text_pdf(tmp_path / "a.pdf"))]
    )
    message = "Lost the connection to NotebookLM; it may have gone through."

    def cut_off() -> None:
        raise UncertainProviderError(message)

    setattr(provider, step, lambda *_a: cut_off())
    with pytest.raises(SourceStepError) as err:
        run(provider, module)
    assert str(err.value) == message
    assert db_session.get(Module, module.id).sources_error == message


def test_legacy_module_skips_source_step(
    db_session: Session,
    media_storage: Storage,
    tmp_path: Path,
    provider: SpyProvider,
    run: Callable[..., NotebookRef],
) -> None:
    module = _module(db_session, media_storage, tmp_path)
    module.notebooklm_notebook_id = "nb-legacy"
    module.sources_ready_at = dt.datetime.now(dt.UTC)
    db_session.flush()

    assert run(provider, module) == NotebookRef(notebook_id="nb-legacy")
    assert provider.source_calls() == 0
    assert provider.calls == []


def test_too_many_sources_message(
    db_session: Session,
    media_storage: Storage,
    tmp_path: Path,
    provider: SpyProvider,
    run: Callable[..., NotebookRef],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "notebook_max_sources", 2)
    pdfs = [(n, _text_pdf(tmp_path / n)) for n in ("a.pdf", "b.pdf")]
    module = _module(db_session, media_storage, tmp_path, pdfs=pdfs)

    with pytest.raises(SourceStepError) as err:
        run(provider, module)

    message = "This module has 3 sources; NotebookLM allows at most 2 per notebook"
    assert str(err.value) == message
    assert db_session.get(Module, module.id).sources_error == message
    assert provider.uploads == []


def test_processing_timeout_message(
    db_session: Session,
    media_storage: Storage,
    tmp_path: Path,
    provider: SpyProvider,
    run: Callable[..., NotebookRef],
    clock: list[float],
) -> None:
    module = _module(
        db_session,
        media_storage,
        tmp_path,
        link=None,
        pdfs=[("a.pdf", _text_pdf(tmp_path / "a.pdf"))],
    )
    provider.never_ready.add("a.pdf")
    start = clock[0]

    with pytest.raises(SourceStepError) as err:
        run(provider, module)

    assert str(err.value) == "NotebookLM is still processing a.pdf after 10 minutes"
    assert 600 <= clock[0] - start < 610
    assert provider.status_polls >= 200  # every 3 s
    module = db_session.get(Module, module.id)
    assert module.sources_error == str(err.value)
    assert _parts(module)[0]["notebooklm_source_id"]  # kept: a Retry only waits

    provider.never_ready.clear()
    run(provider, module)
    assert provider.uploads == ["a.pdf"]
    assert db_session.get(Module, module.id).sources_ready_at is not None


def test_damaged_pdf_message(
    db_session: Session,
    media_storage: Storage,
    tmp_path: Path,
    provider: SpyProvider,
    run: Callable[..., NotebookRef],
) -> None:
    module = _module(
        db_session, media_storage, tmp_path, pdfs=[("broken.pdf", b"%PDF-1.4\nnot a pdf")]
    )

    with pytest.raises(SourceStepError) as err:
        run(provider, module)

    message = "broken.pdf can't be opened (damaged or password-protected)"
    assert str(err.value) == message
    assert db_session.get(Module, module.id).sources_error == message
    assert provider.uploads == []


def test_page_too_large_message(
    db_session: Session,
    media_storage: Storage,
    tmp_path: Path,
    provider: SpyProvider,
    run: Callable[..., NotebookRef],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "source_part_max_bytes", 100)
    module = _module(
        db_session, media_storage, tmp_path, pdfs=[("big.pdf", _text_pdf(tmp_path / "big.pdf"))]
    )

    with pytest.raises(SourceStepError) as err:
        run(provider, module)

    assert str(err.value) == "big.pdf page 1 is larger than NotebookLM's per-source limit"
    assert provider.uploads == []


def test_rerun_all_rebuilds_notebook(
    db_session: Session,
    media_storage: Storage,
    tmp_path: Path,
    provider: SpyProvider,
    run: Callable[..., NotebookRef],
) -> None:
    module = _module(
        db_session, media_storage, tmp_path, pdfs=[("a.pdf", _text_pdf(tmp_path / "a.pdf"))]
    )
    first = run(provider, module)

    orchestrator.start_module_generation(db_session, provider, module.id, [ArtifactType.flashcards])
    db_session.flush()
    second = run(provider, module)

    assert second != first
    assert len(provider.notebooks) == 2
    assert provider.links == [LINK, LINK]
    assert provider.uploads == ["a.pdf", "a.pdf"]
    module = db_session.get(Module, module.id)
    assert module.notebooklm_notebook_id == second.notebook_id
    assert module.sources_ready_at is not None


def test_source_no_longer_listed_is_reuploaded_on_retry(
    db_session: Session,
    media_storage: Storage,
    tmp_path: Path,
    provider: SpyProvider,
    run: Callable[..., NotebookRef],
    clock: list[float],
) -> None:
    module = _module(
        db_session,
        media_storage,
        tmp_path,
        link=None,
        pdfs=[("a.pdf", _text_pdf(tmp_path / "a.pdf"))],
    )
    provider.never_ready.add("a.pdf")
    with pytest.raises(SourceStepError, match="still processing"):
        run(provider, module)  # the id is kept for the Retry
    provider.never_ready.clear()
    provider.unlisted["a.pdf"] = -1  # NotebookLM dropped it

    start = clock[0]
    with pytest.raises(SourceStepError) as err:
        run(provider, module)
    assert str(err.value) == "NotebookLM couldn't read a.pdf"
    assert clock[0] - start < 10  # no 10-minute wait for an id from an earlier run
    module = db_session.get(Module, module.id)
    assert _parts(module)[0]["notebooklm_source_id"] is None  # forgotten → re-upload

    assert provider.deletes == []  # not marked failed: nothing to delete

    provider.unlisted.clear()
    run(provider, module)
    assert provider.uploads == ["a.pdf", "a.pdf"]
    assert db_session.get(Module, module.id).sources_ready_at is not None


def test_new_source_not_yet_listed_is_pending_for_30_seconds(
    db_session: Session,
    media_storage: Storage,
    tmp_path: Path,
    provider: SpyProvider,
    run: Callable[..., NotebookRef],
) -> None:
    module = _module(
        db_session,
        media_storage,
        tmp_path,
        link=None,
        pdfs=[("a.pdf", _text_pdf(tmp_path / "a.pdf"))],
    )
    provider.unlisted["a.pdf"] = 5  # listed from the 6th poll (~15 s)
    run(provider, module)
    assert provider.uploads == ["a.pdf"]
    assert db_session.get(Module, module.id).sources_ready_at is not None


def test_new_source_never_listed_fails_after_30_seconds(
    db_session: Session,
    media_storage: Storage,
    tmp_path: Path,
    provider: SpyProvider,
    run: Callable[..., NotebookRef],
    clock: list[float],
) -> None:
    module = _module(
        db_session,
        media_storage,
        tmp_path,
        link=None,
        pdfs=[("a.pdf", _text_pdf(tmp_path / "a.pdf"))],
    )
    provider.unlisted["a.pdf"] = -1
    start = clock[0]
    with pytest.raises(SourceStepError) as err:
        run(provider, module)
    assert str(err.value) == "NotebookLM couldn't read a.pdf"
    assert 30 <= clock[0] - start < 40
    assert _parts(db_session.get(Module, module.id))[0]["notebooklm_source_id"] is None


@pytest.mark.parametrize("during", ["add_file_source", "source_statuses"])
def test_rerun_all_during_source_step_aborts_the_step(
    db_session: Session,
    media_storage: Storage,
    tmp_path: Path,
    provider: SpyProvider,
    run: Callable[..., NotebookRef],
    source_step_sessions: Sessions,
    during: str,
) -> None:
    module = _module(
        db_session,
        media_storage,
        tmp_path,
        link=None,
        pdfs=[("a.pdf", _text_pdf(tmp_path / "a.pdf"))],
    )

    def rerun_all() -> None:
        with source_step_sessions() as other:
            orchestrator.start_module_generation(
                other, provider, module.id, [ArtifactType.flashcards]
            )

    provider.before[during] = rerun_all
    with pytest.raises(TransientProviderError):
        run(provider, module)

    module = db_session.get(Module, module.id)
    # Re-run all's reset stands: the stale step committed nothing over it
    assert module.notebooklm_notebook_id is None
    assert module.sources_ready_at is None
    assert _parts(module)[0]["notebooklm_source_id"] is None

    nb = run(provider, module)  # the Re-run all job builds a fresh notebook
    module = db_session.get(Module, module.id)
    assert module.notebooklm_notebook_id == nb.notebook_id
    assert len(provider.notebooks) == 2
    assert module.sources_ready_at is not None


def test_artifact_error_shows_source_message(
    db_session: Session,
    media_storage: Storage,
    tmp_path: Path,
    provider: SpyProvider,
    clock: list[float],
) -> None:
    module = _module(
        db_session, media_storage, tmp_path, pdfs=[("broken.pdf", b"%PDF-1.4\nnot a pdf")]
    )
    artifact = orchestrator.ensure_artifacts(db_session, module)[ArtifactType.flashcards]

    with pytest.raises(SourceStepError):
        orchestrator.run_artifact_generation(db_session, provider, artifact.id)

    artifact = db_session.get(Artifact, artifact.id)
    assert artifact.status is ArtifactStatus.error
    assert artifact.last_error == "broken.pdf can't be opened (damaged or password-protected)"
    assert provider.generated == []  # no Studio request was made


# -- Redis trouble, lock keep-alive, transient status errors (review 2026-10-29) --------
class _LockProxy:
    def __init__(self, real: Any, owner: _FlakyRedis) -> None:
        self.real = real
        self.owner = owner

    def acquire(self, *args: Any, **kwargs: Any) -> bool:
        if self.owner.acquire_error is not None:
            raise self.owner.acquire_error
        if self.owner.busy_for > 0:
            self.owner.busy_for -= 1
            return False
        return bool(self.real.acquire(*args, **kwargs))

    def reacquire(self) -> bool:
        self.owner.reacquired += 1
        if self.owner.reacquire_error is not None:
            raise self.owner.reacquire_error
        return bool(self.real.reacquire())

    def release(self) -> None:
        if self.owner.release_error is not None:
            raise self.owner.release_error
        self.real.release()


class _FlakyRedis:
    def __init__(self, real: redis.Redis[str]) -> None:
        self.real = real
        self.acquire_error: Exception | None = None
        self.reacquire_error: Exception | None = None
        self.release_error: Exception | None = None
        self.busy_for = 0
        self.reacquired = 0
        self.ttl: float | None = None

    def lock(self, name: str, **kwargs: Any) -> _LockProxy:
        self.ttl = kwargs.get("timeout")
        return _LockProxy(self.real.lock(name, **kwargs), self)

    def close(self) -> None:
        pass


def _flaky_run(flaky: _FlakyRedis, sessions: Sessions, db: Session) -> Callable[..., NotebookRef]:
    def _run(provider: SpyProvider, module: Module, **kwargs: Any) -> NotebookRef:
        try:
            return ensure_module_sources(
                provider,
                module.id,
                job_created_at=LATER,
                session_factory=sessions,
                redis_client=flaky,  # type: ignore[arg-type]
                **kwargs,
            )
        finally:
            db.expire_all()

    return _run


def test_redis_down_when_taking_the_module_lock_is_transient(
    db_session: Session,
    media_storage: Storage,
    tmp_path: Path,
    provider: SpyProvider,
    source_step_sessions: Sessions,
    redis_client: redis.Redis[str],
    clock: list[float],
) -> None:
    module = _module(db_session, media_storage, tmp_path)
    flaky = _FlakyRedis(redis_client)
    flaky.acquire_error = redis.exceptions.ConnectionError("restarting")
    with pytest.raises(TransientProviderError, match="Redis"):
        _flaky_run(flaky, source_step_sessions, db_session)(provider, module)
    assert provider.source_calls() == 0
    assert db_session.get(Module, module.id).sources_error is None


@pytest.mark.parametrize(
    "error",
    [redis.exceptions.ConnectionError("restarting"), redis.exceptions.LockNotOwnedError("gone")],
    ids=["down", "lost"],
)
def test_a_failed_module_lock_release_keeps_the_finished_step(
    error: Exception,
    db_session: Session,
    media_storage: Storage,
    tmp_path: Path,
    provider: SpyProvider,
    source_step_sessions: Sessions,
    redis_client: redis.Redis[str],
    clock: list[float],
) -> None:
    module = _module(db_session, media_storage, tmp_path)
    flaky = _FlakyRedis(redis_client)
    flaky.release_error = error
    nb = _flaky_run(flaky, source_step_sessions, db_session)(provider, module)
    assert db_session.get(Module, module.id).sources_ready_at is not None
    assert nb.notebook_id


def test_losing_the_module_lock_mid_step_requeues_and_the_retry_resumes(
    db_session: Session,
    media_storage: Storage,
    tmp_path: Path,
    provider: SpyProvider,
    source_step_sessions: Sessions,
    redis_client: redis.Redis[str],
    clock: list[float],
) -> None:
    """Redis restarted while uploading: stop before another job can upload twice; the
    retry carries on from the committed sub-steps."""
    pdfs = [(f"{n}.pdf", _text_pdf(tmp_path / f"{n}.pdf")) for n in ("a", "b")]
    module = _module(db_session, media_storage, tmp_path, pdfs=pdfs)
    flaky = _FlakyRedis(redis_client)
    flaky.reacquire_error = redis.exceptions.LockNotOwnedError("gone")
    run = _flaky_run(flaky, source_step_sessions, db_session)
    with pytest.raises(TransientProviderError, match="lock"):
        run(provider, module)
    assert provider.uploads == []  # stopped after the link, before any upload
    flaky.reacquire_error = None
    run(provider, module)
    assert provider.links == [LINK]  # not added twice
    assert provider.uploads == ["a.pdf", "b.pdf"]


def test_the_module_lock_is_kept_alive_while_working(
    db_session: Session,
    media_storage: Storage,
    tmp_path: Path,
    provider: SpyProvider,
    source_step_sessions: Sessions,
    redis_client: redis.Redis[str],
    clock: list[float],
) -> None:
    """A step longer than the lock's TTL must not lose it: the TTL is short (a dead
    holder frees it soon) and refreshed after each sub-step and status poll."""
    pdfs = [(f"{n}.pdf", _text_pdf(tmp_path / f"{n}.pdf")) for n in ("a", "b", "c")]
    module = _module(db_session, media_storage, tmp_path, pdfs=pdfs)
    provider.unlisted["c.pdf"] = 3  # a few extra status polls
    flaky = _FlakyRedis(redis_client)
    _flaky_run(flaky, source_step_sessions, db_session)(provider, module)
    assert flaky.ttl is not None and flaky.ttl <= 3600
    assert flaky.reacquired >= 3 + 3


def test_waiting_for_the_module_lock_counts_as_progress(
    db_session: Session,
    media_storage: Storage,
    tmp_path: Path,
    provider: SpyProvider,
    source_step_sessions: Sessions,
    redis_client: redis.Redis[str],
    clock: list[float],
) -> None:
    module = _module(db_session, media_storage, tmp_path)
    flaky = _FlakyRedis(redis_client)
    flaky.busy_for = 3  # another job holds it for three wait rounds
    beats: list[int] = []
    _flaky_run(flaky, source_step_sessions, db_session)(
        provider, module, on_progress=lambda: beats.append(1)
    )
    assert len(beats) >= 3


def test_a_transient_status_error_keeps_waiting_for_the_sources(
    db_session: Session,
    media_storage: Storage,
    tmp_path: Path,
    provider: SpyProvider,
    run: Callable[..., NotebookRef],
) -> None:
    """The session lock busy behind a long chat query must not fail the source step."""
    module = _module(db_session, media_storage, tmp_path)
    failures = [TransientProviderError("lock busy")] * 2

    def busy() -> None:
        if failures:
            raise failures.pop()

    provider.before["source_statuses"] = busy
    nb = run(provider, module)
    assert nb.notebook_id
    assert db_session.get(Module, module.id).sources_ready_at is not None
