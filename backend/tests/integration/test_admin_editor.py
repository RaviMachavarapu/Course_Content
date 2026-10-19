"""T028 — Course Editor module operations."""

from __future__ import annotations

import uuid

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.cli import seed_admin
from app.models.artifact import Artifact
from app.models.enums import ArtifactStatus, ArtifactType
from app.models.generation_job import GenerationJob
from app.models.module import Module
from app.pipeline import orchestrator
from app.pipeline.fixture import FixtureProvider

PROVIDER = FixtureProvider()


@pytest.fixture(autouse=True)
def _no_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.api.admin.courses._dispatch_all", lambda *a, **k: None)


def _admin(client: TestClient, db: Session) -> dict[str, str]:
    seed_admin(db, email="ed@example.com", display_name="E", password="editor-admin-pw-1")
    db.flush()
    client.post(
        "/api/admin/auth/login",
        json={"email": "ed@example.com", "password": "editor-admin-pw-1"},
    )
    return {"X-CSRF-Token": client.cookies["sdp_csrf"]}


def _course_with_modules(client: TestClient, h: dict[str, str], names: list[str]) -> str:
    cid = client.post("/api/admin/courses", json={"title": "Editor Course"}, headers=h).json()[
        "course"
    ]["id"]
    for name in names:
        client.post(
            f"/api/admin/courses/{cid}/modules",
            json={
                "source_url": f"https://example.com/{name}",
                "title": name,
                "types": ["report"],
            },
            headers=h,
        )
    return cid


def _modules(client: TestClient, cid: str) -> list[dict]:
    return client.get(f"/api/admin/courses/{cid}").json()["course"]["modules"]


def test_rename_module_persists_title(client: TestClient, db_session: Session) -> None:
    h = _admin(client, db_session)
    cid = _course_with_modules(client, h, ["A"])
    mid = _modules(client, cid)[0]["id"]

    resp = client.patch(f"/api/admin/courses/modules/{mid}", json={"title": "Renamed"}, headers=h)
    assert resp.status_code == status.HTTP_200_OK
    assert resp.json()["title"] == "Renamed"
    assert _modules(client, cid)[0]["title"] == "Renamed"


def test_move_module_up_and_down_persists_order(client: TestClient, db_session: Session) -> None:
    h = _admin(client, db_session)
    cid = _course_with_modules(client, h, ["first", "second", "third"])
    third_id = _modules(client, cid)[2]["id"]

    body = client.post(
        f"/api/admin/courses/modules/{third_id}/move",
        json={"direction": "up"},
        headers=h,
    )
    assert body.status_code == status.HTTP_200_OK
    assert [m["title"] for m in body.json()["course"]["modules"]] == [
        "first",
        "third",
        "second",
    ]
    assert [m["title"] for m in _modules(client, cid)] == ["first", "third", "second"]

    client.post(
        f"/api/admin/courses/modules/{third_id}/move",
        json={"direction": "down"},
        headers=h,
    )
    assert [m["title"] for m in _modules(client, cid)] == ["first", "second", "third"]


def test_move_at_boundary_is_noop(client: TestClient, db_session: Session) -> None:
    h = _admin(client, db_session)
    cid = _course_with_modules(client, h, ["only-a", "only-b"])
    first_id = _modules(client, cid)[0]["id"]
    body = client.post(
        f"/api/admin/courses/modules/{first_id}/move",
        json={"direction": "up"},
        headers=h,
    )
    assert [m["title"] for m in body.json()["course"]["modules"]] == ["only-a", "only-b"]


def test_delete_module_cascades(client: TestClient, db_session: Session) -> None:
    h = _admin(client, db_session)
    cid = _course_with_modules(client, h, ["keep", "drop"])
    drop_id = _modules(client, cid)[1]["id"]

    resp = client.delete(f"/api/admin/courses/modules/{drop_id}", headers=h)
    assert resp.status_code == status.HTTP_204_NO_CONTENT
    assert [m["title"] for m in _modules(client, cid)] == ["keep"]
    assert db_session.get(Module, uuid.UUID(drop_id)) is None


def test_regenerate_bumps_revision_and_keeps_published(
    client: TestClient, db_session: Session
) -> None:
    h = _admin(client, db_session)
    cid = _course_with_modules(client, h, ["gen"])
    mid = _modules(client, cid)[0]["id"]

    module = db_session.get(Module, uuid.UUID(mid))
    assert module is not None
    report = next(a for a in module.artifacts if a.type is ArtifactType.report)

    # generate v1 and publish it
    orchestrator.run_artifact_generation(db_session, PROVIDER, report.id)
    db_session.expire_all()
    report = db_session.get(Artifact, report.id)
    assert report is not None
    report.published_version_id = report.current_version_id
    report.status = ArtifactStatus.published
    published_v = report.published_version_id
    db_session.flush()

    resp = client.post(f"/api/admin/courses/modules/{mid}/regenerate", headers=h)
    assert resp.status_code == status.HTTP_200_OK
    assert len(resp.json()["job_ids"]) == len(list(ArtifactType))

    # simulate the worker completing the report's fresh job
    job = db_session.scalars(
        select(GenerationJob)
        .where(GenerationJob.artifact_id == report.id)
        .where(GenerationJob.state == "queued")
        .order_by(GenerationJob.created_at.desc())
    ).first()
    assert job is not None
    orchestrator.run_artifact_generation(db_session, PROVIDER, report.id, job_id=job.id)

    db_session.expire_all()
    report = db_session.get(Artifact, report.id)
    assert report is not None
    assert report.published_version_id == published_v  # BR5 — untouched
    assert report.current_version_id != published_v
    assert sorted(v.revision for v in report.versions) == [1, 2]


def test_module_ops_require_admin(client: TestClient, db_session: Session) -> None:
    h = _admin(client, db_session)
    cid = _course_with_modules(client, h, ["x"])
    mid = _modules(client, cid)[0]["id"]
    client.cookies.clear()
    assert (
        client.patch(f"/api/admin/courses/modules/{mid}", json={"title": "y"}).status_code
        == status.HTTP_401_UNAUTHORIZED
    )
    assert (
        client.post(f"/api/admin/courses/modules/{mid}/regenerate").status_code
        == status.HTTP_401_UNAUTHORIZED
    )
