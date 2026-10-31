"""The once-per-module source step (spec §4 step 3-4, §5, §8).

Before any artifact of a module is generated, NotebookLM must hold the module's
link and PDFs as sources. `ensure_module_sources` does that exactly once, even
when several artifact jobs start together, and resumes after a failure:

- A Redis lock per module serialises the step across workers; whoever holds it
  does the work, the others then find `sources_ready_at` set and return. Its TTL
  is short (a dead holder frees it soon) and refreshed after every sub-step and
  status poll; losing it (Redis restarted) stops the step as transient before
  anything could be added twice. Redis trouble is always transient.
- Every completed sub-step (notebook, link, split parts, each upload) is
  committed straight away in the step's own session, so a retry (or the next
  job) carries on from there instead of adding anything twice.
- Only the §8 messages (`SourceStepError`) are recorded on the module. Jobs that
  were queued before that failure fail fast with the same message; a Retry
  (a newer job) runs the step again. Auth and transient provider errors pass
  through unrecorded (sign-in status / Celery retry handle them).
"""

from __future__ import annotations

import datetime as dt
import functools
import shutil
import tempfile
import time
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any

import redis
from redis.exceptions import RedisError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import session_scope
from app.logging import get_logger
from app.models.module import Module
from app.models.module_source_file import ModuleSourceFile
from app.pipeline.pdf_split import PageTooLarge, PdfUnreadable, plan_parts, write_parts
from app.pipeline.provider import (
    ContentProvider,
    NotebookRef,
    ProviderAuthError,
    ProviderError,
    SourceRef,
    SourceState,
    TransientProviderError,
    UncertainProviderError,
)
from app.storage.keys import source_key
from app.storage.service import Storage, get_storage

log = get_logger("module_sources")

#: the lock's TTL, refreshed while working; longer than the slowest single sub-step
#: (an upload: the provider's 30-minute limit)
_LOCK_TIMEOUT_SEC = 45 * 60
#: how long a job waits for another job's source step, in rounds of `_LOCK_WAIT_ROUND_SEC`
#: (each round counts as progress: the waiter isn't stuck, the holder is bounded)
_LOCK_WAIT_SEC = 7200
_LOCK_WAIT_ROUND_SEC = 60
_POLL_INTERVAL_SEC = 3.0
_SOURCE_READY_TIMEOUT_SEC = 600.0
# NotebookLM may not list a brand-new source straight away
_UNLISTED_GRACE_SEC = 30.0

# Injected in tests (fake clock) so the source-ready waits run instantly.
_sleep: Callable[[float], None] = time.sleep
_now: Callable[[], float] = time.monotonic


class SourceStepError(ProviderError):
    """A module's sources can't be added; the message is the §8 copy shown to admins.

    Not a `TransientProviderError`, so Celery does not auto-retry it."""


def _noop() -> None:
    return None


def ensure_module_sources(
    provider: ContentProvider,
    module_id: uuid.UUID,
    *,
    job_created_at: dt.datetime,
    session_factory: Callable[[], AbstractContextManager[Session]] = session_scope,
    redis_client: redis.Redis[Any] | None = None,
    on_progress: Callable[[], None] = _noop,
) -> NotebookRef:
    """Make sure the module's notebook holds its link and PDFs, all ready; return it.

    `on_progress` is called whenever the step moves on (or waits its turn), for the
    job's progress watchdog."""
    client = redis_client or redis.Redis.from_url(get_settings().redis_url)
    lock = client.lock(
        f"module-sources:{module_id}",
        timeout=_LOCK_TIMEOUT_SEC,
        blocking_timeout=_LOCK_WAIT_ROUND_SEC,
    )
    try:
        _acquire(lock, on_progress)
    except BaseException:
        if redis_client is None:
            client.close()
        raise

    def keep_alive() -> None:
        on_progress()
        try:
            owned = lock.reacquire()
        except RedisError as exc:
            raise TransientProviderError(f"lost this module's source lock (Redis: {exc})") from exc
        if not owned:  # pragma: no cover - redis-py raises instead
            raise TransientProviderError("lost this module's source lock")

    try:
        with session_factory() as session:
            return _run(session, provider, module_id, job_created_at, keep_alive)
    finally:
        try:
            lock.release()
        except RedisError as exc:  # gone with a Redis restart, or expired: the TTL frees it
            log.warning("module_sources.lock_release_failed", error=str(exc))
        if redis_client is None:
            client.close()


def _acquire(lock: Any, on_progress: Callable[[], None]) -> None:
    deadline = time.monotonic() + _LOCK_WAIT_SEC
    while True:
        try:
            if lock.acquire(blocking=True):
                return
        except RedisError as exc:
            raise TransientProviderError(f"source step lock unavailable (Redis: {exc})") from exc
        if time.monotonic() >= deadline:  # pragma: no cover - waited the full 2 h
            raise TransientProviderError("timed out waiting for this module's sources")
        on_progress()  # waiting for another job's source step: not stuck


def _run(
    session: Session,
    provider: ContentProvider,
    module_id: uuid.UUID,
    job_created_at: dt.datetime,
    keep_alive: Callable[[], None] = _noop,
) -> NotebookRef:
    module = session.get(Module, module_id)
    if module is None:
        raise ValueError(f"module {module_id} not found")

    if module.sources_ready_at is not None and module.notebooklm_notebook_id:
        return NotebookRef(notebook_id=module.notebooklm_notebook_id)

    if module.sources_failed_at is not None and job_created_at < module.sources_failed_at:
        # queued before the step failed: same message, no provider calls
        raise SourceStepError(module.sources_error or "NotebookLM couldn't read this module")

    module.sources_error = None
    module.sources_failed_at = None
    session.commit()
    try:
        nb = _add_sources(session, provider, module, keep_alive)
    except SourceStepError as exc:
        module.sources_error = str(exc)
        module.sources_failed_at = func.clock_timestamp()
        session.commit()
        log.warning("module_sources.failed", module_id=str(module_id), error=str(exc))
        raise

    _check_not_reset(session, module, nb)
    module.sources_ready_at = func.now()
    session.commit()
    log.info("module_sources.ready", module_id=str(module_id), notebook=nb.notebook_id)
    return nb


def _add_sources(
    session: Session,
    provider: ContentProvider,
    module: Module,
    keep_alive: Callable[[], None] = _noop,
) -> NotebookRef:
    settings = get_settings()
    storage = get_storage()

    # 1. the notebook
    if not module.notebooklm_notebook_id:
        try:
            module.notebooklm_notebook_id = provider.create_notebook(module.title).notebook_id
        except UncertainProviderError as exc:
            raise SourceStepError(str(exc)) from exc
        session.commit()
        keep_alive()
    nb = NotebookRef(notebook_id=module.notebooklm_notebook_id)

    # source id -> (display name, wait deadline, how to forget it if it fails)
    waiting: dict[str, tuple[str, float | None, Callable[[], None]]] = {}

    # 2. the link
    link = module.source_url
    if link:
        if not module.notebooklm_link_source_id:
            sid = _upload(link, functools.partial(provider.add_source, nb, link))
            _check_not_reset(session, module, nb)
            module.notebooklm_link_source_id = sid
            session.commit()
            keep_alive()
            waiting[sid] = (link, _now() + _SOURCE_READY_TIMEOUT_SEC, _forget_link(module))
        else:
            waiting[module.notebooklm_link_source_id] = (link, None, _forget_link(module))

    # 3. split the PDFs (once; the parts are kept for later rebuilds)
    files = list(module.source_files)
    for sf in files:
        if not sf.parts:
            sf.parts = _split(storage, module, sf)
            session.commit()
            keep_alive()

    # 4. NotebookLM's per-notebook cap
    total = (1 if link else 0) + sum(len(sf.parts) for sf in files)
    if total > settings.notebook_max_sources:
        raise SourceStepError(
            f"This module has {total} sources; NotebookLM allows at most "
            f"{settings.notebook_max_sources} per notebook"
        )

    # 5. upload every part not yet in the notebook
    for sf in files:
        n = len(sf.parts)
        for i, part in enumerate(sf.parts):
            name = part_display_name(sf.file_name, i + 1, n)
            existing: str | None = part.get("notebooklm_source_id")
            if existing:
                waiting[existing] = (name, None, _forget_part(sf, i))
                continue
            path = str(storage.path_for(part["storage_key"]))
            sid = _upload(name, functools.partial(provider.add_file_source, nb, path, name))
            _check_not_reset(session, module, nb)
            _set_part_id(sf, i, sid)
            session.commit()
            keep_alive()
            waiting[sid] = (name, _now() + _SOURCE_READY_TIMEOUT_SEC, _forget_part(sf, i))

    # 6. wait until NotebookLM has processed every source
    _wait_ready(provider, nb, waiting, keep_alive)
    return nb


def part_display_name(file_name: str, i: int, n: int) -> str:
    """The source name NotebookLM shows for part i of n of a PDF.

    NotebookLM refuses an upload (HTTP 400) whose name doesn't end in `.pdf`, so
    the part label goes before the extension: "book.pdf" -> "book (part 1 of 3).pdf".
    A file that isn't split keeps its own name."""
    if n == 1:
        return file_name
    stem = file_name[:-4] if file_name.lower().endswith(".pdf") else file_name
    return f"{stem} (part {i} of {n}).pdf"


def _upload(name: str, call: Callable[[], SourceRef]) -> str:
    """Add one source; NotebookLM refusing it becomes the §8 message."""
    try:
        return call().source_id
    except (ProviderAuthError, TransientProviderError):
        raise
    except UncertainProviderError as exc:
        # NotebookLM may have added it: no automatic retry; the message is for admins
        raise SourceStepError(str(exc)) from exc
    except ProviderError as exc:
        reason = str(exc).strip()
        raise SourceStepError(
            f"NotebookLM couldn't read {name}" + (f": {reason}" if reason else "")
        ) from exc


def _check_not_reset(session: Session, module: Module, nb: NotebookRef) -> None:
    """Abort if Re-run all reset the module's notebook while this step was running.

    Committing now would write this (stale) notebook's ids over the reset; the
    Re-run all job, waiting on the module lock, rebuilds everything instead."""
    with session.no_autoflush:
        current = session.execute(
            select(Module.notebooklm_notebook_id).where(Module.id == module.id)
        ).scalar_one_or_none()
    if current != nb.notebook_id:
        raise TransientProviderError("this module's sources were reset while being added")


def _wait_ready(
    provider: ContentProvider,
    nb: NotebookRef,
    waiting: dict[str, tuple[str, float | None, Callable[[], None]]],
    keep_alive: Callable[[], None] = _noop,
) -> None:
    # sources added by an earlier run get their 10 minutes from now
    start = _now() + _SOURCE_READY_TIMEOUT_SEC
    pending = {sid: (name, dl or start, forget) for sid, (name, dl, forget) in waiting.items()}
    # an id added in this run may go unlisted for its first seconds; any other is gone
    unlisted_until = {
        sid: dl - _SOURCE_READY_TIMEOUT_SEC + _UNLISTED_GRACE_SEC
        for sid, (_name, dl, _forget) in waiting.items()
        if dl is not None
    }
    while pending:
        try:
            states = provider.source_statuses(nb)
        except TransientProviderError as exc:
            # e.g. the session lock busy behind a long chat query: keep waiting until
            # the deadlines (the ids are committed; a requeue would only wait again)
            log.info("module_sources.status_retry", error=str(exc))
            states = None
        for sid, (name, _deadline, forget) in list(pending.items()):
            if states is None:
                break
            state = states.get(sid)
            if state is None and _now() < unlisted_until.get(sid, float("-inf")):
                state = SourceState.pending
            if state is SourceState.ready:
                del pending[sid]
            elif state is SourceState.failed or state is None:
                if state is SourceState.failed:
                    # owner decision 2026-10-31: the failed copy must not stay beside the
                    # re-upload (it counts toward the notebook's source cap)
                    _delete_failed(provider, nb, sid)
                forget()  # a Retry uploads it again
                raise SourceStepError(f"NotebookLM couldn't read {name}")
        if not pending:
            return
        now = _now()
        for name, deadline, _forget in pending.values():
            if now >= deadline:
                # the id is kept: a Retry only waits again
                raise SourceStepError(f"NotebookLM is still processing {name} after 10 minutes")
        keep_alive()
        _sleep(_POLL_INTERVAL_SEC)


def _delete_failed(provider: ContentProvider, nb: NotebookRef, source_id: str) -> None:
    """Delete a source this step added and NotebookLM marked failed. Best effort: a
    failed delete (or one already gone) is logged, and the Retry re-adds it anyway."""
    try:
        provider.delete_source(nb, source_id)
    except Exception as exc:
        log.warning(
            "module_sources.delete_failed_source_failed",
            notebook=nb.notebook_id,
            source_id=source_id,
            error=f"{type(exc).__name__}: {exc}",
        )
    else:
        log.info(
            "module_sources.failed_source_deleted", notebook=nb.notebook_id, source_id=source_id
        )


def _split(storage: Storage, module: Module, sf: ModuleSourceFile) -> list[dict[str, Any]]:
    """Page-range parts for one PDF; a file that fits is used as-is (no copy)."""
    settings = get_settings()
    original = storage.path_for(sf.storage_key)
    try:
        plan = plan_parts(
            original,
            max_bytes=settings.source_part_max_bytes,
            max_words=settings.source_part_max_words,
        )
        if len(plan) == 1 and original.stat().st_size <= settings.source_part_max_bytes:
            part = plan[0]
            return [_part(part.first_page, part.last_page, sf.storage_key)]
        return _write_split(storage, module, sf, original, plan)
    except PdfUnreadable as exc:
        raise SourceStepError(
            f"{sf.file_name} can't be opened (damaged or password-protected)"
        ) from exc
    except PageTooLarge as exc:
        raise SourceStepError(
            f"{sf.file_name} page {exc.page} is larger than NotebookLM's per-source limit"
        ) from exc


def _write_split(
    storage: Storage,
    module: Module,
    sf: ModuleSourceFile,
    original: Path,
    plan: list[Any],
) -> list[dict[str, Any]]:
    stem = _safe_stem(sf.storage_key)
    # Write into a temp dir beside the sources (same filesystem, so the move is
    # a rename), then move each part to its final key. Nothing is left behind
    # if anything fails.
    tmp = Path(tempfile.mkdtemp(prefix="tmp-split-", dir=original.parent))
    moved: list[Path] = []
    try:
        written = write_parts(original, plan, tmp, stem)
        parts: list[dict[str, Any]] = []
        for i, w in enumerate(written, start=1):
            key = source_key(module.course_id, module.id, sf.order_index, stem, part=i)
            target = storage.path_for(key)
            w.path.replace(target)
            moved.append(target)
            parts.append(_part(w.first_page, w.last_page, key))
        return parts
    except BaseException:
        for target in moved:
            target.unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _safe_stem(storage_key: str) -> str:
    """`.../sources/03-my-book.pdf` -> `my-book` (already sanitised at upload)."""
    leaf = storage_key.rsplit("/", 1)[-1].removesuffix(".pdf")
    return leaf.split("-", 1)[1] if "-" in leaf else leaf


def _part(first: int, last: int, key: str) -> dict[str, Any]:
    return {
        "first_page": first,
        "last_page": last,
        "storage_key": key,
        "notebooklm_source_id": None,
    }


def _set_part_id(sf: ModuleSourceFile, index: int, source_id: str | None) -> None:
    # reassign (not mutate) so the JSONB column registers the change
    sf.parts = [
        {**p, "notebooklm_source_id": source_id} if i == index else p
        for i, p in enumerate(sf.parts)
    ]


def _forget_part(sf: ModuleSourceFile, index: int) -> Callable[[], None]:
    return lambda: _set_part_id(sf, index, None)


def _forget_link(module: Module) -> Callable[[], None]:
    def forget() -> None:
        module.notebooklm_link_source_id = None

    return forget
