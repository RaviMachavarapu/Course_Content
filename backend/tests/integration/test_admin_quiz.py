"""Admin quiz audit (adaptive quiz, spec §4.5): generated question sets + retake switch."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.cli import seed_admin
from app.models.artifact import Artifact
from app.models.course import Course
from app.models.enums import (
    ArtifactType,
    ModuleSourceType,
    QuizSetSource,
    QuizSetStatus,
)
from app.models.module import Module
from app.models.quiz_question_set import QuizQuestionSet
from app.models.user import User, UserRole


def _setup(db: Session) -> tuple[Module, Artifact, User]:
    course = Course(title="C", slug=f"c-{uuid.uuid4()}")
    module = Module(
        course=course,
        order_index=0,
        title="M",
        source_url="https://youtu.be/x",
        source_type=ModuleSourceType.youtube,
    )
    db.add(module)
    db.flush()
    artifact = Artifact(module_id=module.id, type=ArtifactType.quiz)
    student = User(
        email="s@example.com",
        password_hash="x",
        role=UserRole.student,
        display_name="Stu Dent",
    )
    db.add_all([artifact, student])
    db.flush()
    return module, artifact, student


def _admin(client: TestClient, db: Session) -> dict[str, str]:
    seed_admin(db, email="qa@example.com", display_name="QA", password="quiz-admin-pw-12")
    db.flush()
    client.post(
        "/api/admin/auth/login", json={"email": "qa@example.com", "password": "quiz-admin-pw-12"}
    )
    return {"X-CSRF-Token": client.cookies["sdp_csrf"]}


def _set(
    db: Session, artifact: Artifact, student: User, age_min: int, **kw: object
) -> QuizQuestionSet:
    fields: dict[str, object] = {
        "source": QuizSetSource.chat,
        "status": QuizSetStatus.used,
        "created_at": dt.datetime.now(dt.UTC) - dt.timedelta(minutes=age_min),
        **kw,
    }
    row = QuizQuestionSet(artifact_id=artifact.id, user_id=student.id, **fields)
    db.add(row)
    db.flush()
    return row


def test_sets_require_admin(client: TestClient, db_session: Session) -> None:
    _, artifact, _ = _setup(db_session)
    assert client.get(f"/api/admin/artifacts/{artifact.id}/quiz-sets").status_code == 401


def test_sets_newest_first_with_reasons(client: TestClient, db_session: Session) -> None:
    _, artifact, student = _setup(db_session)
    q = [{"type": "mcq", "question": "Q1?", "answer": "A"}]
    _set(db_session, artifact, student, 30, questions=[], validation_report={})
    _set(
        db_session,
        artifact,
        student,
        5,
        questions=q * 2,
        validation_report={
            "rounds": [
                {
                    "round": 1,
                    "kept": ["a", "b"],
                    "dropped": [{"index": 3, "question": "Bad?", "reason": "duplicate"}],
                },
                {
                    "round": 2,
                    "kept": ["c"],
                    "dropped": [{"index": 0, "question": "Worse?", "reason": "shape"}],
                },
            ],
            "served": 2,
        },
    )
    _admin(client, db_session)
    body = client.get(f"/api/admin/artifacts/{artifact.id}/quiz-sets").json()
    assert len(body) == 2
    newest, oldest = body
    assert newest["question_count"] == 2
    assert newest["kept"] == 3 and newest["dropped"] == 2
    assert [d["reason"] for d in newest["dropped_questions"]] == ["duplicate", "shape"]
    assert newest["questions"][0]["answer"] == "A"
    assert newest["student"] == {"display_name": "Stu Dent", "email": "s@example.com"}
    assert newest["source"] == "chat" and newest["status"] == "used"
    assert oldest["kept"] == 0 and oldest["dropped_questions"] == []
    assert newest["warning"] is None and oldest["warning"] is None
    assert (
        client.get(f"/api/admin/artifacts/{artifact.id}/quiz-sets?limit=1").json()[0]["id"]
        == (newest["id"])
    )


def test_sets_default_to_chat_and_all_includes_studio(
    client: TestClient, db_session: Session
) -> None:
    _, artifact, student = _setup(db_session)
    chat = _set(db_session, artifact, student, 10, questions=[], validation_report={})
    studio = _set(
        db_session,
        artifact,
        student,
        5,
        questions=[],
        validation_report={},
        source=QuizSetSource.studio,
    )
    _admin(client, db_session)
    url = f"/api/admin/artifacts/{artifact.id}/quiz-sets"
    assert [r["id"] for r in client.get(url).json()] == [str(chat.id)]
    assert [r["id"] for r in client.get(f"{url}?source=chat").json()] == [str(chat.id)]
    assert [r["id"] for r in client.get(f"{url}?source=all").json()] == [
        str(studio.id),
        str(chat.id),
    ]
    assert client.get(f"{url}?source=bogus").status_code == 422


def test_sets_surface_the_reask_error_as_a_warning(client: TestClient, db_session: Session) -> None:
    _, artifact, student = _setup(db_session)
    _set(
        db_session,
        artifact,
        student,
        5,
        questions=[],
        validation_report={"rounds": [], "reask_error": "GenerationTimeout: chat took too long"},
    )
    _admin(client, db_session)
    (row,) = client.get(f"/api/admin/artifacts/{artifact.id}/quiz-sets").json()
    assert row["warning"] == "GenerationTimeout: chat took too long"
    assert row["error"] is None


def test_sets_unknown_artifact_404(client: TestClient, db_session: Session) -> None:
    _admin(client, db_session)
    assert client.get(f"/api/admin/artifacts/{uuid.uuid4()}/quiz-sets").status_code == 404


def test_switch_get_patch_and_csrf(client: TestClient, db_session: Session) -> None:
    module, _, _ = _setup(db_session)
    h = _admin(client, db_session)
    url = f"/api/admin/modules/{module.id}/quiz-settings"
    assert client.get(url).json() == {"fresh_retakes": True}
    assert client.patch(url, json={"fresh_retakes": False}).status_code == 403
    r = client.patch(url, json={"fresh_retakes": False}, headers=h)
    assert r.status_code == 200 and r.json() == {"fresh_retakes": False}
    assert client.get(url).json() == {"fresh_retakes": False}
    db_session.expire_all()
    assert db_session.get(Module, module.id).quiz_fresh_retakes is False  # type: ignore[union-attr]


@pytest.mark.parametrize("method", ["get", "patch"])
def test_switch_unknown_module_404(client: TestClient, db_session: Session, method: str) -> None:
    h = _admin(client, db_session)
    r = client.request(
        method,
        f"/api/admin/modules/{uuid.uuid4()}/quiz-settings",
        json={"fresh_retakes": True} if method == "patch" else None,
        headers=h,
    )
    assert r.status_code == 404
