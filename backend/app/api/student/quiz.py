"""Student quiz attempts (spec.md §3.12) — submit, score, and history."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from fastapi import APIRouter, status
from sqlalchemy import desc, select

from app.api.deps import CurrentStudent, DbDep
from app.api.student.artifacts import _visible_artifact
from app.errors import APIError
from app.models.artifact import Artifact
from app.models.enums import ArtifactType
from app.models.quiz_attempt import QuizAttempt
from app.schemas.student import (
    QuizAttemptOut,
    QuizAttemptsResponse,
    QuizResultOut,
    QuizResultRow,
    QuizSubmitRequest,
)
from app.services.progress import record_artifact_progress

router = APIRouter(prefix="/api/student", tags=["student-quiz"])


def _questions(artifact: Artifact) -> list[dict[str, Any]]:
    version = next((v for v in artifact.versions if v.id == artifact.published_version_id), None)
    if version is None or not version.content_json:
        return []
    return list(version.content_json.get("questions", []))


@router.post(
    "/artifacts/{artifact_id}/quiz-attempts",
    status_code=status.HTTP_201_CREATED,
    response_model=QuizResultOut,
)
def submit_attempt(
    artifact_id: uuid.UUID,
    body: QuizSubmitRequest,
    db: DbDep,
    student: CurrentStudent,
) -> QuizResultOut:
    artifact = _visible_artifact(db, artifact_id)
    if artifact.type is not ArtifactType.quiz:
        raise APIError(status.HTTP_404_NOT_FOUND, "not_found", "Not available")

    questions = _questions(artifact)
    total = len(questions)
    answers = {int(k): int(v) for k, v in body.answers.items()}
    if len(answers) < total or any(i not in answers for i in range(total)):
        raise APIError(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "incomplete", "Answer every question first."
        )
    if any(not (0 <= answers[i] <= 3) for i in range(total)):
        raise APIError(status.HTTP_422_UNPROCESSABLE_ENTITY, "bad_answer", "Invalid option.")

    rows: list[QuizResultRow] = []
    correct = 0
    for i, q in enumerate(questions):
        ci = int(q.get("correct_index", -1))
        ok = answers[i] == ci
        correct += ok
        rows.append(
            QuizResultRow(
                question_index=i,
                selected_index=answers[i],
                correct_index=ci,
                is_correct=ok,
                explanation=str(q.get("explanation", "")),
            )
        )

    score = round(100 * correct / total, 2) if total else 0.0
    attempt = QuizAttempt(
        user_id=student.id,
        artifact_id=artifact.id,
        answers_json={str(k): v for k, v in answers.items()},
        score_percent=score,
        correct_count=correct,
        total_count=total,
        submitted_at=dt.datetime.now(dt.UTC),
    )
    db.add(attempt)
    db.flush()

    record_artifact_progress(db, user_id=student.id, artifact=artifact, completed=True)

    prior = db.scalars(
        select(QuizAttempt.score_percent).where(
            QuizAttempt.user_id == student.id, QuizAttempt.artifact_id == artifact.id
        )
    ).all()
    return QuizResultOut(
        attempt_id=attempt.id,
        score_percent=float(score),
        correct_count=correct,
        total_count=total,
        results=rows,
        best_score_percent=float(max(prior)) if prior else float(score),
        latest_score_percent=float(score),
    )


@router.get("/artifacts/{artifact_id}/quiz-attempts", response_model=QuizAttemptsResponse)
def list_attempts(
    artifact_id: uuid.UUID, db: DbDep, student: CurrentStudent
) -> QuizAttemptsResponse:
    artifact = _visible_artifact(db, artifact_id)
    if artifact.type is not ArtifactType.quiz:
        raise APIError(status.HTTP_404_NOT_FOUND, "not_found", "Not available")

    attempts = db.scalars(
        select(QuizAttempt)
        .where(QuizAttempt.user_id == student.id, QuizAttempt.artifact_id == artifact.id)
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
