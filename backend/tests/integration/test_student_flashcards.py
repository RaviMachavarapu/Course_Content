"""T034 — student flashcard ratings."""

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
TYPES = [ArtifactType.flashcards, ArtifactType.report]


@pytest.fixture(autouse=True)
def _no_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.api.admin.courses._dispatch_all", lambda *a, **k: None)


def _setup(client: TestClient, db: Session) -> tuple[str, str, str]:
    seed_admin(db, email="fc-admin@example.com", display_name="A", password="fc-admin-pw-1")
    db.flush()
    client.post(
        "/api/admin/auth/login",
        json={"email": "fc-admin@example.com", "password": "fc-admin-pw-1"},
    )
    h = {"X-CSRF-Token": client.cookies["sdp_csrf"]}
    cid = client.post("/api/admin/courses", json={"title": "FC"}, headers=h).json()["course"]["id"]
    mid = client.post(
        f"/api/admin/courses/{cid}/modules",
        json={
            "source_url": "https://example.com/fc",
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

    client.cookies.clear()
    client.post(
        "/api/student/auth/register",
        json={
            "email": "fc-learner@example.com",
            "password": "fc-learner-pw-1",
            "display_name": "L",
        },
    )
    ws = client.get(f"/api/student/courses/{slug}").json()
    by_type = {a["type"]: a["id"] for a in ws["modules"][0]["artifacts"]}
    return slug, by_type["flashcards"], by_type["report"]


def test_rating_a_card_upserts_and_returns_the_full_map(
    client: TestClient, db_session: Session
) -> None:
    _slug, fc_id, _report = _setup(client, db_session)

    r0 = client.put(f"/api/student/artifacts/{fc_id}/flashcard-ratings/0", json={"value": "hard"})
    assert r0.status_code == 200
    assert r0.json() == {"ratings": {"0": "hard"}}

    client.put(f"/api/student/artifacts/{fc_id}/flashcard-ratings/1", json={"value": "good"})
    updated = client.put(
        f"/api/student/artifacts/{fc_id}/flashcard-ratings/0", json={"value": "easy"}
    ).json()
    assert updated == {"ratings": {"0": "easy", "1": "good"}}

    got = client.get(f"/api/student/artifacts/{fc_id}").json()
    assert got["flashcard_ratings"] == {"0": "easy", "1": "good"}


def test_rating_rejects_bad_index_value_and_wrong_type(
    client: TestClient, db_session: Session
) -> None:
    _slug, fc_id, report_id = _setup(client, db_session)

    bad_idx = client.put(
        f"/api/student/artifacts/{fc_id}/flashcard-ratings/999", json={"value": "hard"}
    )
    assert bad_idx.status_code == 422
    assert bad_idx.json()["error"]["code"] == "bad_card_index"

    bad_val = client.put(
        f"/api/student/artifacts/{fc_id}/flashcard-ratings/0", json={"value": "meh"}
    )
    assert bad_val.status_code == 422

    wrong_type = client.put(
        f"/api/student/artifacts/{report_id}/flashcard-ratings/0", json={"value": "hard"}
    )
    assert wrong_type.status_code == 404


def test_rating_requires_a_student(client: TestClient, db_session: Session) -> None:
    _slug, fc_id, _report = _setup(client, db_session)
    client.cookies.clear()
    assert (
        client.put(
            f"/api/student/artifacts/{fc_id}/flashcard-ratings/0", json={"value": "good"}
        ).status_code
        == 401
    )
