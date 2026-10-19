"""T035 — student quiz attempts (submit / score / history / no answer leak)."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.cli import seed_admin
from app.models.enums import ArtifactType
from app.models.module import Module
from app.pipeline import orchestrator
from app.pipeline.fixture import FixtureProvider
from app.services.publish import publish_module

PROVIDER = FixtureProvider()
TYPES = [ArtifactType.quiz, ArtifactType.report]


@pytest.fixture(autouse=True)
def _no_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.api.admin.courses._dispatch_all", lambda *a, **k: None)


def _setup(client: TestClient, db: Session) -> tuple[str, str, list[dict]]:
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

    client.cookies.clear()
    client.post(
        "/api/student/auth/register",
        json={
            "email": "qz-learner@example.com",
            "password": "qz-learner-pw-1",
            "display_name": "L",
        },
    )
    ws = client.get(f"/api/student/courses/{slug}").json()
    by_type = {a["type"]: a["id"] for a in ws["modules"][0]["artifacts"]}
    return by_type["quiz"], by_type["report"], questions


def test_questions_do_not_leak_answers_before_submit(
    client: TestClient, db_session: Session
) -> None:
    quiz_id, _r, _q = _setup(client, db_session)
    got = client.get(f"/api/student/artifacts/{quiz_id}").json()
    for q in got["content_json"]["questions"]:
        assert "correct_index" not in q
        assert "explanation" not in q
        assert len(q["options"]) == 4


def test_submit_scores_marks_complete_and_stores_the_attempt(
    client: TestClient, db_session: Session
) -> None:
    quiz_id, _r, questions = _setup(client, db_session)
    total = len(questions)

    # answer the first question wrong, the rest correct
    answers = {str(i): q["correct_index"] for i, q in enumerate(questions)}
    answers["0"] = (questions[0]["correct_index"] + 1) % 4
    expected_correct = total - 1

    incomplete = client.post(
        f"/api/student/artifacts/{quiz_id}/quiz-attempts", json={"answers": {"0": 1}}
    )
    assert incomplete.status_code == 422
    assert incomplete.json()["error"]["code"] == "incomplete"

    resp = client.post(f"/api/student/artifacts/{quiz_id}/quiz-attempts", json={"answers": answers})
    assert resp.status_code == 201
    result = resp.json()
    assert result["correct_count"] == expected_correct
    assert result["total_count"] == total
    assert result["score_percent"] == round(100 * expected_correct / total, 2)
    assert result["results"][0]["is_correct"] is False
    assert result["results"][1]["is_correct"] is True
    assert "explanation" in result["results"][0]

    # completion rolled up (quiz is 1 of 2 published artifacts -> 50 %)
    assert client.get(f"/api/student/artifacts/{quiz_id}").json()["completed"] is True


def test_retake_creates_a_new_attempt_and_tracks_best(
    client: TestClient, db_session: Session
) -> None:
    quiz_id, _r, questions = _setup(client, db_session)
    all_right = {str(i): q["correct_index"] for i, q in enumerate(questions)}
    all_wrong = {str(i): (q["correct_index"] + 1) % 4 for i, q in enumerate(questions)}

    client.post(f"/api/student/artifacts/{quiz_id}/quiz-attempts", json={"answers": all_right})
    second = client.post(
        f"/api/student/artifacts/{quiz_id}/quiz-attempts", json={"answers": all_wrong}
    ).json()
    assert second["score_percent"] == 0.0
    assert second["best_score_percent"] == 100.0
    assert second["latest_score_percent"] == 0.0

    history = client.get(f"/api/student/artifacts/{quiz_id}/quiz-attempts").json()
    assert len(history["attempts"]) == 2
    assert history["best_score_percent"] == 100.0
    assert history["latest_score_percent"] == 0.0
    assert history["attempts"][0]["score_percent"] == 0.0  # newest first


def test_quiz_endpoints_require_a_student(client: TestClient, db_session: Session) -> None:
    quiz_id, _r, _q = _setup(client, db_session)
    client.cookies.clear()
    assert (
        client.post(
            f"/api/student/artifacts/{quiz_id}/quiz-attempts", json={"answers": {}}
        ).status_code
        == 401
    )
    assert client.get(f"/api/student/artifacts/{quiz_id}/quiz-attempts").status_code == 401
