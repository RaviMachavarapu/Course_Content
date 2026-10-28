"""Review 2026-10-28: INTEGER bounds (422, not a DB overflow 500) and
cover_image_key validation."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.cli import seed_admin
from app.models.course import Course
from app.models.enums import ArtifactType
from tests.integration.test_review_data_fixes import _artifact, _module, _student


# -- bounds / validation ------------------------------------------------------
def test_progress_rejects_values_beyond_integer(client: TestClient, db_session: Session) -> None:
    course = Course(title="B", slug=f"b-{uuid.uuid4()}")
    m = _module(db_session, course, 0, [ArtifactType.report])
    report = _artifact(m, ArtifactType.report)
    _student(client)
    url = f"/api/student/artifacts/{report.id}/progress"
    assert client.put(url, json={"audio_position_seconds": 3_000_000_000}).status_code == 422
    assert client.put(url, json={"slide_last_index": 2_147_483_648}).status_code == 422
    assert client.put(url, json={"audio_position_seconds": 2_147_483_647}).status_code == 200


def _admin(client: TestClient, db: Session) -> dict[str, str]:
    seed_admin(db, email="rv@example.com", display_name="R", password="review-admin-pw-1")
    db.flush()
    client.cookies.clear()
    client.post(
        "/api/admin/auth/login", json={"email": "rv@example.com", "password": "review-admin-pw-1"}
    )
    return {"X-CSRF-Token": client.cookies["sdp_csrf"]}


def test_admin_bounds(client: TestClient, db_session: Session) -> None:
    h = _admin(client, db_session)
    mid = uuid.uuid4()
    assert client.get(f"/api/admin/modules/{mid}/jobs?limit=-1").status_code == 422
    assert client.get(f"/api/admin/modules/{mid}/jobs?limit=500").status_code == 422
    assert client.get(f"/api/admin/modules/{mid}/jobs?limit=5").status_code == 200
    r = client.post(
        "/api/admin/uploads", json={"file_name": "a.pdf", "size_bytes": 2**63}, headers=h
    )
    assert r.status_code == 422


def test_cover_image_key_is_validated_and_clearable(
    client: TestClient, db_session: Session
) -> None:
    h = _admin(client, db_session)
    bad = client.post(
        "/api/admin/courses", json={"title": "C", "cover_image_key": "my cover.png"}, headers=h
    )
    assert bad.status_code == 422
    too_long = client.post(
        "/api/admin/courses", json={"title": "C", "cover_image_key": "a" * 513}, headers=h
    )
    assert too_long.status_code == 422
    cid = client.post(
        "/api/admin/courses", json={"title": "C", "cover_image_key": "covers/a.png"}, headers=h
    ).json()["course"]["id"]
    assert (
        client.patch(
            f"/api/admin/courses/{cid}", json={"cover_image_key": "../x"}, headers=h
        ).status_code
        == 422
    )
    client.patch(f"/api/admin/courses/{cid}", json={"title": "C2"}, headers=h)
    assert db_session.get(Course, uuid.UUID(cid)).cover_image_key == "covers/a.png"  # type: ignore[union-attr]
    client.patch(f"/api/admin/courses/{cid}", json={"cover_image_key": None}, headers=h)
    assert db_session.get(Course, uuid.UUID(cid)).cover_image_key is None  # type: ignore[union-attr]


def test_catalog_survives_a_bad_stored_cover_key(client: TestClient, db_session: Session) -> None:
    course = Course(title="Cov", slug=f"cov-{uuid.uuid4()}", cover_image_key="bad key.png")
    _module(db_session, course, 0, [ArtifactType.report])
    _student(client)
    r = client.get("/api/student/courses")
    assert r.status_code == 200
    row = next(c for c in r.json()["courses"] if c["slug"] == course.slug)
    assert row["cover_image_url"] is None
