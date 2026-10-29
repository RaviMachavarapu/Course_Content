"""T025 — Recent Pipeline / View All + MCP status."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.cli import seed_admin
from app.models.module import Module


@pytest.fixture(autouse=True)
def _no_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.api.admin.courses._dispatch_all", lambda *a, **k: None)


def _admin(client: TestClient, db: Session) -> dict[str, str]:
    seed_admin(db, email="p@example.com", display_name="P", password="pipeline-admin-pw-1")
    db.flush()
    client.post(
        "/api/admin/auth/login", json={"email": "p@example.com", "password": "pipeline-admin-pw-1"}
    )
    return {"X-CSRF-Token": client.cookies["sdp_csrf"]}


def _make_module(client: TestClient, headers: dict[str, str], title: str) -> str:
    cid = client.post(
        "/api/admin/courses", json={"title": f"Course {title}"}, headers=headers
    ).json()["course"]["id"]
    return client.post(
        f"/api/admin/courses/{cid}/modules",
        json={"source_url": f"https://example.com/{title}", "title": title, "types": ["report"]},
        headers=headers,
    ).json()["module"]["id"]


def test_pipeline_lists_modules_with_dots(client: TestClient, db_session: Session) -> None:
    h = _admin(client, db_session)
    _make_module(client, h, "alpha")
    _make_module(client, h, "beta")

    resp = client.get("/api/admin/pipeline")
    assert resp.status_code == status.HTTP_200_OK
    body = resp.json()
    assert body["total"] == 2 and body["page"] == 1
    assert {r["module_title"] for r in body["rows"]} == {"alpha", "beta"}
    assert len(body["rows"][0]["dots"]) == 6
    assert body["rows"][0]["global_status"]


def test_pipeline_orders_newest_first(client: TestClient, db_session: Session) -> None:
    h = _admin(client, db_session)
    old = _make_module(client, h, "older")
    new = _make_module(client, h, "newer")
    for mid, when in (
        (old, dt.datetime(2020, 1, 1, tzinfo=dt.UTC)),
        (new, dt.datetime(2026, 1, 1, tzinfo=dt.UTC)),
    ):
        row = db_session.get(Module, uuid.UUID(mid))
        assert row is not None
        row.created_at = when
    db_session.flush()

    titles = [r["module_title"] for r in client.get("/api/admin/pipeline").json()["rows"]]
    assert titles == ["newer", "older"]


def test_pipeline_search_and_pagination(client: TestClient, db_session: Session) -> None:
    h = _admin(client, db_session)
    for name in ("neural-nets", "trees", "neural-embeddings"):
        _make_module(client, h, name)

    hits = client.get("/api/admin/pipeline", params={"q": "neural"}).json()
    assert hits["total"] == 2

    page1 = client.get("/api/admin/pipeline", params={"page_size": 2, "page": 1}).json()
    page2 = client.get("/api/admin/pipeline", params={"page_size": 2, "page": 2}).json()
    assert len(page1["rows"]) == 2 and len(page2["rows"]) == 1


def test_mcp_status_is_healthy_under_fixture(client: TestClient, db_session: Session) -> None:
    _admin(client, db_session)
    resp = client.get("/api/admin/mcp/status")
    assert resp.status_code == status.HTTP_200_OK
    body = resp.json()
    assert body["healthy"] is True
    assert "Fixture" in body["detail"]
    # T043 — system-health fields are always present, even with nothing recorded yet
    assert body["jobs_succeeded"] == 0
    assert body["jobs_failed"] == 0
    assert body["worker_last_heartbeat_at"] is None
    assert body["worker_heartbeat_stale"] is True


def test_mcp_status_requires_admin(client: TestClient) -> None:
    assert client.get("/api/admin/mcp/status").status_code == status.HTTP_401_UNAUTHORIZED


def test_pipeline_search_matches_pdf_name(client: TestClient, db_session: Session) -> None:
    from app.models.module_source_file import ModuleSourceFile

    h = _admin(client, db_session)
    with_pdf = _make_module(client, h, "alpha")
    _make_module(client, h, "beta")
    row = db_session.get(Module, uuid.UUID(with_pdf))
    assert row is not None
    row.source_url = None
    row.source_files.append(
        ModuleSourceFile(
            order_index=0,
            file_name="Thermodynamics.pdf",
            size_bytes=10,
            checksum_sha256="a" * 64,
            storage_key="module-sources/t.pdf",
            page_count=1,
        )
    )
    db_session.flush()

    body = client.get("/api/admin/pipeline", params={"q": "thermo"}).json()
    assert [r["module_title"] for r in body["rows"]] == ["alpha"]
    assert body["total"] == 1
    assert body["rows"][0]["source_url"] is None
    assert body["rows"][0]["source_files"][0]["file_name"] == "Thermodynamics.pdf"
