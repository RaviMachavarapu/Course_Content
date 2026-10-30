"""Celery task: prepare a student's next fresh quiz question set from NotebookLM chat
(adaptive quiz, spec §4.3).

Runs on its own `quiz` queue (the `worker-quiz` service, one at a time), so chat
queries never take a generation slot. The API enqueues it with `enqueue_prepare`
whenever a student starts an attempt.

Steps: claim a `preparing` chat set for (artifact, student) — the partial unique index
`uq_quiz_question_set_pending_chat` makes the claim idempotent (a second call while a
set is preparing or ready does nothing); ask chat for N questions (N = the published
Studio quiz's question count, default 10) avoiding the student's most recent 60 seen
questions; parse and validate; ask once more for any shortfall; store the set `ready`
(at least min(5, N) questions, at most N) or `failed`, with the validation report either way.

Chat unavailable (a transient provider error, a 5xx/408 answer, the connector unreachable),
unreadable source PDFs or a database connection error is
retried with exponential back-off (30 s, 1, 2, 4, 8 min); the set stays `preparing`
meanwhile and is marked `failed` when the retries run out. Artifact status is never
touched.

Language and difficulty: a set is written in the language and at the difficulty the admin
chose for the quiz (`Artifact.generation_options`), recorded on the set as
`validation_report["prepared_for"]`. A `preparing` or `ready` set whose `prepared_for` no
longer matches the quiz's options (or has none: prepared before this rule) is discarded
(`failed`, `validation_report["discarded"]`) by `discard_stale_sets` — here before claiming,
and by the student API before serving — and a new one is prepared.

Heartbeat: the task stamps `heartbeat_at` on its set when it claims (or resumes) it,
before each chat round and before scheduling a retry. A `preparing` set silent for
`STALE_AFTER` (its worker died; `heartbeat_at`, else `created_at`) is failed and replaced
by the next call. A slow task that finds its set replaced stops ("superseded") without
asking chat again, retrying or writing anything: every write is by set id and only while
the set is still `preparing`, so the replacement is never touched.
"""

from __future__ import annotations

import datetime as dt
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx
import redis.exceptions
from celery import Task, shared_task
from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.db.session import session_scope
from app.logging import get_logger
from app.models.artifact import Artifact
from app.models.enums import ArtifactType, QuizSetSource, QuizSetStatus
from app.models.quiz_question_set import QuizQuestionSet
from app.pipeline.factory import get_content_provider
from app.pipeline.provider import (
    ContentProvider,
    GenerationTimeout,
    NotebookRef,
    ProviderError,
    TransientProviderError,
)
from app.services import quiz_generation as qg

log = get_logger("tasks.quiz")

QUEUE = "quiz"
DEFAULT_QUESTION_COUNT = 10
MAX_RETRIES = 5
RETRY_BASE_SEC = 30
#: a `preparing` set whose heartbeat is this old was abandoned (its worker died). The
#: longest silence of a live task is the last back-off, 8 min (RETRY_BASE_SEC * 2**4),
#: plus waiting for the single quiz worker to finish another student's run (up to ~10 min:
#: two 5-minute chat queries); one chat query alone is at most 5 min. 20 min covers that.
#: It is deliberately longer than the student API's `PREPARING_PATIENCE` (15 min): the
#: student is told "try later" first, and a set is only replaced once it is clearly dead.
#: Replacing a live set by mistake is safe (the slow task stops as "superseded"); it only
#: wastes a chat query.
STALE_AFTER = dt.timedelta(minutes=20)

_PENDING_WHERE = text("source = 'chat' AND status IN ('preparing', 'ready')")
#: chat unavailable (timeout, locked session, 5xx/408, connector unreachable during a restart)
_CHAT_UNAVAILABLE = (
    TransientProviderError,
    GenerationTimeout,
    httpx.TransportError,
    # Redis (the NotebookLM session lock) restarting or unreachable
    redis.exceptions.ConnectionError,
    redis.exceptions.TimeoutError,
)
_RETRYABLE = (*_CHAT_UNAVAILABLE, qg.SourceTextUnavailable, OperationalError)
FINISH_ATTEMPTS = 4
FINISH_BACKOFF_SEC = 0.5


class _Done(Exception):
    """Stop early with this outcome (nothing to prepare)."""

    def __init__(self, outcome: str) -> None:
        super().__init__(outcome)
        self.outcome = outcome


@dataclass
class _Job:
    set_id: uuid.UUID
    n: int
    seen: list[str]
    notebook_id: str | None
    source_text: str | None
    #: the module also has a link: quotes not in its PDFs are kept, flagged
    link_source: bool = False
    language: str = "en"
    difficulty: str = "medium"


@dataclass
class _Result:
    questions: list[dict[str, Any]] = field(default_factory=list)
    report: dict[str, Any] = field(default_factory=dict)

    @property
    def ready(self) -> bool:
        return bool(self.questions)


# -- helpers (also used by the API and tests) -----------------------------------


def studio_questions(artifact: Artifact) -> list[dict[str, Any]]:
    """The published Studio quiz's questions ([] when unpublished)."""
    version = next((v for v in artifact.versions if v.id == artifact.published_version_id), None)
    if version is None or not version.content_json:
        return []
    return list(version.content_json.get("questions", []))


def seen_questions(
    db: Session, artifact: Artifact, user_id: uuid.UUID, limit: int | None = None
) -> list[str]:
    """Every question text the student has seen for this quiz, most recent first: the
    questions of their used sets (newest set first), then the Studio quiz (always their
    attempt 1). Exact repeats are listed once. `limit` keeps the most recent ones only
    (the prompt's avoid list is the first `qg.MAX_AVOID`; validation uses all of them)."""
    sets = db.scalars(
        select(QuizQuestionSet)
        .where(
            QuizQuestionSet.artifact_id == artifact.id,
            QuizQuestionSet.user_id == user_id,
            QuizQuestionSet.status == QuizSetStatus.used,
        )
        .order_by(QuizQuestionSet.created_at.desc(), QuizQuestionSet.id)
    )
    groups = [s.questions for s in sets] + [studio_questions(artifact)]
    texts: list[str] = []
    for questions in groups:
        for q in questions:
            t = q.get("question") if isinstance(q, dict) else None
            if isinstance(t, str) and t.strip() and t not in texts:
                texts.append(t)
    return texts if limit is None else texts[:limit]


def published_options(artifact: Artifact) -> dict[str, Any]:
    """The generation options of the quiz's PUBLISHED version (owner decision 2026-10-30:
    retakes follow the published quiz; a Redo, failed or not yet published, changes
    nothing). Falls back to the artifact's options when the published version has none
    recorded (or nothing is published)."""
    version = next((v for v in artifact.versions if v.id == artifact.published_version_id), None)
    if version is not None and version.generation_options:
        return dict(version.generation_options)
    return dict(artifact.generation_options or {})


def wanted_for(artifact: Artifact) -> dict[str, str]:
    """The language and difficulty the quiz's fresh sets must be prepared for: those of
    the published quiz version."""
    return qg.prepared_for(published_options(artifact))


def discard_stale_sets(db: Session, artifact: Artifact, user_id: uuid.UUID) -> int:
    """Discard the student's `preparing`/`ready` chat sets prepared for another language or
    difficulty than the published quiz version's options (row-locked; a task still filling a
    discarded set finds it no longer `preparing` and stops as "superseded"). Returns how
    many."""
    wanted = wanted_for(artifact)
    pending = db.scalars(
        select(QuizQuestionSet)
        .where(
            QuizQuestionSet.artifact_id == artifact.id,
            QuizQuestionSet.user_id == user_id,
            QuizQuestionSet.source == QuizSetSource.chat,
            QuizQuestionSet.status.in_([QuizSetStatus.preparing, QuizSetStatus.ready]),
        )
        .with_for_update()
    ).all()
    discarded = 0
    for qs in pending:
        report = qs.validation_report if isinstance(qs.validation_report, dict) else {}
        had = report.get("prepared_for")
        if had == wanted:
            continue
        was = f"{had['language']}/{had['difficulty']}" if isinstance(had, dict) else "unknown"
        qs.status = QuizSetStatus.failed
        qs.validation_report = {
            **report,
            "discarded": True,
            "error": (
                f"discarded: prepared for {was}; the quiz is now "
                f"{wanted['language']}/{wanted['difficulty']}"
            ),
        }
        discarded += 1
        log.info(
            "quiz.stale_set_discarded",
            set_id=str(qs.id),
            prepared_for=was,
            wanted=f"{wanted['language']}/{wanted['difficulty']}",
        )
    if discarded:
        db.flush()
    return discarded


def enqueue_prepare(artifact_id: uuid.UUID | str, user_id: uuid.UUID | str) -> None:
    """Queue preparation of the student's next set. Call after the DB commit that
    started the attempt. A broker error is logged, never raised: the student's
    current attempt is unaffected and the next start enqueues again."""
    try:
        prepare_quiz_set.apply_async(
            kwargs={"artifact_id": str(artifact_id), "user_id": str(user_id)}, queue=QUEUE
        )
    except Exception as exc:
        log.warning(
            "quiz.enqueue_failed",
            artifact_id=str(artifact_id),
            user_id=str(user_id),
            error=str(exc),
        )


# -- task ------------------------------------------------------------------------


@shared_task(bind=True, name="app.tasks.prepare_quiz_set", queue=QUEUE)
def prepare_quiz_set(self: Task, artifact_id: str, user_id: str, set_id: str | None = None) -> str:
    """Returns "ready", "failed", "gave up" (out of retries), "exists" (a set is already
    preparing or ready), "superseded" (this run's set was replaced meanwhile), "off"
    (fresh retakes switched off) or "skipped" (not a quiz)."""
    aid, uid = uuid.UUID(artifact_id), uuid.UUID(user_id)
    ctx = {"artifact_id": artifact_id, "user_id": user_id}
    try:
        with session_scope() as db:
            claimed = _claim(db, aid, uid, uuid.UUID(set_id) if set_id else None)
    except _Done as done:
        log.info("quiz.prepare_skipped", outcome=done.outcome, **ctx)
        return done.outcome

    try:
        with session_scope() as db:
            job = _load_job(db, claimed, aid, uid)
        if job.notebook_id is None:
            result = _Result(report={"error": "the module has no NotebookLM notebook"})
        else:
            result = _generate(get_content_provider(), job)
    except _Done as done:
        if done.outcome == "superseded":
            log.warning("quiz.superseded", set_id=str(claimed), **ctx)
        else:
            log.info("quiz.prepare_skipped", outcome=done.outcome, **ctx)
        return done.outcome
    except _RETRYABLE as exc:
        retries = self.request.retries
        if retries >= MAX_RETRIES:
            log.error("quiz.gave_up", attempts=retries + 1, error=str(exc), **ctx)
            _finish(claimed, _Result(report={"error": f"gave up: {exc}"}))
            return "gave up"
        if not _heartbeat(claimed):  # replaced meanwhile: nothing left to retry for
            log.warning("quiz.superseded", set_id=str(claimed), **ctx)
            return "superseded"
        countdown = RETRY_BASE_SEC * 2**retries
        log.warning("quiz.retry", countdown=countdown, error=str(exc), **ctx)
        raise self.retry(
            args=(),
            kwargs={**ctx, "set_id": str(claimed)},
            exc=exc,
            countdown=countdown,
            max_retries=MAX_RETRIES,
        ) from exc
    except Exception as exc:  # a permanent provider error, a sign-in problem, a bug
        log.exception("quiz.failed", error=f"{type(exc).__name__}: {exc}", **ctx)
        _finish(claimed, _Result(report={"error": f"{type(exc).__name__}: {exc}"}))
        return "failed"

    if not _finish(claimed, result):
        log.warning("quiz.superseded", set_id=str(claimed), **ctx)
        return "superseded"
    outcome = "ready" if result.ready else "failed"
    log.info(
        "quiz.prepared",
        outcome=outcome,
        set_id=str(claimed),
        requested=result.report.get("requested"),
        queries=len(result.report.get("rounds", [])),
        kept=sum(len(r["kept"]) for r in result.report.get("rounds", [])),
        dropped=sum(len(r["dropped"]) for r in result.report.get("rounds", [])),
        served=len(result.questions),
        error=result.report.get("error"),
        **ctx,
    )
    return outcome


def _claim(db: Session, aid: uuid.UUID, uid: uuid.UUID, set_id: uuid.UUID | None) -> uuid.UUID:
    """The id of the `preparing` set this run fills; raises `_Done` when there is
    nothing to do. A retry (`set_id` given) resumes its own set."""
    if set_id is not None:
        existing = db.get(QuizQuestionSet, set_id, with_for_update=True)
        if existing is None or existing.status is not QuizSetStatus.preparing:
            raise _Done("exists")
        artifact = db.get(Artifact, aid)
        if artifact is None or not discard_stale_sets(db, artifact, uid):
            existing.heartbeat_at = func.now()
            return set_id
        # the quiz's language/difficulty changed meanwhile: prepare a new set instead

    artifact = db.get(Artifact, aid)
    if artifact is None or artifact.type is not ArtifactType.quiz:
        raise _Done("skipped")
    if not artifact.module.quiz_fresh_retakes:
        raise _Done("off")

    discard_stale_sets(db, artifact, uid)
    wanted = wanted_for(artifact)
    new_id = _insert_preparing(db, aid, uid, wanted)
    if new_id is not None:
        return new_id
    pending = db.scalars(
        select(QuizQuestionSet)
        .where(
            QuizQuestionSet.artifact_id == aid,
            QuizQuestionSet.user_id == uid,
            QuizQuestionSet.source == QuizSetSource.chat,
            QuizQuestionSet.status == QuizSetStatus.preparing,
            func.coalesce(QuizQuestionSet.heartbeat_at, QuizQuestionSet.created_at)
            < dt.datetime.now(tz=dt.UTC) - STALE_AFTER,
        )
        .with_for_update(skip_locked=True)
    ).first()
    if pending is None:  # preparing (recently) or ready: nothing to do
        raise _Done("exists")
    pending.status = QuizSetStatus.failed
    pending.validation_report = {"error": "abandoned: preparation did not finish"}
    db.flush()
    log.warning("quiz.abandoned_set_replaced", set_id=str(pending.id))
    new_id = _insert_preparing(db, aid, uid, wanted)
    if new_id is None:
        raise _Done("exists")
    return new_id


def _insert_preparing(
    db: Session, aid: uuid.UUID, uid: uuid.UUID, wanted: dict[str, str]
) -> uuid.UUID | None:
    """Insert a `preparing` chat set for `wanted` (language, difficulty); None when one is
    already preparing or ready (a concurrent insert waits for the other transaction, then
    does nothing)."""
    stmt = (
        pg_insert(QuizQuestionSet)
        .values(
            id=uuid.uuid4(),
            artifact_id=aid,
            user_id=uid,
            source=QuizSetSource.chat,
            status=QuizSetStatus.preparing,
            questions=[],
            validation_report={"prepared_for": wanted},
            heartbeat_at=func.now(),
        )
        .on_conflict_do_nothing(
            index_elements=["artifact_id", "user_id"], index_where=_PENDING_WHERE
        )
        .returning(QuizQuestionSet.id)
    )
    return db.execute(stmt).scalar_one_or_none()


def _heartbeat(set_id: uuid.UUID) -> bool:
    """Stamp the set's heartbeat; False when it is no longer `preparing` (replaced as
    abandoned, or finished). A database error is logged and ignored (True): a missed
    beat is harmless, and the caller's own error handling covers a database outage."""
    try:
        with session_scope() as db:
            updated = db.execute(
                update(QuizQuestionSet)
                .where(
                    QuizQuestionSet.id == set_id,
                    QuizQuestionSet.status == QuizSetStatus.preparing,
                )
                .values(heartbeat_at=func.now())
            )
            return bool(getattr(updated, "rowcount", 0))
    except OperationalError as exc:
        log.warning("quiz.heartbeat_failed", set_id=str(set_id), error=str(exc))
        return True


def _beat_or_stop(set_id: uuid.UUID) -> None:
    """Heartbeat before a chat round; stop when the set was replaced meanwhile."""
    if not _heartbeat(set_id):
        raise _Done("superseded")


def _load_job(db: Session, set_id: uuid.UUID, aid: uuid.UUID, uid: uuid.UUID) -> _Job:
    artifact = db.get(Artifact, aid)
    if artifact is None:  # deleted meanwhile; the set went with it (cascade)
        raise _Done("skipped")
    module = artifact.module
    qs = db.get(QuizQuestionSet, set_id)
    recorded = qs.validation_report.get("prepared_for") if qs is not None else None
    wanted = qg.prepared_for(recorded if isinstance(recorded, dict) else None)
    source_text = qg.module_source_text(module) if module.notebooklm_notebook_id else None
    return _Job(
        set_id=set_id,
        n=len(studio_questions(artifact)) or DEFAULT_QUESTION_COUNT,
        seen=seen_questions(db, artifact, uid),
        notebook_id=module.notebooklm_notebook_id,
        source_text=source_text,
        link_source=bool(module.source_url),
        language=wanted["language"],
        difficulty=wanted["difficulty"],
    )


def _round(
    number: int,
    requested: int,
    parsed: list[Any],
    kept: list[dict[str, Any]],
    dropped: list[dict[str, Any]],
    unverified: list[dict[str, Any]],
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "round": number,
        "requested": requested,
        "parsed": len(parsed),
        "kept": [q["question"] for q in kept],
        "dropped": dropped,
    }
    if unverified:
        out["unverified"] = unverified
    return out


def _validate(
    job: _Job, parsed: list[Any], seen: list[str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    unverified: list[dict[str, Any]] = []
    kept, dropped = qg.validate(
        parsed,
        seen=seen,
        source_text=job.source_text,
        link_source=job.link_source,
        unverified=unverified,
    )
    return kept, dropped, unverified


def _generate(provider: ContentProvider, job: _Job) -> _Result:
    """Ask chat (once more for a shortfall), validate, and build the set + report."""
    nb = NotebookRef(notebook_id=job.notebook_id or "")
    report: dict[str, Any] = {"requested": job.n, "seen": len(job.seen), "rounds": []}

    _beat_or_stop(job.set_id)
    style = {"language": job.language, "difficulty": job.difficulty}
    parsed = qg.parse_questions(provider.query(nb, qg.build_prompt(job.n, job.seen, **style)))
    kept, dropped, unverified = _validate(job, parsed, job.seen)
    report["rounds"].append(_round(1, job.n, parsed, kept, dropped, unverified))

    if len(kept) < job.n:
        short = job.n - len(kept)
        kept_texts = [q["question"] for q in kept]
        _beat_or_stop(job.set_id)
        try:
            answer = provider.query(nb, qg.build_prompt(short, kept_texts + job.seen, **style))
        except (ProviderError, httpx.TransportError) as exc:
            if len(kept) < qg.min_served(job.n):
                raise  # transient: retry the whole preparation; otherwise the set fails
            report["reask_error"] = f"{type(exc).__name__}: {exc}"  # serve round 1's
        else:
            parsed = qg.parse_questions(answer)
            more, dropped, unverified = _validate(job, parsed, kept_texts + job.seen)
            report["rounds"].append(_round(2, short, parsed, more, dropped, unverified))
            kept += more

    served = kept[: job.n]
    report["served"] = len(served)
    needed = qg.min_served(job.n)
    if len(served) < needed:
        report["error"] = f"only {len(served)} valid question(s), fewer than {needed} needed"
        return _Result(report=report)
    return _Result(questions=served, report=report)


def _finish(set_id: uuid.UUID, result: _Result) -> bool:
    """Store the outcome on the set if it is still `preparing`; False when it no longer
    is (nothing written). A database connection error is retried a few times with a short
    back-off so questions that already cost chat queries are not thrown away."""
    for attempt in range(FINISH_ATTEMPTS):
        try:
            return _write(set_id, result)
        except OperationalError as exc:
            if attempt == FINISH_ATTEMPTS - 1:
                raise
            delay = FINISH_BACKOFF_SEC * 2**attempt
            log.warning("quiz.finish_retry", set_id=str(set_id), delay=delay, error=str(exc))
            time.sleep(delay)
    raise AssertionError("unreachable")


def _write(set_id: uuid.UUID, result: _Result) -> bool:
    with session_scope() as db:
        qs = db.get(QuizQuestionSet, set_id, with_for_update=True)
        if qs is None or qs.status is not QuizSetStatus.preparing:
            return False
        qs.status = QuizSetStatus.ready if result.ready else QuizSetStatus.failed
        qs.questions = result.questions if result.ready else []
        recorded = qs.validation_report.get("prepared_for") if qs.validation_report else None
        qs.validation_report = {**result.report, "prepared_for": recorded}
        return True
