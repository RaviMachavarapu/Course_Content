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
(at least 5 questions, at most N) or `failed`, with the validation report either way.

A transient provider error, unreadable source PDFs or a database connection error is
retried with exponential back-off (30 s, 1, 2, 4, 8 min); the set stays `preparing`
meanwhile and is marked `failed` when the retries run out. Artifact status is never
touched. A `preparing` set older than `STALE_AFTER` (its worker died) is failed and
replaced by the next call.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass, field
from typing import Any

from celery import Task, shared_task
from sqlalchemy import select, text
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
#: a `preparing` set this old was abandoned (worst case for a live one: 5 retries of
#: back-off plus two 5-minute chat queries per run is about 75 minutes)
STALE_AFTER = dt.timedelta(hours=2)

_PENDING_WHERE = text("source = 'chat' AND status IN ('preparing', 'ready')")
_RETRYABLE = (TransientProviderError, qg.SourceTextUnavailable, OperationalError)


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


@dataclass
class _Result:
    questions: list[dict[str, Any]] = field(default_factory=list)
    report: dict[str, Any] = field(default_factory=dict)

    @property
    def ready(self) -> bool:
        return len(self.questions) >= qg.MIN_SERVED


# -- helpers (also used by the API and tests) -----------------------------------


def studio_questions(artifact: Artifact) -> list[dict[str, Any]]:
    """The published Studio quiz's questions ([] when unpublished)."""
    version = next((v for v in artifact.versions if v.id == artifact.published_version_id), None)
    if version is None or not version.content_json:
        return []
    return list(version.content_json.get("questions", []))


def seen_questions(db: Session, artifact: Artifact, user_id: uuid.UUID) -> list[str]:
    """Question texts the student has seen for this quiz, most recent first, at most
    `qg.MAX_AVOID`: the questions of their used sets (newest set first), then the Studio
    quiz (always their attempt 1). Exact repeats are listed once."""
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
    return texts[: qg.MAX_AVOID]


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
    preparing or ready), "off" (fresh retakes switched off) or "skipped" (not a quiz)."""
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
        log.info("quiz.prepare_skipped", outcome=done.outcome, **ctx)
        return done.outcome
    except _RETRYABLE as exc:
        retries = self.request.retries
        if retries >= MAX_RETRIES:
            log.error("quiz.gave_up", attempts=retries + 1, error=str(exc), **ctx)
            _finish(claimed, _Result(report={"error": f"gave up: {exc}"}))
            return "gave up"
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

    _finish(claimed, result)
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
        existing = db.get(QuizQuestionSet, set_id)
        if existing is None or existing.status is not QuizSetStatus.preparing:
            raise _Done("exists")
        return set_id

    artifact = db.get(Artifact, aid)
    if artifact is None or artifact.type is not ArtifactType.quiz:
        raise _Done("skipped")
    if not artifact.module.quiz_fresh_retakes:
        raise _Done("off")

    new_id = _insert_preparing(db, aid, uid)
    if new_id is not None:
        return new_id
    pending = db.scalars(
        select(QuizQuestionSet)
        .where(
            QuizQuestionSet.artifact_id == aid,
            QuizQuestionSet.user_id == uid,
            QuizQuestionSet.source == QuizSetSource.chat,
            QuizQuestionSet.status == QuizSetStatus.preparing,
            QuizQuestionSet.created_at < dt.datetime.now(tz=dt.UTC) - STALE_AFTER,
        )
        .with_for_update(skip_locked=True)
    ).first()
    if pending is None:  # preparing (recently) or ready: nothing to do
        raise _Done("exists")
    pending.status = QuizSetStatus.failed
    pending.validation_report = {"error": "abandoned: preparation did not finish"}
    db.flush()
    log.warning("quiz.abandoned_set_replaced", set_id=str(pending.id))
    new_id = _insert_preparing(db, aid, uid)
    if new_id is None:
        raise _Done("exists")
    return new_id


def _insert_preparing(db: Session, aid: uuid.UUID, uid: uuid.UUID) -> uuid.UUID | None:
    """Insert a `preparing` chat set; None when one is already preparing or ready (a
    concurrent insert waits for the other transaction, then does nothing)."""
    stmt = (
        pg_insert(QuizQuestionSet)
        .values(
            id=uuid.uuid4(),
            artifact_id=aid,
            user_id=uid,
            source=QuizSetSource.chat,
            status=QuizSetStatus.preparing,
            questions=[],
            validation_report={},
        )
        .on_conflict_do_nothing(
            index_elements=["artifact_id", "user_id"], index_where=_PENDING_WHERE
        )
        .returning(QuizQuestionSet.id)
    )
    return db.execute(stmt).scalar_one_or_none()


def _load_job(db: Session, set_id: uuid.UUID, aid: uuid.UUID, uid: uuid.UUID) -> _Job:
    artifact = db.get(Artifact, aid)
    if artifact is None:  # deleted meanwhile; the set went with it (cascade)
        raise _Done("skipped")
    module = artifact.module
    source_text = qg.module_source_text(module) if module.notebooklm_notebook_id else None
    return _Job(
        set_id=set_id,
        n=len(studio_questions(artifact)) or DEFAULT_QUESTION_COUNT,
        seen=seen_questions(db, artifact, uid),
        notebook_id=module.notebooklm_notebook_id,
        source_text=source_text,
    )


def _round(
    number: int,
    requested: int,
    parsed: list[Any],
    kept: list[dict[str, Any]],
    dropped: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "round": number,
        "requested": requested,
        "parsed": len(parsed),
        "kept": [q["question"] for q in kept],
        "dropped": dropped,
    }


def _generate(provider: ContentProvider, job: _Job) -> _Result:
    """Ask chat (once more for a shortfall), validate, and build the set + report."""
    nb = NotebookRef(notebook_id=job.notebook_id or "")
    report: dict[str, Any] = {"requested": job.n, "seen": len(job.seen), "rounds": []}

    parsed = qg.parse_questions(provider.query(nb, qg.build_prompt(job.n, job.seen)))
    kept, dropped = qg.validate(parsed, seen=job.seen, source_text=job.source_text)
    report["rounds"].append(_round(1, job.n, parsed, kept, dropped))

    if len(kept) < job.n:
        short = job.n - len(kept)
        kept_texts = [q["question"] for q in kept]
        try:
            answer = provider.query(nb, qg.build_prompt(short, kept_texts + job.seen))
        except ProviderError as exc:
            if len(kept) < qg.MIN_SERVED:
                raise  # transient: retry the whole preparation; otherwise the set fails
            report["reask_error"] = f"{type(exc).__name__}: {exc}"  # serve round 1's
        else:
            parsed = qg.parse_questions(answer)
            more, dropped = qg.validate(
                parsed, seen=kept_texts + job.seen, source_text=job.source_text
            )
            report["rounds"].append(_round(2, short, parsed, more, dropped))
            kept += more

    served = kept[: job.n]
    report["served"] = len(served)
    if len(served) < qg.MIN_SERVED:
        report["error"] = f"only {len(served)} valid question(s), fewer than {qg.MIN_SERVED} needed"
        return _Result(report=report)
    return _Result(questions=served, report=report)


def _finish(set_id: uuid.UUID, result: _Result) -> None:
    """Store the outcome on the set, if it is still `preparing`."""
    with session_scope() as db:
        qs = db.get(QuizQuestionSet, set_id, with_for_update=True)
        if qs is None or qs.status is not QuizSetStatus.preparing:
            return
        qs.status = QuizSetStatus.ready if result.ready else QuizSetStatus.failed
        qs.questions = result.questions if result.ready else []
        qs.validation_report = result.report
