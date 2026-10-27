"""Student quiz attempts (adaptive quiz, spec §4.1, §4.2, §6, §7).

Flow: start (or resume) an attempt → check one answer at a time → complete.

- Attempt 1 serves the published Studio quiz (stored as a `studio` question set).
- Retakes serve the student's `ready` chat set (prepared in the background by
  `app.tasks.quiz.prepare_quiz_set`); the set is marked `used` in the same commit
  that creates the attempt. With the module's fresh-retakes switch off, retakes
  reuse the Studio quiz.
- Every started attempt enqueues preparation of the student's next set, after
  the commit.

Answer secrecy: a question's answer and explanation are only ever sent after the
student has checked (locked) an answer for it in that attempt.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import desc, func, select, text
from sqlalchemy.orm import Session

from app.api.deps import CurrentStudent, DbDep
from app.api.student.artifacts import _visible_artifact
from app.errors import APIError
from app.models.artifact import Artifact
from app.models.enums import ArtifactType, QuizSetSource, QuizSetStatus
from app.models.quiz_attempt import QuizAttempt
from app.models.quiz_question_set import QuizQuestionSet
from app.schemas.student import (
    QuizAttemptOut,
    QuizAttemptsResponse,
    QuizCheckOut,
    QuizCheckRequest,
    QuizCompleteOut,
    QuizQuestionOut,
    QuizReviewRow,
    QuizStartOut,
)
from app.services.progress import record_artifact_progress
from app.services.quiz_generation import fill_blank_correct
from app.tasks.quiz import enqueue_prepare, studio_questions

router = APIRouter(prefix="/api/student", tags=["student-quiz"])

PREPARING_MESSAGE = "Preparing new questions…"
UNAVAILABLE_MESSAGE = "New questions aren't available right now — please try again later"
#: a chat set still `preparing` after this long is treated as unavailable (the
#: task itself replaces it only after `app.tasks.quiz.STALE_AFTER`)
PREPARING_PATIENCE = dt.timedelta(minutes=15)

QType = Literal["mcq", "fill_blank"]


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _quiz_artifact(db: Session, artifact_id: uuid.UUID) -> Artifact:
    artifact = _visible_artifact(db, artifact_id)
    if artifact.type is not ArtifactType.quiz:
        raise APIError(status.HTTP_404_NOT_FOUND, "not_found", "Not available")
    return artifact


def _qtype(q: dict[str, Any]) -> QType:
    return "fill_blank" if q.get("type") == "fill_blank" else "mcq"


def _correct_answer(q: dict[str, Any]) -> tuple[str, int | None]:
    """(answer text, option index for MCQ)."""
    if _qtype(q) == "fill_blank":
        return str(q.get("answer", "")), None
    ci = int(q.get("correct_index", -1))
    options = list(q.get("options", []))
    return (str(options[ci]) if 0 <= ci < len(options) else ""), ci


def _check_out(index: int, q: dict[str, Any], entry: dict[str, Any]) -> QuizCheckOut:
    answer, ci = _correct_answer(q)
    return QuizCheckOut(
        index=index,
        response=entry["response"],
        correct=bool(entry["correct"]),
        correct_answer=answer,
        correct_index=ci,
        explanation=str(q.get("explanation", "")),
    )


def _attempt_questions(db: Session, attempt: QuizAttempt) -> tuple[list[dict[str, Any]], str]:
    """The attempt's questions (full, server-side) and their source."""
    qs = db.get(QuizQuestionSet, attempt.question_set_id) if attempt.question_set_id else None
    if qs is None:  # legacy attempt (before question sets)
        artifact = db.get(Artifact, attempt.artifact_id)
        return (studio_questions(artifact) if artifact else []), QuizSetSource.studio.value
    return list(qs.questions), qs.source.value


def _start_out(db: Session, attempt: QuizAttempt, number: int, *, resumed: bool) -> QuizStartOut:
    questions, source = _attempt_questions(db, attempt)
    answers = attempt.answers_json or {}
    out: list[QuizQuestionOut] = []
    for i, q in enumerate(questions):
        kind = _qtype(q)
        entry = answers.get(str(i))
        out.append(
            QuizQuestionOut(
                index=i,
                type=kind,
                question=str(q.get("question", "")),
                options=[str(o) for o in q.get("options", [])] if kind == "mcq" else None,
                result=_check_out(i, q, entry) if entry else None,
            )
        )
    return QuizStartOut(
        status="resumed" if resumed else "started",
        attempt_id=attempt.id,
        attempt_number=number,
        source="chat" if source == QuizSetSource.chat.value else "studio",
        total_count=len(questions),
        checked_count=len(answers),
        correct_count=sum(1 for e in answers.values() if e.get("correct")),
        started_at=attempt.started_at,
        questions=out,
    )


def _lock_student_quiz(db: Session, artifact_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """Serialise attempt starts per (student, quiz) for this transaction, so a double
    click can't open two attempts or consume two sets."""
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
        {"k": f"quiz-start:{artifact_id}:{user_id}"},
    )


def _open_attempt(db: Session, artifact_id: uuid.UUID, user_id: uuid.UUID) -> QuizAttempt | None:
    return db.scalar(
        select(QuizAttempt)
        .where(
            QuizAttempt.user_id == user_id,
            QuizAttempt.artifact_id == artifact_id,
            QuizAttempt.completed_at.is_(None),
            QuizAttempt.submitted_at.is_(None),
        )
        .order_by(desc(QuizAttempt.started_at))
        .limit(1)
    )


def _attempt_number(db: Session, attempt: QuizAttempt) -> int:
    earlier = db.scalar(
        select(func.count())
        .select_from(QuizAttempt)
        .where(
            QuizAttempt.user_id == attempt.user_id,
            QuizAttempt.artifact_id == attempt.artifact_id,
            QuizAttempt.started_at < attempt.started_at,
        )
    )
    return int(earlier or 0) + 1


def _chat_set(
    db: Session, artifact_id: uuid.UUID, user_id: uuid.UUID, wanted: QuizSetStatus
) -> QuizQuestionSet | None:
    return db.scalar(
        select(QuizQuestionSet)
        .where(
            QuizQuestionSet.artifact_id == artifact_id,
            QuizQuestionSet.user_id == user_id,
            QuizQuestionSet.source == QuizSetSource.chat,
            QuizQuestionSet.status == wanted,
        )
        .order_by(desc(QuizQuestionSet.created_at))
        .limit(1)
        .with_for_update()
    )


def _latest_chat_status(
    db: Session, artifact_id: uuid.UUID, user_id: uuid.UUID
) -> QuizSetStatus | None:
    return db.scalar(
        select(QuizQuestionSet.status)
        .where(
            QuizQuestionSet.artifact_id == artifact_id,
            QuizQuestionSet.user_id == user_id,
            QuizQuestionSet.source == QuizSetSource.chat,
        )
        .order_by(desc(QuizQuestionSet.created_at))
        .limit(1)
    )


def _waiting(db: Session, artifact_id: uuid.UUID, user_id: uuid.UUID, *, available: bool) -> Any:
    """No ready set: commit (nothing to write), enqueue preparation (idempotent), and
    tell the student to wait (202) or to come back later (409)."""
    db.commit()
    enqueue_prepare(artifact_id, user_id)
    if available:
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={"status": "preparing", "message": PREPARING_MESSAGE},
        )
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={
            "status": "unavailable",
            "message": UNAVAILABLE_MESSAGE,
            "error": {"code": "questions_unavailable", "message": UNAVAILABLE_MESSAGE},
        },
    )


@router.post(
    "/artifacts/{artifact_id}/quiz-attempts",
    status_code=status.HTTP_201_CREATED,
    response_model=QuizStartOut,
    responses={
        200: {"model": QuizStartOut, "description": "Open attempt resumed"},
        202: {"description": "The next question set is still being prepared"},
        409: {"description": "No new questions available right now"},
    },
)
def start_attempt(
    artifact_id: uuid.UUID, response: Response, db: DbDep, student: CurrentStudent
) -> Any:
    artifact = _quiz_artifact(db, artifact_id)
    uid = student.id
    _lock_student_quiz(db, artifact.id, uid)

    open_attempt = _open_attempt(db, artifact.id, uid)
    if open_attempt is not None:
        response.status_code = status.HTTP_200_OK
        return _start_out(db, open_attempt, _attempt_number(db, open_attempt), resumed=True)

    previous = int(
        db.scalar(
            select(func.count())
            .select_from(QuizAttempt)
            .where(QuizAttempt.user_id == uid, QuizAttempt.artifact_id == artifact.id)
        )
        or 0
    )
    fresh = artifact.module.quiz_fresh_retakes

    qs: QuizQuestionSet | None = None
    if previous > 0 and fresh:
        qs = _chat_set(db, artifact.id, uid, QuizSetStatus.ready)
        if qs is None:
            preparing = _chat_set(db, artifact.id, uid, QuizSetStatus.preparing)
            if preparing is not None:
                recent = _now() - preparing.created_at < PREPARING_PATIENCE
                return _waiting(db, artifact.id, uid, available=recent)
            failed = _latest_chat_status(db, artifact.id, uid) is QuizSetStatus.failed
            return _waiting(db, artifact.id, uid, available=not failed)
        qs.status = QuizSetStatus.used
    else:
        questions = [{**q, "type": "mcq"} for q in studio_questions(artifact)]
        if not questions:
            raise APIError(status.HTTP_404_NOT_FOUND, "not_found", "Not available")
        qs = QuizQuestionSet(
            artifact_id=artifact.id,
            user_id=uid,
            source=QuizSetSource.studio,
            status=QuizSetStatus.used,
            questions=questions,
            validation_report={},
        )
        db.add(qs)
        db.flush()

    attempt = QuizAttempt(
        user_id=uid,
        artifact_id=artifact.id,
        question_set_id=qs.id,
        answers_json={},
        score_percent=0,
        correct_count=0,
        total_count=len(qs.questions),
        started_at=_now(),
    )
    db.add(attempt)
    db.flush()
    out = _start_out(db, attempt, previous + 1, resumed=False)
    # the used set and the new attempt land in one commit; then prepare the next set
    db.commit()
    if fresh:
        enqueue_prepare(artifact.id, uid)
    return out


def _locked_attempt(db: Session, attempt_id: uuid.UUID, user_id: uuid.UUID) -> QuizAttempt:
    """The caller's attempt, row-locked for this transaction (404 for anyone else's)."""
    attempt = db.scalar(
        select(QuizAttempt)
        .where(QuizAttempt.id == attempt_id, QuizAttempt.user_id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if attempt is None:
        raise APIError(status.HTTP_404_NOT_FOUND, "not_found", "Not available")
    _quiz_artifact(db, attempt.artifact_id)
    return attempt


def _is_complete(attempt: QuizAttempt) -> bool:
    return attempt.completed_at is not None or attempt.submitted_at is not None


@router.post("/quiz-attempts/{attempt_id}/answers", response_model=QuizCheckOut)
def check_answer(
    attempt_id: uuid.UUID, body: QuizCheckRequest, db: DbDep, student: CurrentStudent
) -> QuizCheckOut:
    attempt = _locked_attempt(db, attempt_id, student.id)
    if _is_complete(attempt):
        raise APIError(status.HTTP_409_CONFLICT, "attempt_completed", "This attempt is finished.")
    questions, _source = _attempt_questions(db, attempt)
    if body.index >= len(questions):
        raise APIError(status.HTTP_422_UNPROCESSABLE_ENTITY, "bad_index", "No such question.")
    key = str(body.index)
    answers = dict(attempt.answers_json or {})
    if key in answers:
        raise APIError(status.HTTP_409_CONFLICT, "already_checked", "Already checked.")

    q = questions[body.index]
    if _qtype(q) == "mcq":
        if not isinstance(body.response, int) or not 0 <= body.response <= 3:
            raise APIError(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "bad_answer", "Choose one of the options."
            )
        correct = body.response == int(q.get("correct_index", -1))
    else:
        if not isinstance(body.response, str) or not body.response.strip():
            raise APIError(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "bad_answer", "Type your answer first."
            )
        correct = fill_blank_correct(q, body.response)

    entry = {"response": body.response, "correct": correct, "checked_at": _now().isoformat()}
    answers[key] = entry
    attempt.answers_json = answers
    attempt.correct_count = sum(1 for e in answers.values() if e.get("correct"))
    db.flush()
    return _check_out(body.index, q, entry)


def _entry(raw: Any, q: dict[str, Any]) -> dict[str, Any]:
    """A checked answer; legacy all-at-once attempts stored just the option index."""
    if isinstance(raw, dict):
        return raw
    return {"response": raw, "correct": raw == q.get("correct_index")}


def _complete_out(db: Session, attempt: QuizAttempt) -> QuizCompleteOut:
    questions, _source = _attempt_questions(db, attempt)
    answers = attempt.answers_json or {}
    review: list[QuizReviewRow] = []
    for i, q in enumerate(questions):
        entry = _entry(answers.get(str(i)), q)
        answer, ci = _correct_answer(q)
        kind = _qtype(q)
        review.append(
            QuizReviewRow(
                index=i,
                type=kind,
                question=str(q.get("question", "")),
                options=[str(o) for o in q.get("options", [])] if kind == "mcq" else None,
                response=entry["response"],
                correct=bool(entry["correct"]),
                correct_answer=answer,
                correct_index=ci,
                explanation=str(q.get("explanation", "")),
            )
        )
    scores = db.scalars(
        select(QuizAttempt.score_percent).where(
            QuizAttempt.user_id == attempt.user_id,
            QuizAttempt.artifact_id == attempt.artifact_id,
            QuizAttempt.submitted_at.is_not(None),
        )
    ).all()
    latest = db.scalar(
        select(QuizAttempt.score_percent)
        .where(
            QuizAttempt.user_id == attempt.user_id,
            QuizAttempt.artifact_id == attempt.artifact_id,
            QuizAttempt.submitted_at.is_not(None),
        )
        .order_by(desc(QuizAttempt.submitted_at))
        .limit(1)
    )
    completed_at = attempt.completed_at or attempt.submitted_at
    assert completed_at is not None
    return QuizCompleteOut(
        attempt_id=attempt.id,
        score_percent=float(attempt.score_percent),
        correct_count=attempt.correct_count,
        total_count=attempt.total_count,
        completed_at=completed_at,
        review=review,
        best_score_percent=float(max(scores)),
        latest_score_percent=float(latest if latest is not None else attempt.score_percent),
    )


@router.post("/quiz-attempts/{attempt_id}/complete", response_model=QuizCompleteOut)
def complete_attempt(attempt_id: uuid.UUID, db: DbDep, student: CurrentStudent) -> QuizCompleteOut:
    attempt = _locked_attempt(db, attempt_id, student.id)
    if _is_complete(attempt):
        return _complete_out(db, attempt)  # double click: same result
    questions, _source = _attempt_questions(db, attempt)
    answers = attempt.answers_json or {}
    if any(str(i) not in answers for i in range(len(questions))):
        raise APIError(
            status.HTTP_409_CONFLICT, "incomplete", "Check every question before finishing."
        )

    total = len(questions)
    correct = sum(1 for i in range(total) if answers[str(i)].get("correct"))
    now = _now()
    attempt.correct_count = correct
    attempt.total_count = total
    attempt.score_percent = round(100 * correct / total, 2) if total else 0.0
    attempt.completed_at = now
    attempt.submitted_at = now
    db.flush()

    artifact = _quiz_artifact(db, attempt.artifact_id)
    record_artifact_progress(db, user_id=student.id, artifact=artifact, completed=True)
    return _complete_out(db, attempt)


@router.get("/artifacts/{artifact_id}/quiz-attempts", response_model=QuizAttemptsResponse)
def list_attempts(
    artifact_id: uuid.UUID, db: DbDep, student: CurrentStudent
) -> QuizAttemptsResponse:
    """Finished attempts, newest first (an open attempt isn't listed)."""
    artifact = _quiz_artifact(db, artifact_id)
    attempts = db.scalars(
        select(QuizAttempt)
        .where(
            QuizAttempt.user_id == student.id,
            QuizAttempt.artifact_id == artifact.id,
            QuizAttempt.submitted_at.is_not(None),
        )
        .order_by(desc(QuizAttempt.submitted_at))
    ).all()
    out = [
        QuizAttemptOut(
            id=a.id,
            score_percent=float(a.score_percent),
            correct_count=a.correct_count,
            total_count=a.total_count,
            submitted_at=a.submitted_at,
        )
        for a in attempts
    ]
    scores = [a.score_percent for a in out]
    return QuizAttemptsResponse(
        attempts=out,
        best_score_percent=float(max(scores)) if scores else None,
        latest_score_percent=out[0].score_percent if out else None,
    )
