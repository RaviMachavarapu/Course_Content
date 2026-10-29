"""Admin — adaptive quiz audit (spec §4.5): recent generated question sets for a
quiz artifact (answers included — admin only) and the per-module retake switch."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Query, status
from pydantic import BaseModel
from sqlalchemy import desc, select

from app.api.admin import ADMIN_DEPENDENCIES
from app.api.deps import DbDep
from app.errors import APIError
from app.models.artifact import Artifact
from app.models.enums import QuizSetSource
from app.models.module import Module
from app.models.quiz_question_set import QuizQuestionSet
from app.models.user import User
from app.services import quiz_generation as qg

router = APIRouter(prefix="/api/admin", tags=["admin-quiz"], dependencies=ADMIN_DEPENDENCIES)


class StudentOut(BaseModel):
    display_name: str
    email: str


class DroppedOut(BaseModel):
    round: int | None = None
    index: int | None = None
    question: str = ""
    reason: str = ""


class QuizSetOut(BaseModel):
    id: uuid.UUID
    source: str
    status: str
    created_at: dt.datetime
    student: StudentOut
    question_count: int
    kept: int
    dropped: int
    dropped_questions: list[DroppedOut]
    #: kept questions whose proof quote isn't in the module's PDFs (link + PDF
    #: module, owner decision 2026-10-28): reason "quote not verified (link source)"
    unverified_questions: list[DroppedOut]
    error: str | None
    #: round 2 (re-ask) chat failure; round 1's questions were served
    warning: str | None
    questions: list[dict[str, Any]]


class QuizSettings(BaseModel):
    fresh_retakes: bool


def _rounds(report: dict[str, Any]) -> list[dict[str, Any]]:
    rounds = report.get("rounds") if isinstance(report, dict) else None
    return [r for r in rounds if isinstance(r, dict)] if isinstance(rounds, list) else []


def _entries(r: dict[str, Any], key: str) -> list[DroppedOut]:
    items = r.get(key)
    return [
        DroppedOut(
            round=r.get("round"),
            index=d.get("index"),
            question=str(d.get("question", "")),
            reason=str(d.get("reason", "")),
        )
        for d in (items if isinstance(items, list) else [])
        if isinstance(d, dict)
    ]


def _served_text(question: str, questions: list[Any]) -> str:
    key = qg.blank_key(question)
    for q in questions:
        if isinstance(q, dict) and qg.blank_key(str(q.get("question", ""))) == key:
            return str(q.get("question"))
    return question


def _out(row: QuizQuestionSet, user: User) -> QuizSetOut:
    dropped: list[DroppedOut] = []
    unverified: list[DroppedOut] = []
    kept = 0
    for r in _rounds(row.validation_report):
        k = r.get("kept")
        kept += len(k) if isinstance(k, list) else 0
        dropped += _entries(r, "dropped")
        unverified += _entries(r, "unverified")
    # only questions actually served (round 1 may return more than N); an older report
    # holds a fill-blank's raw text, so compare with the blank normalised
    served = {
        qg.blank_key(str(q.get("question", ""))) for q in row.questions if isinstance(q, dict)
    }
    unverified = [
        u.model_copy(update={"question": _served_text(u.question, row.questions)})
        for u in unverified
        if qg.blank_key(u.question) in served
    ]
    report = row.validation_report if isinstance(row.validation_report, dict) else {}
    error = report.get("error")
    warning = report.get("reask_error")
    return QuizSetOut(
        id=row.id,
        source=row.source.value,
        status=row.status.value,
        created_at=row.created_at,
        student=StudentOut(display_name=user.display_name, email=user.email),
        question_count=len(row.questions),
        kept=kept,
        dropped=len(dropped),
        dropped_questions=dropped,
        unverified_questions=unverified,
        error=str(error) if error else None,
        warning=str(warning) if warning else None,
        questions=row.questions,
    )


@router.get("/artifacts/{artifact_id}/quiz-sets", response_model=list[QuizSetOut])
def list_quiz_sets(
    artifact_id: uuid.UUID,
    db: DbDep,
    limit: int = Query(20, ge=1, le=100),
    source: Literal["chat", "all"] = Query("chat"),
) -> list[QuizSetOut]:
    """Chat-generated sets by default; `source=all` adds the per-attempt Studio copies."""
    if db.get(Artifact, artifact_id) is None:
        raise APIError(status.HTTP_404_NOT_FOUND, "not_found", "Artifact not found")
    query = (
        select(QuizQuestionSet, User)
        .join(User, User.id == QuizQuestionSet.user_id)
        .where(QuizQuestionSet.artifact_id == artifact_id)
    )
    if source == "chat":
        query = query.where(QuizQuestionSet.source == QuizSetSource.chat)
    rows = db.execute(query.order_by(desc(QuizQuestionSet.created_at)).limit(limit)).all()
    return [_out(s, u) for s, u in rows]


def _module(db: DbDep, module_id: uuid.UUID) -> Module:
    module = db.get(Module, module_id)
    if module is None:
        raise APIError(status.HTTP_404_NOT_FOUND, "not_found", "Module not found")
    return module


@router.get("/modules/{module_id}/quiz-settings", response_model=QuizSettings)
def get_quiz_settings(module_id: uuid.UUID, db: DbDep) -> QuizSettings:
    return QuizSettings(fresh_retakes=_module(db, module_id).quiz_fresh_retakes)


@router.patch("/modules/{module_id}/quiz-settings", response_model=QuizSettings)
def patch_quiz_settings(module_id: uuid.UUID, body: QuizSettings, db: DbDep) -> QuizSettings:
    module = _module(db, module_id)
    module.quiz_fresh_retakes = body.fresh_retakes
    db.commit()
    return QuizSettings(fresh_retakes=module.quiz_fresh_retakes)
