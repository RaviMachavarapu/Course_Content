"""T014 — admin prompt Settings API (spec.md §5.4)."""

from __future__ import annotations

from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.cli import seed_admin
from app.models.enums import ARTIFACT_TYPES

ADMIN_PW = "prompt-admin-pw-1"


def _admin_client(client: TestClient, db_session: Session) -> dict[str, str]:
    seed_admin(db_session, email="pa@example.com", display_name="PA", password=ADMIN_PW)
    db_session.flush()
    client.post("/api/admin/auth/login", json={"email": "pa@example.com", "password": ADMIN_PW})
    return {"X-CSRF-Token": client.cookies["sdp_csrf"]}


def test_requires_admin(client: TestClient) -> None:
    assert client.get("/api/admin/prompts").status_code == status.HTTP_401_UNAUTHORIZED


def test_list_returns_six_active_templates(client: TestClient, db_session: Session) -> None:
    _admin_client(client, db_session)
    resp = client.get("/api/admin/prompts")
    assert resp.status_code == status.HTTP_200_OK
    templates = resp.json()["templates"]
    assert {t["artifact_type"] for t in templates} == {t.value for t in ARTIFACT_TYPES}
    assert all(t["is_active"] and t["version"] == 1 for t in templates)


def test_get_one_has_active_and_history(client: TestClient, db_session: Session) -> None:
    headers = _admin_client(client, db_session)
    client.put("/api/admin/prompts/quiz", json={"body": "v2 body"}, headers=headers)
    detail = client.get("/api/admin/prompts/quiz").json()
    assert detail["active"]["version"] == 2
    assert [h["version"] for h in detail["history"]] == [2, 1]


def test_put_creates_new_version(client: TestClient, db_session: Session) -> None:
    headers = _admin_client(client, db_session)
    resp = client.put("/api/admin/prompts/report", json={"body": "brand new"}, headers=headers)
    assert resp.status_code == status.HTTP_200_OK
    tpl = resp.json()["template"]
    assert tpl["version"] == 2 and tpl["body"] == "brand new" and tpl["is_active"] is True


def test_restore_default(client: TestClient, db_session: Session) -> None:
    headers = _admin_client(client, db_session)
    client.put("/api/admin/prompts/flashcards", json={"body": "custom"}, headers=headers)
    resp = client.post("/api/admin/prompts/flashcards/restore-default", headers=headers)
    assert resp.status_code == status.HTTP_200_OK
    assert "TODO(owner)" in resp.json()["template"]["body"]
    assert resp.json()["template"]["version"] == 3


def test_unknown_type_is_422(client: TestClient, db_session: Session) -> None:
    _admin_client(client, db_session)
    assert client.get("/api/admin/prompts/not_a_type").status_code == (
        status.HTTP_422_UNPROCESSABLE_ENTITY
    )


def test_put_requires_csrf(client: TestClient, db_session: Session) -> None:
    _admin_client(client, db_session)  # logged in, but no X-CSRF-Token header
    assert client.put(
        "/api/admin/prompts/quiz", json={"body": "x"}, headers={"X-CSRF-Token": ""}
    ).status_code == (status.HTTP_403_FORBIDDEN)
