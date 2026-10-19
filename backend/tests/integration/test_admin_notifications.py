"""T030 — admin notifications feed (recent finished generation jobs)."""

from __future__ import annotations

import contextlib
import uuid

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.cli import seed_admin
from app.models.enums import ArtifactType
from app.models.module import Module
from app.pipeline import orchestrator
from app.pipeline.fixture import FixtureProvider

PROVIDER = FixtureProvider()


@pytest.fixture(autouse=True)
def _no_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.api.admin.courses._dispatch_all", lambda *a, **k: None)


def _admin(client: TestClient, db: Session) -> dict[str, str]:
    seed_admin(db, email="note@example.com", display_name="N", password="note-admin-pw-1")
    db.flush()
    client.post(
        "/api/admin/auth/login",
        json={"email": "note@example.com", "password": "note-admin-pw-1"},
    )
    return {"X-CSRF-Token": client.cookies["sdp_csrf"]}


def test_recent_lists_finished_jobs_newest_first(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = _admin(client, db_session)
    cid = client.post("/api/admin/courses", json={"title": "Notif"}, headers=h).json()["course"][
        "id"
    ]
    mid = client.post(
        f"/api/admin/courses/{cid}/modules",
        json={
            "source_url": "https://example.com/n",
            "title": "Notif Module",
            "types": ["report", "infographic"],
        },
        headers=h,
    ).json()["module"]["id"]

    module = db_session.get(Module, uuid.UUID(mid))
    assert module is not None
    report = next(a for a in module.artifacts if a.type is ArtifactType.report)
    infographic = next(a for a in module.artifacts if a.type is ArtifactType.infographic)

    # report succeeds
    orchestrator.run_artifact_generation(db_session, PROVIDER, report.id)

    # every type has a real renderer now — force infographic to fail so this
    # test still proves a failed job shows up correctly in the feed
    from app.pipeline.orchestrator import RENDERERS as live_renderers

    def _boom(*_a: object, **_k: object) -> None:
        raise RuntimeError("simulated infographic failure")

    monkeypatch.setattr(
        "app.pipeline.orchestrator.RENDERERS",
        {**live_renderers, ArtifactType.infographic: _boom},
    )
    with contextlib.suppress(Exception):
        orchestrator.run_artifact_generation(db_session, PROVIDER, infographic.id)
    db_session.flush()

    feed = client.get("/api/admin/jobs/recent", headers=h).json()["jobs"]
    assert len(feed) >= 2
    states = {j["artifact_type"]: j["state"] for j in feed}
    assert states["report"] == "succeeded"
    assert states["infographic"] == "failed"

    row = next(j for j in feed if j["artifact_type"] == "infographic")
    assert row["error_detail"]
    assert row["module_title"] == "Notif Module"
    assert row["module_id"] == mid
    assert row["course_id"] == cid

    # newest first
    times = [j["at"] for j in feed]
    assert times == sorted(times, reverse=True)


def test_recent_requires_admin(client: TestClient, db_session: Session) -> None:
    _admin(client, db_session)
    client.cookies.clear()
    assert client.get("/api/admin/jobs/recent").status_code == status.HTTP_401_UNAUTHORIZED
