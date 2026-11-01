"""T025 — admin courses & module ingestion API."""

from __future__ import annotations

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.cli import seed_admin

ALL_TYPES = ["slide_deck", "flashcards", "quiz", "report", "infographic", "audio_overview"]


@pytest.fixture(autouse=True)
def _no_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.api.admin.courses._dispatch_all", lambda *a, **k: None)


def _admin(client: TestClient, db: Session) -> dict[str, str]:
    seed_admin(db, email="c@example.com", display_name="C", password="courses-admin-pw-1")
    db.flush()
    client.post(
        "/api/admin/auth/login", json={"email": "c@example.com", "password": "courses-admin-pw-1"}
    )
    return {"X-CSRF-Token": client.cookies["sdp_csrf"]}


def test_requires_admin(client: TestClient) -> None:
    assert client.get("/api/admin/courses").status_code == status.HTTP_401_UNAUTHORIZED


def test_create_course_and_list(client: TestClient, db_session: Session) -> None:
    h = _admin(client, db_session)
    r = client.post(
        "/api/admin/courses",
        json={"title": "Intro to ML", "description": "d", "category": "AI"},
        headers=h,
    )
    assert r.status_code == status.HTTP_201_CREATED
    course = r.json()["course"]
    assert course["slug"] == "intro-to-ml"
    assert course["modules"] == []

    listing = client.get("/api/admin/courses").json()["courses"]
    assert any(c["id"] == course["id"] and c["module_count"] == 0 for c in listing)


def test_slug_is_uniquified(client: TestClient, db_session: Session) -> None:
    h = _admin(client, db_session)
    a = client.post("/api/admin/courses", json={"title": "Dup"}, headers=h).json()["course"]
    b = client.post("/api/admin/courses", json={"title": "Dup"}, headers=h).json()["course"]
    assert {a["slug"], b["slug"]} == {"dup", "dup-2"}


def test_create_module_starts_generation(client: TestClient, db_session: Session) -> None:
    h = _admin(client, db_session)
    cid = client.post("/api/admin/courses", json={"title": "C1"}, headers=h).json()["course"]["id"]

    r = client.post(
        f"/api/admin/courses/{cid}/modules",
        json={
            "source_url": "https://www.youtube.com/watch?v=abc",
            "title": "Module 1",
            "types": ["report", "quiz"],
        },
        headers=h,
    )
    assert r.status_code == status.HTTP_201_CREATED
    body = r.json()
    mod = body["module"]
    assert mod["source_type"] == "youtube"
    assert mod["order_index"] == 0
    assert len(mod["artifacts"]) == 6  # BR1 — all six rows exist
    assert len(body["job_ids"]) == 2

    detail = client.get(f"/api/admin/courses/{cid}").json()["course"]
    assert len(detail["modules"]) == 1
    assert detail["modules"][0]["status"] in ("processing", "pending_review")


def test_create_module_stores_per_type_generation_options(
    client: TestClient, db_session: Session
) -> None:
    from sqlalchemy import select

    from app.models.artifact import Artifact
    from app.models.module import Module

    h = _admin(client, db_session)
    cid = client.post("/api/admin/courses", json={"title": "C2"}, headers=h).json()["course"]["id"]

    r = client.post(
        f"/api/admin/courses/{cid}/modules",
        json={
            "source_url": "https://www.youtube.com/watch?v=opts",
            "title": "Module 1",
            # "report" is requested but given no options entry, to prove it
            # still gets that type's defaults, not an empty dict.
            "types": ["quiz", "audio_overview", "infographic", "report"],
            "options": {
                "quiz": {"quantity": "more", "difficulty": "hard"},
                "audio_overview": {"format": "debate", "length": "short", "language": "hi"},
                "infographic": {"orientation": "portrait"},
            },
        },
        headers=h,
    )
    assert r.status_code == status.HTTP_201_CREATED
    module_id = r.json()["module"]["id"]

    module = db_session.get(Module, module_id)
    assert module is not None
    by_type = {a.type.value: a for a in module.artifacts}
    assert by_type["quiz"].generation_options == {
        "quantity": "more",
        "difficulty": "hard",
        "language": "en",
    }
    assert by_type["audio_overview"].generation_options == {
        "format": "debate",
        "length": "short",
        "language": "hi",
    }
    # orientation given, the rest defaulted
    assert by_type["infographic"].generation_options == {
        "orientation": "portrait",
        "language": "en",
        "detail": "standard",
        "style": "auto",
    }
    # requested but no options entry -> that type's defaults, not empty
    assert by_type["report"].generation_options == {
        "format": "interactive",
        "template": None,
        "language": "en",
    }
    # BR1's other rows exist but weren't requested for this ingest — left
    # untouched (empty) until they're actually generated
    slide_deck = db_session.scalar(
        select(Artifact).where(Artifact.module_id == module_id, Artifact.type == "slide_deck")
    )
    assert slide_deck is not None
    assert slide_deck.generation_options == {}


def test_create_module_stores_custom_prompts(client: TestClient, db_session: Session) -> None:
    from app.models.module import Module

    h = _admin(client, db_session)
    cid = client.post("/api/admin/courses", json={"title": "CP"}, headers=h).json()["course"]["id"]
    r = client.post(
        f"/api/admin/courses/{cid}/modules",
        json={
            "source_url": "https://www.youtube.com/watch?v=prompts",
            "title": "Module 1",
            "types": ["quiz", "flashcards", "report"],
            "prompts": {"quiz": " Three questions on chapter 1 ", "flashcards": "   "},
        },
        headers=h,
    )
    assert r.status_code == status.HTTP_201_CREATED
    module = db_session.get(Module, r.json()["module"]["id"])
    assert module is not None
    by_type = {a.type.value: a for a in module.artifacts}
    assert by_type["quiz"].custom_prompt == "Three questions on chapter 1"
    assert by_type["flashcards"].custom_prompt is None  # blank -> template
    assert by_type["report"].custom_prompt is None  # omitted -> template


def test_create_module_rejects_bad_option_value(client: TestClient, db_session: Session) -> None:
    h = _admin(client, db_session)
    cid = client.post("/api/admin/courses", json={"title": "C3"}, headers=h).json()["course"]["id"]

    r = client.post(
        f"/api/admin/courses/{cid}/modules",
        json={
            "source_url": "https://www.youtube.com/watch?v=bad",
            "title": "Module 1",
            "types": ["quiz"],
            "options": {"quiz": {"difficulty": "extreme"}},  # not a real choice
        },
        headers=h,
    )
    assert r.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert r.json()["error"]["code"] == "validation_error"


def test_module_rejects_unsupported_source(client: TestClient, db_session: Session) -> None:
    h = _admin(client, db_session)
    cid = client.post("/api/admin/courses", json={"title": "C2"}, headers=h).json()["course"]["id"]
    r = client.post(
        f"/api/admin/courses/{cid}/modules",
        json={"source_url": "ftp://nope", "title": "m", "types": ["report"]},
        headers=h,
    )
    assert r.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert r.json()["error"]["code"] == "unsupported_source"


def test_module_requires_at_least_one_type(client: TestClient, db_session: Session) -> None:
    h = _admin(client, db_session)
    cid = client.post("/api/admin/courses", json={"title": "C3"}, headers=h).json()["course"]["id"]
    r = client.post(
        f"/api/admin/courses/{cid}/modules",
        json={"source_url": "https://example.com/a", "title": "m", "types": []},
        headers=h,
    )
    assert r.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_patch_and_delete_module_cascades(client: TestClient, db_session: Session) -> None:
    h = _admin(client, db_session)
    cid = client.post("/api/admin/courses", json={"title": "C4"}, headers=h).json()["course"]["id"]
    client.patch(f"/api/admin/courses/{cid}", json={"category": "Data"}, headers=h)
    assert client.get(f"/api/admin/courses/{cid}").json()["course"]["category"] == "Data"

    mid = client.post(
        f"/api/admin/courses/{cid}/modules",
        json={"source_url": "https://example.com/x", "title": "m", "types": ["report"]},
        headers=h,
    ).json()["module"]["id"]
    assert (
        client.request("DELETE", f"/api/admin/courses/modules/{mid}", headers=h).status_code
        == status.HTTP_204_NO_CONTENT
    )
    assert client.get(f"/api/admin/courses/{cid}").json()["course"]["modules"] == []
