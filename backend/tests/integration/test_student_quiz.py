"""Student quiz attempts (adaptive quiz, spec §4.1, §4.2, §6, §7): start/resume,
check one answer at a time, complete, retakes with fresh chat sets, history."""

from __future__ import annotations

import datetime as dt
import json
import random
import uuid
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

import app.api.student.quiz as quiz_api
from app.cli import seed_admin
from app.models.artifact import Artifact
from app.models.enums import ArtifactType, QuizSetSource, QuizSetStatus
from app.models.module import Module
from app.models.quiz_attempt import QuizAttempt
from app.models.quiz_question_set import QuizQuestionSet
from app.models.user import User
from app.pipeline import orchestrator
from app.pipeline.fixture import FixtureProvider
from app.services.publish import publish_module

REAL_RNG = quiz_api._rng  # captured before the identity-order fixture patches it
PROVIDER = FixtureProvider()
TYPES = [ArtifactType.quiz, ArtifactType.report]
SECRET_KEYS = ("correct_index", "answer", "accepted_answers", "explanation", "source_quote", "hint")
PREPARING = {"status": "preparing", "message": "Preparing new questions…"}
UNAVAILABLE = "New questions aren't available right now — please try again later"


@pytest.fixture(autouse=True)
def _no_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.api.admin.courses._dispatch_all", lambda *a, **k: None)


class _KeepOrder:
    """Stands in for the option-shuffling RNG: options stay in stored order."""

    def shuffle(self, x: list[Any]) -> None:
        return None


class _Reverse:
    """A deterministic shuffle that moves every option of a 4-option question."""

    def shuffle(self, x: list[Any]) -> None:
        x.reverse()


@pytest.fixture(autouse=True)
def _identity_order(monkeypatch: pytest.MonkeyPatch) -> None:
    # Most tests read answers straight from the stored set; the shuffle tests below
    # swap in their own RNG.
    monkeypatch.setattr(quiz_api, "_rng", _KeepOrder())


@pytest.fixture(autouse=True)
def enqueued(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "app.api.student.quiz.enqueue_prepare",
        lambda aid, uid: calls.append((str(aid), str(uid))),
    )
    return calls


@dataclass
class Ctx:
    quiz_id: str
    module_id: uuid.UUID
    questions: list[dict[str, Any]]
    student_id: uuid.UUID


def _setup(client: TestClient, db: Session, enqueued: list[tuple[str, str]]) -> Ctx:
    seed_admin(db, email="qz-admin@example.com", display_name="A", password="qz-admin-pw-1")
    db.flush()
    client.post(
        "/api/admin/auth/login",
        json={"email": "qz-admin@example.com", "password": "qz-admin-pw-1"},
    )
    h = {"X-CSRF-Token": client.cookies["sdp_csrf"]}
    cid = client.post("/api/admin/courses", json={"title": "QZ"}, headers=h).json()["course"]["id"]
    mid = client.post(
        f"/api/admin/courses/{cid}/modules",
        json={
            "source_url": "https://example.com/qz",
            "title": "M1",
            "types": [t.value for t in TYPES],
        },
        headers=h,
    ).json()["module"]["id"]
    module = db.get(Module, uuid.UUID(mid))
    assert module is not None
    for artifact in module.artifacts:
        if artifact.type in TYPES:
            orchestrator.run_artifact_generation(db, PROVIDER, artifact.id)
    db.expire_all()
    module = db.get(Module, uuid.UUID(mid))
    assert module is not None
    slug = module.course.slug
    publish_module(db, module)
    db.flush()

    quiz = next(a for a in module.artifacts if a.type is ArtifactType.quiz)
    version = next(v for v in quiz.versions if v.id == quiz.published_version_id)
    questions = version.content_json["questions"]

    _register(client, "qz-learner@example.com")
    student = db.scalar(select(User).where(User.email == "qz-learner@example.com"))
    assert student is not None
    ws = client.get(f"/api/student/courses/{slug}").json()
    by_type = {a["type"]: a["id"] for a in ws["modules"][0]["artifacts"]}
    return Ctx(by_type["quiz"], module.id, questions, student.id)


def _register(client: TestClient, email: str) -> None:
    client.cookies.clear()
    client.post(
        "/api/student/auth/register",
        json={"email": email, "password": "qz-learner-pw-1", "display_name": "L"},
    )


def _start(client: TestClient, ctx: Ctx) -> Any:
    return client.post(f"/api/student/artifacts/{ctx.quiz_id}/quiz-attempts")


def _check(client: TestClient, attempt_id: str, index: int, response: Any) -> Any:
    return client.post(
        f"/api/student/quiz-attempts/{attempt_id}/answers",
        json={"index": index, "response": response},
    )


def _complete(client: TestClient, attempt_id: str) -> Any:
    return client.post(f"/api/student/quiz-attempts/{attempt_id}/complete")


def _attempt_set(db: Session, attempt_id: str) -> QuizQuestionSet:
    attempt = db.get(QuizAttempt, uuid.UUID(attempt_id))
    assert attempt is not None and attempt.question_set_id is not None
    qs = db.get(QuizQuestionSet, attempt.question_set_id)
    assert qs is not None
    return qs


def _right(q: dict[str, Any]) -> Any:
    return q["correct_index"] if q.get("type", "mcq") == "mcq" else q["answer"]


def _finish(client: TestClient, db: Session, attempt_id: str, *, correct: bool = True) -> Any:
    for i, q in enumerate(_attempt_set(db, attempt_id).questions):
        if correct:
            resp: Any = _right(q)
        elif q.get("type", "mcq") == "mcq":
            resp = (q["correct_index"] + 1) % 4
        else:
            resp = "definitely wrong"
        assert _check(client, attempt_id, i, resp).status_code == 200
    done = _complete(client, attempt_id)
    assert done.status_code == 200, done.text
    return done.json()


def _chat_questions() -> list[dict[str, Any]]:
    return [
        {
            "type": "mcq",
            "question": "Which product forms from an SN1 reaction at a stereocentre?",
            "options": ["Racemate", "Single enantiomer", "Meso compound", "No product"],
            "correct_index": 0,
            "explanation": "The planar carbocation is attacked from both faces.",
            "source_quote": "attacked from both faces",
        },
        {
            "type": "fill_blank",
            "question": "An equal mixture of two enantiomers is a ____.",
            "answer": "racemic mixture",
            "accepted_answers": ["racemate"],
            "explanation": "Equal amounts of both enantiomers.",
            "source_quote": "equal mixture",
        },
        {
            "type": "fill_blank",
            "question": "Carbon has ____ valence electrons.",
            "answer": "4",
            "accepted_answers": [],
            "explanation": "Group 14.",
            "source_quote": "four valence electrons",
        },
    ]


def _add_set(
    db: Session,
    ctx: Ctx,
    status: QuizSetStatus,
    *,
    created_at: dt.datetime | None = None,
    heartbeat_at: dt.datetime | None = None,
    questions: list[dict[str, Any]] | None = None,
    prepared_for: dict[str, str] | None = None,
) -> QuizQuestionSet:
    qs = QuizQuestionSet(
        artifact_id=uuid.UUID(ctx.quiz_id),
        user_id=ctx.student_id,
        source=QuizSetSource.chat,
        status=status,
        questions=_chat_questions() if questions is None else questions,
        validation_report={
            "prepared_for": prepared_for or {"language": "en", "difficulty": "medium"}
        },
        heartbeat_at=heartbeat_at,
    )
    if created_at is not None:
        qs.created_at = created_at
    db.add(qs)
    db.flush()
    return qs


def _no_secrets(payload: Any) -> None:
    text = json.dumps(payload)
    for key in SECRET_KEYS:
        assert f'"{key}"' not in text, key


def _attempt_count(db: Session, ctx: Ctx) -> int:
    return len(
        db.scalars(
            select(QuizAttempt).where(QuizAttempt.artifact_id == uuid.UUID(ctx.quiz_id))
        ).all()
    )


# -- attempt 1 ----------------------------------------------------------------------------


def test_start_attempt_has_no_answers(
    client: TestClient, db_session: Session, enqueued: list[tuple[str, str]]
) -> None:
    ctx = _setup(client, db_session, enqueued)
    resp = _start(client, ctx)
    assert resp.status_code == 201
    body = resp.json()
    _no_secrets(body)
    assert body["status"] == "started"
    assert body["attempt_number"] == 1
    assert body["source"] == "studio"
    assert body["total_count"] == len(ctx.questions)
    for i, (got, q) in enumerate(zip(body["questions"], ctx.questions, strict=True)):
        assert set(got) == {"index", "type", "question", "options", "result"}
        assert got == {
            "index": i,
            "type": "mcq",
            "question": q["question"],
            "options": q["options"],
            "result": None,
        }


def test_attempt_one_uses_a_used_studio_set_and_enqueues_the_next(
    client: TestClient, db_session: Session, enqueued: list[tuple[str, str]]
) -> None:
    ctx = _setup(client, db_session, enqueued)
    # a failed chat set before any attempt doesn't block attempt 1
    _add_set(db_session, ctx, QuizSetStatus.failed)
    body = _start(client, ctx).json()
    qs = _attempt_set(db_session, body["attempt_id"])
    assert qs.source is QuizSetSource.studio
    assert qs.status is QuizSetStatus.used
    assert [q["question"] for q in qs.questions] == [q["question"] for q in ctx.questions]
    assert enqueued == [(ctx.quiz_id, str(ctx.student_id))]


def test_open_attempt_is_resumed_with_checked_results_only(
    client: TestClient, db_session: Session, enqueued: list[tuple[str, str]]
) -> None:
    ctx = _setup(client, db_session, enqueued)
    first = _start(client, ctx).json()
    q0 = ctx.questions[0]
    _check(client, first["attempt_id"], 0, q0["correct_index"])

    again = _start(client, ctx)
    assert again.status_code == 200
    body = again.json()
    assert body["status"] == "resumed"
    assert body["attempt_id"] == first["attempt_id"]
    assert body["checked_count"] == 1
    assert body["correct_count"] == 1
    assert body["questions"][0]["result"] == {
        "index": 0,
        "response": q0["correct_index"],
        "correct": True,
        "correct_answer": q0["options"][q0["correct_index"]],
        "correct_index": q0["correct_index"],
        "explanation": q0.get("explanation", ""),
    }
    _no_secrets(body["questions"][1:])
    assert all(q["result"] is None for q in body["questions"][1:])
    assert _attempt_count(db_session, ctx) == 1


# -- checking -----------------------------------------------------------------------------


def test_check_reveals_only_that_question(
    client: TestClient, db_session: Session, enqueued: list[tuple[str, str]]
) -> None:
    ctx = _setup(client, db_session, enqueued)
    attempt_id = _start(client, ctx).json()["attempt_id"]
    q1 = ctx.questions[1]
    wrong = (q1["correct_index"] + 1) % 4
    resp = _check(client, attempt_id, 1, wrong)
    assert resp.status_code == 200
    assert resp.json() == {
        "index": 1,
        "response": wrong,
        "correct": False,
        "correct_answer": q1["options"][q1["correct_index"]],
        "correct_index": q1["correct_index"],
        "explanation": q1.get("explanation", ""),
    }
    other_texts = [q["explanation"] for i, q in enumerate(ctx.questions) if i != 1]
    assert not any(t and t in resp.text for t in other_texts)

    attempt = db_session.get(QuizAttempt, uuid.UUID(attempt_id))
    assert attempt is not None
    entry = attempt.answers_json["1"]
    assert entry["response"] == wrong and entry["correct"] is False
    assert dt.datetime.fromisoformat(entry["checked_at"])


def test_double_check_conflict(
    client: TestClient, db_session: Session, enqueued: list[tuple[str, str]]
) -> None:
    ctx = _setup(client, db_session, enqueued)
    attempt_id = _start(client, ctx).json()["attempt_id"]
    q0 = ctx.questions[0]
    wrong = (q0["correct_index"] + 1) % 4
    assert _check(client, attempt_id, 0, wrong).status_code == 200
    again = _check(client, attempt_id, 0, q0["correct_index"])
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "already_checked"

    attempt = db_session.get(QuizAttempt, uuid.UUID(attempt_id))
    assert attempt is not None
    assert attempt.answers_json["0"]["correct"] is False
    assert attempt.correct_count == 0

    for i, q in enumerate(ctx.questions[1:], start=1):
        _check(client, attempt_id, i, q["correct_index"])
    done = _complete(client, attempt_id).json()
    assert done["correct_count"] == len(ctx.questions) - 1


def test_check_validates_the_response(
    client: TestClient, db_session: Session, enqueued: list[tuple[str, str]]
) -> None:
    ctx = _setup(client, db_session, enqueued)
    attempt_id = _start(client, ctx).json()["attempt_id"]
    assert _check(client, attempt_id, 0, 4).status_code == 422
    assert _check(client, attempt_id, 0, -1).status_code == 422
    assert _check(client, attempt_id, 0, "1").status_code == 422
    assert _check(client, attempt_id, 0, True).status_code == 422
    assert _check(client, attempt_id, len(ctx.questions), 0).status_code == 422
    attempt = db_session.get(QuizAttempt, uuid.UUID(attempt_id))
    assert attempt is not None and attempt.answers_json == {}


def test_fill_blank_grading_uses_the_helper(
    client: TestClient,
    db_session: Session,
    enqueued: list[tuple[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = _setup(client, db_session, enqueued)
    _finish(client, db_session, _start(client, ctx).json()["attempt_id"])
    _add_set(db_session, ctx, QuizSetStatus.ready)

    graded: list[str] = []
    real = quiz_api.fill_blank_correct

    def spy(question: dict[str, Any], response: str) -> bool:
        graded.append(response)
        return real(question, response)

    monkeypatch.setattr(quiz_api, "fill_blank_correct", spy)

    body = _start(client, ctx).json()
    assert body["source"] == "chat"
    _no_secrets(body)
    assert body["questions"][1] == {
        "index": 1,
        "type": "fill_blank",
        "question": "An equal mixture of two enantiomers is a ____.",
        "options": None,
        "result": None,
    }
    aid = body["attempt_id"]
    assert _check(client, aid, 1, 3).status_code == 422  # fill-blank wants text
    assert _check(client, aid, 1, "   ").status_code == 422
    ok = _check(client, aid, 1, "Racemic mixture.").json()
    assert ok == {
        "index": 1,
        "response": "Racemic mixture.",
        "correct": True,
        "correct_answer": "racemic mixture",
        "correct_index": None,
        "explanation": "Equal amounts of both enantiomers.",
    }
    bad = _check(client, aid, 2, "five").json()
    assert bad["correct"] is False and bad["correct_answer"] == "4"
    assert graded == ["Racemic mixture.", "five"]
    assert _check(client, aid, 0, "Racemate").status_code == 422  # MCQ wants an index


# -- complete -----------------------------------------------------------------------------


def test_complete_requires_all_checked_and_records_progress(
    client: TestClient, db_session: Session, enqueued: list[tuple[str, str]]
) -> None:
    ctx = _setup(client, db_session, enqueued)
    attempt_id = _start(client, ctx).json()["attempt_id"]
    q0 = ctx.questions[0]
    _check(client, attempt_id, 0, (q0["correct_index"] + 1) % 4)
    early = _complete(client, attempt_id)
    assert early.status_code == 409
    assert early.json()["error"]["code"] == "incomplete"
    assert client.get(f"/api/student/artifacts/{ctx.quiz_id}").json()["completed"] is False

    for i, q in enumerate(ctx.questions[1:], start=1):
        _check(client, attempt_id, i, q["correct_index"])
    done = _complete(client, attempt_id)
    assert done.status_code == 200
    body = done.json()
    total = len(ctx.questions)
    assert body["correct_count"] == total - 1
    assert body["total_count"] == total
    assert body["score_percent"] == round(100 * (total - 1) / total, 2)
    assert body["best_score_percent"] == body["latest_score_percent"] == body["score_percent"]
    assert body["review"][0] == {
        "index": 0,
        "type": "mcq",
        "question": q0["question"],
        "options": q0["options"],
        "response": (q0["correct_index"] + 1) % 4,
        "correct": False,
        "correct_answer": q0["options"][q0["correct_index"]],
        "correct_index": q0["correct_index"],
        "explanation": q0.get("explanation", ""),
    }
    assert client.get(f"/api/student/artifacts/{ctx.quiz_id}").json()["completed"] is True

    attempt = db_session.get(QuizAttempt, uuid.UUID(attempt_id))
    assert attempt is not None
    assert attempt.completed_at is not None and attempt.submitted_at is not None

    # completing twice returns the same result; checking after completion is refused
    assert _complete(client, attempt_id).json() == body
    assert _check(client, attempt_id, 0, 0).status_code == 409


def test_retake_history_tracks_best_and_latest(
    client: TestClient, db_session: Session, enqueued: list[tuple[str, str]]
) -> None:
    ctx = _setup(client, db_session, enqueued)
    _finish(client, db_session, _start(client, ctx).json()["attempt_id"])
    _add_set(db_session, ctx, QuizSetStatus.ready)
    second = _finish(client, db_session, _start(client, ctx).json()["attempt_id"], correct=False)
    assert second["score_percent"] == 0.0
    assert second["best_score_percent"] == 100.0
    assert second["latest_score_percent"] == 0.0

    _start(client, ctx)  # an open attempt is not listed
    history = client.get(f"/api/student/artifacts/{ctx.quiz_id}/quiz-attempts").json()
    assert len(history["attempts"]) == 2
    assert history["best_score_percent"] == 100.0
    assert history["latest_score_percent"] == 0.0
    assert history["attempts"][0]["score_percent"] == 0.0  # newest first


# -- retakes ------------------------------------------------------------------------------


def test_retake_consumes_the_ready_chat_set_in_the_same_commit(
    client: TestClient,
    db_session: Session,
    enqueued: list[tuple[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = _setup(client, db_session, enqueued)
    _finish(client, db_session, _start(client, ctx).json()["attempt_id"])
    ready = _add_set(db_session, ctx, QuizSetStatus.ready)
    enqueued.clear()

    events: list[Any] = []
    real_commit = db_session.commit

    def commit() -> None:
        db_session.flush()
        attempts = db_session.scalars(
            select(QuizAttempt).where(QuizAttempt.question_set_id == ready.id)
        ).all()
        events.append(("commit", ready.status, len(attempts)))
        real_commit()

    monkeypatch.setattr(db_session, "commit", commit)
    monkeypatch.setattr(
        "app.api.student.quiz.enqueue_prepare",
        lambda aid, uid: events.append(("enqueue", str(aid), str(uid))),
    )

    resp = _start(client, ctx)
    assert resp.status_code == 201
    body = resp.json()
    assert body["source"] == "chat"
    assert body["attempt_number"] == 2
    assert body["total_count"] == 3
    _no_secrets(body)
    assert _attempt_set(db_session, body["attempt_id"]).id == ready.id
    assert ready.status is QuizSetStatus.used
    # one commit writes both the used set and the attempt; enqueue only afterwards
    assert events[0] == ("commit", QuizSetStatus.used, 1)
    assert events[1] == ("enqueue", ctx.quiz_id, str(ctx.student_id))


def test_retake_while_preparing(
    client: TestClient, db_session: Session, enqueued: list[tuple[str, str]]
) -> None:
    ctx = _setup(client, db_session, enqueued)
    _finish(client, db_session, _start(client, ctx).json()["attempt_id"])
    _add_set(db_session, ctx, QuizSetStatus.preparing)
    enqueued.clear()
    for _ in range(3):  # the client polls every 3 s while a fresh set is preparing
        resp = _start(client, ctx)
        assert resp.status_code == 202
        assert resp.json() == PREPARING
    assert _attempt_count(db_session, ctx) == 1
    assert enqueued == []  # already being prepared: polling never enqueues again


def test_retake_with_no_set_yet_is_preparing(
    client: TestClient, db_session: Session, enqueued: list[tuple[str, str]]
) -> None:
    ctx = _setup(client, db_session, enqueued)
    _finish(client, db_session, _start(client, ctx).json()["attempt_id"])
    enqueued.clear()
    resp = _start(client, ctx)
    assert resp.status_code == 202
    assert resp.json() == PREPARING
    assert enqueued == [(ctx.quiz_id, str(ctx.student_id))]


def test_retake_when_failed(
    client: TestClient, db_session: Session, enqueued: list[tuple[str, str]]
) -> None:
    ctx = _setup(client, db_session, enqueued)
    _finish(client, db_session, _start(client, ctx).json()["attempt_id"])
    _add_set(db_session, ctx, QuizSetStatus.failed)
    enqueued.clear()
    resp = _start(client, ctx)
    assert resp.status_code == 409
    assert resp.json()["message"] == UNAVAILABLE
    assert resp.json()["error"]["message"] == UNAVAILABLE
    assert _attempt_count(db_session, ctx) == 1
    assert enqueued == [(ctx.quiz_id, str(ctx.student_id))]


def test_retake_when_preparing_is_stale(
    client: TestClient, db_session: Session, enqueued: list[tuple[str, str]]
) -> None:
    ctx = _setup(client, db_session, enqueued)
    _finish(client, db_session, _start(client, ctx).json()["attempt_id"])
    old = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=16)
    _add_set(db_session, ctx, QuizSetStatus.preparing, created_at=old)
    enqueued.clear()
    resp = _start(client, ctx)
    assert resp.status_code == 409
    assert resp.json()["message"] == UNAVAILABLE
    assert enqueued == [(ctx.quiz_id, str(ctx.student_id))]


def test_retake_while_a_long_preparation_still_beats(
    client: TestClient, db_session: Session, enqueued: list[tuple[str, str]]
) -> None:
    """Created long ago (retries with back-off) but its task beat recently: still coming."""
    ctx = _setup(client, db_session, enqueued)
    _finish(client, db_session, _start(client, ctx).json()["attempt_id"])
    now = dt.datetime.now(dt.UTC)
    _add_set(
        db_session,
        ctx,
        QuizSetStatus.preparing,
        created_at=now - dt.timedelta(minutes=40),
        heartbeat_at=now - dt.timedelta(minutes=2),
    )
    enqueued.clear()
    resp = _start(client, ctx)
    assert resp.status_code == 202
    assert resp.json() == PREPARING
    assert enqueued == []


def test_retake_when_the_preparation_stopped_beating(
    client: TestClient, db_session: Session, enqueued: list[tuple[str, str]]
) -> None:
    ctx = _setup(client, db_session, enqueued)
    _finish(client, db_session, _start(client, ctx).json()["attempt_id"])
    now = dt.datetime.now(dt.UTC)
    _add_set(
        db_session,
        ctx,
        QuizSetStatus.preparing,
        created_at=now - dt.timedelta(minutes=17),
        heartbeat_at=now - dt.timedelta(minutes=16),
    )
    enqueued.clear()
    resp = _start(client, ctx)
    assert resp.status_code == 409
    assert resp.json()["message"] == UNAVAILABLE
    assert enqueued == [(ctx.quiz_id, str(ctx.student_id))]


def test_switch_off_reuses_the_studio_quiz(
    client: TestClient, db_session: Session, enqueued: list[tuple[str, str]]
) -> None:
    ctx = _setup(client, db_session, enqueued)
    module = db_session.get(Module, ctx.module_id)
    assert module is not None
    module.quiz_fresh_retakes = False
    db_session.flush()

    _finish(client, db_session, _start(client, ctx).json()["attempt_id"])
    ready = _add_set(db_session, ctx, QuizSetStatus.ready)  # completed after the switch-off
    enqueued.clear()

    resp = _start(client, ctx)
    assert resp.status_code == 201
    body = resp.json()
    assert body["source"] == "studio"
    assert body["attempt_number"] == 2
    assert [q["question"] for q in body["questions"]] == [q["question"] for q in ctx.questions]
    qs = _attempt_set(db_session, body["attempt_id"])
    assert qs.source is QuizSetSource.studio and qs.status is QuizSetStatus.used
    assert ready.status is QuizSetStatus.ready  # never served
    assert enqueued == []


# -- access -------------------------------------------------------------------------------


def test_attempts_are_owner_only(
    client: TestClient, db_session: Session, enqueued: list[tuple[str, str]]
) -> None:
    ctx = _setup(client, db_session, enqueued)
    attempt_id = _start(client, ctx).json()["attempt_id"]
    _register(client, "qz-other@example.com")
    assert _check(client, attempt_id, 0, 0).status_code == 404
    assert _complete(client, attempt_id).status_code == 404
    assert _check(client, str(uuid.uuid4()), 0, 0).status_code == 404
    # the other student gets their own attempt
    mine = _start(client, ctx).json()
    assert mine["attempt_id"] != attempt_id and mine["attempt_number"] == 1


def test_quiz_endpoints_require_a_student(
    client: TestClient, db_session: Session, enqueued: list[tuple[str, str]]
) -> None:
    ctx = _setup(client, db_session, enqueued)
    attempt_id = _start(client, ctx).json()["attempt_id"]
    client.cookies.clear()
    assert _start(client, ctx).status_code == 401
    assert _check(client, attempt_id, 0, 0).status_code == 401
    assert _complete(client, attempt_id).status_code == 401
    assert client.get(f"/api/student/artifacts/{ctx.quiz_id}/quiz-attempts").status_code == 401


def test_a_non_quiz_artifact_is_not_found(
    client: TestClient, db_session: Session, enqueued: list[tuple[str, str]]
) -> None:
    ctx = _setup(client, db_session, enqueued)
    report = db_session.scalar(
        select(Artifact).where(
            Artifact.module_id == ctx.module_id, Artifact.type == ArtifactType.report
        )
    )
    assert report is not None
    assert client.post(f"/api/student/artifacts/{report.id}/quiz-attempts").status_code == 404


# -- option shuffling ---------------------------------------------------------------------


def _shown_position(q: dict[str, Any]) -> int:
    """Where `_Reverse` shows the correct option of a 4-option question."""
    return 3 - int(q["correct_index"])


def _no_order_leak(payload: Any) -> None:
    text = json.dumps(payload)
    for key in ("option_orders", "order", "original_index", "permutation"):
        assert f'"{key}"' not in text, key


def test_rng_is_cryptographic() -> None:
    assert isinstance(REAL_RNG, random.SystemRandom)


def test_option_orders_are_permutations_and_vary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(quiz_api, "_rng", random.Random(20261027))
    questions = [
        {"type": "mcq", "question": "q", "options": ["a", "b", "c", "d"], "correct_index": 0},
        {"type": "fill_blank", "question": "x ____", "answer": "y"},
    ]
    positions = []
    for _ in range(400):
        orders = quiz_api._new_option_orders(questions)
        assert set(orders) == {"0"}  # fill-blank questions are never shuffled
        assert sorted(orders["0"]) == [0, 1, 2, 3]
        positions.append(orders["0"].index(0))  # display position of the correct option
    counts = [positions.count(p) for p in range(4)]
    assert all(c > 60 for c in counts), counts  # ~100 each: not always first


def test_start_check_resume_and_complete_use_the_shown_order(
    client: TestClient,
    db_session: Session,
    enqueued: list[tuple[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = _setup(client, db_session, enqueued)
    monkeypatch.setattr(quiz_api, "_rng", _Reverse())
    started = _start(client, ctx).json()
    _no_secrets(started)
    _no_order_leak(started)
    aid = started["attempt_id"]
    for got, q in zip(started["questions"], ctx.questions, strict=True):
        assert got["options"] == list(reversed(q["options"]))

    attempt = db_session.get(QuizAttempt, uuid.UUID(aid))
    assert attempt is not None
    assert attempt.option_orders == {str(i): [3, 2, 1, 0] for i in range(len(ctx.questions))}
    # stored content is untouched
    assert _attempt_set(db_session, aid).questions == [{**q, "type": "mcq"} for q in ctx.questions]

    # the shown position of the correct option is right
    q0 = ctx.questions[0]
    ok = _check(client, aid, 0, _shown_position(q0))
    assert ok.status_code == 200
    assert ok.json() == {
        "index": 0,
        "response": _shown_position(q0),
        "correct": True,
        "correct_answer": q0["options"][q0["correct_index"]],
        "correct_index": _shown_position(q0),
        "explanation": q0.get("explanation", ""),
    }
    _no_order_leak(ok.json())
    # the stored (original) index of the correct option is now another option: wrong
    q1 = ctx.questions[1]
    bad = _check(client, aid, 1, q1["correct_index"]).json()
    assert bad["correct"] is False
    assert bad["correct_index"] == _shown_position(q1)
    assert bad["correct_answer"] == q1["options"][q1["correct_index"]]
    assert started["questions"][1]["options"][bad["correct_index"]] == bad["correct_answer"]

    # a different RNG now must not change this attempt's order on resume
    monkeypatch.setattr(quiz_api, "_rng", random.Random(7))
    resumed = _start(client, ctx).json()
    assert resumed["status"] == "resumed"
    assert [q["options"] for q in resumed["questions"]] == [
        q["options"] for q in started["questions"]
    ]
    assert resumed["questions"][0]["result"] == ok.json()
    assert resumed["questions"][1]["result"] == bad
    assert resumed["correct_count"] == 1
    _no_order_leak(resumed)

    for i, q in enumerate(ctx.questions[2:], start=2):
        assert _check(client, aid, i, _shown_position(q)).json()["correct"] is True
    done = _complete(client, aid).json()
    _no_order_leak(done)
    assert done["correct_count"] == len(ctx.questions) - 1
    row1 = done["review"][1]
    assert row1["options"] == started["questions"][1]["options"]
    assert row1["response"] == q1["correct_index"]
    assert row1["correct"] is False
    assert row1["correct_index"] == _shown_position(q1)
    assert row1["options"][row1["correct_index"]] == row1["correct_answer"]
    assert done["review"][0]["correct_index"] == _shown_position(q0)


def test_chat_sets_shuffle_mcq_only(
    client: TestClient,
    db_session: Session,
    enqueued: list[tuple[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = _setup(client, db_session, enqueued)
    _finish(client, db_session, _start(client, ctx).json()["attempt_id"])
    _add_set(db_session, ctx, QuizSetStatus.ready)
    monkeypatch.setattr(quiz_api, "_rng", _Reverse())
    body = _start(client, ctx).json()
    assert body["source"] == "chat"
    _no_secrets(body)
    _no_order_leak(body)
    assert body["questions"][0]["options"] == [
        "No product",
        "Meso compound",
        "Single enantiomer",
        "Racemate",
    ]
    assert body["questions"][1]["options"] is None
    aid = body["attempt_id"]
    attempt = db_session.get(QuizAttempt, uuid.UUID(aid))
    assert attempt is not None and attempt.option_orders == {"0": [3, 2, 1, 0]}

    assert _check(client, aid, 0, 0).json()["correct"] is False  # stored index 0, moved
    assert _check(client, aid, 1, "racemate").json()["correct"] is True
    assert _check(client, aid, 2, "4").json()["correct"] is True
    done = _complete(client, aid).json()
    assert done["review"][0]["correct_index"] == 3
    assert done["review"][0]["correct_answer"] == "Racemate"
    assert done["review"][0]["response"] == 0


def test_open_attempt_without_stored_order_keeps_the_stored_order(
    client: TestClient,
    db_session: Session,
    enqueued: list[tuple[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = _setup(client, db_session, enqueued)
    aid = _start(client, ctx).json()["attempt_id"]
    attempt = db_session.get(QuizAttempt, uuid.UUID(aid))
    assert attempt is not None
    attempt.option_orders = None  # opened before shuffling existed
    db_session.flush()

    monkeypatch.setattr(quiz_api, "_rng", _Reverse())
    resumed = _start(client, ctx).json()
    assert resumed["status"] == "resumed"
    assert [q["options"] for q in resumed["questions"]] == [q["options"] for q in ctx.questions]
    for i, q in enumerate(ctx.questions):
        res = _check(client, aid, i, q["correct_index"]).json()
        assert res["correct"] is True and res["correct_index"] == q["correct_index"]
    done = _complete(client, aid).json()
    assert done["score_percent"] == 100.0
    assert done["review"][0]["options"] == ctx.questions[0]["options"]


# -- the quiz's language and difficulty (owner decision 2026-10-29) ------------------------


def _set_quiz_options(db: Session, ctx: Ctx, **options: str) -> None:
    """The admin published a quiz version made with `options` (retakes follow the
    PUBLISHED version's options, owner decision 2026-10-30)."""
    quiz = db.get(Artifact, uuid.UUID(ctx.quiz_id))
    assert quiz is not None
    quiz.generation_options = {**quiz.generation_options, **options}
    published = next(v for v in quiz.versions if v.id == quiz.published_version_id)
    published.generation_options = {**(published.generation_options or {}), **options}
    db.flush()


def test_an_unpublished_redo_in_another_language_keeps_serving_the_published_ones(
    client: TestClient, db_session: Session, enqueued: list[tuple[str, str]]
) -> None:
    """A Redo to Tamil was queued (the artifact's options changed) and its version is
    stored but not published: the English set is still served."""
    ctx = _setup(client, db_session, enqueued)
    _finish(client, db_session, _start(client, ctx).json()["attempt_id"])
    english = _add_set(db_session, ctx, QuizSetStatus.ready)
    quiz = db_session.get(Artifact, uuid.UUID(ctx.quiz_id))
    assert quiz is not None
    orchestrator.enqueue_artifact_regeneration(
        db_session, quiz.id, redo_note="tamil", options={"language": "ta"}
    )
    orchestrator.run_artifact_generation(db_session, PROVIDER, quiz.id, redo_note="tamil")
    db_session.expire_all()

    resp = _start(client, ctx)
    assert resp.status_code == 201, resp.text
    assert _attempt_set(db_session, resp.json()["attempt_id"]).id == english.id


def test_publishing_a_version_in_another_language_discards_the_ready_set(
    client: TestClient, db_session: Session, enqueued: list[tuple[str, str]]
) -> None:
    ctx = _setup(client, db_session, enqueued)
    _finish(client, db_session, _start(client, ctx).json()["attempt_id"])
    english = _add_set(db_session, ctx, QuizSetStatus.ready)
    quiz = db_session.get(Artifact, uuid.UUID(ctx.quiz_id))
    assert quiz is not None
    orchestrator.enqueue_artifact_regeneration(
        db_session, quiz.id, redo_note="tamil", options={"language": "ta"}
    )
    orchestrator.run_artifact_generation(db_session, PROVIDER, quiz.id, redo_note="tamil")
    db_session.expire_all()
    module = db_session.get(Module, ctx.module_id)
    assert module is not None
    publish_module(db_session, module)
    db_session.flush()

    assert _start(client, ctx).status_code == 202
    db_session.refresh(english)
    assert english.status is QuizSetStatus.failed
    assert "the quiz is now ta/medium" in english.validation_report["error"]


@pytest.mark.parametrize("status", [QuizSetStatus.ready, QuizSetStatus.preparing])
def test_a_set_for_another_language_is_discarded_and_the_retake_waits(
    status: QuizSetStatus,
    client: TestClient,
    db_session: Session,
    enqueued: list[tuple[str, str]],
) -> None:
    """The admin switched the quiz to Tamil after the student's English set was prepared:
    the English set is never served; a Tamil one is prepared (202, not "unavailable")."""
    ctx = _setup(client, db_session, enqueued)
    _finish(client, db_session, _start(client, ctx).json()["attempt_id"])
    english = _add_set(db_session, ctx, status, heartbeat_at=dt.datetime.now(dt.UTC))
    _set_quiz_options(db_session, ctx, language="ta")
    enqueued.clear()

    resp = _start(client, ctx)
    assert resp.status_code == 202, resp.text
    assert resp.json()["status"] == "preparing"
    assert enqueued == [(ctx.quiz_id, str(ctx.student_id))]
    db_session.refresh(english)
    assert english.status is QuizSetStatus.failed
    assert english.validation_report["discarded"] is True

    # the next poll, before the task has inserted the new set, still says "preparing"
    again = _start(client, ctx)
    assert again.status_code == 202 and again.json()["status"] == "preparing"


def test_a_set_without_a_recorded_language_is_discarded(
    client: TestClient, db_session: Session, enqueued: list[tuple[str, str]]
) -> None:
    """Sets prepared before this change (English prompt, no record) are replaced."""
    ctx = _setup(client, db_session, enqueued)
    _finish(client, db_session, _start(client, ctx).json()["attempt_id"])
    legacy = _add_set(db_session, ctx, QuizSetStatus.ready)
    legacy.validation_report = {}
    db_session.flush()
    assert _start(client, ctx).status_code == 202
    db_session.refresh(legacy)
    assert legacy.status is QuizSetStatus.failed


def test_a_set_for_another_difficulty_is_discarded(
    client: TestClient, db_session: Session, enqueued: list[tuple[str, str]]
) -> None:
    ctx = _setup(client, db_session, enqueued)
    _finish(client, db_session, _start(client, ctx).json()["attempt_id"])
    _add_set(db_session, ctx, QuizSetStatus.ready)
    _set_quiz_options(db_session, ctx, difficulty="hard")
    assert _start(client, ctx).status_code == 202


def test_a_set_for_the_quiz_language_and_difficulty_is_served(
    client: TestClient, db_session: Session, enqueued: list[tuple[str, str]]
) -> None:
    ctx = _setup(client, db_session, enqueued)
    _finish(client, db_session, _start(client, ctx).json()["attempt_id"])
    _set_quiz_options(db_session, ctx, language="hi", difficulty="easy")
    hindi = _add_set(
        db_session, ctx, QuizSetStatus.ready, prepared_for={"language": "hi", "difficulty": "easy"}
    )
    resp = _start(client, ctx)
    assert resp.status_code == 201 and resp.json()["source"] == "chat"
    assert _attempt_set(db_session, resp.json()["attempt_id"]).id == hindi.id


def test_a_real_failure_after_a_discard_still_reports_unavailable(
    client: TestClient, db_session: Session, enqueued: list[tuple[str, str]]
) -> None:
    ctx = _setup(client, db_session, enqueued)
    _finish(client, db_session, _start(client, ctx).json()["attempt_id"])
    _add_set(db_session, ctx, QuizSetStatus.ready)
    _set_quiz_options(db_session, ctx, language="kn")
    assert _start(client, ctx).status_code == 202  # discarded
    _add_set(db_session, ctx, QuizSetStatus.failed)  # then the Kannada preparation failed
    assert _start(client, ctx).status_code == 409
